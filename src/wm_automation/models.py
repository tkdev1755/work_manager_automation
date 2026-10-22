from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class JobOffer:
    """One offer, either from the Craft tracker or entered manually via the
    CLI. `preset` is the work_manager preset to use - None means "use the
    default preset".

    The craft_* fields are None for manually-entered offers. When sourced
    from Craft, they identify the specific blocks to flip when marking
    progress: a company item has a "Commencé la candidature ?" and a
    "Postulé ?" checklist block per offer (not a single per-item toggle) -
    see wm_automation.craft.tracker. The *_markdown fields carry each
    block's original unchecked text, so mark_started/mark_applied can flip
    `[ ]` -> `[x]` without assuming exact phrasing beyond what
    fetch_new_offers already matched on.
    """

    company: str
    title: str
    url: str
    # Full posting text for the LLM prompt. Craft-sourced offers only get the
    # short auto-extracted blurb Craft's richUrl block carries (not the full
    # posting - Craft doesn't store that) - fetching the real page content
    # is a known gap, not solved yet. Manually-entered offers can pass the
    # full text via the CLI.
    description: str = ""
    # What the candidate said motivates them about this specific offer - not
    # derivable from Craft or the experience corpus, has to come from the
    # human (or the future chat session). Required for real LM generation;
    # missing it just means llm.generate_lm_content produces a weaker draft.
    motivation: str | None = None
    preset: str | None = None
    # Language the letter and the CV's LLM-written sections (jobs/
    # personal_experience descriptions) should be written in. Not inferred
    # from the offer's text - Craft-sourced descriptions are too short/
    # ambiguous to detect this reliably, and it's the kind of call that
    # should come from the human, same as motivation. Defaults to French,
    # matching the pipeline's original (implicit) behavior. Pair with a
    # matching `preset` (e.g. "english") whose static fields - tagline,
    # skills, education... - are already authored in that language by hand;
    # this field never touches those, only what the LLM itself writes.
    language: str = "français"
    notes: str = ""
    craft_company_item_id: str | None = None
    craft_started_task_id: str | None = None
    craft_started_task_markdown: str | None = None
    craft_applied_task_id: str | None = None
    craft_applied_task_markdown: str | None = None
