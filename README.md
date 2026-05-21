# the-source-mcp

An MCP server that lets Claude Code (and other MCP clients) read your
company's [Haystack](https://haystackteam.com) intranet as a research source.

Five tools are exposed:

- `search_the_source(query)` — runs an AI-powered intranet search and returns
  the rendered results page (including the AI-generated answer).
- `fetch_the_source_page(path_or_url)` — fetches any page on your Haystack
  instance by path (e.g. `/dashboard`) or full URL.
- `list_my_destination_groups_on_the_source()` — lists the groups (teams) the
  caller can post to; pair with the write tool below.
- `create_draft_post_on_the_source(title, body_markdown, destination_group_name)`
  — creates an **unpublished draft post** in the named group. Markdown body is
  converted to HTML. The draft is invisible to others until you publish it
  via the UI. The tool always requires an explicit destination group; there
  is no `publish=True` flag.
- `list_my_drafts_on_the_source()` — lists your existing draft posts so an
  agent can avoid creating duplicates and you can see the full set of drafts
  at a glance (Haystack has no dedicated "all drafts" page in the SPA).
- `delete_post_on_the_source(post_id, confirm_title)` — deletes a post you
  authored. Requires the agent to echo the post's exact title as a guard
  against typos. Drafts are deleted permanently; published posts go to your
  content archive.

Authentication is handled via a Playwright session captured once interactively
through your SSO provider; the session cookie is reused for headless requests.
No credentials live in the repo.

---

## Setup

### 1. Install

Requires [`uv`](https://docs.astral.sh/uv/) and Python 3.11+.

```bash
git clone https://github.com/kyle-semgrep/the-source-mcp.git ~/tools/the-source-mcp
cd ~/tools/the-source-mcp
uv sync
uv run playwright install chromium
```

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env` and set:

- `HAYSTACK_BASE_URL` — your org's Haystack instance, e.g. `https://<your-org>.haystack.so`.
- `ANTHROPIC_API_KEY` — only needed if you also want to run the standalone
  `agent.py` smoke-test harness; the MCP tools themselves don't call any LLM.

### 3. Capture your session

```bash
uv run auth.py
```

A headed Chromium window opens. Complete your SSO flow, land on the
dashboard, then return to the terminal and press Enter. The session is saved
to `.state/storage_state.json` (gitignored). You will need to re-run this
when the session expires (typically every few days, depending on your SSO
provider's policy).

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

Add a line to `~/.claude/CLAUDE.md` (or per-project) so agents reach for the
intranet on broad-research prompts:

> When asked to "use all sources" for research, query the company intranet
> via the `the-source` MCP server alongside Notion and any other connected
> knowledge sources.

---

## Layout

| File              | Purpose                                                        |
| ----------------- | -------------------------------------------------------------- |
| `mcp_server.py`   | FastMCP server entry point; registers the four tools.          |
| `proto.py`        | Hand-written protobuf encoder/decoder for the API requests.    |
| `browser.py`      | Playwright session owned by a dedicated worker thread.         |
| `tools.py`        | Haystack-style tool wrappers (used only by `agent.py`).        |
| `agent.py`        | Standalone Haystack agent — smoke-test / development harness.  |
| `auth.py`         | One-shot interactive login → persists session to `.state/`.    |
| `state.py`        | Tiny JSON state store used by `agent.py`.                      |
| `paths.py`        | Centralized filesystem paths.                                  |
| `.state/`         | **gitignored** — holds your captured session.                  |

---

## Notes & limits

- **Latency:** search runs through the SPA, so a query takes ~3–5 s. Fine for
  research-on-demand, not for tight loops. A direct call to the underlying
  search API would be faster but the request body is protobuf and we don't
  have the `.proto` definition.
- **Result links:** Haystack's SPA renders result cards as JS click handlers,
  not static `<a href>` tags. `search_the_source` returns result *titles* and
  the AI summary; to read a specific result page, call
  `fetch_the_source_page` with a path you know, or extend the server with an
  "open result" tool that clicks via Playwright.
- **Session expiry:** rerun `uv run auth.py` when search/fetch start returning
  the login screen.

---

## Security

- Never commit `.state/` or `.env`. The `.gitignore` already excludes both.
- The session cookie is an SSO-issued credential — treat it as such. It
  lives only on your local disk under `.state/storage_state.json`.
- This tool reads internal company content. Don't pipe its output to
  third-party services without the same care you'd apply to anything else
  from your intranet.
