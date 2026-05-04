"""Stage 3 — cross-note dedupe.

Patient-level types (Condition, MedicationRequest, AllergyIntolerance,
FamilyMemberHistory) dedupe globally across notes; encounter-level types
(Observation, Procedure) dedupe only within the same encounter.

Two phases:
  1. Deterministic exact-match merge by `(resource_type, encounter_key,
     normalized_name, value/dose)` — zero LLM calls.
  2. LLM adjudication for fuzzy near-duplicates within the same scope, batched
     per scope (typically 0–2 calls per run).
"""
from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass, field

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from core.cache import JsonCache
from core.extraction import StageTwoOutput, parse_structured as _parse_structured
from core.prompts import PROMPT_MERGE_ADJUDICATE, PROMPT_VERSION
from core.schemas import MergeAdjudicationResult, MergedCandidate, SourceRef


@dataclass
class StageThreeOutput:
    candidates: list[MergedCandidate] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"candidates": [c.model_dump(mode="json") for c in self.candidates]}

    @classmethod
    def from_json(cls, data: dict) -> "StageThreeOutput":
        return cls(
            candidates=[MergedCandidate.model_validate(c) for c in data["candidates"]],
        )


PATIENT_LEVEL_TYPES = {"Condition", "MedicationRequest", "AllergyIntolerance", "FamilyMemberHistory"}
ENCOUNTER_LEVEL_TYPES = {"Observation", "Procedure"}

_DISCONTINUED_MED_STATUSES = frozenset({"stopped", "cancelled", "completed", "entered-in-error"})


def _is_conflict_signal(t: "_TaggedItem") -> bool:
    if t.resource_type == "MedicationRequest":
        status = getattr(t.item, "status", None)
        if status in _DISCONTINUED_MED_STATUSES:
            return True
    if t.resource_type == "Condition":
        if getattr(t.item, "negated", False):
            return True
    return False


@dataclass
class _TaggedItem:
    resource_type: str
    item: BaseModel
    document_id: str
    source_sentences: list[int]
    normalized_name: str
    encounter_key: str


_STRIP_PREFIXES = re.compile(
    r"^(essential|chronic|acute|mild|moderate|severe|minor)\s+", re.IGNORECASE
)


def _normalize_name(name: str) -> str:
    s = name.strip().lower()
    s = _STRIP_PREFIXES.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _get_item_name(resource_type: str, item: BaseModel) -> str:
    if resource_type == "AllergyIntolerance":
        return getattr(item, "substance", "")
    if resource_type == "FamilyMemberHistory":
        return getattr(item, "relationship", "")
    return getattr(item, "name", "")


def _item_completeness(item: BaseModel) -> int:
    score = 0
    for field_name in type(item).model_fields:
        val = getattr(item, field_name)
        if val is not None and val != [] and val != "":
            score += 1
    return score


def _derive_encounter_key(s2: StageTwoOutput) -> str:
    if s2.encounter_id:
        return s2.encounter_id
    nd = s2.note_context.note_date.value
    if nd:
        return nd[:10]
    return s2.document_id


def _observation_encounter_key(item: BaseModel, fallback: str) -> str:
    """For Observations, anchor to the lab's own effective_date (month precision)
    so the same external lab quoted in different notes lands in the same group.
    """
    eff = getattr(item, "effective_date", None)
    if eff:
        return f"obs:{eff[:7]}"
    return fallback


def _build_tagged_items(stage2_outputs: list[StageTwoOutput]) -> list[_TaggedItem]:
    tagged: list[_TaggedItem] = []
    for s2 in stage2_outputs:
        note_enc_key = _derive_encounter_key(s2)
        for rtype, items in s2.candidates.items():
            for item in items:
                name = _get_item_name(rtype, item)
                enc_key = (
                    _observation_encounter_key(item, note_enc_key)
                    if rtype == "Observation" else note_enc_key
                )
                tagged.append(_TaggedItem(
                    resource_type=rtype,
                    item=item,
                    document_id=s2.document_id,
                    source_sentences=list(item.source_sentences),
                    normalized_name=_normalize_name(name),
                    encounter_key=enc_key,
                ))
    return tagged


