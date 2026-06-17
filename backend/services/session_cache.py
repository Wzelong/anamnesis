"""In-process TTL cache for stateless review sessions.

PHI (proposals, source documents) lives here only — never on disk. Keyed by
opaque run_id, evicted after the TTL. A later call may land on a different
worker under stateless HTTP, so callers must treat a miss as normal and fall
back to client-supplied payloads.
"""
from __future__ import annotations

import time
from threading import Lock

_TTL_SECONDS = 60 * 60
_store: dict[str, dict] = {}
_lock = Lock()


def put(run_id: str, payload: dict) -> None:
    with _lock:
        _evict()
        _store[run_id] = {"at": time.time(), "payload": payload}


def get(run_id: str) -> dict | None:
    with _lock:
        _evict()
        entry = _store.get(run_id)
        return entry["payload"] if entry else None


def drop(run_id: str) -> None:
    with _lock:
        _store.pop(run_id, None)


def _evict() -> None:
    cutoff = time.time() - _TTL_SECONDS
    for key in [k for k, v in _store.items() if v["at"] < cutoff]:
        _store.pop(key, None)
