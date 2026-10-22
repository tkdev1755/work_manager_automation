from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Base URL of the Craft multi-document connection (per-space "link", not a
# generic Craft endpoint - see https://developer.craft.do). Bearer token is
# never hardcoded; it comes from CRAFT_API_TOKEN. The link itself comes from
# CRAFT_API_BASE (e.g. "https://connect.craft.do/links/<your-link>/api/v1").
DEFAULT_CRAFT_API_BASE = ""


@dataclass(frozen=True)
class Settings:
    """Paths and keys the pipeline needs. The MCP server resolves everything
    inside work_manager itself (applications, presets, conf.yml) - this only
    needs to know where its binary lives."""

    mcp_binary: Path
    # Template key (in conf.yml) whose content this pipeline is allowed to
    # write to directly. Must point at a text-based preset (Markdown/Typst),
    # never the default .pages one - see docs/mcp_implementation_plan.md in
    # the work_manager repo for why.
    lm_template_key: str = "lm"

    # Local store mapping work_manager application_id -> the JobOffer it was
    # created from (incl. the Craft item id), so finalize can later report
    # back to Craft. See wm_automation.offers_store.
    offers_store_path: Path = Path.home() / ".wm_automation" / "offers.json"

    # Craft: the tracker document and its collection - set them through
    # CRAFT_TRACKER_DOCUMENT_ID / CRAFT_TRACKER_COLLECTION_ID.
    craft_api_base: str = DEFAULT_CRAFT_API_BASE
    craft_api_token: str | None = None
    craft_tracker_document_id: str = ""
    craft_tracker_collection_id: str = ""

    # Local LLM (LM Studio's OpenAI-compatible server). Model choice and
    # settings validated by manual testing - see docs/implementation_plan.md.
    llm_api_base: str = "http://localhost:1234/v1"
    llm_model: str = "qwen/qwen3.6-35b-a3b"
    llm_system_prompt_path: Path = (
        Path(__file__).parent / "prompts" / "lm_system_prompt.md"
    )
    llm_temperature: float = 0.7
    # None = don't send reasoning_effort at all, i.e. the server's own
    # default - that's what was validated (see implementation_plan.md).
    # Only set this to override it (e.g. "low"/"none" to trade quality for
    # speed, or "high"/"xhigh" for the inverse).
    llm_reasoning_effort: str | None = None
    llm_timeout_seconds: float = 1200.0
    cv_followup_prompt_path: Path = (
        Path(__file__).parent / "prompts" / "cv_followup_prompt.md"
    )
    # Hard cap on the CV follow-up turn. Reasoning models can fall into a
    # non-converging "thinking loop" when asked to satisfy several stacked
    # constraints at once (frozen jobs pool, strict YAML schema, one-page
    # limit) on top of an already long, self-referential conversation -
    # observed in testing as a 14+ minute stall with no output. This turns
    # that into a fast, clean LLMError instead of a silent wait for
    # llm_timeout_seconds.
    llm_cv_max_tokens: int | None = 8000
    # Same idea, for the letter turn - originally left uncapped because it
    # "reliably finishes on its own" (see docs/implementation_plan.md), but
    # that was only ever validated against a ~5200-token corpus. After the
    # corpus enrichment (~14 400 tokens, ×2.8), a real letter call took ~8
    # minutes and spent 95% of its output on reasoning (4487/4701 tokens) -
    # still converged (finish_reason "stop"), but slow enough to blow past
    # Bionic's own tool-call timeout. Same safeguard, same reasoning.
    llm_letter_max_tokens: int | None = 8000

    # A separate, deliberately tiny call (no corpus, forced
    # reasoning_effort="none" regardless of llm_reasoning_effort above) that
    # turns a raw offer title into a short, specific role label (e.g. "SRE
    # Intern") - pipeline.py prepends offer.company itself, so the model
    # never has to get the company name right. Kept out of the main
    # letter/CV conversation so naming an application stays fast (seconds)
    # even when the main generation takes minutes.
    application_name_prompt_path: Path = (
        Path(__file__).parent / "prompts" / "application_name_prompt.md"
    )
    llm_application_name_max_tokens: int = 30

    # Raw text corpus of experiences, stuffed in full into the prompt (small
    # enough that RAG isn't needed yet - see docs/implementation_plan.md).
    corpus_path: Path = Path.home() / "workManager" / "allExperiences.yaml"

    # Template keys (in conf.yml) for the CV side of the pipeline. "asset1"
    # is configuration.yaml (the Typst data source, copied per-application -
    # see docs/implementation_plan.md section 5) and "cv" is the compiled
    # ATSCV.typ/PDF pair. Only jobs/personal_experience/tagline in
    # configuration.yaml get rewritten - everything else (contacts, skills,
    # education...) is the human's to edit directly, see wm_automation.cv.
    cv_config_template_key: str = "asset1"
    cv_template_key: str = "cv"
    # The CV template is hand-tuned to fit one page - this is just a
    # post-export sanity check (page count of the compiled PDF), not
    # something enforced during generation.
    cv_max_pages: int = 1

    # Preset the MCP server's start_application tool uses when the caller
    # doesn't specify one. Must be a text-based preset (see lm_template_key)
    # - work_manager's own "default" preset is the .pages one and would
    # corrupt the LM file if used here. An agent that forgets to pass a
    # preset should still land somewhere safe.
    default_automation_preset: str = "automation"


def load_settings() -> Settings:
    # Explicit path, not load_dotenv()'s default cwd-based discovery: an
    # external MCP host (Bionic) launches this process with its own cwd, not
    # this project's - confirmed empirically that discovery then misses the
    # .env entirely (silently, no error, just a missing CRAFT_API_TOKEN).
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    binary = os.environ.get("WM_MCP_BINARY", str(Path.home() / "workManager" / "work_manager_mcp"))
    offers_store = os.environ.get("WM_OFFERS_STORE")
    return Settings(
        mcp_binary=Path(binary),
        lm_template_key=os.environ.get("WM_LM_TEMPLATE_KEY", Settings.lm_template_key),
        offers_store_path=Path(offers_store) if offers_store else Settings.offers_store_path,
        craft_api_base=os.environ.get("CRAFT_API_BASE", DEFAULT_CRAFT_API_BASE),
        craft_api_token=os.environ.get("CRAFT_API_TOKEN"),
        craft_tracker_document_id=os.environ.get(
            "CRAFT_TRACKER_DOCUMENT_ID", Settings.craft_tracker_document_id
        ),
        craft_tracker_collection_id=os.environ.get(
            "CRAFT_TRACKER_COLLECTION_ID", Settings.craft_tracker_collection_id
        ),
        llm_api_base=os.environ.get("LLM_API_BASE", Settings.llm_api_base),
        llm_model=os.environ.get("LLM_MODEL", Settings.llm_model),
        llm_system_prompt_path=(
            Path(os.environ["LLM_SYSTEM_PROMPT_PATH"])
            if "LLM_SYSTEM_PROMPT_PATH" in os.environ
            else Settings.llm_system_prompt_path
        ),
        llm_temperature=float(os.environ.get("LLM_TEMPERATURE", Settings.llm_temperature)),
        llm_reasoning_effort=os.environ.get("LLM_REASONING_EFFORT", Settings.llm_reasoning_effort),
        llm_timeout_seconds=float(os.environ.get("LLM_TIMEOUT_SECONDS", Settings.llm_timeout_seconds)),
        cv_followup_prompt_path=(
            Path(os.environ["CV_FOLLOWUP_PROMPT_PATH"])
            if "CV_FOLLOWUP_PROMPT_PATH" in os.environ
            else Settings.cv_followup_prompt_path
        ),
        llm_cv_max_tokens=(
            int(os.environ["LLM_CV_MAX_TOKENS"])
            if "LLM_CV_MAX_TOKENS" in os.environ
            else Settings.llm_cv_max_tokens
        ),
        llm_letter_max_tokens=(
            int(os.environ["LLM_LETTER_MAX_TOKENS"])
            if "LLM_LETTER_MAX_TOKENS" in os.environ
            else Settings.llm_letter_max_tokens
        ),
        application_name_prompt_path=(
            Path(os.environ["APPLICATION_NAME_PROMPT_PATH"])
            if "APPLICATION_NAME_PROMPT_PATH" in os.environ
            else Settings.application_name_prompt_path
        ),
        llm_application_name_max_tokens=int(
            os.environ.get("LLM_APPLICATION_NAME_MAX_TOKENS", Settings.llm_application_name_max_tokens)
        ),
        corpus_path=Path(os.environ["WM_CORPUS_PATH"]) if "WM_CORPUS_PATH" in os.environ else Settings.corpus_path,
        cv_config_template_key=os.environ.get(
            "WM_CV_CONFIG_TEMPLATE_KEY", Settings.cv_config_template_key
        ),
        cv_template_key=os.environ.get("WM_CV_TEMPLATE_KEY", Settings.cv_template_key),
        cv_max_pages=int(os.environ.get("WM_CV_MAX_PAGES", Settings.cv_max_pages)),
        default_automation_preset=os.environ.get(
            "WM_DEFAULT_AUTOMATION_PRESET", Settings.default_automation_preset
        ),
    )
