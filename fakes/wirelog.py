"""Wire log shared by the fake MCP servers.

Every record is one JSON object per line (JSONL) with a wall-clock timestamp.
The log is a file, separate from the fake's stdout, so it records what the
client sent no matter what the fake answers.

Secrets rule: env values and HTTP header values are never written. Only a
short SHA-256 prefix and the length are logged, so a test can compare an
expected value by hash without the value ever reaching disk. A value that
must not even leave a fingerprint (the live API key) is logged as
presence() only: {"set": true}.
"""

import hashlib
import json
import os
import threading
import time
from datetime import datetime, timezone

HASH_PREFIX_CHARS = 8


def fingerprint(*, value):
    """Return {sha8, len} for a string value. Never the value itself."""
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return {"sha8": digest[:HASH_PREFIX_CHARS], "len": len(value)}


def presence():
    """{"set": true}: the form of a value whose fingerprint must not be
    written either (the live API key). Says only that the name was set."""
    return {"set": True}


def fingerprint_mapping(*, mapping):
    """Fingerprint every value of a str->str mapping, keyed by name."""
    return {name: fingerprint(value=mapping[name]) for name in sorted(mapping)}


class WireLog:
    """Append-only JSONL writer, safe to call from several threads."""

    def __init__(self, *, path, source):
        self._path = path
        self._source = source
        self._lock = threading.Lock()
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)

    def write(self, *, event, fields):
        now = time.time()
        record = {
            "ts": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(timespec="microseconds"),
            "epoch": now,
            "mono": time.monotonic(),
            "source": self._source,
            "pid": os.getpid(),
            "event": event,
        }
        record.update(fields)
        line = json.dumps(record, sort_keys=True, ensure_ascii=False)
        with self._lock:
            with open(self._path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
