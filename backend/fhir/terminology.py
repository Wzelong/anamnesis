"""FHIR terminology service client — VSAC value-set resolution + code grounding.

Resolves a VSAC OID or ValueSet canonical URL to its expanded code list via the
NLM VSAC FHIR service (`$expand`), and grounds AI-extracted codes against their
code systems (`$validate-code`). Auth is UMLS API key Basic auth (`apikey:KEY`).

This backs the "scope to value set" feature (CONFORMANCE.md): a preset can pin a
resource type to a value set; the pipeline then produces only in-set codes.
Authoritative value sets are resolved here, never AI-parsed; AI output (freeform
paste) is grounded here before it enters a preset. The app HTTP-calls the public
NLM service, so no dedicated validator is required for VSAC content.
"""
from __future__ import annotations

import base64
import re

import httpx

VSAC_FHIR_BASE = "https://cts.nlm.nih.gov/fhir"
_OID_RE = re.compile(r"^[0-2](\.\d+)+$")
_PAGE = 1000  # VSAC returns one example code above 1200 unless paged
_TIMEOUT = 30.0


class TerminologyError(RuntimeError):
    pass


def is_oid(ref: str) -> bool:
    ref = ref.strip().replace("urn:oid:", "")
    return bool(_OID_RE.match(ref))


def _auth_header(umls_key: str) -> dict[str, str]:
    token = base64.b64encode(f"apikey:{umls_key}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Accept": "application/fhir+json"}


def _expansion_codes(body: dict | None) -> list[dict]:
    contains = ((body or {}).get("expansion") or {}).get("contains") or []
    return [
        {"system": c["system"], "code": c["code"], "display": c.get("display", "")}
        for c in contains
        if c.get("system") and c.get("code")
    ]


def _expansion_total(body: dict | None) -> int | None:
    return ((body or {}).get("expansion") or {}).get("total")


def _dedupe(codes: list[dict]) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for c in codes:
        key = (c["system"], c["code"])
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def _validate_code_result(body: dict | None) -> bool:
    for p in (body or {}).get("parameter", []):
        if p.get("name") == "result":
            return bool(p.get("valueBoolean"))
    return False


async def _http_get(url: str, headers: dict, params: dict) -> tuple[int, dict | None]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get(url, headers=headers, params=params)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, None


async def expand_valueset(ref: str, umls_key: str, *, get=_http_get) -> list[dict]:
    """Resolve a VSAC OID or ValueSet URL to its full, deduped expansion.

    Pages with count/offset to clear VSAC's 1200-code single-example cap. Raises
    TerminologyError on a non-200 response. `get` is injectable for tests.
    """
    if not umls_key:
        raise TerminologyError("UMLS API key required for value-set expansion")
    ref = ref.strip()
    headers = _auth_header(umls_key)
    if is_oid(ref):
        url = f"{VSAC_FHIR_BASE}/ValueSet/{ref.replace('urn:oid:', '')}/$expand"
        base_params: dict = {}
    else:
        url = f"{VSAC_FHIR_BASE}/ValueSet/$expand"
        base_params = {"url": ref}

    codes: list[dict] = []
    offset = 0
    while True:
        status, body = await get(url, headers, {**base_params, "count": _PAGE, "offset": offset})
        if status != 200 or not isinstance(body, dict):
            raise TerminologyError(f"$expand failed ({status}) for {ref}")
        page = _expansion_codes(body)
        codes.extend(page)
        offset += len(page)
        total = _expansion_total(body)
        if not page or len(page) < _PAGE or (total is not None and offset >= total):
            break
    return _dedupe(codes)


async def validate_code(system: str, code: str, umls_key: str, *, get=_http_get) -> bool:
    """True if `code` exists in `system` per VSAC $validate-code. Grounds AI output."""
    if not (system and code and umls_key):
        return False
    status, body = await get(
        f"{VSAC_FHIR_BASE}/CodeSystem/$validate-code",
        _auth_header(umls_key),
        {"url": system, "code": code},
    )
    return status == 200 and _validate_code_result(body)


async def ground_codes(codes: list[dict], umls_key: str, *, get=_http_get) -> list[dict]:
    """Keep only codes that validate against their code system — drops AI hallucinations."""
    kept: list[dict] = []
    for c in codes:
        if await validate_code(c.get("system", ""), c.get("code", ""), umls_key, get=get):
            kept.append(c)
    return kept
