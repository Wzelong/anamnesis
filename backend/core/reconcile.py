"""Stage 5: reconcile coded candidates against the patient's existing chart.

Two-tier approach:
1. Deterministic code match — exact (system, code) lookup, ingredient
   normalization for meds, LOINC + value comparison for observations.
2. LLM adjudication — only for AMBIGUOUS results (codes differ but
   display text overlaps). Batched per resource type, parallel across types.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Literal

from openai import AsyncOpenAI

from core.code_candidates import StageFourOutput
from core.extraction import parse_structured
from core.prompts import PROMPT_RECONCILE, RECONCILE_TYPE_RULES
from core.schemas import (
    ChartMatch,
    LLMReconcileBatchResult,
    MergedCandidate,
    ReconciliationResult,
)
from fhir.models import PatientContext

log = logging.getLogger(__name__)

MatchVerdict = Literal["NEW", "DUPLICATE", "UPDATING", "CONFLICTING", "AMBIGUOUS"]

NKDA_CODE = "409137002"
TOBACCO_LOINC = "72166-2"

_DOSE_RE = re.compile(r"\s+\d+(\.\d+)?\s*(mg|mcg|g|ml|units?|%)\b.*", re.IGNORECASE)
_STRIP_PREFIXES = re.compile(
    r"^(essential|chronic|acute|mild|moderate|severe|minor|primary)\s+",
    re.IGNORECASE,
)

_TOBACCO_CURRENT = {"current every day smoker", "current some day smoker",
                     "ongoing", "active", "smoker", "current smoker",
                     "light tobacco smoker", "heavy tobacco smoker"}
_TOBACCO_FORMER = {"former smoker", "quit", "former", "tobacco-free",
                    "ex-smoker", "quit smoking"}
_TOBACCO_NEVER = {"never smoker", "never", "non-smoker"}


def _normalize_ingredient(display: str) -> str:
    return _DOSE_RE.sub("", display.lower()).strip()


def _normalize_display(text: str) -> str:
    t = text.lower().strip()
    t = _STRIP_PREFIXES.sub("", t).strip()
    return t


def _canonical_tobacco(value: str) -> str:
    v = value.lower().strip()
    if v in _TOBACCO_CURRENT or any(k in v for k in ("current", "ongoing", "active", "every day")):
        return "current"
    if v in _TOBACCO_FORMER or any(k in v for k in ("former", "quit", "tobacco-free", "ex-")):
        return "former"
    if v in _TOBACCO_NEVER or "never" in v:
        return "never"
    return v


def _extract_codes(coding_list: list[dict]) -> set[tuple[str, str]]:
    return {(c["system"], c["code"]) for c in coding_list if "system" in c and "code" in c}


def _extract_fhir_codes(resource: dict, path: str = "code") -> set[tuple[str, str]]:
    node = resource
    for part in path.split("."):
        node = node.get(part, {})
        if not node:
            return set()
    codings = node.get("coding", []) if isinstance(node, dict) else []
    return {(c["system"], c["code"]) for c in codings if "system" in c and "code" in c}


def _fhir_display(resource: dict, path: str = "code") -> str:
    node = resource
    for part in path.split("."):
        node = node.get(part, {})
        if not node:
            return ""
    if isinstance(node, dict):
        return node.get("text", "") or next(
            (c.get("display", "") for c in node.get("coding", [])), ""
        )
    return ""


def _resource_id(resource: dict) -> str:
    return resource.get("id", "") or resource.get("fullUrl", "")


# ---------------------------------------------------------------------------
# ChartIndex
# ---------------------------------------------------------------------------

@dataclass
class ChartIndex:
    code_to_resources: dict[str, dict[tuple[str, str], list[dict]]]
    display_to_resources: dict[str, dict[str, list[dict]]]
    has_nkda: bool
    obs_by_loinc: dict[str, list[tuple[dict, str]]]
    med_by_ingredient: dict[str, list[dict]]


def build_chart_index(ctx: PatientContext) -> ChartIndex:
    code_map: dict[str, dict[tuple[str, str], list[dict]]] = {}
    display_map: dict[str, dict[str, list[dict]]] = {}

    for rtype, resources, code_path in [
        ("Condition", ctx.conditions, "code"),
        ("MedicationRequest", ctx.medications, "medicationCodeableConcept"),
        ("AllergyIntolerance", ctx.allergies, "code"),
        ("Procedure", ctx.procedures, "code"),
    ]:
        cm: dict[tuple[str, str], list[dict]] = {}
        dm: dict[str, list[dict]] = {}
        for r in resources:
            for pair in _extract_fhir_codes(r, code_path):
                cm.setdefault(pair, []).append(r)
            disp = _normalize_display(_fhir_display(r, code_path))
            if disp:
                dm.setdefault(disp, []).append(r)
        code_map[rtype] = cm
        display_map[rtype] = dm

    has_nkda = False
    for a in ctx.allergies:
        for c in a.get("code", {}).get("coding", []):
            if c.get("code") == NKDA_CODE:
                has_nkda = True
                break

    obs_by_loinc: dict[str, list[tuple[dict, str]]] = {}
    for o in ctx.observations:
        for c in o.get("code", {}).get("coding", []):
            if c.get("system") == "http://loinc.org":
                val = (
                    o.get("valueCodeableConcept", {}).get("text", "")
                    or next(
                        (cd.get("display", "")
                         for cd in o.get("valueCodeableConcept", {}).get("coding", [])),
                        "",
                    )
                    or o.get("valueString", "")
                    or o.get("valueQuantity", {}).get("value", "")
                )
                obs_by_loinc.setdefault(c["code"], []).append((o, str(val)))

    med_by_ing: dict[str, list[dict]] = {}
    for m in ctx.medications:
        for c in m.get("medicationCodeableConcept", {}).get("coding", []):
            ing = _normalize_ingredient(c.get("display", ""))
            if ing:
                med_by_ing.setdefault(ing, []).append(m)

    fmh_cm: dict[tuple[str, str], list[dict]] = {}
    fmh_dm: dict[str, list[dict]] = {}
    for f in ctx.family_history:
        rel = f.get("relationship", {})
        for c in rel.get("coding", []):
            if "system" in c and "code" in c:
                fmh_cm.setdefault((c["system"], c["code"]), []).append(f)
        disp = _normalize_display(rel.get("text", "") or next(
            (c.get("display", "") for c in rel.get("coding", [])), ""
        ))
        if disp:
            fmh_dm.setdefault(disp, []).append(f)
    code_map["FamilyMemberHistory"] = fmh_cm
    display_map["FamilyMemberHistory"] = fmh_dm

    return ChartIndex(
        code_to_resources=code_map,
        display_to_resources=display_map,
        has_nkda=has_nkda,
        obs_by_loinc=obs_by_loinc,
        med_by_ingredient=med_by_ing,
    )


# ---------------------------------------------------------------------------
# Per-resource-type matchers
# ---------------------------------------------------------------------------

_MatchResult = tuple[MatchVerdict, str, list[ChartMatch], list[dict]]


def _match_condition(c: MergedCandidate, idx: ChartIndex) -> _MatchResult:
    candidate_codes = _extract_codes(c.item.get("coding", []))
    chart_codes = idx.code_to_resources.get("Condition", {})

    for pair in candidate_codes:
        if pair in chart_codes:
            matched = chart_codes[pair]
            return (
                "DUPLICATE",
                f"exact code match {pair[1]}",
                [ChartMatch(resource_id=_resource_id(m), display=_fhir_display(m), match_type="exact_code") for m in matched],
                matched,
            )

    name = _normalize_display(c.item.get("name", ""))
    chart_displays = idx.display_to_resources.get("Condition", {})
    for disp, resources in chart_displays.items():
        if name and (name in disp or disp in name):
            return (
                "AMBIGUOUS",
                f"display overlap: '{name}' ~ '{disp}'",
                [ChartMatch(resource_id=_resource_id(r), display=disp, match_type="display_text") for r in resources],
                resources,
            )

    return ("NEW", "no match in chart", [], [])


_DOSE_IN_TEXT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(mg|mcg|g|ml)\b", re.IGNORECASE)


def _extract_chart_dose(resource: dict) -> str:
    for di in resource.get("dosageInstruction", []):
        for dr in di.get("doseAndRate", []):
            q = dr.get("doseQuantity", {})
            v = q.get("value")
            if v is not None:
                return str(v)
        text = di.get("text", "")
        m = _DOSE_IN_TEXT_RE.search(text)
        if m:
            return m.group(1)
    return ""


def _find_ingredient_match(ing: str, idx: ChartIndex) -> list[dict] | None:
    if ing in idx.med_by_ingredient:
        return idx.med_by_ingredient[ing]
    for chart_ing, resources in idx.med_by_ingredient.items():
        if ing in chart_ing or chart_ing in ing:
            return resources
    return None


def _match_medication(c: MergedCandidate, idx: ChartIndex) -> _MatchResult:
    candidate_codes = _extract_codes(c.item.get("coding", []))
    chart_codes = idx.code_to_resources.get("MedicationRequest", {})

    for pair in candidate_codes:
        if pair in chart_codes:
            matched = chart_codes[pair]
            return (
                "DUPLICATE",
                f"exact RxNorm match {pair[1]}",
                [ChartMatch(resource_id=_resource_id(m), display=_fhir_display(m, "medicationCodeableConcept"), match_type="exact_code") for m in matched],
                matched,
            )

    for coding in c.item.get("coding", []):
        ing = _normalize_ingredient(coding.get("display", ""))
        if not ing:
            ing = _normalize_ingredient(c.item.get("name", ""))
        if not ing:
            continue
        matched = _find_ingredient_match(ing, idx)
        if matched is None:
            continue

        cand_dose = c.item.get("dose", {})
        cand_dose_val = cand_dose.get("value", "") if isinstance(cand_dose, dict) else ""
        chart_dose = _extract_chart_dose(matched[0])

        matches = [ChartMatch(resource_id=_resource_id(m), display=_fhir_display(m, "medicationCodeableConcept"), match_type="ingredient") for m in matched]
        if cand_dose_val and chart_dose and cand_dose_val != chart_dose:
            return ("UPDATING", f"same ingredient '{ing}', dose {chart_dose}->{cand_dose_val}", matches, matched)
        return ("DUPLICATE", f"same ingredient '{ing}'", matches, matched)

    return ("NEW", "no match in chart", [], [])


def _match_allergy(c: MergedCandidate, idx: ChartIndex) -> _MatchResult:
    candidate_codes = _extract_codes(c.item.get("coding", []))

    is_specific_allergy = not any(code == NKDA_CODE for _, code in candidate_codes)
    if is_specific_allergy and idx.has_nkda:
        substance = c.item.get("substance", "unknown")
        return (
            "CONFLICTING",
            f"chart records NKDA but candidate asserts allergy to {substance}",
            [ChartMatch(resource_id="nkda", display="No known drug allergy", match_type="exact_code")],
            [],
        )

    chart_codes = idx.code_to_resources.get("AllergyIntolerance", {})
    for pair in candidate_codes:
        if pair in chart_codes:
            matched = chart_codes[pair]
            return (
                "DUPLICATE",
                f"exact allergy code match {pair[1]}",
                [ChartMatch(resource_id=_resource_id(m), display=_fhir_display(m), match_type="exact_code") for m in matched],
                matched,
            )

    return ("NEW", "no match in chart", [], [])


def _match_observation(c: MergedCandidate, idx: ChartIndex) -> _MatchResult:
    for coding in c.item.get("coding", []):
        if coding.get("system") != "http://loinc.org":
            continue
        loinc = coding.get("code", "")
        if loinc in idx.obs_by_loinc:
            chart_entries = idx.obs_by_loinc[loinc]
            chart_resource, chart_val = chart_entries[0]
            cand_val = c.item.get("value", "")

            if loinc == TOBACCO_LOINC:
                c_canon = _canonical_tobacco(cand_val)
                ch_canon = _canonical_tobacco(chart_val)
                if c_canon == ch_canon:
                    return (
                        "DUPLICATE",
                        f"same tobacco status: {c_canon}",
                        [ChartMatch(resource_id=_resource_id(chart_resource), display=chart_val, match_type="exact_code")],
                        [chart_resource],
                    )
                return (
                    "UPDATING",
                    f"tobacco status changed: {ch_canon} -> {c_canon}",
                    [ChartMatch(resource_id=_resource_id(chart_resource), display=chart_val, match_type="exact_code")],
                    [chart_resource],
                )

            if str(cand_val).strip().lower() == str(chart_val).strip().lower():
                return (
                    "DUPLICATE",
                    f"same LOINC {loinc}, same value",
                    [ChartMatch(resource_id=_resource_id(chart_resource), display=chart_val, match_type="exact_code")],
                    [chart_resource],
                )
            return (
                "UPDATING",
                f"same LOINC {loinc}, value changed: '{chart_val}' -> '{cand_val}'",
                [ChartMatch(resource_id=_resource_id(chart_resource), display=chart_val, match_type="exact_code")],
                [chart_resource],
            )

    return ("NEW", "no LOINC match in chart", [], [])


def _match_procedure(c: MergedCandidate, idx: ChartIndex) -> _MatchResult:
    candidate_codes = _extract_codes(c.item.get("coding", []))
    chart_codes = idx.code_to_resources.get("Procedure", {})

    for pair in candidate_codes:
        if pair in chart_codes:
            matched = chart_codes[pair]
            cand_date = c.item.get("performed", "")
            for m in matched:
                chart_date = m.get("performedDateTime", "") or m.get("performedPeriod", {}).get("start", "")
                if cand_date and chart_date and cand_date == chart_date:
                    return (
                        "DUPLICATE",
                        f"same procedure code + date {cand_date}",
                        [ChartMatch(resource_id=_resource_id(m), display=_fhir_display(m), match_type="exact_code")],
                        matched,
                    )
            return ("NEW", "same procedure code but different date", [], [])

    return ("NEW", "no match in chart", [], [])


def _match_family_history(c: MergedCandidate, idx: ChartIndex) -> _MatchResult:
    rel_coding = c.item.get("coding", [])
    candidate_rel_codes = _extract_codes(rel_coding)
    chart_codes = idx.code_to_resources.get("FamilyMemberHistory", {})

    for pair in candidate_rel_codes:
        if pair in chart_codes:
            return (
                "DUPLICATE",
                f"same relationship code {pair[1]}",
                [ChartMatch(resource_id=_resource_id(m), display="", match_type="exact_code") for m in chart_codes[pair]],
                chart_codes[pair],
            )

    return ("NEW", "no match in chart", [], [])


_MATCHERS = {
    "Condition": _match_condition,
    "MedicationRequest": _match_medication,
    "AllergyIntolerance": _match_allergy,
    "Observation": _match_observation,
    "Procedure": _match_procedure,
    "FamilyMemberHistory": _match_family_history,
}


# ---------------------------------------------------------------------------
# LLM batch classify
# ---------------------------------------------------------------------------

def _format_pair(index: int, candidate: MergedCandidate, chart_resource: dict) -> str:
    cand_summary = {
        "name": candidate.item.get("name") or candidate.item.get("substance", ""),
        "coding": candidate.item.get("coding", []),
    }
    chart_summary = {
        "id": _resource_id(chart_resource),
        "code": chart_resource.get("code", chart_resource.get("medicationCodeableConcept", {})),
    }
    return f"[{index}] Candidate: {json.dumps(cand_summary)}\n    Chart:     {json.dumps(chart_summary)}"


async def _llm_batch_classify(
    resource_type: str,
    pairs: list[tuple[int, MergedCandidate, list[dict]]],
    client: AsyncOpenAI,
    model: str,
) -> dict[int, tuple[str, str]]:
    if not pairs:
        return {}

    type_rules = RECONCILE_TYPE_RULES.get(resource_type, "")
    prompt = PROMPT_RECONCILE.format(resource_type=resource_type, type_rules=type_rules)

    lines = []
    for idx, (orig_idx, cand, chart_resources) in enumerate(pairs):
        chart_r = chart_resources[0] if chart_resources else {}
        lines.append(_format_pair(idx, cand, chart_r))

    user_msg = "\n\n".join(lines)

    result = await parse_structured(
        client, model, prompt, user_msg, LLMReconcileBatchResult,
        stage="stage5", call_type=f"reconcile_{resource_type.lower()}",
    )

    out: dict[int, tuple[str, str]] = {}
    if result:
        for d in result.decisions:
            if 0 <= d.index < len(pairs):
                orig_idx = pairs[d.index][0]
                out[orig_idx] = (d.classification, d.reasoning)

    return out


# ---------------------------------------------------------------------------
# StageFiveOutput + entry point
# ---------------------------------------------------------------------------

@dataclass
class StageFiveOutput:
    results: list[ReconciliationResult] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"results": [r.model_dump(mode="json") for r in self.results]}

    @classmethod
    def from_json(cls, data: dict) -> StageFiveOutput:
        return cls(
            results=[ReconciliationResult.model_validate(r) for r in data["results"]],
        )


async def reconcile(
    stage4_output: StageFourOutput,
    patient_context: PatientContext,
    client: AsyncOpenAI,
    *,
    model: str,
) -> StageFiveOutput:
    chart_index = build_chart_index(patient_context)

    resolved: dict[int, ReconciliationResult] = {}
    ambiguous: list[tuple[int, MergedCandidate, str, list[ChartMatch], list[dict]]] = []

    for ci, cand in enumerate(stage4_output.candidates):
        matcher = _MATCHERS.get(cand.resource_type)
        if matcher is None:
            resolved[ci] = ReconciliationResult(
                candidate=cand, classification="NEW",
                reasoning=f"unknown resource type {cand.resource_type}",
            )
            continue

        verdict, reasoning, chart_matches, raw_resources = matcher(cand, chart_index)
        if verdict == "AMBIGUOUS":
            ambiguous.append((ci, cand, reasoning, chart_matches, raw_resources))
        else:
            resolved[ci] = ReconciliationResult(
                candidate=cand, classification=verdict,
                reasoning=reasoning, chart_matches=chart_matches,
            )

    if ambiguous:
        by_type: dict[str, list[tuple[int, MergedCandidate, list[dict]]]] = {}
        for ci, cand, _reason, _matches, raw_resources in ambiguous:
            by_type.setdefault(cand.resource_type, []).append((ci, cand, raw_resources))

        tasks = [
            _llm_batch_classify(rtype, pairs, client, model)
            for rtype, pairs in by_type.items()
        ]
        llm_results = await asyncio.gather(*tasks)

        llm_map: dict[int, tuple[str, str]] = {}
        for result_dict in llm_results:
            llm_map.update(result_dict)

        for ci, cand, det_reasoning, chart_matches, _raw in ambiguous:
            if ci in llm_map:
                classification, llm_reasoning = llm_map[ci]
                resolved[ci] = ReconciliationResult(
                    candidate=cand, classification=classification,
                    reasoning=f"{det_reasoning}; LLM: {llm_reasoning}",
                    chart_matches=chart_matches,
                )
            else:
                resolved[ci] = ReconciliationResult(
                    candidate=cand, classification="NEW",
                    reasoning=f"{det_reasoning}; LLM failed, defaulting to NEW",
                    chart_matches=chart_matches,
                )

    results = [resolved[i] for i in range(len(stage4_output.candidates))]
    n_by_class = {}
    for r in results:
        n_by_class[r.classification] = n_by_class.get(r.classification, 0) + 1
    log.info("stage5 reconciliation: %s (%d ambiguous -> LLM)", n_by_class, len(ambiguous))

    return StageFiveOutput(results=results)
