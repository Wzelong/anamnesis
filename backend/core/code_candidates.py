"""Stage 4: terminology coding via FAISS vector search + LLM CodeSelector.

US Core fixed codes short-circuit known vital signs / smoking status.
All other candidates go through: vector search top-k -> LLM select ->
optional 1 refinement retry.

No term-level caching by design.  The downstream human-in-the-loop
review may correct codes; a term cache would silently re-apply a code
that a clinician already rejected.  With model + indexes warm, the
full stage runs in ~6-7 s for 50 candidates (all parallel), so the
latency cost of skipping the cache is acceptable.  A production
deployment could add a smart cache that invalidates on HITL
corrections, but for now simplicity wins.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field

import numpy as np
from google import genai

from config import settings
from core.coding import EmbeddingModel, IndexStore, SearchResult, _get_defaults
from core.extraction import parse_structured
from core.prompts import PROMPT_CODE_SELECT
from core.retrieval import ApiRetriever, FaissRetriever, Retriever, union_search
from core.schemas import CodeSelectorResult, MergedCandidate

log = logging.getLogger(__name__)

SYSTEM_URIS: dict[str, str] = {
    "snomed": "http://snomed.info/sct",
    "loinc": "http://loinc.org",
    "rxnorm": "http://www.nlm.nih.gov/research/umls/rxnorm",
    "icd10": "http://hl7.org/fhir/sid/icd-10-cm",
}

RESOURCE_CODE_SYSTEMS: dict[str, list[str]] = {
    "Condition": ["snomed", "icd10"],
    "MedicationRequest": ["rxnorm"],
    "Procedure": ["snomed"],
    "AllergyIntolerance": ["snomed"],
    "FamilyMemberHistory": ["snomed"],
    "Observation": [],
}

# -- US Core fixed LOINC codes (bypass vector search) -----------------------

US_CORE_FIXED: dict[str, tuple[str, str]] = {
    "blood pressure": ("85354-9", "Blood pressure panel with all children optional"),
    "bp": ("85354-9", "Blood pressure panel with all children optional"),
    "systolic": ("8480-6", "Systolic blood pressure"),
    "diastolic": ("8462-4", "Diastolic blood pressure"),
    "body weight": ("29463-7", "Body weight"),
    "body height": ("8302-2", "Body height"),
    "body temperature": ("8310-5", "Body temperature"),
    "heart rate": ("8867-4", "Heart rate"),
    "respiratory rate": ("9279-1", "Respiratory rate"),
    "bmi": ("39156-5", "Body mass index"),
    "pulse oximetry": ("59408-5", "Oxygen saturation by pulse oximetry"),
    "oxygen saturation": ("2708-6", "Oxygen saturation in arterial blood"),
    "spo2": ("2708-6", "Oxygen saturation in arterial blood"),
    "head circumference": ("9843-4", "Head circumference"),
}

US_CORE_SMOKING_TERMS = ("tobacco", "smoking")

# -- FamilyMemberHistory relationship codes (FHIR v3-RoleCode) -------------

FMH_RELATIONSHIP_CODES: dict[str, tuple[str, str]] = {
    "father": ("FTH", "father"),
    "mother": ("MTH", "mother"),
    "brother": ("BRO", "brother"),
    "sister": ("SIS", "sister"),
    "son": ("SON", "natural son"),
    "daughter": ("DAU", "natural daughter"),
    "maternal grandmother": ("MGRMTH", "maternal grandmother"),
    "maternal grandfather": ("MGRFTH", "maternal grandfather"),
    "paternal grandmother": ("PGRMTH", "paternal grandmother"),
    "paternal grandfather": ("PGRFTH", "paternal grandfather"),
    "grandmother": ("GRMTH", "grandmother"),
    "grandfather": ("GRFTH", "grandfather"),
    "uncle": ("UNCLE", "uncle"),
    "aunt": ("AUNT", "aunt"),
    "cousin": ("COUSN", "cousin"),
    "spouse": ("SPS", "spouse"),
    "husband": ("HUSB", "husband"),
    "wife": ("WIFE", "wife"),
}

FMH_ROLE_SYSTEM = "http://terminology.hl7.org/CodeSystem/v3-RoleCode"


def match_us_core_fixed(resource_type: str, item: dict) -> list[dict] | None:
    if resource_type != "Observation":
        return None

    name_lower = (item.get("full_name") or item.get("name") or "").lower()

    for term in US_CORE_SMOKING_TERMS:
        if term in name_lower:
            return [{"system": SYSTEM_URIS["loinc"], "code": "72166-2", "display": "Tobacco smoking status"}]

    if name_lower in US_CORE_FIXED:
        code, display = US_CORE_FIXED[name_lower]
        return [{"system": SYSTEM_URIS["loinc"], "code": code, "display": display}]

    for term, (code, display) in US_CORE_FIXED.items():
        if term in name_lower:
            return [{"system": SYSTEM_URIS["loinc"], "code": code, "display": display}]

    return None


def _fmh_relationship_coding(relationship: str) -> list[dict]:
    key = relationship.strip().lower()
    if key in FMH_RELATIONSHIP_CODES:
        code, display = FMH_RELATIONSHIP_CODES[key]
        return [{"system": FMH_ROLE_SYSTEM, "code": code, "display": display}]
    return [{"text": relationship}]


def _observation_systems(item: dict) -> list[str]:
    hint = item.get("codeset_hint")
    if hint == "LOINC":
        return ["loinc"]
    if hint == "SNOMED":
        return ["snomed"]
    cat = (item.get("category") or "").lower()
    if cat in ("vital-signs", "laboratory", "survey"):
        return ["loinc"]
    return ["snomed"]


def _extract_search_terms(resource_type: str, item: dict) -> list[tuple[str, list[str], list[str]]]:
    """Return (term, queries, systems). `queries` are the parser-emitted search
    strings (fallback to [term]); `term` is the label shown to the selector."""
    if resource_type == "FamilyMemberHistory":
        terms = []
        for cond in item.get("conditions") or []:
            name = cond.get("name", "")
            if name:
                terms.append((name, cond.get("queries") or [name], ["snomed"]))
        return terms

    if resource_type == "AllergyIntolerance":
        terms = []
        substance = item.get("substance") or ""
        if substance:
            terms.append((substance, item.get("substance_queries") or [substance], ["snomed"]))
        reaction = item.get("reaction") or ""
        if reaction:
            terms.append((reaction, item.get("reaction_queries") or [reaction], ["snomed"]))
        return terms

    name = item.get("full_name") or item.get("name") or ""
    if not name:
        return []

    systems = RESOURCE_CODE_SYSTEMS.get(resource_type, ["snomed"])
    if resource_type == "Observation":
        systems = _observation_systems(item)

    return [(name, item.get("code_queries") or [name], systems)]


def _format_candidates_for_llm(results: list[SearchResult]) -> str:
    lines = []
    for r in results:
        lines.append(f"[{r.rank}] {r.code} — {r.display} (score: {r.score:.3f})")
    return "\n".join(lines)


async def _select_code(
    term: str,
    system: str,
    search_results: list[SearchResult],
    client: genai.Client,
    model: str,
    retriever: "Retriever",
) -> dict | None:
    if not search_results:
        return None

    formatted = _format_candidates_for_llm(search_results)
    user_msg = f'Term: "{term}"\n\nCandidates:\n{formatted}'
    prompt = PROMPT_CODE_SELECT.format(system=system.upper())

    result = await parse_structured(
        client, model, prompt, user_msg, CodeSelectorResult,
        stage="stage4", call_type=f"code_select_{system}",
    )
    if result is None:
        return None

    if result.code:
        for r in search_results:
            if r.code == result.code:
                return {"system": SYSTEM_URIS[system], "code": r.code, "display": r.display}
        return {"system": SYSTEM_URIS[system], "code": result.code, "display": term}

    if result.refined_search_term:
        refined_results = await retriever.search(result.refined_search_term, system, 10)
        if not refined_results:
            return None

        formatted2 = _format_candidates_for_llm(refined_results)
        user_msg2 = f'Term: "{result.refined_search_term}" (refined from "{term}")\n\nCandidates:\n{formatted2}'
        result2 = await parse_structured(
            client, model, prompt, user_msg2, CodeSelectorResult,
            stage="stage4", call_type=f"code_select_{system}_retry",
        )
        if result2 and result2.code:
            for r in refined_results:
                if r.code == result2.code:
                    return {"system": SYSTEM_URIS[system], "code": r.code, "display": r.display}
            return {"system": SYSTEM_URIS[system], "code": result2.code, "display": term}

    return None


# -- Batch embedding + search -----------------------------------------------

def _collect_search_jobs(
    candidates: list[MergedCandidate],
) -> list[tuple[int, str, str, list[str], str]]:
    """Return (candidate_index, field_key, term, queries, system) for all searches."""
    jobs: list[tuple[int, str, str, list[str], str]] = []
    for ci, c in enumerate(candidates):
        if match_us_core_fixed(c.resource_type, c.item) is not None:
            continue
        for ti, (term, queries, systems) in enumerate(_extract_search_terms(c.resource_type, c.item)):
            for system in systems:
                key = f"{ci}:{ti}:{system}"
                jobs.append((ci, key, term, queries, system))
    return jobs


async def _retrieve_all(
    jobs: list[tuple[int, str, str, list[str], str]],
    retriever: Retriever,
    top_k: int,
) -> dict[str, list[SearchResult]]:
    """Per job, union the parser-emitted queries through the retriever."""
    async def one(job):
        _ci, key, _term, queries, system = job
        return key, await union_search(retriever, queries, system, top_k)

    return dict(await asyncio.gather(*(one(j) for j in jobs)))


# ===========================================================================
# GRADUATED — legacy FAISS retrieval (Stage 4 v1).
# Superseded by parser-emitted `code_queries` + `ApiRetriever` (see
# `_retrieve_all` / `core/retrieval.py`). Retained for reference and for the
# `coding_retriever="faiss"` option, which now routes through `FaissRetriever`.
# The helpers below (`_query_variants`, `_merge_results`, `_batch_search`) are
# no longer on the live path.
# ===========================================================================

_ABBREV: dict[str, str] = {
    "htn": "hypertension",
    "dm": "diabetes mellitus",
    "dm2": "type 2 diabetes mellitus",
    "t2dm": "type 2 diabetes mellitus",
    "t1dm": "type 1 diabetes mellitus",
    "mi": "myocardial infarction",
    "chf": "congestive heart failure",
    "hfref": "heart failure with reduced ejection fraction",
    "hfpef": "heart failure with preserved ejection fraction",
    "cad": "coronary artery disease",
    "copd": "chronic obstructive pulmonary disease",
    "afib": "atrial fibrillation",
    "a-fib": "atrial fibrillation",
    "ckd": "chronic kidney disease",
    "esrd": "end-stage renal disease",
    "uti": "urinary tract infection",
    "gerd": "gastroesophageal reflux disease",
    "osa": "obstructive sleep apnea",
    "dvt": "deep vein thrombosis",
    "pe": "pulmonary embolism",
    "ldl": "low-density lipoprotein cholesterol",
    "hdl": "high-density lipoprotein cholesterol",
    "bp": "blood pressure",
    "hr": "heart rate",
    "rr": "respiratory rate",
    "spo2": "oxygen saturation",
    "a1c": "hemoglobin a1c",
    "hba1c": "hemoglobin a1c",
}

_LATERALITY_RE = re.compile(r"[,\s]+(?:left|right|bilateral|bilat)\.?\s*$", re.IGNORECASE)
_PARENS_RE = re.compile(r"\s*\([^)]*\)\s*$")
_DOSE_RE = re.compile(r"\s+\d+(?:\.\d+)?\s*(?:mg|mcg|µg|g|ml|units?|iu|tabs?|caps?)\b.*$", re.IGNORECASE)
_LEADING_SEVERITY_RE = re.compile(r"^(?:severe|moderate|mild|acute|subacute|chronic|recurrent|active|resolved|small|large)\s+", re.IGNORECASE)
_TRAILING_QUALIFIER_RE = re.compile(r",\s*(?:nos|unspecified|nec|stable|improving|worsening)\.?\s*$", re.IGNORECASE)


def _query_variants(term: str) -> list[str]:
    """Generate query variants for first-pass search.

    Returns the original term first, then progressively stripped/expanded forms.
    Order is deterministic; deduped while preserving first occurrence.
    """
    out: list[str] = [term.strip()]
    seen = {out[0].lower()}

    def _add(v: str) -> None:
        v = v.strip()
        key = v.lower()
        if v and key not in seen:
            out.append(v)
            seen.add(key)

    _add(_LATERALITY_RE.sub("", term))
    _add(_PARENS_RE.sub("", term))
    _add(_DOSE_RE.sub("", term))
    _add(_LEADING_SEVERITY_RE.sub("", term))
    _add(_TRAILING_QUALIFIER_RE.sub("", term))

    lower = term.lower().strip().rstrip(".")
    if lower in _ABBREV:
        _add(_ABBREV[lower])
    for tok in re.findall(r"\b[a-z][a-z0-9-]+\b", lower):
        if tok in _ABBREV and _ABBREV[tok] not in seen:
            _add(term.lower().replace(tok, _ABBREV[tok]))

    return out


def _merge_results(lists: list[list[SearchResult]], top_k: int) -> list[SearchResult]:
    """Merge per-variant FAISS hits, dedupe by code, keep best score, re-rank."""
    best: dict[str, SearchResult] = {}
    for hits in lists:
        for r in hits:
            prev = best.get(r.code)
            if prev is None or r.score > prev.score:
                best[r.code] = r
    merged = sorted(best.values(), key=lambda r: -r.score)[:top_k]
    return [SearchResult(code=r.code, display=r.display, score=r.score, rank=i + 1) for i, r in enumerate(merged)]


def _batch_search(
    jobs: list[tuple[int, str, str, list[str], str]],
) -> dict[str, list[SearchResult]]:
    """Batch-embed unique terms (with variants), run FAISS, merge per-job."""
    if not jobs:
        return {}

    store, emb_model = _get_defaults()

    job_variants: dict[str, list[str]] = {}
    all_terms: set[str] = set()
    for _, key, term, _queries, _system in jobs:
        variants = _query_variants(term)
        job_variants[key] = variants
        all_terms.update(variants)

    unique_terms = sorted(all_terms)
    vecs = emb_model.encode(unique_terms)
    term_to_vec: dict[str, np.ndarray] = {t: vecs[i] for i, t in enumerate(unique_terms)}

    results: dict[str, list[SearchResult]] = {}
    for _, key, _term, _queries, system in jobs:
        per_variant = [store.search(term_to_vec[v], system, 5) for v in job_variants[key]]
        results[key] = _merge_results(per_variant, top_k=10)
    return results

# =========================== end GRADUATED block ===========================


async def _code_candidate(
    ci: int,
    candidate: MergedCandidate,
    search_results: dict[str, list[SearchResult]],
    client: genai.Client,
    model: str,
    retriever: Retriever,
) -> MergedCandidate:
    item = dict(candidate.item)

    fixed = match_us_core_fixed(candidate.resource_type, item)
    if fixed is not None:
        item["coding"] = fixed
        return candidate.model_copy(update={"item": item})

    search_terms = _extract_search_terms(candidate.resource_type, item)

    if candidate.resource_type == "FamilyMemberHistory":
        conditions = list(item.get("conditions") or [])
        for i, cond in enumerate(conditions):
            cond = dict(cond)
            name = cond.get("name", "")
            if not name:
                cond["coding"] = [{"text": "unknown"}]
                conditions[i] = cond
                continue
            key = f"{ci}:{i}:snomed"
            sr = search_results.get(key, [])
            coding_result = await _select_code(name, "snomed", sr, client, model, retriever)
            cond["coding"] = [coding_result] if coding_result else [{"text": name}]
            conditions[i] = cond
        item["conditions"] = conditions
        item["coding"] = _fmh_relationship_coding(item.get("relationship", ""))
        return candidate.model_copy(update={"item": item})

    if candidate.resource_type == "AllergyIntolerance":
        substance = item.get("substance") or ""
        reaction = item.get("reaction") or ""
        sub_coding = None
        react_coding = None
        tasks = []
        ti = 0
        if substance:
            key = f"{ci}:{ti}:snomed"
            sr = search_results.get(key, [])
            tasks.append(("substance", _select_code(substance, "snomed", sr, client, model, retriever)))
            ti += 1
        if reaction:
            key = f"{ci}:{ti}:snomed"
            sr = search_results.get(key, [])
            tasks.append(("reaction", _select_code(reaction, "snomed", sr, client, model, retriever)))

        for field_name, coro in tasks:
            result = await coro
            if field_name == "substance":
                sub_coding = result
            else:
                react_coding = result

        item["coding"] = [sub_coding] if sub_coding else [{"text": substance}]
        if react_coding:
            item["reaction_coding"] = [react_coding]
        return candidate.model_copy(update={"item": item})

    all_codings: list[dict] = []
    tasks = []
    for ti, (term, _queries, systems) in enumerate(search_terms):
        for system in systems:
            key = f"{ci}:{ti}:{system}"
            sr = search_results.get(key, [])
            tasks.append(_select_code(term, system, sr, client, model, retriever))

    if tasks:
        results = await asyncio.gather(*tasks)
        for r in results:
            if r is not None:
                all_codings.append(r)

    if not all_codings:
        term_name = (item.get("full_name") or item.get("name")
                     or item.get("substance") or "")
        all_codings = [{"text": term_name}]

    item["coding"] = all_codings
    return candidate.model_copy(update={"item": item})


@dataclass
class StageFourOutput:
    candidates: list[MergedCandidate] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"candidates": [c.model_dump(mode="json") for c in self.candidates]}

    @classmethod
    def from_json(cls, data: dict) -> StageFourOutput:
        return cls(
            candidates=[MergedCandidate.model_validate(c) for c in data["candidates"]],
        )


async def code_candidates(
    stage3_output,
    client: genai.Client,
    *,
    model: str,
    top_k: int = 10,
    retriever: Retriever | None = None,
) -> StageFourOutput:
    candidates = stage3_output.candidates

    own = retriever is None
    if retriever is None:
        retriever = FaissRetriever() if settings.coding_retriever == "faiss" else ApiRetriever()
    try:
        jobs = _collect_search_jobs(candidates)
        search_results = await _retrieve_all(jobs, retriever, top_k)
        coded = await asyncio.gather(*(
            _code_candidate(ci, c, search_results, client, model, retriever)
            for ci, c in enumerate(candidates)
        ))
    finally:
        if own and hasattr(retriever, "aclose"):
            await retriever.aclose()
    return StageFourOutput(candidates=list(coded))
