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
from core.prompts import build_code_select_prompt
from core.retrieval import ApiRetriever, Retriever, SearchResult, search_with_backoff, union_search
from core.mcode_obs import (
    ROLE_TUMOR_MARKER,
    fixed_coding as _mcode_fixed_coding,
    is_tumor_marker,
    match_mcode_obs,
    match_tnm_category,
    match_tumor_marker_fixed,
)
from core.schemas import CodeSelectorResult, MergedCandidate
from core.systems import RETRIEVABLE, SYSTEM_URIS, URI_TO_KEY

log = logging.getLogger(__name__)

RESOURCE_CODE_SYSTEMS: dict[str, list[str]] = {
    "Condition": ["snomed", "icd10"],
    "MedicationRequest": ["rxnorm"],
    "Procedure": ["snomed", "icd10pcs", "hcpcs"],
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


def _mcode_obs_active(effective) -> bool:
    rule = effective.rule("Observation") if effective is not None else None
    return bool(rule and rule.candidate_profiles)


def _tag_mcode_roles(candidate: MergedCandidate, effective) -> MergedCandidate:
    """Tag tumor-marker observations (mCODE active only) so the retrieved-code path
    routes to LOINC and the builder/selector shape the marker structure. Fixed-code
    mCODE observations are handled by `match_fixed`, so they are left untagged."""
    if candidate.resource_type != "Observation" or not _mcode_obs_active(effective):
        return candidate
    name = candidate.item.get("full_name") or candidate.item.get("name") or ""
    if match_mcode_obs(name) is None and is_tumor_marker(name):
        item = dict(candidate.item)
        item["mcode_role"] = ROLE_TUMOR_MARKER
        item.setdefault("codeset_hint", "LOINC")
        return candidate.model_copy(update={"item": item})
    return candidate


def _match_code_override(overrides: list[dict], item: dict) -> list[dict] | None:
    """A preset term->code override whose `match` is a substring of the term name."""
    name = (item.get("full_name") or item.get("name") or item.get("substance") or "").lower()
    if not name:
        return None
    for o in overrides or []:
        m = (o.get("match") or "").lower()
        if m and m in name:
            return [{"system": o.get("system"), "code": o["code"], "display": o.get("display", "")}]
    return None


def match_fixed(resource_type: str, item: dict, effective=None) -> list[dict] | None:
    """Fixed coding for a candidate. Preset term->code overrides win (reproducible
    coding the user chose); then mCODE concepts when active; then US Core vitals.

    All short-circuit retrieval — a matched term keeps the same code every run."""
    rule = effective.rule(resource_type) if effective is not None else None
    if rule is not None:
        ov = _match_code_override(rule.code_overrides, item)
        if ov is not None:
            return ov
    if resource_type == "Observation" and _mcode_obs_active(effective):
        tnm = match_tnm_category(item.get("value") or "")  # value-specific; beats the broad "stage" term
        if tnm is not None:
            return tnm
        name = item.get("full_name") or item.get("name") or ""
        spec = match_mcode_obs(name)
        if spec is not None:
            return _mcode_fixed_coding(spec)
        marker = match_tumor_marker_fixed(name)  # ER/PR/HER2/Ki-67 -> fixed LOINC (role tag still shapes value)
        if marker is not None:
            return marker
    return match_us_core_fixed(resource_type, item)


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


_BESPOKE = {"FamilyMemberHistory", "AllergyIntolerance"}  # snomed-only coding paths


def _default_systems(resource_type: str, item: dict) -> list[str]:
    if resource_type == "Observation":
        return _observation_systems(item)
    return RESOURCE_CODE_SYSTEMS.get(resource_type, ["snomed"])


def _resolve_coding(effective, resource_type: str, item: dict) -> tuple[list[str], dict[str, list[dict]]]:
    """(open_systems, pinned_by_system) for a candidate.

    open_systems: retrievable systems to free-code (preset OPEN list, or default).
    pinned_by_system: short system key -> the preset's pinned codes for it (any system).
    """
    rule = effective.rule(resource_type) if effective is not None else None
    raw = rule.coding_systems if rule is not None else None
    base = _default_systems(resource_type, item) if raw is None else raw
    open_systems = [s for s in base if s in RETRIEVABLE]

    pinned: dict[str, list[dict]] = {}
    for c in (rule.pinned if rule is not None else []):
        key = URI_TO_KEY.get(c.get("system"))
        if key and c.get("code"):
            pinned.setdefault(key, []).append(c)
    return open_systems, pinned


def _systems_for(resource_type: str, term_systems: list[str], pinned: dict[str, list[dict]]) -> list[str]:
    """Systems to produce a coding for: the term's open systems plus any pinned-only
    systems (additive). Bespoke types code snomed only — pins don't apply."""
    if resource_type in _BESPOKE:
        return term_systems
    return list(dict.fromkeys([*term_systems, *pinned]))


def _code_body_site(effective, resource_type: str, item: dict) -> bool:
    """Code Condition.bodySite to SNOMED only when a specialty IG (mCODE) is active
    for Condition and a body site was extracted. Off otherwise -> output unchanged."""
    if resource_type != "Condition" or not item.get("body_site"):
        return False
    rule = effective.rule(resource_type) if effective is not None else None
    return bool(rule and rule.candidate_profiles)


def _extract_search_terms(
    resource_type: str, item: dict, open_systems: list[str], code_body_site: bool = False,
) -> list[tuple[str, str, list[str], list[str]]]:
    """Return (field, term, queries, systems). `field` is 'code' for the primary
    coding or 'body_site'; `queries` are the parser-emitted search strings
    (fallback to [term]); `term` is the label shown to the selector."""
    if resource_type == "FamilyMemberHistory":
        terms = []
        for cond in item.get("conditions") or []:
            name = cond.get("name", "")
            if name:
                terms.append(("code", name, cond.get("queries") or [name], ["snomed"]))
        return terms

    if resource_type == "AllergyIntolerance":
        terms = []
        substance = item.get("substance") or ""
        if substance:
            terms.append(("code", substance, item.get("substance_queries") or [substance], ["snomed"]))
        reaction = item.get("reaction") or ""
        if reaction:
            terms.append(("code", reaction, item.get("reaction_queries") or [reaction], ["snomed"]))
        return terms

    name = item.get("full_name") or item.get("name") or ""
    if not name:
        return []

    terms = [("code", name, item.get("code_queries") or [name], open_systems)]
    if code_body_site:
        for site in item.get("body_site") or []:
            if site:
                terms.append(("body_site", site, [site], ["snomed"]))
    return terms


def _format_candidates_for_llm(results: list[SearchResult]) -> str:
    lines = []
    for r in results:
        lines.append(f"[{r.rank}] {r.code} — {r.display} (score: {r.score:.3f})")
    return "\n".join(lines)


async def _refine_query(prompt: str, term: str, system: str, client: genai.Client, model: str) -> str | None:
    """Ask the selector to rewrite a term the lexical search missed into the shape
    the system indexes. Reached when retrieval returned zero candidates."""
    user_msg = (
        f'Term: "{term}"\n\nCandidates:\n'
        f'(none - the {system.upper()} search returned no results; '
        f'return a refined_search_term in the form {system.upper()} indexes)'
    )
    result = await parse_structured(
        client, model, prompt, user_msg, CodeSelectorResult,
        stage="stage4", call_type=f"code_refine_{system}",
    )
    return result.refined_search_term if (result and result.refined_search_term) else None


async def _select_code(
    term: str,
    system: str,
    search_results: list[SearchResult],
    client: genai.Client,
    model: str,
    retriever: "Retriever",
) -> dict | None:
    prompt = build_code_select_prompt(system)

    # Zero retrieval hits: a verbose term the lexical APIs missed. Let the LLM
    # rewrite it into the system's indexed shape, then retrieve that (with token
    # backoff). Previously this path was unreachable on empty results.
    if not search_results:
        refined = await _refine_query(prompt, term, system, client, model)
        if not refined:
            return None
        search_results = await search_with_backoff(retriever, refined, system, 10)
        if not search_results:
            return None
        term = refined

    formatted = _format_candidates_for_llm(search_results)
    user_msg = f'Term: "{term}"\n\nCandidates:\n{formatted}'

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
        refined_results = await search_with_backoff(retriever, result.refined_search_term, system, 10)
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
        if match_fixed(c.resource_type, c.item, effective) is not None:
            continue
        open_systems, pinned = _resolve_coding(effective, c.resource_type, c.item)
        cbs = _code_body_site(effective, c.resource_type, c.item)
        for ti, (field, term, queries, systems) in enumerate(_extract_search_terms(c.resource_type, c.item, open_systems, cbs)):
            syslist = systems if field == "body_site" else _systems_for(c.resource_type, systems, pinned)
            for system in syslist:
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


def _split_jobs(
    jobs: list[tuple[int, str, str, list[str], str]],
    candidates: list[MergedCandidate],
    effective,
    top_k: int,
) -> tuple[dict[str, list[SearchResult]], list[tuple[int, str, str, list[str], str]]]:
    """Per job, gather pinned candidates from the preset's codeset, and queue API
    retrieval for open retrievable systems. The two are unioned downstream, so an
    open system free-codes AND its pinned codes are available (additive)."""
    pinned_results: dict[str, list[SearchResult]] = {}
    api_jobs: list[tuple[int, str, str, list[str], str]] = []
    for job in jobs:
        ci, key, _term, queries, system = job
        open_systems, pinned = _resolve_coding(effective, candidates[ci].resource_type, candidates[ci].item)
        pins = pinned.get(system) or []
        if pins:
            pinned_results[key] = _subset_candidates(pins, queries, top_k)
        if system in open_systems and system in RETRIEVABLE:
            api_jobs.append(job)
    return pinned_results, api_jobs


def _merge_results(results: list[SearchResult], top_k: int) -> list[SearchResult]:
    """Union candidates by code (best score wins), re-rank, cap at top_k."""
    best: dict[str, SearchResult] = {}
    for r in results:
        prev = best.get(r.code)
        if prev is None or r.score > prev.score:
            best[r.code] = r
    ordered = sorted(best.values(), key=lambda r: -r.score)[:top_k]
    return [SearchResult(code=r.code, display=r.display, score=r.score, rank=i + 1)
            for i, r in enumerate(ordered)]


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

    fixed = match_fixed(candidate.resource_type, item, effective)
    if fixed is not None:
        item["coding"] = fixed
        return candidate.model_copy(update={"item": item})

    open_systems, pinned = _resolve_coding(effective, candidate.resource_type, item)
    cbs = _code_body_site(effective, candidate.resource_type, item)
    search_terms = _extract_search_terms(candidate.resource_type, item, open_systems, cbs)

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

    tasks: list[tuple[str, int, object]] = []  # (field, term-index, coro)
    for ti, (field, term, _queries, systems) in enumerate(search_terms):
        syslist = systems if field == "body_site" else _systems_for(candidate.resource_type, systems, pinned)
        for system in syslist:
            key = f"{ci}:{ti}:{system}"
            sr = search_results.get(key, [])
            tasks.append((field, ti, _select_code(term, system, sr, client, model, retriever)))

    all_codings: list[dict] = []
    site_by_ti: dict[int, dict] = {}
    if tasks:
        results = await asyncio.gather(*(c for _, _, c in tasks))
        for (field, ti, _), r in zip(tasks, results):
            if r is None:
                continue
            if field == "body_site":
                site_by_ti.setdefault(ti, r)
            else:
                all_codings.append(r)

    if not all_codings:
        term_name = (item.get("full_name") or item.get("name")
                     or item.get("substance") or "")
        all_codings = [{"text": term_name}]

    item["coding"] = all_codings
    site_tis = [ti for ti, (field, *_) in enumerate(search_terms) if field == "body_site"]
    if site_tis:
        item["body_site_coding"] = [site_by_ti.get(ti) for ti in site_tis]
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
    candidates = [_tag_mcode_roles(c, effective) for c in stage3_output.candidates]

    own = retriever is None
    if retriever is None:
        retriever = ApiRetriever()
    try:
        jobs = _collect_search_jobs(candidates, effective)
        pinned_results, api_jobs = _split_jobs(jobs, candidates, effective, top_k)
        api_results = await _retrieve_all(api_jobs, retriever, top_k)
        search_results = {
            key: _merge_results(api_results.get(key, []) + pinned_results.get(key, []), top_k)
            for key in set(api_results) | set(pinned_results)
        }
        coded = await asyncio.gather(*(
            _code_candidate(ci, c, search_results, client, model, retriever, effective)
            for ci, c in enumerate(candidates)
        ))
    finally:
        if own and hasattr(retriever, "aclose"):
            await retriever.aclose()
    return StageFourOutput(candidates=list(coded))
