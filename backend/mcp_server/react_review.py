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
    prefab_user_context,
    prefab_verified_user_context,
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
    result = {
        "patient_id": patient_id, "patient_name": name, "birth_date": birth_date,
        "sex": sex, "mrn": mrn, "byok_enabled": bool(settings.config_secret_key),
    }
    uc = prefab_user_context()
    if uc:
        from services import users
        result["user"] = await users.register_session(
            uc.user_key, display_name=uc.display_name, workspace_id=uc.workspace_id, role=uc.role,
        )
    return result


async def get_user_config() -> dict:
    """App-only: the current clinician's persisted framework config.

    Per-user read: requires a PO-signature-verified token so a forged `sub`
    cannot read another clinician's config. Secrets are redacted to presence
    flags ({set, last4}) — plaintext never leaves the server (see AUTH.md).
    """
    from core import byok
    from services import users
    uc = prefab_verified_user_context()
    return {"config": byok.redact(await users.get_config(uc.user_key))}


async def set_user_config(patch: dict) -> dict:
    """App-only: deep-merge a patch into the clinician's persisted config.

    Per-user write: requires a PO-signature-verified token so a forged `sub`
    cannot overwrite another clinician's config. Secret fields are encrypted at
    rest; the response is redacted (see AUTH.md).
    """
    from core import byok
    from services import users
    uc = prefab_verified_user_context()
    return {"config": byok.redact(await users.set_config(uc.user_key, patch))}


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

    from core.effective_profile import resolve_from_config

    uc, key, cfg = await _run_identity()
    return await svc.run_extraction_ephemeral(
        patient_id,
        fhir_client=prefab_fhir_client(),
        tenant_key=prefab_tenant(),
        triggered_by="mcp:react",
        progress_cb=progress_cb,
        gemini_api_key=key,
        user_key=uc.user_key,
        workspace_id=uc.workspace_id,
        effective=resolve_from_config(cfg),
    )


async def _run_identity():
    """Verified clinician + their decrypted BYOK Gemini key. Raises if BYOK is
    unprovisioned, the token is unverified, or no key is stored — the pipeline
    runs on the clinician's key, never a shared one."""
    if not settings.config_secret_key:
        raise ValueError("BYOK is not enabled on this server.")
    uc = prefab_verified_user_context()
    from core import byok
    from services import users
    cfg = byok.unseal(await users.get_config(uc.user_key))
    key = (cfg.get("byok") or {}).get("gemini_api_key")
    if not key:
        raise ValueError("Connect a Gemini API key in Configuration before running augmentation.")
    return uc, key, cfg


async def get_usage() -> dict:
    """App-only: the current clinician's run history + cumulative spend (non-PHI)."""
    from services import usage
    uc = prefab_verified_user_context()
    return {"summary": await usage.summary(uc.user_key), "runs": await usage.list_runs(uc.user_key)}


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
        effective=await _accept_effective(),
    )


async def _accept_effective():
    """Verified clinician's active preset (for the conformance coding-subset gate).
    Defaults when unconfigured/unverified -- enforcement is opt-in, regression-safe."""
    from core.effective_profile import resolve_from_config
    try:
        uc = prefab_verified_user_context()
        from services import users
        return resolve_from_config(await users.get_config(uc.user_key))
    except Exception:
        return resolve_from_config(None)


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


async def _resolve_keys(*, require_umls: bool = False) -> tuple[str | None, str | None]:
    """Verified clinician's BYOK Gemini + UMLS keys; UMLS falls back to the server key.
    Plaintext stays in-process (unsealed here, never returned to the iframe)."""
    from config import settings
    from core import byok
    from services import users

    uc = prefab_verified_user_context()
    cfg = byok.unseal(await users.get_config(uc.user_key))
    bk = cfg.get("byok") or {}
    gemini = bk.get("gemini_api_key")
    umls = bk.get("umls_api_key") or settings.umls_api_key or None
    if require_umls and not umls:
        raise ValueError("A UMLS API key is required to resolve value sets. Add it in Configuration.")
    return gemini, umls


async def resolve_value_set(ref: str) -> dict:
    """App-only: resolve a VSAC OID or ValueSet URL to its expanded code list.

    Authoritative path: the codes come straight from the NLM VSAC FHIR $expand, not
    from the model. Returns {ref, count, codes:[{system,code,display}]}.
    """
    from fhir.terminology import expand_valueset

    _gemini, umls = await _resolve_keys(require_umls=True)
    codes = await expand_valueset((ref or "").strip(), umls)
    return {"ref": (ref or "").strip(), "count": len(codes), "codes": codes}


