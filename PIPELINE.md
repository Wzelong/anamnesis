# Anamnesis Augmentation Pipeline

The deep-dive on how a clinical note becomes a clinician-reviewable, provenance-stamped FHIR write. Every stage is a pure function over typed Pydantic schemas; LLM calls are wrapped in telemetry; nothing here is demo-specific.

For the system shape (MCP surface, REST API, frontend, persistence) see [ARCHITECTURE.md](ARCHITECTURE.md). For benchmarked accuracy see [benchmarks/eval-corpus-v1/](benchmarks/eval-corpus-v1/).

![Pipeline](pipeline.png)

```
 FHIR server (or uploaded docs)                            FHIR server
     │                                                         ▲
     │ DocumentReference + existing chart          Resource + Provenance
     ▼                                                         │
 ┌───────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐  ┌─────────┐  ┌──────────┐  ┌────────┐
 │ Load  │─▶│ Preproc. │─▶│ Extract  │─▶│ Cross-note │─▶│Reconcile│─▶│ Assemble │─▶│ Review │
 │ chart │  │          │  │          │  │   dedupe   │  │ vs chart│  │ proposal │  │ + write│
 └───────┘  └──────────┘  └──────────┘  └────────────┘  └─────────┘  └──────────┘  └────────┘
   fhir/       core/         core/          core/          core/        core/       services/
   read.py   preprocess.py  extraction.py  extraction.py  reconcile.py augment.py   + fhir/
   local_                                                 + code_                    write.py
   bundle.py                                              candidates.py
```

## Stage 0 — Chart load (`backend/fhir/read.py`, `backend/fhir/local_bundle.py`)

Pulls the inputs the pipeline reasons over.

- `read_patient_context(fhir, patient_id)` → `PatientContext`: existing structured chart (Condition, MedicationRequest, AllergyIntolerance, Observation, FamilyMemberHistory, Procedure, Encounter).
- `read_documents(fhir, patient_id)` → `list[Document]`: DocumentReferences with decoded note text, encounter_id, and date metadata.
- `local_bundle.load_demo_data(path)` → same types from a local Bundle JSON, used for offline dev, tests, and the demo path that needs no FHIR server.

Each `Document` carries `encounter_id` extracted from `DocumentReference.context.encounter[0]`. When absent (uploaded docs with no FHIR link), downstream stages fall back to note date as the encounter grouping key.

Output is the only ground truth the pipeline uses. Nothing else re-reads FHIR until Stage 8.

## Stage 0.5 — Input guardrail (`backend/core/doc_guardrails.py`)

Per-document gate that runs *before* the expensive Stage 2 spend. Two-tier: deterministic checks first (free, instant), then a parallel `gpt-5.4-nano` semantic classification with `reasoning.effort="none"`. All notes screen concurrently via `asyncio.gather`.

**Why here.** Stage 2 fans out 1 + N parse calls per note; a single bad input costs real money. The gate filters obvious garbage, non-clinical text, and prompt-injection attempts before that fan-out begins.

**Deterministic checks** (`deterministic_check`):

| Check | Threshold | Catches |
|---|---|---|
| Empty / whitespace-only | non-whitespace required | empty uploads |
| Byte size | ≤ 256 KB | defense-in-depth above the 200 KB inline cap |
| Printable-char ratio | ≥ 0.85 | binary blobs, base64 mistakenly handed in as text |

**LLM check.** Single call per surviving doc. Structured output (`GuardrailVerdict`) classifies as one of `clinical | empty | non_clinical_text | binary_or_garbage | prompt_injection | other`. The system prompt is intentionally permissive on formatting — messy dictation, partial notes, and shorthand are all `clinical`. Verified 25/25 against the eval corpus + 6 synthetic noise samples (real notes including `pt 58F, c/o cp x 2d. trop neg…` accepted; news, code, base64, prompt-injection, empty all rejected).

**Failure model:**

- Per-doc rejection, never per-run. One bad note doesn't kill the run.
- API failure → fail-open (doc is accepted, rejection telemetry records the error).
- Result persisted on `PipelineRun.meta_json["guardrail"] = {"accepted": N, "rejected": [{document_id, reason, category, detail}]}` so the review UI can badge skipped docs.

**Cost & latency** (gpt-5.4-nano, `effort="none"`):

- Per-call: ~1087 input tokens, ~73 output tokens, p50 ~1.5s, p95 ~2.5s.
- Per-call cost: ~$0.0003 — trivially cheap.
- 25 docs in parallel: 2.6s wall-clock.

