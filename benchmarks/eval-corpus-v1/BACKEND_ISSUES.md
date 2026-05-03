# Backend issues surfaced by eval-corpus-v1

Issues found while running the augmentation benchmark against the Anamnesis pipeline. Listed in priority order by impact on the demo's "structure first, reason second, act third" thesis.

## Benchmark baseline (post Path-1 corpus re-baselining)

- 18 notes, 13 fixtures, 77 augmentation actions
- NEW recall: 39/47 (83%)
- DUPLICATE recall: 12/26 (46%)
- UPDATING recall: 0/3 (0%)
- CONFLICTING recall: 0/1 to 1/1 (run-to-run flips)
- Overall: ~51-53/77 (66-69%)

Run-to-run variance: ~11/77 cells flip across cleared-cache runs. CONFLICTING and DUPLICATE are most affected.

---

## P0 — UPDATING classification never fires

**Evidence:** 0/3 across all UPDATING test cases. C2-F2 (LVEF 30→40, LOINC 18043-0), N4-F2 (MoCA 26→21, LOINC 72133-2), N6-F2 (tobacco Former→Current, LOINC 72166-2) all classified as NEW or DUPLICATE.

**Hypothesis:** Observation candidates are not being tagged with the right LOINC by Stage 4, so `_match_observation` exits at "no LOINC match → NEW" before reaching the value-comparison branch. The MoCA case is most diagnostic: a 21/30 score is so distinctive it can only fail to classify if the candidate has no LOINC code attached.

**Files:**
- `backend/core/extraction.py` — Observation parser
- `backend/core/coding.py` — tobacco LOINC short-circuit (verify it fires for "Currently smoking 0.5 ppd" wording)

**Why P0:** UPDATING is the meaningful "the chart needs editing" signal that distinguishes augmentation from naive append-only extraction. Zero recall here breaks the demo thesis.

---

## P1 — DUPLICATE coding-mismatch on chronic conditions

**Evidence:** ~50% DUPLICATE recall after Path 1 corpus re-baselining. Common pattern: chart and note refer to the same condition but Stage 4 picks a different code than the chart, so `_match_condition` exact-code match fails.

**Hypothesis:** LLM CodeSelector picks from FAISS top-10 with reasoning-model variance. Even when the canonical code is in top-10, the model sometimes picks a synonym.

**Files:**
- `backend/core/code_candidates.py` — CodeSelector LLM call
- `backend/core/reconcile.py:_match_condition` — display-overlap LLM adjudication path

**Fix paths:**
1. Add SNOMED synonymy/equivalence map to `reconcile.py` so canonical and synonym codes match (e.g., 84114007 ↔ 155377000 for HFrEF).
2. Tighten CodeSelector prompt to prefer most-specific over first plausible.
3. Both — equivalence map handles the long tail; prompt tightening reduces variance at source.

---

## P1 — MedicationRequest dose-diff false positives on combo doses

**Evidence:** E6-F1 and N1-F1 occasionally classified as UPDATING when expected DUPLICATE. Sacubitril/valsartan-style "97/103 mg" doses break the regex.

**Hypothesis:** `_extract_chart_dose` regex `(\d+(?:\.\d+)?)\s*(mg|mcg|g|ml)` matches first number ("97") whereas candidate `dose.value` may be "97/103" → false UPDATING.

**Files:**
- `backend/core/reconcile.py:_extract_chart_dose` (lines ~290-305)

**Fix:** Match combo-dose pattern `X/Y` explicitly, or normalize both sides to first-component-only consistently.

---

## P1 — Procedure-already-completed-before-visit not extracted

**Evidence:** N3-F2 (CT head 2026-03-26 PCP-ordered, completed before neuro visit) MISSING. N5-F2 (prior MRI 2025-11) MISSING. C1-F3 (cardiac cath) hits because of explicit dated verb pattern.

**Hypothesis:** Procedure parser treats "PCP ordered", "Last MRI", "Prior CT" as historical reference rather than completed Procedure to record.

**Files:**
- `backend/core/extraction.py` — Procedure parser prompt

**Fix:** Add rule that procedures referenced as historical-but-with-date should be extracted with `status=completed` + `performedDateTime`.

---

## P1 — Reasoning-model variance has no API-level fix (measurement gap)

**Evidence:** ~11/77 cells flip across runs with cleared cache. CONFLICTING went 1/1 → 0/1 between two identical runs. OpenAI Responses API rejects `seed` (`"Unknown parameter: 'seed'"`); `temperature=0` requires `reasoning.effort="none"` which disables reasoning entirely.

**Hypothesis:** No silver-bullet config. Variance must be reduced by tightening prompts and replacing LLM-driven steps with deterministic logic where possible. Caching for benchmark stability is rejected — would mask production variance the benchmark should expose.

