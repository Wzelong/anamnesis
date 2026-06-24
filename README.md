# Anamnesis

> The data wasn't missing — it was unstructured. Now it's not.

A FHIR augmentation **MCP server** for the **Agents Assemble: The Healthcare AI Endgame** hackathon (Option 1: Build a Superpower). Anamnesis reads clinical notes against an existing FHIR record, proposes additions and corrections with full source provenance, and writes them back to the FHIR server only after a clinician approves them.

The MCP is the substantive deliverable — invokable by any agent in the Prompt Opinion (PO) ecosystem. The provider-facing review workspace ships **inside the same server** as a standard MCP App, rendered in the PO host iframe — no separate frontend deploy.

## Try it

- **Demo video** — <https://youtu.be/S1mlkVjZD2s>
- **Marketplace listing** — <https://app.promptopinion.ai/marketplace/mcp/019df448-2990-7148-981a-72ebf813006b>
- **MCP endpoint** — Streamable HTTP at `/mcp` on the deployed server (Render). Register it under PO *Configuration → MCP Servers*; the review UI opens in-host.

## How it works

![Pipeline](pipeline.png)

Six stages from clinical note to clinician-reviewable proposal, plus a deterministic write-back stage on accept. Deterministic where it can be (sentence splitting, terminology lookup, code matching, FHIR assembly), LLM-driven where it must be (extraction, fuzzy reconciliation). The pipeline runs **in memory — no PHI at rest**. Every accepted change writes back as a transaction Bundle with a `Provenance` resource that points at the source span — an audit trail manual chart review does not produce.

See [Architecture.md](Architecture.md) for the system shape, [DIRECTION.md](DIRECTION.md) for where it is headed, and [PIPELINE.md](PIPELINE.md) for the per-stage deep-dive.

## What we built

- **MCP server (`backend/po_main.py`)** — one FastMCP v3 server, one transport (Streamable HTTP at `/mcp`). One model-visible tool, `ReviewChart`, opens the in-host review workspace and seeds the patient header. The rest are app-only, invoked by the review app over the MCP-Apps postMessage bridge: `RunExtraction`, `AcceptAugmentation`, `RejectAugmentation`, `SearchTerminology` (SNOMED / RxNorm / LOINC / ICD-10), and the config/usage tools `GetUserConfig` / `SetUserConfig` / `GetUsage`. SHARP-aware: FHIR base URL, access token, and patient id arrive as request headers.
- **In-host review app (`mcp-app/`)** — a Vite + React 19 + shadcn/ui SPA that builds to a single `review.js` / `review.css` pair served by the backend. It renders in PO's iframe, shows live stage-by-stage progress as the pipeline runs, and surfaces source notes, the chart slice, classification, confidence breakdown, citation spans, conflict callouts, and accept / edit / reject actions.
- **BYOK, encrypted, required.** The pipeline runs on the clinician's own Gemini key (`gemini-3.5-flash`; guardrail on `gemini-3.1-flash-lite`), never a shared one. Secret fields are Fernet-encrypted at rest in the per-clinician config and only ever decrypted in-process; the iframe sees a `{set, last4}` presence flag.
- **PO-native auth.** Identity is the SHARP token `sub`. Per-user config/secret writes are gated on a JWKS signature + `iss` + `exp` verification (`context/token_verify.py`); reads stay host-delegated (a forged token self-fails at the FHIR server).
- **Augmentation pipeline** — six stages plus a per-doc input guardrail, dual-coded terminology against SNOMED / ICD-10 / LOINC / RxNorm via live authoritative APIs (NLM / UMLS / RxNav) behind a pluggable `Retriever` seam, deterministic chart reconciliation with LLM adjudication only for ambiguous cases.
- **Eval corpus + benchmark runner** — 18 multi-source clinical notes × 13 patient charts × 77 labeled facts, with multi-run accuracy / consistency / provenance reporting.

## Benchmark headline

| Metric | Value |
|---|---|
| Augmentation accuracy | 90% [87%, 95%] |
| Consistency (correct in ≥4/5 runs) | 88% |
| Provenance coverage | 100% |
| Cost per chart prep (3 notes) | ~$0.13 |
| End-to-end latency per chart prep | ~20-25s wall-clock (notes processed in parallel) |

![Per-class accuracy](benchmarks/eval-corpus-v1/results/20260504T015004Z/per_class_accuracy.png)

NEW (93%) and DUPLICATE (92%) — the bulk of real clinical findings — both clear 90% with tight variance. UPDATING and CONFLICTING are thin slices (n=3 and n=1); the wide error bars are honest sample-size acknowledgment, not hidden failures.

> The headline run was captured on the earlier pipeline (`gpt-5.4-mini` / `gpt-5.4-nano`, 5 runs · 18 notes × 13 fixtures × 77 facts). The live stack has since migrated to Gemini + BYOK; a re-run on the Gemini models is pending. Full per-class accuracy, confusion matrix, stability buckets, per-stage cost breakdown, and reproducibility instructions are in the latest [REPORT.md](benchmarks/eval-corpus-v1/results/20260504T015004Z/REPORT.md).

## Demo flow

