"""Prefab spike: verify Prompt Opinion renders a FastMCP v3 @app.ui() inline.

Standalone, isolated from the main MCP server. Run against the ngrok tunnel and
call ReviewSpike in PO. Confirms: (1) PO renders a PrefabApp, (2) a CallTool
button round-trips to a backend tool, (3) SHARP headers reach the tool.
"""
from fastmcp import FastMCP, FastMCPApp
from fastmcp.server.dependencies import get_http_headers
from prefab_ui.actions import SetState, ShowToast
from prefab_ui.actions.mcp import CallTool
from prefab_ui.app import PrefabApp
from prefab_ui.components import Badge, Button, Card, CardContent, CardHeader, CardTitle, Column, Markdown, Row, Span, Text
from prefab_ui.rx import RESULT

_FHIR_CONTEXT_EXTENSION = "ai.promptopinion/fhir-context"
_SCOPES = [
    {"name": "patient/Patient.rs", "required": True},
    {"name": "patient/Condition.rs"},
]


def _patch_caps(mcp: FastMCP) -> None:
    from types import MethodType
    original = mcp._mcp_server.get_capabilities

    def get_capabilities(self, notification_options, experimental_capabilities):
        caps = original(notification_options, experimental_capabilities)
        existing = getattr(caps, "extensions", None) or {}
        caps.extensions = {**existing, _FHIR_CONTEXT_EXTENSION: {"scopes": _SCOPES}}
        return caps

    mcp._mcp_server.get_capabilities = MethodType(get_capabilities, mcp._mcp_server)


mcp = FastMCP(name="Anamnesis Prefab Spike", instructions="Spike for PO Prefab rendering")
_patch_caps(mcp)

spike_app = FastMCPApp("Review spike")


def _sharp() -> dict:
    h = get_http_headers(include_all=True)
    return {
        "url": h.get("x-fhir-server-url"),
        "token_present": bool(h.get("x-fhir-access-token")),
        "patient_id": h.get("x-patient-id"),
    }


@spike_app.tool("SpikeExtract")
def spike_extract() -> dict:
    """Stand-in for RunExtraction: returns fake proposals + echoes SHARP context."""
    s = _sharp()
    return {
        "sharp_ok": s["token_present"] and bool(s["url"]),
        "patient_id": s["patient_id"] or "(none)",
        "proposals": [
            {"label": "Stable angina pectoris", "tier": "REVIEW",
             "note": "patient reports... **stable angina** on metoprolol..."},
            {"label": "Losartan 50mg", "tier": "ATTENTION",
             "note": "switch to **losartan 50 mg** ... lisinopril discontinued"},
        ],
    }


@spike_app.ui("ReviewSpike")
def review_spike() -> PrefabApp:
    """Render a card with a button that calls SpikeExtract and shows the result."""
    extract = CallTool(
        spike_extract,
        on_success=[
            SetState("ran", True),
            SetState("sharp_ok", RESULT.sharp_ok),
            SetState("patient_id", RESULT.patient_id),
            SetState("proposals", RESULT.proposals),
            ShowToast("Extraction ran", variant="success"),
        ],
        on_error=ShowToast("{{ $error }}", variant="error"),
    )

    with Card(css_class="m-2") as view:
        with CardHeader():
            CardTitle("Anamnesis — Prefab Spike")
        with CardContent():
            with Column(gap=3):
                with Row(gap=2, align="center"):
                    Text("SHARP context:")
                    Badge("{{ sharp_ok ? 'received' : 'pending' }}")
                    Span("patient {{ patient_id }}", css_class="text-sm text-muted-foreground")
                Button("Run extraction", on_click=extract)
                # citation-highlight feasibility check: Markdown + styled Span
                Markdown("**Note reader test** — highlight below should be amber:")
                Span("stable angina pectoris", css_class="bg-amber-200 rounded px-1")

    return PrefabApp(view=view, state={"ran": False, "sharp_ok": False, "patient_id": "?", "proposals": []})


mcp.add_provider(spike_app)


def main() -> None:
    print("Prefab spike at http://0.0.0.0:8042/mcp — Ctrl+C to stop.")
    mcp.run(transport="http", host="0.0.0.0", port=8042)


if __name__ == "__main__":
    main()
