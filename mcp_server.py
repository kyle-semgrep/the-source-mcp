"""MCP server exposing a Haystack-backed company intranet as tools for agents.

Three tools:
  - search_the_source(query): AI-powered intranet search
  - fetch_the_source_page(path): fetch a specific page by path or URL
  - create_draft_post_on_the_source(title, body_markdown): create an
        unpublished draft page in the caller's private space

Configure the target instance via the HAYSTACK_BASE_URL env var.

Register with Claude Code:
  claude mcp add the-source -- uv --directory /absolute/path/to/the-source-mcp \\
      run mcp_server.py
"""
import atexit
import json

from mcp.server.fastmcp import FastMCP

import browser

mcp = FastMCP("the-source")

atexit.register(browser.stop)


@mcp.tool()
def search_the_source(query: str) -> str:
    """Search 'The Source' — the configured Haystack company intranet — for the given query.
    Uses the AI-powered search view which returns a synthesized answer plus
    relevant posts, pages, people, and events.

    Args:
        query: Natural-language search query.

    Returns:
        JSON string with keys: url, text (the rendered search results page,
        including any AI-generated answer and result list), links.
    """
    result = browser.search(query)
    # Cap to keep responses reasonable for the calling agent.
    if len(result["text"]) > 25_000:
        result["text"] = result["text"][:25_000] + "\n…[truncated]"
    if len(result["links"]) > 200:
        result["links"] = result["links"][:200]
    return json.dumps(result)


@mcp.tool()
def fetch_the_source_page(path_or_url: str) -> str:
    """Fetch a specific page on 'The Source'. Use this to follow a link
    returned by `search_the_source`, or to load a known page directly
    (e.g. "/dashboard", "/events", or a full URL on the configured Haystack
    host).

    Args:
        path_or_url: Path (e.g. "/events") or full URL on the same host.

    Returns:
        JSON string with keys: url, text (cleaned visible text), links.
    """
    result = browser.fetch(path_or_url)
    if len(result["text"]) > 25_000:
        result["text"] = result["text"][:25_000] + "\n…[truncated]"
    if len(result["links"]) > 200:
        result["links"] = result["links"][:200]
    return json.dumps(result)


@mcp.tool()
def create_draft_post_on_the_source(title: str, body_markdown: str) -> str:
    """Create a NEW DRAFT page on The Source. The page is saved as an
    unpublished draft in the caller's private space — it is NOT visible
    to anyone else until the caller manually publishes it through the UI.

    Use this when the user asks to "write a post / page on The Source"
    or similar. The body is written in Markdown and rendered to HTML
    before saving, so standard Markdown (headings, lists, links, code,
    bold/italic) renders correctly in the Haystack editor.

    Args:
        title: Page title (plain text).
        body_markdown: Page body in Markdown. Will be converted to HTML.

    Returns:
        JSON string with keys:
          - status: HTTP status code (200/201 on success)
          - url: full URL of the new draft, or null if the server didn't
                 return a parseable resource ID
          - note: human-readable confirmation string

    The draft is always private until the user publishes it. This tool
    has no parameter for destination group, visibility, tags, or
    attachments — those decisions are intentionally left to the human
    review step.
    """
    result = browser.create_draft(title=title, body_markdown=body_markdown)
    result["note"] = (
        "Draft saved to your private pages. "
        "Open the URL above to review and publish manually."
    )
    return json.dumps(result)


if __name__ == "__main__":
    mcp.run()
