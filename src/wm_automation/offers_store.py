"""Local mapping of work_manager application_id -> the JobOffer it came
from. work_manager's own metadata.json has no field for this, and Craft's
schema isn't confirmed yet, so this is wm_automation's own small bookkeeping
- needed so finalize can later report "applied" back to the right Craft
item, keyed off the id it already has."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from wm_automation.models import JobOffer


def save_offer(store_path: Path, application_id: str, offer: JobOffer) -> None:
    store_path.parent.mkdir(parents=True, exist_ok=True)
    data = _read(store_path)
    data[application_id] = asdict(offer)
    store_path.write_text(json.dumps(data, indent=2))


def load_offer(store_path: Path, application_id: str) -> JobOffer | None:
    data = _read(store_path)
    entry = data.get(application_id)
    return JobOffer(**entry) if entry is not None else None


def _read(store_path: Path) -> dict:
    if not store_path.exists():
        return {}
    return json.loads(store_path.read_text())
