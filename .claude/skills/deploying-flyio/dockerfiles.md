# Dockerfiles

## Backend — Dockerfile.backend

```dockerfile
FROM python:3.13-slim AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
COPY backend/pyproject.toml backend/uv.lock ./
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.13-slim
WORKDIR /app

COPY --from=builder /install /usr/local
COPY backend/ .
COPY data/indexes/ /app/data/indexes/
COPY embeddings/ /app/embeddings/

ENV HF_HUB_DISABLE_PROGRESS_BARS=1 \
    HF_HUB_DISABLE_SYMLINKS_WARNING=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    HF_HUB_DISABLE_XET=1 \
    HF_HUB_VERBOSITY=error \
    TOKENIZERS_PARALLELISM=false \
    WARMUP_CODING_ON_STARTUP=true

EXPOSE 8042
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8042"]
```

Notes:
- `data/indexes/` is baked in (built offline via `scripts.build_indexes`)
- `embeddings/` is needed only if indexes need rebuilding — can omit if indexes are pre-built
- The sentence-transformers model downloads on first warmup and caches in HuggingFace's default cache dir; for reproducible deploys, pre-download it in the builder stage or mount a persistent volume at `HF_HOME`
- SQLite DB is NOT in the image — it lives on the mounted Fly volume at `/data/anamnesis.db`

### Pre-downloading the embedding model (optional, for reproducible builds)

Add to the builder stage:
```dockerfile
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
```

Then copy the cache:
```dockerfile
COPY --from=builder /root/.cache/huggingface /root/.cache/huggingface
```

## Frontend — Dockerfile.frontend

```dockerfile
FROM node:20-slim AS deps
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

FROM node:20-slim AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY frontend/ .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:20-slim
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1

COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public

EXPOSE 3042
CMD ["node", "server.js"]
```

Notes:
- Requires `output: "standalone"` in `next.config.ts` for the standalone build to work
- The standalone output produces a self-contained `server.js` (~15MB vs full node_modules)
- `NEXT_PUBLIC_*` env vars are baked in at build time — set them as build args or in fly.toml `[env]` before deploying

### next.config.ts change needed

```ts
const nextConfig: NextConfig = {
  output: "standalone",
  // ... existing config
};
```
