# Gemini cost & latency run — 2026-08-25

First cost/latency measurement on the current stack. Captured from
`core.telemetry` (per-call tokens, latency, and `core.pricing` cost) rather than
from `run_demo_benchmark.py`, which is still OpenAI-coupled.

    uv run python benchmarks/eval-corpus-v1/run_augmentation_benchmark.py --runs 3

3 cold passes; Stage-2/3 caches cleared before every pass.

## Headline vs the prior OpenAI run

| Metric | OpenAI (`20260504T015004Z`) | Gemini (this run) | Delta |
|---|---|---|---|
| Cost / run | $0.81 | **$3.61** | **4.5x more expensive** |
| Wall clock / run | 1547 s (25.8 min) | **368 s (6.1 min)** | **4.2x faster** |
| LLM calls / run | ~800 | 940 | +18% |
| Cost / note | $0.045 | $0.201 | 4.5x |
| Cost / 3-note chart prep | $0.13 | $0.60 | 4.5x |

Per-run wall clock: 471 s, 326 s, 306 s (the first pass pays cold-start).

## Per-stage, mean of 3 runs

| Stage | Calls | Input tok | Output tok | Cached tok | $/run | Cost share |
|---|---:|---:|---:|---:|---:|---:|
| 2 Extract | 380 | 582,436 | 123,594 | 1,116 | 1.9845 | 54.9% |
| 3 Merge | 40 | 33,061 | 14,815 | 0 | 0.1829 | 5.1% |
| 4 Code | 518 | 435,116 | 87,193 | 0 | 1.4374 | 39.8% |
| 5 Reconcile | 2 | 989 | 697 | 0 | 0.0078 | 0.2% |
| **Total** | **940** | | | **1,116** | **3.6126** | 100% |

Stage shares are close to the OpenAI run (57% / 5% / 38% / <1%), so the
proportions in `docs/OPTIMIZATION.md` were sound. The absolute dollars were not.

## Why cost rose while latency fell

**Reported cache hits collapsed.** The OpenAI run recorded 1,892,864 cached input
tokens per run from automatic prefix caching. This run records **1,116** — about
0.1% of the 1,017,552 input tokens it sends.

Caveat on that reading: `core/llm.py` maps Gemini's `cached_content_token_count`,
which reports *explicit* context caching. If implicit caching is applying without
surfacing there, actual billing is lower than the figures here. The field is
non-zero, so the plumbing works — but these dollars are token counts priced
against `core/pricing.py`, not a billing statement. **Reconcile against a real
Gemini bill before acting on the caching lever.**

Repricing the cached-eligible input at the cached rate ($1.50/M -> $0.15/M) would
save ~$1.37/run, taking $3.61 -> ~$2.24. That is the single largest cost lever and
it confirms the "turn on Gemini prefix caching" quick win.

It does not close the gap alone. Stage-2 output tokens cost $1.11/run on their own
(123,594 tok x $9.00/M) and output is never cacheable, so output pricing sets the
floor. Getting back to OpenAI-era cost needs fewer or shorter completions, not just
caching.

Latency moved the other way: 4.2x faster despite 18% more calls, which is why the
stage wall-clock sums (Stage 2: 762 s, Stage 4: 770 s of summed per-call latency)
far exceed the 368 s of real elapsed time — the fan-out is heavily concurrent.

## Caveats

- **Stage 0.5 guardrail is missing from these totals.** `clear_pipeline_caches()`
  clears only `stage2_output` and `stage3`, so the guardrail served every document
  from `.cache/doc_guardrail` and made zero LLM calls. It was <1% of cost on the
  prior stack, so the totals are not materially affected — but this is a real gap
  in the harness.
- **Terminology-API round-trips are still unmetered.** Only LLM calls pass through
  `telemetry.record_call`; the live UMLS/RxNav/NLM calls in Stage 4 are not
  recorded. Stage-4 wall clock is therefore understated. This is finding B in
  `docs/OPTIMIZATION.md`, still open.

## Files

- `cost.json` — aggregated per-stage and per-run figures
- `telemetry/*.jsonl` — raw per-call telemetry, one file per run
- `run.log` — console output
