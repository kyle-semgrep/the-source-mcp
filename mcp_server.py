"""MCP server exposing a Haystack-backed company intranet as tools for agents.

Four tools:
  - search_the_source(query): AI-powered intranet search
  - fetch_the_source_page(path): fetch a specific page by path or URL
  - list_my_destination_groups_on_the_source(): list groups the caller
        can post to (name + uuid pairs)
  - create_draft_post_on_the_source(title, body_markdown, destination_group_name):
        create an unpublished draft post in the named group

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
def list_my_destination_groups_on_the_source() -> str:
    """List the groups (teams) on The Source that the caller can post to.

    Use this BEFORE calling `create_draft_post_on_the_source` so you know
    the available destinations and can present the user with a choice (or
    confirm a destination they named).

    Returns:
        JSON array of {"name": str, "uuid": str} entries.
    """
    teams = browser.list_teams()
    return json.dumps(teams)


@mcp.tool()
def create_draft_post_on_the_source(
    title: str, body_markdown: str, destination_group_name: str
) -> str:
    """Create a NEW DRAFT post on The Source, targeted at a specific group.
    The post is saved as an unpublished draft — it is NOT visible to
    anyone else until the caller manually publishes it through the UI.

    Use this when the user asks to "write a post on The Source", "draft
    a post in <group>", or similar. The body is Markdown; it is converted
    to HTML before saving so standard formatting (headings, lists, links,
    code, bold/italic) renders correctly in the Haystack editor.

    The destination group is REQUIRED — there is no default. You should
    confirm the destination with the user before calling. If you don't
    already know the group name, call
    `list_my_destination_groups_on_the_source` first and either pick a
    group the user named or ask them.

    Args:
        title: Post title (plain text).
        body_markdown: Post body in Markdown. Converted to HTML.
        destination_group_name: Exact display name of the group, e.g.
            "Major General" or "Company Offsite 2026". Matched
            case-insensitively against the list returned by
            `list_my_destination_groups_on_the_source`. If no match, the
            tool errors with the list of available groups so you can
            correct.

    Returns:
        JSON string with keys:
          - status: HTTP status code (200/201 on success)
          - url: full URL of the new draft, or null if the server didn't
                 return a parseable resource ID
          - destination_name: confirmed group name the draft is bound to
          - destination_uuid: that group's UUID
          - note: human-readable confirmation string

    The draft is always private until the user publishes it via the UI.
    This tool intentionally does NOT support `publish=True` — every write
    requires a deliberate human click.
    """
    try:
        result = browser.create_draft_announcement(
            title=title,
            body_markdown=body_markdown,
            destination_group_name=destination_group_name,
        )
    except ValueError as e:
        return json.dumps({"status": 400, "error": str(e)})
    result["note"] = (
        f"Draft saved, scoped to publish to {result['destination_name']!r}. "
        f"Open the URL above to review and publish manually."
    )
    return json.dumps(result)


if __name__ == "__main__":
    mcp.run()
