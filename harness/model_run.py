"""Run `claude -p` against fake MCP servers and parse its stream-json output.

Every run (doc 11, PINNED ENV):
  claude -p <prompt> --output-format stream-json --verbose
         --model <MODEL_ID> --max-turns <MAX_TURNS> --max-budget-usd <cap>
         --permission-mode default --permission-prompts none
         --strict-mcp-config --debug=mcp --debug-file <artifact dir>/debug-<label>.log
         [extra args of the test, e.g. --settings <inline JSON> for hooks]
         --mcp-config <artifact dir>/mcp-config-<label>.json
         --allowedTools <rules: mcp__<server>__*[,...] (doc 11), other rules in D23/T10>
The prompt comes right after -p: --mcp-config and --allowedTools are
variadic (`<configs...>`, `<tools...>`) and would swallow a prompt placed
after them. The env is the sandbox's: a fresh CLAUDE_CONFIG_DIR and HOME,
the model pins (harness/constants.py MODEL_ENV_PINS) and the API key. The
container runs as a non-root user; bypass mode is never used.

Stream shapes used (headless.md "Read session metadata", "Fail CI when a
plugin or MCP server doesn't load"; agent-sdk__mcp.md:723):
  {"type":"system","subtype":"init","model":..,"tools":[..],
   "mcp_servers":[{"name","status"}], "mcp_server_errors":[{"name","type","message"}] (omitted when empty)}
  {"type":"assistant","message":{"content":[{"type":"text"|"tool_use",..}]}}
      tool_use: {"id","name","input"}
  {"type":"user","message":{"content":[{"type":"tool_result","tool_use_id","content","is_error"}]}}
  {"type":"result","subtype","is_error","num_turns","result","total_cost_usd","permission_denials"}  (last line)
"""

import json
import os
from dataclasses import dataclass

from harness.check import got, step
from harness.claude_cli import OUTPUT_PREVIEW_HIDDEN, run_claude
from harness.cost_ledger import SOURCE_EXCEPTION, SOURCE_NO_RESULT, SOURCE_RESULT, SOURCE_RESULT_WITHOUT_COST


INIT_SUBTYPE = "init"
TOTAL_COST_KEY = "total_cost_usd"


@dataclass(frozen=True)
class ToolUse:
    index: int  # line number of the event in the stream
    id: str
    name: str
    input: dict


@dataclass(frozen=True)
class ToolResult:
    index: int
    tool_use_id: str
    content: object  # a string or a list of content blocks, as streamed
    is_error: object  # True / False as streamed, None when the block has no is_error key (seen on success)

    def text(self):
        """All text of the content, joined (a string content is returned as is)."""
        if isinstance(self.content, str):
            return self.content
        return "".join(block["text"] for block in self.content if block["type"] == "text")


@dataclass(frozen=True)
class Stream:
    events: list
    unparsed_lines: list
    init: dict  # None when the stream has no system/init event
    tool_uses: list
    tool_results: list
    assistant_text_indexes: list  # indexes of assistant events that carry a text block
    result: dict  # None when the stream has no result event

    def tool_uses_named(self, *, name):
        return [use for use in self.tool_uses if use.name == name]

    def result_for(self, *, tool_use_id):
        return [res for res in self.tool_results if res.tool_use_id == tool_use_id]

    def events_of(self, *, event_type, subtype):
        return [e for e in self.events if e["type"] == event_type and "subtype" in e and e["subtype"] == subtype]


def parse_stream(*, text):
    """Parse newline-delimited stream-json. A line that is not JSON is kept
    in unparsed_lines (the caller decides; with --verbose none is expected)."""
    events = []
    unparsed = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except ValueError:
            unparsed.append(line)
    init = None
    result = None
    tool_uses = []
    tool_results = []
    text_indexes = []
    for index, event in enumerate(events):
        kind = event["type"]
        if kind == "system" and "subtype" in event and event["subtype"] == INIT_SUBTYPE and init is None:
            init = event
        elif kind == "result":
            result = event
        elif kind in ("assistant", "user"):
            content = event["message"]["content"]
            if isinstance(content, str):
                continue
            for block in content:
                if block["type"] == "tool_use":
                    tool_uses.append(ToolUse(index=index, id=block["id"], name=block["name"], input=block["input"]))
                elif block["type"] == "tool_result":
                    tool_results.append(
                        ToolResult(
                            index=index, tool_use_id=block["tool_use_id"], content=block["content"],
                            is_error=block["is_error"] if "is_error" in block else None,
                        )
                    )
                elif block["type"] == "text" and kind == "assistant":
                    text_indexes.append(index)
    return Stream(
        events=events, unparsed_lines=unparsed, init=init, tool_uses=tool_uses, tool_results=tool_results,
        assistant_text_indexes=text_indexes, result=result,
    )


def stdio_server_entry(*, fake_script, python, fake_env):
    """One --mcp-config entry for the stdio fake. `type` is given
    explicitly (an entry with no `type` is also read as stdio, mcp.md:85)."""
    return {"type": "stdio", "command": python, "args": [fake_script], "env": dict(fake_env)}


