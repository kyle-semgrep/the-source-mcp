"""Tools exposed to the Haystack Agent."""
import hashlib
import json
from typing import Any

from haystack.tools import tool

import browser
import state


@tool
def fetch_page(path: str) -> str:
    """Fetch a page from the Haystack site (authenticated). Returns JSON with
    keys: url, text (cleaned visible text), links (list of {text, href}).

    `path` is a path or full URL on the same host, e.g. "/dashboard" or
    "/events" or "/pages/company-offsite".
    """
    result = browser.fetch(path)
    # Truncate to keep tokens manageable; agent can request narrower paths.
    if len(result["text"]) > 20_000:
        result["text"] = result["text"][:20_000] + "\n…[truncated]"
    if len(result["links"]) > 200:
        result["links"] = result["links"][:200]
    return json.dumps(result)


@tool
def read_state(key: str) -> str:
    """Read a previously stored value. Returns JSON-encoded value or "null"
    if the key is unset. Use this at the start of a check to load
    last-seen post IDs / event IDs / page hash."""
    return json.dumps(state.get(key))


@tool
def write_state(key: str, value_json: str) -> str:
    """Persist a value for future runs. `value_json` must be JSON-encoded
    (string, number, list, or object). Returns "ok"."""
    parsed: Any = json.loads(value_json)
    state.set_(key, parsed)
    return "ok"


@tool
def hash_text(text: str) -> str:
    """Return a stable SHA-256 hex digest of the input text. Use this to
    fingerprint a page's content so subsequent runs can detect changes."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


ALL_TOOLS = [fetch_page, read_state, write_state, hash_text]