async def parse_codes_freeform(text: str) -> dict:
    """App-only: AI-parse a freeform/CSV code list, then ground it against VSAC.

    The model extracts codes from messy input; every code is validated against its
    code system so no hallucination enters the preset. Returns {codes, parsed, grounded}.
    """
    from config import settings
    from core.value_set import parse_codes

    gemini, umls = await _resolve_keys(require_umls=True)
    if not gemini:
        raise ValueError("Connect a Gemini API key in Configuration before parsing codes.")
    return await parse_codes(text or "", gemini_key=gemini, umls_key=umls, model=settings.gemini_model_smart)


async def draft_prompt_addon(
    resource_type: str, note: str, ideas: str, current_addon: str = "", lane: str = "extract",
) -> dict:
    """App-only: AI-draft an add-only addon from an example note + intent, for one lane.

    `lane` is "capture" (scan routing / recall) or "extract" (parse shape). The validated
    base prompt is unchanged; the addon layers extra rules on top. The note is used only to
    draft — never persisted. Returns {resource_type, lane, addon}.
    """
    from config import settings
    from core.prompt_tuning import draft_addon
    from core.schemas import RESOURCE_TYPES

    if resource_type not in RESOURCE_TYPES:
        raise ValueError(f"unknown resource type: {resource_type}")
    if lane not in ("capture", "extract"):
        raise ValueError(f"unknown lane: {lane}")
    gemini, _umls = await _resolve_keys()
    if not gemini:
        raise ValueError("Connect a Gemini API key in Configuration before drafting prompts.")
    addon = await draft_addon(
        lane=lane, resource_type=resource_type, note=note or "", ideas=ideas or "",
        current_addon=current_addon or "", gemini_key=gemini, model=settings.gemini_model_smart,
    )
    return {"resource_type": resource_type, "lane": lane, "addon": addon}


async def test_prompt_addon(resource_type: str, note: str, capture: str = "", extract: str = "") -> dict:
    """App-only: run the production extraction (Stage 1->2: scan/parse/clean) on the note
    with the draft capture + extract addons applied, scoped to one resource type.

    Same steps and model as a prod run — only the prompts are replaced and the output is
    narrowed to one type. Returns {resource_type, items}. The note is not persisted.
    """
    from config import settings
    from core.prompt_tuning import test_addon
    from core.schemas import RESOURCE_TYPES

    if resource_type not in RESOURCE_TYPES:
        raise ValueError(f"unknown resource type: {resource_type}")
    gemini, _umls = await _resolve_keys()
    if not gemini:
        raise ValueError("Connect a Gemini API key in Configuration before testing prompts.")
    return await test_addon(
        resource_type=resource_type, note=note or "", capture=capture or "", extract=extract or "",
        gemini_key=gemini, model=settings.gemini_model_fast,
    )


async def get_prompt_bases() -> dict:
    """App-only: the editable base routing rules per resource type, for seeding the Capture
    lane editor. Returns {capture: {resource_type: rules}}. No key required (read-only text).
    """
    from core.extraction import scan_block
    from core.schemas import RESOURCE_TYPES

    return {"capture": {rt: scan_block(rt) for rt in RESOURCE_TYPES}}


async def search_terminology(query: str, system: str, top_k: int = 10) -> dict:
    """App-only: search a terminology (snomed/rxnorm/loinc/icd10) for codes."""
    from core.retrieval import ApiRetriever

    norm = system.lower().strip()
    if norm not in _TERMINOLOGY_SYSTEMS:
        raise ValueError(f"system must be one of {_TERMINOLOGY_SYSTEMS}")
    if not query or not query.strip():
        return {"system": norm, "results": []}

    retriever = ApiRetriever()
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
        (resolve_value_set, "ResolveValueSet"),
        (parse_codes_freeform, "ParseCodes"),
        (draft_prompt_addon, "DraftPromptAddon"),
        (test_prompt_addon, "TestPromptAddon"),
        (get_prompt_bases, "GetPromptBases"),
        (get_user_config, "GetUserConfig"),
        (set_user_config, "SetUserConfig"),
        (get_usage, "GetUsage"),
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
