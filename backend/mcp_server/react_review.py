"""React review app for the Prompt Opinion host (FastMCP v3, standard MCP Apps).

PO's iframe bridge speaks the standard MCP-Apps postMessage protocol (verified:
its renderer negotiates protocolVersion 2026-01-26 with ui/initialize +
callServerTool, identical to @modelcontextprotocol/ext-apps). So our React app
connects once its JS executes. PO's CSP blocks inline JS, so the ui:// shell is a
bare <div id=root> that loads review.js/review.css over an absolute URL served by
this server's own HTTP routes.

Tools: ReviewChart (model-visible, seeds the patient header) plus app-only
RunExtraction / AcceptAugmentation / RejectAugmentation. All stateless; no PHI
persisted (see services.proposals).
"""
from __future__ import annotations

from pathlib import Path

from fastmcp import FastMCP
from fastmcp.apps.config import AppConfig, ResourceCSP, app_config_to_meta_dict
from fastmcp.resources.types import TextResource
from fastmcp.tools import Tool
from fastmcp.utilities.mime import UI_MIME_TYPE
from starlette.requests import Request
from starlette.responses import Response

from config import settings
from context.prefab_ctx import (
    prefab_fhir_client,
    prefab_patient_id,
    prefab_reviewer,
    prefab_tenant,
)
from fhir.client import FhirClient
from services import proposals as svc

RESOURCE_URI = "ui://anamnesis/review.html"
_ASSETS_DIR = Path(__file__).parent / "ui" / "assets"
_BASE = settings.app_assets_base_url.rstrip("/")

_SHELL = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <style>
      html, body {{ height: 100%; margin: 0; }}
      #root {{ min-height: 520px; height: 100%; }}
    </style>
    <link rel="stylesheet" href="{_BASE}/app/review.css" />
  </head>
  <body>
    <div id="root"></div>
    <script type="module" crossorigin src="{_BASE}/app/review.js"></script>
  </body>
