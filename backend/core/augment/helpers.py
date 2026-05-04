"""Validation, parsing, and CodeableConcept helpers shared by the builders."""
from __future__ import annotations

from core.augment.config import (
    _AGE_RE,
    _ALLERGY_VERIFY_MAP,
    _ALLERGY_VERIFY_SYSTEM,
    _BP_RE,
    _COND_VERIFY_SYSTEM,
    _CONDITION_VERIFY_MAP,
    _FHIR_DATE_RE,
    _ICD10_DOT_RE,
    _NUM_RE,
)
from core.reconcile import _DISCONTINUED_STATUSES
from core.schemas import MergedCandidate


def _is_negated_assertion(c: MergedCandidate) -> bool:
    if c.resource_type == "Condition" and c.item.get("negated"):
        return True
    if c.resource_type == "MedicationRequest" and c.item.get("status") in _DISCONTINUED_STATUSES:
        return True
    return False


def _strip_none(d: dict | list) -> dict | list:
    if isinstance(d, list):
        return [_strip_none(v) for v in d if v is not None]
    if not isinstance(d, dict):
        return d
    out = {}
    for k, v in d.items():
        if v is None:
            continue
        if isinstance(v, dict):
            v = _strip_none(v)
            if not v:
                continue
        elif isinstance(v, list):
            v = _strip_none(v)
            if not v:
                continue
        out[k] = v
    return out


def _cc(coding: list[dict], text: str) -> dict:
    valid = [c for c in coding if c.get("system") and c.get("code")]
    if valid:
        return {"coding": valid, "text": text}
    fallback_text = text or next(
        (c.get("text") or c.get("display") or "" for c in coding if c.get("text") or c.get("display")),
        "",
    )
    return {"text": fallback_text} if fallback_text else {}


def _cond_verification(certainty: str) -> dict:
    code = _CONDITION_VERIFY_MAP.get(certainty, "provisional")
    return {"coding": [{"system": _COND_VERIFY_SYSTEM, "code": code}]}


def _allergy_verification(certainty: str) -> dict:
    code = _ALLERGY_VERIFY_MAP.get(certainty, "unconfirmed")
    return {"coding": [{"system": _ALLERGY_VERIFY_SYSTEM, "code": code}]}


def _parse_bp(value_str: str) -> tuple[int, int] | None:
    m = _BP_RE.search(value_str)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _parse_onset_age(s: str) -> int | None:
    m = _AGE_RE.search(s)
    return int(m.group(1)) if m else None


def _is_numeric(v: str) -> bool:
    return bool(_NUM_RE.match(v.strip()))


def _normalize_icd10(code: str) -> str:
    m = _ICD10_DOT_RE.match(code.strip())
    if m:
        return f"{m.group(1)}.{m.group(2)}"
    return code


def _normalize_coding(coding_list: list[dict]) -> list[dict]:
    out = []
    for c in coding_list:
        c = dict(c)
        if c.get("system") == "http://hl7.org/fhir/sid/icd-10-cm" and c.get("code"):
            c["code"] = _normalize_icd10(c["code"])
        out.append(c)
    return out


def _is_valid_fhir_date(s: str) -> bool:
    return bool(_FHIR_DATE_RE.match(s))
