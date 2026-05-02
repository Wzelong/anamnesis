"""Chat service: streams an OpenAI Responses API call with tool dispatch.

The chat is per-run, ephemeral on the client. Each request carries the
sliding window of prior messages and the currently-selected proposal id;
the system prompt is rebuilt server-side from fresh DB state.

SSE event shape (one JSON object per `data:` line):
    {"type": "text",            "delta": "..."}
    {"type": "reasoning",       "summary": "..."}
    {"type": "tool_call_start", "name": "...", "args": {...}, "id": "..."}
    {"type": "tool_call_result","id": "...", "ok": true|false, "summary": "..."}
    {"type": "proposed_edit",   "proposal_id": "...", "patch": {...},
                                 "rationale": "..."}
    {"type": "error",           "message": "..."}
    {"type": "done"}
"""
from __future__ import annotations

import json
import logging
from datetime import timezone
from typing import AsyncIterator

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from core import coding
from db.models import PipelineRun
from services import proposals as proposal_svc

log = logging.getLogger(__name__)

MAX_TOOL_TURNS = 8


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.openai_api_key)


def _doc_index_block(documents) -> str:
    if not documents:
        return "(no source documents)"
    lines = []
    for d in documents:
        meta = " · ".join(filter(None, [d.type, d.date, d.author])) or d.id
        lines.append(f"- {d.id}: {meta}")
    return "\n".join(lines)


_STYLE_GUIDE = """\
You help a clinician triage FHIR augmentation proposals — structured resources \
extracted from clinical notes, queued for accept/reject/edit. The clinician sees \
the same proposal you do; they want sharper signal, not a recap.

Voice
- Talk like a senior colleague leaning over their shoulder. Direct, unhedged, no \
preamble. No "Certainly!", no "As an AI...", no closing offers to help further.
- Default to one short paragraph. Bullets only when listing distinct items.
- Numbers and code values matter — quote them verbatim.

Grounding
- Every clinical claim cites its source inline: `(<Doc type>, <YYYY-MM-DD>)` for \
notes, `(chart)` for existing FHIR, `(<system>:<code>)` for terminology hits. \
Example: "EF 35% (Cardiology consult, 2025-12-15) supports HFrEF (ICD10:I50.22)."
- Never fabricate a citation. If you don't have the source, say "I'd need to \
check the discharge note" and call `get_doc`.
- The selected proposal is included below — answer from it without a tool call.

Tools — use them, don't narrate them
- Reach for tools the moment a question requires data you don't have. Don't ask \
permission. Don't say "let me check"; just check.
- `list_proposals` filters are independent and ALL OPTIONAL. One call answers \
queue-wide questions. Don't carry the selected proposal's resource_type forward \
unless the user explicitly named it.
  - "list all conflicting proposals" → `{classification: "CONFLICTING"}` (one call, no other filters)
  - "what's still pending?" → `{status: "pending"}` (one call)
  - "show all attention items" → `{tier: "ATTENTION"}` (one call)
  - never call it three times to enumerate tier values, and never include filters \
the user didn't ask about.
- The response contains a `run_summary` with totals by tier/status/classification. \
Use it to answer "how many" without further calls.
- Batch lookups: `search_codes` takes a list, use it. Don't loop one query per call.
- `propose_edit` is the ONLY way to modify a proposal. The `resource` argument \
is REQUIRED — pass the FULL updated FHIR resource (not a partial patch). Never \
paste the patch as prose. The user approves on a card.

Hard rules
- Never write to FHIR. Edits live on proposals; FHIR writes happen elsewhere on accept.
- No medical-advice disclaimers. The user is the clinician.
- No "I cannot..." refusals on clinical content. This is a clinical workspace.

Asking the user
- When two reasonable paths exist, end with a fenced choices block — single-select:

  ```choices
  - Mark as accepted
  - Edit the dose
  - Reject as duplicate
  ```

- Don't volunteer a choices block when the answer is obvious. Use it for branching, \
not for confirmation.
"""


