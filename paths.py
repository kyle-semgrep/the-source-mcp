"""Filesystem paths. State lives alongside the tool in ./.state/ (gitignored)."""
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
STATE_DIR = PROJECT_DIR / ".state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

STORAGE_STATE = STATE_DIR / "storage_state.json"
STATE_FILE = STATE_DIR / "state.json"
