"""US Core profile URLs, terminology system URIs, and small lookup maps used by the FHIR builders."""
from __future__ import annotations

import re

_BP_LOINC = "85354-9"
_TOBACCO_LOINC = "72166-2"
_OCCUPATION_LOINC = "11341-5"
_SEXUAL_ORIENTATION_LOINC = "76690-7"
_FHIR_DATE_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
_NUM_RE = re.compile(r"^([<>≤≥]?)\s*([\d.]+)$")
_BP_RE = re.compile(r"(\d+)\s*/\s*(\d+)")
_AGE_RE = re.compile(r"(\d+)")
_ICD10_DOT_RE = re.compile(r"^([A-Z]\d{2})(\d+)$")

# Pinned base IG version. Profile canonicals below are unversioned (FHIR norm);
# this records which US Core package they resolve against (mCODE 4.0.0's substrate).
US_CORE_VERSION = "6.1.0"

# FamilyMemberHistory is intentionally absent: US Core 6.1.0 defines no FMH
# profile, so FamilyMemberHistory is emitted as base FHIR R4 (no meta.profile).
US_CORE_PROFILES: dict[str, str] = {
    "Condition-problem": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-condition-problems-health-concerns",
    "Condition-encounter": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-condition-encounter-diagnosis",
    "MedicationRequest": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-medicationrequest",
    "Procedure": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-procedure",
    "AllergyIntolerance": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-allergyintolerance",
    "Provenance": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-provenance",
}

OBS_PROFILES: dict[str, str] = {
    "vital-signs": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-vital-signs",
    "laboratory": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-observation-lab",
    "survey": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-observation-screening-assessment",
    "exam": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-simple-observation",
    "imaging": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-observation-clinical-result",
    "bp": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-blood-pressure",
    "smokingstatus": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-smokingstatus",
    "occupation": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-observation-occupation",
    "sexual-orientation": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-observation-sexual-orientation",
    # Fallback for other USCDI social-history facts (alcohol, substance use).
    "social-history": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-simple-observation",
    "heart-rate": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-heart-rate",
    "respiratory-rate": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-respiratory-rate",
    "body-temperature": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-body-temperature",
    "body-weight": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-body-weight",
    "body-height": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-body-height",
    "bmi": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-bmi",
    "pulse-oximetry": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-pulse-oximetry",
    "head-circumference": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-head-circumference",
}

# Specific US Core vital-sign profiles keyed by their required LOINC code. A
# vital carrying one of these codes uses the specific profile instead of the
# generic us-core-vital-signs. Codes mirror US_CORE_FIXED in code_candidates.py.
VITAL_PROFILE_BY_LOINC: dict[str, str] = {
    "8867-4": OBS_PROFILES["heart-rate"],
    "9279-1": OBS_PROFILES["respiratory-rate"],
    "8310-5": OBS_PROFILES["body-temperature"],
    "29463-7": OBS_PROFILES["body-weight"],
    "8302-2": OBS_PROFILES["body-height"],
    "39156-5": OBS_PROFILES["bmi"],
    "59408-5": OBS_PROFILES["pulse-oximetry"],
    "9843-4": OBS_PROFILES["head-circumference"],
}

_COMPARATOR_MAP = {"<": "<", ">": ">", "≤": "<=", "≥": ">="}

_CONDITION_VERIFY_MAP: dict[str, str] = {
    "definite": "confirmed",
    "probable": "provisional",
    "uncertain": "unconfirmed",
}

_ALLERGY_VERIFY_MAP: dict[str, str] = {
    "definite": "confirmed",
    "probable": "unconfirmed",
    "uncertain": "unconfirmed",
}

CONDITION_CATEGORY_MAP: dict[str, str] = {
    "diagnosis": "encounter-diagnosis",
    "problem": "problem-list-item",
}

_TOBACCO_SNOMED: dict[str, tuple[str, str]] = {
    "current": ("449868002", "Current every day smoker"),
    "ongoing": ("449868002", "Current every day smoker"),
    "active": ("449868002", "Current every day smoker"),
    "former": ("8517006", "Former smoker"),
    "quit": ("8517006", "Former smoker"),
    "never": ("266919005", "Never smoker"),
    "non-smoker": ("266919005", "Never smoker"),
}

_UCUM_CODES: dict[str, str] = {
    "%": "%", "mg": "mg", "mg/dL": "mg/dL", "g/dL": "g/dL",
    "mEq/L": "meq/L", "mmol/L": "mmol/L", "ng/mL": "ng/mL",
    "mmHg": "mm[Hg]", "kg": "kg", "cm": "cm", "mm": "mm", "bpm": "/min",
    "breaths/min": "/min", "kg/m2": "kg/m2",
}

_COND_CLINICAL_SYSTEM = "http://terminology.hl7.org/CodeSystem/condition-clinical"
_COND_VERIFY_SYSTEM = "http://terminology.hl7.org/CodeSystem/condition-ver-status"
_COND_CATEGORY_SYSTEM = "http://terminology.hl7.org/CodeSystem/condition-category"
_OBS_CATEGORY_SYSTEM = "http://terminology.hl7.org/CodeSystem/observation-category"
_ALLERGY_CLINICAL_SYSTEM = "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical"
_ALLERGY_VERIFY_SYSTEM = "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification"
