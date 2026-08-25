# Gemini accuracy re-run — 2026-08-25

First accuracy measurement on the current stack (`gemini-3.5-flash` pipeline,
`gemini-3.1-flash-lite` guardrail, live terminology APIs for Stage 4). The prior
checked-in run (`../20260504T015004Z/`) used `gpt-5.4-mini`/`nano` with local
FAISS retrieval, so both the model and the retrieval backend changed in between.

Produced by:

    uv run python benchmarks/eval-corpus-v1/run_augmentation_benchmark.py --runs 5

## Headline

| Metric | This run | Prior (OpenAI) |
|---|---|---|
| Overall accuracy | 89.4% [87.0%, 92.2%] | 90% [87%, 95%] |
| Correct in >=4 of 5 runs | 88.3% (68/77) | 88% |

Per-run: 88.3%, 89.6%, 89.6%, 87.0%, 92.2%.

| Class | This run | Prior (OpenAI) |
|---|---|---|
| NEW (n=47) | 93.2% [89.4%, 97.9%] | 93% [89%, 98%] |
| DUPLICATE (n=26) | 88.5% [84.6%, 92.3%] | 92% [88%, 96%] |
| UPDATING (n=3) | 33.3% (no variance) | 53% [33%, 67%] |
| CONFLICTING (n=1) | 100% (no variance) | 20% [0%, 100%] |

`UPDATING` and `CONFLICTING` are n=3 and n=1. A single fact moves those columns
by tens of points; they are not comparable across runs in any meaningful sense.

## Deterministic failures

Four facts missed in all five runs. All four are classification errors, and
three are chart content classified as `NEW`:

| Fact | Expected | Always classified |
|---|---|---|
| C2-F1 | DUPLICATE | NEW |
| C2-F2 | UPDATING | NEW |
| N4-F2 | UPDATING | NEW |
| N6-F1 | DUPLICATE | UPDATING |

Two of the three `UPDATING` facts are in this list, which is why that column
reads exactly 33.3% in every run.

## Scope and caveats

- **Accuracy only.** Cost, latency, and provenance coverage were not measured.
  `run_demo_benchmark.py`, which produces those, is still OpenAI-coupled and does
  not run against the current config.
- **Run 1 started warm.** The harness clears the Stage-2/3 caches only when
  `run_idx > 0`, so the first pass may have reused cached extractions. This does
  not affect classification accuracy but would bias any cost measurement.

## Files

- `stability.json` — full per-fact records across all 5 runs
- `run.log` — console output
