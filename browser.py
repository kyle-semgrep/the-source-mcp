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


def create_draft(title: str, body_markdown: str) -> dict:
    """Create a draft page on The Source via /api/v1/knowledge/create.

    Markdown body is converted to HTML before sending. Always uses the
    captured "save as draft" flag from the reference cURL (field 47 = 1).

    Returns dict with keys: status, url (if a UUID could be parsed from the
    response), raw_response_hex (truncated, for debugging).
    """
    import markdown as md  # local import keeps top-of-module imports light

    import proto

    html_body = md.markdown(
        body_markdown,
        extensions=["extra", "sane_lists", "nl2br"],
    )
    request_body = proto.build_create_knowledge(title=title, html_body=html_body)
    result = api_post("/api/v1/knowledge/create", request_body)

    uuid_match = UUID_RE.search(result["body"])
    url = (
        f"{BASE_URL}/resources/{uuid_match.group(0).decode()}"
        if uuid_match
        else None
    )
    return {
        "status": result["status"],
        "url": url,
        "raw_response_hex": result["body"][:200].hex(),
    }
