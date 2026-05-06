# Architecture

Anamnesis is a FHIR augmentation agent. It reads clinical notes against an existing FHIR record, proposes additions and corrections with full source provenance, and writes them back to the FHIR server only after a clinician approves them. The product ships as an **MCP server** (the substantive deliverable) plus a **provider-facing review workspace** that handles the human-in-the-loop hand-off.

This document describes the system as it is, not as it might become. For the augmentation pipeline internals see [PIPELINE.md](PIPELINE.md). For the demo path and quickstart see [README.md](README.md).

![Pipeline](pipeline.png)

## Top-level layout

```
anamnesis/
  backend/             FastAPI + FastMCP server, augmentation pipeline, FHIR I/O
  frontend/            Next.js review workspace (thin client)
  benchmarks/          eval-corpus-v1 + augmentation benchmark runner
  data/demo_patient/   Synthetic patient bundle + four notes for offline demos
```

The backend is self-sufficient: any agent in the Prompt Opinion ecosystem can drive it through MCP without the frontend existing. The frontend is a reference consumer.

## End-to-end demo flow

1. A clinician (in Prompt Opinion) asks the agent to prepare a chart. The agent calls **`ProposeAugmentations`** over MCP. SHARP headers carry the FHIR base URL, an access token, and the patient ID.
2. The MCP tool creates a `PipelineRun` record, mints a review token, returns a deep link `/{runId}?token=…` immediately, and starts the pipeline as a background task.
3. The clinician opens the link. The review workspace shows live stage-by-stage progress (guardrail → extraction → deduplication → coding → reconciliation → assembly). The agent polls **`GetRunStatus`** and reports completion.
4. When the pipeline finishes, proposals appear in the workspace. The clinician reviews source notes, the chart slice, and accepts / edits / rejects each proposal.
5. The clinician walks into the visit. Mid-encounter, the agent uploads the live transcript text via **`ProposeAugmentationsFromNotes`** (a `list[str]` of raw bodies). The pipeline runs again — same stages, but on inline `Document` objects rather than `DocumentReference`s pulled from the chart. The transcript is **not** written to FHIR at this point.
6. On accept, `apply_augmentation` builds a single FHIR `transaction` Bundle: the resource (`Condition`, `Observation`, …), a `Provenance` with one entity per source document and one source-span extension per citation, and — for inline notes — a US Core `DocumentReference` bundling the source text. The chart only ever contains ratified evidence behind an approved finding.

## Backend

Lives under `backend/`. FastAPI app entrypoint at `backend/main.py` mounts the MCP server at the root and the REST API under `/api`. SQLite by default (`anamnesis.db`); pluggable via `DATABASE_URL`.

### MCP surface (`mcp_server/`)

`server.py` is a `FastMCP` instance that advertises a SHARP capability extension listing the FHIR scopes it needs (`patient/Patient.rs` required, plus read scopes for the resource types the pipeline reasons over). Tools are registered in `tools.py`:

| Tool | Job |
|---|---|
| `WhoIsPatient` | Returns identifying info for the SHARP-bound patient. |
| `GetPatientContext` | Counts of existing conditions, meds, allergies, observations, family history, procedures, encounters, documents. |
| `ProposeAugmentations` | Starts the pipeline asynchronously against the patient's chart-resident notes. Returns a deep link to the review UI immediately; the workspace shows live stage progress. |
| `ProposeAugmentationsFromNotes` | Runs the pipeline against agent-supplied note text (`list[str]`, ≤ 200KB each). Source documents are written to the chart only when a derived augmentation is accepted. |
| `GetRunStatus` | Returns the status of a pipeline run: stage progress if running, proposal summary if completed, error if failed. Used by the agent to poll after ProposeAugmentations. |
| `ListProposals` | Lists proposals for the current patient grouped by tier (ATTENTION / REVIEW / CONFIDENT). Each row carries display label, classification, score, status, flags, and a top citation snippet for in-chat triage. |
| `GetProposal` | Full detail for one proposal: FHIR resource JSON, resolved citations (with char spans), classification + extraction + merge reasoning, confidence breakdown, chart_matches, supersedes, and (if accepted) the Provenance resource and write_result. Lets an agent decide accept/reject/edit without the review UI. |
| `SearchTerminology` | Vector search over SNOMED, RxNorm, LOINC, or ICD-10. Returns ranked `{code, display, score}` for a free-text query. Useful before `EditProposal` to swap in a more appropriate code. Read-only; no FHIR side effects. |
| `AcceptProposal` | Accept a proposal; writes the FHIR resource + Provenance as a transaction Bundle. |
| `RejectProposal` | Archive a proposal with a reason; no FHIR write. |
| `ReopenProposal` | Return a previously rejected proposal to pending. Accepted proposals cannot be reopened (FHIR write is permanent); rejection history is preserved. |
| `EditProposal` | Edit the FHIR resource JSON of a pending proposal before accepting. Citations and provenance are preserved. |

