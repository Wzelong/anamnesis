"""Probe: what does PO's ui:// sandbox actually allow?

Three resources behind one ReviewChart tool-ish setup, but we test by swapping
which HTML the resource serves. Run, point PO at it, see which renders:
  - static  : pure HTML/CSS, no JS  -> if this renders, HTML works; JS is the issue
  - inline  : one inline <script> that writes text -> tests inline-script CSP
  - external: <script src> from jsdelivr -> tests external-domain allowance
"""
import os
from types import MethodType

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

from fastmcp import FastMCP
from fastmcp.apps.config import AppConfig, ResourceCSP, app_config_to_meta_dict
from fastmcp.resources.types import TextResource
from fastmcp.tools import Tool
from fastmcp.utilities.mime import UI_MIME_TYPE

RESOURCE_URI = "ui://anamnesis/probe.html"
_FHIR_EXT = "ai.promptopinion/fhir-context"
_SCOPES = [{"name": "patient/Patient.rs", "required": True}]

# pick via env: PROBE=static|inline|external (default static)
MODE = os.environ.get("PROBE", "static")

_STATIC = """<!doctype html><html><head><meta charset='utf-8'><style>
body{margin:0;font-family:system-ui;background:#0f5132;color:#fff;padding:24px}
.c{background:#fff;color:#111;border-radius:12px;padding:18px;max-width:420px}
mark{background:#fde68a;padding:0 3px;border-radius:3px}</style></head>
<body><div class='c'><h2 style='margin:0 0 8px'>STATIC HTML renders ✓</h2>
<p>No JavaScript. If you see this styled card, plain ui:// HTML works in PO.</p>
<p>Note: ...reports <mark>stable angina pectoris</mark> on metoprolol...</p></div></body></html>"""

_INLINE = """<!doctype html><html><head><meta charset='utf-8'></head>
<body style='font-family:system-ui;padding:24px'>
<div id='o'>INLINE JS did NOT run (blocked)</div>
<script>document.getElementById('o').textContent='INLINE JS ran ✓ '+new Date().toLocaleTimeString();
document.getElementById('o').style.color='green';</script></body></html>"""

_EXTERNAL = """<!doctype html><html><head><meta charset='utf-8'>
<script type='module' crossorigin src='https://cdn.jsdelivr.net/npm/canvas-confetti@1.9.3/dist/confetti.browser.js'></script>
</head><body style='font-family:system-ui;padding:24px'>
<div>EXTERNAL script test — if confetti fires, external CDN JS works ✓</div>
<script>setTimeout(()=>{try{window.confetti&&window.confetti()}catch(e){}},500)</script>
</body></html>"""

_HTML = {"static": _STATIC, "inline": _INLINE, "external": _EXTERNAL}[MODE]

mcp = FastMCP(name=f"Anamnesis Probe[{MODE}]", instructions="ui sandbox probe")
_orig = mcp._mcp_server.get_capabilities
def _caps(self, n, e):
    c = _orig(n, e); ex = getattr(c, "extensions", None) or {}
    c.extensions = {**ex, _FHIR_EXT: {"scopes": _SCOPES}}; return c
mcp._mcp_server.get_capabilities = MethodType(_caps, mcp._mcp_server)


async def review_chart() -> dict:
    """Open the probe."""
    return {"mode": MODE}


csp = ResourceCSP(resource_domains=["https://cdn.jsdelivr.net"],
                  connect_domains=["https://cdn.jsdelivr.net"])
mcp.add_tool(Tool.from_function(
    review_chart, name="ReviewChart", description="Open the sandbox probe.",
    meta={"ui": app_config_to_meta_dict(AppConfig(resource_uri=RESOURCE_URI, visibility=["model"]))},
))
mcp.add_resource(TextResource(
    uri=RESOURCE_URI, name="Probe", mime_type=UI_MIME_TYPE, text=_HTML,
    meta={"ui": app_config_to_meta_dict(AppConfig(csp=csp))},
))


def main() -> None:
    print(f"Probe[{MODE}] at http://0.0.0.0:8042/mcp — Ctrl+C to stop.")
    try:
        mcp.run(transport="http", host="0.0.0.0", port=8042)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
