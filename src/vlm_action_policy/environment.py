"""Load optional private model defaults without executing a shell configuration file."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping


def load_environment(path: str | None, names: Mapping[str, str]) -> None:
    """Existing nonempty environment values take precedence over private defaults."""
    if not path:
        return
    source = Path(path).expanduser()
    if not source.exists():
        return
    # This file may hold an API key; do not echo its contents on errors.
    if os.name == "posix" and source.stat().st_mode & 0o077:
        raise ValueError("private model configuration must have mode 0600")
    values = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(values, dict) or set(values) - set(names):
        raise ValueError("private model configuration contains unsupported fields")
    if any(not isinstance(value, str) or "\x00" in value for value in values.values()):
        raise ValueError("private model configuration values must be strings")
    for key, value in values.items():
        name = names[key]
        if not os.environ.get(name, "").strip():
            os.environ[name] = value
