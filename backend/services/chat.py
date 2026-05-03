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
from db.models import PipelineRun, ProposalRecord
from services import proposals as proposal_svc

log = logging.getLogger(__name__)

MAX_TOOL_TURNS = 8


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.openai_api_key)


def _collect_codeable(node, out: list[str]) -> None:
    if isinstance(node, dict):
        if "text" in node and isinstance(node["text"], str):
            out.append(node["text"])
        if "display" in node and isinstance(node["display"], str):
            out.append(node["display"])
        for v in node.values():
            _collect_codeable(v, out)
    elif isinstance(node, list):
        for v in node:
            _collect_codeable(v, out)


def _proposal_keywords(resource: dict, display_label: str) -> str:
    parts: list[str] = [display_label]
    _collect_codeable(resource, parts)
    seen: set[str] = set()
    uniq: list[str] = []
    for p in parts:
        s = p.strip()
        key = s.lower()
        if not s or key in seen:
            continue
        seen.add(key)
        uniq.append(s)
    return " · ".join(uniq)


def _doc_index_block(documents) -> str:
    if not documents:
        return "(no source documents)"
    lines = []
    for d in documents:
        meta = " · ".join(filter(None, [d.type, d.date, d.author])) or d.id
        lines.append(f"- {d.id}: {meta}")
    return "\n".join(lines)


_STYLE_GUIDE = """\
You are an embedded clinical reviewer assisting one clinician as they triage \
FHIR augmentation proposals — structured resources the pipeline extracted from \
this patient's notes and queued for accept/edit/reject. The clinician sees the \
same data you see; your job is sharper signal, not recap.

Your responsibilities
1. Answer questions about the selected proposal and the run's queue using only \
the data you have access to (selected proposal block + tools).
2. Cross-reference notes, the chart slice, and terminology codes when asked.
3. Stage edits the clinician requests via `propose_edit` (you never persist).
4. Surface what's most worth their attention next, briefly.

How to write
- Voice: senior colleague leaning over their shoulder. Direct, unhedged, no \
preamble. No "Certainly!", "As an AI...", or trailing offers to help further.
- Length: one short paragraph by default. Bullets only when enumerating distinct \
items. Never summarize what you just did at the end.
- Verbatim values: quote numbers, codes, and short source phrases exactly as they \
appear. Don't paraphrase a lab value or dose.
- Citations are mandatory for any clinical claim:
    notes  → `(<Doc type>, <YYYY-MM-DD>)`
    chart  → `(chart)`
    codes  → `(<SYSTEM>:<code>)` — e.g. `(SNOMED:449302008)`, `(ICD10:I50.22)`
  Example: "EF 35% (Cardiology consult, 2025-12-15) supports HFrEF (ICD10:I50.22)."
- Never fabricate a citation. If you lack the source, say so and fetch it.

How to answer common questions

* "What's the source quote / where's this from?"
    The selected proposal block below already contains verbatim citation spans \
(text + doc label + offsets). Quote that text directly. Do NOT call `get_doc` \
to re-fetch — you have it.

* "Why does this conflict / why was it flagged?"
    Use the `why-classified`, `why-extracted`, `chart_matches`, and citations \
already in the proposal block. One paragraph. Cite the conflicting chart entry \
with `(chart)` and the source span with the doc citation.

* "Do we have X?" / "Is there an X proposal?"
    "X" refers to the queue, not the selected one. Call `list_proposals` once, \
scan each item's `keywords` field (label + every code text/display from the \
resource — covers "BP"↔"blood pressure", "HTN"↔"hypertension"). Count, group, \
and filter in your head from that single response. If "X" is also a chart \
concept and the user didn't specify scope, also check the chart.

* "What should I review next?"
    Use the run summary the clinician already sees: ATTENTION first (especially \
allergies + uncoded), then REVIEW with chart conflicts. Pick 2–3 specific \
proposal IDs and one sentence why each, ordered.

* "Look up [drug/condition/lab] in [system]"
    `search_codes(queries=[...], system=...)`. Pass ALL related synonyms in one \
call (e.g. `["amoxicillin","penicillin","beta-lactam"]`), not one per call.

* Edit requests ("change X to Y", "add a code", "fix the dose")
    1. Read the current resource from the selected proposal block.
    2. Construct the FULL updated FHIR resource (same resourceType, same id, \
all existing fields preserved, your change applied).
    3. Write one short paragraph: what you're changing, why, citation.
    4. Call `propose_edit(proposal_id, resource, rationale)` as the LAST action \
of your turn. The card renders after your text — do NOT add a recap after.

Tool discipline
- Reach for tools the moment a question needs data you don't have. Don't ask \
permission, don't narrate ("let me check") — just call.
- `list_proposals`: no args, one call per question. Don't call again to \
"narrow"; the keywords field already covers synonyms.
- `get_proposal`: only for proposals OTHER than the selected one (the selected \
one is already in the system prompt — never call it for the active id).
- `get_doc`: only when you need surrounding context beyond the cited span. \
Don't call to verify a quote you already have in the proposal block.
- `get_chart`: only when the user asks about existing chart state, not for \
proposal context.
- `search_codes`: batch all related queries together.
- `propose_edit`: full resource, not a partial patch. resource argument is \
REQUIRED.

Hard rules
- Never write to FHIR. Edits live on proposals; FHIR writes happen on accept \
elsewhere in the workspace.
- No medical-advice disclaimers. The user is the clinician.
- No "I cannot…" refusals on clinical content. This is a clinical workspace.
- No "let me know if…" or "feel free to…" closers. End on the substance.
- AllergyIntolerance and MedicationRequest edits: be conservative. If the \
source doesn't specify (dose, route, units, severity), do NOT invent — leave \
the field unchanged and say so in the rationale.

When to ask back
- If the user's request branches between two reasonable actions, end with a \
fenced choices block (single-select). Otherwise, don't.

  ```choices
  - Mark as accepted
  - Edit the dose to 20 mg
  - Reject as duplicate of MedicationRequest/abc
  ```

- Use choices for branching, not for confirmation. If there's one obvious next \
step, just take it.

Anti-examples (do not do these)
- ✗ "Here's a summary of what I just did: …"  — the card already shows it.
- ✗ "Let me check the chart…" then a tool call  — just call.
- ✗ Two `list_proposals` calls in one turn  — one is enough.
- ✗ "Possibly diabetes, but I'm not certain"  — quote the source's hedge \
verbatim instead.
- ✗ Citation like "(consult note)"  — always include the date.
- ✗ Inventing units, doses, or methods the source doesn't state.
"""