**Caching.** Hash `(model, prompt_version, sha256(text))`. Re-runs of the same note (retries, demo bundle in tests) hit the cache and skip the API call entirely.

**Telemetry.** Recorded as `stage="stage0"` / `call_type="doc_guardrail"` on `LLMCall`, so guardrail spend rolls up in the standard run summary alongside the other stages.

Disable via `DOC_GUARDRAIL_ENABLED=false` in `.env` if needed.

## Stage 1 — Preprocess (`backend/core/preprocess.py`)

Per note, deterministic, no I/O.

- Rule-based sentence split tuned for clinical text (titles, frequencies like `b.i.d`, decimals, inline list markers, section headers).
- Build a `numbered_note` where every sentence is prefixed `[N]` — this number is the universal address used by every downstream LLM call.
- Each `SentenceSpan` records `(number, start_char, end_char, text)` with exact byte offsets in the original note for provenance.
- `encounter_id` passes through from Document to `PreprocessedNote`.

`NoteContext` (note_date, admission_date, discharge_date) is extracted by the scanner in Stage 2, not in Stage 1.

Singleton extraction (Patient/Encounter/etc.) is intentionally skipped — Anamnesis already has them from SHARP context and `DocumentReference.context`.

## Stage 2 — Extract candidates (`backend/core/extraction.py`)

Scan → parse → clean, per note, all notes in parallel via `asyncio.gather`. Model: `gpt-5.4-mini` with `reasoning.effort="low"`.

1. **Scan.** One LLM call per note classifies which sentence numbers hold clinical content. Output is sentence-number groups per resource type (Condition, Observation, MedicationRequest, Procedure, AllergyIntolerance, FamilyMemberHistory). Routing priority rules prevent cross-type leakage (allergies → AllergyIntolerance only, family history → FamilyMemberHistory only, tobacco → Observation only).
2. **Parse.** One LLM call per sentence group per resource type, all concurrent within a note. Produces Pydantic structured outputs. Each candidate carries `source_sentences`, `reasoning`, and `certainty` (definite / probable / uncertain — how assertively the source text states the fact).
3. **Clean.** One LLM call per resource type (within-note only) removes junk and de-duplicates near-identical candidates.

Parser prompts accept `NoteContext` so "started yesterday" becomes a real ISO date. Prompts enforce strict exclusion rules: no pertinent negatives in Observations, no generic drug names in MedicationRequests, no ruled-out conditions, no billing-code duplicates.

Output: `list[StageTwoOutput]` — one per note, each carrying `document_id`, `encounter_id`, `note_context`, and `candidates` grouped by resource type. Cached by `(note_hash, model, prompt_version)`.

## Stage 3 — Cross-note dedupe (`backend/core/extraction.py::merge_across_notes`)

Merges duplicate candidates across notes into single items with multi-document `source_refs`. Encounter-scoped: patient-level resources dedupe globally, encounter-level resources dedupe only within the same encounter.

**Resource scoping:**

| Scope | Types | Rationale |
|-------|-------|-----------|
| Patient-level | Condition, MedicationRequest, AllergyIntolerance, FamilyMemberHistory | Chart state — "hypertension" is one fact regardless of which visit mentions it |
| Encounter-level | Observation, Procedure | Measurements and events — BP from cardio ≠ BP from neuro |

**Encounter key derivation:** `encounter_id` (from DocumentReference) → note date (YYYY-MM-DD) → document_id (last resort). Two notes on the same day with no encounter_id are assumed to be the same encounter.

**Two-phase algorithm:**

1. **Deterministic exact-match merge** (zero LLM calls). Tag items with `(resource_type, encounter_key, normalized_name, value/dose)`. Normalize: lowercase, strip clinical-irrelevant prefixes (essential, chronic, acute, mild, moderate, severe, minor). Group by key. Multi-doc exact matches merge deterministically — pick the most complete item as survivor, union all SourceRefs.

2. **LLM adjudication** for fuzzy near-duplicates within the same scope. All calls run in parallel via `asyncio.gather`:
   - 1 call for patient-level ambiguous groups (e.g. "coronary artery disease" vs "two-vessel coronary artery disease")
   - 1 call per encounter for encounter-level ambiguous groups (if any)

   Model: `gpt-5.4-mini`, `reasoning.effort="low"`. The LLM returns merge / reassign / keep decisions with reasoning. Unconsumed groups pass through as singletons.

