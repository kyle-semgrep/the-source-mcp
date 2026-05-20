"""Haystack Agent that monitors the configured Haystack intranet for:
  - new posts on the dashboard feed
  - new events
  - changes to a tracked page

Run: `uv run agent.py`
"""
import os
import sys

from dotenv import load_dotenv
from haystack.components.agents import Agent
from haystack.dataclasses import ChatMessage
from haystack_integrations.components.generators.anthropic import (
    AnthropicChatGenerator,
)

import browser
from tools import ALL_TOOLS

load_dotenv()

SYSTEM_PROMPT = """\
You are an assistant that monitors the configured company Haystack intranet.
On each run, you must:

1. Discover and read the dashboard feed (start at "/dashboard"). Identify
   individual posts. Compare against `read_state("posts_seen")` (a list of
   post fingerprints — title or short stable summary). Report any NEW posts.
   Update state with the new full list before finishing.

2. Discover and read the events page (look for a link with text containing
   "Events" from the dashboard, or try "/events"). Identify individual
   events. Compare against `read_state("events_seen")`. Report any NEW
   events. Update state.

3. Find the "company offsite" page (search dashboard links for "offsite").
   Persist its URL in state key "offsite_url" the first time you find it.
   Compute `hash_text` of the page's main text and compare against
   `read_state("offsite_hash")`. If changed (or first run), say what
   appears to have changed at a high level and update state.

Rules:
- Use `fetch_page` to navigate. Prefer paths over full URLs.
- Keep tool inputs small; don't paste huge text back into tool args.
- After all three checks, output ONE concise markdown summary with three
  sections: "New posts", "New events", "Offsite page". If nothing
  changed in a section, write "No changes."
- Do not invent items. Only report what you actually saw in fetched text.
"""

USER_PROMPT = "Run the daily check now."


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set. Copy .env.example to .env and fill it in.")
        return 1

    generator = AnthropicChatGenerator(
        model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        generation_kwargs={"max_tokens": 4096},
    )
    agent = Agent(
        chat_generator=generator,
        tools=ALL_TOOLS,
        system_prompt=SYSTEM_PROMPT,
        max_agent_steps=25,
    )

    try:
        result = agent.run(messages=[ChatMessage.from_user(USER_PROMPT)])
    finally:
        browser.stop()

    final = result["messages"][-1]
    print(final.text if hasattr(final, "text") else final)
    return 0


if __name__ == "__main__":
    sys.exit(main())