def _proposal_block(detail: dict | None) -> str:
    if not detail:
        return "(none — chat should not be reachable without a selection)"
    fields = [
        f"id: {detail['id']}",
        f"resource_type: {detail['resource_type']}",
        f"classification: {detail['classification']}",
        f"confidence: {detail['confidence_tier']} ({detail['confidence_score']:.2f})",
        f"status: {detail['status']}",
        f"label: {detail['display_label']}",
    ]
    if detail.get("classification_reasoning"):
        fields.append(f"why-classified: {detail['classification_reasoning']}")
    if detail.get("merge_reasoning"):
        fields.append(f"why-merged: {detail['merge_reasoning']}")
    if detail.get("chart_matches"):
        fields.append(f"chart_matches: {json.dumps(detail['chart_matches'])}")
    fields.append("resource:")
    fields.append(json.dumps(detail["resource"], indent=2))
    return "\n".join(fields)


async def _build_system_prompt(
    run_id: str,
    selected_proposal_id: str | None,
    session: AsyncSession,
) -> str:
    run = (await session.execute(
        select(PipelineRun).where(PipelineRun.id == run_id)
    )).scalar_one_or_none()
    patient_label = (run.patient_name or run.patient_id) if run else run_id

    source = await proposal_svc.load_run_source(run_id, session)
    documents = source[1] if source else []

    selected_detail = None
    if selected_proposal_id:
        try:
            selected_detail = await proposal_svc.get_proposal(selected_proposal_id, session)
        except ValueError:
            selected_detail = None

    return f"""{_STYLE_GUIDE}
---
Patient: {patient_label}
Run: {run_id}

Source documents in this run (call `get_doc` for full text):
{_doc_index_block(documents)}

Selected proposal (the one the clinician is looking at right now):
{_proposal_block(selected_detail)}
"""


def _tool_schemas() -> list[dict]:
    return [
        {
            "type": "function",
            "name": "list_proposals",
            "description": (
                "Lists proposals in this run. Always returns a `run_summary` with "
                "totals broken down by tier/status/classification/resource_type — "
                "use that to answer 'how many' questions WITHOUT calling again. "
                "All filters are independent and optional; omit any you don't need. "
                "Never enumerate combinations of filter values across multiple calls."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tier": {
                        "type": "string",
                        "enum": ["ATTENTION", "REVIEW", "CONFIDENT"],
                        "description": "Restrict to a single tier. OMIT to include all tiers — that's the right call for any broad question.",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pending", "accepted", "rejected"],
                        "description": "Restrict to one status. OMIT to include all (pending+accepted+rejected).",
                    },
                    "resource_type": {
                        "type": "string",
                        "description": "Exact FHIR resourceType (e.g. 'Condition'). OMIT to include all types.",
                    },
                    "classification": {
                        "type": "string",
                        "enum": ["NEW", "UPDATING", "CONFLICTING"],
                        "description": "Restrict to one classification. OMIT to include all.",
                    },
                },
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "get_proposal",
            "description": (
                "Full detail of a non-active proposal (resource JSON, citations, "
                "reasoning, chart matches). Don't call for the currently-selected "
                "proposal — it's already in the system prompt."
            ),
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "get_chart",
            "description": (
                "Slice of the existing FHIR chart. Default returns conditions, "
                "medications, allergies, observations, procedures, family_history. "
                "Pass resource_types to narrow."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "resource_types": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "conditions", "medications", "allergies", "observations",
                                "procedures", "family_history", "encounters",
                            ],
                        },
                    }
                },
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "get_doc",
            "description": (
                "Full markdown of one source document. The doc index is in the "
                "system prompt — pick the id from there. Use when you need to "
                "verify a quote or look beyond what citations already gave you."
            ),
            "parameters": {
                "type": "object",
                "properties": {"doc_id": {"type": "string"}},
                "required": ["doc_id"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "search_codes",
            "description": (
                "Batched vector search over a clinical terminology. Always pass "
                "all related terms in one call — e.g. for an allergy lookup, send "
                "['amoxicillin', 'penicillin', 'beta-lactam'] together."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "queries": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    "system": {"type": "string", "enum": ["rxnorm", "snomed", "icd10", "loinc"]},
                    "top_k": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
                },
                "required": ["queries", "system"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "propose_edit",
            "description": (
                "Stage an edit on a pending proposal. Pass the FULL updated FHIR "
                "resource (same resourceType, same id) — it replaces the current "
                "resource. Renders as a card the clinician must Apply. Never call "
                "this on accepted/rejected proposals. After calling, do not also "
                "describe the patch in prose — the card shows the diff."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "proposal_id": {"type": "string"},
                    "resource": {
                        "type": "object",
                        "description": "Complete updated FHIR resource. Must include resourceType.",
                        "additionalProperties": True,
                    },
                    "rationale": {
                        "type": "string",
                        "description": "One sentence on why this edit, with citation.",
                    },
                },
                "required": ["proposal_id", "resource", "rationale"],
                "additionalProperties": False,
            },
        },
    ]


