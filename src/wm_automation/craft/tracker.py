"""Craft tracker integration.

Confirmed against the real tracker (one Craft document, one collection,
76 companies):

- One collection item = one COMPANY. Its `content` is a flat, repeating
  sequence per offer: a `richUrl` block (the posting link) followed by two
  `text` checklist blocks ("Commencé la candidature ?", "Postulé ?"),
  matched by substring since exact phrasing/order isn't guaranteed to be
  rigid. Some richUrl blocks (a generic career-portal link) have no
  checklist after them - not every link is an offer.
- Checked state lives in a structured `taskInfo.state` field ("todo" /
  "done"), not in the `[ ]`/`[x]` markdown syntax - that's just a render
  of the same state, but it's what PUT /blocks accepts (only `markdown` is
  documented as writable for text blocks), so writing back means editing
  that markdown, not taskInfo directly.
- A single `GET /blocks?id=<document_id>&maxDepth=-1` returns the whole
  tree (all companies, confirmed - 286KB for 76 items) - cheap enough for
  a periodic poll against the rate limits, and much simpler than 76
  per-company calls.

Design: fetch_new_offers() only surfaces offers where BOTH checklist items
are still "todo" - i.e. genuinely untouched. An offer with "Commencé..."
already done but "Postulé..." still todo was likely started by hand,
outside this pipeline, and picking it up here could create a duplicate
work_manager application - left for manual handling.

mark_started()/mark_applied() correspond to this pipeline's prepare/
finalize split: prepare_application should call mark_started once it's
created the work_manager application, finalize_application should call
mark_applied once export succeeds. NOT YET VALIDATED against the real API
(no write test run yet) - test via Bruno request 09 before trusting it in
pipeline.py.
"""

from __future__ import annotations

from collections.abc import Iterator

from wm_automation.config import Settings
from wm_automation.craft.client import CraftClient
from wm_automation.models import JobOffer


class CraftNotConfigured(RuntimeError):
    pass


def _require_token(settings: Settings) -> None:
    if not settings.craft_api_token:
        raise CraftNotConfigured("Missing CRAFT_API_TOKEN - see README.")


def _iter_collection_items(block: dict) -> Iterator[dict]:
    if block.get("type") == "collectionItem":
        yield block
    # A `collection` block nests its rows under `items`, not `content` -
    # everything else (including a collectionItem's own body) uses
    # `content`. Confirmed against the real document tree: this was missed
    # on the first pass and made fetch_new_offers() silently find nothing.
    for child in (block.get("content") or []) + (block.get("items") or []):
        yield from _iter_collection_items(child)


def _offers_in_company(item: dict) -> list[JobOffer]:
    company = item.get("title", "")
    offers = []
    last_url_block: dict | None = None
    started: dict | None = None
    applied: dict | None = None

    for block in item.get("content", []) or []:
        if block.get("type") == "richUrl":
            last_url_block = block
            started = applied = None
            continue

        if block.get("listStyle") != "task":
            continue

        text = block.get("markdown", "").lower()
        if "commenc" in text:
            started = block
        elif "postul" in text:
            applied = block

        if started is not None and applied is not None and last_url_block is not None:
            if started.get("taskInfo", {}).get("state") == "todo" and applied.get("taskInfo", {}).get(
                "state"
            ) == "todo":
                offers.append(
                    JobOffer(
                        company=company,
                        title=last_url_block.get("title") or last_url_block.get("url", ""),
                        url=last_url_block.get("url", ""),
                        # Short auto-extracted blurb only - not the full posting,
                        # see JobOffer.description.
                        description=last_url_block.get("description", ""),
                        craft_company_item_id=item.get("id"),
                        craft_started_task_id=started["id"],
                        craft_started_task_markdown=started.get("markdown", ""),
                        craft_applied_task_id=applied["id"],
                        craft_applied_task_markdown=applied.get("markdown", ""),
                    )
                )
            started = applied = None

    return offers


async def fetch_new_offers(settings: Settings) -> list[JobOffer]:
    """Offers across the tracker where neither checklist item has been
    touched yet."""
    _require_token(settings)
    async with CraftClient(settings.craft_api_base, settings.craft_api_token) as client:
        tree = await client.get_blocks(settings.craft_tracker_document_id, max_depth=-1)

    offers = []
    for item in _iter_collection_items(tree):
        offers.extend(_offers_in_company(item))
    return offers


async def _flip_task(task_id: str | None, original_markdown: str | None, settings: Settings) -> None:
    if task_id is None or original_markdown is None:
        raise ValueError("offer has no matching Craft task block - not sourced from Craft")
    _require_token(settings)
    new_markdown = original_markdown.replace("[ ]", "[x]", 1)
    async with CraftClient(settings.craft_api_base, settings.craft_api_token) as client:
        await client.update_blocks([{"id": task_id, "markdown": new_markdown}])


async def mark_started(offer: JobOffer, settings: Settings) -> None:
    await _flip_task(offer.craft_started_task_id, offer.craft_started_task_markdown, settings)


async def mark_applied(offer: JobOffer, settings: Settings) -> None:
    await _flip_task(offer.craft_applied_task_id, offer.craft_applied_task_markdown, settings)
