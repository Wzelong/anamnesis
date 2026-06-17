"""Prompt Opinion review workspace, built with Prefab UI on FastMCP v3.

Mirrors the frontend review surface: a proposal queue, a detail view with the
proposed resource / conflict / confidence, and a source-note reader with the
cited spans highlighted. Driven entirely by CallTool into the stateless
pipeline — no PHI is persisted.

The note reader highlights citations by slicing the note text server-side into
plain + highlighted segments (offsets are exact here, so this is simpler and
more robust than client-side offset mapping).
"""
from __future__ import annotations

from fastmcp import FastMCPApp
from prefab_ui.actions import SetState, ShowToast, ToggleState
from prefab_ui.actions.mcp import CallTool
from prefab_ui.app import PrefabApp
from prefab_ui.components import (
    Alert, AlertDescription, AlertTitle, Badge, Button, Card, CardContent,
    CardHeader, CardTitle, Column, Div, Elif, Else, ForEach, Heading, If,
    Loader, Markdown, Metric, Row, Separator, Span, Text,
)
from prefab_ui.rx import RESULT

from context.prefab_ctx import prefab_fhir_client, prefab_patient_id, prefab_reviewer, prefab_tenant
from mcp_server.prefab_theme import anamnesis_theme
from services import proposals as svc

review_app = FastMCPApp("Anamnesis chart review")

_TIER_BADGE = {"ATTENTION": "destructive", "REVIEW": "warning", "CONFIDENT": "success"}


# --- backend tools (app-only: hidden from the model, called via CallTool) -----

@review_app.tool
async def run_extraction() -> dict:
    """Run the augmentation pipeline; return proposals + source notes. No PHI persisted."""
    patient_id = prefab_patient_id()
    if not patient_id:
        raise ValueError("No patient in FHIR context")
    result = await svc.run_extraction_ephemeral(
        patient_id,
        fhir_client=prefab_fhir_client(),
        tenant_key=prefab_tenant(),
        triggered_by="mcp:prefab",
    )
    return _view_state(result)


@review_app.tool
async def accept_augmentation(run_id: str, proposal_id: str) -> dict:
    """Accept a proposal and write to FHIR with Provenance."""
    result = await svc.accept_augmentation(
        fhir_client=prefab_fhir_client(),
        reviewer=prefab_reviewer(),
        patient_id=prefab_patient_id(),
        run_id=run_id,
        proposal_id=proposal_id,
    )
    wr = result.get("write_result")
    return {"id": result["id"], "written": bool(wr),
            "resource_ref": (wr or {}).get("resource_ref")}


@review_app.tool
async def reject_augmentation(run_id: str, proposal_id: str, resource_type: str = "") -> dict:
    """Record a non-PHI reject decision."""
    await svc.record_decision(
        action="reject", run_id=run_id, resource_type=resource_type or None,
        reviewer=(prefab_reviewer().display if prefab_reviewer() else None),
    )
    return {"id": proposal_id}


# --- view-state shaping (server-side; includes pre-sliced note segments) ------

def _view_state(result: dict) -> dict:
    docs = {d["id"]: d for d in result["documents"]}
    proposals = []
    for p in result["proposals"]:
        cites = p.get("citations", [])
        primary = cites[0] if cites else None
        proposals.append({
            "id": p["id"],
            "run_id": p["run_id"],
            "resource_type": p["resource_type"],
            "label": p["display_label"],
            "tier": p["confidence_tier"],
            "tier_variant": _TIER_BADGE.get(p["confidence_tier"], "secondary"),
            "classification": p["classification"],
            "confidence_label": f"{round(p['confidence_score'] * 100)}%",
            "conflicting": "CONFLICTING" in (p.get("flags") or []),
            "reasoning": p.get("extraction_reasoning") or "",
            "citation_text": (primary or {}).get("text", ""),
            "segments": _note_segments(docs, cites),
            "decided": "",
        })
    return {
        "ran": True,
        "patient_id": result["patient_id"],
        "proposals": proposals,
        "total": len(proposals),
        "current": proposals[0] if proposals else None,
    }


