---
name: deploying-flyio
description: Fly.io deployment for the Anamnesis project (FastAPI backend + Next.js frontend). Covers fly.toml configuration, Dockerfile authoring, secrets, volumes, VM sizing, and multi-process setup. Use when deploying to fly.io, writing fly.toml, creating Dockerfiles for fly.io, or configuring fly.io secrets/volumes/scaling.
---

# Fly.io Deployment — Anamnesis

## Stack

- **Backend**: Python 3.13 FastAPI + uvicorn, sentence-transformers (~1GB model), FAISS indexes (~200MB), SQLite
- **Frontend**: Next.js 16, React 19, port 3042
- Backend listens on port 8042, frontend on 3042

## Architecture decision: two apps

Deploy as **two separate Fly.io apps** (`anamnesis-api` and `anamnesis-web`). The backend needs persistent volumes, large VM, and slow cold starts from ML model loading. The frontend is stateless and lightweight. Separate apps allow independent scaling, deployment, and resource allocation.

The frontend's `NEXT_PUBLIC_API_URL` env var points to the backend app's public URL.

## fly.toml — backend

```toml
app = "anamnesis-api"
primary_region = "ord"

[build]
dockerfile = "Dockerfile.backend"

[env]
LOG_LEVEL = "INFO"
DATABASE_URL = "sqlite+aiosqlite:////data/anamnesis.db"

[http_service]
internal_port = 8042
force_https = true
auto_stop_machines = false
auto_start_machines = true
min_machines_running = 1

[[http_service.checks]]
grace_period = "120s"
interval = "30s"
timeout = "5s"
method = "GET"
path = "/health"

[[mounts]]
source = "anamnesis_data"
destination = "/data"

[[vm]]
memory = "2gb"
cpus = 2
cpu_kind = "performance"
```

Key choices:
- `auto_stop_machines = false` — ML model load takes 30-60s, cold starts are unacceptable
- `grace_period = "120s"` — model + index warmup on first boot
- `performance` CPU — sentence-transformers needs consistent CPU, not burstable
- `2gb` RAM minimum — model (~1GB) + indexes (~200MB) + app overhead
- Volume at `/data` — SQLite persistence across deploys

## fly.toml — frontend

```toml
app = "anamnesis-web"
primary_region = "ord"

[build]
dockerfile = "Dockerfile.frontend"

[env]
NEXT_PUBLIC_API_URL = "https://anamnesis-api.fly.dev"

[http_service]
internal_port = 3042
force_https = true
auto_stop_machines = true
auto_start_machines = true

[[vm]]
memory = "512mb"
cpus = 1
cpu_kind = "shared"
```

## Dockerfile patterns

See [dockerfiles.md](dockerfiles.md) for complete Dockerfile examples for both backend and frontend.

Backend Dockerfile key points:
- Multi-stage build: builder (install deps) → runtime (slim image)
- Copy `embeddings/` and pre-built `data/indexes/` into the image
- The index build step runs at build time, not runtime
- SQLite DB lives on the mounted volume, not in the image
- `WARMUP_CODING_ON_STARTUP=true` loads model + indexes at boot

Frontend Dockerfile key points:
- Multi-stage: deps → build → runtime
- Next.js standalone output mode for minimal image size
- Static assets served by Next.js built-in server

## Secrets

```bash
# Backend
fly secrets set OPENAI_API_KEY=sk-... -a anamnesis-api
fly secrets set REVIEW_TOKEN_SECRET=... -a anamnesis-api

# Frontend (if any server-side secrets needed)
fly secrets set API_SECRET=... -a anamnesis-web
```

Never put secrets in `fly.toml [env]` — those are visible in the config. Use `fly secrets set` for anything sensitive.

## Volumes

```bash
fly volumes create anamnesis_data --region ord --size 1 -a anamnesis-api
```

- SQLite DB lives on this volume at `/data/anamnesis.db`
- Volume name must match `[[mounts]].source` in fly.toml
- Volumes are region-pinned — the machine runs in the same region as its volume
- One volume per machine; if scaling to N machines, create N volumes

## Deploy commands

```bash
# First time
fly launch --no-deploy --name anamnesis-api
# Edit fly.toml, then:
fly volumes create anamnesis_data --region ord --size 1
fly deploy

# Subsequent deploys
fly deploy -a anamnesis-api
fly deploy -a anamnesis-web
```

## Scaling

```bash
fly scale show -a anamnesis-api
fly scale vm performance-2x -a anamnesis-api
fly scale memory 4096 -a anamnesis-api    # if 2GB isn't enough
fly scale count 1 -a anamnesis-api        # single instance for SQLite
```

SQLite constraint: only one machine can write to the volume. Keep backend at `count 1` unless migrating to LiteFS or Postgres.

## Debugging

```bash
fly logs -a anamnesis-api            # stream logs
fly ssh console -a anamnesis-api     # shell into the machine
fly status -a anamnesis-api          # machine status
fly checks list -a anamnesis-api     # health check results
```

## Gotchas

- **Model cold start**: sentence-transformers downloads on first import if not baked into the image. Always include model files in the Docker image or a volume.
- **Health check timing**: the default 10s grace period will fail — backend needs 60-120s to load models. Set `grace_period = "120s"`.
- **SQLite + volumes**: the DB path in `DATABASE_URL` must point to the mounted volume (`/data/`), not the app directory (ephemeral).
- **CORS**: backend CORS must allow the frontend app's fly.dev domain.
- **HuggingFace downloads**: set `HF_HOME=/data/hf_cache` if you want model cache to persist on the volume, or bake models into the image at build time.
