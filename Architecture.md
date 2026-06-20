# Architecture

Anamnesis is a FHIR augmentation **MCP server**. It reads clinical notes against an existing FHIR record, proposes additions and corrections with full source provenance, and writes them back to the FHIR server only after a clinician approves them. The MCP is the substantive deliverable; the review workspace ships **inside the same server as a standard MCP App** rendered in the Prompt Opinion (PO) host iframe.

This document describes the system as it is. For where it is headed — the configurable extraction framework — see [DIRECTION.md](DIRECTION.md). For the augmentation pipeline internals see [PIPELINE.md](PIPELINE.md). For the demo path and quickstart see [README.md](README.md).

![Pipeline](pipeline.png)

## Top-level layout

```
anamnesis/
  backend/             FastMCP v3 server, augmentation pipeline, FHIR I/O
  mcp-app/             React review UI (Vite), built into backend/mcp_server/ui/assets
  benchmarks/          eval-corpus-v1 + augmentation benchmark runner
  data/demo_patient/   Synthetic patient bundle + notes for offline demos
```

The backend is self-sufficient: any agent in the PO ecosystem drives it through MCP. The review UI is a standard MCP App served by the backend itself — there is no separate frontend deploy.

## Single server, no PHI at rest

There is one process (`backend/po_main.py`) and one transport (Streamable HTTP at `/mcp`). There is no separate REST API and no separate frontend service. The pipeline runs **in memory**; the durable clinical store is the FHIR server (resource + `Provenance`). The only persisted state is non-PHI: per-clinician framework config and a per-run usage ledger.

## End-to-end flow

1. A clinician (in PO) asks the agent to prepare a chart. The agent calls **`ReviewChart`** over MCP. SHARP request headers carry the FHIR base URL, an access token, and the patient id.
2. `ReviewChart` seeds the patient header and opens the in-host React review app (an MCP App `ui://` resource). The app connects to the PO host over the standard MCP-Apps postMessage bridge.
3. If the clinician has not connected a Gemini API key, the app lands on the BYOK connect view. **BYOK is required** — the pipeline runs on the clinician's key, never a shared one.
4. The clinician runs augmentation. The app calls the app-only **`RunExtraction`** tool, which runs the pipeline synchronously and streams stage-by-stage progress back to the iframe via MCP progress notifications (guardrail → preprocess → extract → merge → code → reconcile → assemble).
5. `RunExtraction` returns proposals + source notes. The clinician reviews each proposal — source span, the FHIR resource Anamnesis would write, classification (NEW / UPDATING / CONFLICTING), confidence breakdown, chart conflicts — and accepts / edits / rejects via **`AcceptAugmentation`** / **`RejectAugmentation`**.
6. On accept, `AcceptAugmentation` builds a single FHIR `transaction` Bundle: the resource (`Condition`, `Observation`, …), a `Provenance` with one entity per source document and one source-span extension per citation, and — for inline notes — a US Core `DocumentReference` carrying the source text. The chart only ever contains ratified evidence behind an approved finding.

## Backend

Lives under `backend/`. `po_main.py` instantiates a single `FastMCP` server, advertises the PO SHARP capability extension (`ai.promptopinion/fhir-context`) listing the FHIR scopes the pipeline needs, registers the review app, and runs over Streamable HTTP. `ANAMNESIS_UI=prefab` swaps the React app for the legacy Prefab app; the default is `react`.

### MCP surface (`mcp_server/react_review.py`)

One model-visible tool opens the workspace; the rest are app-only — invoked by the React app over the MCP-Apps bridge, not by the model.

