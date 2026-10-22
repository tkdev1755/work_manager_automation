"""MCP server exposing wm_automation's pipeline to an interactive agent
(e.g. LM Studio Bionic) as a small, deliberately restricted toolset.

This is NOT the same surface as WorkManagerClient/CraftClient (which talk
to work_manager_mcp and Craft directly, for wm_automation's own internal
use and for manual testing/debugging). An agent connected here never gets
work_manager's preset-admin tools (add_preset/remove_preset - the latter
is irreversible) or Craft's raw block-editing API - only the three
high-level operations below. See docs/implementation_plan.md for why.

Like work_manager_mcp, this talks MCP over stdio, so stdout is the
protocol channel - nothing here may print() to stdout. Logging goes to
stderr via the stdlib logging module instead.
"""

from __future__ import annotations

import dataclasses
import logging
import sys

from mcp.server.mcpserver import MCPServer

from wm_automation.config import load_settings
from wm_automation.craft.tracker import fetch_new_offers
from wm_automation.pipeline import finalize_application as _finalize_application
from wm_automation.pipeline import prepare_application as _prepare_application

logger = logging.getLogger(__name__)

server = MCPServer(
    name="wm_automation",
    instructions=(
        "Tools to work through a personal job-application tracker (Craft) "
        "one offer at a time. Workflow: call list_untouched_offers to see "
        "what's left, pick one, ask the person why that specific offer "
        "interests them (this isn't in the data - don't skip or invent "
        "it), then call start_application with that offer's url and the "
        "motivation. It creates the application and writes an LLM-drafted "
        "cover letter for the person to review/edit themselves - never "
        "call finalize_application right after start_application without "
        "the person confirming they've reviewed the draft first."
    ),
)


@server.tool()
async def list_untouched_offers() -> dict:
    """Lists tracker offers where neither 'Commencé la candidature ?' nor
    'Postulé ?' is checked yet - i.e. genuinely untouched. Read-only.

    Returns a single {"offers": [...]} object rather than a bare list -
    mcp's MCPServer splits a bare list return into one content block per
    item (confirmed: 28 offers -> 28 content blocks), which silently loses
    everything past the first item for any client that only reads
    content[0].text, a common pattern (including this project's own
    WorkManagerClient). A wrapping object serializes as a single block."""
    settings = load_settings()
    offers = await fetch_new_offers(settings)
    return {
        "offers": [
            {"company": o.company, "title": o.title, "url": o.url, "description": o.description}
            for o in offers
        ]
    }


@server.tool()
async def start_application(
    offer_url: str, motivation: str, preset: str | None = None, language: str | None = None
) -> dict:
    """Creates the work_manager application for one offer from the tracker
    (identified by its `url`, as returned by list_untouched_offers), and
    writes an LLM-generated cover letter draft plus a rewritten CV
    (jobs/personal_experience/tagline only, tailored to this offer - see
    docs/implementation_plan.md section 5) to review - neither is exported
    yet. `motivation` is what the person said draws them to this specific
    offer; ask them, don't invent it. `preset` defaults to a text-based,
    LLM-writable preset if omitted - work_manager's own default preset
    can't be written to safely here.

    `language` controls the language of the letter and of the CV's
    LLM-written fields (jobs/personal_experience descriptions) - defaults
    to French. Not inferred from the offer - if it's ambiguous whether the
    offer wants French or another language, ask the person rather than
    guessing. Pair it with a matching `preset` whose static CV fields
    (tagline, skills, education...) are already written in that language
    by hand - this only affects what the LLM itself writes, not those.

    Deliberately stateless - re-fetches the tracker and looks the offer up
    by url rather than trusting an index into a previous
    list_untouched_offers call. An in-memory index cache used to back this
    (see docs/implementation_plan.md section 2, bug 10) and broke silently
    any time the MCP server process restarted between the two calls -
    offer_index would point at an empty/stale cache and fail immediately,
    before ever reaching Craft or the LLM."""
    settings = load_settings()
    offers = await fetch_new_offers(settings)
    matches = [o for o in offers if o.url == offer_url]
    if not matches:
        raise ValueError(
            f"No untouched offer with url={offer_url!r} - call list_untouched_offers "
            "again, it may have already been started/applied or the url may be wrong"
        )
    offer = dataclasses.replace(
        matches[0],
        motivation=motivation,
        preset=preset or settings.default_automation_preset,
        **({"language": language} if language is not None else {}),
    )
    result = await _prepare_application(offer, settings)
    return {
        "application_id": result.application_id,
        "lm_draft_path": result.lm_path,
        "cv_config_path": result.cv_config_path,
    }


@server.tool()
async def finalize_application(application_id: str) -> dict:
    """Exports a reviewed application (runs every non-asset template's
    export_command) and reports back to Craft. Only call this once the
    person has confirmed they reviewed the LM draft and the CV - see
    start_application. The result includes cv_page_count and, if the
    exported CV came out longer than one page, a cv_page_warning to relay
    to the person (the CV template is meant to fit a single page)."""
    settings = load_settings()
    return await _finalize_application(application_id, settings)


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    server.run()


if __name__ == "__main__":
    main()
