"""Path C test: standard ui:// MCP App (our React bundle) on FastMCP v3.

Registers ReviewChart as a UI tool pointing at a TextResource that serves the
existing mcp-app/ React single-file build. If PO renders this, our React app
(NoteReader and all) works as-is — no Prefab.

    python test_pathC.py   # http://0.0.0.0:8042/mcp
"""
import os
from pathlib import Path
from types import MethodType

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

from fastmcp import FastMCP
from fastmcp.apps.config import AppConfig, ResourceCSP, app_config_to_meta_dict
from fastmcp.resources.types import TextResource
from fastmcp.tools import Tool
from fastmcp.utilities.mime import UI_MIME_TYPE

from context.prefab_ctx import prefab_fhir_client, prefab_patient_id, prefab_tenant
from services import proposals as svc

RESOURCE_URI = "ui://anamnesis/review.html"
_HTML = Path(__file__).parent / "mcp_server" / "ui" / "review.html"

_FHIR_EXT = "ai.promptopinion/fhir-context"
_SCOPES = [{"name": "patient/Patient.rs", "required": True}, {"name": "patient/Condition.rs"},
           {"name": "patient/DocumentReference.rs"}]


def _patch_caps(mcp: FastMCP) -> None:
    original = mcp._mcp_server.get_capabilities

    def get_capabilities(self, notification_options, experimental_capabilities):
        caps = original(notification_options, experimental_capabilities)
        existing = getattr(caps, "extensions", None) or {}
        caps.extensions = {**existing, _FHIR_EXT: {"scopes": _SCOPES}}
        return caps

    mcp._mcp_server.get_capabilities = MethodType(get_capabilities, mcp._mcp_server)


mcp = FastMCP(name="Anamnesis PathC", instructions="Standard MCP App test")
_patch_caps(mcp)


async def review_chart() -> dict:
    """Open the review workspace (renders the React app)."""
    pid = prefab_patient_id()
    return {"patient_id": pid or "(none)"}


async def run_extraction() -> dict:
    """App-only: run the pipeline, return proposals + notes."""
    pid = prefab_patient_id()
    if not pid:
        raise ValueError("No patient in FHIR context")
    return await svc.run_extraction_ephemeral(
        pid, fhir_client=prefab_fhir_client(), tenant_key=prefab_tenant(), triggered_by="mcp:pathC",
    )


csp = ResourceCSP(connect_domains=["*"])
mcp.add_tool(Tool.from_function(
    review_chart, name="ReviewChart",
    description="Open the interactive chart review workspace.",
    meta={"ui": app_config_to_meta_dict(AppConfig(resource_uri=RESOURCE_URI, visibility=["model"]))},
))
mcp.add_tool(Tool.from_function(
    run_extraction, name="RunExtraction",
    description="App-only: run extraction.",
    meta={"ui": app_config_to_meta_dict(AppConfig(resource_uri=RESOURCE_URI, visibility=["app"]))},
))
mcp.add_resource(TextResource(
    uri=RESOURCE_URI, name="Anamnesis Review", mime_type=UI_MIME_TYPE,
    text=_HTML.read_text(encoding="utf-8"),
    meta={"ui": app_config_to_meta_dict(AppConfig(csp=csp))},
))


def main() -> None:
    import asyncio
    from db import init_db
    asyncio.run(init_db())
    print("Path C (standard MCP App) at http://0.0.0.0:8042/mcp — Ctrl+C to stop.")
    try:
        mcp.run(transport="http", host="0.0.0.0", port=8042)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