### REST surface (`api/routes.py`, `api/chat_routes.py`)

The frontend talks to the backend over a small REST API:

- `GET /api/auth/check` — validate a review token and return the aliased clinician identity.
- `GET /api/runs` — list pipeline runs with status (including `running`), counts, total tokens, and USD cost.
- `GET /api/runs/{run_id}/progress` — stage-by-stage progress for a running pipeline (polled by the frontend every 2s).
- `GET /api/runs/{run_id}/chart` — patient context as fetched at run time, tagged with its source (FHIR snapshot, FHIR live, or local bundle).
- `GET /api/runs/{run_id}/documents` — source documents for a run (chart-resident or inline).
- `GET /api/proposals`, `GET /api/proposals/{id}` — list / fetch proposals.
- `POST /api/proposals/{id}/{accept|reject}`, `PUT /api/proposals/{id}` — write-side, gated on a valid review token.
- `POST /api/chat/{run_id}/stream` — SSE chat with proposal context for the in-product assistant.

### The pipeline (`core/`)

Six stages from chart load to clinician-reviewable proposal, plus an input guardrail before Stage 2 and a deterministic write-back stage on accept. Each stage is a pure function over typed Pydantic schemas; LLM calls are wrapped in telemetry. Two service-layer entry points compose the stages:

- `services.proposals.run_pipeline(patient_id, session, fhir_client)` — chart-only path. Loads `PatientContext` and chart `DocumentReference`s, then runs the stages.
- `services.proposals.run_pipeline_with_inline_notes(patient_id, raw_notes, session, …)` — inline path. Builds `Document`s directly from text via `_documents_from_notes` (id = `inline_<sha256[:12]>`, deterministic across re-uploads), then runs the same stages.

For per-stage detail (preprocess, extract, merge, code, reconcile, assemble, review, write-back), confidence scoring, and module layout, see [PIPELINE.md](PIPELINE.md).

### Persistence (`db/models.py`)

Four tables, all indexed for the access patterns the UI hits:

- **`PipelineRun`** — `id`, `patient_id`, `triggered_by` (`api`, `mcp`, `api:inline`), `status`, `started_at`, `finished_at`, `meta_json`.
- **`LLMCall`** — one row per LLM invocation: `run_id`, `stage`, `model`, token counts (input / output / reasoning / cached), `latency_ms`, `usd_cost`, error fields.
- **`ProposalRecord`** — one per proposal: `resource_type`, `classification`, `confidence_tier`, `confidence_score`, `status`, `resource_json`, `citations_json`, `metadata_json`, `conflict_group_id` (nullable; links proposals that contradict each other across notes), reviewer audit columns.
- **`ReviewToken`** — short opaque tokens (`rev_xxxxxxxx`) aliased to a clinician's display + FHIR reference, with expiry. The frontend never sees the underlying SHARP access token.

Per-run **snapshots** (`services/run_snapshot.py`) are written to `.cache/runs/{run_id}.json` so the review surface can render notes and chart context without round-tripping the FHIR server on every page load.

### FHIR I/O (`fhir/`)

