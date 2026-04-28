# Anamnesis Augmentation Pipeline

End-to-end flow from clinical notes on the FHIR server to clinician-reviewed,
provenance-stamped writes back to FHIR. Every stage is implemented as a module
under `backend/core/` (plus `backend/fhir/` for I/O). The pipeline is designed
to be reusable by any MCP consumer — nothing here is demo-specific.

```
 FHIR server                                              FHIR server
     │                                                         ▲
     │ DocumentReference + existing chart          Resource + Provenance
     ▼                                                         │
 ┌───────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐  ┌───────────┐  ┌─────────┐  ┌──────────┐  ┌────────┐
 │ Load  │─▶│ Preproc. │─▶│ Extract  │─▶│ Cross-note │─▶│ Terminology│─▶│ Classify│─▶│ Assemble │─▶│ Review │
 │ chart │  │          │  │          │  │   dedupe   │  │   coding   │  │         │  │ proposal │  │ + write│
 └───────┘  └──────────┘  └──────────┘  └────────────┘  └───────────┘  └─────────┘  └──────────┘  └────────┘
   fhir/       core/         core/          core/          core/         core/        core/       api/ +
   read.py   preprocess.py  extraction.py  extraction.py  terminology.py classifier.py augment.py fhir/write.py
                                                         + coding.py
```

## Stage 0 — Chart load (`fhir/read.py`, already built)

Pulls the inputs the pipeline reasons over.

- `read_patient_context(fhir, patient_id)` → existing structured chart
  (Condition, MedicationRequest, AllergyIntolerance, Observation,
  FamilyMemberHistory, Procedure).
- `read_documents(fhir, patient_id)` → DocumentReference list with attached
  note text and encounter/date metadata.

Output is the only ground truth the pipeline uses. Nothing else re-reads FHIR
until Stage 7.

## Stage 1 — Preprocess (`core/preprocess.py`)

Per note, in parallel.

- Rule-based sentence split tuned for clinical text (titles, frequencies like
  `b.i.d`, decimals, inline list markers, section headers).
- Build a `numbered_note` where every sentence is prefixed `[N]` — this number
  becomes the universal address used by every downstream LLM call.
- Compute `sentence_positions`: `[N] → (start_char, end_char)` in the original
  note. Used later to resolve source spans for provenance.
- One LLM call extracts `NoteContext`: `note_date`, `admission_date`,
  `discharge_date`. These anchors let later stages resolve relative dates
  ("yesterday", "on discharge").

Singleton extraction (Patient/Encounter/etc.) is intentionally skipped —
Anamnesis already has them from SHARP context and `DocumentReference.context`.

## Stage 2 — Extract candidates (`core/extraction.py`)

Scan → parse → clean, per note, in parallel. Adapted from text2fhir, trimmed.

1. **Scan.** A single LLM call classifies which sentence numbers hold
   clinical findings / interventions / planning content. Output is
   sentence-number groups per target resource type (Condition, Observation,
   MedicationRequest, Procedure, AllergyIntolerance, FamilyMemberHistory,
   Goal, ServiceRequest).
2. **Parse.** One LLM call per sentence group, per resource type, producing
   Pydantic structured outputs. Each candidate carries its `source_sentences`
   and a short `reasoning` field (why the model thinks this is a Condition,
   not just text).
3. **Clean.** One LLM call per resource type removes junk and de-duplicates
   near-identical candidates within the note.

Parser prompts accept `NoteContext` so "started yesterday" becomes a real
ISO date and carries a `_field_source` tag pointing back at the sentence that
introduced the relative reference.

## Stage 3 — Cross-note dedupe (`core/extraction.py::merge_across_notes`)

Candidates from different notes for the same fact are merged into a single
candidate with multiple `source_refs` (one per `(DocumentReference, sentence
span)` pair). Cross-type duplicates — e.g. "hypertension" extracted as both a
Condition and an Observation — are collapsed using a light LLM arbitration
call that picks the preferred FHIR type given the context.

## Stage 4 — Terminology coding (`core/terminology.py`, `core/coding.py`)

The smartest piece ported from text2fhir, generalized.

- `TerminologyClient` interface with pluggable providers:
  - Prompt Opinion terminology service (if available at runtime)
  - NLM Clinical Tables / RxNav (public, default fallback)
  - Local Typesense + preloaded ValueSets (optional self-host)
  - Pure-LLM code emission (last resort, stronger model, schema-validated)
- Embedding backend is also pluggable: SapBERT from HuggingFace by default,
  overridable via config. Loaded lazily — never at import — so MCP cold start
  stays fast.
- `RESOURCE_CODE_SYSTEMS` is config, not a Python literal
  (`Condition → SNOMED + ICD-10`, `MedicationRequest → RxNorm`, `Observation
  → LOINC`, …).

Per candidate:

1. Embed `item.name` (and any synonyms the parser proposed), search top-k in
   the chosen code systems.
2. LLM `CodeSelector` receives the term, its sentence context, and the
   candidate list. It either picks a `conceptId` or emits a `refined_query`.
3. Loop up to a small refinement budget (default 2). Cache by
   `(term, code_system)` so re-runs are free.
4. If every backend fails, fall back to the pure-LLM code path.

IG adapters (`core/profiles/`) may short-circuit with a fixed code (e.g. the
US Core BP panel pins LOINC 85354-9 without searching).

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
  preprocess.py    # sentence splitter + NoteContext extractor
  extraction.py    # scan → parse → clean → cross-note merge
  terminology.py   # TerminologyClient interface + providers + cache
  coding.py        # vector-search + LLM CodeSelector + fallback
  diff.py          # retrieve-similar strategies per resource type
  classifier.py    # NEW / UPDATING / CONFLICTING / DUPLICATE
  augment.py       # assemble AugmentationProposal
  profiles/        # IG adapters (US Core 6.1.0)
    base.py
    us_core/       # BP, smoking status, med-req, condition, allergy, fam-hx
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
