# Anamnesis Augmentation Pipeline

End-to-end flow from clinical notes on the FHIR server to clinician-reviewed,
provenance-stamped writes back to FHIR. Every stage is implemented as a module
under `backend/core/` (plus `backend/fhir/` for I/O). The pipeline is designed
to be reusable by any MCP consumer — nothing here is demo-specific.

```
 FHIR server (or uploaded docs)                            FHIR server
     │                                                         ▲
     │ DocumentReference + existing chart          Resource + Provenance
     ▼                                                         │
 ┌───────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐  ┌─────────┐  ┌──────────┐  ┌────────┐
 │ Load  │─▶│ Preproc. │─▶│ Extract  │─▶│ Cross-note │─▶│Classify │─▶│ Assemble │─▶│ Review │
 │ chart │  │          │  │          │  │   dedupe   │  │ vs chart│  │ proposal │  │ + write│
 └───────┘  └──────────┘  └──────────┘  └────────────┘  └─────────┘  └──────────┘  └────────┘
   fhir/       core/         core/          core/          core/        core/       api/ +
   read.py   preprocess.py  extraction.py  extraction.py  classifier.py augment.py fhir/write.py
   local_                                                 + diff.py
   bundle.py
```

Stages 5-6 in the diagram above correspond to the original stages 5-6 in
the numbered list below.

## Stage 0 — Chart load (`fhir/read.py` or `fhir/local_bundle.py`) ✅

Pulls the inputs the pipeline reasons over.

- `read_patient_context(fhir, patient_id)` → `PatientContext`: existing
  structured chart (Condition, MedicationRequest, AllergyIntolerance,
  Observation, FamilyMemberHistory, Procedure, Encounter).
- `read_documents(fhir, patient_id)` → `list[Document]`: DocumentReference
  list with decoded note text, encounter_id, and date metadata.
- `local_bundle.load_demo_data()` → same types from a local bundle JSON,
  used for offline dev and testing without a FHIR server.

Each `Document` carries `encounter_id` extracted from
`DocumentReference.context.encounter[0]`. When absent (uploaded docs with no
FHIR link), downstream stages fall back to note date as encounter grouping key.

Output is the only ground truth the pipeline uses. Nothing else re-reads FHIR
until Stage 7.

## Stage 1 — Preprocess (`core/preprocess.py`) ✅

Per note, deterministic, no I/O.

- Rule-based sentence split tuned for clinical text (titles, frequencies like
  `b.i.d`, decimals, inline list markers, section headers).
- Build a `numbered_note` where every sentence is prefixed `[N]` — this number
  becomes the universal address used by every downstream LLM call.
- Each `SentenceSpan` records `(number, start_char, end_char, text)` with
  exact byte offsets in the original note for provenance.
- `encounter_id` passes through from Document to `PreprocessedNote`.

`NoteContext` (note_date, admission_date, discharge_date) is extracted by the
scanner in Stage 2, not in Stage 1.

Singleton extraction (Patient/Encounter/etc.) is intentionally skipped —
Anamnesis already has them from SHARP context and `DocumentReference.context`.

## Stage 2 — Extract candidates (`core/extraction.py`) ✅

Scan → parse → clean, per note, all notes in parallel via `asyncio.gather`.
Model: `gpt-5.4-mini` with `reasoning.effort="low"`.

1. **Scan.** One LLM call per note classifies which sentence numbers hold
   clinical content. Output is sentence-number groups per resource type
   (Condition, Observation, MedicationRequest, Procedure, AllergyIntolerance,
   FamilyMemberHistory). Routing priority rules prevent cross-type leakage
   (allergies → AllergyIntolerance only, family history → FamilyMemberHistory
   only, tobacco → Observation only).
2. **Parse.** One LLM call per sentence group per resource type, all
   concurrent within a note. Produces Pydantic structured outputs. Each
   candidate carries `source_sentences` and `reasoning`.
3. **Clean.** One LLM call per resource type (within-note only) removes junk
   and de-duplicates near-identical candidates.

Parser prompts accept `NoteContext` so "started yesterday" becomes a real
ISO date. Prompts enforce strict exclusion rules: no pertinent negatives in
Observations, no generic drug names in MedicationRequests, no ruled-out
conditions, no billing-code duplicates.

