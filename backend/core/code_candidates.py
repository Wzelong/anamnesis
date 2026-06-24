"""Stage 4: terminology coding via live-API retrieval + LLM CodeSelector.

US Core fixed codes short-circuit known vital signs / smoking status.
All other candidates go through: API retrieval top-k -> LLM select ->
optional 1 refinement retry.

No term-level caching by design.  The downstream human-in-the-loop
review may correct codes; a term cache would silently re-apply a code
that a clinician already rejected.  A production deployment could add a
smart cache that invalidates on HITL corrections, but for now simplicity
wins.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from google import genai

from core.extraction import parse_structured
from core.prompts import PROMPT_CODE_SELECT
from core.retrieval import ApiRetriever, Retriever, SearchResult, union_search
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

# -- US Core fixed LOINC codes (bypass retrieval) ---------------------------

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
    "occupation": ("11341-5", "History of Occupation"),
    "sexual orientation": ("76690-7", "Sexual orientation"),
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


def _systems_override(effective, resource_type: str) -> list[str] | None:
    """Preset coding-systems override for a type, filtered to known systems.
    None = use the default routing (regression-safe)."""
    if effective is None:
        return None
    systems = effective.rule(resource_type).coding_systems
    if not systems:
        return None
    valid = [s for s in systems if s in SYSTEM_URIS]
    return valid or None


def _extract_search_terms(
    resource_type: str, item: dict, systems_override: list[str] | None = None,
) -> list[tuple[str, list[str], list[str]]]:
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

    systems = systems_override or RESOURCE_CODE_SYSTEMS.get(resource_type, ["snomed"])
    if resource_type == "Observation" and not systems_override:
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
    effective=None,
) -> list[tuple[int, str, str, list[str], str]]:
    """Return (candidate_index, field_key, term, queries, system) for all searches."""
    jobs: list[tuple[int, str, str, list[str], str]] = []
    for ci, c in enumerate(candidates):
        if match_us_core_fixed(c.resource_type, c.item) is not None:
            continue
        override = _systems_override(effective, c.resource_type)
        for ti, (term, queries, systems) in enumerate(_extract_search_terms(c.resource_type, c.item, override)):
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


def _tokens(s: str) -> set[str]:
    out: set[str] = set()
    cur: list[str] = []
    for ch in s.lower():
        if ch.isalnum():
            cur.append(ch)
        elif cur:
            out.add("".join(cur)); cur = []
    if cur:
        out.add("".join(cur))
    return out


def _subset_candidates(sys_codes: list[dict], queries: list[str], top_k: int) -> list[SearchResult]:
    """Rank a value-set's codes (for one system) by lexical overlap with the search
    queries and return the top_k as selector candidates. The selector then picks the
    best in-set code, so a scoped type codes to its value set instead of being dropped."""
    if not sys_codes:
        return []
    qtokens: set[str] = set()
    for qy in queries:
        qtokens |= _tokens(qy)
    ranked = sorted(sys_codes, key=lambda c: -len(qtokens & _tokens(c.get("display") or "")))
    return [
        SearchResult(code=c["code"], display=c.get("display") or "", score=1.0 - i * 0.02, rank=i + 1)
        for i, c in enumerate(ranked[:top_k])
        if c.get("code")
    ]


def _partition_scoped(
    jobs: list[tuple[int, str, str, list[str], str]],
    candidates: list[MergedCandidate],
    effective,
    top_k: int,
) -> tuple[dict[str, list[SearchResult]], list[tuple[int, str, str, list[str], str]]]:
    """Split jobs: scoped types (preset pins a value set) get their candidates FROM the
    value set; the rest retrieve from the live API. Makes the value set the search space."""
    scoped: dict[str, list[SearchResult]] = {}
    api_jobs: list[tuple[int, str, str, list[str], str]] = []
    for job in jobs:
        ci, key, _term, queries, system = job
        subset = effective.rule(candidates[ci].resource_type).code_subset if effective is not None else None
        if subset:
            uri = SYSTEM_URIS.get(system)
            scoped[key] = _subset_candidates([c for c in subset if c.get("system") == uri], queries, top_k)
        else:
            api_jobs.append(job)
    return scoped, api_jobs


async def _code_candidate(
    ci: int,
    candidate: MergedCandidate,
    search_results: dict[str, list[SearchResult]],
    client: genai.Client,
    model: str,
    retriever: Retriever,
    effective=None,
) -> MergedCandidate:
    item = dict(candidate.item)

    fixed = match_us_core_fixed(candidate.resource_type, item)
    if fixed is not None:
        item["coding"] = fixed
        return candidate.model_copy(update={"item": item})

    search_terms = _extract_search_terms(
        candidate.resource_type, item, _systems_override(effective, candidate.resource_type),
    )

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
    effective=None,
) -> StageFourOutput:
    candidates = stage3_output.candidates

    own = retriever is None
    if retriever is None:
        retriever = ApiRetriever()
    try:
        jobs = _collect_search_jobs(candidates, effective)
        scoped_results, api_jobs = _partition_scoped(jobs, candidates, effective, top_k)
        api_results = await _retrieve_all(api_jobs, retriever, top_k)
        search_results = {**scoped_results, **api_results}
        coded = await asyncio.gather(*(
            _code_candidate(ci, c, search_results, client, model, retriever, effective)
            for ci, c in enumerate(candidates)
        ))
    finally:
        if own and hasattr(retriever, "aclose"):
            await retriever.aclose()
    return StageFourOutput(candidates=list(coded))
