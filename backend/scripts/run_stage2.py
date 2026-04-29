"""CLI: FHIR -> Stage 1 -> Stage 2 -> pretty-print + cache + demo contract check.

Run from backend/:
    python -m scripts.run_stage2 [--patient-id=...] [--doc-id=...] [--no-cache]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI

try:
    from openai import DefaultAioHttpClient
    _AIO_AVAILABLE = True
except ImportError:
    DefaultAioHttpClient = None  # type: ignore[assignment]
    _AIO_AVAILABLE = False

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import settings
from core import telemetry
from core.cache import JsonCache
from core.extraction import StageTwoOutput, extract_candidates_batch
from core.preprocess import PreprocessedNote, SentenceSpan, preprocess_document
from core.schemas import NoteContext
from db import init_db
from fhir.bootstrap import MRN_SYSTEM, MRN_VALUE
from fhir.client import FhirClient
from fhir.models import Document
from fhir.read import read_documents

STAGE1_CACHE = Path(__file__).resolve().parent.parent / ".cache" / "stage1"
STAGE2_CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "stage2"
STAGE2_OUTPUT_DIR = Path(__file__).resolve().parent.parent / ".cache" / "stage2_output"


async def _resolve_patient_id(client: FhirClient, override: str | None) -> str:
    if override:
        return override
    bundle = await client.search("Patient", {"identifier": f"{MRN_SYSTEM}|{MRN_VALUE}"})
    for e in (bundle or {}).get("entry", []):
        pid = (e.get("resource") or {}).get("id")
        if pid:
            return pid
    raise RuntimeError(
        f"No patient found for MRN {MRN_VALUE}. Run `python -m scripts.bootstrap` first."
    )


def _load_cached_note(doc_id: str) -> PreprocessedNote | None:
    path = STAGE1_CACHE / f"{doc_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    from datetime import datetime

    sentences = tuple(
        SentenceSpan(number=s["number"], start=s["start"], end=s["end"], text=s["text"])
        for s in data["sentences"]
    )
    doc_date = datetime.fromisoformat(data["document_date"]) if data.get("document_date") else None
    return PreprocessedNote(
        document_id=data["document_id"],
        document_date=doc_date,
        original_text=data["original_text"],
        sentences=sentences,
        numbered_note=data["numbered_note"],
    )


def _preprocess(doc: Document) -> PreprocessedNote:
    cached = _load_cached_note(doc.id)
    if cached is not None:
        return cached
    return preprocess_document(doc)


def _sentence_text(note: PreprocessedNote, number: int, width: int = 100) -> str:
    for s in note.sentences:
        if s.number == number:
            preview = " ".join(s.text.split())
            return preview[: width - 3] + "..." if len(preview) > width else preview
    return "<missing>"


def _print_note_context(ctx: NoteContext, note: PreprocessedNote) -> None:
    print("  note_context:")
    for label in ("note_date", "admission_date", "discharge_date"):
        df = getattr(ctx, label)
        if df.value is None:
            continue
        cite = ", ".join(
            f"[{n}] {_sentence_text(note, n, width=70)}" for n in df.source_sentences
        ) or "<no source>"
        print(f"    {label}: {df.value}  <- {cite}")


def _print_candidates(note: PreprocessedNote, out: StageTwoOutput) -> None:
    for rtype, items in out.candidates.items():
        if not items:
            continue
        print(f"\n  {rtype} (x{len(items)})")
        for item in items:
            data = item.model_dump(mode="json")
            headline = _headline_for(rtype, data)
            print(f"    - {headline}")
            for n in data.get("source_sentences", []):
                print(f"        [{n}] {_sentence_text(note, n, width=90)}")


def _headline_for(rtype: str, data: dict) -> str:
    if rtype == "Condition":
        parts = [data.get("name", "")]
        if data.get("severity"):
            parts.append(f"severity={data['severity']}")
        if data.get("onset"):
            parts.append(f"onset={data['onset']}")
        return " | ".join(p for p in parts if p)
    if rtype == "Observation":
        return f"{data.get('name', '')} = {data.get('value', '')} {data.get('unit') or ''}".strip()
    if rtype == "MedicationRequest":
        dose = data.get("dose")
        dose_str = f"{dose['value']}{dose['unit']}" if dose else ""
        freq = data.get("frequency") or ""
        return f"{data.get('name', '')} {dose_str} {freq} [{data.get('status','')}]".strip()
    if rtype == "Procedure":
        return f"{data.get('name', '')} performed={data.get('performed')} status={data.get('status')}"
    if rtype == "AllergyIntolerance":
        return (
            f"{data.get('substance', '')} reaction={data.get('reaction')} "
            f"severity={data.get('severity')} criticality={data.get('criticality')} "
            f"route={data.get('exposure_route')} onset_age={data.get('onset_age')}"
        )
    if rtype == "FamilyMemberHistory":
        conds = ", ".join(
            f"{c['name']} @ {c.get('onset_age') or '?'}" for c in data.get("conditions", [])
        )
        return f"{data.get('relationship', '')}: {conds}"
    return json.dumps(data, ensure_ascii=False)


DEMO_CHECKS = {
    "cardio": {
        "date_prefix": "2025-10",
        "label": "cardiology consult (2025-10-20)",
        "expected": [
            ("Condition", "angina"),
            ("Condition", "coronary"),
            ("Procedure", "catheter"),
            ("MedicationRequest", "metoprolol"),
        ],
    },
    "ed": {
        "date_prefix": "2025-12",
        "label": "ED discharge (2025-12-15)",
        "expected": [
            ("AllergyIntolerance", "penicillin"),
        ],
    },
    "neuro": {
        "date_prefix": "2026-02",
        "label": "neurology follow-up (2026-02-23)",
        "expected": [
            ("MedicationRequest", "lisinopril"),
            ("Observation", "tobacco"),
            ("FamilyMemberHistory", "father"),
        ],
    },
}


def _classify_doc(doc: Document) -> str | None:
    date = doc.date or ""
    for tag, spec in DEMO_CHECKS.items():
        if date.startswith(spec["date_prefix"]):
            return tag
    return None


def _run_demo_checks(results: list[StageTwoOutput], docs: list[Document]) -> bool:
    print("\n" + "=" * 72)
    print("DEMO CONTRACT CHECK")
    overall = True
    docs_by_id = {d.id: d for d in docs}

    for out in results:
        doc = docs_by_id.get(out.document_id)
        if doc is None:
            continue
        tag = _classify_doc(doc)
        if tag is None:
            continue

        spec = DEMO_CHECKS[tag]
        print(f"\n  {spec['label']}")
        for rtype, needle in spec["expected"]:
            items = out.candidates.get(rtype, [])
            hit = any(
                needle.lower() in _flatten_item_text(i).lower() for i in items
            )
            mark = "PASS" if hit else "FAIL"
            overall &= hit
            print(f"    {mark}  {rtype} contains '{needle}'  (candidates: {len(items)})")

    return overall


def _flatten_item_text(item) -> str:
    data = item.model_dump(mode="json")
    pieces: list[str] = []
    for key in ("name", "substance", "value", "reaction", "relationship"):
        if key in data and data[key]:
            pieces.append(str(data[key]))
    for cond in data.get("conditions", []) or []:
        pieces.append(str(cond.get("name", "")))
    return " ".join(pieces)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--patient-id", default=None)
    parser.add_argument("--doc-id", default=None)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument(
        "--from-stage1-cache",
        action="store_true",
        help="Skip FHIR; read notes from backend/.cache/stage1/",
    )
    args = parser.parse_args()

    load_dotenv()
    if not settings.openai_api_key:
        print("error: OPENAI_API_KEY must be set in .env", file=sys.stderr)
        return 2

    docs: list[Document] = []
    notes: list[PreprocessedNote] = []

    if args.from_stage1_cache:
        for p in sorted(STAGE1_CACHE.glob("*.json")):
            data = json.loads(p.read_text(encoding="utf-8"))
            docs.append(Document(
                id=data["document_id"],
                type="",
                date=data.get("document_date") or "",
                author="",
                text=data["original_text"],
            ))
            note = _load_cached_note(data["document_id"])
            if note is not None:
                notes.append(note)
        if args.doc_id:
            keep = {n.document_id for n in notes if args.doc_id in n.document_id}
            docs = [d for d in docs if d.id in keep]
            notes = [n for n in notes if n.document_id in keep]
    else:
        fhir_url = os.environ.get("DEV_FHIR_BASE_URL")
        fhir_token = os.environ.get("DEV_FHIR_TOKEN")
        if not fhir_url or not fhir_token:
            print("error: DEV_FHIR_BASE_URL and DEV_FHIR_TOKEN must be set in .env", file=sys.stderr)
            return 2

        fhir = FhirClient(fhir_url, fhir_token)
        patient_id = await _resolve_patient_id(fhir, args.patient_id)
        print(f"Patient/{patient_id}")

        docs = await read_documents(fhir, patient_id)
        if args.doc_id:
            docs = [d for d in docs if d.id == args.doc_id or args.doc_id in d.id]
        if not docs:
            print("no DocumentReferences found", file=sys.stderr)
            return 1
        notes = [_preprocess(d) for d in docs]
    print(f"{len(notes)} note(s); preprocessed sentences: {[len(n.sentences) for n in notes]}")

    cache = None if args.no_cache else JsonCache(STAGE2_CACHE_DIR)
    STAGE2_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    await init_db()

    client_kwargs: dict = {"api_key": settings.openai_api_key}
    if _AIO_AVAILABLE:
        client_kwargs["http_client"] = DefaultAioHttpClient()
    else:
        print("note: openai[aiohttp] not installed; using default httpx transport", file=sys.stderr)

    async with AsyncOpenAI(**client_kwargs) as client:
        pid = args.patient_id if args.from_stage1_cache else None
        run_ctx = await telemetry.start_run(
            patient_id=pid,
            triggered_by="cli:run_stage2",
            meta={"doc_count": len(notes), "model": settings.openai_model_fast},
        )
        print(f"run_id={run_ctx.run_id}")

        t0 = time.perf_counter()
        try:
            results = await extract_candidates_batch(
                notes,
                client,
                model=settings.openai_model_fast,
                cache=cache,
                max_concurrent=settings.stage2_max_concurrent,
            )
        except Exception as exc:
            await telemetry.finish_run("failed", error=str(exc))
            raise
        elapsed = time.perf_counter() - t0
        print(f"stage2 complete in {elapsed:.1f}s (model={settings.openai_model_fast})")

    by_doc_id = {n.document_id: n for n in notes}
    for out in results:
        note = by_doc_id[out.document_id]
        doc = next(d for d in docs if d.id == out.document_id)
        print(f"\n{'=' * 72}")
        print(f"{doc.id}  |  {doc.type}  |  {doc.date}")
        print(f"  sentences: {len(note.sentences)}")
        _print_note_context(out.note_context, note)
        _print_candidates(note, out)

        out_path = STAGE2_OUTPUT_DIR / f"{out.document_id}.json"
        out_path.write_text(
            json.dumps(out.to_json(), indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        print(f"\n  wrote: {out_path.relative_to(STAGE2_OUTPUT_DIR.parent.parent)}")

    all_ok = _run_demo_checks(results, docs)
    await telemetry.finish_run("success" if all_ok else "failed")
    await _print_telemetry_summary(run_ctx.run_id)
    print("\n" + "=" * 72)
    print("OVERALL:", "PASS" if all_ok else "FAIL")
    return 0 if all_ok else 1


async def _print_telemetry_summary(run_id: str) -> None:
    rows = await telemetry.run_summary(run_id)
    if not rows:
        return
    print("\n" + "=" * 72)
    print("TELEMETRY")
    header = f"  {'stage':<7} {'call_type':<26} {'calls':>5} {'in_tok':>8} {'cached':>7} {'out_tok':>7} {'cost':>10} {'ms_sum':>8}"
    print(header)
    totals = {"calls": 0, "in_tok": 0, "cached_tok": 0, "out_tok": 0, "cost": 0, "ms": 0}
    for r in rows:
        print(f"  {r['stage']:<7} {r['call_type']:<26} {r['calls']:>5} "
              f"{r['in_tok']:>8,} {r['cached_tok']:>7,} {r['out_tok']:>7,} "
              f"${r['usd_cost']:>9.6f} {r['total_ms']:>8,}")
        totals["calls"] += r["calls"]
        totals["in_tok"] += r["in_tok"]
        totals["cached_tok"] += r["cached_tok"]
        totals["out_tok"] += r["out_tok"]
        totals["cost"] += float(r["usd_cost"])
        totals["ms"] += r["total_ms"]
    print(f"  {'TOTAL':<7} {'':<26} {totals['calls']:>5} "
          f"{totals['in_tok']:>8,} {totals['cached_tok']:>7,} {totals['out_tok']:>7,} "
          f"${totals['cost']:>9.6f} {totals['ms']:>8,}")


if __name__ == "__main__":
    # aiohttp + Windows has a known SSL transport shutdown hang
    # (aiohttp issue #1925, milestone 4.0 — not released).
    # Our work is done by the time main() returns; bypass the event-loop
    # cleanup entirely via os._exit so the CLI exits promptly.
    code = asyncio.run(main())
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
