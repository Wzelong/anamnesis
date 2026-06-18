# Direction

Where Anamnesis is headed: from a hackathon submission to a **stable, open-source
configurable clinical-extraction framework** that the Prompt Opinion (PO) team can
adopt and maintain. This doc is the design spec for that framework — the v1 scope is
**decided** (see the decisions table); items under "Open decisions" are not.

For the system as it stands today see [Architecture.md](Architecture.md) and
[PIPELINE.md](PIPELINE.md); for auth see [AUTH.md](AUTH.md); for the config surface as
demoed see [DEMO.md](DEMO.md).

## Goal

Anamnesis stops being *a* FHIR-augmentation tool and becomes **a configurable
extraction framework**: a strong general pipeline that each deployment shapes to its
use case. Better open-source story, cleaner hand-off, no head-to-head with point tools.
The framework — not the demo — is the product. Every knob is a clean, general
extension point; nothing patient-specific is hard-coded.

## Already shipped (foundation)

These were "planned" in earlier drafts and are now done:

- **Stateless, no PHI at rest.** Pipeline runs in memory; the durable clinical store is
  FHIR (resource + `Provenance`). The only persisted state is per-clinician config.
- **PO-native auth.** Identity is the SHARP token `sub`; `verify_po_token()` checks the
  JWKS signature + `iss` + `exp` and gates per-user config writes (`context/token_verify.py`).
- **BYOK, encrypted.** Secret fields in `app_user.config` are Fernet-encrypted at rest,
  decrypted in-process only, redacted (`{set,last4}`) to the iframe (`core/byok.py`).
- **In-host review via MCP App.** The review UI ships as a standard MCP App served by the
  backend and rendered in PO's iframe (`mcp-app/`), no separate deploy.
- **Gemini LLM stack.** `gemini-3.5-flash` (guardrail on `gemini-3.1-flash-lite`) via the
  single `core/llm.py` wrapper. BYOK is **required** — the pipeline runs on the clinician's
  key, never a shared one.

## The framework: IG is the spine, not a peer

The five config dimensions are **not** equal picks. Four of them are *layers over the
chosen IG*; one is orthogonal account/usage.

```
   ACCOUNT & USAGE   (BYOK key · run stats · spend)     ← orthogonal, non-clinical
   ───────────────────────────────────────────────
   USER OVERRIDES    (thin, declarative, app_user.config)
     · resource include/exclude + custom extensions      (dim 3)
     · coding system map + value-set subsets              (dim 4)
     · prompt overrides + test notes + versions           (dim 5)
   ───────────────────────────────────────────────
   SPECIALTY IG   (mCODE…)   dependsOn ↓                 ← developer module
   BASE IG        (US Core, always present)              ← developer module
```

