#!/usr/bin/env bash
# bwrap probe: does Claude Code 2.1.296 run bubblewrap when it spawns a
# stdio MCP server under CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1 or
# CLAUDE_CODE_MCP_ALLOWLIST_ENV=1, with the `sandbox` setting off (the
# default: no settings file at all)?
#
#   ./run.sh -m free                          # or any run: builds mcp-client-suite:local
#   evidence/2026-10-17-bwrap-probe.sh > evidence/2026-10-17-bwrap-probe.txt
#
# Needs only Docker and the image ./run.sh builds. Free: no model call, no
# API key (none is passed in; the dummies below are made-up values, and the
# fake logs only env NAMES here). One throwaway container (--rm), started as
# root only to swap /usr/bin/bwrap for a logging shim; every `claude` command
# runs as the image's non-root user `node`, with a fresh HOME and
# CLAUDE_CONFIG_DIR per case and only the env given below (env -i).
#
# The shim appends its argv to a log, then execs the real bwrap. For each
# case the script prints the exit codes of `claude mcp add` and `claude mcp
# list`, the list line, whether the shim was called and its argv lines, and
# the env names the stdio fake (fakes/stdio_fake.py) got. A last pair of
# cases removes bwrap entirely, to show which settings need it present.
#
# What it can show: whether bwrap runs for `claude mcp add` / `claude mcp
# list` and the stdio spawn they make, in this setup. What it cannot show:
# Bash tool subprocesses (env-vars.md:567 scopes the PID-namespace isolation
# to those; no Bash tool runs here), and anything with `sandbox` turned on.
set -euo pipefail

IMAGE="mcp-client-suite:local"

docker image inspect "$IMAGE" >/dev/null

echo "# bwrap probe, $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "# image $IMAGE $(docker image inspect --format '{{.Id}}' "$IMAGE")"

docker run --rm -i --user 0 --entrypoint bash "$IMAGE" -s <<'INNER'
set -euo pipefail
PROBE=/tmp/bwrap-probe
mkdir -p "$PROBE"
chmod 0777 "$PROBE"

echo "claude --version: $(runuser -u node -- env -i PATH="$PATH" HOME=/tmp DISABLE_AUTOUPDATER=1 claude --version)"
REAL="$(command -v bwrap || true)"
if [ -z "$REAL" ]; then
  echo "bwrap: not found in the image; nothing to probe"
  exit 1
fi
echo "bwrap: $REAL ($(bwrap --version))"

# The shim: log argv (one line per call, each argument in []) to one fixed
# file (not taken from the env, which the client may strip), then run the
# real bwrap with the same arguments. Each case counts the lines it added.
CALLS="$PROBE/bwrap-calls.log"
touch "$CALLS"; chmod 0666 "$CALLS"
mv "$REAL" "$REAL.real"
cat > "$REAL" <<SHIM
#!/bin/sh
{ printf 'bwrap called (pid %s, uid %s):' "\$\$" "\$(id -u)"; for a in "\$@"; do printf ' [%s]' "\$a"; done; printf '\n'; } >> $CALLS
exec $REAL.real "\$@"
SHIM
chmod 0755 "$REAL"
echo "shim installed at $REAL (real binary moved to $REAL.real)"
# Positive control: the shim logs when it is run (as node, like claude).
runuser -u node -- bwrap --version >/dev/null
echo "shim self-test (\`bwrap --version\` as node): $(wc -l < "$CALLS" | tr -d ' ') call(s) logged: $(cat "$CALLS")"
: > "$CALLS"

# One case: fresh HOME/CLAUDE_CONFIG_DIR, `claude mcp add` of the stdio
# fake, then `claude mcp list`. $1 = label, rest = extra NAME=value env.
run_case() {
  local label="$1"; shift
  local dir="$PROBE/$label"
  mkdir -p "$dir/home" "$dir/config" "$dir/project"
  chown -R node:node "$dir"
  local before
  before="$(wc -l < "$CALLS" | tr -d ' ')"
  local base=(env -i PATH="$PATH" LANG=C.UTF-8 HOME="$dir/home" CLAUDE_CONFIG_DIR="$dir/config"
              DISABLE_AUTOUPDATER=1 DISABLE_TELEMETRY=1 DISABLE_ERROR_REPORTING=1 MCP_TIMEOUT=15000
              NPM_TOKEN=probe-dummy-npm-token MY_INHERITED_TOKEN=probe-dummy-own-token
              MY_PLAIN_SETTING=probe-plain-value "$@")
  echo
  echo "== case $label: extra env: ${*:-(none)}; settings: none (sandbox off, the default)"
  set +e
  (cd "$dir/project" && runuser -u node -- "${base[@]}" claude mcp add probe \
      --env FAKE_MODE=normal --env FAKE_LOG="$dir/wire.jsonl" --env FAKE_NAME=probe \
      --env FAKE_INIT_REPLY_DELAY_MS=0 --env FAKE_CANARY=probe-canary --env FAKE_TOOLSET=smoke \
      --env FAKE_PRESENCE_ONLY_ENV= --env MY_SERVICE_TOKEN=probe-dummy-service-token \
      -- python3 /suite/fakes/stdio_fake.py) > "$dir/add.out" 2>&1
  local add_rc=$?
  (cd "$dir/project" && runuser -u node -- "${base[@]}" claude mcp list) > "$dir/list.out" 2>&1
  local list_rc=$?
  set -e
  echo "claude mcp add: exit $add_rc; error line: $(grep -h 'error:' "$dir/add.out" | head -n 1 || echo '(none)')"
  echo "claude mcp list: exit $list_rc; probe line: $(grep -h '^probe' "$dir/list.out" || echo '(none)');" \
       "error line: $(grep -h 'error:' "$dir/list.out" | head -n 1 || echo '(none)')"
  local calls
  calls=$(( $(wc -l < "$CALLS" | tr -d ' ') - before ))
  echo "bwrap shim called: $calls time(s)"
  if [ "$calls" -gt 0 ]; then tail -n "$calls" "$CALLS" | sed 's/^/  /'; fi
  if [ -f "$dir/wire.jsonl" ]; then
    python3 - "$dir/wire.jsonl" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    starts = [json.loads(line) for line in handle if '"event": "started"' in line]
print("stdio fake spawns: %d" % len(starts))
for start in starts:
    print("  pid %s env names: %s" % (start["pid"], " ".join(sorted(start["env"]))))
PY
  else
    echo "stdio fake spawns: 0 (no wire log)"
  fi
}

run_case control
run_case scrub CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1
run_case allowlist CLAUDE_CODE_MCP_ALLOWLIST_ENV=1

# bwrap absent: which settings need the binary to exist at all?
rm -f "$REAL" "$REAL.real"
echo
echo "bwrap removed from the container (command -v bwrap: $(command -v bwrap || echo none))"
run_case scrub-no-bwrap CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1
run_case allowlist-no-bwrap CLAUDE_CODE_MCP_ALLOWLIST_ENV=1
INNER
