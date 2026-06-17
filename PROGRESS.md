# Anamnesis — Progress Report (2026-06-16)

Session focus: stateless backend + getting a custom review UI to render in the
Prompt Opinion (PO) host. Substantial backend progress; UI delivery mechanism
now fully diagnosed and the path forward is clear.

---

## TL;DR

- **Backend stateless contract: built, verified, no PHI at rest.** This is the real deliverable and it's solid.
- **Tool surface redesigned** to a clean 3-tool model surface; legacy tools gated behind a flag.
- **UI is the open problem.** Spent the session discovering how PO renders apps. Final, tested conclusion:
  - PO does **NOT** render standard `ui://` HTML apps the way we first built them (inline-bundled React) — **inline JS is CSP-blocked** in PO's sandbox.
  - PO **DOES** render custom `ui://` HTML (static HTML/CSS confirmed rendering) and loads **external CDN JS** (its own Prefab renderer works that way).
  - PO **DOES** render Prefab (its native server-side component DSL) — we built a full themed Prefab review app that works end-to-end, but the user dislikes the Prefab look ceiling.
- **Tomorrow's plan: ship our React app as externally-hosted JS (not inlined), served as routes on our own server, and connect it to PO's `io.modelcontextprotocol/ui` bridge.** This likely lets us keep the entire React UI already built.

---

## What works right now (committed/working in tree)

### Stateless backend (the substance — DONE)
- `backend/services/proposals.py`:
  - `run_extraction_ephemeral()` — runs the full pipeline, returns `{run_id, patient_id, documents, proposals}`, **persists no PHI**. Streams stage progress via a `progress_cb`.
  - `accept_augmentation()` — writes FHIR resource + Provenance via the per-request SHARP token; resolves from RAM cache (`run_id`+`proposal_id`) or payload fallback. Records a non-PHI `DecisionAudit`.
  - `record_decision()` — non-PHI audit rows.
  - `_execute_stages(..., progress_cb=, persist_guardrail=)` — refactored to a pure compute path (no DB writes when called statelessly).
- `backend/services/session_cache.py` — in-process TTL cache (1h) for proposals+docs, keyed by `run_id`. PHI lives here only, never disk.
- `backend/db/models.py` — added `DecisionAudit` (non-PHI: run_id, action, resource_type, reviewer, resource_ref, at).
- `backend/context/sharp.py` — added `get_tenant_key()` (hash of FHIR server URL / token issuer; non-PHI, for telemetry + future config).
- `backend/core/telemetry.py` — `start_run(patient_id=None, patient_name=None)` on the stateless path → PHI-free run rows; LLM cost still attributed by opaque run_id.
- **Verified**: dry-run on demo bundle → 54 proposals, 0 ProposalRecord persisted, run row patient_id=None, token never stored, RAM-cache hit, Provenance built on accept, DecisionAudit written. Offline tests: **88 passed (~1.7s)**.

### Tool surface redesign (DONE)
- Clean **model-visible** surface (3 tools): `GetPatientContext`, `ReviewChart`, `SearchTerminology`.
- **App-only** (visibility:["app"], hidden from model): `RunExtraction`, `AcceptAugmentation`, `RejectAugmentation`.
- **Legacy DB-backed tools** (WhoIsPatient, ProposeAugmentations, ListProposals, AcceptProposal, etc.) gated behind `settings.expose_legacy_tools` (default False; env `EXPOSE_LEGACY_TOOLS=true` re-enables for the web-workspace deploy). See `backend/mcp_server/server.py` (official-SDK server) — this is the `mcp` 1.27 path.

### Bug fixed
- `SearchTerminology` was still loading the 527k-vector FAISS index (SapBERT) on call. Rewired to the API retriever (`backend/mcp_server/tools.py`). Confirmed `faiss imported: False`, `losartan → RxNorm 52175` via live API.

### Prefab review app (WORKS in PO, but look rejected by user)
- `backend/mcp_server/prefab_review.py` — full review UI in Prefab (FastMCP v3): auto-run extraction on open (`on_mount`), queue + detail + highlighted source-note reader, accept/reject via `CallTool` into the stateless tools.
- `backend/mcp_server/prefab_theme.py` — our exact OKLCH tokens + component CSS overrides.
- `backend/po_main.py` — FastMCP **v3** entrypoint serving the Prefab app (PO uses `fastmcp[apps]`, NOT the official `mcp` SDK).
- `backend/context/prefab_ctx.py` — SHARP context via `get_http_headers()` (v3 has no `ctx` param).
- **Fixed mid-session**: selection bug — was `If(f"selected == {p.id}")` (template-in-expression, never matched). Now stores whole proposal in `current` state and renders detail from `current.*`. Builds clean.

---

## The big discovery: how Prompt Opinion actually renders UI

PO is **NOT** standard MCP Apps as we assumed. Investigated their sample repo
`github.com/prompt-opinion/po-fastmcp`:
- PO runs **FastMCP v3** (`fastmcp[apps]>=3.2.4`), not the official `mcp` SDK's `mcp.server.fastmcp`.
- Their UI framework is **Prefab** (`prefab-ui`, public PyPI pkg, v0.19–0.20) — a server-side declarative component DSL (`@app.ui()` returns a `PrefabApp`; `Card`/`Column`/`Button`/`CallTool`/`SetState`). Has 117 components incl. `Markdown`, `Span`, `Embed`, `Tabs`, `DataTable`.
- FHIR context via `get_http_headers()` reading `x-fhir-server-url` / `x-fhir-access-token` / `x-patient-id` (same SHARP headers we use).

