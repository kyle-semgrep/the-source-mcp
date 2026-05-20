"""Minimal JSON state store for tracking what the agent has already seen."""
import json
from typing import Any

from paths import STATE_FILE


def load() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    return json.loads(STATE_FILE.read_text())


def save(state: dict[str, Any]) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))


def get(key: str, default: Any = None) -> Any:
    return load().get(key, default)


def set_(key: str, value: Any) -> None:
    s = load()
    s[key] = value
    save(s)
