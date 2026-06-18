# Anamnesis — Demo Guide

## What Anamnesis is

Anamnesis is a **FHIR augmentation agent**. It reads unstructured clinical notes
against an existing FHIR record, proposes structured additions and corrections
with full source provenance, and — only after a clinician approves — writes them
back to the FHIR server as valid R4 resources with a `Provenance` trail.

> The data wasn't missing — it was unstructured. Now it's not.

The name is the medical term for a patient history reconstructed from
documentation, which is exactly what the agent does.

It ships as an **MCP server** on the Prompt Opinion (PO) marketplace, with a thin
**React review workspace** delivered as an MCP App (the human-in-the-loop
surface). The MCP is the product; the UI is a reference consumer. Any agent in
the PO ecosystem can compose the same tools.

**Demo persona:** a provider doing pre-visit chart catch-up across multi-source
notes (cardiology consult, external ER visit, neurology follow-up). Not a payer
tool, not a patient app, not an EHR replacement, not ambient capture.

## The pipeline (high level)

A note becomes a clinician-reviewable, provenance-stamped FHIR write through a
chain of pure functions over typed schemas. Full detail in
[PIPELINE.md](PIPELINE.md); the demo-level view:

| Stage | What it does |
|---|---|
| **0 — Load** | Pull the existing chart + clinical documents (FHIR, or a local bundle for the offline demo). |
| **0.5 — Guardrail** | Cheap per-document gate (deterministic checks + `nano` LLM) drops garbage, non-clinical text, and prompt-injection before the expensive fan-out. |
| **1 — Preprocess** | Split each note into numbered sentences `[N]` — the universal address every downstream call cites. |
| **2 — Extract** | Scan → parse → clean. Find clinical facts, emit typed candidates with `source_sentences`, `reasoning`, `certainty`. |
| **3 — Merge** | Dedupe candidates across notes into single facts with multi-document provenance. |
| **4 — Code** | Attach terminology codes (SNOMED / RxNorm / LOINC / ICD-10) via vector search + an LLM CodeSelector, with US Core fixed-code short-circuits. |
| **5 — Reconcile** | Classify each fact against the existing chart: **NEW / DUPLICATE / UPDATING / CONFLICTING**. This is the augmentation brain. |
| **6 — Assemble** | Build valid FHIR R4 resources, resolve sentence numbers → character spans, detect cross-note conflicts, score confidence. |
| **7 — Review** | Hand proposals to the clinician (the React workspace). Nothing has touched FHIR yet. |
| **8 — Write-back** | On **accept only**, write the resource + a multi-citation `Provenance` to FHIR atomically. |

Core principles: **structure first, reason second, act third**; **every fact
carries provenance**; **nothing writes silently**.

## The recent shift: stateless MCP app

We collapsed a stateful backend (its own working DB of runs, proposals, audit,
telemetry) into a **near-stateless MCP server**. The organizing contract is
**no-PHI-at-rest**.

**Design goals**

- **No PHI persisted.** FHIR is the only durable clinical store. The pipeline
  runs in memory; extracted clinical data never touches disk.
- **Horizontally scalable, no sticky sessions.** A follow-up call (e.g. accept)
  may land on a different worker, so the React app re-supplies the full proposal
  payload on accept. An in-process TTL cache (`services/session_cache.py`, 1h) is
  a best-effort optimization — a miss is normal, never an error.
- **Identity is a pure function of the request.** We mint no tokens and store no
  tokens. Every per-request fact (FHIR client, patient, clinician, tenant) is
  derived from the SHARP headers PO sends.
- **The backend stays self-sufficient.** Any consumer can drive the MCP without
  our UI existing.

**What this removed:** `PipelineRun`, `DecisionAudit`, and `LLMCall` tables are
gone. Telemetry is now JSONL + an in-memory buffer; decisions are a structured
log line (clinician free-text reason is deliberately *not* logged). Per-run
stats come from the live telemetry buffer, not a DB.

**What persists:** exactly one table — `app_user` (per-clinician identity +
framework config). Not patient data; configuration only.

## Deployment: Render + Neon

- **Compute — Render.** A single Python web service (`render.yaml`) runs the
  FastMCP v3 server (`python po_main.py`, serving `/mcp` and a `/healthz`
  probe). `RENDER_EXTERNAL_URL` is auto-injected and used as the public origin
  for the MCP App's JS/CSS assets (PO's iframe is sandboxed, so assets load over
  an absolute URL). Secrets (`OPENAI_API_KEY`, `UMLS_API_KEY`, `DATABASE_URL`)
  are unsynced env vars.
- **State — Neon (Postgres).** `DATABASE_URL` points at Neon over `asyncpg`.
  Two Neon-specific choices: `NullPool` (a fresh connection per use — avoids the
  asyncpg cross-event-loop error and defers pooling to Neon's server-side
  pgBouncer), and `timestamptz` for every timestamp column. Schema is one table;
  `init_db()` creates it idempotently on startup.

```
PO host ──SHARP headers──▶ Render (FastMCP /mcp) ──▶ Neon (app_user only)
   │                              │
   └──── OAuth / token ───────────┘────────▶ PO FHIR server (the source of truth)
```

## Auth

PO is the **host and the authorization server**; Anamnesis is a pure **OAuth 2.1
resource server**. PO authenticates the clinician, mints the token, and
propagates launch context as SHARP HTTP headers on every `/mcp` call:

| Header | Contents |
|---|---|
| `x-fhir-server-url` | the patient's FHIR base |
| `x-fhir-access-token` | the PO-issued JWT (bearer for FHIR + identity claims) |
| `x-patient-id` | the patient in context |

