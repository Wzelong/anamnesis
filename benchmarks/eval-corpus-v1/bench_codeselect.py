"""End-to-end code accuracy: messy span -> variants -> retrieve -> LLM select.

The deciding metric for FAISS-vs-API: does the pipeline assign the CORRECT
code, not just surface it in candidates. Reuses the real selector prompt and
refine loop. Scoring credits the expected code OR a selection whose display
matches the expected concept (so legacy->current swaps count as correct).

Usage:  python benchmarks/eval-corpus-v1/bench_codeselect.py [--limit N]
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(ROOT))

from openai import AsyncOpenAI  # noqa: E402

from bench_retrieval_variants import (  # noqa: E402
    load_facts, norm_code, norm_display, union_search,
)
from config import settings  # noqa: E402
from core.code_search_terms import generate_search_queries  # noqa: E402
from core.extraction import parse_structured  # noqa: E402
from core.prompts import PROMPT_CODE_SELECT  # noqa: E402
from core.retrieval import ApiRetriever, FaissRetriever  # noqa: E402
from core.schemas import CodeSelectorResult  # noqa: E402


def _fmt(cands):
    return "\n".join(f"[{r.rank}] {r.code} — {r.display}" for r in cands)


async def select(term, system, retriever, cands, client, model):
    if not cands:
        return None, {}
    disp = {r.code: r.display for r in cands}
    prompt = PROMPT_CODE_SELECT.format(system=system.upper())
    res = await parse_structured(
        client, model, prompt, f'Term: "{term}"\n\nCandidates:\n{_fmt(cands)}',
        CodeSelectorResult, stage="stage4", call_type=f"sel_{system}",
    )
    if res is None:
        return None, disp
    if res.code:
        return res.code, disp
    if res.refined_search_term:
        rc = await retriever.search(res.refined_search_term, system, 10)
        if rc:
            disp.update({r.code: r.display for r in rc})
            res2 = await parse_structured(
                client, model, prompt,
                f'Term: "{res.refined_search_term}"\n\nCandidates:\n{_fmt(rc)}',
                CodeSelectorResult, stage="stage4", call_type=f"sel_{system}_retry",
            )
            if res2 and res2.code:
                return res2.code, disp
    return None, disp


def correct(fact, code, disp_map):
    if code is None:
        return False
    if norm_code(code, fact["system"]) == norm_code(fact["code"], fact["system"]):
        return True
    want = norm_display(fact["display"])
    return bool(want) and norm_display(disp_map.get(code, "")) == want


async def run_arm(name, retriever, facts, variants, client, model, sem):
    hits = 0
    by_sys = defaultdict(lambda: [0, 0])

    async def one(fact):
        nonlocal hits
        qs = variants.get(fact["id"], [fact["text"]])
        async with sem:
            cands = await union_search(retriever, qs, fact["system"])
            code, disp_map = await select(fact["text"], fact["system"], retriever, cands, client, model)
        ok = correct(fact, code, disp_map)
        by_sys[fact["system"]][1] += 1
        if ok:
            hits += 1
            by_sys[fact["system"]][0] += 1

    t0 = time.perf_counter()
    await asyncio.gather(*(one(f) for f in facts))
    n = len(facts)
    print(f"\n===== {name}  ({time.perf_counter()-t0:.1f}s, n={n}) =====")
    print(f"  code accuracy   {hits}/{n}  {hits/n*100:5.1f}%")
    for sysk in ("snomed", "icd10", "rxnorm", "loinc"):
        if by_sys[sysk][1]:
            h, t = by_sys[sysk]
            print(f"    {sysk:<7} {h:>2}/{t:<2} {h/t*100:5.1f}%")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    facts = load_facts(args.limit)
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    model = settings.openai_model_fast
    print(f"{len(facts)} targets; generating variants...")
    jobs = [{"id": f["id"], "text": f["text"], "resource_type": f["resource_type"], "system": f["system"]} for f in facts]
    variants = await generate_search_queries(jobs, client, model=model)

    api = ApiRetriever()
    await run_arm("LIVE API + variants", api, facts, variants, client, model, asyncio.Semaphore(6))
    await api.aclose()
    await run_arm("FAISS + variants", FaissRetriever(), facts, variants, client, model, asyncio.Semaphore(8))


if __name__ == "__main__":
    asyncio.run(main())
