# Direction

Where Anamnesis is headed after the hackathon, the changes under consideration, and the evidence behind them. This is a working document — decisions here are proposals unless marked otherwise. For the system as it stands today see [Architecture.md](Architecture.md) and [PIPELINE.md](PIPELINE.md).

## Goal

Take Anamnesis from a hackathon submission to a **stable, polished, open-source framework** that the Prompt Opinion team can adopt, run in their marketplace, and continue to maintain. The intent is a clean hand-off: the framework should be self-explanatory, well-tested, and lightweight enough that a team that didn't build it can own it.

The reframe that follows from this: Anamnesis stops being *a* FHIR-augmentation tool and becomes **a configurable clinical-extraction framework**. Ship a strong general pipeline; let each deployment shape it to their use case. That is a better open-source story and avoids competing head-to-head with similar point tools.

## Planned changes

### 1. Stateless + Prompt Opinion-native auth

Today the backend persists working state (proposals, run snapshots, review tokens) in SQLite and authenticates the review UI with a self-minted `rev_` token. Target: **persist no patient data on the MCP server.** Configuration is not patient data and may still be stored.

The path:
- Run the pipeline synchronously (or let the host hold run state) so per-run persistence is unnecessary.
- Move review into the host (see MCP Apps below) so proposals live in the session, not our DB.
- Write audit/provenance to **FHIR** (`Provenance` resources, which we already emit on accept) rather than a local audit table.
- Delegate auth fully to Prompt Opinion's SHARP/SMART flow — verify the JWT against their JWKS or formally rely on host-delegated trust — and drop our own token minting.

What remains on disk is read-only infrastructure (e.g. a terminology index, if kept), which does not violate "no patient data persisted."

### 2. In-host review via MCP Apps

Replace the separate Next.js deep-link workspace with an **MCP App**: the same tool that runs the pipeline returns an interactive review UI that the host renders inline, with a message bridge back to the MCP tools. This removes a separate deploy, the deep link, and the review-token table, and lets auth flow from the host session. (MCP Apps was an evolving part of the spec as of early 2026 — confirm the current host-side contract with Prompt Opinion before committing.)

### 3. Configurable Extraction Profile

A single config object (proposed name: **Extraction Profile**) that overrides the shipped defaults and drives the pipeline. Axes, ordered by tractability:

| Axis | Effort | Notes |
|---|---|---|
| **Prompt-tuning loop** | Low–Med | Productize the existing eval corpus + benchmark runner: upload sample notes, edit extraction rules, validate results. Highest leverage; the engine already exists. |
| **BYOK model** | Med | Bring-your-own model + key. Requires decoupling from the hard-wired OpenAI client (structured output differs across providers). |
| **Code constraints** | Med | Restrict to a codeset, a subset, or custom codes. Lean on FHIR `$expand`/`$validate-code` for the "allowed values" layer. |
| **FHIR IG** | High | Ship US Core; allow swapping in another IG. Demo target: **mCODE for oncology**. Full IG support consumes StructureDefinitions + ValueSets. |
| **Resources + extensions** | High | Config-driven resource/extension set. Reliable extension generation from free text is genuinely hard. |

**Architectural unifier:** the IG + validation + value-set-binding cluster collapses into one infrastructure choice — **load the IG into a HAPI/terminology server** and let it drive `$validate`, `$expand`, and `$validate-code`. "Configure mCODE," "constrain codes," and "validate resources" then become one feature, not three.

### 4. Terminology retrieval: live APIs + LLM search terms

Replace (or make pluggable) the local FAISS vector indexes with **live authoritative terminology APIs**, and add an LLM step that emits terminology-style search queries to drive retrieval. Motivation: the pre-built indexes are large, must be rebuilt on each terminology release, can go stale, and force a heavy startup. This is the one change we have **built and benchmarked** — results below.

### 5. FHIR validation (HAPI `$validate`)

Today resources are hand-built dicts asserted to conform to US Core but never validated against a real FHIR validator (the only `validate` calls are Pydantic). Add a `$validate` call against a HAPI server before write. This closes a real gap, aligns with the project's own convention ("do not hand-roll resource validation"), and composes with the IG work in change 3.

---

## Results: terminology retrieval (change 4)

The only change investigated so far. Built as drop-in, behind a `Retriever` seam, and measured against the eval corpus.

### What was built

