"""PreToolUse command hook for D23/T9 (hooks.md), given with `claude -p --settings '<inline JSON>'`.

  python3 guard_hook.py <log path> <mode> <target tool name> <reason>

Claude Code runs it with the hook input (JSON) on stdin. Every run appends one line to <log path>,
{"epoch": <wall clock>, "input": <hook input as received>, "action": <what this run did>}, BEFORE the
hook answers, so the log shows every call the hook saw.

For any tool other than <target tool name> it prints nothing and exits 0 (action "pass": hooks.md,
exit 0 with no output lets the call go on). For the target tool:

  deny  prints {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": <reason>}} and exits 0 (action "deny"; hooks.md "PreToolUse decision
        control").
  ask   the same with "ask" (action "ask"); hooks.md:1934: in `-p` no one can answer the prompt, so the call is
        denied and Claude reads the reason in the tool result.
  allow the same with "allow" (action "allow"); hooks.md:1933: "allow" skips the permission prompt.
  fail  prints nothing to stdout, one line to stderr, and exits 1 (action "exit1"): a non-blocking
        error, unless the handler sets `onFailure: "block"` (hooks.md "Block the action when a hook fails").
"""

import json
import sys
import time

TARGET_ACTIONS = {"deny": "deny", "ask": "ask", "allow": "allow", "fail": "exit1"}  # mode -> target tool action
MODES = tuple(TARGET_ACTIONS)
DECISION_ACTIONS = ("deny", "ask", "allow")  # actions answered with a permissionDecision
FAIL_EXIT_CODE = 1
USAGE_EXIT_CODE = 3  # not 2: exit 2 is a blocking error on PreToolUse


def main():
    if len(sys.argv) != 5 or sys.argv[2] not in MODES:
        sys.stderr.write("guard_hook: usage: guard_hook.py <log path> <%s> <target tool> <reason>\n" % "|".join(MODES))
        sys.exit(USAGE_EXIT_CODE)
    log_path, mode, target, reason = sys.argv[1:5]
    raw = sys.stdin.read()
    now = time.time()
    payload = json.loads(raw)
    is_target = payload["tool_name"] == target
    action = TARGET_ACTIONS[mode] if is_target else "pass"
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"epoch": now, "input": payload, "action": action}, sort_keys=True,
                                ensure_ascii=False) + "\n")
    if action in DECISION_ACTIONS:
        sys.stdout.write(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": action, "permissionDecisionReason": reason}}))
        sys.exit(0)
    if action == "exit1":
        sys.stderr.write("guard_hook: failing on purpose for %s\n" % target)
        sys.exit(FAIL_EXIT_CODE)
    sys.exit(0)


if __name__ == "__main__":
    main()