1. **Pre-visit catch-up.** A clinician asks the agent to prepare a chart. The agent calls `ReviewChart` over MCP. SHARP headers carry the FHIR base URL, an access token, and the patient id.
2. **Workspace opens in-host.** The review app renders in PO's iframe. First-time clinicians land on the BYOK connect view; once a Gemini key is connected, the landing shows the patient header and a run action.
3. **Pipeline runs.** The app calls `RunExtraction`; the backend pulls the existing chart and notes, runs the six-stage augmentation on the clinician's key, and streams stage progress back to the iframe. Nothing is persisted.
4. **Clinician reviews.** Each proposal shows the source span highlighted in the original note, the FHIR resource Anamnesis would write, the classification (NEW / UPDATING / CONFLICTING), a confidence breakdown, and any conflict with the existing chart. A code-search view swaps in a better terminology code before accepting.
5. **Accept.** On accept, `AcceptAugmentation` writes a single transaction Bundle: the resource, a `Provenance` with one entity per source document and one source-span extension per citation, and — for inline notes — a US Core `DocumentReference` carrying the source text. Nothing reaches the chart silently.

## Run it locally

Prerequisites: Python 3.11+ (3.12 in prod), Node 20+, ngrok, a Gemini API key.

### 1. Start the backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env               # set GEMINI_API_KEY and CONFIG_SECRET_KEY
python po_main.py                  # serves http://0.0.0.0:8042/mcp
```

Sanity check: `curl http://localhost:8042/healthz` → `{"status":"ok"}`.

Terminology coding uses live NLM/UMLS/RxNav APIs. SNOMED retrieval needs a free `UMLS_API_KEY` (<https://uts.nlm.nih.gov>); RxNorm / ICD-10 / LOINC need none.

### 2. Expose the asset origin via ngrok

PO's iframe is sandboxed (null origin), so the `ui://` shell loads `review.js` / `review.css` over an absolute URL. Point `APP_ASSETS_BASE_URL` (in `.env`) at a public origin:

```bash
ngrok http --domain=<your-domain>.ngrok-free.dev 8042
```

### 3. Build the review app

```bash
cd mcp-app
npm install
npm run build          # outputs review.js / review.css into backend/mcp_server/ui/assets/
```

For UI development, `npm run dev` serves the app standalone (pinned to PO's 800×520 iframe size) with `?preview=<view>` for offline view work.

### 4. Configure Prompt Opinion

1. **Register the MCP server.** *Configuration → MCP Servers → Add MCP Server*. Enter the ngrok URL (`.../mcp`), select **Streamable HTTP**, enable the **Prompt Opinion Extension**, set FHIR Context Permission to **Full Authority** (for testing). Save.
2. **Create an agent.** *Agents → Add AI Agent*. Set Allowed Contexts to **Patient**. Under **Tools → Additional Tools (MCP Servers)**, select the Anamnesis server. Save.
3. **Import the demo patient.** *Patient Data → Import* → upload `data/demo_patient/anamnesis-demo-bundle.json`.

### 5. Run the demo

*Launchpad → Select a Scope → Patient*, select **James Lee (11/15/1958)**, then the agent you created. Ask it to review the chart; the review workspace opens in-host. Connect a Gemini key in Configuration, then run augmentation.

### Reproduce the benchmark

```bash
cd benchmarks/eval-corpus-v1
python run_demo_benchmark.py --runs 5
```

Re-render the report from a prior run (no API spend): `python run_demo_benchmark.py --rerender results/<timestamp>`.

## Deployment

Deployed on **Render** (native Python, no Docker) with a **Neon** Postgres database (`asyncpg`, `NullPool`). `render.yaml` defines the service: `pip install .` then `python po_main.py`, health check at `/healthz`. `CONFIG_SECRET_KEY` is generated by Render; `GEMINI_API_KEY`, `UMLS_API_KEY`, and `DATABASE_URL` are set as secrets. The built UI assets are committed under `backend/mcp_server/ui/assets/`, so deploys do not run a Node build. The only persisted state is non-PHI: per-clinician config and a per-run usage ledger.

## Repo layout

```
anamnesis/
  backend/             FastMCP v3 server, augmentation pipeline, FHIR I/O
  mcp-app/             React review UI (Vite), built into backend/mcp_server/ui/assets
  benchmarks/          Eval corpus + multi-run benchmark
  data/demo_patient/   Synthetic Bundle + notes for offline demos
  Architecture.md      System shape, contracts, invariants
  DIRECTION.md         Where Anamnesis is headed (configurable extraction framework)
  PIPELINE.md          Per-stage augmentation pipeline deep-dive
```

## Docs

- [Architecture.md](Architecture.md) — system shape, MCP surface, persistence, auth, FHIR write path, contracts, invariants
- [DIRECTION.md](DIRECTION.md) — the configurable extraction-framework direction (IG layering, presets, BYOK, usage ledger)
- [PIPELINE.md](PIPELINE.md) — six-stage augmentation pipeline + write-back, confidence scoring
- [benchmarks/eval-corpus-v1/README.md](benchmarks/eval-corpus-v1/README.md) — eval corpus design, label schema, reproducibility
