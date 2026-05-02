"""Stage 2 (scan -> parse -> clean) and Stage 3 (cross-note dedupe).

Stage 2 turns a PreprocessedNote into candidates per type, all with
source_sentences traceable to the numbered note.

Stage 3 merges candidates from multiple notes into a flat list with
multi-document source refs.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from core import telemetry
from core.cache import JsonCache
from core.preprocess import PreprocessedNote, SentenceSpan
from core.prompts import (
    PROMPT_CLEAN,
    PROMPT_MERGE_ADJUDICATE,
    PROMPT_SCAN,
    PROMPT_VERSION,
    PROMPTS_BY_TYPE,
)
from core.schemas import (
    CleanerResult,
    DatedField,
    ITEM_LIST_MODELS,
    MergeAdjudicationResult,
    MergedCandidate,
    NoteContext,
    RESOURCE_TYPES,
    ScanResult,
    SourceRef,
)
from core.validation import validate_fhir_date

log = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "stage2"


@dataclass
class StageTwoOutput:
    document_id: str
    note_context: NoteContext
    candidates: dict[str, list[BaseModel]] = field(default_factory=dict)
    raw_scan: ScanResult | None = None
    encounter_id: str | None = None

    def to_json(self) -> dict:
        return {
            "document_id": self.document_id,
            "encounter_id": self.encounter_id,
            "prompt_version": PROMPT_VERSION,
            "note_context": self.note_context.model_dump(mode="json"),
            "raw_scan": self.raw_scan.model_dump(mode="json") if self.raw_scan else None,
            "candidates": {
                t: [c.model_dump(mode="json") for c in items]
                for t, items in self.candidates.items()
            },
        }

    @classmethod
    def from_json(cls, data: dict) -> "StageTwoOutput":
        out = cls(
            document_id=data["document_id"],
            note_context=NoteContext.model_validate(data["note_context"]),
            raw_scan=ScanResult.model_validate(data["raw_scan"]) if data.get("raw_scan") else None,
            encounter_id=data.get("encounter_id"),
        )
        for rtype, items in (data.get("candidates") or {}).items():
            model = _item_model_for(rtype)
            out.candidates[rtype] = [model.model_validate(i) for i in items]
        return out


def _item_model_for(resource_type: str) -> type[BaseModel]:
    list_model = ITEM_LIST_MODELS[resource_type]
    return list_model.model_fields["items"].annotation.__args__[0]


def _build_snippet(group: list[int], sentences_by_number: dict[int, SentenceSpan]) -> str:
    lines: list[str] = []
    for n in sorted(group):
        span = sentences_by_number.get(n)
        if span is None:
            continue
        text = " ".join(span.text.split())
        lines.append(f"[{n}] {text}")
    return "\n".join(lines)


def _render_temporal_context(note_context: NoteContext) -> str:
    parts: list[str] = []
    for label, field_name in (
        ("note_date", "note_date"),
        ("admission_date", "admission_date"),
        ("discharge_date", "discharge_date"),
    ):
        value = getattr(note_context, field_name).value
        if value is not None:
            parts.append(f"{label}={value}")
    return "; ".join(parts) if parts else "none"


async def parse_structured(
    client: AsyncOpenAI,
    model: str,
    developer_prompt: str,
    user_content: str,
    response_model: type[BaseModel],
    *,
    stage: str = "stage2",
    call_type: str,
    document_id: str | None = None,
    reasoning_effort: str = "low",
) -> BaseModel | None:
    started_at = datetime.now(timezone.utc)
    usage: dict | None = None
    status = "ok"
    error: str | None = None
    parsed: BaseModel | None = None
    try:
        response = await client.responses.parse(
            model=model,
            reasoning={"effort": reasoning_effort},
            input=[
                {"role": "developer", "content": developer_prompt},
                {"role": "user", "content": user_content},
            ],
            text_format=response_model,
        )
        usage = response.usage.model_dump() if getattr(response, "usage", None) else None
        parsed = response.output_parsed
        if parsed is None:
            status = "error"
            error = "no_parsed_output"
            log.warning("openai returned no parsed output for %s", response_model.__name__)
    except Exception as exc:
        status = "error"
        error = f"{type(exc).__name__}: {exc}"
        log.warning("openai parse failed (%s): %s", response_model.__name__, exc)

    finished_at = datetime.now(timezone.utc)
    await telemetry.record_call(
        stage=stage,
        call_type=call_type,
        model=model,
        prompt_version=PROMPT_VERSION,
        started_at=started_at,
        finished_at=finished_at,
        usage=usage,
        status=status,
        error=error,
        document_id=document_id,
    )
    return parsed

_parse_structured = parse_structured


async def scan_note(
    note: PreprocessedNote,
    client: AsyncOpenAI,
    model: str,
) -> ScanResult:
    parsed = await _parse_structured(
        client,
        model,
        PROMPT_SCAN,
        note.numbered_note,
        ScanResult,
        call_type="scan",
        document_id=note.document_id,
        reasoning_effort="low",
    )
    scan = parsed or ScanResult()
    scan = _sanitize_note_context_dates(scan, note)
    return scan


def _sanitize_note_context_dates(scan: ScanResult, note: PreprocessedNote) -> ScanResult:
    snippet = note.original_text
    nc = scan.note_context
    raw_note_date = nc.note_date.value

    def _fix(df: DatedField, ref: str | None) -> DatedField:
        kept, reason = validate_fhir_date(df.value, snippet, ref)
        if kept is None and df.value is not None:
            telemetry.log_event_sync("date_reject", {
                "document_id": note.document_id,
                "field": "note_context",
                "value": df.value,
                "reason": reason,
            })
            return DatedField(value=None, source_sentences=df.source_sentences)
        return df

    nc.note_date = _fix(nc.note_date, raw_note_date)
    nc.admission_date = _fix(nc.admission_date, nc.note_date.value)
    nc.discharge_date = _fix(nc.discharge_date, nc.note_date.value)
    scan.note_context = nc
    return scan


async def parse_group(
    resource_type: str,
    snippet: str,
    note_context: NoteContext,
    client: AsyncOpenAI,
    model: str,
    allowed_sentences: set[int],
    *,
    document_id: str | None = None,
) -> list[BaseModel]:
    prompt = PROMPTS_BY_TYPE[resource_type]
    list_model = ITEM_LIST_MODELS[resource_type]
    user_content = (
        f"Temporal context: {_render_temporal_context(note_context)}\n\n"
        f"Snippet:\n{snippet}"
    )
    parsed = await _parse_structured(
        client,
        model,
        prompt,
        user_content,
        list_model,
        call_type=f"parse_{resource_type}",
        document_id=document_id,
    )
    if parsed is None:
        return []

    note_date = note_context.note_date.value if note_context else None
    kept: list[BaseModel] = []
    for item in parsed.items:
        src = [n for n in (item.source_sentences or []) if n in allowed_sentences]
        if not src:
            src = sorted(allowed_sentences)
        updates: dict[str, Any] = {"source_sentences": src}

        item = _apply_date_validators(item, resource_type, snippet, note_date, document_id)
        if resource_type == "FamilyMemberHistory" and not getattr(item, "conditions", None):
            continue
        item = item.model_copy(update=updates)
        kept.append(item)
    return kept


def _apply_date_validators(
    item: BaseModel,
    resource_type: str,
    snippet: str,
    note_date: str | None,
    document_id: str | None,
) -> BaseModel:
    field_name: str | None = None
    if resource_type == "Observation":
        field_name = "effective_date"
    elif resource_type == "Procedure":
        field_name = "performed"
    if field_name is None:
        return item

    current = getattr(item, field_name, None)
    if current is None:
        return item
    kept, reason = validate_fhir_date(current, snippet, note_date)
    if kept is None:
        telemetry.log_event_sync("date_reject", {
            "document_id": document_id,
            "field": f"{resource_type}.{field_name}",
            "value": current,
            "reason": reason,
        })
        return item.model_copy(update={field_name: None})
    if kept != current:
        return item.model_copy(update={field_name: kept})
    return item


async def clean_candidates(
    resource_type: str,
    candidates: list[BaseModel],
    client: AsyncOpenAI,
    model: str,
    *,
    document_id: str | None = None,
) -> list[BaseModel]:
    if len(candidates) <= 1:
        return candidates

    numbered = "\n".join(
        f"[{i + 1}] {json.dumps(c.model_dump(mode='json'), ensure_ascii=False)}"
        for i, c in enumerate(candidates)
    )
    user_content = f"Resource type: {resource_type}\n\n{numbered}"
    result = await _parse_structured(
        client,
        model,
        PROMPT_CLEAN,
        user_content,
        CleanerResult,
        call_type=f"clean_{resource_type}",
        document_id=document_id,
    )
    if result is None:
        return candidates

    return _apply_cleaner(candidates, result)


def _apply_cleaner(
    candidates: list[BaseModel], result: CleanerResult
) -> list[BaseModel]:
    n = len(candidates)
    keep_flags = [True] * n
    merged_sources: dict[int, list[int]] = {}

    for idx in result.discard or []:
        if 1 <= idx <= n:
            keep_flags[idx - 1] = False

    for grp in result.deduplicate or []:
        valid_group = [i for i in grp.group if 1 <= i <= n]
        if not valid_group:
            continue
        keep = grp.keep if grp.keep in valid_group else valid_group[0]
        survivor_idx = keep - 1

        merged: set[int] = set(getattr(candidates[survivor_idx], "source_sentences", []) or [])
        for i in valid_group:
            merged.update(getattr(candidates[i - 1], "source_sentences", []) or [])
            if i != keep:
                keep_flags[i - 1] = False
        merged_sources[survivor_idx] = sorted(merged)
        keep_flags[survivor_idx] = True

    survivors: list[BaseModel] = []
    for i, c in enumerate(candidates):
        if not keep_flags[i]:
            continue
        if i in merged_sources:
            c = c.model_copy(update={"source_sentences": merged_sources[i]})
        survivors.append(c)
    return survivors


def _note_cache_key(note: PreprocessedNote, model: str) -> str:
    h = hashlib.sha256()
    h.update(note.original_text.encode("utf-8"))
    h.update(b"\x00")
    h.update(model.encode("utf-8"))
    h.update(b"\x00")
    h.update(PROMPT_VERSION.encode("utf-8"))
    return h.hexdigest()


async def extract_candidates(
    note: PreprocessedNote,
    client: AsyncOpenAI,
    *,
    model: str,
    cache: JsonCache | None = None,
) -> StageTwoOutput:
    if cache is not None:
        cached = cache.get(_note_cache_key(note, model))
        if cached is not None:
            try:
                return StageTwoOutput.from_json(cached)
            except (ValidationError, KeyError) as exc:
                log.warning("stale cache entry for %s: %s", note.document_id, exc)

    scan = await scan_note(note, client, model)

    sentences_by_number = {s.number: s for s in note.sentences}
    all_numbers = set(sentences_by_number.keys())

    groups_by_type: dict[str, list[list[int]]] = {
        "Condition": [[n] for n in scan.condition],
        "Observation": [[n] for n in scan.observation],
        "AllergyIntolerance": [[n] for n in scan.allergy_intolerance],
        "FamilyMemberHistory": [[n] for n in scan.family_member_history],
        "Procedure": [list(g) for g in scan.procedure],
        "MedicationRequest": [list(g) for g in scan.medication_request],
    }

    parse_tasks: list[tuple[str, asyncio.Task]] = []
    for rtype, groups in groups_by_type.items():
        for group in groups:
            valid_group = [n for n in group if n in all_numbers]
            if not valid_group:
                continue
            snippet = _build_snippet(valid_group, sentences_by_number)
            allowed = set(valid_group)
            parse_tasks.append((
                rtype,
                asyncio.create_task(parse_group(
                    rtype, snippet, scan.note_context, client, model, allowed,
                    document_id=note.document_id,
                )),
            ))

    parsed_by_type: dict[str, list[BaseModel]] = {t: [] for t in RESOURCE_TYPES}
    for rtype, task in parse_tasks:
        items = await task
        parsed_by_type[rtype].extend(items)

    clean_tasks = {
        rtype: asyncio.create_task(clean_candidates(
            rtype, items, client, model, document_id=note.document_id,
        ))
        for rtype, items in parsed_by_type.items()
        if items
    }
    cleaned_by_type: dict[str, list[BaseModel]] = {}
    for rtype, task in clean_tasks.items():
        cleaned_by_type[rtype] = await task

    output = StageTwoOutput(
        document_id=note.document_id,
        note_context=scan.note_context,
        candidates=cleaned_by_type,
        raw_scan=scan,
        encounter_id=note.encounter_id,
    )

    if cache is not None:
        cache.put(_note_cache_key(note, model), output.to_json())

    return output


async def extract_candidates_batch(
    notes: list[PreprocessedNote],
    client: AsyncOpenAI,
    *,
    model: str,
    cache: JsonCache | None = None,
    max_concurrent: int = 50,
) -> list[StageTwoOutput]:
    tasks = [
        extract_candidates(n, client, model=model, cache=cache)
        for n in notes
    ]
    return await asyncio.gather(*tasks)


# ---------------------------------------------------------------------------
# Stage 3 — cross-note dedupe
# ---------------------------------------------------------------------------

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


def _build_tagged_items(stage2_outputs: list[StageTwoOutput]) -> list[_TaggedItem]:
    tagged: list[_TaggedItem] = []
    for s2 in stage2_outputs:
        enc_key = _derive_encounter_key(s2)
        for rtype, items in s2.candidates.items():
            for item in items:
                name = _get_item_name(rtype, item)
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
