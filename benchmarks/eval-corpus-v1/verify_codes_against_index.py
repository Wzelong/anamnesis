"""Verify every code-reference.json entry against the FAISS terminology indexes.

Two passes:
  A. Presence: does the code exist in the system's metadata at all?
  B. Retrieval: when we vector-search the display string, does the code show up
     in the top-K (default 10)?

Pass A is a sanity check. Pass B is what Stage 4 of the augmentation pipeline
relies on; an extracted phrase needs to surface its canonical code in top-K
for the LLM CodeSelector to pick it.

Usage:
  python benchmarks/eval-corpus-v1/verify_codes_against_index.py
  python benchmarks/eval-corpus-v1/verify_codes_against_index.py --top-k 20 --skip-retrieval
  python benchmarks/eval-corpus-v1/verify_codes_against_index.py --output report.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent
sys.path.insert(0, str(REPO / "backend"))

CODE_REF = ROOT / "code-reference.json"
INDEX_DIR = REPO / "data" / "indexes"

SHORT_TO_INDEX = {"SNOMED": "snomed", "RxNorm": "rxnorm", "LOINC": "loinc", "ICD-10": "icd10"}


def normalize_code(short: str, code: str) -> str:
    if short == "ICD-10":
        return code.replace(".", "")
    return code


def load_metadata(system: str) -> tuple[list[str], list[str]]:
    m = np.load(INDEX_DIR / f"{system}_metadata.npz", allow_pickle=False)
    return m["codes"].tolist(), m["displays"].tolist()


def build_code_to_indices(codes: list[str]) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for i, c in enumerate(codes):
        out.setdefault(c, []).append(i)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--skip-retrieval", action="store_true")
    parser.add_argument("--output", help="Optional path for full JSON report")
    args = parser.parse_args()

    ref = json.loads(CODE_REF.read_text(encoding="utf-8"))
    entries = ref["codes"]
    print(f"Loaded {len(entries)} entries from {CODE_REF.name}")

    by_system: dict[str, list[dict]] = {}
    for e in entries:
        by_system.setdefault(e["system_short"], []).append(e)

    metadata = {}
    for short, sysname in SHORT_TO_INDEX.items():
        if short not in by_system:
            continue
        codes, displays = load_metadata(sysname)
        metadata[short] = {
            "system": sysname,
            "codes": codes,
            "displays": displays,
            "code_to_indices": build_code_to_indices(codes),
        }
        print(f"  {short:6} index loaded: {len(codes):>7} entries")

    presence_results = []
    presence_counter = Counter()
    for short, items in by_system.items():
        meta = metadata.get(short)
        if not meta:
            print(f"WARN: no index for {short}; skipping")
            continue
        for e in items:
            norm = normalize_code(short, e["code"])
            present = norm in meta["code_to_indices"]
            presence_results.append({
                "system": short, "code": e["code"], "display": e["display"], "present": present,
            })
            presence_counter[("present" if present else "missing")] += 1
            if not present:
                print(f"  MISSING in index: {short}:{e['code']}  '{e['display']}'")

    print(f"\nPresence: {presence_counter['present']} present, {presence_counter['missing']} missing")

    retrieval_results = []
    if args.skip_retrieval:
        print("\nSkipping retrieval pass.")
    else:
        from core.coding import EmbeddingModel, IndexStore
        print(f"\nRetrieval pass (top-{args.top_k}):")
        model = EmbeddingModel()
        store = IndexStore()

        per_system_rank_counter: dict[str, Counter] = {}
        for short, items in by_system.items():
            sysname = SHORT_TO_INDEX.get(short)
            if not sysname:
                continue
            store._ensure_loaded(sysname)
            terms = [e["display"] for e in items]
            embeddings = model.encode(terms)
            ranks = []
            for e, vec in zip(items, embeddings):
                results = store.search(np.array([vec]), sysname, top_k=args.top_k)
                target = normalize_code(short, e["code"])
                rank = next((r.rank for r in results if r.code == target), None)
                ranks.append({
                    "system": short, "code": e["code"], "display": e["display"],
                    "rank": rank,
                    "top_match": {"code": results[0].code, "display": results[0].display, "score": results[0].score} if results else None,
                })
            per_system_rank_counter[short] = Counter(
                "top1" if r["rank"] == 1
                else f"top{args.top_k}" if r["rank"] is not None
                else "miss"
                for r in ranks
            )
            retrieval_results.extend(ranks)
            top1 = per_system_rank_counter[short].get("top1", 0)
            topk = per_system_rank_counter[short].get(f"top{args.top_k}", 0) + top1
            miss = per_system_rank_counter[short].get("miss", 0)
            n = len(ranks)
            print(f"  {short:6} top-1 {top1}/{n} ({top1/n*100:5.1f}%)  top-{args.top_k} {topk}/{n} ({topk/n*100:5.1f}%)  miss {miss}")

        misses = [r for r in retrieval_results if r["rank"] is None]
        if misses:
            print(f"\n{len(misses)} retrieval misses (display didn't surface canonical code in top-{args.top_k}):")
            for r in misses[:30]:
                top = r.get("top_match") or {}
                print(f"  {r['system']:6} {r['code']:12}  expected '{r['display'][:50]}'")
                print(f"           top1={top.get('code'):>12} '{top.get('display', '')[:60]}' (score={top.get('score', 0):.3f})")
            if len(misses) > 30:
                print(f"  ... and {len(misses) - 30} more")

    if args.output:
        report = {
            "presence": presence_results,
            "retrieval": retrieval_results,
            "presence_summary": dict(presence_counter),
        }
        Path(args.output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"\nFull report written to {args.output}")

    return 0 if presence_counter["missing"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
