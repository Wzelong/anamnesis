"""Generate terminology-style search queries for candidate retrieval.

One batched LLM call per target system turns a messy clinical entity into a
short ordered list of queries phrased the way the terminology names concepts.
Used by the API retrieval path (and helps FAISS recall on abbreviations too).
"""
from __future__ import annotations

import asyncio

from google import genai

from core.extraction import parse_structured
from core.prompts.search_terms import PROMPT_CODE_SEARCH_TERMS
from core.schemas import _Strict


class _Queries(_Strict):
    id: str
    queries: list[str]


class _QueryBatch(_Strict):
    items: list[_Queries]


CHUNK = 8


async def generate_search_queries(
    jobs: list[dict],
    client: genai.Client,
    *,
    model: str,
) -> dict[str, list[str]]:
    """jobs: [{id, text, resource_type, system}] -> {id: [queries]}."""
    by_system: dict[str, list[dict]] = {}
    for j in jobs:
        by_system.setdefault(j["system"], []).append(j)

    async def one_chunk(system: str, items: list[dict]) -> dict[str, list[str]]:
        local = {str(i): j for i, j in enumerate(items)}
        listing = "\n".join(
            f'- id={k} type={j["resource_type"]} entity="{j["text"]}"' for k, j in local.items()
        )
        prompt = PROMPT_CODE_SEARCH_TERMS.format(system=system)
        result = await parse_structured(
            client, model, prompt, listing, _QueryBatch,
            stage="stage4", call_type=f"search_terms_{system}",
        )
        if result is None:
            return {j["id"]: [j["text"]] for j in items}
        got = {q.id: q.queries for q in result.items}
        return {j["id"]: (got.get(k) or [j["text"]]) for k, j in local.items()}

    chunks = [
        (s, items[i:i + CHUNK])
        for s, items in by_system.items()
        for i in range(0, len(items), CHUNK)
    ]
    merged: dict[str, list[str]] = {}
    for part in await asyncio.gather(*(one_chunk(s, c) for s, c in chunks)):
        merged.update(part)
    return merged