- `backend/core/retrieval.py` — a `Retriever` interface with two implementations returning the same `SearchResult` shape Stage 4 consumes: `FaissRetriever` (current default) and `ApiRetriever` (a per-system router).
- `backend/core/code_search_terms.py` + `backend/core/prompts/search_terms.py` — an LLM step that turns a messy clinical entity into terminology-style search queries.
- Benchmarks under `benchmarks/eval-corpus-v1/`: `bench_retrieval.py` (recall, display queries), `bench_retrieval_variants.py` (recall, realistic spans ± variants), `bench_codeselect.py` (end-to-end code accuracy).
- `backend/scripts/exp_live_terminology.py` — endpoint probes.

Not yet wired into the live pipeline — `code_candidates.py` still calls FAISS directly. `UMLS_API_KEY` is read from config/`.env`.

### API landscape

No single API covers all systems; the `ApiRetriever` is a best-of-breed router:

| System | Backend | Notes |
|---|---|---|
| SNOMED | UMLS UTS | Requires an API key. Cross-vocabulary synonymy (CAD → "Coronary arteriosclerosis"). |
| RxNorm | RxNav `approximateTerm` | Genuinely fuzzy; tolerates dose/route noise. |
| ICD-10 | NLM Clinical Tables | Needs `sf=code,name` or it returns nothing for clinical phrasing. |
| LOINC | NLM Clinical Tables | UMLS LOINC search returns Parts/HEDIS artifacts — worse. |

### Benchmark: retrieval recall on realistic (messy) clinical spans, n=95

Scored at the concept level (expected code **or** a candidate whose display matches the concept, so legacy→current code swaps are not counted as misses).

| Retriever | raw span | **+ variants** |
|---|---|---|
| Live API | 8.4% | **80.0%** |
| FAISS | 44.2% | **88.4%** |

Per system, with variants:

| System | API | FAISS |
|---|---|---|
| SNOMED | 72.5% | 85.0% |
| ICD-10 | 92.3% | 100% |
| RxNorm | 90.5% | 95.2% |
| LOINC | 50% | 50% |

### Findings

1. **Variant emission is the decisive lever — adopt it regardless of retriever.** It is mandatory for the API (8% → 80%) and a large lift for FAISS (44% → 88%). Variants must be *terminology-phrased* (e.g. `HFrEF` → "systolic heart failure"), not just acronym expansions — a query worded like the note misses; a query worded like the terminology hits.
2. **API + variants is viable but trails FAISS + variants by ~8 pts on retrieval**, concentrated in SNOMED. Part of even that gap is a scoring artifact: FAISS returns the exact code it indexed, while the eval reference holds *deprecated* SNOMED codes (e.g. essential hypertension `155296003`) and the API returns the *current* code (`59621000`). The API self-corrects the staleness that motivated this change in the first place.
3. **The end-to-end exact-code benchmark is inconclusive by construction.** Both retrievers score ~30–35%, not because retrieval failed (the right code is usually in candidates) but because labels carry one code at one granularity while the selector picks defensible *different* granularities (ingredient vs clinical drug; specific vs unspecified). That error is the selector's job and is retriever-independent, so it cannot separate the two. The pipeline's published ~90% is *classification* accuracy, a different metric. **Do not quote an end-to-end code-accuracy figure until this benchmark is re-scored with granularity tolerance.**

### Recommendation & status

- **Adopt variant emission unconditionally.** Highest leverage, helps either retriever, validated.
- **Keep the `Retriever` seam.** Cheap, and avoids a one-way door.
- **API + variants is a defensible *default* for the stateless/lightweight/hand-off goals** — trading ~8 pts of retrieval recall (partly artifact) for zero index hosting, instant startup, always-current codes, and no maintenance. This is a judgment call weighted by the goals above, not a pure accuracy win; on retrieval recall alone, FAISS still edges it.
- **Do not delete FAISS yet.** Keep it as the alternate adapter (SNOMED-heavy or offline deployments) until a trustworthy end-to-end number exists.

**Next steps:** (a) re-score the end-to-end benchmark with concept/granularity tolerance so the drop/keep call rests on a sound metric; (b) wire the `Retriever` seam + variant emission into `code_candidates.py` behind a config flag.

## Open decisions

- Drop FAISS entirely vs keep it as a pluggable, non-default adapter.
- MCP Apps vs keeping a thin separate frontend (depends on the host-side contract).
- How far to take IG configurability for the first release (mCODE demo slice vs general IG support).
- License and the commercial/relationship terms of the hand-off (out of scope for this doc).