Output: `list[StageTwoOutput]` — one per note, each carrying `document_id`,
`encounter_id`, `note_context`, and `candidates` grouped by resource type.
Cached by `(note_hash, model, prompt_version)`.

## Stage 3 — Cross-note dedupe (`core/extraction.py::merge_across_notes`) ✅

Merges duplicate candidates across notes into single items with multi-document
`source_refs`. Encounter-scoped: patient-level resources dedupe globally,
encounter-level resources dedupe only within the same encounter.

**Resource scoping:**

| Scope | Types | Rationale |
|-------|-------|-----------|
| Patient-level | Condition, MedicationRequest, AllergyIntolerance, FamilyMemberHistory | Chart state — "hypertension" is one fact regardless of which visit mentions it |
| Encounter-level | Observation, Procedure | Measurements and events — BP from cardio ≠ BP from neuro |

**Encounter key derivation:** `encounter_id` (from DocumentReference) → note
date (YYYY-MM-DD) → document_id (last resort). Two notes on the same day with
no encounter_id are assumed to be the same encounter.

**Two-phase algorithm:**

1. **Deterministic exact-match merge** (zero LLM calls). Tag items with
   `(resource_type, encounter_key, normalized_name, value/dose)`. Normalize:
   lowercase, strip clinical-irrelevant prefixes (essential, chronic, acute,
   mild, moderate, severe, minor). Group by key. Multi-doc exact matches
   merge deterministically — pick the most complete item as survivor, union
   all SourceRefs.