**Why IGs layer (not compete):** in real FHIR, mCODE *depends on* US Core — its profiles
derive from US Core profiles (mCODE `CancerPatient` = US Core `Patient` + one must-support
element), so any US Core resource also satisfies the mCODE base, and mCODE is itself
designed as a base for further IGs. IGs declare typed `dependsOn` (package + version) and
implementations may conform to several at once when compatible. So picking mCODE *implies*
US Core; they stack additively rather than conflict.
Sources: [mCODE conformance](https://build.fhir.org/ig/HL7/fhir-mCODE-ig/conformance-general.html),
[FHIR ImplementationGuide](https://hl7.org/fhir/R4/implementationguide.html).

## v1 decisions

| # | Question | Decision (v1) |
|---|---|---|
| Q1 | IG stacking | **Base + at most one specialty IG** (deps auto-resolved). Ship **US Core (full) + mCODE**. No sibling-merge/conflict logic yet; manifest designed to allow it later. |
| Q2 | Config ownership | **Per-clinician** (`sub`). Schema keyed so a future workspace (`po_ws_id`) policy layer can be added without migration. |
| Q3 | Presets | **Single active preset**; a user may create multiple but only one is active at a time. No per-patient context-binding yet. |
| Q4 | Custom extensions | **Declarative + LLM-assisted** (option B). User declares an extension structurally → deterministic FHIR field generation + an LLM-*drafted* extraction-prompt fragment the user reviews. |
| Q5 | Prompt tuning | **User-owned, versioned overrides**; tune against uploaded test notes. **No write-back** into the canonical IG module. |
| Q6 | Run stats | **A small non-PHI usage ledger** (per-run + cumulative spend). Justified re-introduction of persistence; pure billing metadata, no clinical content. |

## Data model

### `app_user.config` (per clinician, keyed on `sub`)

```jsonc
{
  "byok": { "gemini_api_key": <encrypted>, "umls_api_key": <encrypted|null> },
  "active_preset_id": "preset_xxx",
  "presets": [ Preset, ... ]            // Q3: many allowed, one active
}
```

### `Preset` — the user-facing bundle (avoids the FHIR word "profile")

```jsonc
{
  "id": "preset_xxx",
  "name": "Oncology",
  "ig": { "base": "us-core@6.1.0", "specialty": "mcode@4.0.0" | null },  // Q1
  "resources": { "<ResourceType>": { "enabled": true } },               // dim 3 toggles over IG default
  "extensions": [ UserExtension, ... ],                                  // dim 3 (Q4)
  "coding":   { "<ResourceType>": { "systems": ["snomed","icd10"],      // dim 4
                                    "subset": <valueSetRef | codes | null> } },
  "prompts":  { "<resourceType|stage>": { "version": 3,                 // dim 5 (Q5)
                                          "override_text": "...",
                                          "test_notes_ref": "..." } },
  "model": { "fast": "gemini-3.5-flash", "smart": "gemini-3.5-flash" }   // optional per-preset
}
```

### `UserExtension` — declarative, LLM-assisted (Q4)

```jsonc
{
  "id": "ext_eye_color",
  "name": "Eye color",
  "attach_to": "Patient",                 // resourceType / profile the extension hangs on
  "url": "<generated canonical>",
  "datatype": "CodeableConcept",          // code | string | CodeableConcept | Quantity | boolean | ...
  "binding": { "valueSet": "...", "codes": [...] } | null,
  "prompt_fragment": { "text": "<LLM-drafted, human-approved>", "version": 1 }
}
```
Flow: user supplies (name, attach-point, datatype, optional binding) → **deterministic**
generation of the `resource.extension[]` shape in the builder → the LLM **drafts** the
extraction-prompt fragment, which the user reviews/edits before it goes live. Declarative
spec in, deterministic FHIR out, LLM only writes prose.

### IG module — the developer extension surface (the hand-off deliverable)

A declarative manifest + assets, authored in the repo (not by end users):

```jsonc
IGModule {
  "id": "mcode", "version": "4.0.0", "title": "...",
  "dependsOn": ["us-core@6.1.0"],
  "resources": {
    "<ResourceType>": {
      "profiles": ["<canonical>"],
      "inclusion": "required" | "supported" | "optional",
      "coding": { "systems": [...], "valueSets": [...] },   // binding defaults
      "extensions": [ ... ],
      "extraction_prompt": "<ref>"                          // dedicated prompt / fragment
    }
  }
}
```

### Usage ledger (Q6) — non-PHI

```sql
usage_run(
  id, user_key,            -- sub; NO patient id, NO clinical content
  workspace_id, ts,
  model, input_tokens, output_tokens, reasoning_tokens,
  cost_usd, duration_ms, doc_count
)
```
Populated from the existing in-memory telemetry buffer at run end (run-level aggregate
only — never the per-call `document_id`). Powers the "Account & usage" pane: this run's
duration/tokens/cost **and** cumulative/monthly spend, so a BYOK clinician can see what
their key is being charged.

## Effective Profile: resolution → pipeline

1. **Resolve.** Active preset → base IG + specialty IG → resolve `dependsOn` → merge
   manifests (specialty constrains/extends base; specialty-only resources are added;
   base-only remain) → apply preset user-overrides last (toggles, extensions, coding
   subsets, prompt overrides). Result: an **Effective Profile**.
2. **Thread it through the stages:**

| Stage | What the Effective Profile drives |
|---|---|
| 0.5 / 2 (extract) | which resourceTypes to scan; the IG's per-type extraction prompt + user fragments + user overrides |
| 4 (code) | coding systems per resourceType; value-set **subset** constrains/validates candidates |
| 6 (assemble) | builders stamp the IG profile URLs; emit IG + user-declared extensions |
| 8 / validate | (planned) `$validate` accepted resources against the IG profiles |

Unconfigured clinicians get the shipped defaults (US Core, standard system routing, base
prompts) — the override layers are all optional.

## Authoring a new IG (developer workflow)

The OSS extension point. To add an IG:

1. Write the **manifest** (`dependsOn`, resources, profiles, coding bindings, extensions).
2. Provide **extraction prompts** per resourceType (or inherit the base IG's).
3. Register **builders** for any new resourceTypes/profiles the base doesn't cover.
4. Load the IG's **StructureDefinitions + ValueSets** into the terminology/validation
   server so `$expand` / `$validate-code` / `$validate` resolve against it.

End users never touch this; they pick the IG by name.

## Supporting infrastructure (enables the framework)

- **FHIR `$validate` (HAPI).** Resources are currently hand-built dicts asserted to conform
  but never validated against a real validator. Add a `$validate` call before write —
  closes a real gap, honors the project convention ("do not hand-roll resource validation"),
  and is the same infra that makes IG + coding-subset enforcement one feature, not three:
  **load the IG into a HAPI/terminology server** and let it drive `$validate`, `$expand`,
  `$validate-code`.
- **Terminology retrieval: live APIs + LLM search terms.** Make the local FAISS indexes
  pluggable behind the `Retriever` seam; default to live authoritative APIs + an LLM step
  that emits *terminology-phrased* query variants. Built and benchmarked (appendix). Variant
  emission is the decisive lever and must be adopted regardless of retriever.

## Appendix: terminology retrieval benchmark

Built as a drop-in behind a `Retriever` seam (`core/retrieval.py`) with an LLM search-term
step (`core/code_search_terms.py`), measured against `benchmarks/eval-corpus-v1/`.

**API landscape** — no single API covers all systems; `ApiRetriever` is a best-of-breed router:

| System | Backend | Notes |
|---|---|---|
| SNOMED | UMLS UTS | API key; cross-vocab synonymy (CAD → "Coronary arteriosclerosis") |
| RxNorm | RxNav `approximateTerm` | Genuinely fuzzy; tolerates dose/route noise |
| ICD-10 | NLM Clinical Tables | Needs `sf=code,name` |
| LOINC | NLM Clinical Tables | UMLS LOINC search returns Parts/HEDIS artifacts — worse |

**Retrieval recall on realistic (messy) spans, n=95** (concept-level scoring):

| Retriever | raw span | **+ variants** |
|---|---|---|
| Live API | 8.4% | **80.0%** |
| FAISS | 44.2% | **88.4%** |

Per system (with variants): SNOMED 72.5/85.0 · ICD-10 92.3/100 · RxNorm 90.5/95.2 · LOINC 50/50 (API/FAISS).

**Findings:**
1. **Variant emission is the decisive lever — adopt unconditionally.** Mandatory for the API
   (8→80%), large lift for FAISS (44→88%). Variants must be *terminology-phrased*
   (`HFrEF` → "systolic heart failure"), not acronym expansions.
2. **API + variants trails FAISS + variants by ~8 pts**, concentrated in SNOMED — partly a
   scoring artifact (FAISS returns the deprecated code the eval holds; the API returns the
   current code, self-correcting the staleness that motivated the change).
3. **The end-to-end exact-code benchmark is inconclusive by construction** (both ~30–35%);
   the gap is granularity choice by the *selector*, retriever-independent. Do not quote an
   end-to-end code-accuracy figure until re-scored with granularity tolerance.

**Status:** API + variants is the defensible default for the lightweight/hand-off goals
(zero index hosting, instant startup, always-current codes) — a goal-weighted judgment, not
a pure accuracy win. Keep FAISS as a non-default adapter until a trustworthy end-to-end
number exists.

## Open decisions

- **Sibling specialty IGs** (two specialties over one base) and their conflict resolution —
  deferred past v1; manifest is designed to allow it.
- **Workspace-level governance** (`po_ws_id` policy over clinician overrides) — schema-ready,
  not built in v1.
- **Per-patient/encounter preset binding** (auto-select preset from context) — v2 idea.
- **Drop FAISS entirely vs keep as a pluggable non-default adapter** — pending a sound
  end-to-end metric.
- **Promotion of user-tuned prompts back into IG modules** — out of scope (Q5: no write-back);
  could become a contribution workflow later.
- License and commercial terms of the hand-off — out of scope for this doc.
