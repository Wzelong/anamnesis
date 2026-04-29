---
name: fhir-us-core
description: FHIR R4 US Core 6.1.0 profile requirements and code bindings. Use when constructing FHIR resources, validating profiles, assigning terminology codes, or building CodeableConcept/coding arrays for Condition, Observation, MedicationRequest, Procedure, AllergyIntolerance, or FamilyMemberHistory resources.
---

# FHIR R4 US Core 6.1.0 Quick Reference

## Code System URIs

```python
SYSTEM_URIS = {
    "snomed":   "http://snomed.info/sct",
    "loinc":    "http://loinc.org",
    "rxnorm":   "http://www.nlm.nih.gov/research/umls/rxnorm",
    "icd10cm":  "http://hl7.org/fhir/sid/icd-10-cm",
    "ucum":     "http://unitsofmeasure.org",
    "obs_cat":  "http://terminology.hl7.org/CodeSystem/observation-category",
    "cond_cat": "http://terminology.hl7.org/CodeSystem/condition-category",
}
```

## Profile Quick Reference

| Resource | US Core Profile | Code Binding | Strength | Preferred Systems |
|---|---|---|---|---|
| Condition | us-core-condition-problems-health-concerns | US Core Condition Codes | Extensible | SNOMED CT + ICD-10-CM |
| MedicationRequest | us-core-medicationrequest | Medication Clinical Drug | Extensible | RxNorm |
| Observation (vitals) | us-core-vital-signs + specific | Fixed per profile | Required | LOINC |
| Observation (smoking) | us-core-smokingstatus | LOINC 72166-2 | Extensible | LOINC |
| Observation (labs) | us-core-observation-lab | LOINC | Extensible | LOINC |
| Procedure | us-core-procedure | US Core Procedure Codes | Extensible | SNOMED CT + CPT |
| AllergyIntolerance | us-core-allergyintolerance | (extensible) | Extensible | SNOMED CT, RxNorm |
| FamilyMemberHistory | (no US Core profile) | — | — | SNOMED CT |

## Vital Signs Fixed LOINC Codes

These codes are **required** by US Core — bypass terminology search entirely:

| Vital Sign | LOINC | Display | Units (UCUM) | Category |
|---|---|---|---|---|
| Blood Pressure (panel) | 85354-9 | Blood pressure panel | — | vital-signs |
| — Systolic (component) | 8480-6 | Systolic blood pressure | mm[Hg] | |
| — Diastolic (component) | 8462-4 | Diastolic blood pressure | mm[Hg] | |
| Body Weight | 29463-7 | Body weight | kg, [lb_av] | vital-signs |
| Body Height | 8302-2 | Body height | cm, [in_i] | vital-signs |
| Body Temperature | 8310-5 | Body temperature | Cel, [degF] | vital-signs |
| Heart Rate | 8867-4 | Heart rate | /min | vital-signs |
| Respiratory Rate | 9279-1 | Respiratory rate | /min | vital-signs |
| BMI | 39156-5 | Body mass index | kg/m2 | vital-signs |
| Pulse Oximetry | 59408-5 | SpO2 by pulse oximetry | % | vital-signs |
| — O2 Sat (secondary code) | 2708-6 | O2 saturation in arterial blood | % | |
| — Flow Rate (component) | 3151-8 | Inhaled O2 flow rate | L/min | |
| — Concentration (component) | 3150-0 | Inhaled O2 concentration | % | |
| Head Circumference | 9843-4 | Head circumference | cm, [in_i] | vital-signs |
| Smoking Status | 72166-2 | Tobacco smoking status | CodeableConcept | social-history |

## Binding Strength Rules

- **Required**: SHALL use a code from the value set. No alternatives.
- **Extensible**: SHALL use from value set if an applicable concept exists. May use other codes only if no suitable match.
- **Preferred**: SHOULD use from value set. Other codes acceptable.

For `CodeableConcept` with extensible binding: at least one `coding` entry must be from the required/extensible value set if a match exists. Additional codings from other systems are allowed alongside.

## Common Category Codes

**Condition.category** (required binding):
- `problem-list-item` — Problems and diagnoses
- `health-concern` — Health concerns

**Observation.category** (required pattern):
- `vital-signs` — Vital signs observations
- `laboratory` — Lab results
- `social-history` — Social history (smoking status)
- `exam` — Physical exam findings
- `imaging` — Imaging results
- `survey` — Survey/screening

## Status Enums

**Condition.clinicalStatus**: active | recurrence | relapse | inactive | remission | resolved

**MedicationRequest.status**: active | on-hold | cancelled | completed | stopped | draft | unknown

**MedicationRequest.intent**: proposal | plan | order | original-order | instance-order

**Observation.status**: registered | preliminary | final | amended | corrected | cancelled | entered-in-error | unknown

**Procedure.status**: preparation | in-progress | not-done | on-hold | stopped | completed | entered-in-error | unknown

## Detailed Profile Specs

See [profiles.md](profiles.md) for must-support elements, constraints, and FHIR resource construction patterns per profile.
