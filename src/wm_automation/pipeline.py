from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from wm_automation.config import Settings
from wm_automation.craft import tracker as craft_tracker
from wm_automation.cv import apply_cv_sections, count_pdf_pages
from wm_automation.llm import generate_application_content, generate_application_name
from wm_automation.mcp_client import WorkManagerClient
from wm_automation.models import JobOffer
from wm_automation.offers_store import load_offer, save_offer

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedApplication:
    application_id: str
    lm_path: str
    cv_config_path: str


async def prepare_application(offer: JobOffer, settings: Settings) -> PreparedApplication:
    """Step 1: create the application, drop an LLM-generated LM draft, and
    rewrite the CV's jobs/personal_experience/tagline for this offer (see
    docs/implementation_plan.md section 5 - everything else in
    configuration.yaml is left untouched, that's the human's to edit).
    Stops short of exporting - a human always reviews the LM (see the
    brique 2 briefing) before finalize_application() runs the export.

    The MCP session is closed before the main LLM call (which can take a
    while - see docs/implementation_plan.md) rather than held open for no
    reason. The application name is resolved with its own tiny LLM call
    *before* create_application, so multiple applications at the same
    company are distinguishable (e.g. "Google SRE Intern" vs "Google SWE
    Intern") - as a side effect, if the LLM is unreachable, this fails
    before anything is created at all, rather than leaving an orphan
    application behind (which happened repeatedly with the old
    offer.company-only naming whenever the main generation failed)."""
    application_name = f"{offer.company} {await generate_application_name(offer, settings)}"
    async with WorkManagerClient(settings.mcp_binary) as client:
        created = await client.create_application(name=application_name, preset=offer.preset)
        application_id = created["id"]

        resolved_lm = await client.resolve_template_path(
            settings.lm_template_key, application_id=application_id
        )
        lm_path = resolved_lm["path"]

        resolved_cv_config = await client.resolve_template_path(
            settings.cv_config_template_key, application_id=application_id
        )
        cv_config_path = Path(resolved_cv_config["path"])

    current_config = yaml.safe_load(cv_config_path.read_text(encoding="utf-8")) or {}
    corpus = yaml.safe_load(settings.corpus_path.read_text(encoding="utf-8")) or {}
    generated = await generate_application_content(
        offer,
        settings,
        jobs_pool=corpus.get("jobs", []),
        current_tagline=current_config.get("tagline"),
    )
    with open(lm_path, "w", encoding="utf-8") as f:
        f.write(generated.letter)
    apply_cv_sections(
        cv_config_path,
        generated.cv_sections,
        corpus_personal_experience=corpus.get("personal_experience", []),
        corpus_jobs=corpus.get("jobs", []),
    )

    save_offer(settings.offers_store_path, application_id, offer)

    if offer.craft_started_task_id is not None:
        try:
            await craft_tracker.mark_started(offer, settings)
        except Exception:  # pragma: no cover - Craft write-back is best-effort
            logger.warning("Couldn't mark 'Commencé la candidature ?' in Craft", exc_info=True)

    return PreparedApplication(
        application_id=application_id, lm_path=lm_path, cv_config_path=str(cv_config_path)
    )


async def finalize_application(application_id: str, settings: Settings) -> dict:
    """Step 2: run after the human has reviewed/edited the LM. Runs every
    non-asset template's export_command and copies results to export_path.

    Also does a post-export sanity check on the CV's page count - the
    template is hand-tuned for one page, but nothing during generation
    actually measures Typst's rendered output, so this is the only real
    check that the LLM's rewritten sections didn't overflow (see
    docs/implementation_plan.md section 5). Best-effort: a failure here
    (missing export, unreadable PDF) never blocks the export itself."""
    async with WorkManagerClient(settings.mcp_binary) as client:
        result = await client.export_application(application_id=application_id)

    try:
        cv_export = next(
            f for f in result.get("exported", []) if f.get("templateKey") == settings.cv_template_key
        )
        page_count = count_pdf_pages(Path(cv_export["exportedPath"]))
        result["cv_page_count"] = page_count
        if page_count > settings.cv_max_pages:
            warning = (
                f"CV export has {page_count} page(s), expected at most "
                f"{settings.cv_max_pages} - trim jobs/personal_experience before "
                "treating this as final."
            )
            result["cv_page_warning"] = warning
            logger.warning(warning)
    except Exception:  # pragma: no cover - page-count check is best-effort
        logger.warning("Couldn't check the exported CV's page count", exc_info=True)

    offer = load_offer(settings.offers_store_path, application_id)
    if offer is not None and offer.craft_applied_task_id is not None:
        try:
            await craft_tracker.mark_applied(offer, settings)
        except Exception:  # pragma: no cover - Craft write-back is best-effort
            logger.warning("Couldn't mark 'Postulé ?' in Craft", exc_info=True)

    return result
