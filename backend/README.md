# Anamnesis Backend

FastAPI backend for Anamnesis. Serves both an MCP interface for AI agents and a REST API for the frontend. This is the runnable skeleton — no business logic yet.

## Install

From this directory:

```
pip install -e .
```

For tests:

```
pip install -e ".[dev]"
```

Copy `.env.example` to `.env` and fill in values.

## Run

```
uvicorn main:app --reload
```

## Health check

```
curl http://localhost:8000/health
```

Expected: `{"status":"ok","service":"anamnesis"}`

## Test

```
pytest
```
