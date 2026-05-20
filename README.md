# the-source-mcp

An MCP server that lets Claude Code (and other MCP clients) read Semgrep's
internal Haystack intranet, **The Source** (`semgrep.haystack.so`).

Two tools are exposed:

- `search_the_source(query)` — runs an AI-powered intranet search and returns
  the rendered results page (including the AI-generated answer).
- `fetch_the_source_page(path_or_url)` — fetches any page on The Source by
  path (e.g. `/dashboard`) or full URL.

Authentication is handled via a Playwright session captured once interactively;
the session cookie (a 9-day JWT) is reused for headless requests. No
credentials live in the repo.

---

## Setup

### 1. Install

Requires [`uv`](https://docs.astral.sh/uv/) and Python 3.11+.

```bash
git clone git@github.com:kyle-semgrep/the-source-mcp.git ~/tools/the-source-mcp
cd ~/tools/the-source-mcp
uv sync
uv run playwright install chromium
```

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env` and set `ANTHROPIC_API_KEY` (only needed if you also want to run
the standalone `agent.py` smoke-test harness; the MCP tools themselves don't
call any LLM). `HAYSTACK_BASE_URL` defaults to `https://semgrep.haystack.so`.

### 3. Capture your session

```bash
uv run auth.py
```

A headed Chromium window opens. Complete the Okta/SAML SSO flow, land on the
dashboard, then return to the terminal and press Enter. The session is saved
to `.state/storage_state.json` (gitignored). You will need to re-run this
every ~9 days when the JWT expires.

### 4. Register with Claude Code

User-scoped registration so the tools are available in every session:

```bash
claude mcp add the-source --scope user -- \
    uv --directory ~/tools/the-source-mcp run mcp_server.py
```

Verify:

```bash
claude mcp list | grep the-source
# the-source: uv --directory ... - ✓ Connected
```

### 5. Tell your agents to use it

Add a line to `~/.claude/CLAUDE.md` (or per-project) so agents reach for The
Source on broad-research prompts:

> When asked to "use all sources" for research, query **The Source** (the
> `the-source` MCP server) alongside Notion and any other connected
> knowledge sources.

---

## Layout

| File              | Purpose                                                        |
| ----------------- | -------------------------------------------------------------- |
| `mcp_server.py`   | FastMCP server entry point; registers the two tools.           |
| `browser.py`      | Playwright session owned by a dedicated worker thread.         |
| `tools.py`        | Haystack-style tool wrappers (used only by `agent.py`).        |
| `agent.py`        | Standalone Haystack agent — smoke-test / development harness.  |
| `auth.py`         | One-shot interactive login → persists session to `.state/`.    |
| `state.py`        | Tiny JSON state store used by `agent.py`.                      |
| `paths.py`        | Centralized filesystem paths.                                  |
| `.state/`         | **gitignored** — holds `storage_state.json` (JWT cookie).      |

---

## Notes & limits

- **Latency:** search runs through the SPA, so a query takes ~3–5 s. Fine for
  research-on-demand, not for tight loops. A direct call to the
  `/api/v1/gen_ai/search` protobuf endpoint would be faster but requires a
  `.proto` definition we don't have.
- **Result links:** The Source's SPA renders result cards as JS click handlers,
  not static `<a href>` tags. `search_the_source` returns result *titles* and
  the AI summary; to read a specific result page, call
  `fetch_the_source_page` with a path you know, or extend the server with an
  "open result" tool that clicks via Playwright.
- **Session expiry:** rerun `uv run auth.py` when search/fetch start returning
  the login screen.

---

## Security

- Never commit `.state/` or `.env`. The `.gitignore` already excludes both.
- The session cookie is a SAML-issued JWT — treat it as a credential. It
  lives only on your local disk under `.state/storage_state.json`.
- This tool reads internal Semgrep content. Don't pipe its output to
  third-party services without the same care you'd apply to anything else
  from The Source.
