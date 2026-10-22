"""Local LLM call generating the LM draft. Model/prompt validated by manual
testing against LM Studio - see docs/implementation_plan.md for the
comparison that led here (Qwen3.6-35B-A3B, default reasoning effort).

Deliberately a single, scoped, non-agentic HTTP call: no tool access, no
multi-turn loop. It produces a draft the human still reviews before export -
see pipeline.py's prepare/finalize split.

Model, system prompt and generation parameters are all configurable (see
Settings in config.py / env vars) rather than hardcoded here, since all
three were iterated on repeatedly during testing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx
import yaml

from wm_automation.config import Settings
from wm_automation.models import JobOffer

LETTER_PATTERN = re.compile(r"<<<LETTRE_DEBUT>>>(.*?)<<<LETTRE_FIN>>>", re.DOTALL)
CV_PATTERN = re.compile(r"<<<CV_DEBUT>>>(.*?)<<<CV_FIN>>>", re.DOTALL)
APPLICATION_NAME_PATTERN = re.compile(r"<<<NOM_DEBUT>>>(.*?)<<<NOM_FIN>>>", re.DOTALL)


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class GeneratedApplication:
    letter: str
    cv_sections: dict


def _build_user_message(offer: JobOffer, corpus: str) -> str:
    parts = [f"Offre : {offer.title} - {offer.company}\n{offer.description}".strip()]
    parts.append(f"Langue de rédaction de la lettre : {offer.language}")
    parts.append(f"Expériences personnelles :\n{corpus}")
    if offer.motivation:
        parts.append(
            "Ce qui me motive dans cette offre (à ne pas reprendre dans la lettre tel quel) : "
            + offer.motivation
        )
    return "\n\n".join(parts)


def _build_cv_followup_message(
    settings: Settings, jobs_pool: list, current_tagline: str | None, language: str
) -> str:
    template = settings.cv_followup_prompt_path.read_text(encoding="utf-8")
    jobs_yaml = yaml.safe_dump(jobs_pool, allow_unicode=True, sort_keys=False).strip()
    return (
        template.replace("__JOBS_POOL_YAML__", jobs_yaml)
        .replace("__CURRENT_TAGLINE__", current_tagline or "")
        .replace("__LANGUAGE__", language)
    )


async def _complete(
    client: httpx.AsyncClient,
    settings: Settings,
    messages: list[dict],
    *,
    reasoning_effort: str | None,
    max_tokens: int | None = None,
) -> str:
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": settings.llm_temperature,
    }
    if reasoning_effort is not None:
        payload["reasoning_effort"] = reasoning_effort
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    response = await client.post(f"{settings.llm_api_base}/chat/completions", json=payload)
    response.raise_for_status()
    choice = response.json()["choices"][0]
    if choice.get("finish_reason") == "length":
        raise LLMError(
            f"Completion was cut off at max_tokens={max_tokens} without finishing - "
            "likely a non-converging reasoning loop rather than a genuinely long answer."
        )
    return choice["message"]["content"]


async def generate_application_content(
    offer: JobOffer, settings: Settings, jobs_pool: list, current_tagline: str | None
) -> GeneratedApplication:
    """Two turns of a single conversation: first the cover letter (unchanged
    from the validated prompt - see docs/implementation_plan.md sections 1.2
    and 3), then a follow-up turn asking the same model, with the letter's
    reasoning still in context, to also produce the CV's jobs/
    personal_experience/tagline sections. Deliberately one conversation, not
    two independent calls, so the CV reuses the same experience-selection
    reasoning as the letter instead of re-deriving it (see implementation_plan.md
    section 4: "même session conversationnelle que la LM, pas deux flux
    séparés").

    `jobs_pool` is the master list of real jobs (from the corpus, like
    personal_experience) the model selects and reformulates from - not a
    single fixed entry to merely keep/reword/omit anymore, now that there's
    more than one real job to choose between (see implementation_plan.md)."""
    corpus = settings.corpus_path.read_text(encoding="utf-8")
    system_prompt = settings.llm_system_prompt_path.read_text(encoding="utf-8")
    user_message = _build_user_message(offer, corpus)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
        letter_response = await _complete(
            client,
            settings,
            messages,
            reasoning_effort=settings.llm_reasoning_effort,
            max_tokens=settings.llm_letter_max_tokens,
        )

        letter_match = LETTER_PATTERN.search(letter_response)
        if not letter_match:
            raise LLMError(
                "LLM response didn't contain a <<<LETTRE_DEBUT>>>/<<<LETTRE_FIN>>> block - "
                f"got:\n{letter_response}"
            )
        letter = letter_match.group(1).strip()

        messages.append({"role": "assistant", "content": letter_response})
        messages.append(
            {
                "role": "user",
                "content": _build_cv_followup_message(settings, jobs_pool, current_tagline, offer.language),
            }
        )
        cv_response = await _complete(
            client,
            settings,
            messages,
            reasoning_effort=settings.llm_reasoning_effort,
            max_tokens=settings.llm_cv_max_tokens,
        )

    cv_match = CV_PATTERN.search(cv_response)
    if not cv_match:
        raise LLMError(
            "LLM response didn't contain a <<<CV_DEBUT>>>/<<<CV_FIN>>> block - "
            f"got:\n{cv_response}"
        )
    cv_sections = yaml.safe_load(cv_match.group(1).strip())
    if not isinstance(cv_sections, dict):
        raise LLMError(f"CV block didn't parse to a YAML mapping - got:\n{cv_match.group(1)}")

    return GeneratedApplication(letter=letter, cv_sections=cv_sections)


async def generate_application_name(offer: JobOffer, settings: Settings) -> str:
    """Returns a short, specific role label extracted from the offer's raw
    title/description (e.g. "SRE Intern"), so multiple applications at the
    same company are distinguishable by name. The caller (pipeline.py)
    prepends offer.company itself - the model never has to get the company
    name right, only the role.

    Deliberately its own tiny, isolated call - not part of
    generate_application_content's conversation, and forced to
    reasoning_effort="none" regardless of Settings.llm_reasoning_effort:
    this task needs no deep reasoning, and keeping it separate means naming
    an application stays fast (seconds) no matter how slow the main
    letter/CV generation is."""
    template = settings.application_name_prompt_path.read_text(encoding="utf-8")
    user_message = f"Titre : {offer.title}\nDescription : {offer.description}"
    messages = [
        {"role": "system", "content": template},
        {"role": "user", "content": user_message},
    ]
    async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
        response = await _complete(
            client,
            settings,
            messages,
            reasoning_effort="none",
            max_tokens=settings.llm_application_name_max_tokens,
        )
    match = APPLICATION_NAME_PATTERN.search(response)
    if not match:
        raise LLMError(
            "LLM response didn't contain a <<<NOM_DEBUT>>>/<<<NOM_FIN>>> block - "
            f"got:\n{response}"
        )
    return match.group(1).strip()
