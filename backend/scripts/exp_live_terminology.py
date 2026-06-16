"""Experiment: live terminology APIs as a drop-in for FAISS retrieval.

Returns the same SearchResult shape Stage 4's LLM selector consumes, so this
is a true substitute for `_batch_search`. Measures candidate recall + latency
per (term, system). Read-only, no OpenAI calls — isolates the retrieval layer.

Run:  python -m scripts.exp_live_terminology
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass


@dataclass
class SearchResult:
    code: str
    display: str
    score: float
    rank: int


def _get(url: str, timeout: float = 25.0) -> bytes:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def search_rxnorm(term: str, top_k: int = 10) -> list[SearchResult]:
    url = (
        "https://rxnav.nlm.nih.gov/REST/approximateTerm.json?"
        + urllib.parse.urlencode({"term": term, "maxEntries": top_k})
    )
    data = json.loads(_get(url))
    cands = (data.get("approximateGroup") or {}).get("candidate") or []
    seen: dict[str, SearchResult] = {}
    rank = 0
    for c in cands:
        rxcui = c.get("rxcui")
        if not rxcui or rxcui in seen:
            continue
        name = c.get("name") or _rxnorm_name(rxcui)
        if not name:
            continue
        rank += 1
        seen[rxcui] = SearchResult(code=rxcui, display=name, score=float(c.get("score", 0)), rank=rank)
        if rank >= top_k:
            break
    return list(seen.values())


def _rxnorm_name(rxcui: str) -> str | None:
    try:
        url = f"https://rxnav.nlm.nih.gov/REST/rxcui/{rxcui}/property.json?propName=RxNorm%20Name"
        data = json.loads(_get(url))
        props = (data.get("propConceptGroup") or {}).get("propConcept") or []
        return props[0]["propValue"] if props else None
    except Exception:
        return None


def search_icd10(term: str, top_k: int = 10) -> list[SearchResult]:
    url = (
        "https://clinicaltables.nlm.nih.gov/api/icd10cm/v3/search?"
        + urllib.parse.urlencode({"sf": "code,name", "terms": term, "maxList": top_k})
    )
    _total, _codes, _x, rows = json.loads(_get(url))
    return [
        SearchResult(code=code, display=name, score=1.0 - i * 0.05, rank=i + 1)
        for i, (code, name) in enumerate(rows)
    ]


def search_loinc(term: str, top_k: int = 10) -> list[SearchResult]:
    url = (
        "https://clinicaltables.nlm.nih.gov/api/loinc_items/v3/search?"
        + urllib.parse.urlencode(
            {"terms": term, "maxList": top_k, "df": "LOINC_NUM,LONG_COMMON_NAME"}
        )
    )
    _total, codes, _x, rows = json.loads(_get(url))
    out = []
    for i, code in enumerate(codes):
        disp = rows[i][1] if i < len(rows) and len(rows[i]) > 1 else rows[i][0]
        out.append(SearchResult(code=code, display=disp, score=1.0 - i * 0.05, rank=i + 1))
    return out


def search_snomed(term: str, top_k: int = 10) -> list[SearchResult]:
    # No open no-auth endpoint reachable; IHTSDO public servers deny datacenter IPs.
    raise RuntimeError("SNOMED: no open API (needs UMLS key or licensed Snowstorm)")


SEARCH = {
    "rxnorm": search_rxnorm,
    "icd10": search_icd10,
    "loinc": search_loinc,
    "snomed": search_snomed,
}

# (term, system, expected-ish concept) — chosen to stress recall.
CASES = [
    ("coronary artery disease", "icd10", "I25.1x atherosclerotic heart disease"),
    ("two-vessel coronary artery disease", "icd10", "I25.x"),
    ("HFrEF", "icd10", "I50.2x systolic heart failure"),
    ("paroxysmal atrial fibrillation", "icd10", "I48.0"),
    ("GERD", "icd10", "K21.9"),
    ("lisinopril 10 mg", "rxnorm", "lisinopril 10 mg tablet"),
    ("losartan 50 mg PO daily", "rxnorm", "losartan 50 mg"),
    ("metoprolol succinate 25 mg", "rxnorm", "metoprolol succinate ER 25 mg"),
    ("HbA1c", "loinc", "4548-4 / 4549-2"),
    ("LDL cholesterol", "loinc", "13457-7 / 18262-6"),
    ("troponin", "loinc", "troponin I/T"),
    ("penicillin", "snomed", "764146007 penicillin"),
]


def run() -> None:
    for term, system, expected in CASES:
        t0 = time.perf_counter()
        try:
            results = SEARCH[system](term)
            ms = (time.perf_counter() - t0) * 1000
            print(f"\n[{system}] {term!r}   ({ms:.0f} ms)   expect ~ {expected}")
            if not results:
                print("   *** ZERO CANDIDATES — recall miss ***")
            for r in results[:5]:
                print(f"   [{r.rank}] {r.code:<12} {r.display}")
        except Exception as e:
            ms = (time.perf_counter() - t0) * 1000
            print(f"\n[{system}] {term!r}   ({ms:.0f} ms)   FAILED: {e}")


if __name__ == "__main__":
    run()