**Investigation path:**
1. Add `--runs N` to `benchmarks/eval-corpus-v1/run_augmentation_benchmark.py` and emit per-fact stability stats (`{fact_id → (most_common_classification, agreement_count_over_N)}`).
2. Identify which specific fact_ids are unstable.
3. Prompt-tighten or de-LLM the calls that produce them — both gains land in production.

**Why P1:** Measurement infrastructure first. Without per-fact stability data we are chasing ghosts.

---

## P2 — One-time ED medication administration inconsistently surfacing

**Evidence:** E1-F2 (IV ceftriaxone 2g x1 in ED) and C2-F5/F6 (carvedilol/spironolactone "Continue") MISSING in some runs, present in others. Cache invalidation flips behavior.

**Hypothesis:** MedicationRequest parser distinguishes "Initiate X" cleanly but "Continue X" and "x 1 dose" patterns may be merged or filtered.

**Files:**
- `backend/core/extraction.py` — MedicationRequest parser prompt

**Fix:** Verify parser emits separate MedicationRequest candidates with `status=completed` for one-time administration, `status=active` for continued meds.

---

## P2 — Composite Condition merging swallows separately-coded facts

**Evidence:** C1-F2 (single-vessel CAD, SNOMED 53741008) MISSING — merged into C1-F1 (stable angina, SNOMED 233819005). Note prose: "Stable angina pectoris in the setting of single-vessel coronary artery disease." Stage 3 dedupe likely treats the second clause as elaboration.

**Files:**
- `backend/core/extraction.py:merge_across_notes` — adjudicator prompt

**Fix:** Don't merge two candidates if they have distinct SNOMED root concepts, even when text overlaps.

---

## P3 — Corpus uses non-US-Core-canonical SNOMED codes (Path 1 debt)

**Evidence:** Path 1 (`benchmarks/eval-corpus-v1/apply_code_swaps.py`) swapped 19 codes to FAISS-canonical equivalents. Corpus now uses e.g. SNOMED 155377000 ("Heart failure NOS") instead of US Core canonical 84114007. Acceptable for benchmark; not for real FHIR write-back.

**Fix path:** Implement P1 SNOMED synonymy map in `reconcile.py`, then revert corpus to US Core canonical codes via reverse-swap script. The synonymy map is the same fix needed for P1 DUPLICATE coding-mismatch, so this collapses into that ticket.

---

## P3 — CONFLICTING is fragile (depends on extractor producing the candidate)

**Evidence:** E5-F1 sulfa-vs-NKDA worked in one run (1/1) and disappeared in next (0/1) purely because the extractor didn't produce the AllergyIntolerance candidate that turn.

**Hypothesis:** Same root cause as P1 reasoning-model variance, but symptom on the highest-stakes classification — surfacing a chart conflict for human review.

**Fix:** Inherits from P1 measurement work + AllergyIntolerance parser prompt review.

---

## Suggested ticket bundling for execution

| Ticket | Priority | Scope | Issues addressed |
|---|---|---|---|
| 1 | P0 | Observation LOINC tagging in extraction + tobacco short-circuit | UPDATING never fires |
| 2 | P1 | SNOMED synonymy map in `reconcile.py` + corpus US Core revert | DUPLICATE coding-mismatch + Path 1 debt |
| 3 | P1 | Combo-dose handling in `_extract_chart_dose` | Med dose-diff false positives |
| 4 | P1 | Multi-run benchmark + per-fact stability dump | Measurement infrastructure for variance work |
| 5 | P1 | Procedure historical-with-date extraction | N3-F2, N5-F2 MISSING |
| 6 | P2 | Continue-vs-Initiate medication parsing | One-time admin inconsistency |
| 7 | P2 | Condition merge prompt — preserve distinct SNOMED concepts | Composite condition merging |

Tickets 2, 3, 5, 6, 7 are mostly prompt/regex edits — small surface, fast iterations. Tickets 1 and 4 need slightly more investigation. Total scope is roughly 1-2 days if split between people.

---

## How to reproduce these findings

```bash
# 1. Validate the corpus (must pass with 0 errors)
python benchmarks/eval-corpus-v1/validate_corpus.py

# 2. Verify codes against vector DB (top-10 should be 100% across systems post Path 1)
python benchmarks/eval-corpus-v1/verify_codes_against_index.py

# 3. Run augmentation benchmark
python benchmarks/eval-corpus-v1/run_augmentation_benchmark.py --output report.json

# 4. Diff two runs to observe variance
rm -rf backend/.cache/stage2_output backend/.cache/stage3
python benchmarks/eval-corpus-v1/run_augmentation_benchmark.py --output run_a.json
rm -rf backend/.cache/stage2_output backend/.cache/stage3
python benchmarks/eval-corpus-v1/run_augmentation_benchmark.py --output run_b.json
# Compare confusion matrices and per-row classifications
```
