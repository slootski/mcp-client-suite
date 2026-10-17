# System under test: Claude Code 2.1.296, black-box, in a pinned image.
#
# Base image is pinned by its multi-arch INDEX digest (not a per-platform
# manifest digest), so the same line resolves on linux/arm64 and linux/amd64.
# node:22-bookworm-slim, index digest read with
# `docker buildx imagetools inspect node:22-bookworm-slim` on 2026-10-17.
# The pin is written once, here, and recorded in every run.json via
# SUITE_BASE_IMAGE (doc 11: run.json carries the image digest).
ARG BASE_IMAGE=node:22-bookworm-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392
FROM ${BASE_IMAGE}
ARG BASE_IMAGE

# UTF-8 locale: the `claude mcp list` status glyphs (✔ ✘ !) must decode cleanly.
ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DISABLE_AUTOUPDATER=1 \
    SUITE_BASE_IMAGE=${BASE_IMAGE}

# bubblewrap: on Linux, CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1 makes every claude
# command exit 1 when no bwrap binary is found ("bubblewrap is required for
# subprocess env scrubbing and isolation"), so the scrub test (D23/T11) needs
# it installed. What was tested (evidence/2026-10-17-bwrap-probe.sh, output
# in evidence/2026-10-17-bwrap-probe.txt): for `claude mcp add` / `claude
# mcp list` and the stdio MCP spawns they make, with the `sandbox` setting
# off (the default), 2.1.296 checks that bwrap exists but does not run it (a
# logging shim in its place was never called, under the scrub or under
# CLAUDE_CODE_MCP_ALLOWLIST_ENV=1, which does not need bwrap at all). So
# those tests need no extra container privileges. Not tested: Bash tool
# subprocesses (env-vars.md:567 scopes the PID-namespace isolation to
# them) and runs with `sandbox` on. Exact Debian bookworm version, same on
# arm64 and amd64.
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates \
      bubblewrap=0.8.0-2+deb12u1 \
 && rm -rf /var/lib/apt/lists/*

# Test runner in its own venv, exact versions.
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir pytest==8.4.2 pytest-timeout==2.4.0 pytest-html==4.1.1
ENV PATH="/opt/venv/bin:${PATH}"

# The system under test, at the exact version. The autoupdater is off (above).
RUN npm install -g @anthropic-ai/claude-code@2.1.296 \
 && npm cache clean --force

WORKDIR /suite
COPY . /suite

# Non-root. The `node` user (uid 1000) ships with the base image. run.sh
# passes --user <host uid>:<host gid> instead, so files in ./artifacts are
# owned by the host user. Any uid works: the suite writes only under /tmp
# (world-writable), and each test gives claude its own HOME there.
USER node
ENV HOME=/tmp

# Extra `docker run ... IMAGE <args>` are passed on to pytest (e.g. -m free).
ENTRYPOINT ["python3", "-m", "harness.entrypoint", "--staging-dir", "/tmp/suite-staging", "--artifact-dir", "/tmp/suite-out", "--"]
