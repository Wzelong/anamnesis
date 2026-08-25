# Contributing to Anamnesis

Thanks for your interest. Anamnesis is a FHIR augmentation MCP server: a clinical-note to FHIR pipeline with human-in-the-loop review. This guide gets you from clone to a green test run and a mergeable change.

## Project layout

```
backend/     FastMCP v3 server, augmentation pipeline, FHIR I/O (Python 3.12)
mcp-app/     React 19 + Vite review UI, built into backend/mcp_server/ui/assets
benchmarks/  Eval corpus + multi-run benchmark
data/        Synthetic demo patient bundle + notes
```

Read [Architecture.md](Architecture.md) for the system shape, [PIPELINE.md](PIPELINE.md) for the per-stage pipeline, and [DIRECTION.md](DIRECTION.md) for where the project is headed.

## Development setup

Prerequisites: Python 3.12 (3.11 supported), Node 20+, and [uv](https://docs.astral.sh/uv/) (recommended) or pip.

### Backend

```bash
cd backend
uv sync --extra dev            # or: python -m venv .venv && pip install -e ".[dev]"
cp .env.example .env           # set GEMINI_API_KEY and CONFIG_SECRET_KEY
uv run pytest                  # 300+ tests, fully offline, ~2s
uv run python po_main.py       # serves http://0.0.0.0:8042/mcp
```

The test suite needs no network and no API keys. `curl http://localhost:8042/healthz` should return `{"status":"ok"}`.

### Review app

```bash
cd mcp-app
npm install
npm run typecheck              # tsc --noEmit
npm run build                  # outputs review.js / review.css into backend/mcp_server/ui/assets
```

Built UI assets are committed (the deploy target serves them without a Node build), so run `npm run build` and commit the assets when you change the app.

## Before you open a PR

Run the same checks CI runs:

```bash
# backend
cd backend
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest

# app
cd ../mcp-app
npm run typecheck
```

## Coding conventions

- Keep the code clean, concise, and state-of-the-art. Descriptive names for variables, functions, and classes.
- Minimal comments. Explain *why*, not *what*; let clear code speak for itself.
- Each pipeline stage is a pure function over typed Pydantic schemas. LLM calls go through the single `core/llm.py` wrapper and are wrapped in telemetry.
- **Provenance is non-negotiable.** A proposal without source refs, or a write without a `Provenance` resource, is a bug.
- **Nothing writes to FHIR outside Stage 8** (`fhir/write.py`), and only on explicit accept.
- No PHI at rest. Do not add persistence of clinical content.

## Commit and PR guidelines

- Write focused commits with clear messages (imperative subject).
- One logical change per PR. Include tests for behavior changes.
- Fill out the PR template. Link the issue it closes.
- CI must be green (lint, type-check, tests) before review.

## Reporting issues

Use the issue templates. For security vulnerabilities, follow [SECURITY.md](SECURITY.md) instead of opening a public issue.
