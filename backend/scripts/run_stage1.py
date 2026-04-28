"""CLI: FHIR -> Stage 1 (preprocess) -> pretty-print + cache to JSON.

Run from backend/:
    python -m scripts.run_stage1 [--patient-id=...] [--doc-id=...]

If --patient-id is omitted, looks up the demo patient by MRN.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from core.preprocess import preprocess_document
from fhir.bootstrap import MRN_SYSTEM, MRN_VALUE
from fhir.client import FhirClient
from fhir.read import read_documents

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "stage1"


async def _resolve_patient_id(client: FhirClient, override: str | None) -> str:
    if override:
        return override
    bundle = await client.search("Patient", {"identifier": f"{MRN_SYSTEM}|{MRN_VALUE}"})
    entries = (bundle or {}).get("entry", [])
    for e in entries:
        pid = (e.get("resource") or {}).get("id")
        if pid:
            return pid
    raise RuntimeError(
        f"No patient found for MRN {MRN_VALUE}. Run `python -m scripts.bootstrap` first."
    )


def _dump(note) -> dict:
    return {
        "document_id": note.document_id,
        "document_date": note.document_date.isoformat() if note.document_date else None,
        "original_text": note.original_text,
        "numbered_note": note.numbered_note,
        "sentences": [asdict(s) for s in note.sentences],
    }


def _print_note(note, index: int, total: int) -> bool:
    print(f"\n{'=' * 72}")
    print(f"[{index}/{total}] {note.document_id}")
    print(f"  date:      {note.document_date}")
    print(f"  sentences: {len(note.sentences)}")
    print(f"  chars:     {len(note.original_text)}")

    print("\n  first 5 sentences:")
    for s in note.sentences[:5]:
        preview = s.text.replace("\n", " ")
        if len(preview) > 120:
            preview = preview[:117] + "..."
        print(f"    [{s.number}] ({s.start}-{s.end}) {preview}")

    ok = sum(1 for s in note.sentences if s.text == note.original_text[s.start:s.end])
    total_spans = len(note.sentences)
    label = "PASS" if ok == total_spans else "FAIL"
    print(f"\n  roundtrip: {label} {ok}/{total_spans}")
    return ok == total_spans


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--patient-id", default=None)
    parser.add_argument("--doc-id", default=None, help="filter to a single DocumentReference id")
    args = parser.parse_args()

    load_dotenv()
    url = os.environ.get("DEV_FHIR_BASE_URL")
    token = os.environ.get("DEV_FHIR_TOKEN")
    if not url or not token:
        print("error: DEV_FHIR_BASE_URL and DEV_FHIR_TOKEN must be set in .env", file=sys.stderr)
        return 2

    client = FhirClient(url, token)
    patient_id = await _resolve_patient_id(client, args.patient_id)
    print(f"Patient/{patient_id}")

    docs = await read_documents(client, patient_id)
    if args.doc_id:
        docs = [d for d in docs if d.id == args.doc_id]
    if not docs:
        print("no DocumentReferences found", file=sys.stderr)
        return 1

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    all_ok = True
    for i, doc in enumerate(docs, 1):
        note = preprocess_document(doc)
        all_ok &= _print_note(note, i, len(docs))
        out = CACHE_DIR / f"{note.document_id}.json"
        out.write_text(json.dumps(_dump(note), indent=2), encoding="utf-8")
        print(f"  wrote: {out.relative_to(CACHE_DIR.parent.parent)}")

    print(f"\n{'=' * 72}")
    print("OVERALL:", "PASS" if all_ok else "FAIL")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