async def _dispatch_tool(
    name: str,
    args: dict,
    run_id: str,
    session: AsyncSession,
) -> tuple[dict, str, dict | None]:
    """Run a tool call. Returns (json_payload_for_model, human_summary, side_event_or_none)."""
    if name == "list_proposals":
        all_items = await proposal_svc.list_proposals(session, run_id=run_id)
        summary = {
            "total_in_run": len(all_items),
            "by_tier": {},
            "by_status": {},
            "by_classification": {},
            "by_resource_type": {},
        }
        for p in all_items:
            for src, dst in (
                ("confidence_tier", "by_tier"),
                ("status", "by_status"),
                ("classification", "by_classification"),
                ("resource_type", "by_resource_type"),
            ):
                key = p.get(src)
                if key:
                    summary[dst][key] = summary[dst].get(key, 0) + 1

        items = all_items
        for k in ("tier", "status", "resource_type", "classification"):
            v = args.get(k)
            if v is None or v == "":
                continue
            field = "confidence_tier" if k == "tier" else k
            items = [p for p in items if p.get(field) == v]
        slim = [
            {k: p[k] for k in ("id", "display_label", "confidence_tier", "classification", "status", "resource_type")}
            for p in items
        ]
        return (
            {"proposals": slim, "matched": len(slim), "run_summary": summary},
            f"list_proposals → {len(slim)} of {len(all_items)}",
            None,
        )

    if name == "get_proposal":
        try:
            detail = await proposal_svc.get_proposal(args["id"], session)
            return detail, f"get_proposal {args['id']}", None
        except ValueError as e:
            return {"error": str(e)}, f"get_proposal failed: {e}", None

    if name == "get_chart":
        source = await proposal_svc.load_run_source(run_id, session)
        if source is None:
            return {"error": "run not found"}, "get_chart failed", None
        ctx, _ = source
        wanted = args.get("resource_types") or [
            "conditions", "medications", "allergies", "observations", "procedures", "family_history",
        ]
        result = {k: getattr(ctx, k) for k in wanted if hasattr(ctx, k)}
        return result, f"get_chart {','.join(wanted)}", None

    if name == "get_doc":
        source = await proposal_svc.load_run_source(run_id, session)
        if source is None:
            return {"error": "run not found"}, "get_doc failed", None
        _, docs = source
        for d in docs:
            if d.id == args["doc_id"]:
                return {
                    "id": d.id, "type": d.type, "date": d.date,
                    "author": d.author, "text": d.text,
                }, f"get_doc {d.type or d.id}", None
        return {"error": "doc not found"}, "get_doc not found", None

    if name == "search_codes":
        sys_ = args["system"]
        top_k = int(args.get("top_k") or 5)
        out: dict[str, list[dict]] = {}
        for q in args["queries"]:
            try:
                hits = coding.search_code(q, sys_, top_k=top_k)
                out[q] = [{"code": h.code, "display": h.display, "score": round(h.score, 3)} for h in hits]
            except Exception as exc:
                out[q] = [{"error": str(exc)}]
        return out, f"search_codes {sys_} ({len(args['queries'])})", None

    if name == "propose_edit":
        proposal_id = args.get("proposal_id")
        resource = args.get("resource")
        if not proposal_id:
            return {"error": "missing required argument 'proposal_id'"}, "propose_edit: missing proposal_id", None
        if not isinstance(resource, dict) or not resource:
            return (
                {"error": (
                    "missing required argument 'resource'. Pass the FULL updated FHIR "
                    "resource as an object (with resourceType and all fields). The patch "
                    "replaces the current resource — partial diffs are not supported."
                )},
                "propose_edit: missing resource",
                None,
            )
        side = {
            "type": "proposed_edit",
            "proposal_id": proposal_id,
            "resource": resource,
            "rationale": args.get("rationale", ""),
        }
        return {"staged": True}, "propose_edit (awaiting clinician)", side

    return {"error": f"unknown tool {name}"}, f"unknown tool {name}", None


