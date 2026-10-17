"""Parse `claude mcp list` and `claude mcp get <name>` output.

Shapes observed on 2.1.296 (the docs give the status strings, not the line
layout):

  claude mcp list:
    <name>: <command or url> - <status>[ — <detail>]
  claude mcp get <name>:
    <name>:
      Scope: ...
      Status: <status>
      Issue: <detail>          (only on a failure)
"""

from harness.check import expect_in, expect_true
from harness.constants import LIST_DETAIL_SEPARATOR

LIST_STATUS_SEPARATOR = " - "

# The parsers read the raw output (a test may check it for a credential),
# but a failing check shows only the redacted text: `claude mcp get` prints
# a configured header in clear on 2.1.296 (observations.md, finding 5).


def list_line(*, output, server_name, registry):
    """The single `claude mcp list` line for this server."""
    prefix = server_name + ": "
    lines = [line for line in output.splitlines() if line.startswith(prefix)]
    expect_true(what="`claude mcp list` lines for %s" % server_name, expected="exactly 1 line",
                actual="%d line(s) in: %s" % (len(lines), registry.redact_text(text=output)), holds=len(lines) == 1)
    return lines[0]


def list_status(*, output, server_name, registry):
    """(status, detail) from `claude mcp list`. detail is None when absent.
    The caller logs them (redacted)."""
    line = list_line(output=output, server_name=server_name, registry=registry)
    expect_in(what="status separator in the `claude mcp list` line of %s" % server_name, item=LIST_STATUS_SEPARATOR,
              container=registry.redact_text(text=line))
    segment = line.split(LIST_STATUS_SEPARATOR, 1)[1]
    if LIST_DETAIL_SEPARATOR in segment:
        status, detail = segment.split(LIST_DETAIL_SEPARATOR, 1)
    else:
        status, detail = segment, None
    return status, detail


def get_fields(*, output, server_name, registry):
    """Indented `Key: value` fields of `claude mcp get <name>`."""
    lines = output.splitlines()
    header = server_name + ":"
    expect_in(what="`%s` header line in the `claude mcp get` output" % header, item=header,
              container=registry.redact_text(text=output).splitlines())
    fields = {}
    for line in lines[lines.index(header) + 1:]:
        if not line.startswith("  ") or line.startswith("    "):
            continue
        key, separator, value = line.strip().partition(": ")
        if separator:
            fields[key] = value
    return fields
