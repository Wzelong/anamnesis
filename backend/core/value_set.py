"""Lane B of "scope to value set" (CONFORMANCE.md): parse a freeform code list with
the LLM, then ground every code against VSAC.

The model handles messy human input (CSV, pasted lists, measure-spec excerpts) and
maps each code to a supported terminology system; the terminology service is the
source of truth, so no hallucinated or mistyped code enters a preset. Authoritative
value sets (OID/URL) are NOT parsed here — they are resolved via fhir.terminology.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from core.llm import build_client, generate_structured
from core.systems import SYSTEM_URIS as SUPPORTED_SYSTEMS
from core.systems import VALIDATABLE_URIS
from fhir.terminology import ground_codes

_SUPPORTED_URIS = set(SUPPORTED_SYSTEMS.values())

_SYSTEM_PROMPT = """\
You extract medical terminology codes from arbitrary user-supplied text into a \
structured list. The text may be a CSV, a pasted code list, or an excerpt from a \
quality-measure or registry specification.

For every code you find, emit its terminology system as the canonical FHIR system \
URI. Only these systems are supported:
- SNOMED CT -> http://snomed.info/sct
- LOINC -> http://loinc.org
- RxNorm -> http://www.nlm.nih.gov/research/umls/rxnorm
- ICD-10-CM -> http://hl7.org/fhir/sid/icd-10-cm
- ICD-10-PCS -> http://www.cms.gov/Medicare/Coding/ICD10
- HCPCS -> http://www.cms.gov/Medicare/Coding/HCPCSReleaseCodeSets

Identify the system from explicit labels in the text first (e.g. a column header or \
"ICD-10:" prefix), then from the code's format as a fallback (ICD-10-CM has a letter \
then digits with an optional dot like E11.9; ICD-10-PCS is a 7-character alphanumeric \
string like 0DTJ0ZZ; HCPCS Level II is a letter then four digits like E1130 or J1885; \
LOINC is digits-dash-digit like 4548-4; RxNorm and SNOMED CT are plain integers, \
distinguished by surrounding context). If a code's system is ambiguous or not one of \
the supported systems, omit that code rather than guessing. Preserve any display text \
given for a code; leave it empty if none is provided. Do not invent codes that are not \
present in the input.\
"""


class ParsedCode(BaseModel):
    system: str = Field(description="Canonical FHIR system URI")
    code: str = Field(description="The code value exactly as it should appear in FHIR")
    display: str = Field(default="", description="Human-readable display, empty if unknown")


class ParsedCodes(BaseModel):
    codes: list[ParsedCode]


def _supported(codes: list[dict]) -> list[dict]:
    """Keep codes whose system is one of the supported URIs and has a code value."""
    return [c for c in codes if c.get("system") in _SUPPORTED_URIS and c.get("code")]


async def parse_codes(text: str, *, gemini_key: str, umls_key: str, model: str, get=None) -> dict:
    """Parse freeform `text` into codes, then ground them against VSAC.

    Returns {codes, parsed, grounded, error}. `codes` are only the grounded ones.
    `get` is injectable for tests (passed through to the terminology client).
    """
    if not (text and text.strip()):
        return {"codes": [], "parsed": 0, "grounded": 0, "error": None}

    client = build_client(gemini_key)
    parsed, _usage, error = await generate_structured(
        client, model, system=_SYSTEM_PROMPT, user=text, schema=ParsedCodes, thinking="low",
    )
    if error or parsed is None:
        return {"codes": [], "parsed": 0, "grounded": 0, "error": error or "no_output"}

    raw = _supported([{"system": c.system, "code": c.code, "display": c.display} for c in parsed.codes])
    # Validate only systems we can $validate-code; trust asserted codes from systems
    # we can't (CPT, ICD-O-3, ...) — they enter the codeset ungrounded by design.
    checkable = [c for c in raw if c["system"] in VALIDATABLE_URIS]
    asserted = [c for c in raw if c["system"] not in VALIDATABLE_URIS]
    grounded = await ground_codes(checkable, umls_key, **({"get": get} if get is not None else {}))
    codes = grounded + asserted
    return {"codes": codes, "parsed": len(raw), "grounded": len(grounded), "error": None}