def _sse(event: dict) -> bytes:
    return f"data: {json.dumps(event)}\n\n".encode("utf-8")


async def stream_chat(
    run_id: str,
    messages: list[dict],
    selected_proposal_id: str | None,
    session: AsyncSession,
) -> AsyncIterator[bytes]:
    client = _client()
    model = settings.openai_model_fast
    system_prompt = await _build_system_prompt(run_id, selected_proposal_id, session)
    tools = _tool_schemas()

    input_items: list[dict] = [{"role": "developer", "content": system_prompt}]
    for m in messages:
        input_items.append({"role": m["role"], "content": m["content"]})

    for _turn in range(MAX_TOOL_TURNS):
        try:
            stream = await client.responses.create(
                model=model,
                reasoning={"effort": "low", "summary": "auto"},
                input=input_items,
                tools=tools,
                stream=True,
            )
        except Exception as exc:
            log.exception("chat stream failed to start")
            yield _sse({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
            yield _sse({"type": "done"})
            return

        function_calls: list[dict] = []
        emitted_text = False
        async for event in stream:
            etype = getattr(event, "type", "")
            if etype == "response.output_text.delta":
                emitted_text = True
                yield _sse({"type": "text", "delta": event.delta})
            elif etype == "response.reasoning_summary_text.delta":
                yield _sse({"type": "reasoning", "summary": event.delta})
            elif etype == "response.output_item.done":
                item = event.item
                if getattr(item, "type", None) == "function_call":
                    function_calls.append({
                        "call_id": item.call_id,
                        "name": item.name,
                        "arguments": item.arguments,
                        "id": getattr(item, "id", None),
                    })
            elif etype == "response.error":
                yield _sse({"type": "error", "message": str(getattr(event, "error", "stream error"))})

        if not function_calls:
            if not emitted_text:
                yield _sse({"type": "error", "message": "empty response"})
            yield _sse({"type": "done"})
            return

        for fc in function_calls:
            try:
                args = json.loads(fc["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            yield _sse({
                "type": "tool_call_start",
                "id": fc["call_id"],
                "name": fc["name"],
                "args": args,
            })
            try:
                result, summary, side = await _dispatch_tool(fc["name"], args, run_id, session)
                ok = "error" not in result
            except Exception as exc:
                log.exception("tool %s crashed", fc["name"])
                result = {"error": f"{type(exc).__name__}: {exc}"}
                summary = f"{fc['name']} crashed"
                side = None
                ok = False

            yield _sse({
                "type": "tool_call_result",
                "id": fc["call_id"],
                "ok": ok,
                "summary": summary,
            })
            if side:
                yield _sse(side)

            input_items.append({
                "type": "function_call",
                "call_id": fc["call_id"],
                "name": fc["name"],
                "arguments": fc["arguments"],
            })
            input_items.append({
                "type": "function_call_output",
                "call_id": fc["call_id"],
                "output": json.dumps(result),
            })

    yield _sse({"type": "error", "message": "tool turn limit reached"})
    yield _sse({"type": "done"})
