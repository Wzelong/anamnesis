"""Run the Anamnesis pipeline against fixture+note pairs and score against augmentation_labels.

Usage:
  python benchmarks/eval-corpus-v1/run_augmentation_benchmark.py
  python benchmarks/eval-corpus-v1/run_augmentation_benchmark.py --only C1,E1
  python benchmarks/eval-corpus-v1/run_augmentation_benchmark.py --output report.json

Captures Stage 5 (with DUPLICATEs) and Stage 6 (Proposals) so all four classifications
can be scored. Maps reconciler output to corpus fact_ids by primary code first, then
citation char-span overlap with verbatim_span as a tiebreaker.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent
sys.path.insert(0, str(REPO / "backend"))

from openai import AsyncOpenAI

from config import settings
from core.augment import assemble_proposals
from core.cache import JsonCache
from core.code_candidates import code_candidates
from core.extraction import extract_candidates_batch, merge_across_notes
from core.preprocess import preprocess_documents
from core.reconcile import reconcile
from fhir.local_bundle import load_demo_data
from fhir.models import Document

NOTES_DIR = ROOT / "notes"
LABELS_DIR = ROOT / "labels"
AUG_DIR = ROOT / "augmentation_labels"
FIXTURES_DIR = ROOT / "fixtures"
CACHE_ROOT = REPO / "backend" / ".cache"

SYSTEM_TO_SHORT = {
    "http://snomed.info/sct": "SNOMED",
    "http://hl7.org/fhir/sid/icd-10-cm": "ICD-10",
    "http://loinc.org": "LOINC",
    "http://www.nlm.nih.gov/research/umls/rxnorm": "RxNorm",
}


def load_pairs(only: set[str] | None):
    for label_path in sorted(AUG_DIR.glob("*.json")):
        stem = label_path.stem
        note_id = stem.split("-", 1)[0]
        if only and note_id not in only:
            continue
        aug = json.loads(label_path.read_text(encoding="utf-8"))
        ext = json.loads((LABELS_DIR / f"{stem}.json").read_text(encoding="utf-8"))
        note_path = NOTES_DIR / f"{stem}.txt"
        bundle_path = FIXTURES_DIR / f"{aug['paired_bundle']}.json"
        yield stem, aug, ext, note_path, bundle_path


async def execute_pipeline(patient_context, documents, client):
    notes = preprocess_documents(documents)
    model = settings.openai_model_fast
    stage2 = await extract_candidates_batch(
        notes, client, model=model, cache=JsonCache(CACHE_ROOT / "stage2_output"),
    )
    stage3 = await merge_across_notes(
        stage2, client, model=model, cache=JsonCache(CACHE_ROOT / "stage3"),
    )
    stage4 = await code_candidates(stage3, client, model=model)
    stage5 = await reconcile(stage4, patient_context, client, model=model)
    return notes, stage5, None


def candidate_codes(candidate) -> set[tuple[str, str]]:
    codes: set[tuple[str, str]] = set()
    item = candidate.item if hasattr(candidate, "item") else {}
    for c in item.get("coding", []) or []:
        sysname = c.get("system") or ""
        code = c.get("code") or ""
        short = SYSTEM_TO_SHORT.get(sysname, sysname)
        if code:
            codes.add((short, code))
    return codes


def fact_codes(fact) -> set[tuple[str, str]]:
    return {(c.get("system"), c.get("code")) for c in fact.get("expected_codes", []) if c.get("code")}


def candidate_spans(candidate, notes_by_doc) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for sr in getattr(candidate, "source_refs", []) or []:
        note = notes_by_doc.get(sr.document_id)
        if not note:
            continue
        for n in getattr(sr, "source_sentences", []) or []:
            if 1 <= n <= len(note.sentences):
                s = note.sentences[n - 1]
                spans.append((s.start, s.end))
    return spans


def fact_span(note_text: str, fact) -> tuple[int, int] | None:
    span = fact.get("verbatim_span")
    if not span:
        return None
    idx = note_text.find(span)
    if idx < 0:
        return None
    return (idx, idx + len(span))


def overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return not (a[1] <= b[0] or b[1] <= a[0])


def map_candidate_to_fact(candidate, notes_by_doc, ext_facts, note_text) -> str | None:
    cand_codes = candidate_codes(candidate)
    for f in ext_facts:
        if cand_codes & fact_codes(f):
            return f["id"]
    cand_spans = candidate_spans(candidate, notes_by_doc)
    for f in ext_facts:
        fs = fact_span(note_text, f)
        if not fs:
            continue
        if any(overlap(cs, fs) for cs in cand_spans):
            return f["id"]
    return None


async def run_one(stem, aug, ext, note_path, bundle_path, client):
    note_text = note_path.read_text(encoding="utf-8")
    pc, _ = load_demo_data(bundle_path)
    docs = [Document(
        id=aug["note_id"], type="Progress note",
        date="2026-04-01", author="bench",
        text=note_text, encounter_id=None,
    )]
    notes, stage5, _ = await execute_pipeline(pc, docs, client)
    notes_by_doc = {n.document_id: n for n in notes}

    # Two-pass mapping: code-overlap first across all candidates, then citation
    # overlap for remaining unmatched facts. Prevents a text-only candidate from
    # claiming a fact_id via span overlap before a properly-coded sibling is
    # checked.
    actual_by_fact: dict[str, str] = {}
    matched_by_code: set[int] = set()
    for i, result in enumerate(stage5.results):
        cand_codes = candidate_codes(result.candidate)
        if not cand_codes:
            continue
        for f in ext["expected_facts"]:
            if cand_codes & fact_codes(f):
                actual_by_fact.setdefault(f["id"], result.classification)
                matched_by_code.add(i)
                break
    for i, result in enumerate(stage5.results):
        if i in matched_by_code:
            continue
        cand_spans = candidate_spans(result.candidate, notes_by_doc)
        if not cand_spans:
            continue
        for f in ext["expected_facts"]:
            if f["id"] in actual_by_fact:
                continue
            fs = fact_span(note_text, f)
            if fs and any(overlap(cs, fs) for cs in cand_spans):
                actual_by_fact.setdefault(f["id"], result.classification)
                break

    rows = []
    for action in aug["expected_actions"]:
        fid = action["fact_id"]
        expected = action["action"]
        actual = actual_by_fact.get(fid, "MISSING")
        rows.append({
            "note": stem,
            "fact_id": fid,
            "expected": expected,
            "actual": actual,
            "hit": actual == expected,
        })

    extracted_fact_ids = set(actual_by_fact.keys())
    expected_fact_ids = {a["fact_id"] for a in aug["expected_actions"]}
    spurious = sorted(extracted_fact_ids - expected_fact_ids)

    return rows, spurious


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="Comma-separated note IDs (e.g. C1,E1)")
    parser.add_argument("--output", help="Write full report JSON here")
    args = parser.parse_args()

    only = {x.strip() for x in args.only.split(",")} if args.only else None
    if not settings.openai_api_key:
        print("ERROR: OPENAI_API_KEY not set", file=sys.stderr)
        return 2

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    confusion: dict[str, Counter] = defaultdict(Counter)
    per_tier: dict[str, Counter] = defaultdict(Counter)
    all_rows = []
    all_spurious = {}

    for stem, aug, ext, note_path, bundle_path in load_pairs(only):
        print(f"running {stem} (bundle={aug['paired_bundle']}) ...", flush=True)
        rows, spurious = await run_one(stem, aug, ext, note_path, bundle_path, client)
        all_rows.extend(rows)
        all_spurious[stem] = spurious
        for r in rows:
            confusion[r["expected"]][r["actual"]] += 1
            per_tier[ext["tier"]]["hit" if r["hit"] else "miss"] += 1

    overall_hits = sum(1 for r in all_rows if r["hit"])
    summary = {
        "totals": {"facts": len(all_rows), "hits": overall_hits, "misses": len(all_rows) - overall_hits},
        "confusion": {k: dict(v) for k, v in confusion.items()},
        "per_tier": {k: dict(v) for k, v in per_tier.items()},
        "spurious_per_note": all_spurious,
    }

    print()
    print(json.dumps(summary, indent=2))

    if args.output:
        report = {**summary, "rows": all_rows}
        Path(args.output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"\nFull report written to {args.output}")

    return 0 if overall_hits == len(all_rows) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
