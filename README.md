# Anamnesis

> The data wasn't missing — it was unstructured. Now it's not.

A FHIR augmentation **MCP server** for the **Agents Assemble: The Healthcare AI Endgame** hackathon (Option 1: Build a Superpower). Anamnesis reads clinical notes against an existing FHIR record, proposes additions and corrections with full source provenance, and writes them back to the FHIR server only after a clinician approves them.

The MCP is the substantive deliverable — invokable by any agent in the Prompt Opinion ecosystem. A thin **provider-facing review workspace** ships alongside as a reference consumer for the human-in-the-loop hand-off.

## How it works

![Pipeline](pipeline.png)

Six stages from clinical note to clinician-reviewable proposal, plus a deterministic write-back stage on accept. Deterministic where it can be (sentence splitting, terminology lookup, code matching, FHIR assembly), LLM-driven where it must be (extraction, fuzzy reconciliation). Every accepted change writes back as a transaction Bundle with a `Provenance` resource that points at the source span — an audit trail manual chart review does not produce.

See [Architecture.md](Architecture.md) for the system shape and [PIPELINE.md](PIPELINE.md) for the per-stage deep-dive.

## What we built

- **MCP server** — twelve tools covering patient context, augmentation proposals (chart-resident and inline notes), run status polling, proposal listing and full-detail retrieval, terminology code search across SNOMED / RxNorm / LOINC / ICD-10, and proposal lifecycle (accept / reject / reopen / edit). Streamable HTTP at `/mcp`. SHARP-aware. Pipeline runs asynchronously — the tool returns a workspace link immediately and the frontend shows live stage-by-stage progress. The MCP is self-sufficient: a chat-only agent can list, drill into, code-shop, edit, and accept without ever opening the review UI.
- **Augmentation pipeline** — six stages plus a per-doc input guardrail (deterministic + `gpt-5.4-nano`), dual-coded terminology against 1M+ SNOMED / ICD-10 / LOINC / RxNorm concepts via FAISS, deterministic chart reconciliation with LLM adjudication only for ambiguous cases.
- **Review workspace** — Next.js deep-link UI showing source notes, the chart slice, classification, confidence breakdown, and accept / edit / reject actions. Streaming chat assistant per run.
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

5 runs · `gpt-5.4-mini` (pipeline) · `gpt-5.4-nano` (guardrail) · 18 notes × 13 fixtures × 77 facts. Full per-class accuracy, confusion matrix, stability buckets, per-stage cost breakdown, and reproducibility instructions in the latest [REPORT.md](benchmarks/eval-corpus-v1/results/20260504T015004Z/REPORT.md).

## Demo flow

1. **Pre-visit catch-up.** A clinician asks the agent to prepare a chart. The agent calls `ProposeAugmentations` over MCP. SHARP headers carry the FHIR base URL, an access token, and the patient ID.
2. **Workspace opens immediately.** The MCP tool returns a deep link within seconds. The review workspace shows live stage-by-stage progress as the pipeline runs in the background.
3. **Pipeline completes.** Backend pulls the existing chart and notes, runs the six-stage augmentation, and persists proposals tiered by confidence. The agent polls `GetRunStatus` and reports the result.
4. **Clinician reviews.** Each proposal shows the source span highlighted in the original note, the FHIR resource Anamnesis would write, the classification (NEW / UPDATING / CONFLICTING), a confidence breakdown, and any conflict with the existing chart.
5. **Mid-encounter capture.** The agent uploads transcript text via `ProposeAugmentationsFromNotes`. Same pipeline, same review surface — the transcript itself is **not** written to FHIR yet.
6. **Accept.** On accept, `apply_augmentation` writes a single transaction Bundle: the resource, a `Provenance` with one entity per source document and one source-span extension per citation, and — for inline notes — a US Core `DocumentReference` carrying the source text. Nothing reaches the chart silently.

## Run it locally

Prerequisites: Python 3.11+, Node 20+, ngrok, an OpenAI API key.

### 1. Prepare embeddings and indexes

Download the [embeddings archive](https://drive.google.com/file/d/1Jf72Rb87ZjOSCt9I8d3_HYOl5yEXrJk5/view?usp=sharing) (requires access), unzip it, and place the resulting `embeddings/` folder at the repo root.

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m scripts.build_indexes    # builds data/indexes/ from embeddings/
python -m scripts.smoke_test_indexes  # verify indexes work
```

### 2. Start the backend

```bash
cp .env.example .env               # fill in OPENAI_API_KEY
uvicorn main:app --reload --port 8042
```

Wait for `Coding model and indexes ready` in the log. Sanity check: `curl http://localhost:8042/health` → `{"status":"ok","service":"anamnesis"}`.

### 3. Expose via ngrok

```bash
ngrok http --domain=<your-domain>.ngrok-free.dev 8042
```

Note the public URL (e.g. `https://<your-domain>.ngrok-free.dev`).

### 4. Start the frontend

```bash
cd frontend
npm install
npm run dev          # http://localhost:3042
```

### 5. Configure Prompt Opinion

1. **Register the MCP server.** Go to **Configuration → MCP Servers → Add MCP Server**. Enter the ngrok URL, select **Streamable HTTP**, set authentication to **None**, enable **Prompt Opinion Extension**, and set FHIR Context Permission to **Full Authority** (for testing). Save.
2. **Create an agent.** Go to **Agents → Add AI Agent**. Set Allowed Contexts to **Patient**. Under **Tools → Additional Tools (MCP Servers)**, select the Anamnesis server you just added. Save.
3. **Import the demo patient.** Go to **Patient Data → Import**. Under "Upload a FHIR Bundle", select `data/demo_patient/anamnesis-demo-bundle.json` from this repo. Import.

### 6. Run the demo

Go to **Launchpad → Select a Scope → Patient**, select **James Lee (11/15/1958)**, then select the agent you created. In the chat, type **"Augment chart"** and wait ~30 seconds. The agent will respond with a link to the review workspace — open it.

### Reproduce the benchmark

```bash
cd benchmarks/eval-corpus-v1
python run_demo_benchmark.py --runs 5
```

Re-render the report from a prior run (no API spend): `python run_demo_benchmark.py --rerender results/<timestamp>`.

## Repo layout

```
anamnesis/
  backend/             FastAPI + FastMCP server, augmentation pipeline, FHIR I/O
  frontend/            Next.js review workspace
  benchmarks/          Eval corpus + multi-run benchmark
  data/demo_patient/   Synthetic Bundle + four notes for offline demos
  Architecture.md      System shape, contracts, invariants
  PIPELINE.md          Per-stage augmentation pipeline deep-dive
```

## Docs

- [Architecture.md](Architecture.md) — system shape, MCP contract, persistence, frontend, contracts, out-of-scope
- [PIPELINE.md](PIPELINE.md) — six-stage augmentation pipeline + write-back, confidence scoring
- [benchmarks/eval-corpus-v1/README.md](benchmarks/eval-corpus-v1/README.md) — eval corpus design, label schema, reproducibility

## Links

- Hackathon: <https://healthcareagents.devpost.com>
- SHARP-on-MCP spec: <https://sharponmcp.com>
- Reference MCP: <https://github.com/darena-solutions/darena-health-community-mcp>
