"""Small Streamable HTTP MCP server (legacy era, JSON replies only, no SSE).

It serves one MCP endpoint path. It answers:
  POST initialize, notifications/*, ping, tools/list, tools/call -> JSON
  POST any other method (server/discover included)               -> 400 + JSON-RPC -32601
  GET / DELETE on the MCP path                                   -> 405
  GET OAuth discovery documents (auth-mode require only)         -> 200
  any other path                                                 -> 404

Auth check (scripted by --auth-mode):
  require       the Authorization header must equal the value of the env var
           FAKE_EXPECTED_AUTHORIZATION. Missing or wrong -> HTTP 401 on every
           request, before any method is looked at. The fake also serves
           the OAuth discovery documents a spec-compliant protected MCP
           server publishes (MCP 2025-11-25 authorization: servers MUST
           implement RFC 9728 Protected Resource Metadata):
             /.well-known/oauth-protected-resource<path>  (RFC 9728)
             /.well-known/oauth-authorization-server      (RFC 8414)
           No authorization, token or registration endpoint is implemented:
           a health check must stop at "needs authentication".
  require_bare  same 401 check, but NO discovery documents: every other
                path is 404. A non-compliant server that answers a bare 401.
  off           no check, no discovery documents.

Every HTTP request is logged to the JSONL wire log: method, path (without
the query string), the query parameters as name -> sha8+length, header names
with sha8+length of each value (never the value), the Authorization header
split into its scheme (in clear, e.g. "Bearer") and the sha8+length of the
credential after it, the auth verdict, the parsed JSON-RPC body, and the HTTP
status sent back. A query string or credential can hold a secret, so neither
is ever logged as text.

CLI (every argument is required):
  --host HOST --port PORT (0 = pick a free port) --path /mcp
  --log FILE --ready-file FILE --name LABEL --auth-mode {require,require_bare,off}
The ready file is written once the socket listens: {"port": N, "pid": N}.
"""

import argparse
import hmac
import json
import os
import signal
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wirelog import WireLog, fingerprint, fingerprint_mapping  # noqa: E402

AUTH_MODES = ("require", "require_bare", "off")
CHECKING_MODES = ("require", "require_bare")  # modes that check Authorization
DISCOVERY_MODES = ("require",)  # modes that publish OAuth discovery documents
EXPECTED_AUTH_ENV = "FAKE_EXPECTED_AUTHORIZATION"
CLEAR_AUTH_SCHEMES = ("Bearer", "Basic")  # safe to log as text

LEGACY_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
NEWEST_LEGACY_VERSION = LEGACY_VERSIONS[0]
FAKE_VERSION = "0.1.0"

METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
PARSE_ERROR = -32700

PROTECTED_RESOURCE_PREFIX = "/.well-known/oauth-protected-resource"
AUTHORIZATION_SERVER_PATH = "/.well-known/oauth-authorization-server"

# Free of anything token-shaped: Claude Code redacts credential-like text
# from the failure detail, and the tests look for this phrase.
UNAUTHORIZED_DESCRIPTION = "fake mcp server rejected the request authorization"

ECHO_TOOL = {
    "name": "echo",
    "description": "Return the given text unchanged.",
    "inputSchema": {
        "type": "object",
        "properties": {"text": {"type": "string", "description": "Text to echo back."}},
        "required": ["text"],
        "additionalProperties": False,
    },
}


def parse_args(*, argv):
    parser = argparse.ArgumentParser(description="HTTP fake MCP server")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--path", required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--ready-file", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--auth-mode", required=True, choices=AUTH_MODES)
    return parser.parse_args(argv)


