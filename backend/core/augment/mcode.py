"""mCODE specialty logic: select which candidate profile fits a built resource.

The generic bridge (EffectiveProfile.candidate_profiles) offers the profiles a
specialty IG *could* apply to a type; this module makes the per-resource call an
mCODE profile is a semantic claim, not a type tag. Classification is deterministic
(code text + ICD-10 ranges) so it runs without an LLM and stays testable.
"""
from __future__ import annotations

import re

from core.augment.overlay import merge_profiles
from core.mcode_obs import ROLE_TUMOR_MARKER, spec_for_codings

# Inherently-malignant terms; bare "tumor"/"neoplasm"/"-oma" omitted (can be
# benign: lipoma, adenoma). Specific malignant histologies are listed explicitly.
_CANCER_TERMS = (
    "cancer", "carcinoma", "melanoma", "lymphoma", "leukemia", "leukaemia",
    "sarcoma", "myeloma", "blastoma", "glioma", "mesothelioma", "malignant",
    "malignancy", "seminoma", "germinoma",
)
_SECONDARY_TERMS = ("secondary", "metastatic", "metastasis", "metastases", "metastat")

_ICD10_CM = "http://hl7.org/fhir/sid/icd-10-cm"


def _condition_text(resource: dict) -> str:
    code = resource.get("code") or {}
    parts = [code.get("text") or ""]
    parts += [c.get("display") or "" for c in code.get("coding") or []]
    return " ".join(parts).lower()


def _icd10_codes(resource: dict) -> list[str]:
    code = resource.get("code") or {}
    return [c.get("code") or "" for c in code.get("coding") or [] if c.get("system") == _ICD10_CM]


def has_cancer_signal(text: str) -> bool:
    return any(t in text.lower() for t in _CANCER_TERMS)


def classify_cancer_condition(resource: dict) -> str | None:
    """'primary' | 'secondary' | None — None means not a cancer condition.

    ICD-10-CM C77–C79 are secondary malignant neoplasms; any other C-code is a
    malignancy. Otherwise fall back to malignant terms in the code display/text,
    with 'secondary'/'metastatic' phrasing marking metastasis.
    """
    text = _condition_text(resource)
    icd = [c.upper() for c in _icd10_codes(resource)]
    malignant_icd = [c for c in icd if c.startswith("C")]
    if not has_cancer_signal(text) and not malignant_icd:
        return None
    if any(t in text for t in _SECONDARY_TERMS) or any(c[:3] in ("C77", "C78", "C79") for c in malignant_icd):
        return "secondary"
    return "primary"


def _select_for_role(role: str, candidate_profiles: list[str]) -> str | None:
    needle = f"mcode-{role}-cancer-condition"
    return next((p for p in candidate_profiles if needle in p), None)


def _select_by_needle(needle: str, candidate_profiles: list[str]) -> str | None:
    return next((p for p in candidate_profiles if needle in p), None)


def _reason_is_cancer(resource: dict) -> bool:
    """True when the resource's reasonCode names a cancer (the cancer-related signal)."""
    text = " ".join((rc.get("text") or "") for rc in (resource.get("reasonCode") or []))
    return has_cancer_signal(text)


# Laterality + generic anatomy words dropped so organ identity is what matches
# (so "right testis" == "testis", but "right inguinal region" != "prostate").
_SITE_STOPWORDS = frozenset({
    "left", "right", "bilateral", "region", "structure", "area", "site", "the", "of",
    "lobe", "upper", "lower", "outer", "inner", "quadrant", "proximal", "distal", "anterior", "posterior",
})


def body_site_tokens(resource: dict) -> set[str]:
    """Organ tokens from a resource's bodySite text (laterality/generic words removed)."""
    toks: set[str] = set()
    for b in resource.get("bodySite") or []:
        for w in re.findall(r"[a-z]+", (b.get("text") or "").lower()):
            if len(w) > 2 and w not in _SITE_STOPWORDS:
                toks.add(w)
    return toks


def _drop_primary_organ_bodysite(resource: dict, primary_sites: set[str] | None) -> None:
    """A metastasis is not located in the primary organ. If a secondary cancer's
    bodySite is wholly the primary cancer's site (the LLM leaked the origin organ
    onto a distant lesion), drop it — a missing bodySite beats a wrong one. Skipped
    when the met names a distinct site (keeps "bone"), or no primary is known."""
    if not primary_sites:
        return
    met = body_site_tokens(resource)
    if met and met <= primary_sites:
        resource.pop("bodySite", None)


def apply_specialty_profiles(
    resource: dict, resource_type: str, candidate_profiles: list[str],
    item: dict | None = None, cancer_sites: set[str] | None = None,
    primary_cancer_sites: set[str] | None = None,
) -> dict:
    """Select and attach the one specialty profile that fits this resource.

    Condition (primary/secondary cancer), Observation (fixed-code concepts +
    tumor markers), and cancer-related Procedure/MedicationRequest are resolved;
    other types pass through unchanged. A surgical procedure is cancer-related when
    its reason names a cancer OR its body site is a cancer's site (`cancer_sites`,
    the organ tokens of the run's cancer Conditions).
    """
    if not candidate_profiles:
        return resource
    selected = None
    if resource_type == "Condition":
        role = classify_cancer_condition(resource)
        if role is not None:
            selected = _select_for_role(role, candidate_profiles)
            if role == "secondary":
                _drop_primary_organ_bodysite(resource, primary_cancer_sites)
    elif resource_type == "Observation":
        spec = spec_for_codings((resource.get("code") or {}).get("coding") or [])
        if spec is not None:
            selected = _select_by_needle(f"mcode-{spec['profile']}", candidate_profiles)
        elif item and item.get("mcode_role") == ROLE_TUMOR_MARKER:
            selected = _select_by_needle("mcode-tumor-marker-test", candidate_profiles)
    elif resource_type == "Procedure":
        site_match = bool(cancer_sites and body_site_tokens(resource) & cancer_sites)
        if (item or {}).get("category") == "surgical" and (_reason_is_cancer(resource) or site_match):
            selected = _select_by_needle("mcode-cancer-related-surgical-procedure", candidate_profiles)
    elif resource_type == "MedicationRequest":
        if _reason_is_cancer(resource):
            selected = _select_by_needle("mcode-cancer-related-medication-request", candidate_profiles)
    if selected:
        merge_profiles(resource, [selected])
    return resource