- `fhir/client.py` — async `FhirClient(base_url, token)` with `read`, `search`, `transaction`.
- `fhir/read.py` — `read_patient_context` and `read_documents` build the typed `PatientContext` and `Document` shapes the pipeline consumes.
- `fhir/write.py` — the accept-time write path:
  - `Citation` carries `document_ref`, `start`, `end`, `text`, and optional `inline_document` (a `Document` to be minted as a US Core `DocumentReference`).
  - `apply_augmentation` dispatches by classification:
    - **NEW** — POST resource + POST Provenance.
    - **UPDATING** — read existing → PUT updated resource (carrying `versionId` for optimistic concurrency) + POST Provenance against the superseded reference.
    - **CONFLICTING** — POST a parallel new resource + POST Provenance. Does not retire the existing resource; the conflict is an annotation, not a unilateral correction.
  - `_resolve_inline_citations` mints one `DocumentReference` Bundle entry per unique inline document (US Core profile, LOINC `34109-9 Note` default, base64 inline content, `clinical-note` category, `Patient/{id}` subject, attester as `author`) and rewrites citation `document_ref`s to that entry's `urn:uuid:` so the standard provenance builder produces correct linkage.
  - `build_provenance` emits one `entity` per unique source plus one `source-text-span` extension per citation, recording the document ref, character offsets, and quoted text. Multi-citation proposals get multi-entity provenance — the UI uses these to highlight every corroborating note.

### Auth & SHARP (`context/`)

- `context/sharp.py` — extracts `FhirContext` (server URL + token), `patient_id`, and `ReviewerIdentity` from MCP request headers and the JWT inside the FHIR access token (read-only; signature trust is delegated to the agent platform that issued it).
- `context/auth.py` — `mint_review_token(identity)` produces a short opaque token backed by `ReviewToken`. `validate_review_token(token)` is the gate for write-side REST endpoints. The token is an alias of the clinician's Prompt Opinion session, not a credential we issue from scratch.

### Telemetry (`core/telemetry.py`)

A `RunContext` is established in a `ContextVar` at `start_run` and torn down at `finish_run`. Each LLM call goes through a wrapper that records model, token mix, latency, and computed USD cost (`core/pricing.py`) into both the `LLMCall` table and a JSONL file at `.cache/telemetry/{run_id}.jsonl`. The frontend surfaces total tokens, USD cost, and wall-clock duration per run alongside the proposal counts.

### Tests (`tests/`)

`test_e2e_pipeline.py` exercises the chart-only path against the demo bundle. `test_inline_notes_e2e.py` covers the agent-supplied path: deterministic `inline_*` IDs, snapshot round-trip, and that an accepted NEW proposal yields a transaction Bundle with a US Core `DocumentReference`, the resource, and a `Provenance` whose `entity[].what` references the just-minted `DocumentReference`'s `urn:uuid`. Stage- and unit-level tests live alongside (`test_extraction.py`, `test_preprocess.py`, `test_telemetry.py`, `test_auth.py`).

## Frontend

Next.js 16 (App Router, React 19, TypeScript), shadcn/ui on Radix + Tailwind. Dev port is `3042` to avoid colliding with other local projects.

### Layout

The workspace is a deep-link surface: `/{runId}?token=…`. Three panels, plus a header.

- **Header** (`components/layout/header.tsx`) — patient identity, run picker, auth chip, theme toggle.
- **Left rail** — collapses two panels by context:
  - `run-list-panel.tsx` — runs grouped by patient, with status, proposal counts, tokens, USD cost, and duration. Multi-select + bulk delete.
  - `proposal-list-panel.tsx` — proposals in the active run grouped by tier with classification badges and quick filters.
- **Center** (`proposal-detail-panel.tsx`) — the selected proposal: resource viewer, classification + confidence breakdown, citation list, conflict callouts (chart conflicts shown side-by-side with the proposed resource; inter-note conflicts shown side-by-side with the sibling proposal, linked for navigation), and the action row (Accept / Reject / Edit). Accepting a proposal in a conflict group auto-rejects its siblings. When the review token is missing or invalid, the action row turns into a destructive read-only banner with a tooltip explaining that writes need an alias of the clinician's Prompt Opinion session, with production-SSO honesty about the gap.
- **Right rail** (`right-panel.tsx`) — three tabs:
  - **Notes** — source documents, with cited spans highlighted in place by tier color.
  - **Chart** — the patient context slice the pipeline reconciled against (conditions, meds, allergies, observations, procedures, family history, encounters), tagged with its source label (`FHIR server`, `FHIR server snapshot`, or `Local bundle`) and fetch time.
  - **Chat** — streaming assistant that helps the clinician reason through a proposal's citations, conflicts, and reasoning. Empty state explains the assistant's role and surfaces the same auth gate.

`run-stats-strip.tsx` shows tokens, USD cost, and elapsed time per run; mobile collapses it into the proposal list header.

### Edit experience

`proposal-form-view.tsx` plus `components/ui/json-editor.tsx` (CodeMirror) gives clinicians an editable view of the FHIR resource before accepting. Citations and provenance are preserved across edits — only the resource body is mutable.

