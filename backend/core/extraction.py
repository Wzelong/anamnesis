"""Stage 2: scan -> parse -> clean per note.

Turns a `PreprocessedNote` into candidates per resource type, all with
`source_sentences` traceable to the numbered note. Stage 3 (cross-note merge)
lives in `core/extraction_merge.py` and is re-exported from this module so
existing call sites keep working.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
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
    PROMPT_SCAN,
    PROMPT_VERSION,
    PROMPTS_BY_TYPE,
)
from core.schemas import (
    CleanerResult,
    DatedField,
    ITEM_LIST_MODELS,
    NoteContext,
    RESOURCE_TYPES,
    ScanResult,
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
    """Single OpenAI Responses-API call wrapped in telemetry.

    Used by every LLM-driven stage (extraction, merge, code-select, reconcile
    adjudication). Records latency / token / cost into the active run via
    `telemetry.record_call` and returns `None` on error so callers can decide
    how to recover (most just skip the candidate).
    """
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
    """Run Stage 2 (scan -> parse -> clean) on a single preprocessed note.

    Three sub-phases, all wrapped in `asyncio.gather` for fan-out:
      1. **Scan** — one LLM call routes sentence numbers to resource types.
      2. **Parse** — one LLM call per (resource type, sentence group) emits
         typed candidates with `source_sentences` citations.
      3. **Clean** — one LLM call per resource type discards within-note dupes.

    Output is cached by `(note_hash, model, prompt_version)`. A cache hit
    returns immediately without any LLM call. Stale cache entries are
    silently re-computed.
    """
    if cache is not None:
        cached = cache.get(_note_cache_key(note, model))
        if cached is not None:
            try:
                out = StageTwoOutput.from_json(cached)
                # Cache key is text-only, so a hit may carry a document_id from a
                # prior run of the same note (e.g. demo bundle vs live FHIR).
                # Rebind to the current note so citations resolve.
                out.document_id = note.document_id
                out.encounter_id = note.encounter_id
                return out
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
    """Run `extract_candidates` over many notes concurrently.

    Bounded by `max_concurrent` semaphore to keep the OpenAI client from
    issuing thousands of in-flight requests at once. Order of returned
    `StageTwoOutput` matches the input note order.
    """
    tasks = [
        extract_candidates(n, client, model=model, cache=cache)
        for n in notes
    ]
    return await asyncio.gather(*tasks)


# Re-export Stage 3 entry points so existing call sites
# (`from core.extraction import merge_across_notes`) keep working unchanged.
# Imported at the bottom to avoid circular-import issues — extraction_merge
# depends on `StageTwoOutput` and `parse_structured` defined above.
from core.extraction_merge import StageThreeOutput, merge_across_notes  # noqa: E402, F401

