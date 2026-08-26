# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Default pipeline model is now `gemini-3.7-flash` (was `gemini-3.5-flash`). Measured over
  5 cold passes: **$1.62/run against $3.61, for 90.6% accuracy against 92.6%.** The saving
  is promotional — 3.7 reverts to standard rates on 2027-01-01, about $3.24/run.
  Two facts regressed from flaky to deterministically wrong (`N1-F2`, `N1-F4`).
- `core/pricing.py` carries promotional rates in a separate table with their own expiry
  date, so they revert automatically instead of silently under-reporting cost from 2027.

### Added

- Gemini accuracy benchmark (`benchmarks/eval-corpus-v1/results/20260825T050000Z/`):
  89.4% overall [87.0%, 92.2%], 88.3% of facts correct in >=4 of 5 runs — statistically
  unchanged from the 90% measured on the retired OpenAI stack.
- The augmentation benchmark now runs inside a telemetry run, so per-call tokens, cost,
  and latency are recorded instead of silently discarded.
- Gemini cost/latency benchmark (`benchmarks/eval-corpus-v1/results/20260825T060000Z/`):
  $3.61 and 368 s per run over the 18-note corpus, against $0.81 and 1547 s on the
  retired OpenAI stack — 4.5x more expensive, 4.2x faster. Stage cost shares are
  within a point of the previous run.

### Changed

- Ruff configuration moved to a repo-root `ruff.toml` so lint and format cover
  `benchmarks/` and `data/` as well as `backend/`; CI now checks the whole repo.

### Fixed

- `UsageTracker` was referenced in annotations in the augmentation benchmark runner
  without being imported, and `zip()` calls over equal-length sequences in the
  benchmark scripts now pass `strict=True` instead of silently truncating.

## [0.1.0] - 2026-08-24

Initial release, prepared for open-source hand-off. Six-stage augmentation pipeline,
in-host MCP review app, PO-native auth, encrypted BYOK, and a non-PHI usage ledger.
Benchmark: 90% augmentation accuracy, 100% provenance coverage on the eval-corpus-v1
corpus (`benchmarks/eval-corpus-v1/results/20260504T015004Z/`).

### Added

- Open-source hand-off scaffolding: `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`,
  `.editorconfig`, `CODEOWNERS`, issue/PR templates, and a GitHub Actions CI workflow
  (backend lint + type-check + tests, review-app type-check + build).
- Ruff and mypy configuration for the backend; lint/typecheck scripts for the review app.
- `docs/OPTIMIZATION.md` — pipeline bottleneck analysis, SOTA comparison, and ranked next
  steps, with a standalone HTML rendering for sharing.

### Changed

- Documentation reconciled with the stateless, live-API implementation: `PIPELINE.md`
  (Stage 4 terminology retrieval, confidence scoring, stateless review hand-off),
  filename references in `DIRECTION.md` and `Architecture.md`, and README framing.

### Fixed

- README's benchmark headline was still the OpenAI run: 90% accuracy, ~$0.13/chart, and an
  embedded per-class chart from `results/20260504T015004Z/`. Replaced with the measured
  `gemini-3.7-flash` figures, and the reproduce command now points at the runner that works.
- PIPELINE.md attributed the Stage 0.5 guardrail to the pipeline model; it runs on
  `gemini_model_nano` (`gemini-3.1-flash-lite`).
- `estimate_cost` returning 0 for an unpriced model is now caught in CI:
  `test_configured_models_are_priced` asserts every model in `settings` has a rate entry.
  Previously a model bump would silently record $0 spend in the BYOK usage ledger.
- `backend/.env.example` now matches the code: the dev scripts under `backend/scripts/`
  read `DEV_FHIR_BASE_URL` / `DEV_FHIR_TOKEN`, which were undocumented.
- Stage-2 regression tests no longer abort collection on a clean checkout. They called
  `pytest.skip()` from `@pytest.mark.parametrize`, which runs at collection time, so a
  clone without the gitignored `backend/.cache/stage2_output/` failed the whole suite
  instead of skipping those tests.

### Removed

- Stale experiment `backend/spike_prefab/` and a committed benchmark output artifact.
- Vestigial `FHIR_BASE_URL` and unused `NGROK_DOMAIN` from `backend/.env.example`; the
  server takes the FHIR base URL and token per request from SHARP headers.
