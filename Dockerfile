# ---- Stage 1: Build Next.js frontend ----
FROM node:20-slim AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
ENV NEXT_PUBLIC_API_URL=""
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ---- Stage 2: Python deps + model download ----
FROM python:3.13-slim AS backend-build
WORKDIR /build

RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir uv

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev

ENV HF_HOME=/build/hf_cache
ENV HF_HUB_DISABLE_PROGRESS_BARS=1
ENV HF_HUB_DISABLE_TELEMETRY=1
RUN . .venv/bin/activate && python -c \
    "from sentence_transformers import SentenceTransformer; SentenceTransformer('cambridgeltl/SapBERT-from-PubMedBERT-fulltext')"

# ---- Stage 3: Runtime ----
FROM python:3.13-slim
WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

COPY --from=backend-build /build/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

COPY --from=backend-build /build/hf_cache /app/hf_cache

COPY backend/ /app/backend/
COPY data/indexes/*.faiss data/indexes/*_metadata.parquet data/indexes/build_manifest.json /app/data/indexes/
COPY data/demo_patient/ /app/data/demo_patient/
COPY data/demo_fixture.json /app/data/demo_fixture.json

COPY --from=frontend-build /build/.next/standalone /app/frontend/
COPY --from=frontend-build /build/.next/static /app/frontend/.next/static
COPY --from=frontend-build /build/public /app/frontend/public

COPY start.sh /app/start.sh
RUN sed -i 's/\r$//' /app/start.sh && chmod +x /app/start.sh

ENV HF_HOME=/app/hf_cache \
    HF_HUB_OFFLINE=1 \
    HF_HUB_DISABLE_PROGRESS_BARS=1 \
    HF_HUB_DISABLE_SYMLINKS_WARNING=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    HF_HUB_DISABLE_XET=1 \
    HF_HUB_VERBOSITY=error \
    TOKENIZERS_PARALLELISM=false \
    NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1

EXPOSE 3042

CMD ["/app/start.sh"]
