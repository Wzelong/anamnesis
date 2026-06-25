"""Backend reader for the shared IG catalog.

Single source of truth with the frontend: `shared/ig/catalog.json` drives both
the config UI and the backend's specialty -> profile resolution. Adding an IG is
a JSON edit, picked up by both sides. The catalog stays declarative; selecting
which profile actually applies to a given resource is the builder's job (see
`candidate profiles` below).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from core.systems import SYSTEM_URIS

_CATALOG_PATH = Path(__file__).resolve().parents[2] / "shared" / "ig" / "catalog.json"


@lru_cache(maxsize=1)
def _catalog() -> dict:
    return json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))


def _ig_by_id(ig_id: str) -> dict | None:
    cat = _catalog()
    for d in (*cat.get("base", []), *cat.get("specialties", [])):
        if isinstance(d, dict) and d.get("id") == ig_id:
            return d
    return None


def specialty_candidate_profiles(specialty_id: str | None) -> dict[str, list[str]]:
    """Per-resource-type candidate profiles a specialty IG contributes.

    These are *candidates*, not unconditional overlays: a resource is tagged with
    at most one (e.g. a Condition is primary OR secondary cancer), so a downstream
    builder/classifier selects the fitting profile. Empty for an unknown/None IG.
    """
    ig = _ig_by_id(specialty_id) if specialty_id else None
    if not ig:
        return {}
    out: dict[str, list[str]] = {}
    for rt, rule in (ig.get("resources") or {}).items():
        profiles = [p for p in (rule.get("profiles") or []) if isinstance(p, str)]
        if profiles:
            out[rt] = profiles
    return out


def fixed_codings(base_id: str | None, specialty_id: str | None, rt: str) -> list[dict]:
    """Codes a resource type's active profiles pin (declared per IG in the catalog).

    The pipeline assigns these deterministically, bypassing retrieval; surfaced
    read-only in the config UI and always permitted by the codeset allow-list so a
    restrictive preset can't drop a conformance-required fixed code. `system` is the
    canonical URI; entries from base + specialty are merged (deduped by system+code).
    """
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for ig_id in (base_id, specialty_id):
        ig = _ig_by_id(ig_id) if ig_id else None
        if not ig:
            continue
        for e in ((ig.get("resources") or {}).get(rt) or {}).get("fixed") or []:
            code = e.get("code")
            uri = SYSTEM_URIS.get(e.get("system"), e.get("system"))
            if not code or not uri or (uri, code) in seen:
                continue
            seen.add((uri, code))
            out.append({"system": uri, "code": code, "display": e.get("display", "")})
    return out
