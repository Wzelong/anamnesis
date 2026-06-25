"""Specialty IG prompt contributions for stage 2 (capture + extract).

Mirrors the candidate-profiles bridge: when a specialty IG is active, it layers
add-only guidance onto the validated base prompts so extraction surfaces the
concepts the structural builders need (e.g. names a metastasis recognizably,
keeps a negative receptor result). Generic seam (`specialty_prompt_addons`),
per-specialty content. Empty for an unknown/None specialty -> base unchanged.
"""
from __future__ import annotations

# extract: add-only, appended to the per-type parse prompt.
# capture: additive, appended inside that type's scan-routing block.

_CONDITION_EXTRACT = """\
Oncology (mCODE) — when the snippet describes cancer:
- Name the tumor by its histology and type as written ("infiltrating ductal carcinoma", "ductal carcinoma in situ") so it resolves to a SNOMED cancer disorder.
- Set body_site to the cancer's anatomic site ("right breast", "lower outer quadrant"); the body location is coded separately.
- Name a metastasis as "metastatic <type>" or "secondary malignant neoplasm of <site>" so spread is distinguishable from a new primary — the two map to different mCODE profiles. Leave a primary tumor named by its site of origin.
- "secondary" here means metastatic. Do not treat "secondary malignant neoplasm" as an "X secondary to Y" split."""

_OBSERVATION_EXTRACT = """\
Oncology (mCODE) — capture these as observation results:
- Performance status named "ECOG performance status" (value 0-4) or "Karnofsky" (value 0-100).
- Histologic grade named "histologic grade" with the stated value ("high grade", "grade 3").
- Primary tumor or mass size named "tumor size" with the measured greatest dimension and unit ("3.2 cm").
- Cancer disease status named "cancer disease status" with the trend value ("stable", "responding", "progressing").
- Overall stage group named "stage group" with the AJCC roman-numeral value ("IIA", "IIIB"), emitted even when the stage is written in the same sentence as the diagnosis.
- A TNM string ("pT2N1M0", "cT3 N0 M0") is three separate observations, not one: emit primary tumor (value "pT2"), regional nodes (value "N1"), and distant metastases (value "M0"), each preserving the c/p/y/r prefix. Keep a single category token intact ("Tis", "NX").
- Tumor markers and receptors (ER, PR, HER2, Ki-67, PSA, CEA, AFP, hCG): a negative result is as decisive as a positive one (HER2-negative changes treatment), so emit these assays even when the value is "negative". This is the exception to the pertinent-negative rule, which is meant for review-of-systems and exam findings, not assays."""

_PROCEDURE_EXTRACT = """\
Oncology (mCODE): for a surgical procedure that treats or diagnoses cancer (resection, excision, an -ectomy, or a tumor biopsy), set reason to the cancer it addresses ("breast cancer") so it is recognized as cancer-related."""

_MEDICATION_EXTRACT = """\
Oncology (mCODE): for a cancer-directed medication (chemotherapy, hormone therapy, targeted or immunotherapy agent), set reason to the cancer it treats ("breast cancer")."""

_OBSERVATION_CAPTURE = """\
Oncology results to capture: route a cancer stage or TNM statement ("stage IIIB", "T2 N0 M0") to Observation even when it shares a sentence with the diagnosis. Treat tumor-marker and receptor assays (ER, PR, HER2, Ki-67, PSA, CEA, AFP, hCG), cancer disease status, and histologic grade as results to include even when the value is negative — a "HER2 negative" assay drives treatment, unlike a review-of-systems negative."""

_ADDONS: dict[str, dict[str, dict[str, str]]] = {
    "mcode@4.0.0": {
        "Condition": {"extract": _CONDITION_EXTRACT},
        "Observation": {"extract": _OBSERVATION_EXTRACT, "capture": _OBSERVATION_CAPTURE},
        "Procedure": {"extract": _PROCEDURE_EXTRACT},
        "MedicationRequest": {"extract": _MEDICATION_EXTRACT},
    },
}


def specialty_prompt_addons(specialty_id: str | None) -> dict[str, dict[str, str]]:
    """{resource_type: {"extract": str, "capture": str}} a specialty IG contributes."""
    return _ADDONS.get(specialty_id or "", {})
