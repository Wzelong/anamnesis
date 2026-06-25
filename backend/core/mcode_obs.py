"""mCODE fixed-code observations: recognition + structure spec.

Shared, lightweight (pure data + string matching, no pipeline imports) so both
stage 4 (assign the fixed code, skip retrieval) and stage 6 (shape value[x],
select the profile) can use it. These mCODE observations pin `.code`, so the
concept name alone determines the code — terminology search is bypassed.
"""
from __future__ import annotations

import re

_LOINC = "http://loinc.org"
_NCIT = "http://ncicb.nci.nih.gov/xml/owl/EVS/Thesaurus.owl"

# Ordered: more specific terms first. `profile` is the mCODE slug (sans canonical
# prefix); `value` is how the builder shapes value[x] (integer | codeable).
MCODE_OBS: list[dict] = [
    {"terms": ("ecog",), "system": _LOINC, "code": "89247-1",
     "display": "ECOG performance status", "profile": "ecog-performance-status", "value": "integer"},
    {"terms": ("karnofsky",), "system": _LOINC, "code": "89243-0",
     "display": "Karnofsky Performance Status score", "profile": "karnofsky-performance-status", "value": "integer"},
    {"terms": ("cancer disease status", "disease status"), "system": _LOINC, "code": "97509-4",
     "display": "Cancer disease status", "profile": "cancer-disease-status", "value": "codeable"},
    {"terms": ("histologic grade", "histological grade", "tumor grade", "tumour grade", "nuclear grade"),
     "system": _NCIT, "code": "C18000", "display": "Grade", "profile": "histologic-grade", "value": "codeable"},
    {"terms": ("histologic behavior", "histologic type", "histology and behavior"), "system": _LOINC,
     "code": "31206-6", "display": "Histology and behavior ICD-O-3", "profile": "histologic-behavior-and-type", "value": "codeable"},
    {"terms": ("tnm stage", "ajcc stage", "stage group", "overall stage", "cancer stage",
               "tumor stage", "pathologic stage", "clinical stage", "stage"), "system": _LOINC,
     "code": "21908-9", "display": "Stage group.clinical Cancer", "profile": "tnm-stage-group", "value": "codeable"},
    {"terms": ("tumor size", "tumor greatest dimension", "greatest dimension", "tumor dimension",
               "tumor maximum dimension", "size of tumor", "mass size", "size of mass"), "system": _LOINC,
     "code": "21889-1", "display": "Size.maximum dimension Tumor", "profile": "tumor-size", "value": "quantity"},
]

_BY_CODE = {(e["system"], e["code"]): e for e in MCODE_OBS}
_INT_RE = re.compile(r"-?\d+")

# TNM categories: code is value-dependent (pathologic 'pT' vs clinical 'cT'/bare
# use different LOINCs), so they're recognized by the value TOKEN, not a name.
# Both codes per category feed the reverse map so the builder/selector pick up
# either. The LLM is prompted to split a combined "pT2N1M0" into three of these.
_TNM = {
    "T": ("tnm-primary-tumor-category", ("21905-5", "Primary tumor.clinical [Class] Cancer"), ("21899-0", "Primary tumor.pathology [Class] Cancer")),
    "N": ("tnm-regional-nodes-category", ("21906-3", "Regional lymph nodes.clinical [Class] Cancer"), ("21900-6", "Regional lymph nodes.pathology [Class] Cancer")),
    "M": ("tnm-distant-metastases-category", ("21907-1", "Distant metastases.clinical [Class] Cancer"), ("21901-4", "Distant metastases.pathology [Class] Cancer")),
}
for _letter, (_prof, _clin, _path) in _TNM.items():
    for _code, _disp in (_clin, _path):
        _BY_CODE[(_LOINC, _code)] = {"system": _LOINC, "code": _code, "display": _disp, "profile": _prof, "value": "codeable"}

_TNM_VALUE_RE = re.compile(r"(?i)^\s*([cpyr]*)([tnm])(is|x|\d[a-d]?)\s*$")


def match_tnm_category(value: str) -> list[dict] | None:
    """Fixed coding for a single TNM category token (T2, pN1, cM0, Tis, NX), or None.

    Value-driven: a combined token like 'pT2N1M0' does not match (the LLM splits
    those upstream); a stage group like 'IIA' has no T/N/M letter so it falls
    through to the stage-group recognizer."""
    m = _TNM_VALUE_RE.match(value or "")
    if not m:
        return None
    _prof, clin, path = _TNM[m.group(2).upper()]
    code, disp = path if "p" in m.group(1).lower() else clin
    return [{"system": _LOINC, "code": code, "display": disp}]

# Tumor markers: code is RETRIEVED (LOINC), not fixed — so these are recognized by
# name and carry a role tag rather than a fixed code. ROLE is set in stage 4 (only
# when the specialty is active), so it doubles as the mCODE-active signal downstream.
ROLE_TUMOR_MARKER = "tumor-marker"

# Matched separator-insensitively, so "alpha-fetoprotein" == "alpha fetoprotein".
_TM_LONG = (
    "estrogen receptor", "progesterone receptor", "her2", "her2/neu",
    "epidermal growth factor receptor",  # HER2/EGFR spelled out
    "prostate specific antigen", "carcinoembryonic antigen", "alpha fetoprotein",
    "human chorionic gonadotropin", "choriogonadotropin", "hcg",
    "ca 15-3", "ca 27-29", "ca 125", "ca 19-9", "ki-67", "tumor marker",
)


def _norm(s: str) -> str:
    return re.sub(r"[\s\-/,]+", "", (s or "").lower())


_TM_NORM = tuple(_norm(t) for t in _TM_LONG)
_TM_SHORT_RE = re.compile(r"\b(er|pr|her2|psa|cea|afp|hcg|ki[\s-]?67)\b", re.IGNORECASE)


def is_tumor_marker(name: str) -> bool:
    return any(t in _norm(name) for t in _TM_NORM) or bool(_TM_SHORT_RE.search(name or ""))


def match_mcode_obs(name: str) -> dict | None:
    """The mCODE fixed-observation spec a concept name names, or None."""
    n = (name or "").lower()
    return next((e for e in MCODE_OBS if any(t in n for t in e["terms"])), None)


def fixed_coding(spec: dict) -> list[dict]:
    return [{"system": spec["system"], "code": spec["code"], "display": spec["display"]}]


def spec_for_codings(codings: list[dict]) -> dict | None:
    """Reverse lookup: the spec for a built resource's codings (by system+code)."""
    for c in codings or []:
        e = _BY_CODE.get((c.get("system"), c.get("code")))
        if e:
            return e
    return None


def parse_int(value: str) -> int | None:
    m = _INT_RE.search(value or "")
    return int(m.group()) if m else None
