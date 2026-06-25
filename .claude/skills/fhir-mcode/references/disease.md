# mCODE Disease Domain

Patient, the cancer conditions, and disease status. All profiles constrain US Core — satisfy the US Core base first (`fhir-us-core` skill), then apply these mCODE additions.

## CancerPatient (Patient → us-core-patient)

No oncology-specific content — it is US Core Patient with the same must-support set (identifier, name, gender, birthDate, address, communication.language). Use it as the subject of every other mCODE resource. The only reason it exists is to mark the patient as in-scope for mCODE; conform to US Core Patient and reference this profile.

## PrimaryCancerCondition (Condition → us-core-condition-problems-health-concerns)

The original/first neoplasm. Records the cancer diagnosis and links to staging.

| Element | Card | MS | Binding |
|---|---|---|---|
| clinicalStatus | 0..1 | ✓ | required: condition-clinical |
| verificationStatus | 0..1 | ✓ | required: condition-ver-status |
| category | 1..* | ✓ | required: us-core-problem-or-health-concern (+ condition-category) |
| code | 1..1 | ✓ | **extensible: PrimaryCancerDisorderVS** — resolve via SNOMED CT (preferred) or ICD-10-CM |
| bodySite | 0..* | ✓ | extensible: CancerBodyLocationVS (SNOMED); +laterality/location-qualifier extensions |
| subject | 1..1 | ✓ | Patient |
| onset[x], abatement[x], recordedDate | 0..1 | ✓ | |
| stage | 0..* | ✓ | `stage.assessment` → references TNMStageGroup / CancerStage Observations; `stage.type` extensible: CancerStagingMethodVS |
| evidence.code | 0..* | | required: CancerDiseaseStatusEvidenceTypeVS |

Extensions (must-support): `histology-morphology-behavior` (ICD-O-3 morphology, links to a TumorMorphology Observation or codes inline), `assertedDate`, `condition-related`.

`code` value set is large and grammar-based (SNOMED disorder hierarchy) — bind by URL, do **not** enumerate. Search terminology for the specific histology+site disorder code.

## SecondaryCancerCondition (Condition → us-core-condition-problems-health-concerns)

Metastases — cancer that has spread from the primary site. Same shape as PrimaryCancerCondition with two differences:

- `code` binds **extensible: SecondaryCancerDisorderVS** (secondary/metastatic malignant neoplasm disorders).
- Adds the standard FHIR `condition-related` extension (`Condition.extension`, url fixed to `http://hl7.org/fhir/StructureDefinition/condition-related`) — point it at the PrimaryCancerCondition this metastasis derives from.

`bodySite` (CancerBodyLocationVS) records the metastatic site(s).

## CancerDiseaseStatus (Observation, base Observation)

A clinician's qualitative judgment of the cancer's trend (stable / improving / worsening). Note: base R4 Observation, **not** US Core.

| Element | Card | MS | Binding |
|---|---|---|---|
| status | 1..1 | ✓ | required: observation-status |
| code | 1..1 | ✓ | **fixed LOINC 97509-4** "Cancer disease status" |
| subject | 1..1 | ✓ | Patient |
| focus | 0..* | ✓ | → the Condition this status is about |
| effective[x] | 0..1 | ✓ | |
| value[x] | 0..1 | ✓ | **preferred: ConditionStatusTrendVS** (CodeableConcept) |
| evidence type | | | via extension `cancer-disease-status-evidence-type` |

**ConditionStatusTrendVS** (SNOMED, 4 codes — enumerable):
| code | display |
|---|---|
| 268910001 | Patient's condition improved |
| 359746009 | Patient status stable |
| 271299001 | Patient's condition worsened |
| 709137006 | Patient condition undetermined |

## HistoryOfMetastaticCancer (Observation → us-core-simple-observation)

Records that a past episode of metastatic cancer existed, for long-term tracking.

| Element | Card | MS | Binding |
|---|---|---|---|
| status | 1..1 | ✓ | required: observation-status |
| code | 1..1 | ✓ | extensible: HistoryOfMetastaticMalignantNeoplasmVS (SNOMED) |
| subject | 1..1 | ✓ | Patient |
| value[x] | 0..1 | ✓ | |
