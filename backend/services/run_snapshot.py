"""Per-run snapshot of source documents + chart context.

When a run is triggered via MCP, citations reference DocumentReference IDs
from the live FHIR server. The frontend reviews the run over plain REST
(no SHARP context), so it cannot re-resolve those documents from the live
server. We freeze a copy of the inputs at run time so review is decoupled
from the live FHIR connection — and so the audit trail captures the exact
documents the proposals were extracted from.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path

from fhir.models import Document, PatientContext

log = logging.getLogger(__name__)

SNAPSHOT_DIR = Path(__file__).resolve().parent.parent / ".cache" / "runs"


def _path(run_id: str) -> Path:
    return SNAPSHOT_DIR / f"{run_id}.json"


def write(run_id: str, patient_context: PatientContext, documents: list[Document]) -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "patient_context": asdict(patient_context),
        "documents": [asdict(d) for d in documents],
    }
    try:
        _path(run_id).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        log.warning("snapshot write failed for run %s: %s", run_id, exc)


def read(run_id: str) -> tuple[PatientContext, list[Document]] | None:
    p = _path(run_id)
    if not p.exists():
        return None
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("snapshot read failed for run %s: %s", run_id, exc)
        return None
    pc = PatientContext(**payload["patient_context"])
    docs = [Document(**d) for d in payload["documents"]]
    return pc, docs


def delete_many(run_ids: list[str]) -> None:
    for rid in run_ids:
        try:
            _path(rid).unlink(missing_ok=True)
        except OSError:
            pass
