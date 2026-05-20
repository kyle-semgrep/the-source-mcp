"""MCP server exposing a Haystack-backed company intranet as tools for agents.

Two tools:
  - search_the_source(query): AI-powered intranet search
  - fetch_the_source_page(path): fetch a specific page by path or URL

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


if __name__ == "__main__":
    mcp.run()