### The CSP sandbox findings (tested empirically against the live PO host)
Ran probes (`backend/test_pathC_probe.py`, `PROBE=static|inline|external`):

| HTML content | Renders in PO? |
|---|---|
| Static HTML + CSS (no JS) | ✅ YES (green card rendered) |
| **Inline `<script>`** | ❌ **BLOCKED** (CSP, no unsafe-inline) |
| External CDN `<script src>` | ✅ YES (PO's own Prefab renderer loads from cdn.jsdelivr.net this way) |

**Root cause of our blank-box failure:** our `mcp-app` React build uses
`vite-plugin-singlefile` → everything inlined → inline JS blocked → blank box.
The HTML/resource served fine; only the JS didn't execute.

### Tool dispatch finding
- A `ui://` tool MUST carry `meta.ui = {resourceUri, visibility:["model"]}`.
  Our first Path C attempt omitted `visibility:["model"]` → PO returned
  *"Requested function ReviewChart not found"* (rejected before reaching server).
  Adding it fixed dispatch (box rendered).
- Earlier same error was ALSO caused by PO pointing at the stale `anamnesis-demo.fly.dev` deploy at one point, and by tool-name mismatches. All resolved.

### Dead ends (don't retry)
- **Inline-bundled React app** — blocked by CSP. Must externalize JS.
- **Reusing `mcp-app/` single-file build as-is** — same inline problem.
- Prefab-only look — works but user rejected the aesthetic ceiling.

---

## Tomorrow's plan (in priority order)

**Goal: our own custom React UI rendering in PO with working accept/reject — no Prefab.**

1. **Rebuild `mcp-app` WITHOUT `vite-plugin-singlefile`** → emit separate `review.js` + `review.css`.
2. **Serve those as plain HTTP routes** on the FastMCP server (same ngrok host) — no GitHub/CDN push needed. Add that origin to the resource CSP `resource_domains`.
3. **Shrink the `ui://` HTML resource** to PO's renderer pattern: `<div id=root>` + `<link rel=stylesheet href=...>` + `<script type=module src=".../review.js">`.
4. **THE KEY UNKNOWN — the iframe↔host data bridge.** PO advertises
   `io.modelcontextprotocol/ui` in its `initialize` handshake. Need to determine
   how the iframe calls back to the host to (a) get tool input/result and
   (b) invoke RunExtraction/AcceptAugmentation. Options to investigate:
   - Does our existing `@modelcontextprotocol/ext-apps` `PostMessageTransport` +
     `callServerTool` connect to PO's bridge? (PO advertises the standard ext;
     it might just work once JS executes.)
   - Inspect PO's `prefab-ui` renderer.js (cdn.jsdelivr.net/npm/@prefecthq/prefab-ui@0.20.2/dist/app/renderer.js) to see exactly what host API it uses.
   - Worst case: a small postMessage protocol matching whatever PO exposes.
5. If the bridge connects → wire our React app's data layer to the real tools, done.
6. **Fallback if the React bridge can't be made to work:** hybrid — custom HTML
   for the fancy display inside a Prefab `Embed`, Prefab buttons for the
   tool-calling actions (Embed is sandboxed / no MCP bridge).

---

## Environment notes for tomorrow

- **Two server entrypoints exist:**
  - `backend/main.py` — official `mcp` SDK server (port 8042), the 3+legacy tools, `app.mount("/", mcp.streamable_http_app())` → endpoint at `/mcp`.
  - `backend/po_main.py` — **FastMCP v3** server (port 8042) serving the Prefab app. This is the one PO connects to. Run with the **backend venv** (`.venv`) — `fastmcp[apps]` + `prefab-ui` were installed into it this session (coexists with `mcp` 1.27; starlette bumped to 1.3.1, tests still pass).
- **PO connection**: ngrok forwards `https://ogle-spinach-splendor.ngrok-free.dev` → `localhost:8042`. The MCP endpoint is **`/mcp`** (bare domain 404s — that's normal). PO must re-sync tools after a server change.
- **ngrok web inspector**: `http://127.0.0.1:4040/inspect/http` — shows exactly what PO sends; use it to confirm whether a tool call reached the server.
- **Probe/test files** (can delete later): `backend/test_pathB.py` (Prefab Embed island — renders), `backend/test_pathC.py` (standard ui:// React — box renders, JS blocked), `backend/test_pathC_probe.py` (static/inline/external CSP probe), `backend/spike_prefab/app.py` (original spike).
- **Throwaway probe venv** at `/tmp/.prefab-probe` (has fastmcp[apps]+prefab-ui) — not needed anymore since backend `.venv` now has them.
- `AGENT_PROMPT.md` — clean general prompt written for the 3-tool surface (no demo specifics).

## Caveats / honest status
- The Prefab review app **works end-to-end** (extraction, selection, accept/reject) if we ever want to fall back to it. Selection bug fixed but the *themed* version wasn't re-verified clicking in PO after the fix (server was up but user stopped for the day).
- The React-on-PO path (tomorrow's plan) is **not yet proven** — step 4 (the host bridge) is a genuine unknown and the main risk.
- Stateless backend is the one part that is fully done and verified.
- UMLS key still in `.env` / chat history — ROTATE before any public push.
