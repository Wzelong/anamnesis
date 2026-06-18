"""Telemetry: per-call LLM usage + cost, dual-written to DB and JSONL."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.ids import short_id
from core.pricing import estimate_cost

log = logging.getLogger(__name__)

DEFAULT_JSONL_DIR = Path(__file__).resolve().parent.parent / ".cache" / "telemetry"


@dataclass
class RunContext:
    run_id: str
    patient_id: str | None
    triggered_by: str
    started_at: datetime
    jsonl_path: Path
    regional: bool = False
    call_buffer: list[dict] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.call_buffer is None:
            self.call_buffer = []


_current_run: ContextVar[RunContext | None] = ContextVar("anamnesis_run", default=None)


def current_run() -> RunContext | None:
    return _current_run.get()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return uuid.uuid4().hex


def _append_jsonl(path: Path, payload: dict) -> None:
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    except OSError as exc:
        log.warning("telemetry jsonl write failed: %s", exc)


async def start_run(
    *,
    patient_id: str | None,
    triggered_by: str,
    patient_name: str | None = None,
    run_id: str | None = None,
    meta: dict[str, Any] | None = None,
    jsonl_dir: Path | None = None,
    regional: bool = False,
) -> RunContext:
    from db import AsyncSessionLocal, PipelineRun

    directory = jsonl_dir or DEFAULT_JSONL_DIR
    directory.mkdir(parents=True, exist_ok=True)

    rid = run_id or short_id("run")
    run = RunContext(
        run_id=rid,
        patient_id=patient_id,
        triggered_by=triggered_by,
        started_at=_now(),
        jsonl_path=directory / f"{rid}.jsonl",
        regional=regional,
    )

    async with AsyncSessionLocal() as session:
        session.add(PipelineRun(
            id=run.run_id,
            patient_id=run.patient_id,
            patient_name=patient_name,
            triggered_by=run.triggered_by,
            status="running",
            started_at=run.started_at,
            meta_json=json.dumps(meta, default=str) if meta else None,
        ))
        await session.commit()

    _append_jsonl(run.jsonl_path, {
        "event": "run_started",
        "ts": run.started_at.isoformat(),
        "run_id": run.run_id,
        "patient_id": run.patient_id,
        "triggered_by": run.triggered_by,
        "meta": meta,
    })

    _current_run.set(run)
    return run


async def finish_run(status: str = "success", *, error: str | None = None) -> None:
    from sqlalchemy import update

    from db import AsyncSessionLocal, PipelineRun

    run = _current_run.get()
    if run is None:
        return

    now = _now()
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(PipelineRun)
            .where(PipelineRun.id == run.run_id)
            .values(finished_at=now, status=status)
        )
        await session.commit()

    _append_jsonl(run.jsonl_path, {
        "event": "run_finished",
        "ts": now.isoformat(),
        "run_id": run.run_id,
        "status": status,
        "error": error,
    })
    _current_run.set(None)


async def record_call(
    *,
    stage: str,
    call_type: str,
    model: str,
    prompt_version: str,
    started_at: datetime,
    finished_at: datetime,
    usage: dict[str, Any] | None,
    status: str,
    error: str | None,
    document_id: str | None,
) -> None:
    """No-op when no run is active."""
    run = _current_run.get()
    if run is None:
        return

    input_tokens = int((usage or {}).get("input_tokens") or 0)
    output_tokens = int((usage or {}).get("output_tokens") or 0)
    cached_tokens = int(
        ((usage or {}).get("input_tokens_details") or {}).get("cached_tokens") or 0
    )
    reasoning_tokens = int(
        ((usage or {}).get("output_tokens_details") or {}).get("reasoning_tokens") or 0
    )

    usd = estimate_cost(
        model=model,
        input_tokens=input_tokens,
        cached_tokens=cached_tokens,
        output_tokens=output_tokens,
        regional=run.regional,
    )

    latency_ms = int((finished_at - started_at).total_seconds() * 1000)
    call_id = _uuid()

    run.call_buffer.append({
        "id": call_id,
        "run_id": run.run_id,
        "document_id": document_id,
        "stage": stage,
        "call_type": call_type,
        "model": model,
        "prompt_version": prompt_version,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "cached_tokens": cached_tokens,
        "latency_ms": latency_ms,
        "usd_cost": usd,
        "status": status,
        "error": error,
        "started_at": started_at,
        "finished_at": finished_at,
    })

    _append_jsonl(run.jsonl_path, {
        "event": "llm_call",
        "ts": finished_at.isoformat(),
        "run_id": run.run_id,
        "call_id": call_id,
        "stage": stage,
        "call_type": call_type,
        "model": model,
        "prompt_version": prompt_version,
        "document_id": document_id,
        "input_tokens": input_tokens,
        "cached_tokens": cached_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "latency_ms": latency_ms,
        "usd_cost": str(usd),
        "status": status,
        "error": error,
    })


def log_event_sync(event: str, payload: dict[str, Any]) -> None:
    """JSONL-only event (warnings, validator rejects). Safe if no run active."""
    run = _current_run.get()
    if run is None:
        return
    _append_jsonl(run.jsonl_path, {
        "event": event,
        "ts": _now().isoformat(),
        "run_id": run.run_id,
        **payload,
    })


async def log_event(event: str, payload: dict[str, Any]) -> None:
    log_event_sync(event, payload)