def _group_key(t: _TaggedItem) -> str:
    if t.resource_type in ENCOUNTER_LEVEL_TYPES:
        key = f"{t.resource_type}::{t.encounter_key}::{t.normalized_name}"
        if t.resource_type == "Observation":
            val = getattr(t.item, "value", "") or ""
            key += f"::{val.strip().lower()}"
    else:
        key = f"{t.resource_type}::{t.normalized_name}"
        if t.resource_type == "MedicationRequest":
            dose = getattr(t.item, "dose", None)
            if dose:
                key += f"::{dose.value.strip().lower()} {dose.unit.strip().lower()}"
    return key


def _deterministic_group(
    tagged: list[_TaggedItem],
) -> dict[str, list[_TaggedItem]]:
    groups: dict[str, list[_TaggedItem]] = {}
    for t in tagged:
        groups.setdefault(_group_key(t), []).append(t)
    return groups


def _resolve_exact_matches(
    groups: dict[str, list[_TaggedItem]],
) -> tuple[list[MergedCandidate], dict[str, list[_TaggedItem]]]:
    by_rtype: dict[str, list[str]] = {}
    for key in groups:
        rtype = key.split("::")[0]
        by_rtype.setdefault(rtype, []).append(key)

    needs_llm: set[str] = set()
    for rtype, keys in by_rtype.items():
        if len(keys) > 1:
            needs_llm.update(keys)

    resolved: list[MergedCandidate] = []
    ambiguous: dict[str, list[_TaggedItem]] = {}

    for key, items in groups.items():
        if key in needs_llm:
            ambiguous[key] = items
            continue

        enc_key = items[0].encounter_key if items[0].resource_type in ENCOUNTER_LEVEL_TYPES else None
        doc_ids = set(t.document_id for t in items)
        if len(doc_ids) <= 1:
            for t in items:
                resolved.append(MergedCandidate(
                    resource_type=t.resource_type,
                    item=t.item.model_dump(mode="json"),
                    source_refs=[SourceRef(
                        document_id=t.document_id,
                        source_sentences=t.source_sentences,
                    )],
                    encounter_key=enc_key,
                ))
        else:
            survivor = max(items, key=lambda t: _item_completeness(t.item))
            resolved.append(MergedCandidate(
                resource_type=survivor.resource_type,
                item=survivor.item.model_dump(mode="json"),
                source_refs=[
                    SourceRef(document_id=t.document_id, source_sentences=t.source_sentences)
                    for t in items
                ],
                encounter_key=enc_key,
                merge_reasoning=f"exact match across {len(doc_ids)} notes",
            ))

    return resolved, ambiguous


def _format_groups_for_llm(groups: dict[str, list[_TaggedItem]]) -> str:
    lines: list[str] = []
    for i, (key, items) in enumerate(sorted(groups.items()), 1):
        rtype = key.split("::")[0]
        names = sorted(set(_get_item_name(t.resource_type, t.item) for t in items))
        name_str = " / ".join(names)

        details: list[str] = []
        for t in items:
            d = t.item.model_dump(mode="json")
            parts = [f"doc={t.document_id[:12]}"]
            for fld in ("value", "severity", "onset", "dose", "effective_date", "performed"):
                if fld in d and d[fld]:
                    parts.append(f"{fld}={d[fld]}")
            details.append("(" + ", ".join(parts) + ")")

        lines.append(f"[{i}] {rtype}: \"{name_str}\" {'; '.join(details)}")
    return "\n".join(lines)