def _note_segments(docs: dict, citations: list[dict]) -> list[dict]:
    """Slice the primary cited note into ordered plain/highlight segments."""
    if not citations:
        return []
    doc_id = citations[0]["document_id"]
    doc = docs.get(doc_id)
    if not doc or not doc.get("text"):
        return [{"text": c["text"], "hl": True} for c in citations]
    text = doc["text"]
    spans = sorted(
        ((c["char_start"], c["char_end"]) for c in citations if c["document_id"] == doc_id),
        key=lambda s: s[0],
    )
    merged: list[list[int]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    segments, cursor = [], 0
    for s, e in merged:
        if s > cursor:
            segments.append({"text": text[cursor:s], "hl": False})
        segments.append({"text": text[s:e], "hl": True})
        cursor = e
    if cursor < len(text):
        segments.append({"text": text[cursor:], "hl": False})
    return segments


# --- UI ----------------------------------------------------------------------

@review_app.ui("ReviewChart")
def review_chart() -> PrefabApp:
    run = CallTool(
        run_extraction,
        on_success=[
            SetState("ran", RESULT.ran),
            SetState("patient_id", RESULT.patient_id),
            SetState("proposals", RESULT.proposals),
            SetState("total", RESULT.total),
            SetState("current", RESULT.current),
            SetState("loading", False),
        ],
        on_error=[SetState("loading", False), ShowToast("{{ $error }}", variant="error")],
    )

    with Column(gap=0, css_class="h-full", on_mount=[SetState("loading", True), run]) as view:
        # header
        with Row(gap=2, align="center", css_class="anamnesis-header px-4 py-2.5 border-b shrink-0"):
            Heading("Chart review", css_class="text-sm font-semibold m-0")
            Span("{{ total }} proposals", css_class="ml-auto text-xs text-muted-foreground whitespace-nowrap")

        # loading state — streamed stages
        with If("loading"):
            with Column(gap=3, align="center", css_class="flex-1 justify-center p-10"):
                Loader()
                Text("Extracting facts and reconciling against the chart…",
                     css_class="text-sm text-muted-foreground")

        with Elif("total == 0"):
            with Column(gap=2, align="center", css_class="flex-1 justify-center p-10"):
                Text("No augmentations found.", css_class="text-sm text-muted-foreground")

        with Else():
            with Row(gap=0, css_class="flex-1 min-h-0"):
                _queue_panel()
                _detail_panel()

    return PrefabApp(
        view=view,
        theme=anamnesis_theme(),
        state={"loading": False, "ran": False, "patient_id": "",
               "proposals": [], "total": 0, "current": None},
    )


def _queue_panel() -> None:
    with Column(gap=0, css_class="w-64 border-r overflow-y-auto shrink-0"):
        with ForEach("proposals") as (_, p):
            with Div(
                css_class="anamnesis-queue-item px-3 py-2.5 border-b cursor-pointer",
                on_click=SetState("current", p),
            ):
                with Row(gap=2, align="center"):
                    Span(p.resource_type, css_class="text-[11px] text-muted-foreground")
                    with If("$item.conflicting"):
                        Badge("conflict", variant="destructive", css_class="text-[10px]")
                Text(p.label, css_class="text-sm font-medium truncate")


def _detail_panel() -> None:
    with Column(gap=0, css_class="flex-1 min-w-0"):
        with If("!current"):
            with Column(gap=2, align="center", css_class="flex-1 justify-center p-10"):
                Text("Select a proposal to review.", css_class="text-sm text-muted-foreground")
        with Else():
            # header
            with Column(gap=2, css_class="px-4 py-3 border-b"):
                with Row(gap=1.5, align="center", css_class="flex-wrap"):
                    Badge("{{ current.tier }}", variant="{{ current.tier_variant }}")
                    Badge("{{ current.classification }}", variant="secondary")
                    Badge("{{ current.confidence_label }}", variant="outline")
                    with If("current.conflicting"):
                        Badge("conflict", variant="destructive")
                Span("{{ current.resource_type }}", css_class="text-[11px] uppercase tracking-wide text-muted-foreground")
                Heading("{{ current.label }}", css_class="text-base font-semibold")

            # body
            with Column(gap=4, css_class="flex-1 min-h-0 overflow-y-auto px-4 py-3"):
                with If("current.conflicting"):
                    with Alert(variant="warning"):
                        AlertTitle("Conflicts with the existing chart")
                        AlertDescription("Accepting this will supersede the conflicting record.")
                with If("current.reasoning"):
                    Text("{{ current.reasoning }}", css_class="text-sm text-muted-foreground leading-relaxed")
                Separator()
                Span("Source note", css_class="text-[11px] uppercase tracking-wide text-muted-foreground")
                with Div(css_class="text-sm leading-relaxed whitespace-pre-wrap"):
                    with ForEach("current.segments") as (_si, seg):
                        with If("$item.hl"):
                            Span(seg.text, css_class="anamnesis-hl")
                        with Else():
                            Span(seg.text)

            # actions
            with Row(gap=2, css_class="border-t px-4 py-3"):
                Button(
                    "Reject", variant="outline", css_class="flex-1",
                    on_click=CallTool(
                        reject_augmentation,
                        arguments={"run_id": "{{ current.run_id }}", "proposal_id": "{{ current.id }}",
                                   "resource_type": "{{ current.resource_type }}"},
                        on_success=ShowToast("Rejected", variant="info"),
                        on_error=ShowToast("{{ $error }}", variant="error"),
                    ),
                )
                Button(
                    "Accept & write", variant="default", css_class="flex-1",
                    on_click=CallTool(
                        accept_augmentation,
                        arguments={"run_id": "{{ current.run_id }}", "proposal_id": "{{ current.id }}"},
                        on_success=ShowToast("Written to chart with Provenance", variant="success"),
                        on_error=ShowToast("{{ $error }}", variant="error"),
                    ),
                )
