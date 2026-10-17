"""Keep test credentials out of artifacts.

Two layers:
  * argv: the value after --env / --header is replaced by its hash + length,
    whatever it holds (the name stays readable);
  * text: every value registered in a SecretRegistry (the bearer tokens a
    test generates) is replaced wherever it appears, e.g. in the output of
    `claude mcp get`, which prints configured headers (see observations.md).
    A value registered presence_only (the live API key) is replaced by
    PRESENCE_ONLY_PLACEHOLDER, with no hash, also inside an argv flag value.
After a test, scan_dir() proves no registered value is left on disk.
copy_tree_redacted() never copies a file named in withheld_names (the
config dir's `.credentials.json`, where OAuth tokens live), whatever it
holds: a token the registry does not know could not be redacted.
"""

import os

from fakes.wirelog import fingerprint

VALUE_FLAGS = ("--env", "-e", "--header", "-H")
PRESENCE_ONLY_PLACEHOLDER = "<redacted: live key, presence only>"


def placeholder(*, value):
    print_form = fingerprint(value=value)
    return "<redacted sha8=%s len=%d>" % (print_form["sha8"], print_form["len"])


class SecretRegistry:
    """The credential values of one test. Values never leave it except as a
    hash, or, for a presence_only value (the live API key), not at all."""

    def __init__(self):
        self._values = []
        self._presence_only = []

    def register(self, *, value, presence_only):
        """presence_only: True for the live API key (redacted with no hash),
        False for a credential the test made up (redacted as sha8 + len)."""
        assert value, "refusing to register an empty secret"
        if presence_only:
            self._presence_only.append(value)
        else:
            self._values.append(value)
        return value

    def values(self):
        return self._presence_only + self._values

    def redact_presence_only(self, *, text):
        for value in self._presence_only:
            text = text.replace(value, PRESENCE_ONLY_PLACEHOLDER)
        return text

    def redact_text(self, *, text):
        text = self.redact_presence_only(text=text)
        for value in self._values:
            text = text.replace(value, placeholder(value=value))
        return text


def _redact_flag_value(*, flag, value):
    if flag in ("--env", "-e"):
        name, separator, secret = value.partition("=")
        return name + separator + placeholder(value=secret) if separator else placeholder(value=value)
    name, separator, secret = value.partition(":")
    return name + separator + " " + placeholder(value=secret.strip()) if separator else placeholder(value=value)


def redact_argv(*, argv, registry):
    out = []
    previous = None
    for item in argv:
        if previous in VALUE_FLAGS:
            out.append(_redact_flag_value(flag=previous, value=registry.redact_presence_only(text=item)))
        else:
            out.append(registry.redact_text(text=item))
        previous = item
    return out


def scan_dir(*, root, registry):
    """Relative paths of files under root that still hold a registered value."""
    needles = [value.encode("utf-8") for value in registry.values()]
    hits = []
    for directory, _subdirs, files in os.walk(root):
        for filename in files:
            full = os.path.join(directory, filename)
            with open(full, "rb") as handle:
                data = handle.read()
            if any(needle in data for needle in needles):
                hits.append(os.path.relpath(full, root))
    return sorted(hits)


def copy_tree_redacted(*, source, target, registry, withheld_names):
    """Copy a directory, replacing registered values in every text file.
    A file named in withheld_names is not copied at all. A file that is not
    UTF-8 text is dropped rather than copied blind. Returns
    {"withheld": [relative paths], "dropped_binary": [relative paths]}."""
    dropped = []
    withheld = []
    for directory, _subdirs, files in os.walk(source):
        for filename in files:
            full = os.path.join(directory, filename)
            relative = os.path.relpath(full, source)
            if filename in withheld_names:
                withheld.append(relative)
                continue
            try:
                with open(full, encoding="utf-8") as handle:
                    text = handle.read()
            except UnicodeDecodeError:
                dropped.append(relative)
                continue
            destination = os.path.join(target, relative)
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            with open(destination, "w", encoding="utf-8") as handle:
                handle.write(registry.redact_text(text=text))
    return {"withheld": sorted(withheld), "dropped_binary": sorted(dropped)}