**Output:** `StageThreeOutput` — a flat list of `MergedCandidate`, each with:
- `resource_type`, `item` (dict), `source_refs` (multi-doc provenance)
- `encounter_key` (for encounter-level items, None for patient-level)
- `merge_reasoning` (audit trail)

## Stage 4 — Terminology coding (`backend/core/coding.py`, `backend/core/code_candidates.py`)

FAISS vector search + LLM CodeSelector + US Core fixed-code short-circuits. Model: `gpt-5.4-mini` with `reasoning.effort="low"`.

**Infrastructure:** Pre-computed SapBERT embeddings (dim 768) stored in four FAISS indexes under `data/indexes/`:

| System | Rows | Index type |
|--------|------|------------|
| SNOMED | 527K | IndexIVFPQ |
| RxNorm | 449K | IndexIVFPQ |
| LOINC | 95K | IndexFlatIP |
| ICD-10 | 23K | IndexFlatIP |

Indexes and the embedding model load lazily on first use, and backend startup runs `core.coding.warmup()` by default and blocks until the model and all indexes are ready. Disable with `WARMUP_CODING_ON_STARTUP=false`. `EmbeddingModel` and `IndexStore` are thread-safe singletons in `core/coding.py`.

**Per candidate flow:**

1. **US Core short-circuit.** Observations matching known vital signs or smoking status get fixed LOINC codes instantly — no vector search, no LLM call. BP → 85354-9, tobacco → 72166-2, body weight → 29463-7, etc.
2. **Cache check** by `(PROMPT_VERSION, normalized_term, code_system)`. Hits return immediately.
3. **Vector search** top-10 via FAISS inner product (cosine on unit vectors).
4. **LLM CodeSelector** picks the best code from the candidate list, or returns a `refined_search_term` for retry. Max 1 refinement retry.
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

All candidates processed in parallel via `asyncio.gather`. Cached by `(term, code_system)` so re-runs are free.

Output: `StageFourOutput` — same `MergedCandidate` list with `coding` field injected into each item dict. Structure mirrors FHIR `CodeableConcept.coding[]`: `[{system, code, display}]`.

## Stage 5 — Reconcile vs existing chart (`backend/core/reconcile.py`)

The augmentation brain. This is the capability text2fhir does *not* have.

**Two-tier approach:** deterministic code match first (no LLM), then LLM adjudication only for ambiguous cases where codes differ but display text overlaps. Typically 0–2 LLM calls per run.

**Per-resource-type matching:**

| Resource | Strategy | Example |
|----------|----------|---------|
| Condition | exact (system, code) match → DUPLICATE; display overlap → LLM | HTN ICD-10 I10 match → DUPLICATE |
| MedicationRequest | exact RxNorm → DUPLICATE; ingredient substring + dose compare → UPDATING | lisinopril 10→20 mg |
| AllergyIntolerance | specific allergy vs NKDA (409137002) → CONFLICTING | penicillin vs NKDA |
| Observation | LOINC match + tobacco-status normalization → UPDATING if value changed | smoking current→former |
| Procedure | SNOMED code + date match → DUPLICATE; different date → NEW |  |
| FamilyMemberHistory | relationship code + condition code match |  |

**LLM batching by resource type.** Ambiguous candidates grouped by type, one LLM call per type (max 6, typically 0–1), all in parallel via `asyncio.gather`. Model: `gpt-5.4-mini`, `reasoning.effort="low"`.