def _items_to_candidate(items: list[_TaggedItem], merge_reasoning: str | None = None) -> MergedCandidate:
    enc_key = items[0].encounter_key if items[0].resource_type in ENCOUNTER_LEVEL_TYPES else None
    doc_ids = set(t.document_id for t in items)
    if len(doc_ids) <= 1 and merge_reasoning is None:
        survivor = items[0]
    else:
        survivor = max(items, key=lambda t: _item_completeness(t.item))
    if merge_reasoning is None and len(doc_ids) > 1:
        merge_reasoning = f"exact match across {len(doc_ids)} notes"
    return MergedCandidate(
        resource_type=survivor.resource_type,
        item=survivor.item.model_dump(mode="json"),
        source_refs=[
            SourceRef(document_id=t.document_id, source_sentences=t.source_sentences)
            for t in items
        ],
        encounter_key=enc_key,
        merge_reasoning=merge_reasoning,
    )


def _groups_to_candidates(
    groups: dict[str, list[_TaggedItem]],
) -> list[MergedCandidate]:
    candidates: list[MergedCandidate] = []
    for key, items in groups.items():
        doc_ids = set(t.document_id for t in items)
        if len(doc_ids) <= 1:
            for t in items:
                candidates.append(_items_to_candidate([t]))
        else:
            candidates.append(_items_to_candidate(items))
    return candidates


def _apply_adjudication(
    groups: dict[str, list[_TaggedItem]],
    result: MergeAdjudicationResult,
) -> list[MergedCandidate]:
    """Translate the LLM's merge / reassign / keep decisions back into MergedCandidates.

    Walks `result.decisions`: for `merge` and `reassign` actions, picks the
    most-complete item from the survivor group, unions all source refs, and
    optionally retypes via `decision.target_resource_type`. Groups not
    consumed by any decision pass through untouched.
    """
    group_keys = list(sorted(groups.keys()))
    consumed: set[int] = set()
    candidates: list[MergedCandidate] = []

    for decision in result.decisions:
        if decision.action == "keep":
            continue

        valid_ids = [gid for gid in decision.group_ids if 1 <= gid <= len(group_keys)]
        if not valid_ids:
            continue

        survivor_id = decision.survivor_group_id
        if survivor_id not in valid_ids:
            survivor_id = valid_ids[0]

        all_items: list[_TaggedItem] = []
        for gid in valid_ids:
            all_items.extend(groups[group_keys[gid - 1]])
            consumed.add(gid)

        survivor_group = groups[group_keys[survivor_id - 1]]
        survivor = max(survivor_group, key=lambda t: _item_completeness(t.item))
        target_rtype = decision.target_resource_type or survivor.resource_type
        enc_key = survivor.encounter_key if target_rtype in ENCOUNTER_LEVEL_TYPES else None

        candidates.append(MergedCandidate(
            resource_type=target_rtype,
            item=survivor.item.model_dump(mode="json"),
            source_refs=[
                SourceRef(document_id=t.document_id, source_sentences=t.source_sentences)
                for t in all_items
            ],
            encounter_key=enc_key,
            merge_reasoning=decision.reasoning,
        ))

    for i, key in enumerate(sorted(groups.keys()), 1):
        if i in consumed:
            continue
        items = groups[key]
        doc_ids = set(t.document_id for t in items)
        if len(doc_ids) <= 1:
            for t in items:
                candidates.append(_items_to_candidate([t]))
        else:
            candidates.append(_items_to_candidate(items))

    return candidates


def _merge_cache_key(llm_input: str, model: str) -> str:
    h = hashlib.sha256()
    h.update(llm_input.encode("utf-8"))
    h.update(b"\x00")
    h.update(model.encode("utf-8"))
    h.update(b"\x00")
    h.update(PROMPT_VERSION.encode("utf-8"))
    return h.hexdigest()


