"""Command hook for `claude -p --settings '<inline JSON>'` (hooks.md).

  python3 hook_logger.py <log path>

Claude Code runs it with the hook input (JSON) on stdin. It appends one
line to <log path>: {"epoch": <wall clock when the hook ran>, "input":
<the hook input as received>}. It prints nothing and exits 0, so it never
changes the run (hooks.md: exit 0 with no output adds nothing for Claude).
"""

import json
import sys
import time


def main():
    if len(sys.argv) != 2:
        sys.stderr.write("hook_logger: usage: hook_logger.py <log path>\n")
        sys.exit(2)
    raw = sys.stdin.read()
    now = time.time()
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = {"unparsed_stdin_len": len(raw)}
    with open(sys.argv[1], "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"epoch": now, "input": payload}, sort_keys=True, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
