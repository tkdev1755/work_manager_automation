from __future__ import annotations

import argparse
import asyncio

from wm_automation.config import load_settings
from wm_automation.craft.tracker import fetch_new_offers
from wm_automation.models import JobOffer
from wm_automation.pipeline import finalize_application, prepare_application


async def _poll(args: argparse.Namespace) -> None:
    settings = load_settings()
    offers = await fetch_new_offers(settings)
    if not offers:
        print("No untouched offers found.")
        return
    for offer in offers:
        print(f"{offer.company} - {offer.title}")
        print(f"  {offer.url}")


async def _prepare(args: argparse.Namespace) -> None:
    settings = load_settings()
    offer = JobOffer(
        company=args.company,
        title=args.title,
        url=args.url,
        description=args.description or "",
        motivation=args.motivation,
        preset=args.preset,
        **({"language": args.language} if args.language else {}),
    )
    result = await prepare_application(offer, settings)
    print(f"Created application {result.application_id}")
    print(f"LM draft written to: {result.lm_path}")
    print(f"CV jobs/personal_experience/tagline rewritten in: {result.cv_config_path}")
    print("Review/edit them, then run:")
    print(f"  python -m wm_automation.cli finalize --id {result.application_id}")


async def _finalize(args: argparse.Namespace) -> None:
    settings = load_settings()
    result = await finalize_application(args.id, settings)
    for f in result["exported"]:
        print(f"Exported {f['templateKey']} -> {f['exportedPath']}")
    if "cv_page_warning" in result:
        print(f"WARNING: {result['cv_page_warning']}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="wm_automation")
    sub = parser.add_subparsers(dest="command", required=True)

    poll_p = sub.add_parser("poll", help="List Craft tracker offers not yet started (read-only).")
    poll_p.set_defaults(func=_poll)

    prepare_p = sub.add_parser("prepare", help="Create an application and generate an LM draft for review.")
    prepare_p.add_argument("--company", required=True)
    prepare_p.add_argument("--title", required=True)
    prepare_p.add_argument("--url", required=True)
    prepare_p.add_argument("--description", default=None, help="Full offer text, for a better LM draft.")
    prepare_p.add_argument("--motivation", default=None, help="Why this offer interests you - not in the corpus.")
    prepare_p.add_argument("--preset", default=None)
    prepare_p.add_argument(
        "--language", default=None, help="Language for the letter/CV LLM-written fields (default: français)."
    )
    prepare_p.set_defaults(func=_prepare)

    finalize_p = sub.add_parser("finalize", help="Export a reviewed application.")
    finalize_p.add_argument("--id", required=True, help="Application id from `prepare`.")
    finalize_p.set_defaults(func=_finalize)

    args = parser.parse_args()
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
