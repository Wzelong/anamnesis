"""Focused trace for P0 — UPDATING never fires.

Runs pipeline on C2 (LVEF), N4 (MoCA), N6 (tobacco) and dumps for each
Observation candidate:
  - parser fields: full_name, value, codeset_hint, category
  - what _observation_systems() routes it to
  - what match_us_core_fixed returned (None or a fixed coding)
  - the final coding[] after Stage 4
  - what Stage 5 classified it as

Run from repo root:
  python benchmarks/eval-corpus-v1/trace_observations.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent
sys.path.insert(0, str(REPO / "backend"))

from openai import AsyncOpenAI
from config import settings
from core.augment import assemble_proposals
from core.cache import JsonCache
from core.code_candidates import (
    code_candidates,
    match_us_core_fixed,
    _observation_systems,
)
from core.extraction import extract_candidates_batch, merge_across_notes
from core.preprocess import preprocess_documents
from core.reconcile import reconcile
from fhir.local_bundle import load_demo_data
from fhir.models import Document

CACHE_ROOT = REPO / "backend" / ".cache"
CASES = [
    ("C2-cardiology-hfref-gdmt-optimization", "hfref-gdmt"),
    ("N4-neurology-cognitive-moca-eval", "cognitive-mci"),
    ("N6-neurology-tobacco-consolidation", "pd-tobacco"),
]


async def run_case(stem: str, fixture_id: str, client) -> dict:
    note_path = ROOT / "notes" / f"{stem}.txt"
    bundle_path = ROOT / "fixtures" / f"{fixture_id}.json"
    pc, _ = load_demo_data(bundle_path)
    docs = [Document(
        id=stem.split("-")[0],
        type="Progress note",
        date="2026-04-01",
        author="trace",
        text=note_path.read_text(encoding="utf-8"),
        encounter_id=None,
    )]
    notes = preprocess_documents(docs)
    model = settings.openai_model_fast

    s2 = await extract_candidates_batch(
        notes, client, model=model,
        cache=JsonCache(CACHE_ROOT / "stage2_output"),
    )
    s3 = await merge_across_notes(
        s2, client, model=model,
        cache=JsonCache(CACHE_ROOT / "stage3"),
    )
    s4 = await code_candidates(s3, client, model=model)
    s5 = await reconcile(s4, pc, client, model=model)

    rows = []
    for result in s5.results:
        if result.candidate.resource_type != "Observation":
            continue
        item = result.candidate.item
        fixed = match_us_core_fixed("Observation", item)
        rows.append({
            "name": item.get("name"),
            "full_name": item.get("full_name"),
            "value": item.get("value"),
            "codeset_hint": item.get("codeset_hint"),
            "category": item.get("category"),
            "routed_systems": _observation_systems(item),
            "us_core_fixed_coding": fixed,
            "final_coding": item.get("coding"),
            "classification": result.classification,
            "reasoning": result.reasoning,
        })
    return {"note": stem, "fixture": fixture_id, "observations": rows}


async def main():
    if not settings.openai_api_key:
        print("ERROR: OPENAI_API_KEY not set", file=sys.stderr)
        return 2
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    out = []
    for stem, fixture_id in CASES:
        print(f"--- tracing {stem} (fixture={fixture_id}) ---", flush=True)
        out.append(await run_case(stem, fixture_id, client))

    print()
    for r in out:
        print(f"\n=== {r['note']} (chart fixture: {r['fixture']}) ===")
        for obs in r["observations"]:
            print(f"  name           = {obs['name']!r}")
            print(f"  full_name      = {obs['full_name']!r}")
            print(f"  value          = {obs['value']!r}")
            print(f"  codeset_hint   = {obs['codeset_hint']!r}")
            print(f"  category       = {obs['category']!r}")
            print(f"  routed_systems = {obs['routed_systems']}")
            print(f"  us_core_fixed  = {obs['us_core_fixed_coding']}")
            print(f"  final_coding   = {obs['final_coding']}")
            print(f"  classification = {obs['classification']}  ({obs['reasoning']})")
            print()


if __name__ == "__main__":
    asyncio.run(main())
