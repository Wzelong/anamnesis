# Pipeline Bottlenecks, SOTA Comparison, and Next Steps

A working document for the Prompt Opinion (PO) hand-off discussion. It maps where the augmentation pipeline spends time, money, and accuracy; compares each stage to the 2024-2026 state of the art; and ranks concrete next steps. Every SOTA claim is cited in the [sources](#sources).

> **Measurement status.** Accuracy has been re-measured on the current Gemini stack (`benchmarks/eval-corpus-v1/results/20260825T050000Z/`, `gemini-3.5-flash` + `gemini-3.1-flash-lite`, 5 runs, 18 notes x 13 charts x 77 facts): **89.4% overall [87.0%, 92.2%], 88.3% of facts correct in >=4 of 5 runs** — statistically unchanged from the 90% measured on the earlier OpenAI stack, despite both the model and the Stage-4 retrieval backend changing since.
>
> **The cost and latency figures below are still from the OpenAI run** (`results/20260504T015004Z/`, `gpt-5.4-mini`/`nano`). Relative stage proportions are expected to hold; absolute dollars and seconds do not. The report generator for those figures (`run_demo_benchmark.py`) is still OpenAI-coupled and does not run against the current config — see the quick-wins table.

---

## 1. Where the pipeline actually spends

The pipeline is a **many-small-LLM-calls** architecture: ~800 model calls per run, almost all reusing large fixed system prompts for small structured outputs.

| Stage | Nature | Calls/run | Share of cost | Notes |
|---|---|---:|---:|---|
| 0.5 Guardrail | LLM (nano), parallel | ~3 | <1% | Cheap, cached, not a bottleneck |
| 1 Preprocess | Deterministic | 0 | 0 | Regex sentence split; negligible |
| **2 Extract** | LLM (scan+parse+clean), parallel | **~366** | **~57%** | **Top cost.** Fan-out = notes x types x sentence-groups |
| 3 Merge | Deterministic + sparse LLM | ~0-2 | ~5% | Exact-match first; LLM only for fuzzy dups |
| **4 Code** | Live-API retrieval + LLM selector | **~435** | **~38%** | **Second cost; likely top wall-clock** (see below) |
| 5 Reconcile | Deterministic + sparse LLM | ~0-2 | <1% | Chart-size-insensitive; the "brain," and it is cheap |
| 6 Assemble | Deterministic | 0 | 0 | FHIR build + citations; negligible |

**Two stages (Extract + Code) are ~95% of both cost and LLM wall-clock.** Everything downstream of coding is nearly free.

### Accuracy is lost at the front, not the brain

From the benchmark error attribution:

| Error source | Share | Stage |
|---|---:|---|
| **Extraction miss** (fact never extracted) | **62%** | 2 |
| **Coding miss** (right fact, wrong code) | **32%** | 4 |
| Reconciler miss (right fact/code, wrong class) | 5% | 5 |

The reconciliation stage — the capability that differentiates Anamnesis — is the *least* error-prone. **94% of errors live in the extract and code stages.** Optimization effort should follow.

**Update (2026-08-25 Gemini run).** The front-loaded picture holds overall, but the two error kinds separate cleanly by determinism. Of 77 facts across 5 runs, 61 were stable-right, 12 flaky, and 4 stable-wrong. Sixteen of the flaky misses are `MISSING` — the fact was never extracted — consistent with extraction being the dominant error source. But **all 4 deterministic failures are classification errors, not extraction or coding**:

| Fact | Expected | Always classified |
|---|---|---|
| `C2-F1` | DUPLICATE | NEW |
| `C2-F2` | UPDATING | NEW |
| `N4-F2` | UPDATING | NEW |
| `N6-F1` | DUPLICATE | UPDATING |

Three of the four are the same failure mode: content already present in the chart classified as `NEW`. Two of the three `UPDATING` facts fail this way in every run, which is the entire reason that column reads 33.3% with zero variance. So while the reconciler contributes the fewest errors by volume, it contributes the ones that are reproducible and therefore actually fixable — the extraction misses are variance, these are logic.

---

## 2. Code-level findings (verified against current source)

These are concrete, low-ambiguity issues found while tracing the current code. They are the cheapest wins and should land before any architectural change.

| # | Finding | Evidence | Impact |
|---|---|---|---|
| A | **Dead concurrency cap.** `extract_candidates_batch` takes `max_concurrent=50` and its docstring claims "bounded by semaphore," but the body is a bare `asyncio.gather` with no semaphore — no backpressure on in-flight calls. (Docstring also still says "OpenAI client.") | `core/extraction.py:558-577`; `config.py:18` `stage2_max_concurrent` is unused | On dense multi-note patients, hundreds of concurrent Gemini calls burst at once -> rate-limit 429s -> retry tail latency |
| B | **Terminology-API latency is invisible.** Telemetry wraps only LLM calls; the live UMLS/RxNav/NLM round-trips in Stage 4 are never recorded. Retrieval is globally throttled to **6 concurrent** with 25s timeouts and multi-variant + backoff fan-out. | `core/telemetry.py` `record_call` (LLM only); `core/retrieval.py` (`concurrency=6`) | The likely top wall-clock sink is unmeasured. Cannot optimize what you cannot see |
| C | **Serial coding sub-loops.** AllergyIntolerance codes substance then reaction sequentially; FamilyMemberHistory codes each condition in an `await` loop. The main Condition/Med/Procedure path already parallelizes. | `core/code_candidates.py` (allergy + FMH paths) | Free per-candidate latency for those types |
| D | **Model tier not wired.** `gemini_model_smart == gemini_model_fast`. The "stronger model for ambiguous reconciliation" design point is nominal only. | `config.py:11-12`; `services/proposals.py` passes fast model to reconcile | No quality headroom on the hardest calls; also no cost harm today |
| E | **No Stage-4 cache (by design).** Every run re-hits live APIs for the same `(term, system)`, even on retries. Deliberate (a stale cache could re-apply a HITL-corrected code), but it is the only stage with no warm path. | `core/code_candidates.py` docstring | Repeated latency/cost; addressable with HITL-aware invalidation |

---

## 3. SOTA comparison (2024-2026) and how it maps to us

### 3.1 Clinical extraction (Stage 2) — our #1 error source

- Rigorous **cross-domain** strict-span F1 for GPT-4o-class models is **~53-57** (NCER benchmark), not the 0.9+ that narrow single-domain studies report [NCER 2024]. On 1,588 annotated notes the best LLM reached 0.932 NER F1, edging BERT with a >7% advantage in low-resource/cross-institution settings [JAMIA 2025].
- **Single-pass vs multi-call is nuanced.** Long-context single-pass suffers "lost in the middle" (>30% drop for mid-context facts) and multi-fact recall collapse [Lost in the Middle 2023; PARSE 2025]. But *each* routing/gate step is itself a recall-loss point — which is exactly our failure mode.
- **Recall lever: multi-sample then UNION, not majority vote.** Majority-vote self-consistency adds ~0.7pp at ~5x cost and is fading on frontier models [arXiv:2604.19395, 2026]; union-over-samples is the mechanism that actually lifts recall [arXiv:2601.18395, 2026 — thin].
- **Structured decoding** guarantees output *shape*, not *coverage*; it helps slot-filling but will not fix true omissions, and can hurt free-form reasoning [Let Me Speak Freely? 2024; XGrammar-2 2026].

**Us:** our 62% "never extracted" is almost certainly the per-note **scan** step dropping/misrouting a sentence before any parse call sees it (a relevance-gate false negative), not long-context loss (our inputs are short). Highest-leverage fix: **multi-sample the scan/parse at temp>0 and union the facts**, letting the existing clean/dedup pass absorb precision. Structured decoding is worth adding for reliability but is not a 62%-mover.

### 3.2 Medical coding / entity linking (Stage 4) — our #2 error source

- The field converged on exactly our shape — **retrieve candidates, LLM disambiguates** [BeLink 2026; ACL 2025 "LLM as Disambiguator"]. Recurring caveat: **the reranker is capped by candidate recall — an LLM cannot pick a code the retriever never surfaced.**
- Plain lexical retrieval is a stronger candidate generator than intuition suggests (TF-IDF beat SapBERT at Acc@1 in one head-to-head; SapBERT wins at k=5/32) [PMC11097978]. No decisive successor to SapBERT, but **BioLORD-2023 modestly beats it** on concept mapping [JAMIA 2024]. **LOINC/lab normalization is the hardest** (<40% acc@1 for both). RxNorm is best-solved.

**Us:** the load-bearing diagnostic for our 32% coding miss is **retrieval-recall failure vs rerank failure** — they need opposite fixes. Run a candidate **recall@K ablation on our own error set** first. If retrieval is the gap, add a **hybrid** (union of live-lexical + a dense biomedical index) rather than swapping; if reintroducing an encoder, **BioLORD-2023 is a better default than the old SapBERT**. No published benchmark compares live-APIs vs local SapBERT+FAISS — measure internally.

### 3.3 Reconciliation (Stage 5) — correctly low priority

- **No paper frames the exact NEW/DUPLICATE/UPDATING/CONFLICTING task** — itself a finding. The closest analogue, VeriFact ("decompose -> retrieve patient facts -> LLM-judge"), hits 92.7% agreement with clinicians, *above* inter-clinician agreement [VeriFact 2025]. Our deterministic-code-match-then-LLM design is aligned with, and arguably ahead of, published med-rec work (which mostly stops at extraction).
- Known weak spot: **temporal reasoning** (update-vs-conflict edge cases) with a single flash-class model [EMNLP Findings 2025].

**Us:** at 5% of errors, leave it. If reconciliation errors ever climb, look at temporal edge cases first, and this is the natural place to finally wire `gemini_model_smart` to a stronger model (finding D).

### 3.4 LLM -> FHIR (Stage 6) — our design is validated

- Element extraction is accurate, but **structural/profile conformance of directly-emitted FHIR is where LLMs fail.** A frontier model emitting raw FHIR produced **248 validation errors** across a 150-resource patient vs **zero** for a deterministic converter [John Snow Labs 2026]; Infherno deliberately moved the LLM off raw-JSON emission to code that builds validated objects [Infherno 2025]. Giving the model `$validate` in a loop raised validity sharply [Flexpa 2025].

**Us:** our Stage 6 (LLM produces structured candidates -> deterministic US Core/mCODE assembly) is the well-supported choice. **Add FHIR `$validate` against US Core 6.1.0 + mCODE STU4 in CI** (profile slicing + terminology bindings, not just base-schema validity) plus a terminology-server check on code selections. This also aligns with the `validate_before_write` gate already stubbed in `config.py`.

### 3.5 Cross-cutting efficiency — the most certain win

- **Prompt/prefix/context caching** is the biggest, most certain lever for a ~800-call/run pipeline reusing shared instructions. Gemini 2.5 **implicit caching is on by default (~75% realized savings)**; **explicit caching bills cached input at 10% of standard** [Gemini caching docs 2025/2026]. BYOK does not block it.
- **Batch API: 50% off** with a <=24h SLA, combinable with caching — good for non-interactive processing, unusable while a clinician waits [Gemini Batch 2026].
- **Model cascades** (cheap-first, escalate on low confidence) cut cost 35-85% on benchmarks [FrugalGPT 2023; RouteLLM 2024] — but unvalidated on clinical extraction; treat as experimental.
- **Does not transfer to BYOK/API:** speculative decoding (serving-side), distillation (needs a hosted fine-tuned model, not the user's stock Gemini key).

**Us:** restructure prompts **invariant-block-first, variable content last** so caching applies; add explicit caching on the shared Stage-2/4 blocks. This directly attacks the 57%/38% cost buckets and de-risks the added cost of union-sampling (§3.1).

### 3.6 Evaluation practices

- Field norm: per-type P/R/F1 under **both exact and relaxed** span match, micro **and** macro; **granularity-tolerant hierarchical code metrics (hF1** with ancestor augmentation) instead of flat exact-code accuracy [arXiv:2410.01305, 2024]; consistency across >=5 runs with agreement stats; >=2-clinician adjudication with reported kappa; TRIPOD-LLM reporting [Nature Medicine 2025].

**Us:** a **77-fact** gold set sits at the low end of the field's "tens of items" feasibility tier and is under-powered for stable per-type F1 (bootstrap the CIs). Reporting 5-run consistency is *above* field median, but 5 is the floor. Our own DIRECTION appendix already flags that end-to-end code accuracy is "inconclusive by construction" without granularity tolerance — hF1 closes that.

---

## 4. Ranked next steps

Two buckets. **Quick wins** are low-risk, mostly code-level, and should land first. **Strategic** items are SOTA-aligned, need design + eval, and are where the discussion with PO matters.

### Quick wins (this-sprint, high certainty)

| Move | Attacks | Effort | Notes |
|---|---|---|---|
| **Re-instrument the cost/latency benchmark for Gemini** | measurement | S-M | Accuracy is done (2026-08-25, unchanged at 89.4%). Cost/latency are not: `run_demo_benchmark.py` still builds an `AsyncOpenAI` client and reads `settings.openai_*` fields that no longer exist. `core/telemetry.py` + `core/pricing.py` already cover Gemini, so wiring `start_run()` into the benchmark is the cheaper path than porting `usage_tracker.py` |
| **Meter terminology-API latency/errors in telemetry** (finding B) | latency visibility | S | Make the hidden Stage-4 wall-clock measurable before optimizing it |
| **Wire the dead concurrency cap + a global in-flight limit** (finding A) | latency (429 tail) | S | Removes rate-limit-induced retries on dense charts |
| **Parallelize allergy + FMH coding sub-loops** (finding C) | latency | S | Free; `asyncio.gather` the sub-jobs |
| **Turn on Gemini prefix/context caching** (invariant-block-first prompts) | cost + latency | S-M | Biggest certain efficiency win; hits the 57%/38% buckets |

### Strategic (needs design + eval, discuss with PO)

| Move | Attacks | Effort | Evidence strength |
|---|---|---|---|
| **Union multi-sampling of scan/parse** (temp>0, dedup absorbs precision) | 62% extraction miss | M | Strong on why majority-vote fails; thin on union-for-extraction — pilot-measure |
| **Recall@K ablation of Stage 4, then hybrid lexical+dense retrieval** (BioLORD-2023 if adding an encoder) | 32% coding miss | M-H | Strong that rerankers are recall-bounded; live-vs-local is unbenchmarked — measure |
| **Structured decoding (schema/function calling) on extract+code** | reliability | L-M | Verified; sets expectations — fixes shape, not omissions |
| **FHIR `$validate` (US Core 6.1.0 + mCODE STU4) + terminology check in CI** | conformance | L-M | Strong; confirms deterministic-assembly choice |
| **Eval upgrade: hF1 + grow gold set to ~200+ + per-type micro/macro F1 + >=2-clinician kappa** | measurement quality | L-M | Strong, named methods; the measuring stick for all above |
| **Batch API (50% off) for non-interactive; Flash-Lite->Flash cascade** | cost | M | Batch certain; cascade experimental/unvalidated clinically |

**Priority logic:** moves that target the 94% of errors in extract+code (union-sampling, retrieval diagnosis) should dominate. Structured decoding is often over-sold as a recall fix — it is not. Distillation and speculative decoding do not transfer to the BYOK/API setting.

---

## 5. Open questions for the PO discussion

1. **Retrieval strategy end-state** — commit to live-API-only (zero index hosting, always-current, but network-bound and unmetered), or fund a hybrid with a local dense index (better recall on paraphrased mentions, but staleness + hosting)? The recall@K ablation should decide this, not intuition.
2. **Latency budget** — chart prep is interactive (clinician waiting), so the 50%-off Batch API only helps offline paths. Is there an offline/pre-fetch path worth building?
3. **Model policy under BYOK** — do we wire a cheap->strong cascade (and eat the clinical-validation cost), or keep a single model for auditability?
4. **Eval investment** — who annotates the larger gold set, and do we adopt TRIPOD-LLM reporting for credibility with clinical stakeholders?
5. **The `validate_before_write` gate** — ship the `$validate` hard-gate on by default, or keep it opportunistic (attach conformance, never block)?

---

## Sources

Extraction: NCER (arXiv:2410.05046, 2024); "Are we ready to switch to LLMs?" (JAMIA, 10.1093/jamia/ocaf213, 2025); Lost in the Middle (arXiv:2307.03172, 2023); PARSE (arXiv:2510.08623, 2025); Let Me Speak Freely? (arXiv:2408.02442, 2024); XGrammar-2 (arXiv:2601.04426, 2026); Self-Consistency recall (arXiv:2604.19395, 2026); union-sampling IE (arXiv:2601.18395, 2026).
Coding: Biomedical Entity Linking eval (PMC11097978, 2024); BioLORD-2023 (JAMIA, 2024); BeLink (arXiv:2605.22501, 2026); "LLM as Disambiguator" (ACL 2025 Short); PLM-ICD (arXiv:2207.05289, 2022).
Reconciliation: VeriFact (arXiv:2501.16672, 2025); temporal reasoning (Kruse, EMNLP Findings 2025); MedNLI (arXiv:1808.06752, 2018).
FHIR: FHIR-GPT (PMC12312630, 2024); Infherno (arXiv:2507.12261, 2025); Flexpa LLM FHIR Eval (2025); John Snow Labs deterministic OMOP-to-FHIR (2026).
Efficiency: Gemini context caching + implicit caching (Google, 2025/2026); Gemini Batch API (2026); FrugalGPT (arXiv:2305.05176, 2023); RouteLLM (LMSYS, 2024).
Evaluation: Revisiting Hierarchical Text Classification (arXiv:2410.01305, 2024); TRIPOD-LLM (Nature Medicine, 10.1038/s41591-024-03425-5, 2025).