**Identity.** `sub` is the clinician's stable OIDC subject — the per-user key.
(Confirmed a real user token: `is_client_creds=false`, `role=User`, no `fhirUser`
claim, so `sub` is what we key on.) `po_ws_id` is the workspace/tenant.

**Trust tiers** — verification is proportional to risk:

| Operation | Trust model |
|---|---|
| Read FHIR (PHI passthrough) | host-delegated — a forged token self-fails at the FHIR server, so PHI is self-protecting |
| Read non-secret config | host-delegated |
| **Write config / any secret (BYOK)** | **token verified** — JWKS signature + `iss` + `exp`. Keying a write to an unverified `sub` is forgeable. |

**Verification** (`context/token_verify.py`): PO publishes a JWKS
(one RS256 key). We verify signature + `iss` + `exp` against the cached keys via
`PyJWKClient`. PO issues **no `aud` claim**, so audience binding is optional via
a `po_mcp_id` pseudo-audience check when configured. Verification lives in our
token-reading path (not FastMCP's `Authorization`-header auth gate) because PO
sends the token in `x-fhir-access-token`. Full findings in [AUTH.md](AUTH.md).

## Configuration

Per-clinician config is the `app_user.config` JSONB blob, keyed on `sub`. It
persists across sessions (the header chip shows "returning clinician, session
#N"). Every knob ships with a working default, so an unconfigured clinician gets
a sensible US-Core run out of the box. Setting any config value requires a
**verified** token (see Auth).

### Out-of-the-box default

```jsonc
{
  "byok": {
    "gemini_api_key": null,         // falls back to the server key
    "umls_api_key": null,
    "model_fast": "gemini-3.5-flash",  // scan / parse / merge / code / reconcile
    "model_smart": "gemini-3.5-flash"  // reserved for hard adjudication
  },
  "prompts": {
    "overrides": {}                // stage prompt id -> replacement text
  },
  "fhir_ig": "us-core-6.1.0",      // implementation guide to validate against
  "resources": {
    "enabled": [                   // resourceTypes the pipeline may propose
      "Condition", "Observation", "MedicationRequest",
      "AllergyIntolerance", "Procedure", "FamilyMemberHistory"
    ],
    "extensions": []               // extra IG extensions to emit on writes
  },
  "coding": {
    "systems": {                   // resourceType -> terminology systems
      "Condition": ["snomed", "icd10"],
      "Observation": ["loinc", "snomed"],
      "MedicationRequest": ["rxnorm"],
      "Procedure": ["snomed"],
      "AllergyIntolerance": ["snomed"],
      "FamilyMemberHistory": ["snomed"]
    },
    "subset": null,                // optional value-set allowlist (codes/OIDs)
    "overrides": {}                // term -> fixed code, clinician-curated
  }
}
```

### What each section controls

- **BYOK (bring your own key).** A clinician/workspace supplies its own Gemini
  (and UMLS) key and model choices instead of the shared server key — the path
  to per-tenant billing and isolation. Asking for a Gemini key is low-friction:
  PO already has the clinician provide one to run the chat, so it is expected
  UX (PO does not propagate that key to us, so we still collect our own).
  **These are the secrets** that make token verification on config writes
  non-negotiable; they are encrypted at rest, decrypted in-process only, and
  never sent to the iframe. *Default:* the shared server key, `gemini-3.5-flash`.

- **Prompt playground + tuning.** Each pipeline stage's system prompt is
  addressable by id; an override replaces it for that clinician's runs. Lets an
  informaticist tune extraction/reconciliation language to a specialty without a
  code change, and A/B a prompt against the eval corpus. *Default:* the shipped
  prompts under `core/prompts/`.

- **FHIR IG selection.** Which implementation guide proposals validate and
  profile against. *Default:* US Core 6.1.0. Roadmap targets: mCODE (oncology),
  other regional/specialty IGs — selectable per workspace.

- **FHIR resource customization.** Which `resourceType`s the pipeline is allowed
  to propose, and which IG **extensions** to emit on write. A workspace that only
  wants problems + meds narrows `enabled`; one with local extensions adds them
  here. *Default:* the six core types above, no extra extensions.

- **Medical code mapping / subset / customization.** Per-resource terminology
  **systems** (e.g. Condition → SNOMED + ICD-10 dual coding), an optional value-set
  **subset** that constrains coding to an approved allowlist, and clinician
  **overrides** that pin a term to a chosen code (which the pipeline must honor —
  this is why Stage 4 has no silent term cache). *Default:* the standard US Core
  system routing, no subset, no overrides.

> **Honesty note:** the schema above is the target config contract and its
> defaults. **Done:** verified read/write gating, BYOK secret encryption at rest
> (`core/byok.py`, Fernet via `CONFIG_SECRET_KEY`), redaction on read (the iframe
> sees `{set, last4}`, never plaintext), and the pipeline consuming a clinician's
> BYOK Gemini key when set. **Still staged:** the IG / resource / coding override
> wiring into the pipeline (today it runs the defaults).

## Demo flow

1. Open the deep link from PO → `ReviewChart` seeds the patient header and the
   recognition chip (new vs returning clinician, session #N).
2. `RunExtraction` runs Stages 0.5–6 in memory, streaming stage progress; the
   review queue fills with NEW / UPDATING / CONFLICTING proposals, each showing
   the highlighted source span, the FHIR resource, classification, confidence
   tier, and any chart conflict.
3. Accept a proposal → it writes to FHIR with a visible multi-citation
   `Provenance`. Reject/edit are audited as non-PHI decisions.

The thesis lands when a fact mentioned in three notes shows up coded, reconciled
against the existing chart, and written back with all three citations attached.
