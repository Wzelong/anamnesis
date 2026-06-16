"""Retrieval recall@K: FAISS (local index) vs live APIs, on code-reference.json.

Pass: for each ground-truth code, query the retriever with its canonical
display and check whether the code appears in top-K. This is a ceiling/sanity
measure (display-string queries favor FAISS, which indexed that string); the
realistic messy-input + LLM-variant comparison is bench_retrieval_variants.py.

Usage:  UMLS_API_KEY=... python benchmarks/eval-corpus-v1/bench_retrieval.py [--top-k 10] [--api-only]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent
sys.path.insert(0, str(REPO / "backend"))

from core.retrieval import ApiRetriever, FaissRetriever  # noqa: E402

SHORT_TO_SYS = {"SNOMED": "snomed", "ICD-10": "icd10", "RxNorm": "rxnorm", "LOINC": "loinc"}


def norm(code: str, system: str) -> str:
    code = code.strip().upper()
    return code.replace(".", "") if system == "icd10" else code


async def recall_api(entries, top_k, concurrency=5):
    api = ApiRetriever()
    sem = asyncio.Semaphore(concurrency)
    hits = defaultdict(int)
    totals = defaultdict(int)
    misses = []

    async def one(e):
        system = SHORT_TO_SYS[e["system_short"]]
        async with sem:
            try:
                results = await api.search(e["display"], system, top_k)
            except Exception as ex:
                results = []
                misses.append((e["system_short"], e["code"], e["display"], f"ERR {ex}"))
        codes = {norm(r.code, system) for r in results}
        totals[system] += 1
        if norm(e["code"], system) in codes:
            hits[system] += 1
        else:
            misses.append((e["system_short"], e["code"], e["display"], "not in top-k"))

    await asyncio.gather(*(one(e) for e in entries))
    await api.aclose()
    return hits, totals, misses


def recall_faiss(entries, top_k):
    faiss = FaissRetriever()
    hits = defaultdict(int)
    totals = defaultdict(int)
    misses = []

    async def one(e):
        system = SHORT_TO_SYS[e["system_short"]]
        results = await faiss.search(e["display"], system, top_k)
        codes = {norm(r.code, system) for r in results}
        totals[system] += 1
        if norm(e["code"], system) in codes:
            hits[system] += 1
        else:
            misses.append((e["system_short"], e["code"], e["display"], "not in top-k"))

    async def runner():
        for e in entries:
            await one(e)

    asyncio.run(runner())
    return hits, totals, misses


def report(name, hits, totals, misses, elapsed):
    print(f"\n===== {name}  (recall@k, {elapsed:.1f}s) =====")
    tot_h = sum(hits.values())
    tot_t = sum(totals.values())
    for sysk in ("snomed", "icd10", "rxnorm", "loinc"):
        if totals[sysk]:
            print(f"  {sysk:<8} {hits[sysk]:>2}/{totals[sysk]:<2}  {hits[sysk]/totals[sysk]*100:5.1f}%")
    print(f"  {'TOTAL':<8} {tot_h:>2}/{tot_t:<2}  {tot_h/tot_t*100:5.1f}%")
    if misses:
        print(f"  misses ({len(misses)}):")
        for s, c, d, why in misses[:25]:
            print(f"    [{s}] {c} {d[:48]} — {why}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--api-only", action="store_true")
    args = ap.parse_args()

    entries = json.loads((ROOT / "code-reference.json").read_text())["codes"]

    t0 = time.perf_counter()
    h, t, m = asyncio.run(recall_api(entries, args.top_k))
    report("LIVE API", h, t, m, time.perf_counter() - t0)

    if not args.api_only:
        t0 = time.perf_counter()
        h, t, m = recall_faiss(entries, args.top_k)
        report("FAISS", h, t, m, time.perf_counter() - t0)


if __name__ == "__main__":
    main()
