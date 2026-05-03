"""Run the Anamnesis pipeline against fixture+note pairs and score against augmentation_labels.

Usage:
  python benchmarks/eval-corpus-v1/run_augmentation_benchmark.py
  python benchmarks/eval-corpus-v1/run_augmentation_benchmark.py --only C1,E1
  python benchmarks/eval-corpus-v1/run_augmentation_benchmark.py --output report.json
  python benchmarks/eval-corpus-v1/run_augmentation_benchmark.py --runs 5 --output stability.json

Captures Stage 5 (with DUPLICATEs) and Stage 6 (Proposals) so all four classifications
can be scored. Maps reconciler output to corpus fact_ids by primary code first, then
ingredient-display normalization for medications, then citation char-span overlap.

With --runs N (N>1), runs the full corpus N times with stage2/3 caches cleared
between runs. Reports per-fact stability (stable-right / stable-wrong / flaky)
to distinguish real bugs from reasoning-model variance.
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
from core.reconcile import reconcile, _normalize_ingredient
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

    # Three-pass mapping. Mirrors the production reconciler's matching strategy
    # so the benchmark scores what the system actually does, not what the
    # mapper happens to recognize. Pass order is intentional: stricter matches
    # first to prevent loose matches from claiming a fact_id before the right
    # candidate is checked.
    actual_by_fact: dict[str, str] = {}
    matched_result_by_fact: dict[str, object] = {}
    matched: set[int] = set()

    def record(fid: str, result):
        actual_by_fact.setdefault(fid, result.classification)
        matched_result_by_fact.setdefault(fid, result)

    # Pass 1: exact code overlap across all candidates.
    for i, result in enumerate(stage5.results):
        cand_codes = candidate_codes(result.candidate)
        if not cand_codes:
            continue
        for f in ext["expected_facts"]:
            if cand_codes & fact_codes(f):
                record(f["id"], result)
                matched.add(i)
                break

    # Pass 2: ingredient overlap for MedicationRequest only. Reuses
    # _normalize_ingredient from reconcile.py — same logic that fires in
    # production when extractor picks a different RxNorm granularity (e.g.
    # "apixaban 5 MG" 1364444 vs chart "apixaban" 1364430). Limited to meds
    # to avoid collisions on similarly-named conditions.
    for i, result in enumerate(stage5.results):
        if i in matched or result.candidate.resource_type != "MedicationRequest":
            continue
        cand_ings = {
            _normalize_ingredient(c.get("display", ""))
            for c in result.candidate.item.get("coding", []) or []
        }
        cand_ings.discard("")
        if not cand_ings:
            continue
        for f in ext["expected_facts"]:
            if f["id"] in actual_by_fact or f.get("category") != "medication_request":
                continue
            fact_ings = {
                _normalize_ingredient(c.get("display", ""))
                for c in f.get("expected_codes", []) or []
            }
            fact_ings.discard("")
            if cand_ings & fact_ings:
                record(f["id"], result)
                matched.add(i)
                break

    # Pass 3: citation span overlap for remaining unmatched facts.
    for i, result in enumerate(stage5.results):
        if i in matched:
            continue
        cand_spans = candidate_spans(result.candidate, notes_by_doc)
        if not cand_spans:
            continue
        for f in ext["expected_facts"]:
            if f["id"] in actual_by_fact:
                continue
            fs = fact_span(note_text, f)
            if fs and any(overlap(cs, fs) for cs in cand_spans):
                record(f["id"], result)
                break

    fact_by_id = {f["id"]: f for f in ext["expected_facts"]}
    tier = ext.get("tier")
    rows = []
    for action in aug["expected_actions"]:
        fid = action["fact_id"]
        expected = action["action"]
        actual = actual_by_fact.get(fid, "MISSING")
        result = matched_result_by_fact.get(fid)
        ext_fact = fact_by_id.get(fid, {})

        if result is None:
            code_matched = None
            provenance_count = 0
        else:
            cand_codes = candidate_codes(result.candidate)
            code_matched = bool(cand_codes & fact_codes(ext_fact))
            provenance_count = sum(
                len(getattr(sr, "source_sentences", []) or [])
                for sr in getattr(result.candidate, "source_refs", []) or []
            )

        expected_systems = sorted({
            c.get("system") for c in ext_fact.get("expected_codes", []) if c.get("code")
        })

        rows.append({
            "note": stem,
            "tier": tier,
            "category": ext_fact.get("category"),
            "fact_id": fid,
            "expected": expected,
            "actual": actual,
            "hit": actual == expected,
            "expected_systems": expected_systems,
            "code_matched": code_matched,
            "provenance_count": provenance_count,
        })

    non_fact_by_id = {nf["id"]: nf for nf in ext.get("expected_non_facts", [])}
    trap_results = []
    for nf_action in aug.get("expected_non_fact_actions", []):
        nf_id = nf_action["non_fact_id"]
        nf = non_fact_by_id.get(nf_id)
        if not nf:
            continue
        trap_span = fact_span(note_text, nf)
        rejected = True
        if trap_span:
            for result in stage5.results:
                cand_spans = candidate_spans(result.candidate, notes_by_doc)
                if any(overlap(cs, trap_span) for cs in cand_spans):
                    rejected = False
                    break
        trap_results.append({
            "note": stem,
            "non_fact_id": nf_id,
            "trap_type": nf.get("trap_type"),
            "rejected": rejected,
        })

    extracted_fact_ids = set(actual_by_fact.keys())
    expected_fact_ids = {a["fact_id"] for a in aug["expected_actions"]}
    spurious = sorted(extracted_fact_ids - expected_fact_ids)

    return rows, spurious, trap_results


async def run_full_pass(only, client) -> tuple[list[dict], dict, list[dict]]:
    rows = []
    spurious = {}
    traps = []
    for stem, aug, ext, note_path, bundle_path in load_pairs(only):
        print(f"  {stem} (bundle={aug['paired_bundle']}) ...", flush=True)
        r, sp, tr = await run_one(stem, aug, ext, note_path, bundle_path, client)
        rows.extend(r)
        spurious[stem] = sp
        traps.extend(tr)
    return rows, spurious, traps


def clear_pipeline_caches() -> None:
    import shutil
    for sub in ("stage2_output", "stage3"):
        target = CACHE_ROOT / sub
        if target.exists():
            shutil.rmtree(target)


def summarize_runs(per_run_rows: list[list[dict]]) -> dict:
    fact_records: dict[str, dict] = {}
    for run_idx, rows in enumerate(per_run_rows):
        for row in rows:
            key = (row["note"], row["fact_id"])
            rec = fact_records.setdefault(key, {
                "note": row["note"],
                "fact_id": row["fact_id"],
                "expected": row["expected"],
                "classifications": Counter(),
            })
            rec["classifications"][row["actual"]] += 1

    n_runs = len(per_run_rows)
    facts_summary = []
    for (note, fid), rec in fact_records.items():
        c = rec["classifications"]
        most_common, top_count = c.most_common(1)[0]
        agreement = top_count / n_runs
        hits = c.get(rec["expected"], 0)
        if hits == n_runs:
            stability = "stable_right"
        elif hits == 0:
            stability = "stable_wrong"
        else:
            stability = "flaky"
        facts_summary.append({
            "note": note,
            "fact_id": fid,
            "expected": rec["expected"],
            "most_common_actual": most_common,
            "agreement": round(agreement, 2),
            "hits_over_runs": f"{hits}/{n_runs}",
            "distribution": dict(c),
            "stability": stability,
        })
    facts_summary.sort(key=lambda x: (x["stability"] != "stable_wrong", x["stability"] != "flaky", x["fact_id"]))

    counts = Counter(f["stability"] for f in facts_summary)

    per_class_runs: dict[str, list[float]] = defaultdict(list)
    for rows in per_run_rows:
        per_class_total: Counter = Counter()
        per_class_hit: Counter = Counter()
        for row in rows:
            per_class_total[row["expected"]] += 1
            if row["hit"]:
                per_class_hit[row["expected"]] += 1
        for cls, total in per_class_total.items():
            per_class_runs[cls].append(per_class_hit.get(cls, 0) / total if total else 0.0)

    per_class_summary = {}
    for cls, vals in per_class_runs.items():
        per_class_summary[cls] = {
            "mean": round(sum(vals) / len(vals), 3),
            "min": round(min(vals), 3),
            "max": round(max(vals), 3),
            "n_runs": len(vals),
        }

    overall_per_run = [
        sum(1 for r in rows if r["hit"]) / len(rows) if rows else 0.0
        for rows in per_run_rows
    ]
    overall = {
        "mean": round(sum(overall_per_run) / len(overall_per_run), 3),
        "min": round(min(overall_per_run), 3),
        "max": round(max(overall_per_run), 3),
        "per_run": [round(x, 3) for x in overall_per_run],
    }

    return {
        "n_runs": n_runs,
        "stability_counts": dict(counts),
        "overall_accuracy": overall,
        "per_class_accuracy": per_class_summary,
        "facts": facts_summary,
    }


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="Comma-separated note IDs (e.g. C1,E1)")
    parser.add_argument("--output", help="Write full report JSON here")
    parser.add_argument("--runs", type=int, default=1,
                        help="Number of full-corpus passes for stability analysis (default 1). "
                             "When >1, clears stage2/3 caches between runs.")
    args = parser.parse_args()

    only = {x.strip() for x in args.only.split(",")} if args.only else None
    if not settings.openai_api_key:
        print("ERROR: OPENAI_API_KEY not set", file=sys.stderr)
        return 2

    client = AsyncOpenAI(api_key=settings.openai_api_key)

    if args.runs <= 1:
        print("running single pass...", flush=True)
        rows, spurious, _ = await run_full_pass(only, client)
        confusion: dict[str, Counter] = defaultdict(Counter)
        per_tier: dict[str, Counter] = defaultdict(Counter)
        for r in rows:
            confusion[r["expected"]][r["actual"]] += 1
        ext_by_stem = {p[0]: p[2] for p in load_pairs(only)}
        for r in rows:
            per_tier[ext_by_stem[r["note"]]["tier"]]["hit" if r["hit"] else "miss"] += 1

        overall_hits = sum(1 for r in rows if r["hit"])
        summary = {
            "totals": {"facts": len(rows), "hits": overall_hits, "misses": len(rows) - overall_hits},
            "confusion": {k: dict(v) for k, v in confusion.items()},
            "per_tier": {k: dict(v) for k, v in per_tier.items()},
            "spurious_per_note": spurious,
        }
        print()
        print(json.dumps(summary, indent=2))

        if args.output:
            report = {**summary, "rows": rows}
            Path(args.output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(f"\nFull report written to {args.output}")

        return 0 if overall_hits == len(rows) else 1

    per_run_rows: list[list[dict]] = []
    for run_idx in range(args.runs):
        print(f"\n=== run {run_idx + 1}/{args.runs} ===", flush=True)
        if run_idx > 0:
            clear_pipeline_caches()
        rows, _, _ = await run_full_pass(only, client)
        per_run_rows.append(rows)

    stability = summarize_runs(per_run_rows)

    print()
    print(f"=== Stability report (N={stability['n_runs']} runs) ===")
    print(f"\nOverall accuracy: mean={stability['overall_accuracy']['mean']:.1%}  "
          f"range={stability['overall_accuracy']['min']:.1%}-{stability['overall_accuracy']['max']:.1%}  "
          f"per-run={stability['overall_accuracy']['per_run']}")
    print(f"\nStability counts: {stability['stability_counts']}")
    print(f"\nPer-classification accuracy across runs:")
    for cls, s in stability["per_class_accuracy"].items():
        print(f"  {cls:12} mean={s['mean']:.1%}  range={s['min']:.1%}-{s['max']:.1%}")

    print(f"\nStable-wrong (always miss expected — real bugs):")
    for f in stability["facts"]:
        if f["stability"] == "stable_wrong":
            print(f"  {f['fact_id']:8}  expected={f['expected']:12}  always={f['most_common_actual']:12}  dist={f['distribution']}")
    print(f"\nFlaky (variance):")
    for f in stability["facts"]:
        if f["stability"] == "flaky":
            print(f"  {f['fact_id']:8}  expected={f['expected']:12}  hits={f['hits_over_runs']}  dist={f['distribution']}")

    if args.output:
        Path(args.output).write_text(json.dumps(stability, indent=2) + "\n", encoding="utf-8")
        print(f"\nFull stability report written to {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
