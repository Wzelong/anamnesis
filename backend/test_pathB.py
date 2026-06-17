"""Path B test: Prefab Embed(html=...) island — arbitrary HTML/JS in a sandbox.

Tests whether PO renders a Prefab app whose body is a custom HTML/JS iframe.
If it renders, we can put any fancy custom UI inside Embed (charts, custom
layouts) while keeping a thin Prefab shell. Note: Embed HTML is sandboxed and
has no MCP bridge, so interactivity-with-backend differs from Path C.

    python test_pathB.py   # http://0.0.0.0:8042/mcp
"""
import os
from types import MethodType

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

from fastmcp import FastMCP, FastMCPApp
from prefab_ui.app import PrefabApp
from prefab_ui.components import Column, Embed

_FHIR_EXT = "ai.promptopinion/fhir-context"
_SCOPES = [{"name": "patient/Patient.rs", "required": True}]

_CUSTOM_HTML = """
<!doctype html><html><head><meta charset='utf-8'>
<style>
  body{margin:0;font-family:system-ui,sans-serif;background:#fff;color:#18181b}
  .wrap{padding:20px}
  .hero{background:linear-gradient(135deg,#0f5132,#198754);color:#fff;border-radius:14px;padding:22px;box-shadow:0 8px 24px rgba(0,0,0,.12)}
  .hero h1{margin:0 0 4px;font-size:20px}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:16px}
  .card{border:1px solid #e4e4e7;border-radius:12px;padding:14px;transition:transform .15s}
  .card:hover{transform:translateY(-2px);box-shadow:0 6px 18px rgba(0,0,0,.08)}
  .pill{display:inline-block;font-size:11px;font-weight:600;padding:2px 8px;border-radius:999px;background:#fef3c7;color:#92400e}
  mark{background:#fde68a;border-radius:3px;padding:0 3px}
</style></head><body><div class='wrap'>
  <div class='hero'><h1>Anamnesis — custom HTML island</h1>
    <div style='opacity:.9;font-size:13px'>If you can read this styled card in chat, Path B renders.</div></div>
  <div class='grid'>
    <div class='card'><span class='pill'>REVIEW</span><div style='font-weight:600;margin-top:6px'>Stable angina pectoris</div>
      <div style='font-size:13px;color:#52525b;margin-top:6px'>...reports <mark>stable angina pectoris</mark> on metoprolol...</div></div>
    <div class='card'><span class='pill'>ATTENTION</span><div style='font-weight:600;margin-top:6px'>Losartan 50mg</div>
      <div style='font-size:13px;color:#52525b;margin-top:6px'>switch to <mark>losartan 50 mg</mark>; lisinopril discontinued</div></div>
  </div>
  <button onclick="document.getElementById('o').textContent='JS works ✓ ('+new Date().toLocaleTimeString()+')'"
    style='margin-top:16px;padding:8px 14px;border:0;border-radius:8px;background:#18181b;color:#fff;cursor:pointer'>Test JS</button>
  <div id='o' style='margin-top:10px;font-size:13px;color:#16a34a'></div>
</div></body></html>
"""

embed_app = FastMCPApp("Embed island test")


@embed_app.ui("ReviewChart")
def review_chart() -> PrefabApp:
    with Column(css_class="h-full") as view:
        Embed(html=_CUSTOM_HTML, width="100%", height="560px",
              sandbox="allow-scripts")
    return PrefabApp(view=view)


mcp = FastMCP(name="Anamnesis PathB", instructions="Embed island test")
_orig = mcp._mcp_server.get_capabilities
def _caps(self, n, e):
    c = _orig(n, e); ex = getattr(c, "extensions", None) or {}
    c.extensions = {**ex, _FHIR_EXT: {"scopes": _SCOPES}}; return c
mcp._mcp_server.get_capabilities = MethodType(_caps, mcp._mcp_server)
mcp.add_provider(embed_app)


def main() -> None:
    print("Path B (Embed island) at http://0.0.0.0:8042/mcp — Ctrl+C to stop.")
    try:
        mcp.run(transport="http", host="0.0.0.0", port=8042)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