</html>"""

_MIME = {
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
}


async def review_chart() -> dict:
    """Open the interactive chart-review workspace and seed the patient header."""
    from context.debug_token import capture
    capture("ReviewChart")
    patient_id = prefab_patient_id()
    if not patient_id:
        raise ValueError("No patient in FHIR context")
    name, birth_date, sex, mrn = None, None, None, None
    fhir = prefab_fhir_client()
    if fhir:
        patient = await fhir.read(f"Patient/{patient_id}")
        if patient:
            np = (patient.get("name") or [{}])[0]
            name = f"{' '.join(np.get('given') or [])} {np.get('family') or ''}".strip() or None
            birth_date = patient.get("birthDate")
            sex = patient.get("gender")
            for ident in patient.get("identifier") or []:
                text = (ident.get("type") or {}).get("text", "")
                code = next((c.get("code") for c in (ident.get("type") or {}).get("coding") or []), "")
                if code == "MR" or "medical record" in text.lower():
                    mrn = ident.get("value")
                    break
            if not mrn and patient.get("identifier"):
                mrn = patient["identifier"][0].get("value")
    return {"patient_id": patient_id, "patient_name": name, "birth_date": birth_date, "sex": sex, "mrn": mrn}


_STAGES = [
    "guardrail", "stage1_preprocess", "stage2_extract", "stage3_merge",
    "stage4_code", "stage5_reconcile", "stage6_assemble",
]


def _stage_detail(stage: str, d: dict) -> str:
    if stage == "guardrail":
        return f"{d.get('documents_accepted', 0)} documents accepted"
    if stage == "stage1_preprocess":
        return f"{d.get('sentences', 0)} sentences"
    if stage == "stage2_extract":
        return f"{d.get('candidates', 0)} candidates"
    if stage == "stage3_merge":
        return f"{d.get('candidates', 0)} merged"
    if stage == "stage4_code":
        return f"{d.get('coded', 0)} coded"
    if stage == "stage5_reconcile":
        parts = [f"{v} {k}" for k, v in d.items() if isinstance(v, int) and v > 0]
        return ", ".join(parts) or "done"
    if stage == "stage6_assemble":
        return f"{d.get('proposals', 0)} proposals"
    return ""


async def run_extraction() -> dict:
    """App-only: run the augmentation pipeline; return proposals + source notes."""
    from fastmcp.server.dependencies import get_context

    from context.debug_token import capture
    capture("RunExtraction")
    patient_id = prefab_patient_id()
    if not patient_id:
        raise ValueError("No patient in FHIR context")

    try:
        ctx = get_context()
    except Exception:
        ctx = None

    async def progress_cb(stage: str, detail: dict | None = None) -> None:
        if ctx is None:
            return
        try:
            idx = _STAGES.index(stage) + (1 if detail else 0)
        except ValueError:
            idx = 0
        # message = "stage" while running, "stage\x1fdetail-text" on completion.
        message = f"{stage}\x1f{_stage_detail(stage, detail)}" if detail else stage
        await ctx.report_progress(progress=idx, total=len(_STAGES), message=message)

    return await svc.run_extraction_ephemeral(
        patient_id,
        fhir_client=prefab_fhir_client(),
        tenant_key=prefab_tenant(),
        triggered_by="mcp:react",
        progress_cb=progress_cb,
    )


async def accept_augmentation(
    run_id: str,
    proposal_id: str,
    resource: dict | None = None,
    citations: list[dict] | None = None,
    classification: str = "NEW",
    supersedes: list[str] | None = None,
) -> dict:
    """App-only: accept a proposal and write it to FHIR with Provenance.

    The app supplies the full proposal payload (resource/citations/classification/
    supersedes) so the write succeeds even when this call lands on a worker that
    never held the run in its in-process cache. Pass an edited `resource` to write
    a clinician-revised version.
    """
    return await svc.accept_augmentation(
        fhir_client=prefab_fhir_client(),
        reviewer=prefab_reviewer(),
        patient_id=prefab_patient_id(),
        run_id=run_id,
        proposal_id=proposal_id,
        resource=resource,
        citations=citations,
        classification=classification,
        supersedes=supersedes,
    )


async def reject_augmentation(
    run_id: str, proposal_id: str, resource_type: str = "", reason: str = "",
) -> dict:
    """App-only: record a non-PHI reject decision."""
    reviewer = prefab_reviewer()
    await svc.record_decision(
        action="reject", run_id=run_id, resource_type=resource_type or None,
        reviewer=reviewer.display if reviewer else None, reason=reason or None,
    )
    return {"id": proposal_id, "status": "rejected"}


_TERMINOLOGY_SYSTEMS = ("snomed", "rxnorm", "loinc", "icd10")


async def search_terminology(query: str, system: str, top_k: int = 10) -> dict:
    """App-only: search a terminology (snomed/rxnorm/loinc/icd10) for codes."""
    from config import settings
    from core.retrieval import ApiRetriever, FaissRetriever

    norm = system.lower().strip()
    if norm not in _TERMINOLOGY_SYSTEMS:
        raise ValueError(f"system must be one of {_TERMINOLOGY_SYSTEMS}")
    if not query or not query.strip():
        return {"system": norm, "results": []}

    retriever = FaissRetriever() if settings.coding_retriever == "faiss" else ApiRetriever()
    try:
        results = await retriever.search(query.strip(), norm, max(1, min(top_k, 25)))
    finally:
        client = getattr(retriever, "_client", None)
        if client is not None:
            await client.aclose()

    return {
        "system": norm,
        "results": [
            {"system": norm, "code": r.code, "display": r.display, "score": round(r.score, 4), "rank": r.rank}
            for r in results
        ],
    }


def register(mcp: FastMCP) -> None:
    """Register the React review tools, ui:// shell, and asset routes on `mcp`."""

    @mcp.custom_route("/app/{filename:path}", methods=["GET"])
    async def _assets(request: Request) -> Response:
        name = Path(request.path_params["filename"]).name
        path = _ASSETS_DIR / name
        if not path.is_file() or path.parent != _ASSETS_DIR:
            return Response("not found", status_code=404)
        media = _MIME.get(path.suffix, "application/octet-stream")
        return Response(path.read_bytes(), media_type=media, headers={
            "Cache-Control": "no-cache",
            "Access-Control-Allow-Origin": "*",
        })

    mcp.add_tool(Tool.from_function(
        review_chart, name="ReviewChart",
        description="Open the interactive chart-review workspace for the current patient.",
        meta={"ui": app_config_to_meta_dict(
            AppConfig(resource_uri=RESOURCE_URI, visibility=["model"]))},
    ))
    for fn, fname in [
        (run_extraction, "RunExtraction"),
        (accept_augmentation, "AcceptAugmentation"),
        (reject_augmentation, "RejectAugmentation"),
        (search_terminology, "SearchTerminology"),
    ]:
        mcp.add_tool(Tool.from_function(
            fn, name=fname, description=(fn.__doc__ or "").strip(),
            meta={"ui": app_config_to_meta_dict(
                AppConfig(resource_uri=RESOURCE_URI, visibility=["app"]))},
        ))

    csp = ResourceCSP(
        resource_domains=[_BASE],
        connect_domains=[_BASE],
    )
    mcp.add_resource(TextResource(
        uri=RESOURCE_URI, name="Anamnesis Review", mime_type=UI_MIME_TYPE, text=_SHELL,
        meta={"ui": app_config_to_meta_dict(AppConfig(csp=csp))},
    ))
