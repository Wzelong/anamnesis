# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
