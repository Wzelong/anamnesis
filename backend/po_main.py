"""Prompt Opinion entrypoint: FastMCP v3 server hosting the review workspace.

Serves the custom React review app as a standard MCP App (default) — the ui://
shell loads externally-hosted JS/CSS, and the app talks to PO's host over the
standard MCP-Apps postMessage bridge. Set ANAMNESIS_UI=prefab to fall back to the
Prefab app. Reuses the same stateless services; no PHI is persisted.

    python po_main.py   # serves http://0.0.0.0:8042/mcp
"""
import os

os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

from types import MethodType

from fastmcp import FastMCP

from db import init_db

_UI = os.environ.get("ANAMNESIS_UI", "react").lower()

_FHIR_CONTEXT_EXTENSION = "ai.promptopinion/fhir-context"
_SCOPES = [
    {"name": "patient/Patient.rs", "required": True},
    {"name": "patient/Condition.rs"},
    {"name": "patient/MedicationStatement.rs"},
    {"name": "patient/MedicationRequest.rs"},
    {"name": "patient/AllergyIntolerance.rs"},
    {"name": "patient/Observation.rs"},
    {"name": "patient/Procedure.rs"},
    {"name": "patient/DocumentReference.rs"},
]


def _add_fhir_context_extension(mcp: FastMCP) -> None:
    original = mcp._mcp_server.get_capabilities

    def get_capabilities(self, notification_options, experimental_capabilities):
        caps = original(notification_options, experimental_capabilities)
        existing = getattr(caps, "extensions", None) or {}
        caps.extensions = {**existing, _FHIR_CONTEXT_EXTENSION: {"scopes": _SCOPES}}
        return caps

    mcp._mcp_server.get_capabilities = MethodType(get_capabilities, mcp._mcp_server)


mcp = FastMCP(name="Anamnesis", instructions="FHIR chart augmentation with human-in-the-loop review.")
_add_fhir_context_extension(mcp)


@mcp.custom_route("/healthz", methods=["GET"])
async def _healthz(request):
    from starlette.responses import JSONResponse
    return JSONResponse({"status": "ok"})

if _UI == "prefab":
    from mcp_server.prefab_review import review_app
    mcp.add_provider(review_app)
else:
    from mcp_server import react_review
    react_review.register(mcp)


def main() -> None:
    import asyncio
    port = int(os.environ.get("PORT") or os.environ.get("PO_PORT") or "8042")
    asyncio.run(init_db())
    print(f"Anamnesis ({_UI}/PO) at http://0.0.0.0:{port}/mcp — Ctrl+C to stop.")
    try:
        mcp.run(transport="http", host="0.0.0.0", port=port)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
