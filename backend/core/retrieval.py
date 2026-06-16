"""Pluggable terminology retrieval: FAISS (local) or live authoritative APIs.

Both implementations return the same `SearchResult` shape Stage 4's LLM
selector consumes, so either is a drop-in for the candidate-retrieval step.

API routing is best-of-breed per system (measured): SNOMED -> UMLS UTS,
RxNorm -> RxNav approximateTerm, ICD-10/LOINC -> NLM Clinical Tables.
"""
from __future__ import annotations

import asyncio
import os
from typing import Protocol

import httpx

from config import settings
from core.coding import SearchResult, _get_defaults

UMLS_SEARCH = "https://uts-ws.nlm.nih.gov/rest/search/current"
RXNAV_APPROX = "https://rxnav.nlm.nih.gov/REST/approximateTerm.json"
RXNAV_PROP = "https://rxnav.nlm.nih.gov/REST/rxcui/{rxcui}/property.json"
CT_ICD10 = "https://clinicaltables.nlm.nih.gov/api/icd10cm/v3/search"
CT_LOINC = "https://clinicaltables.nlm.nih.gov/api/loinc_items/v3/search"

UMLS_SAB = {"snomed": "SNOMEDCT_US"}


class Retriever(Protocol):
    async def search(self, term: str, system: str, top_k: int = 10) -> list[SearchResult]: ...


async def union_search(
    retriever: "Retriever", queries: list[str], system: str, top_k: int = 10
) -> list[SearchResult]:
    """Run every query, union candidates by code (first/best rank wins), re-rank."""
    lists = await asyncio.gather(
        *(retriever.search(q, system, top_k) for q in queries), return_exceptions=True
    )
    best: dict[str, SearchResult] = {}
    for lst in lists:
        if isinstance(lst, Exception):
            continue
        for r in lst:
            prev = best.get(r.code)
            if prev is None or r.score > prev.score:
                best[r.code] = r
    merged = sorted(best.values(), key=lambda r: -r.score)[:top_k]
    return [SearchResult(code=r.code, display=r.display, score=r.score, rank=i + 1)
            for i, r in enumerate(merged)]


class FaissRetriever:
    async def search(self, term: str, system: str, top_k: int = 10) -> list[SearchResult]:
        store, model = _get_defaults()
        vec = await asyncio.to_thread(model.encode, [term])
        return await asyncio.to_thread(store.search, vec, system, top_k)


class ApiRetriever:
    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        umls_api_key: str | None = None,
        concurrency: int = 6,
    ):
        self._client = client or httpx.AsyncClient(timeout=25.0)
        self._umls_key = umls_api_key or os.environ.get("UMLS_API_KEY") or settings.umls_api_key
        self._name_cache: dict[str, str] = {}
        self._sem = asyncio.Semaphore(concurrency)

    async def search(self, term: str, system: str, top_k: int = 10) -> list[SearchResult]:
        async with self._sem:
            if system == "snomed":
                return await self._snomed(term, top_k)
            if system == "rxnorm":
                return await self._rxnorm(term, top_k)
            if system == "icd10":
                return await self._icd10(term, top_k)
            if system == "loinc":
                return await self._loinc(term, top_k)
            return []

    async def _snomed(self, term: str, top_k: int) -> list[SearchResult]:
        if not self._umls_key:
            raise RuntimeError("UMLS_API_KEY required for SNOMED retrieval")
        params = {
            "string": term, "sabs": UMLS_SAB["snomed"], "returnIdType": "code",
            "pageSize": top_k, "apiKey": self._umls_key,
        }
        r = await self._client.get(UMLS_SEARCH, params=params)
        r.raise_for_status()
        rows = r.json().get("result", {}).get("results", [])
        out = []
        for i, row in enumerate(rows):
            if row.get("ui") in (None, "NONE"):
                continue
            out.append(SearchResult(code=row["ui"], display=row.get("name", ""), score=1.0 - i * 0.02, rank=i + 1))
        return out

    async def _rxnorm(self, term: str, top_k: int) -> list[SearchResult]:
        r = await self._client.get(RXNAV_APPROX, params={"term": term, "maxEntries": top_k})
        r.raise_for_status()
        cands = (r.json().get("approximateGroup") or {}).get("candidate") or []
        out: list[SearchResult] = []
        seen: set[str] = set()
        for c in cands:
            rxcui = c.get("rxcui")
            if not rxcui or rxcui in seen:
                continue
            seen.add(rxcui)
            name = c.get("name") or await self._rxnorm_name(rxcui)
            if not name:
                continue
            out.append(SearchResult(code=rxcui, display=name, score=float(c.get("score", 0)), rank=len(out) + 1))
            if len(out) >= top_k:
                break
        return out

    async def _rxnorm_name(self, rxcui: str) -> str:
        if rxcui in self._name_cache:
            return self._name_cache[rxcui]
        try:
            r = await self._client.get(RXNAV_PROP.format(rxcui=rxcui), params={"propName": "RxNorm Name"})
            props = (r.json().get("propConceptGroup") or {}).get("propConcept") or []
            name = props[0]["propValue"] if props else ""
        except Exception:
            name = ""
        self._name_cache[rxcui] = name
        return name

    async def _icd10(self, term: str, top_k: int) -> list[SearchResult]:
        params = {"sf": "code,name", "terms": term, "maxList": top_k}
        r = await self._client.get(CT_ICD10, params=params)
        r.raise_for_status()
        _total, _codes, _x, rows = r.json()
        return [
            SearchResult(code=code, display=name, score=1.0 - i * 0.05, rank=i + 1)
            for i, (code, name) in enumerate(rows)
        ]

    async def _loinc(self, term: str, top_k: int) -> list[SearchResult]:
        params = {"terms": term, "maxList": top_k, "df": "LOINC_NUM,LONG_COMMON_NAME"}
        r = await self._client.get(CT_LOINC, params=params)
        r.raise_for_status()
        _total, codes, _x, rows = r.json()
        out = []
        for i, code in enumerate(codes):
            disp = rows[i][1] if i < len(rows) and len(rows[i]) > 1 else code
            out.append(SearchResult(code=code, display=disp, score=1.0 - i * 0.05, rank=i + 1))
        return out

    async def aclose(self) -> None:
        await self._client.aclose()
