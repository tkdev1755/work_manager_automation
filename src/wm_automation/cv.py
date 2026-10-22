"""Local file operations for the CV side of an application - no LLM calls
here (see wm_automation.llm.generate_application_content for that). Only
jobs/personal_experience/tagline are ever touched: the rest of
configuration.yaml (contacts, skills, education...) changes rarely and is
edited by hand - see docs/implementation_plan.md section 5.

Both `jobs` and `personal_experience` are selected/reformulated by the LLM
from a master pool in the corpus (allExperiences.yaml) and reconciled here
against that same pool - `jobs` used to be a single fixed entry the LLM
could only keep/reword/omit, back when there was only one real job. Now
that there's more than one, it works exactly like personal_experience."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pypdf import PdfReader

logger = logging.getLogger(__name__)

# Fields the LLM is trusted to write. Everything else on an entry comes from
# its authoritative source in the corpus (allExperiences.yaml's
# personal_experience or jobs) - see _reconcile_entries. Confirmed
# necessary by a real test (Framatome, 2026-09-19): despite an explicit
# instruction to copy company/product/tags/from/to/location verbatim, the
# LLM silently altered one entry's company link to a plausible-looking but
# wrong domain. Not something a prompt tweak can be trusted to fully fix.
_ENTRY_KEYS = ("position", "company", "product", "tags", "from", "to", "location")


def _reconcile_entries(generated: list[dict], authoritative: list[dict]) -> list[dict]:
    """Matches each LLM-generated entry to its source entry by `position`
    (the field consistently reproduced faithfully in testing) and rebuilds
    it from the authoritative data, keeping only the LLM's `description`.
    An entry with no exact match in the source is dropped rather than kept
    with unverified company/product/link data."""
    by_position = {entry["position"].strip(): entry for entry in authoritative}
    reconciled = []
    for entry in generated:
        source = by_position.get(str(entry.get("position", "")).strip())
        if source is None:
            logger.warning(
                "CV entry with position %r doesn't match any source entry - dropped "
                "rather than trusting its unverified company/product/link data",
                entry.get("position"),
            )
            continue
        merged = {key: source[key] for key in _ENTRY_KEYS if key in source}
        if entry.get("description"):
            merged["description"] = entry["description"]
        reconciled.append(merged)
    return reconciled


def apply_cv_sections(
    config_path: Path,
    cv_sections: dict,
    corpus_personal_experience: list,
    corpus_jobs: list,
) -> None:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if cv_sections.get("tagline") is not None:
        config["tagline"] = cv_sections["tagline"]
    if cv_sections.get("jobs") is not None:
        config["jobs"] = _reconcile_entries(cv_sections["jobs"], corpus_jobs)
    if cv_sections.get("personal_experience") is not None:
        config["personal_experience"] = _reconcile_entries(
            cv_sections["personal_experience"], corpus_personal_experience
        )
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def count_pdf_pages(pdf_path: Path) -> int:
    return len(PdfReader(str(pdf_path)).pages)