### State (`lib/store.ts`)

Single Zustand store with localStorage-persisted slices for `token` and the most recent `runId`. Hydration order:

1. Layout reads `token` from the URL → `setToken` → calls `api.checkAuth` → sets `tokenValid` (`true | false | null` for the verifying state).
2. `fetchRuns()` and `fetchProposals(runId)` populate the rails. Detail and right-panel data are fetched on selection.
3. Accept / reject / edit actions call the REST endpoints with `Authorization: Bearer {token}`; failures roll back optimistic UI.

### Auth gate

The frontend treats the review token as a binary access gate, not a per-action credential. Read endpoints (`/runs`, `/proposals`, `/documents`, `/chart`) are open; **write endpoints require a valid token**. When `tokenValid !== true`, the proposal panel shows a read-only banner and disables the action row, the chat tab shows a "Review token required" empty state, and a tooltip explains the model honestly: this surface is meant to be SSO-embedded in production; the short token is an alias of the clinician's Prompt Opinion session that keeps the demo deep-linkable.

## Contracts

The boundaries another consumer would need to reason about if they swapped the frontend, embedded the MCP elsewhere, or replaced the FHIR server.

- **MCP tool contract** — tool names, input schemas, output shapes, and required SHARP scopes are advertised by the `FastMCP` server in `mcp_server/server.py` and `tools.py`. Inputs and outputs are Pydantic models; the wire format is JSON over Streamable HTTP at `/mcp`.
- **REST contract** — paths, methods, and response shapes live in `api/routes.py` and `api/chat_routes.py`. The frontend depends only on these endpoints; there is no shared module between frontend and backend.
- **Review-token contract** — a `rev_xxxxxxxx` string passed as `Authorization: Bearer {token}`. It is an alias of the clinician's Prompt Opinion session (not a credential we mint from scratch) and is the only auth needed for write-side REST calls. The backend never exposes the underlying SHARP access token to the frontend.
- **FHIR write contract** — every accepted proposal becomes one transaction Bundle: the resource (`Condition` / `MedicationRequest` / `AllergyIntolerance` / `Observation` / `Procedure` / `FamilyMemberHistory`, US Core where a profile exists), a `Provenance` with one `entity` per source document and one `source-text-span` extension per citation, and — for inline notes — a US Core `DocumentReference`. UPDATING uses PUT with `versionId` for optimistic concurrency; CONFLICTING never retires the existing resource.
- **Source-of-truth contract** — clinical data lives on the FHIR server. The local SQLite holds working state only (runs, proposals, decisions, telemetry, review tokens). Wiping `anamnesis.db` loses history but never clinical data.

## Invariants

- **Nothing writes silently.** Every chart change passes through `apply_augmentation` and is paired with a `Provenance`. Inline source text only enters the chart when its derived augmentation is accepted, in the same transaction.
- **Every fact carries provenance.** Source span, classification, confidence breakdown, reviewer identity, and Provenance reference are persisted on every accepted proposal.
- **Contradictions are surfaced, not hidden.** Inter-note conflicts (same medication, contradictory actions across providers) are detected deterministically and grouped so the clinician must resolve them as a unit. Accepting one auto-rejects the others.
- **FHIR is the source of truth.** Local SQLite holds working state — runs, proposals, decisions, audit log, telemetry. Clinical data lives on the FHIR server.
- **The MCP is the product.** The frontend is a thin reference consumer; substituting it with another agent or UI does not change the contract.

## Out of scope

What Anamnesis intentionally is not, so reviewers don't ask "why didn't you…":

- **Not an EHR.** No order entry, no billing, no scheduling, no longitudinal patient app.
- **Not ambient capture.** Notes come from the FHIR server or are uploaded by the calling agent. The system does not record audio or transcribe live encounters.
- **Not a payer / coding-revenue tool.** The terminology coding exists to enable reconciliation against an existing chart, not to maximize billing codes.
- **Not multi-tenant.** A single FHIR server per session, scoped by SHARP context. No tenant routing layer.
- **Not a SHARP token issuer.** The agent platform issues SHARP access tokens; the backend reads the JWT for identity but does not validate the signature. Trust is delegated to the issuing platform.
- **Not a clinical decision-support system.** Proposals are evidence the clinician reviews; the system never recommends a diagnosis or therapy.
