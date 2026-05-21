"""Playwright session owned by a dedicated worker thread.

Haystack's Agent invokes tools from worker threads, but sync Playwright pins
its event loop to whichever thread created it. To survive across tool calls,
we start one long-lived worker thread that owns the browser, and dispatch
fetch requests to it through a queue.
"""
import json
import os
import queue
import re
import threading
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from paths import STORAGE_STATE

load_dotenv()
BASE_URL = os.environ.get("HAYSTACK_BASE_URL", "https://your-org.haystack.so")

_requests: queue.Queue[tuple[str, Any] | None] = queue.Queue()
_responses: queue.Queue[tuple[str, Any]] = queue.Queue()
_worker: threading.Thread | None = None
_ready = threading.Event()
_lock = threading.Lock()  # serialize fetch() callers


def _run_worker() -> None:
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(storage_state=str(STORAGE_STATE))
            _ready.set()
            try:
                while True:
                    msg = _requests.get()
                    if msg is None:
                        return
                    op, arg = msg
                    if op == "fetch":
                        try:
                            page = context.new_page()
                            try:
                                page.goto(arg, wait_until="networkidle", timeout=30_000)
                                _responses.put(
                                    ("ok", {"url": page.url, "html": page.content()})
                                )
                            finally:
                                page.close()
                        except Exception as e:  # noqa: BLE001
                            _responses.put(("err", repr(e)))
                    elif op == "search":
                        try:
                            page = context.new_page()
                            try:
                                page.goto(arg, wait_until="domcontentloaded", timeout=30_000)
                                # AI search streams its answer; wait for network
                                # to quiet down, but tolerate the timeout.
                                try:
                                    page.wait_for_load_state(
                                        "networkidle", timeout=20_000
                                    )
                                except Exception:  # noqa: BLE001
                                    pass
                                _responses.put(
                                    ("ok", {"url": page.url, "html": page.content()})
                                )
                            finally:
                                page.close()
                        except Exception as e:  # noqa: BLE001
                            _responses.put(("err", repr(e)))
                    elif op == "api_post":
                        try:
                            path, body, jwt = arg
                            resp = context.request.post(
                                f"{BASE_URL}{path}",
                                data=body,
                                headers={
                                    "Authorization": f"Bearer {jwt}",
                                    "Content-Type": "application/x-protobuf",
                                    "Accept": "application/json, text/plain, */*",
                                    "Origin": BASE_URL,
                                    "Referer": f"{BASE_URL}/resources/new?edit=true",
                                    "sso-provider": "SAML",
                                    "x-client-type": "web",
                                    "x-os": "macos",
                                    "x-client-timezone": "America/New_York",
                                },
                            )
                            _responses.put(
                                ("ok", {"status": resp.status, "body": resp.body()})
                            )
                        except Exception as e:  # noqa: BLE001
                            _responses.put(("err", repr(e)))
            finally:
                context.close()
                browser.close()
    except Exception as e:  # noqa: BLE001
        _responses.put(("err", f"worker failed to start: {e!r}"))
        _ready.set()


def start() -> None:
    global _worker
    if _worker is not None and _worker.is_alive():
        return
    if not STORAGE_STATE.exists():
        raise RuntimeError(
            f"No saved session at {STORAGE_STATE}. Run `uv run auth.py` first."
        )
    _worker = threading.Thread(target=_run_worker, name="playwright-worker", daemon=True)
    _worker.start()
    _ready.wait(timeout=30)


def stop() -> None:
    global _worker
    if _worker and _worker.is_alive():
        _requests.put(None)
        _worker.join(timeout=10)
    _worker = None


