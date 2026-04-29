# US Core 6.1.0 Profile Details

## Condition (us-core-condition-problems-health-concerns)

Profile URL: `http://hl7.org/fhir/us/core/StructureDefinition/us-core-condition-problems-health-concerns`

**Required elements:**
- `category` (1..*): required binding — "problem-list-item" or "health-concern"
- `code` (1..1): extensible binding — SNOMED CT + ICD-10-CM preferred
- `subject` (1..1): reference to US Core Patient

**Must-support:**
- clinicalStatus, verificationStatus, category, code, subject
- onset[x] (onsetDateTime), abatement[x] (abatementDateTime), recordedDate
- assertedDate extension

**Code construction:**
```json
{
  "code": {
    "coding": [
      {"system": "http://snomed.info/sct", "code": "44054006", "display": "Type 2 diabetes mellitus"},
      {"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "E11.9", "display": "Type 2 diabetes mellitus without complications"}
    ],
    "text": "Type 2 diabetes mellitus"
  }
}
```

Dual coding (SNOMED + ICD-10-CM) is the standard US practice. At minimum one coding from the extensible value set.

**Constraints:**
- If category is "problem-list-item", clinicalStatus SHOULD be present
- clinicalStatus values: active | recurrence | relapse | inactive | remission | resolved

---

## MedicationRequest (us-core-medicationrequest)

Profile URL: `http://hl7.org/fhir/us/core/StructureDefinition/us-core-medicationrequest`

**Required elements:**
- `status` (1..1): required binding
- `intent` (1..1): required binding
- `medication[x]` (1..1): extensible binding — RxNorm preferred (Medication Clinical Drug value set)
- `subject` (1..1): reference to US Core Patient

**Must-support:**
- category, reported[x], encounter, authoredOn, requester
- dosageInstruction.text, dosageInstruction.timing, dosageInstruction.doseAndRate
- dispenseRequest.quantity, dispenseRequest.numberOfRepeatsAllowed
- reasonCode, reasonReference

**Code construction:**
```json
{
  "medicationCodeableConcept": {
    "coding": [
      {"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": "597983", "display": "atorvastatin 40 MG"}
    ],
    "text": "Atorvastatin 40mg"
  }
}
```

**Constraints:**
- us-core-21: requester SHALL be present if intent is an order type
- NDC codes optional as additional coding (USCDI V3+)

---

## Observation — Blood Pressure (us-core-blood-pressure)

Profile URL: `http://hl7.org/fhir/us/core/StructureDefinition/us-core-blood-pressure`

**Fixed codes:**
- `code`: LOINC 85354-9 "Blood pressure panel with all children optional"
- `category`: vital-signs
- `component[systolic].code`: LOINC 8480-6
- `component[diastolic].code`: LOINC 8462-4

**Structure:**
```json
{
  "resourceType": "Observation",
  "status": "final",
  "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "vital-signs"}]}],
  "code": {"coding": [{"system": "http://loinc.org", "code": "85354-9", "display": "Blood pressure panel"}]},
  "component": [
    {
      "code": {"coding": [{"system": "http://loinc.org", "code": "8480-6", "display": "Systolic blood pressure"}]},
      "valueQuantity": {"value": 120, "unit": "mmHg", "system": "http://unitsofmeasure.org", "code": "mm[Hg]"}
    },
    {
      "code": {"coding": [{"system": "http://loinc.org", "code": "8462-4", "display": "Diastolic blood pressure"}]},
      "valueQuantity": {"value": 80, "unit": "mmHg", "system": "http://unitsofmeasure.org", "code": "mm[Hg]"}
    }
  ]
}
```

No top-level `valueQuantity` — values go in components only.

---

## Observation — Smoking Status (us-core-smokingstatus)

Profile URL: `http://hl7.org/fhir/us/core/StructureDefinition/us-core-smokingstatus`

**Fixed codes:**
- `code`: LOINC 72166-2 "Tobacco smoking status NHIS"
- `category`: social-history

**Required:**
- `status` (1..1)
- `code` (1..1)
- `subject` (1..1)
- `effectiveDateTime` (1..1)
- `value[x]` as CodeableConcept from Smoking Status value set (preferred binding)

---

## Observation — Other Vital Signs

All share the pattern: fixed LOINC code, category=vital-signs, valueQuantity with UCUM units.

| Profile | LOINC | Required unit codes |
|---|---|---|
| Body Weight | 29463-7 | kg, [lb_av], g |
| Body Height | 8302-2 | cm, [in_i] |
| Body Temperature | 8310-5 | Cel, [degF] |
| Heart Rate | 8867-4 | /min |
| Respiratory Rate | 9279-1 | /min |
| BMI | 39156-5 | kg/m2 |
| Head Circumference | 9843-4 | cm, [in_i] |
| Pulse Oximetry | 59408-5 | % |

---

## Observation — Laboratory (us-core-observation-lab)

Profile URL: `http://hl7.org/fhir/us/core/StructureDefinition/us-core-observation-lab`

**Required:**
- `status` (1..1)
- `category`: laboratory (fixed)
- `code` (1..1): extensible binding — LOINC preferred
- `subject` (1..1)

**Must-support:** effectiveDateTime, value[x], dataAbsentReason

No fixed LOINC code — each lab observation uses the appropriate LOINC code for that analyte.

---

## AllergyIntolerance (us-core-allergyintolerance)

Profile URL: `http://hl7.org/fhir/us/core/StructureDefinition/us-core-allergyintolerance`

**Required:**
- `clinicalStatus` (0..1): required binding when present
- `code` (1..1): extensible binding
- `patient` (1..1)

**Must-support:**
- clinicalStatus, verificationStatus, code, patient
- reaction, reaction.manifestation

**Code construction:**
```json
{
  "code": {
    "coding": [
      {"system": "http://snomed.info/sct", "code": "764146007", "display": "Penicillin"}
    ],
    "text": "Penicillin allergy"
  }
}
```

---

## Procedure (us-core-procedure)

Profile URL: `http://hl7.org/fhir/us/core/StructureDefinition/us-core-procedure`

**Required:**
- `status` (1..1): required binding
- `code` (1..1): extensible binding — SNOMED CT + CPT preferred
- `subject` (1..1)

**Must-support:** status, code, subject, performed[x]

**Code construction:**
```json
{
  "code": {
    "coding": [
      {"system": "http://snomed.info/sct", "code": "41976001", "display": "Cardiac catheterization"}
    ],
    "text": "Cardiac catheterization"
  }
}
```
