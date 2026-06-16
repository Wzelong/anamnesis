"""Realistic retrieval recall: messy clinical spans -> codes, FAISS vs API,
with and without LLM-generated terminology-style search queries.

Input is each label's verbatim_span (real note phrasing), NOT the canonical
display — so neither retriever gets the circular advantage of querying with a
string already in its index. Scoring credits the expected code OR any
candidate whose display matches the expected concept (so legacy->current code
swaps are not counted as misses). Fixed-code vitals/smoking are excluded since
the real pipeline short-circuits them before retrieval.

Usage:  OPENAI_API_KEY=... UMLS_API_KEY=... \
        python benchmarks/eval-corpus-v1/bench_retrieval_variants.py [--limit N]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent
sys.path.insert(0, str(REPO / "backend"))

from openai import AsyncOpenAI  # noqa: E402

from config import settings  # noqa: E402
from core.code_search_terms import generate_search_queries  # noqa: E402
from core.retrieval import ApiRetriever, FaissRetriever  # noqa: E402

SHORT_TO_SYS = {"SNOMED": "snomed", "ICD-10": "icd10", "RxNorm": "rxnorm", "LOINC": "loinc"}
CAT_TO_TYPE = {
    "condition": "Condition", "medication": "MedicationRequest", "allergy": "AllergyIntolerance",
    "observation": "Observation", "procedure": "Procedure", "family_history": "FamilyMemberHistory",
}
FIXED_LOINC = {"29463-7", "85354-9", "8480-6", "8462-4", "8302-2", "8310-5", "8867-4",
               "9279-1", "39156-5", "59408-5", "2708-6", "9843-4", "72166-2"}
FIXED_SNOMED_SMOKING = {"8517006", "266919005", "77176002", "266927001", "230056004"}
_TAG = re.compile(r"\((disorder|finding|procedure|product|substance|situation|qualifier value)\)")


def norm_code(code: str, system: str) -> str:
    code = code.strip().upper()
    return code.replace(".", "") if system == "icd10" else code


def norm_display(d: str) -> str:
    d = _TAG.sub("", d.lower())
    d = re.sub(r"\b(nos|unspecified)\b", "", d)
    return re.sub(r"[^a-z0-9]+", " ", d).strip()


def load_facts(limit=None):
    facts = []
    for f in sorted((ROOT / "labels").glob("*.json")):
        d = json.loads(f.read_text())
        for fact in d.get("expected_facts", []):
            span = " ".join(fact["verbatim_span"].split())
            rtype = CAT_TO_TYPE.get(fact["category"], "Condition")
            for ec in fact.get("expected_codes", []):
                system = SHORT_TO_SYS.get(ec["system"])
                if not system:
                    continue
                if system == "loinc" and ec["code"] in FIXED_LOINC:
                    continue
                if system == "snomed" and ec["code"] in FIXED_SNOMED_SMOKING:
                    continue
                facts.append({
                    "id": f'{fact["id"]}:{system}', "text": span, "resource_type": rtype,
                    "system": system, "code": ec["code"], "display": ec["display"],
                })
    return facts[:limit] if limit else facts


def hit(fact, results) -> bool:
    want_code = norm_code(fact["code"], fact["system"])
    want_disp = norm_display(fact["display"])
    for r in results:
        if norm_code(r.code, fact["system"]) == want_code:
            return True
        if want_disp and norm_display(r.display) == want_disp:
            return True
    return False


async def union_search(retriever, queries, system, top_k=10):
    lists = await asyncio.gather(
        *(retriever.search(q, system, top_k) for q in queries), return_exceptions=True
    )
    out, seen = [], set()
    for lst in lists:
        if isinstance(lst, Exception):
            continue
        for r in lst:
            if r.code not in seen:
                seen.add(r.code)
                out.append(r)
    return out


async def run_arm(name, retriever, facts, variants, sem):
    raw_hits = var_hits = 0
    by_sys_raw = defaultdict(lambda: [0, 0])
    by_sys_var = defaultdict(lambda: [0, 0])

    async def one(fact):
        nonlocal raw_hits, var_hits
        async with sem:
            raw = await union_search(retriever, [fact["text"]], fact["system"])
            var = await union_search(retriever, variants.get(fact["id"], [fact["text"]]), fact["system"])
        sysk = fact["system"]
        by_sys_raw[sysk][1] += 1
        by_sys_var[sysk][1] += 1
        if hit(fact, raw):
            raw_hits += 1
            by_sys_raw[sysk][0] += 1
        if hit(fact, var):
            var_hits += 1
            by_sys_var[sysk][0] += 1

    t0 = time.perf_counter()
    await asyncio.gather(*(one(f) for f in facts))
    n = len(facts)
    print(f"\n===== {name}  ({time.perf_counter()-t0:.1f}s, n={n}) =====")
    print(f"  raw span      {raw_hits}/{n}  {raw_hits/n*100:5.1f}%")
    print(f"  + variants    {var_hits}/{n}  {var_hits/n*100:5.1f}%   (lift {(var_hits-raw_hits)/n*100:+.1f})")
    for sysk in ("snomed", "icd10", "rxnorm", "loinc"):
        if by_sys_var[sysk][1]:
            rh, rt = by_sys_raw[sysk]
            vh, vt = by_sys_var[sysk]
            print(f"    {sysk:<7} raw {rh:>2}/{rt:<2} {rh/rt*100:5.1f}%  | +var {vh:>2}/{vt:<2} {vh/vt*100:5.1f}%")
    return var_hits / n


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    facts = load_facts(args.limit)
    print(f"loaded {len(facts)} (fact,system) retrieval targets")

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    print("generating search-term variants...")
    t0 = time.perf_counter()
    jobs = [{"id": f["id"], "text": f["text"], "resource_type": f["resource_type"], "system": f["system"]} for f in facts]
    variants = await generate_search_queries(jobs, client, model=settings.openai_model_fast)
    print(f"  done ({time.perf_counter()-t0:.1f}s).  sample:")
    for f in facts[:4]:
        print(f"    [{f['system']}] {f['text'][:42]!r} -> {variants.get(f['id'])}")

    sem = asyncio.Semaphore(6)
    api = ApiRetriever()
    await run_arm("LIVE API", api, facts, variants, sem)
    await api.aclose()
    await run_arm("FAISS", FaissRetriever(), facts, variants, asyncio.Semaphore(8))


if __name__ == "__main__":
    asyncio.run(main())