def _parse(html: str, final_url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = "\n".join(
        line.strip() for line in soup.get_text("\n").splitlines() if line.strip()
    )
    links = [
        {"text": (a.get_text() or "").strip(), "href": urljoin(final_url, a["href"])}
        for a in soup.find_all("a", href=True)
        if a["href"] and not a["href"].startswith("#")
    ]
    return {"url": final_url, "text": text, "links": links}


def _dispatch(op: str, arg: Any) -> dict:
    start()
    with _lock:
        _requests.put((op, arg))
        status, payload = _responses.get()
    if status == "err":
        raise RuntimeError(f"playwright {op} failed: {payload}")
    return _parse(payload["html"], payload["url"])


def fetch(path: str) -> dict:
    """Navigate to BASE_URL + path, return cleaned text and links."""
    return _dispatch("fetch", urljoin(BASE_URL + "/", path.lstrip("/")))


def search(query: str) -> dict:
    """Run an AI-powered intranet search via the SPA, return cleaned text + links."""
    from urllib.parse import quote

    url = f"{BASE_URL}/search-app?q={quote(query)}&ai=true"
    return _dispatch("search", url)


def _read_jwt() -> str:
    """Pull the SAML-issued JWT out of the captured session cookies."""
    state = json.loads(STORAGE_STATE.read_text())
    for c in state.get("cookies", []):
        if c.get("name") == "token":
            return c["value"]
    raise RuntimeError(
        f"No 'token' cookie in {STORAGE_STATE}; session may be invalid. "
        "Run `uv run auth.py` to refresh."
    )


def api_post(path: str, body: bytes) -> dict:
    """POST a protobuf-encoded body to a /api/v1/... endpoint using the
    authenticated session. Returns {"status": int, "body": bytes}."""
    start()
    jwt = _read_jwt()
    with _lock:
        _requests.put(("api_post", (path, body, jwt)))
        status, payload = _responses.get()
    if status == "err":
        raise RuntimeError(f"playwright api_post failed: {payload}")
    return payload


UUID_RE = re.compile(rb"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def delete_post(post_id: str, confirm_title: str) -> dict:
    """Delete an announcement (post) you authored on The Source.

    Before deleting, fetches the post and verifies its title matches
    `confirm_title` exactly. Raises ValueError on mismatch so a typo in
    post_id can't silently delete the wrong record.

    Drafts are deleted permanently; published posts go to the author's
    content archive (recoverable) per Haystack's standard behavior.
    """
    import proto

    get_resp = api_post("/api/v1/announcement/get", proto.build_get_announcement(post_id))
    if get_resp["status"] != 200:
        raise RuntimeError(
            f"could not fetch post {post_id} for confirmation "
            f"(status {get_resp['status']})"
        )
    actual_title = proto.extract_announcement_title(get_resp["body"])
    if actual_title is None:
        raise RuntimeError(
            f"could not parse a title from the post {post_id} response"
        )
    if actual_title != confirm_title:
        raise ValueError(
            f"refusing to delete: post {post_id} has title "
            f"{actual_title!r}, not the expected {confirm_title!r}"
        )

    del_resp = api_post(
        "/api/v1/announcement/delete", proto.build_delete_announcement(post_id)
    )
    return {
        "status": del_resp["status"],
        "deleted_post_id": post_id,
        "deleted_title": actual_title,
    }


def list_drafts() -> list[dict]:
    """Fetch the caller's draft posts (announcements) via
    /api/v1/announcement/list with draft_only=true. Returns a list of dicts
    with id, title, destination {uuid, name}, created/last_updated
    timestamps, and a /post/<id> URL ready to open.
    """
    import datetime as dt

    import proto

    result = api_post(
        "/api/v1/announcement/list", proto.build_list_announcements_draft_only()
    )
    drafts = proto.parse_list_announcements_response(result["body"])
    for d in drafts:
        if "id" in d:
            d["url"] = f"{BASE_URL}/post/{d['id']}"
        for k in ("created_ts", "last_updated_ts"):
            v = d.get(k)
            if isinstance(v, int) and v > 0:
                # Server gives unix seconds; ms in case the field grew.
                if v > 10_000_000_000:
                    v //= 1000
                try:
                    d[k.replace("_ts", "_iso")] = dt.datetime.fromtimestamp(
                        v, tz=dt.timezone.utc
                    ).isoformat()
                except Exception:  # noqa: BLE001
                    pass
    return drafts


def list_teams() -> list[dict]:
    """Fetch the list of teams/groups the caller can post to via
    /api/v1/teams/list. Returns a list of {"name", "uuid"} dicts."""
    import proto

    # Body captured from the UI's teams/list call — field 4 varint = 10
    # (probably page_size or similar).
    result = api_post("/api/v1/teams/list", bytes([0x20, 0x0a]))
    return proto.parse_teams_list_response(result["body"])


def _md_to_html(body_markdown: str) -> str:
    import markdown as md
    return md.markdown(body_markdown, extensions=["extra", "sane_lists", "nl2br"])


def create_draft_announcement(
    title: str, body_markdown: str, destination_group_name: str
) -> dict:
    """Create a DRAFT post (/announcement/create) targeted at a specific
    group. The destination is resolved by name via list_teams(); if no
    exact match (case-insensitive) is found, raises ValueError with the
    list of available group names so the caller can correct.

    Drafts are invisible to others until the user publishes from the UI.
    """
    import proto

    teams = list_teams()
    name_lower = destination_group_name.strip().lower()
    matches = [t for t in teams if t["name"].lower() == name_lower]
    if not matches:
        available = ", ".join(repr(t["name"]) for t in teams)
        raise ValueError(
            f"No group matches {destination_group_name!r}. "
            f"Available groups: {available}"
        )
    if len(matches) > 1:
        raise ValueError(
            f"Ambiguous group name {destination_group_name!r} — "
            f"matches {len(matches)} groups."
        )
    destination = matches[0]

    request_body = proto.build_create_announcement_draft(
        title=title,
        html_body=_md_to_html(body_markdown),
        destination_group_id=destination["uuid"],
    )
    result = api_post("/api/v1/announcement/create", request_body)
    uuid_match = UUID_RE.search(result["body"])
    # Posts live at /post/<uuid>, NOT /resources/<uuid> (that's the path
    # for /knowledge pages). The two namespaces share the resources/get_*
    # API surface but have separate SPA routes.
    url = (
        f"{BASE_URL}/post/{uuid_match.group(0).decode()}"
        if uuid_match
        else None
    )
    return {
        "status": result["status"],
        "url": url,
        "destination_name": destination["name"],
        "destination_uuid": destination["uuid"],
        "raw_response_hex": result["body"][:200].hex(),
    }
