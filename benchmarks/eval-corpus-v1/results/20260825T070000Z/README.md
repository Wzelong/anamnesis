# gemini-3.7-flash adoption run — 2026-08-25

5 cold passes on `gemini-3.7-flash`, the new `config.py` default. Guardrail stays
on `gemini-3.1-flash-lite`. Compare against `../20260825T060000Z/` (3.5-flash,
3 cold passes) and `../20260825T050000Z/` (3.5-flash, 5 passes, warm first pass).

    uv run python benchmarks/eval-corpus-v1/run_augmentation_benchmark.py --runs 5

## Result

| | 3.5-flash (3 cold) | **3.7-flash (5 cold)** |
|---|---:|---:|
| Overall accuracy | 92.6% [89.6–94.8] | **90.6% [89.6–90.9]** |
| stable-right | 68 | 69 |
| flaky | 5 | **2** |
| **stable-wrong** | **4** | **6** |
| Cost / run | $3.61 | **$1.62** |
| Wall clock / run | 368 s | 373 s |
| LLM calls / run | 940 | 1,054 |

**Cost is 55% lower. Accuracy is ~2 points lower and two facts regressed.**

Latency is a wash. An earlier 3-run pass measured 320 s; at 5 runs it is 373 s
against 368 s for 3.5-flash. Do not claim 3.7 is faster.

## Cost by stage (correctly priced, promo rates)

| Stage | Calls | Input tok | Output tok | $/run | Share |
|---|---:|---:|---:|---:|---:|
| 2 Extract | 431 | 657,437 | 98,356 | 0.8619 | 53.2% |
| 3 Merge | 43 | 36,202 | 9,593 | 0.0631 | 3.9% |
| 4 Code | 577 | 482,361 | 87,810 | 0.6911 | 42.7% |
| 5 Reconcile | 2 | 1,167 | 523 | 0.0028 | 0.2% |
| **Total** | **1,054** | | | **1.6189** | 100% |

**The $1.62 is promotional.** `gemini-3.7-flash` is $0.75/$3.75 per 1M through
2026-12-31, then $1.50/$7.50. At standard rates this run costs **~$3.24**, a 10%
saving over 3.5-flash rather than 55%. `core/pricing.py` reverts automatically on
the expiry date; budget on $3.24.

## The regression, confirmed

3.7 fixes none of 3.5's four deterministic failures and adds two more. Both were
merely flaky under 3.5 and are now wrong in every run:

| Fact | Expected | 3.5-flash (3 cold) | 3.7-flash (5 cold) |
|---|---|---|---|
| N1-F2 | DUPLICATE | flaky, 2/3 hits | **0/5 — UPDATING ×5** |
| N1-F4 | NEW | flaky, 2/3 hits | **0/5 — MISSING ×5** |

`N1-F4` is the worse of the two: the fact is never extracted at all, in any run.

Carried over unchanged from 3.5 (and from the OpenAI stack before it): `C2-F1`,
`C2-F2`, `N4-F2`, `N6-F1`. Six model generations across two vendors now fail these
identically, which places them in pipeline logic rather than model capability.

## Reading the accuracy delta

The variance collapsed: 3.7 ranges 89.6–90.9% against 3.5's 89.6–94.8%. 3.7 is more
consistent but consistently lower, and the "flaky 5 -> 2" improvement is partly
flaky facts becoming reliably wrong rather than reliably right.

No 5-run cold baseline exists for 3.5-flash, so the headline comparison is 5 cold
runs against 3 cold runs. The regression on N1-F2/N1-F4 is unambiguous; the ~2-point
overall gap is less firmly established.

## Files

- `stability.json` — per-fact records across all 5 runs
- `telemetry/*.jsonl` — raw per-call telemetry
- `run.log` — console output
