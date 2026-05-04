"""Stage 5: reconcile coded candidates against the patient's existing chart.

Two-tier approach:
  1. Deterministic code match (`core.reconcile_match_rules._MATCHERS`) — exact
     `(system, code)` lookup, ingredient normalization for meds, LOINC + value
     comparison for observations, NKDA-vs-specific-allergy detection, etc.
  2. LLM adjudication — only for AMBIGUOUS results (codes differ but display
     text overlaps). Batched per resource type, parallel across types.

The match rules and ChartIndex live in `core.reconcile_match_rules` and are
re-exported below so existing call sites (`from core.reconcile import
ChartIndex`, etc.) keep working unchanged.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field

from openai import AsyncOpenAI

from core.code_candidates import StageFourOutput
from core.extraction import parse_structured
from core.prompts import PROMPT_RECONCILE, RECONCILE_TYPE_RULES
from core.reconcile_match_rules import (
    _DISCONTINUED_STATUSES,
    _MATCHERS,
    ChartIndex,
    NKDA_CODE,
    TOBACCO_LOINC,
    _normalize_ingredient,
    _resource_id,
    build_chart_index,
)
from core.schemas import (
    ChartMatch,
    ConfidenceAxis,
    ConfidenceBreakdown,
    LLMReconcileBatchResult,
    MergedCandidate,
    ReconciliationResult,
)
from fhir.models import PatientContext

log = logging.getLogger(__name__)

__all__ = [
    "reconcile",
    "StageFiveOutput",
    # Re-exported from reconcile_match_rules for backwards-compat:
    "_DISCONTINUED_STATUSES",
    "ChartIndex",
    "build_chart_index",
    "NKDA_CODE",
    "TOBACCO_LOINC",
    "_normalize_ingredient",
]


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


_CERTAINTY_BASE = {"definite": 1.0, "probable": 0.6, "uncertain": 0.25}
_CERTAINTY_PROMOTED = {"definite": 1.0, "probable": 1.0, "uncertain": 0.6}

_W_CERTAINTY = 0.5
_W_CODING = 0.5

_CONFIDENT_THRESHOLD = 0.80
_REVIEW_THRESHOLD = 0.40


def _compute_confidence(result: ReconciliationResult) -> ReconciliationResult:
    """Attach `confidence_score`, `confidence_tier`, `flags`, and `breakdown` to a result.

    Two deterministic signals drive the score:
      * **Certainty** (weight 0.4 — promoted to 0.5 when corroborated by ≥2
        notes) — LLM-labeled `definite` / `probable` / `uncertain`. The LLM is
        good at categorical language classification but bad at numeric
        confidence; we use the label and ignore self-reported numbers.
      * **Coding** (weight 0.6) — real terminology code found, with a small
        bonus when ≥2 systems agree (e.g. SNOMED + ICD-10 both bound to a
        Condition). Falls to 0.3 when only text-only coding remains.

    Tier thresholds:
      * `CONFLICTING` -> `ATTENTION` (hard override; never auto-approve a
        clinical contradiction).
      * `AllergyIntolerance` with `uncertain` certainty or no real code ->
        `ATTENTION` (allergy mistakes are high-stakes).
      * composite ≥ 0.70 -> `CONFIDENT` (downgraded to `REVIEW` if no real code).
      * composite ≥ 0.40 -> `REVIEW`.
      * else -> `ATTENTION`.

    Flags are human-readable reasons the clinician can verify, derived from
    the same signals.
    """
    item = result.candidate.item
    refs = result.candidate.source_refs
    cls = result.classification
    n_docs = len({sr.document_id for sr in refs})

    certainty = item.get("certainty", "probable")
    corroborated = n_docs >= 2
    certainty_score = (
        _CERTAINTY_PROMOTED if corroborated else _CERTAINTY_BASE
    ).get(certainty, 0.6)
    certainty_reason = {
        "definite": "Stated assertively",
        "probable": "Probable in source" + (" (corroborated)" if corroborated else ""),
        "uncertain": "Uncertain or secondhand" + (" (corroborated)" if corroborated else ""),
    }.get(certainty, "Probable in source")

    codings = item.get("coding", [])
    has_real_code = any("code" in c for c in codings)
    if has_real_code:
        coding_score = 1.0
        systems = {c.get("system", "").split("/")[-1] for c in codings if "system" in c}
        systems.discard("")
        coding_reason = (
            f"Coded in {len(systems)} systems ({', '.join(sorted(systems))})"
            if len(systems) >= 2
            else f"{len([c for c in codings if 'code' in c])} terminology code"
        )
    else:
        coding_score = 0.3
        coding_reason = "No terminology code"

    composite = certainty_score * _W_CERTAINTY + coding_score * _W_CODING

    breakdown = ConfidenceBreakdown(
        certainty=ConfidenceAxis(
            score=round(certainty_score, 3),
            weight=_W_CERTAINTY,
            contribution=round(certainty_score * _W_CERTAINTY, 3),
            reason=certainty_reason,
        ),
        coding=ConfidenceAxis(
            score=round(coding_score, 3),
            weight=_W_CODING,
            contribution=round(coding_score * _W_CODING, 3),
            reason=coding_reason,
        ),
    )

    resource_type = result.candidate.resource_type
    if cls == "CONFLICTING":
        tier = "ATTENTION"
    elif resource_type == "AllergyIntolerance" and (certainty == "uncertain" or not has_real_code):
        tier = "ATTENTION"
    elif composite >= _CONFIDENT_THRESHOLD:
        tier = "REVIEW" if not has_real_code else "CONFIDENT"
    elif composite >= _REVIEW_THRESHOLD:
        tier = "REVIEW"
    else:
        tier = "ATTENTION"

    flags: list[str] = []

    if n_docs >= 2:
        flags.append(f"Mentioned in {n_docs} notes")

    if certainty == "uncertain":
        flags.append("Source language is uncertain or secondhand")
    elif certainty == "definite":
        flags.append("Stated assertively in source")

    if not has_real_code:
        flags.append("No terminology code found — verify manually")
    else:
        systems = {c.get("system", "").split("/")[-1] for c in codings if "system" in c}
        systems.discard("")
        if len(systems) >= 2:
            flags.append(f"Coded in {len(systems)} systems ({', '.join(sorted(systems))})")

    best_match_type = None
    if result.chart_matches:
        priority = {"exact_code": 3, "ingredient": 2, "display_text": 1}
        best_match_type = max(result.chart_matches, key=lambda m: priority.get(m.match_type, 0)).match_type

    if cls == "CONFLICTING":
        displays = [m.display for m in result.chart_matches if m.display]
        conflict_desc = displays[0] if displays else "existing chart record"
        flags.append(f"Conflicts with: {conflict_desc}")
    elif cls == "UPDATING":
        change = result.reasoning.split(",", 1)[-1].strip() if "," in result.reasoning else result.reasoning
        flags.append(f"Updates existing: {change}")
    elif cls == "DUPLICATE":
        flags.append("Already in chart")

    if best_match_type == "display_text":
        flags.append("Approximate match — verify")

    return result.model_copy(update={
        "confidence_score": round(composite, 3),
        "confidence_tier": tier,
        "flags": flags,
        "confidence_breakdown": breakdown,
    })


async def reconcile(
    stage4_output: StageFourOutput,
    patient_context: PatientContext,
    client: AsyncOpenAI,
    *,
    model: str,
) -> StageFiveOutput:
    """Run Stage 5: classify each candidate against the existing chart.

    Two-tier strategy:
      1. **Deterministic match** per resource type (`_MATCHERS`) — exact
         `(system, code)` lookups, ingredient + dose comparisons, NKDA-vs-
         specific-allergy detection, LOINC value diffs, etc. Returns NEW /
         DUPLICATE / UPDATING / CONFLICTING for the easy cases, AMBIGUOUS
         for cases where codes differ but display text overlaps.
      2. **LLM adjudication** for AMBIGUOUS cases, batched per resource type
         (typically 0–2 calls per run). Failure or timeout falls back to NEW.

    Every result is then run through `_compute_confidence` to attach the
    confidence score, tier, flags, and breakdown.
    """
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

    results = [_compute_confidence(resolved[i]) for i in range(len(stage4_output.candidates))]
    n_by_class = {}
    for r in results:
        n_by_class[r.classification] = n_by_class.get(r.classification, 0) + 1
    log.info("stage5 reconciliation: %s (%d ambiguous -> LLM)", n_by_class, len(ambiguous))

    return StageFiveOutput(results=results)