async def _adjudicate_groups(
    groups: dict[str, list[_TaggedItem]],
    client: AsyncOpenAI,
    model: str,
    cache: JsonCache | None,
    call_type: str,
) -> list[MergedCandidate]:
    if not groups:
        return []

    llm_input = _format_groups_for_llm(groups)
    adjudication: MergeAdjudicationResult | None = None
    cache_key = _merge_cache_key(llm_input, model)

    if cache is not None:
        cached = cache.get(cache_key)
        if cached is not None:
            try:
                adjudication = MergeAdjudicationResult.model_validate(cached)
            except ValidationError:
                pass

    if adjudication is None:
        adjudication = await _parse_structured(
            client,
            model,
            PROMPT_MERGE_ADJUDICATE,
            llm_input,
            MergeAdjudicationResult,
            stage="stage3",
            call_type=call_type,
            reasoning_effort="low",
        )
        if adjudication and cache is not None:
            cache.put(cache_key, adjudication.model_dump(mode="json"))

    if adjudication:
        return _apply_adjudication(groups, adjudication)
    return _groups_to_candidates(groups)


async def merge_across_notes(
    stage2_outputs: list[StageTwoOutput],
    client: AsyncOpenAI,
    *,
    model: str,
    cache: JsonCache | None = None,
) -> StageThreeOutput:
    """Run Stage 3: cross-note dedupe with deterministic-first then LLM-adjudicated merge.

    Patient-level types (Condition, MedicationRequest, AllergyIntolerance,
    FamilyMemberHistory) dedupe globally across notes; encounter-level types
    (Observation, Procedure) dedupe only within the same encounter (encounter
    key = `encounter_id` -> note date -> document_id fallback).

    Two phases per scope:
      1. Exact-match merge by `(resource_type, encounter_key, normalized_name,
         value/dose)` — zero LLM calls. Multi-doc matches are merged
         deterministically; the most-complete item wins as the survivor.
      2. LLM adjudication for fuzzy near-duplicates within the same scope
         (e.g. "coronary artery disease" vs "two-vessel coronary artery
         disease"). One call per scope, all in parallel via `asyncio.gather`.

    Cached by `(scope, prompt_version, sorted_group_keys)` so re-runs are
    free on the second pass.
    """
    if not stage2_outputs:
        return StageThreeOutput()

    tagged = _build_tagged_items(stage2_outputs)
    groups = _deterministic_group(tagged)
    resolved, ambiguous = _resolve_exact_matches(groups)

    protected_keys = [k for k, items in ambiguous.items() if any(_is_conflict_signal(t) for t in items)]
    if protected_keys:
        protected_groups = {k: ambiguous.pop(k) for k in protected_keys}
        resolved.extend(_groups_to_candidates(protected_groups))

    if not ambiguous:
        return StageThreeOutput(candidates=resolved)

    patient_ambiguous = {
        k: v for k, v in ambiguous.items()
        if v[0].resource_type in PATIENT_LEVEL_TYPES
    }
    encounter_ambiguous = {
        k: v for k, v in ambiguous.items()
        if v[0].resource_type in ENCOUNTER_LEVEL_TYPES
    }

    tasks: list[asyncio.Task] = []

    if patient_ambiguous:
        tasks.append(asyncio.create_task(
            _adjudicate_groups(patient_ambiguous, client, model, cache, "merge_patient")
        ))

    enc_groups_by_key: dict[str, dict[str, list[_TaggedItem]]] = {}
    for k, items in encounter_ambiguous.items():
        enc_key = items[0].encounter_key
        enc_groups_by_key.setdefault(enc_key, {})[k] = items

    for enc_key, enc_groups in enc_groups_by_key.items():
        if any(len(v) > 1 or len(enc_groups) > 1 for v in enc_groups.values()):
            tasks.append(asyncio.create_task(
                _adjudicate_groups(enc_groups, client, model, cache, f"merge_enc_{enc_key[:8]}")
            ))
        else:
            resolved.extend(_groups_to_candidates(enc_groups))

    for result in await asyncio.gather(*tasks):
        resolved.extend(result)

    return StageThreeOutput(candidates=resolved)