| Tool | Visibility | Job |
|---|---|---|
| `ReviewChart` | model | Open the review workspace and seed the patient header (name, DOB, sex, MRN, BYOK flag, returning-user recognition). |
| `RunExtraction` | app | Run the augmentation pipeline on the clinician's BYOK key; stream stage progress; return proposals + source notes. |
| `AcceptAugmentation` | app | Write an accepted proposal to FHIR as a transaction Bundle with `Provenance`. Accepts an edited resource. |
| `RejectAugmentation` | app | Record a non-PHI reject decision (structured log; no FHIR write). |
| `SearchTerminology` | app | Vector/API search over SNOMED, RxNorm, LOINC, or ICD-10. Returns ranked `{code, display, score}`. Read-only. |
| `GetUserConfig` | app | The clinician's persisted framework config, secrets redacted to `{set, last4}`. Token-verified. |
| `SetUserConfig` | app | Deep-merge a config patch; secret fields encrypted at rest; response redacted. Token-verified. |
| `GetUsage` | app | The clinician's run history + cumulative spend (non-PHI usage ledger). |

The `ui://` shell, the `/app/{filename}` asset routes (serving `review.js` / `review.css`), and a `/healthz` check are registered as custom HTTP routes on the same server.

### The pipeline (`core/`, `services/proposals.py`)

Six stages from chart load to clinician-reviewable proposal, plus an input guardrail before Stage 2 and a deterministic write-back stage on accept. Each stage is a pure function over typed Pydantic schemas; LLM calls go through the single `core/llm.py` Gemini wrapper (`gemini-3.5-flash`; guardrail on `gemini-3.1-flash-lite`) and are wrapped in telemetry. The service layer composes them:

- `services.proposals.run_extraction_ephemeral(patient_id, fhir_client, …)` — loads `PatientContext` + chart `DocumentReference`s (or the local demo bundle when no FHIR client is bound), runs the stages, records a usage row, caches the run in an in-process TTL cache, and returns proposals + notes. **Persists no PHI** (`use_cache=False`: no extracted clinical data touches disk).
- Inline notes are supported in the same entry point (`inline_notes: list[str]`): `_documents_from_notes` builds `Document`s with deterministic `inline_<sha256[:12]>` ids. Inline source text only enters the chart on accept, minted as a US Core `DocumentReference` in the same transaction.

For per-stage detail (preprocess, extract, merge, code, reconcile, assemble, write-back), confidence scoring, and module layout, see [PIPELINE.md](PIPELINE.md).

### Persistence (`db/models.py`)

Two tables, both non-PHI, keyed on the PO token `sub`:

- **`AppUser`** — per-clinician framework config (`user_key` = token `sub`, `display_name`, `workspace_id`, `role`, `config` JSON, recognition counters). The `config` blob holds BYOK secrets (encrypted), the active preset, and presets. This is the only durable application state.
- **`UsageRun`** — one row per pipeline run: `user_key`, `model`, token counts (input / output / reasoning), `cost_usd`, `duration_ms`, `doc_count`, `status`, `triggered_by`. No patient id, no clinical content — pure billing metadata that powers the "Account & usage" view.

`db/session.py` uses a SQLAlchemy 2.0 async engine. SQLite by default (`DATABASE_URL`); Postgres (Neon, via `asyncpg`) in production with `NullPool` so connections are not reused across event loops. `init_db()` runs `create_all` at startup.

There is **no** `PipelineRun`, `LLMCall`, `ProposalRecord`, or `ReviewToken` table — those were removed when the stack went stateless. Clinical data lives only on the FHIR server.

### Auth & SHARP (`context/`)

- `context/auth.py` — reads identity claims from the PO SHARP access token (signature not checked here): `extract_user_context` maps `sub` → `user_key`, `po_ws_id` → `workspace_id`, `role`; `extract_clinician_identity` derives the reviewer display + `fhirUser` reference for Provenance attestation. We mint nothing and store no tokens.
- `context/prefab_ctx.py` — sources SHARP context from the per-request HTTP headers (`x-fhir-server-url`, `x-fhir-access-token`, `x-patient-id`) via FastMCP's `get_http_headers()`, since app-only tools have no `Context` param. `prefab_patient_id` prefers the `patient` claim inside the access-token JWT.
- `context/token_verify.py` — `verify_po_token` treats the server as an OAuth 2.1 resource server: it fetches PO's JWKS and verifies signature + `iss` + `exp` (plus an optional `po_mcp_id` pseudo-audience). `prefab_verified_user_context()` gates every **per-user write** (config, BYOK secrets) on this verification — an unverified `sub` is forgeable. **Read paths stay host-delegated**: a forged token self-fails at the FHIR server.