def write_mcp_config(*, path, servers):
    """servers: {name: entry}. Written as {"mcpServers": servers}."""
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"mcpServers": servers}, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return path


def allowed_tools_for(*, servers):
    """doc 11: --allowedTools "mcp__<server>__*" for the test's servers."""
    return ",".join("mcp__%s__*" % name for name in servers)


def print_args(*, prompt, model, max_turns, max_budget_usd, mcp_config_path, debug_file, allowed_tools,
               extra_args):
    """extra_args (e.g. ["--settings", <inline JSON>]) go before the two
    variadic flags, so neither can read them as one of its values."""
    return [
        "-p", prompt,
        "--output-format", "stream-json",
        "--verbose",
        "--model", model,
        "--max-turns", str(max_turns),
        "--max-budget-usd", "%.2f" % max_budget_usd,
        "--permission-mode", "default",
        "--permission-prompts", "none",
        "--strict-mcp-config",
        "--debug=mcp",
        "--debug-file", debug_file,
    ] + list(extra_args) + [
        "--mcp-config", mcp_config_path,
        "--allowedTools", allowed_tools,
    ]


@dataclass(frozen=True)
class ModelRun:
    label: str
    cli: object  # harness.claude_cli.CliResult
    stream: Stream
    debug_file: str
    stream_file: str
    charged_usd: float


def run_print(*, sandbox, env, ledger, test_id, label, prompt, model, max_turns, max_budget_usd, servers,
              allowed_tools, timeout_s, extra_args):
    """Write the --mcp-config, run `claude -p` with `env` (the sandbox's, or
    a copy with a fresh CLAUDE_CONFIG_DIR for a retry), save the stream,
    charge the ledger. servers: {name: --mcp-config entry}; allowed_tools:
    the --allowedTools value (allowed_tools_for(servers=[...]) gives the
    doc 11 default, `mcp__<name>__*` per server; D23/T10 passes other
    rules); extra_args: more arguments ([] for none). Returns a ModelRun.

    Charging, exactly once per run:
      * a result event with total_cost_usd: that value;
      * no result event (crash, budget stop): the per-run cap;
      * a result event WITHOUT total_cost_usd: the per-run cap, then the
        test fails (the spend is unknown, and headless.md documents the key);
      * any exception between the start of the run and the charge (the CLI
        timeout, a pytest-timeout or Ctrl-C, a parse error): the per-run
        cap, then the exception goes on (BaseException, so pytest's
        outcome exceptions and KeyboardInterrupt are covered too)."""
    ledger.check_before_run(test_id=test_id)
    step(text="%s: write --mcp-config with servers %s, run claude -p (model %s, allowedTools %s, extra args %d)" % (
        label, sorted(servers), model, allowed_tools, len(extra_args)))
    config_path = write_mcp_config(
        path=os.path.join(sandbox.artifact_dir, "mcp-config-%s.json" % label), servers=servers
    )
    debug_file = os.path.join(sandbox.artifact_dir, "debug-%s.log" % label)
    args = print_args(
        prompt=prompt, model=model, max_turns=max_turns, max_budget_usd=max_budget_usd,
        mcp_config_path=config_path, debug_file=debug_file,
        allowed_tools=allowed_tools, extra_args=extra_args,
    )
    try:
        cli = run_claude(args=args, env=env, cwd=sandbox.project_dir, timeout_s=timeout_s,
                         command_log=sandbox.command_log, show_output_preview=OUTPUT_PREVIEW_HIDDEN)
        stream = parse_stream(text=cli.stdout)
        stream_file = os.path.join(sandbox.artifact_dir, "stream-%s.jsonl" % label)
        with open(stream_file, "w", encoding="utf-8") as handle:
            handle.write(sandbox.registry.redact_text(text=cli.stdout))
        cost_missing = stream.result is not None and TOTAL_COST_KEY not in stream.result
        cost = stream.result[TOTAL_COST_KEY] if stream.result is not None and not cost_missing else None
    except BaseException:
        ledger.charge(test_id=test_id, label=label, total_cost_usd=None, source=SOURCE_EXCEPTION)
        raise
    if cost_missing:
        ledger.charge(test_id=test_id, label=label, total_cost_usd=None, source=SOURCE_RESULT_WITHOUT_COST)
        raise AssertionError("%s: key %s in the result event: Expected: present (headless.md). Actual: absent, keys %s; "
                             "charged the per-run cap." % (label, TOTAL_COST_KEY, sorted(stream.result)))
    source = SOURCE_RESULT if cost is not None else SOURCE_NO_RESULT
    got(what="%s stream" % label, value="%d events, tool_use %s, %d tool_result, result event %s, total_cost_usd %s" % (
        len(stream.events), [use.name for use in stream.tool_uses], len(stream.tool_results),
        "present" if stream.result is not None else "MISSING", cost))
    charged = ledger.charge(test_id=test_id, label=label, total_cost_usd=cost, source=source)
    return ModelRun(
        label=label, cli=cli, stream=stream, debug_file=debug_file, stream_file=stream_file, charged_usd=charged
    )