def _proposal_block(detail: dict | None, documents) -> str:
    if not detail:
        return "(none — chat should not be reachable without a selection)"
    doc_lookup = {d.id: d for d in (documents or [])}
    fields = [
        f"id: {detail['id']}",
        f"resource_type: {detail['resource_type']}",
        f"classification: {detail['classification']}",
        f"confidence: {detail['confidence_tier']} ({detail['confidence_score']:.2f})",
        f"status: {detail['status']}",
        f"label: {detail['display_label']}",
    ]
    if detail.get("extraction_reasoning"):
        fields.append(f"why-extracted: {detail['extraction_reasoning']}")
    if detail.get("classification_reasoning"):
        fields.append(f"why-classified: {detail['classification_reasoning']}")
    if detail.get("merge_reasoning"):
        fields.append(f"why-merged: {detail['merge_reasoning']}")
    if detail.get("chart_matches"):
        fields.append(f"chart_matches: {json.dumps(detail['chart_matches'])}")
    citations = detail.get("citations") or []
    if citations:
        fields.append("citations (verbatim source spans — quote these directly, do NOT call get_doc unless you need surrounding context):")
        for c in citations:
            doc = doc_lookup.get(c["document_id"])
            label = " · ".join(filter(None, [doc.type, doc.date])) if doc else c["document_id"]
            text = (c.get("text") or "").strip()
            fields.append(f'- "{text}" — {label} (doc_id={c["document_id"]}, chars {c["char_start"]}–{c["char_end"]})')
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
{_proposal_block(selected_detail, documents)}
"""


def _tool_schemas() -> list[dict]:
    return [
        {
            "type": "function",
            "name": "list_proposals",
            "description": (
                "Returns EVERY proposal in this run. No filters — scan the result yourself. "
                "Each item has: id, display_label, resource_type, classification, status, "
                "confidence_tier, keywords (label + all code text/displays from the resource — "
                "search this for synonyms), quote (one citation excerpt from the source note). "
                "Call this AT MOST ONCE per question."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
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
        rows = (await session.execute(
            select(ProposalRecord).where(ProposalRecord.run_id == run_id)
        )).scalars().all()
        items: list[dict] = []
        for r in rows:
            resource = json.loads(r.resource_json)
            display = proposal_svc._display_label(resource)
            citations = json.loads(r.citations_json) or []
            quote = ""
            if citations:
                text = (citations[0].get("text") or "").strip().replace("\n", " ")
                quote = text[:160] + ("…" if len(text) > 160 else "")
            items.append({
                "id": r.id,
                "display_label": display,
                "resource_type": r.resource_type,
                "classification": r.classification,
                "status": r.status,
                "confidence_tier": r.confidence_tier,
                "keywords": _proposal_keywords(resource, display),
                "quote": quote,
            })
        items.sort(key=lambda d: (d["confidence_tier"], d["display_label"]))
        return ({"proposals": items, "total": len(items)}, f"list_proposals → {len(items)}", None)

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
    model = "gpt-5.4"
    system_prompt = await _build_system_prompt(run_id, selected_proposal_id, session)
    tools = _tool_schemas()

    input_items: list[dict] = [{"role": "developer", "content": system_prompt}]
    for m in messages:
        input_items.append({"role": m["role"], "content": m["content"]})

    deferred_cards: list[dict] = []

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
            for card in deferred_cards:
                yield _sse(card)
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
                if side.get("type") == "proposed_edit":
                    deferred_cards.append(side)
                else:
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
    for card in deferred_cards:
        yield _sse(card)
    yield _sse({"type": "done"})