### BYOK (`core/byok.py`)

Secret fields in `app_user.config` (`gemini_api_key`, `umls_api_key`) are Fernet-encrypted at rest under `CONFIG_SECRET_KEY` (any string; an empty key disables BYOK and storing a secret raises). Three operations: `seal` (encrypt a patch before storage; an echoed redaction placeholder is dropped so a deep-merge never wipes a stored key), `redact` (replace ciphertext with `{set, last4}` for the iframe — plaintext never leaves the server), `unseal` (decrypt in-process to build the LLM client, pipeline use only). `RunExtraction` requires a stored, decryptable Gemini key.

### Telemetry & usage (`core/telemetry.py`, `services/usage.py`)

A `RunContext` is established in a `ContextVar` at `start_run` and torn down at `finish_run`. Each LLM call records model, token mix, latency, and computed USD cost (`core/pricing.py`) into an in-memory buffer and a JSONL file under `.cache/telemetry/`. At run end the buffer is aggregated to a single non-PHI row (`services.usage.record_run`) — run-level totals only, never the per-call `document_id`. `GetUsage` surfaces per-run detail + cumulative spend.

### FHIR I/O (`fhir/`)

- `fhir/client.py` — async `FhirClient(base_url, token)` with `read`, `search`, `transaction`.
- `fhir/read.py` — `read_patient_context` and `read_documents` build the typed `PatientContext` and `Document` shapes the pipeline consumes.
- `fhir/local_bundle.py` — `load_demo_data()` serves the synthetic demo bundle for offline runs (no FHIR client bound).
- `fhir/write.py` — the accept-time write path:
  - `Citation` carries `document_ref`, `start`, `end`, `text`, and optional `inline_document` (a `Document` to be minted as a US Core `DocumentReference`).
  - `apply_augmentation` dispatches by classification:
    - **NEW** — POST resource + POST Provenance.
    - **UPDATING** — read existing → PUT updated resource (carrying `versionId` for optimistic concurrency) + POST Provenance against the superseded reference.
    - **CONFLICTING** — POST a parallel new resource + POST Provenance. Does not retire the existing resource; the conflict is an annotation, not a unilateral correction.
  - `_resolve_inline_citations` mints one `DocumentReference` Bundle entry per unique inline document (US Core profile, LOINC `34109-9 Note` default, base64 inline content, `clinical-note` category, `Patient/{id}` subject, attester as `author`) and rewrites citation `document_ref`s to that entry's `urn:uuid:` so the standard provenance builder produces correct linkage.
  - `build_provenance` emits one `entity` per unique source plus one `source-text-span` extension per citation, recording the document ref, character offsets, and quoted text. Multi-citation proposals get multi-entity provenance — the UI uses these to highlight every corroborating note.

### Tests (`tests/`)

Stage- and unit-level tests run without network: `test_extraction.py`, `test_preprocess.py`, `test_stage2_regression.py`, `test_coding_warmup.py`, `test_doc_guardrails.py`, `test_byok.py`, `test_usage.py`.

## Review app (`mcp-app/`)

A Vite + React 19 + TypeScript SPA, shadcn/ui on Radix + Tailwind, that builds to a single `review.js` / `review.css` pair under `backend/mcp_server/ui/assets/`. It runs in the PO host iframe. PO's CSP blocks inline JS, so the `ui://` shell is a bare `<div id=root>` that loads the bundle over the absolute `APP_ASSETS_BASE_URL`; the app then talks to the host over the MCP-Apps postMessage bridge (`@modelcontextprotocol/ext-apps`).

Views:

- **Landing** — patient header + run action once a Gemini key is connected.
- **Connect Gemini / BYOK** — the gate the app lands on when unconfigured.
- **Review** — proposals grouped by tier with classification badges; per-proposal detail (resource viewer, confidence breakdown, citation list with source spans, conflict callouts), an editable FHIR resource form, and Accept / Reject / Edit actions. Accepting a proposal in a conflict group auto-rejects its siblings.
- **Note reader** — source documents with cited spans highlighted by tier color.
- **Code search** — `SearchTerminology` UI to swap in a better code before accepting.
- **Configuration** — framework config surface (presets, IG selection, resource toggles, coding, prompts) plus an Account & usage pane. This is the in-progress home of the configurable framework; see [DIRECTION.md](DIRECTION.md).

Theme and host style variables are applied from the host context. The dev build (`npm run dev`) pins the layout to PO's iframe size (800×520) and supports `?preview=<view>` for offline view development.

## Contracts

The boundaries another consumer would reason about if they embedded the MCP elsewhere or replaced the FHIR server.

- **MCP tool contract** — tool names, input schemas, output shapes, visibility, and required SHARP scopes are advertised by the `FastMCP` server in `po_main.py` and `mcp_server/react_review.py`. Inputs and outputs are JSON over Streamable HTTP at `/mcp`.
- **MCP App contract** — the `ui://anamnesis/review.html` resource and the `/app/*` asset routes. The iframe negotiates the standard MCP-Apps protocol (`ui/initialize` + `callServerTool`) with the host.
- **SHARP context contract** — `x-fhir-server-url`, `x-fhir-access-token`, `x-patient-id` request headers; the access token is a PO-signed OIDC JWT whose `sub` is the per-clinician key and `patient` claim carries the patient id.
- **FHIR write contract** — every accepted proposal becomes one transaction Bundle: the resource (`Condition` / `MedicationRequest` / `AllergyIntolerance` / `Observation` / `Procedure` / `FamilyMemberHistory`, US Core where a profile exists), a `Provenance` with one `entity` per source document and one `source-text-span` extension per citation, and — for inline notes — a US Core `DocumentReference`. UPDATING uses PUT with `versionId`; CONFLICTING never retires the existing resource.
- **Source-of-truth contract** — clinical data lives on the FHIR server. The local database holds non-PHI working state only (per-clinician config, usage ledger). Wiping it loses config and billing history, never clinical data.

## Invariants

- **No PHI at rest.** The pipeline runs in memory; extracted clinical data never touches disk. The only persisted state is per-clinician config and a non-PHI usage ledger.
- **Nothing writes silently.** Every chart change passes through `apply_augmentation` and is paired with a `Provenance`. Inline source text only enters the chart when its derived augmentation is accepted, in the same transaction.
- **Every fact carries provenance.** Source span, classification, confidence breakdown, reviewer identity, and Provenance reference accompany every accepted proposal.
- **Per-user writes are signature-verified.** Keying any config or secret to a `sub` requires a PO-verified token; reads stay host-delegated.
- **BYOK only.** The pipeline runs on the clinician's own Gemini key, decrypted in-process, never a shared server key.
- **The MCP is the product.** The review app is a reference consumer rendered in-host; substituting it with another agent or UI does not change the contract.

## Out of scope

What Anamnesis intentionally is not:

- **Not an EHR.** No order entry, billing, scheduling, or longitudinal patient app.
- **Not ambient capture.** Notes come from the FHIR server or are supplied by the calling agent. No audio recording or live transcription.
- **Not a payer / coding-revenue tool.** Terminology coding enables reconciliation against the chart, not billing maximization.
- **Not multi-tenant.** A single FHIR server per session, scoped by SHARP context. No tenant routing layer.
- **Not a SHARP token issuer.** PO issues the access token; the backend verifies its signature as a resource server but does not mint credentials.
- **Not a clinical decision-support system.** Proposals are evidence the clinician reviews; the system never recommends a diagnosis or therapy.
