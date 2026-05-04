"""US Core profile URLs, terminology system URIs, and small lookup maps used by the FHIR builders."""
from __future__ import annotations

import re

_BP_LOINC = "85354-9"
_TOBACCO_LOINC = "72166-2"
_FHIR_DATE_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
_NUM_RE = re.compile(r"^([<>≤≥]?)\s*([\d.]+)$")
_BP_RE = re.compile(r"(\d+)\s*/\s*(\d+)")
_AGE_RE = re.compile(r"(\d+)")
_ICD10_DOT_RE = re.compile(r"^([A-Z]\d{2})(\d+)$")

US_CORE_PROFILES: dict[str, str] = {
    "Condition-problem": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-condition-problems-health-concerns",
    "Condition-encounter": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-condition-encounter-diagnosis",
    "MedicationRequest": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-medicationrequest",
    "Procedure": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-procedure",
    "AllergyIntolerance": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-allergyintolerance",
    "FamilyMemberHistory": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-familymemberhistory",
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
    "mmHg": "mm[Hg]", "kg": "kg", "cm": "cm", "bpm": "/min",
    "breaths/min": "/min", "kg/m2": "kg/m2",
}

_COND_CLINICAL_SYSTEM = "http://terminology.hl7.org/CodeSystem/condition-clinical"
_COND_VERIFY_SYSTEM = "http://terminology.hl7.org/CodeSystem/condition-ver-status"
_COND_CATEGORY_SYSTEM = "http://terminology.hl7.org/CodeSystem/condition-category"
_OBS_CATEGORY_SYSTEM = "http://terminology.hl7.org/CodeSystem/observation-category"
_ALLERGY_CLINICAL_SYSTEM = "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical"
_ALLERGY_VERIFY_SYSTEM = "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification"
