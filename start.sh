#!/bin/bash
set -e

mkdir -p /data /data/hf_cache /data/indexes

cd /app/backend && python -m uvicorn main:app --host 127.0.0.1 --port 8042 &

cd /app/frontend && PORT=3042 HOSTNAME=0.0.0.0 node server.js &

wait -n
exit 1