def result_reply(*, request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error_reply(*, request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def answer(*, name, message):
    """Return (http_status, reply_or_None) for one JSON-RPC message."""
    if not isinstance(message, dict) or "method" not in message:
        return 202, None  # a response from the client: accept, no body
    method = message["method"]
    if "id" not in message:
        return 202, None  # a notification, e.g. notifications/initialized
    request_id = message["id"]

    if method == "initialize":
        if "params" not in message or "protocolVersion" not in message["params"]:
            return 200, error_reply(request_id=request_id, code=INVALID_PARAMS, message="initialize needs params.protocolVersion")
        asked = message["params"]["protocolVersion"]
        version = asked if asked in LEGACY_VERSIONS else NEWEST_LEGACY_VERSION
        return 200, result_reply(
            request_id=request_id,
            result={
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": name, "version": FAKE_VERSION},
            },
        )
    if method == "ping":
        return 200, result_reply(request_id=request_id, result={})
    if method == "tools/list":
        return 200, result_reply(request_id=request_id, result={"tools": [ECHO_TOOL]})
    if method == "tools/call":
        if "params" not in message or "name" not in message["params"]:
            return 200, error_reply(request_id=request_id, code=INVALID_PARAMS, message="tools/call needs params.name")
        params = message["params"]
        if params["name"] != ECHO_TOOL["name"]:
            return 200, error_reply(request_id=request_id, code=INVALID_PARAMS, message="Unknown tool: %s" % params["name"])
        if "arguments" not in params or "text" not in params["arguments"]:
            return 200, error_reply(request_id=request_id, code=INVALID_PARAMS, message="echo needs arguments.text")
        return 200, result_reply(
            request_id=request_id,
            result={"content": [{"type": "text", "text": params["arguments"]["text"]}], "isError": False},
        )
    # server/discover and anything else unknown. 400 + a non-modern JSON-RPC
    # error is the legacy signal the 2026-07-28 HTTP backward-compat rule names.
    return 400, error_reply(request_id=request_id, code=METHOD_NOT_FOUND, message="Method not found: %s" % method)


def make_handler(*, log, name, mcp_path, auth_mode, expected_auth):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "fake-mcp-http"
        sys_version = ""

        def log_message(self, format, *args):  # noqa: A002 - stdlib signature
            return  # the wire log replaces the stderr access log

        def _headers_fingerprint(self):
            return fingerprint_mapping(mapping={k.lower(): v for k, v in self.headers.items()})

        def _auth_verdict(self):
            if auth_mode not in CHECKING_MODES:
                return "not_checked"
            if "Authorization" not in self.headers:
                return "missing"
            if hmac.compare_digest(self.headers["Authorization"].encode("utf-8"), expected_auth.encode("utf-8")):
                return "match"
            return "mismatch"

        def _send_json(self, *, status, payload, extra_headers):
            body = b"" if payload is None else json.dumps(payload).encode("utf-8")
            self.send_response(status)
            for key in extra_headers:
                self.send_header(key, extra_headers[key])
            if payload is not None:
                self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def _authorization_parts(self):
            """{scheme, credential: {sha8, len}} of the Authorization header,
            or None when the request has none. The scheme is logged in clear
            only when it is a known word (CLEAR_AUTH_SCHEMES); otherwise the
            whole value counts as the credential and scheme is None."""
            if "Authorization" not in self.headers:
                return None
            value = self.headers["Authorization"].strip()
            scheme, _separator, credential = value.partition(" ")
            if scheme not in CLEAR_AUTH_SCHEMES:
                return {"scheme": None, "credential": fingerprint(value=value)}
            return {"scheme": scheme, "credential": fingerprint(value=credential.strip())}

        def _log(self, *, verdict, body, status):
            parts = urlsplit(self.path)
            log.write(
                event="http_request",
                fields={
                    "method": self.command,
                    "path": parts.path,
                    "query": [
                        {"name": name, "value": fingerprint(value=value)}
                        for name, value in parse_qsl(parts.query, keep_blank_values=True)
                    ],
                    "headers": self._headers_fingerprint(),
                    "authorization": self._authorization_parts(),
                    "auth": verdict,
                    "body": body,
                    "status": status,
                },
            )

        def _read_body(self):
            if "Content-Length" not in self.headers:
                return None, None  # the request has no body
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            if not raw:
                return None, None
            text = raw.decode("utf-8", errors="replace")
            try:
                return json.loads(text), None
            except ValueError:
                return None, fingerprint(value=text)

        def _reject_unauthorized(self, *, verdict, body):
            self._log(verdict=verdict, body=body, status=401)
            self._send_json(
                status=401,
                payload={"error": "invalid_token", "error_description": UNAUTHORIZED_DESCRIPTION},
                extra_headers={"WWW-Authenticate": 'Bearer realm="fake-mcp", error="invalid_token"'},
            )

        def _discovery_document(self):
            """Return the OAuth discovery document for this path, or None."""
            if auth_mode not in DISCOVERY_MODES:
                return None
            origin = "http://" + self.headers["Host"]
            path = self.path.split("?")[0]
            if path == PROTECTED_RESOURCE_PREFIX + mcp_path:
                return {"resource": origin + mcp_path, "authorization_servers": [origin]}
            if path == AUTHORIZATION_SERVER_PATH:
                return {
                    "issuer": origin,
                    "authorization_endpoint": origin + "/authorize",
                    "token_endpoint": origin + "/token",
                    "registration_endpoint": origin + "/register",
                    "response_types_supported": ["code"],
                    "grant_types_supported": ["authorization_code", "refresh_token"],
                    "code_challenge_methods_supported": ["S256"],
                    "token_endpoint_auth_methods_supported": ["none"],
                }
            return None

        def _not_mcp_path(self, *, verdict, body):
            document = self._discovery_document() if self.command == "GET" else None
            if document is not None:
                self._log(verdict=verdict, body=body, status=200)
                self._send_json(status=200, payload=document, extra_headers={})
                return
            self._log(verdict=verdict, body=body, status=404)
            self._send_json(status=404, payload={"error": "not_found"}, extra_headers={})

        def do_POST(self):  # noqa: N802 - stdlib name
            parsed, unparsed = self._read_body()
            body_for_log = parsed if unparsed is None else {"unparsed": unparsed}
            verdict = self._auth_verdict()
            if self.path.split("?")[0] != mcp_path:
                self._not_mcp_path(verdict=verdict, body=body_for_log)
                return
            if verdict in ("missing", "mismatch"):
                self._reject_unauthorized(verdict=verdict, body=body_for_log)
                return
            if parsed is None:
                self._log(verdict=verdict, body=body_for_log, status=400)
                self._send_json(
                    status=400,
                    payload=error_reply(request_id=None, code=PARSE_ERROR, message="Parse error"),
                    extra_headers={},
                )
                return
            if isinstance(parsed, list):
                replies = []
                status = 202
                for item in parsed:
                    item_status, reply = answer(name=name, message=item)
                    if reply is not None:
                        replies.append(reply)
                        status = 200
                self._log(verdict=verdict, body=body_for_log, status=status)
                self._send_json(status=status, payload=replies if replies else None, extra_headers={})
                return
            status, reply = answer(name=name, message=parsed)
            self._log(verdict=verdict, body=body_for_log, status=status)
            self._send_json(status=status, payload=reply, extra_headers={})

        def _no_body_method(self):
            verdict = self._auth_verdict()
            if self.path.split("?")[0] != mcp_path:
                self._not_mcp_path(verdict=verdict, body=None)
                return
            if verdict in ("missing", "mismatch"):
                self._reject_unauthorized(verdict=verdict, body=None)
                return
            self._log(verdict=verdict, body=None, status=405)
            self._send_json(status=405, payload=None, extra_headers={"Allow": "POST"})

        def do_GET(self):  # noqa: N802
            self._no_body_method()

        def do_DELETE(self):  # noqa: N802
            self._no_body_method()

    return Handler


def main():
    args = parse_args(argv=sys.argv[1:])
    log = WireLog(path=args.log, source=args.name)
    started_fields = {"path": args.path, "auth_mode": args.auth_mode}
    if args.auth_mode in CHECKING_MODES:
        if EXPECTED_AUTH_ENV not in os.environ:
            sys.stderr.write("http_fake: --auth-mode %s needs env %s\n" % (args.auth_mode, EXPECTED_AUTH_ENV))
            sys.exit(2)
        expected_auth = os.environ[EXPECTED_AUTH_ENV]
        started_fields["expected_authorization"] = fingerprint(value=expected_auth)
    else:
        expected_auth = None  # explicit: mode "off" never compares a header
    handler = make_handler(
        log=log, name=args.name, mcp_path=args.path, auth_mode=args.auth_mode, expected_auth=expected_auth
    )
    server = ThreadingHTTPServer((args.host, args.port), handler)
    server.daemon_threads = True
    port = server.server_address[1]

    def on_signal(signum, frame):
        log.write(event="signal", fields={"signal": signal.Signals(signum).name})
        sys.exit(0)

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    log.write(
        event="started",
        fields=dict(started_fields, port=port),
    )
    tmp = args.ready_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump({"port": port, "pid": os.getpid()}, handle)
    os.replace(tmp, args.ready_file)
    server.serve_forever()


if __name__ == "__main__":
    main()
