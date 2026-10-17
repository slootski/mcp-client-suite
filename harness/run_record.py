"""Per-test run.json: what ran, under which pins, and what was observed."""

import json


class RunRecord:
    def __init__(self, *, test_id, claude_version, image_id, base_image, env_pins, env_unset):
        self._data = {
            "test_id": test_id,
            "claude_version": claude_version,
            "image_id": image_id,
            "base_image": base_image,
            "env_pins": dict(env_pins),
            "env_unset_on_purpose": list(env_unset),
            "env_overrides": {},
            "observations": {},
        }

    def override_env(self, *, name, shown):
        """Record a per-test env value (shown: the value, or its fingerprint
        for a secret). The name is no longer 'unset on purpose'."""
        self._data["env_overrides"][name] = shown
        self._data["env_unset_on_purpose"] = [n for n in self._data["env_unset_on_purpose"] if n != name]

    def unset_env(self, *, name):
        """Record that a pinned env var was removed for this test."""
        del self._data["env_pins"][name]
        if name not in self._data["env_unset_on_purpose"]:
            self._data["env_unset_on_purpose"].append(name)

    def set_field(self, *, key, value):
        """A top-level field of a model run (model_id, era_seen,
        total_cost_usd). Refuses to overwrite a core field."""
        assert key not in ("test_id", "claude_version", "image_id", "base_image", "env_pins",
                           "env_unset_on_purpose", "env_overrides", "observations", "outcome"), key
        self._data[key] = value

    def observe(self, *, key, value):
        """Attach an observation (status line, first client message, ...)."""
        self._data["observations"][key] = value

    def write(self, *, path, outcome):
        self._data["outcome"] = outcome
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self._data, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