2. **LLM adjudication** for fuzzy near-duplicates within the same scope.
   All calls run in parallel via `asyncio.gather`:
   - 1 call for patient-level ambiguous groups (e.g. "coronary artery
     disease" vs "two-vessel coronary artery disease")
   - 1 call per encounter for encounter-level ambiguous groups (if any)
   
   Model: `gpt-5.4-mini`, `reasoning.effort="low"`. The LLM returns
   merge/reassign/keep decisions with reasoning. Unconsumed groups pass
   through as singletons.

**Output:** `StageThreeOutput` — a flat list of `MergedCandidate`, each with:
- `resource_type`, `item` (dict), `source_refs` (multi-doc provenance)
- `encounter_key` (for encounter-level items, None for patient-level)
- `merge_reasoning` (audit trail)

## Stage 4 — Terminology coding (`core/coding.py`, `core/code_candidates.py`) ✅

FAISS vector search + LLM CodeSelector + US Core fixed-code short-circuits.
Model: `gpt-5.4-mini` with `reasoning.effort="low"`.

**Infrastructure:** Pre-computed SapBERT embeddings (dim 768) stored in
four FAISS indexes under `data/indexes/`:

| System | Rows | Index type |
|--------|------|------------|
| SNOMED | 527K | IndexIVFPQ |
| RxNorm | 449K | IndexIVFPQ |
| LOINC | 95K | IndexFlatIP |
| ICD-10 | 23K | IndexFlatIP |

Indexes and embedding model load lazily on first use. `EmbeddingModel` and
`IndexStore` are thread-safe singletons in `core/coding.py`.

**Per candidate flow:**

1. **US Core short-circuit.** Observations matching known vital signs or
   smoking status get fixed LOINC codes instantly — no vector search, no LLM
   call. BP → 85354-9, tobacco → 72166-2, body weight → 29463-7, etc.
2. **Cache check** by `(PROMPT_VERSION, normalized_term, code_system)`.
   Hits return immediately.
3. **Vector search** top-10 via FAISS inner product (cosine on unit vectors).
4. **LLM CodeSelector** picks the best code from the candidate list, or
   returns a `refined_search_term` for retry. Max 1 refinement retry.
5. **Fallback:** text-only coding `[{"text": term}]` if all attempts fail.

**Resource → code system routing:**

| Resource type | Systems | Notes |
|---|---|---|
| Condition | SNOMED + ICD-10 | Dual coding, both in parallel |
| Observation | LOINC or SNOMED | Routed by `codeset_hint` from parser |
| MedicationRequest | RxNorm | |
| Procedure | SNOMED | |
| AllergyIntolerance | SNOMED | |
| FamilyMemberHistory | SNOMED | Each condition coded separately |

All candidates processed in parallel via `asyncio.gather`. Cached by
`(term, code_system)` so re-runs are free.

Output: `StageFourOutput` — same `MergedCandidate` list with `coding`
field injected into each item dict. Structure mirrors FHIR
`CodeableConcept.coding[]`: `[{system, code, display}]`.

## Stage 5 — Classify vs existing chart (`core/classifier.py`, `core/diff.py`)

The augmentation brain. This is the capability text2fhir does *not* have.

For each coded candidate:

1. **Retrieve similar existing resources** from the chart loaded in Stage 0
   using a per-resource-type strategy declared alongside the profile:
   - `Condition` — exact code match, then SNOMED/ICD parent-child, then
     SapBERT similarity over `code.text`.
   - `MedicationRequest` — match by RxNorm ingredient (same drug, different
     dose → UPDATING).
   - `AllergyIntolerance` — match by substance RxNorm.
   - `Observation` — match by LOINC + effective date window.
2. **LLM classify** (stronger model) → `NEW | UPDATING | CONFLICTING |
   DUPLICATE`, with `reasoning` and `conflict_refs[]`.
3. Route:
   - `DUPLICATE` → drop.
   - `UPDATING` → emit with `priorPrescription` / `supersedes` references.
   - `CONFLICTING` → emit and flag for clinician adjudication.
   - `NEW` → emit plain.

## Stage 6 — Assemble proposal (`core/augment.py`)

Builds the `AugmentationProposal` record persisted to the working DB
(`backend/db/`). One row per proposal:

```
AugmentationProposal {
  resource:                 # FHIR JSON built by core/profiles adapters
  classification:           NEW | UPDATING | CONFLICTING
  classification_reasoning: str
  source_refs: [            # one entry per citation
    { document_ref, sentence_range, char_span }
  ]
  extraction_reasoning:     str          # from parser
  coding_reasoning:         str | None   # from CodeSelector
  confidence: float         # composite: extract × code-match × classifier
  conflicts_with: [ref]     # if CONFLICTING
  supersedes:    [ref]      # if UPDATING
  status: pending
}
```

No FHIR write happens here. The resource JSON is pre-assembled and valid but
sits in the working DB until a clinician acts.

## Stage 7 — Review (`api/routes.py`, `mcp_server/tools.py`)

The human-in-the-loop surface, exposed two ways:

- **MCP tools** — `propose_augmentations`, `list_proposals`,
  `accept_proposal`, `reject_proposal`, `edit_proposal`. Any Prompt Opinion
  agent can drive the flow.
- **REST API** — same surface, consumed by the frontend review workspace.

This stage runs the pipeline on demand and returns the queue; it does not
itself do extraction.

## Stage 8 — Write-back (`fhir/write.py`, already built)

On accept, `apply_augmentation(client, proposal)`:

1. POST the resource to FHIR (US Core R4).
2. POST a `Provenance` resource pointing at the written resource, with the
   `source-span` extension recording each `(DocumentReference, char range)`
   citation and the approver's identity.
3. Append a row to the audit log (working DB) with the tool call payload,
   timestamps, and outcome.

Rejections and edits are audited too — every decision is recoverable.

---

## Module layout (target)

```
backend/core/
  preprocess.py       # sentence splitter + NoteContext extractor
  extraction.py       # scan → parse → clean → cross-note merge
  coding.py           # FAISS index store + SapBERT embedding model
  code_candidates.py  # US Core fixed codes + LLM CodeSelector + cache
  diff.py             # retrieve-similar strategies per resource type
  classifier.py       # NEW / UPDATING / CONFLICTING / DUPLICATE
  augment.py          # assemble AugmentationProposal
```

## Design invariants

- **Sentence numbers are the universal address.** Every LLM call references
  sentences by `[N]`; source spans are derived from `sentence_positions`.
- **Two-tier model routing.** Cheap model for scan/parse/clean; stronger
  model for `CodeSelector` and the classifier. Configurable per call.
- **Pluggable terminology + embeddings.** No vendor endpoint is hardcoded.
- **Cache by `(note_hash, resource_type)` and `(term, code_system)`.** Dev
  re-runs are free; production gets idempotency for retries.
- **Provenance is non-negotiable.** A proposal without `source_refs` is a
  bug; a write without a `Provenance` resource is a bug.
- **Nothing writes silently.** Stages 0–6 never touch the FHIR server; only
  Stage 8 does, and only on explicit accept.
