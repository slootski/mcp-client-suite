"""Secret scan: no artifact may contain the value of ANTHROPIC_API_KEY, or
the prefix of a test credential (constants.SECRET_SCAN_MARKERS)."""

import os


def find_leaks(*, root, needles):
    """Relative paths of files under root whose bytes or name contain any
    of needles (a list of str)."""
    encoded = [needle.encode("utf-8") for needle in needles]
    leaks = []
    for directory, _subdirs, files in os.walk(root):
        for filename in files:
            full = os.path.join(directory, filename)
            with open(full, "rb") as handle:
                data = handle.read()
            name = filename.encode("utf-8")
            if any(needle in data or needle in name for needle in encoded):
                leaks.append(os.path.relpath(full, root))
    return sorted(set(leaks))
