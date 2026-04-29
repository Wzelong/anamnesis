"""Smoke test FAISS indexes against known medical concepts."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from core.coding import IndexStore, EmbeddingModel, SearchResult

DEFAULT_INDEX_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "indexes"

SMOKE_TESTS = [
    {"query": "angina pectoris", "system": "snomed", "expected_code": "17828002"},
    {"query": "acute myocardial infarction", "system": "snomed", "expected_code": "57054005"},
    {"query": "type 2 diabetes mellitus", "system": "snomed", "expected_code": "44054006"},
    {"query": "essential hypertension", "system": "snomed", "expected_code": "59621000"},
    {"query": "cardiac catheterization", "system": "snomed", "expected_code": "41976001"},

    {"query": "metoprolol succinate 25 mg", "system": "rxnorm", "expected_code": "1370489"},
    {"query": "lisinopril 10 mg tablet", "system": "rxnorm", "expected_code": "314076"},
    {"query": "atorvastatin 40 mg", "system": "rxnorm", "expected_code": "597983"},
    {"query": "aspirin 81 mg", "system": "rxnorm", "expected_code": "315431"},
    {"query": "metformin 1000 mg", "system": "rxnorm", "expected_code": "316255"},

    {"query": "tobacco smoking status", "system": "loinc", "expected_code": "72166-2"},
    {"query": "systolic blood pressure", "system": "loinc", "expected_code": "8480-6"},
    {"query": "body weight", "system": "loinc", "expected_code": "29463-7"},
    {"query": "hemoglobin a1c", "system": "loinc", "expected_code": "4548-4"},

    {"query": "essential hypertension", "system": "icd10", "expected_code": "I10"},
    {"query": "type 2 diabetes", "system": "icd10", "expected_code": "E119"},
    {"query": "angina pectoris unspecified", "system": "icd10", "expected_code": "I209"},
]


def run_tests(index_dir: Path, top_k: int = 20) -> int:
    store = IndexStore(index_dir)
    model = EmbeddingModel()

    print("Loading embedding model (first call)...")
    t0 = time.time()
    model.encode(["warmup"])
    print(f"Model loaded in {time.time() - t0:.1f}s\n")

    passed = 0
    failed = 0

    for test in SMOKE_TESTS:
        query = test["query"]
        system = test["system"]
        expected = test["expected_code"]

        embedding = model.encode([query])
        results = store.search(embedding, system, top_k)

        found_rank = None
        found_score = None
        for r in results:
            if r.code == expected or r.code.startswith(expected) or expected.startswith(r.code):
                found_rank = r.rank
                found_score = r.score
                break

        if found_rank is not None:
            passed += 1
            print(f"  PASS  {system:>6}: \"{query}\" -> expected {expected} found at rank {found_rank} (score {found_score:.4f})")
        else:
            failed += 1
            top3 = ", ".join(f"{r.code} \"{r.display[:40]}\" ({r.score:.3f})" for r in results[:3])
            print(f"  FAIL  {system:>6}: \"{query}\" -> expected {expected} NOT in top {top_k}")
            print(f"         Top 3: {top3}")

    total = passed + failed
    print(f"\n{'=' * 50}")
    print(f"  {passed}/{total} passed (threshold: {total - 1}/{total})")
    print(f"{'=' * 50}")

    if failed > 1:
        print("  FAILED: more than 1 test failed — investigate model mismatch")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test FAISS indexes")
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR)
    parser.add_argument("--top-k", type=int, default=20)
    args = parser.parse_args()
    return run_tests(args.index_dir, args.top_k)


if __name__ == "__main__":
    sys.exit(main())
