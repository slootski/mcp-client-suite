#!/usr/bin/env bash
# One command: build the image, run the suite, exit with pytest's exit code.
#
#   ./run.sh                 # every test (model tests skip if no key)
#   ./run.sh -m free         # extra arguments go to pytest
#
# Needs only Docker. ANTHROPIC_API_KEY is read from this shell when set; it
# may be unset, and the free tests still run.
#
# The key never goes into the container config: no `docker run -e`, no
# --env-file, so `docker inspect` cannot show it, also not for a container
# a `kill -9` of this script leaves behind. Instead the key is written to a
# 0600 file in a private temp dir, `docker cp`ed into the created container
# (KEY_IN_CONTAINER, same path as harness/constants.py
# API_KEY_FILE_IN_CONTAINER) before `docker start`, and the host file is
# deleted at once. The entrypoint reads the file, deletes it, and gives the
# key to the pytest process only (harness/entrypoint.py).
#
# Artifacts: each run gets a fresh folder ./artifacts/<run-id>/ (junit.xml, cost.json,
# secret-scan.json, per-test run.json, wire logs, command transcripts), and
# ./artifacts/latest is a plain file holding the newest complete <run-id>.
# Nothing is bind-mounted: the container writes inside itself and this
# script copies the result out with `docker cp` once it exits. (A bind mount
# of a just-created host folder fails intermittently on Docker Desktop, and
# `docker cp` also leaves the files owned by the host user.) Nothing is
# deleted; old runs stay until you remove them.
set -euo pipefail

cd "$(dirname "$0")"
SUITE_DIR="$PWD"
IMAGE="mcp-client-suite:local"
CONTAINER_OUT="/tmp/suite-out"
KEY_IN_CONTAINER="/tmp/suite-api-key"
# The uid the image runs as when the host user is root (Dockerfile: USER node).
IMAGE_USER_UID=1000
IMAGE_USER_GID=1000

if [ -L artifacts ]; then
  echo "run.sh: ./artifacts is a symlink; refusing to write through it" >&2
  exit 2
fi

docker build -t "$IMAGE" .
IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$IMAGE")"

# Run as the host user (any uid works: the suite writes only under /tmp).
# A root host keeps the image's non-root user, uid 1000.
USER_ARGS=()
if [ "$(id -u)" -ne 0 ]; then
  USER_ARGS=(--user "$(id -u):$(id -g)")
fi

KEY_ARGS=()
KEY_DIR=""
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  KEY_ARGS=(-e SUITE_API_KEY_FILE="$KEY_IN_CONTAINER")
fi

# Log times (harness/log_format.py) in the host's time zone: the zone name
# from /etc/localtime (macOS and most Linux), UTC when it has none.
HOST_TZ="$(readlink /etc/localtime 2>/dev/null | sed -n 's#.*/zoneinfo/##p')"
if [ -z "$HOST_TZ" ]; then HOST_TZ="UTC"; fi

CID=""
cleanup() {
  if [ -n "$KEY_DIR" ]; then rm -rf "$KEY_DIR"; fi
  if [ -n "$CID" ]; then docker rm -f "$CID" >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT

CID="$(docker create \
  ${USER_ARGS[@]+"${USER_ARGS[@]}"} \
  ${KEY_ARGS[@]+"${KEY_ARGS[@]}"} \
  -e SUITE_IMAGE_ID="$IMAGE_ID" \
  -e TZ="$HOST_TZ" \
  "$IMAGE" "$@")"

if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  # Private dir + 0600 file, owned by the uid the container runs as, so
  # `docker cp -a` (keeps owner and mode) gives that user, and only it, read
  # access. The value goes through printf (a shell builtin), never argv.
  KEY_DIR="$(umask 077 && mktemp -d)"
  (umask 077 && printf '%s' "$ANTHROPIC_API_KEY" > "$KEY_DIR/key")
  if [ "$(id -u)" -eq 0 ]; then
    chown "$IMAGE_USER_UID:$IMAGE_USER_GID" "$KEY_DIR/key"
  fi
  # Residual risk (docs/flake-policy.md, "Residual risks"): a `kill -9` of
  # this script after this `docker cp` and before `docker start` skips the
  # cleanup trap and leaves the key file in the created container. `docker
  # inspect` does not show it, but `docker cp "$CID:$KEY_IN_CONTAINER" -`
  # can read it until the container is removed (`docker rm`). The window is
  # this one `docker cp` call; it is not closed.
  docker cp -a "$KEY_DIR/key" "$CID:$KEY_IN_CONTAINER"
  rm -rf "$KEY_DIR"
  KEY_DIR=""
fi

set +e
docker start --attach "$CID"
rc=$?
set -e

mkdir -p artifacts
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
RUN_DIR="$SUITE_DIR/artifacts/$RUN_ID"
mkdir "$RUN_DIR"
# `latest` moves only to a complete run: secret-scan.json is written by the
# entrypoint after pytest, so a run without it (entrypoint crash, failed
# copy) keeps its folder for debugging but does not become `latest`.
if docker cp "$CID:$CONTAINER_OUT/." "$RUN_DIR/" && [ -f "$RUN_DIR/secret-scan.json" ]; then
  printf '%s\n' "$RUN_ID" > artifacts/latest
else
  echo "run.sh: no complete artifacts (copy failed or no secret-scan.json); artifacts/latest not updated" >&2
  if [ "$rc" -eq 0 ]; then rc=1; fi
fi
echo "run.sh: suite exit code $rc (artifacts in ./artifacts/$RUN_ID)"
exit "$rc"