**Output:** `StageFiveOutput` — `list[ReconciliationResult]`, each wrapping the original `MergedCandidate` + `classification` (NEW / DUPLICATE / UPDATING / CONFLICTING) + `reasoning` + `chart_matches` (refs to matched existing resources) + `confidence_breakdown` (see [Confidence scoring](#confidence-scoring) below).

For benchmarked classification accuracy by class (NEW / DUPLICATE / UPDATING / CONFLICTING) see [benchmarks/eval-corpus-v1/results/](benchmarks/eval-corpus-v1/results/).

## Stage 6 — Assemble proposal (`backend/core/augment.py`)

Pure deterministic transform — no LLM calls, no I/O. Converts `StageFiveOutput` into clinician-reviewable `Proposal` records with valid FHIR R4 resource JSON and character-level source citations.

**Three jobs:**

1. **Filter.** Drop DUPLICATEs (already in chart). Only NEW / UPDATING / CONFLICTING reach the review surface.
2. **Build FHIR resources.** One builder per resource type, emitting plain dicts that conform to US Core R4. Key mapping: `item["coding"]` → `CodeableConcept.coding[]`, `item["name"]` → `CodeableConcept.text`. Special handling for BP (component-based), tobacco (valueCodeableConcept), and onset age parsing for FamilyMemberHistory.
3. **Resolve citations.** Sentence numbers → character spans via `PreprocessedNote.sentences`. Contiguous sentences merge into one `ResolvedCitation`; non-contiguous produce multiple.

**Per-type assembly:**

| Type | Code field | Subject field | Profile |
|------|-----------|--------------|---------|
| Condition | `code` | `subject` | us-core-condition-problems-health-concerns |
| Observation | `code` | `subject` | varies by category (vital-signs, lab, smokingstatus) |
| MedicationRequest | `medicationCodeableConcept` | `subject` | us-core-medicationrequest |
| Procedure | `code` | `subject` | us-core-procedure |
| AllergyIntolerance | `code` | `patient` | us-core-allergyintolerance |
| FamilyMemberHistory | `relationship` | `patient` | (none) |

**certainty → verificationStatus:** `definite` → confirmed, `probable` → provisional, `uncertain` → unconfirmed (Condition + AllergyIntolerance).

**Output:** `Proposal` schema carrying:
- `resource` (valid FHIR R4 dict), `resource_type`, `classification`
- `citations` (list of `ResolvedCitation` with document_id, char_start/end, text)
- `confidence_score`, `confidence_tier`, `flags` (carried from Stage 5)
- `supersedes` (UPDATING), `chart_matches` (any classification with chart hits)
- `classification_reasoning`, `extraction_reasoning`, `merge_reasoning`

No FHIR write happens here. The resource JSON is pre-assembled and valid but sits in the working DB (via `ProposalRecord` ORM model) until a clinician acts.

## Stage 7 — Review hand-off (`backend/services/proposals.py`)

The pipeline's terminal stage from the augmentation engine's perspective: persist proposals, mint a review token, return a deep link. The interactive review (MCP tools, REST endpoints, frontend) is documented in [ARCHITECTURE.md](ARCHITECTURE.md).

What this stage emits:

- One `ProposalRecord` per Stage-6 `Proposal`, with `resource_json`, `citations_json`, `classification`, `confidence_tier`, `confidence_score`, and audit columns.
- One `PipelineRun` row aggregating status, timing, token totals, and triggering surface (`api`, `mcp`, `api:inline`).
- One run snapshot at `.cache/runs/{run_id}.json` so the review surface can render notes and chart context without re-fetching FHIR.
- One `ReviewToken` (short opaque `rev_xxxxxxxx`) aliased to the clinician's identity, returned in the deep link.

**Pipeline caching:** if pending proposals already exist for a patient, the service returns them without re-running. Avoids redundant ~25s pipeline executions.

## Stage 8 — Write-back (`backend/fhir/write.py`)

On accept, `apply_augmentation(client, proposal)` writes to the FHIR server atomically (transaction Bundle) with full multi-citation Provenance.

**Three classification flows:**

| Classification | FHIR operation | Provenance activity | Behavior |
|---|---|---|---|
| NEW | POST resource + POST Provenance | CREATE | New resource added to chart |
| UPDATING | PUT to existing ref + POST Provenance | UPDATE | Replaces existing resource (e.g., dose change) |
| CONFLICTING | POST resource + POST Provenance | CREATE | New resource created; existing NOT retired (separate clinical decision) |

**Multi-citation Provenance:** each source document gets its own `entity` entry. Each citation span gets its own `source-text-span` extension with `documentRef`, `start`, `end`, `text`. A condition corroborated by 3 notes produces 3 extension entries and up to 3 entity entries (deduplicated by document).

**UPDATING flow:** reads the existing resource to get its `id` and `versionId`, merges the proposal's resource, PUTs to the same reference. The `supersedes_ref` from Stage 5 reconciliation provides the target.

**Inline note minting:** when a citation references an inline `Document` (no FHIR `DocumentReference` yet), `_resolve_inline_citations` mints one US Core `DocumentReference` per unique inline document into the same transaction Bundle (LOINC `34109-9 Note` default, base64 inline content, `clinical-note` category, `Patient/{id}` subject, attester as `author`) and rewrites the citation's `document_ref` to that entry's `urn:uuid:` so Provenance points at it correctly. Inline source text only enters the chart when its derived augmentation is accepted, in the same transaction.

**Write result:** `WriteResult(resource_ref, provenance_ref, superseded_ref)` returned to the service layer, stored in the proposal audit trail.

Rejections and edits are audited in the working DB — every decision is recoverable.

---

## Module layout

```
backend/core/
  doc_guardrails.py   # Stage 0.5: deterministic + nano-LLM input gate
  preprocess.py       # sentence splitter + NoteContext extractor
  extraction.py       # scan → parse → clean → cross-note merge
  coding.py           # FAISS index store + SapBERT embedding model
  code_candidates.py  # US Core fixed codes + LLM CodeSelector
  reconcile.py        # deterministic match + LLM adjudication → NEW/DUPLICATE/UPDATING/CONFLICTING
  augment.py          # FHIR builders + citation resolution → Proposal assembly
  telemetry.py        # RunContext + LLM call wrapper (token + cost accounting)
  pricing.py          # per-model token pricing for USD cost computation

backend/services/
  proposals.py        # proposal lifecycle: run pipeline, list, accept, reject, edit

backend/fhir/
  client.py           # async FhirClient (read, search, transaction)
  read.py             # PatientContext + Document loaders
  write.py            # apply_augmentation: NEW/UPDATING/CONFLICTING write paths
  local_bundle.py     # offline Bundle loader for demo + tests
```

---

## Confidence scoring

Every `ReconciliationResult` carries three confidence outputs:

- `confidence_score: float` — 0.0–1.0, used for sort order
- `confidence_tier: CONFIDENT | REVIEW | ATTENTION` — UI display tier
- `flags: list[str]` — human-readable reasons the clinician can verify

### Why not LLM confidence scores?

LLMs are poorly calibrated at self-reported numeric confidence. They say 0.85 whether they're right or wrong. Instead, we use one LLM **label** at extraction time (`certainty: definite | probable | uncertain` — the LLM *is* good at categorical language classification) and combine it with four **deterministic signals** from downstream stages that are more trustworthy.

### Five factors

| # | Factor | Weight | Source | Signal |
|---|--------|--------|--------|--------|
| 1 | Source evidence | 0.25 | Stage 3 | How many notes corroborate this fact (1→0.4, 2→0.7, 3+→1.0) |
| 2 | Extraction certainty | 0.20 | Stage 2 | LLM label (definite→1.0, probable→0.6, uncertain→0.2) |
| 3 | Coding quality | 0.25 | Stage 4 | Real terminology codes vs text-only fallback; multi-system bonus |
| 4 | Reconciliation match | 0.20 | Stage 5 | Match type quality (exact_code > ingredient > display_text) |
| 5 | Classification override | 0.10 | Stage 5 | Type penalty (CONFLICTING→0.0, ensures double-zero with factor 4) |

**Source evidence** is the strongest signal: a fact in 3 independent notes is almost certainly real. **Coding quality** is next: if FAISS can't find a match from 1M+ terminology concepts, either the extraction is wrong or the concept is unusual. **Certainty** at 0.20 gives the LLM a voice without letting it dominate — if 3 notes mention something with real SNOMED codes, an "uncertain" label shouldn't override that.

### Tier thresholds

```
CONFLICTING → ATTENTION  (hard override, no exceptions)
composite ≥ 0.70 → CONFIDENT
composite ≥ 0.40 → REVIEW
composite < 0.40 → ATTENTION
```

CONFLICTING always forces ATTENTION regardless of score. This is a safety invariant — a clinical contradiction must never be auto-approved.

### Flags (what clinicians actually see)

The tier tells the clinician *how much attention* to pay. The flags tell them *where to look*. Each flag is derived from the same signals:

- Source: "Mentioned in 3 notes" / "Single mention"
- Certainty: "Stated assertively in source" / "Source language is uncertain"
- Coding: "Coded in 2 systems (icd-10-cm, sct)" / "No terminology code found — verify manually"
- Classification: "Already in chart" / "Conflicts with: No known drug allergy" / "Updates existing: dose 10→20"
- Match: "Approximate match — verify"

---

## Design invariants

- **Sentence numbers are the universal address.** Every LLM call references sentences by `[N]`; source spans are derived from `sentence_positions`.
- **Two-tier model routing.** Cheap model for scan/parse/clean; stronger model reserved for ambiguous reconciliation calls. Configurable per call.
- **Pluggable terminology + embeddings.** No vendor endpoint is hardcoded.
- **Cache by `(note_hash, resource_type)` and `(term, code_system)`.** Dev re-runs are free; production gets idempotency for retries.
- **Provenance is non-negotiable.** A proposal without `source_refs` is a bug; a write without a `Provenance` resource is a bug.
- **Nothing writes silently.** Stages 0–7 never touch the FHIR server; only Stage 8 does, and only on explicit accept.
