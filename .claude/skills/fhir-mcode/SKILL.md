---
name: fhir-mcode
description: FHIR R4 mCODE STU4 (4.0.0) oncology profile requirements, terminology bindings, and fixed codes. Use whenever building, validating, or reasoning about oncology FHIR data — cancer Condition/staging/TNM, tumor markers, genomic variants, radiotherapy, performance status (ECOG/Karnofsky), cancer-related medications, or any mCODE profile — even if the user says "oncology data" or "cancer FHIR" without naming mCODE. mCODE constrains US Core, so pair this with the fhir-us-core skill.
---

# FHIR R4 mCODE STU4 (4.0.0) Quick Reference

mCODE™ (minimal Common Oncology Data Elements) is an HL7 FHIR R4 IG: 39 profiles + 14 extensions for oncology. **Every mCODE profile constrains a US Core or base R4 profile** — mCODE only *adds* oncology rules (codes, must-support, cardinality). So first satisfy the US Core base (see the `fhir-us-core` skill), then apply the mCODE constraints here.

- FHIR version: **R4 (4.0.1)** · IG version: **STU4 / 4.0.0**
- Profile canonical: `http://hl7.org/fhir/us/mcode/StructureDefinition/mcode-<name>`
- ValueSet canonical: `http://hl7.org/fhir/us/mcode/ValueSet/<name>`

## Code System URIs

mCODE leans on SNOMED CT heavily, plus several systems beyond the US Core set. The non-obvious ones (NCI Thesaurus, AJCC, ICD-O-3) trip people up — get them exact:

```python
SYSTEM_URIS = {
    "snomed":     "http://snomed.info/sct",
    "loinc":      "http://loinc.org",
    "rxnorm":     "http://www.nlm.nih.gov/research/umls/rxnorm",
    "icd10cm":    "http://hl7.org/fhir/sid/icd-10-cm",
    "icdo3":      "http://terminology.hl7.org/CodeSystem/icd-o-3",
    "ncit":       "http://ncicb.nci.nih.gov/xml/owl/EVS/Thesaurus.owl",  # NCI Thesaurus (codes like C167435)
    "ajcc":       "http://cancerstaging.org",                            # AJCC stage groups
    "hgnc":       "http://www.genenames.org/geneId",                     # gene symbols
    "ucum":       "http://unitsofmeasure.org",
    "cpt":        "http://www.ama-assn.org/go/cpt",
    "v2_0487":    "http://terminology.hl7.org/CodeSystem/v2-0487",       # specimen type
    "obs_cat":    "http://terminology.hl7.org/CodeSystem/observation-category",
}
```

## Profile Quick Reference

`.code` binding strength and value set per profile. **Pref. systems** = where to search when the binding isn't a fixed code. See "Fixed `.code` codes" below for profiles whose `.code` is pinned (skip terminology search entirely).

| Profile (`mcode-…`) | FHIR / US Core base | `.code` binding | `.value[x]` binding | Pref. systems |
|---|---|---|---|---|
| primary-cancer-condition | Condition / us-core-condition-problems-health-concerns | extensible: PrimaryCancerDisorderVS | — | SNOMED, ICD-10-CM |
| secondary-cancer-condition | Condition / (same) | extensible: SecondaryCancerDisorderVS | — | SNOMED, ICD-10-CM |
| cancer-patient | Patient / us-core-patient | — | — | — |
| cancer-disease-status | Observation / (base) | **fixed** LOINC 97509-4 | preferred: ConditionStatusTrendVS | SNOMED |
| tnm-primary-tumor-category | Observation / mcode-tnm-category | preferred: T staging-type VS | preferred: TNMPrimaryTumorCategoryVS | SNOMED (AJCC) |
| tnm-regional-nodes-category | Observation / mcode-tnm-category | preferred: N staging-type VS | preferred: TNMRegionalNodesCategoryVS | SNOMED (AJCC) |
| tnm-distant-metastases-category | Observation / mcode-tnm-category | preferred: M staging-type VS | preferred: TNMDistantMetastasesCategoryVS | SNOMED (AJCC) |
| tnm-stage-group | Observation / mcode-cancer-stage | preferred: stage-group staging-type VS | preferred: TNMStageGroupVS | SNOMED, AJCC |
| cancer-stage | Observation / us-core-simple-observation | preferred: CancerStageTypeVS | preferred: CancerStageValueVS | SNOMED |
| lymphoma-stage | Observation / mcode-cancer-stage | **fixed** SNOMED 385388004 | required: LymphomaStageValueVS | SNOMED |
| tumor-marker-test | Observation / us-core-observation-lab | extensible: TumorMarkerTestVS | (Quantity/CC) | LOINC |
| histologic-behavior-and-type | Observation / us-core-observation-lab | **fixed** LOINC 31206-6 | extensible: HistologicBehaviorAndTypeVS | ICD-O-3 |
| histologic-grade | Observation / us-core-observation-lab | **fixed** NCIt C18000 | extensible: HistologicGradeVS | SNOMED |
| tumor-morphology | Observation / us-core-simple-observation | **fixed** LOINC 77753-2 | — | ICD-O-3, SNOMED |
| tumor-size | Observation / (base) | **fixed** LOINC 21889-1 | components in mm/cm | UCUM |
| tumor | BodyStructure | — (morphology+location) | — | SNOMED, ICD-O-3 |
| human-specimen | Specimen / us-core-specimen | type: extensible HumanSpecimenTypeVS | — | HL7 v2-0487 |
| ecog-performance-status | Observation / us-core-observation-clinical-result | **fixed** LOINC 89247-1 | (LOINC answer list LL529-9) | — |
| karnofsky-performance-status | Observation / (same) | **fixed** LOINC 89243-0 | (answer list LL4986-7) | — |
| lansky-play-performance-status | Observation / (same) | **fixed** NCIt C38144 | int 0–100 | — |
| comorbidities | Observation / us-core-simple-observation | **fixed** SNOMED 398192003 | — | SNOMED |
| genomic-variant | Observation / Genomics Reporting `variant` | **fixed** LOINC 69548-6 | (see genomics.md) | HGNC, LOINC |
| genomic-region-studied | Observation / `region-studied` | **fixed** LOINC 53041-0 | (components) | HGNC, LOINC |
| genomics-report | DiagnosticReport / Genomics `genomics-report` | preferred: report codes | — | LOINC |
| cancer-related-medication-request | MedicationRequest / us-core-medicationrequest | extensible: medication VS | — | RxNorm |
| cancer-related-medication-administration | MedicationAdministration / (base) | extensible: medication VS | — | RxNorm |
| cancer-related-surgical-procedure | Procedure / us-core-procedure | extensible: CancerRelatedSurgicalProcedureVS | — | SNOMED, CPT |
| radiotherapy-course-summary | Procedure / us-core-procedure | **fixed** SNOMED 1217123003 | — | SNOMED |

> The full element-level tables (cardinality, must-support, every binding, slices, extensions) live in `references/`. Read the file for the domain you're working in — don't reconstruct constraints from memory.

## Fixed `.code` codes (bypass terminology search)

When `.code` is fixed, emit exactly this coding — do **not** search a terminology server:

| Profile | system | code | display |
|---|---|---|---|
| cancer-disease-status | LOINC | 97509-4 | Cancer disease status |
| ecog-performance-status | LOINC | 89247-1 | ECOG performance status |
| karnofsky-performance-status | LOINC | 89243-0 | Karnofsky Performance Status score |
| lansky-play-performance-status | NCIt | C38144 | Lansky Play-Performance Status |
| histologic-behavior-and-type | LOINC | 31206-6 | Histology and behavior ICD-O-3 |
| histologic-grade | NCIt | C18000 | Grade |
| tumor-morphology | LOINC | 77753-2 | Tumor morphology |
| tumor-size | LOINC | 21889-1 | Size Tumor |
| comorbidities | SNOMED | 398192003 | Co-morbid conditions |
| deauville-scale | SNOMED | 708895006 | Deauville five point scale |
| lymphoma-stage | SNOMED | 385388004 | Lymphoma stage |
| body-surface-area | LOINC | 8277-6 | Body surface area |
| genomic-variant | LOINC | 69548-6 | Genetic variant assessment |
| genomic-region-studied | LOINC | 53041-0 | DNA region of interest panel |
| radiotherapy-course-summary | SNOMED | 1217123003 | Radiotherapy course of treatment |
| ALL-risk-assessment | NCIt | C167435 | Leukemia Finding |
| rhabdomyosarcoma-risk-assessment | NCIt | C148010 | IRSG Clinical Staging System |

## Binding strength rules

Same semantics as US Core. **Required** → SHALL use a code from the value set. **Extensible** → use the value set if an applicable concept exists; only go outside it if none fits. **Preferred** → encouraged but not enforced. mCODE's clinically-richest value sets (cancer disorders, body locations, tumor markers, ICD-O-3 morphology) are large/grammar-based and *not* enumerable here — bind by URL and resolve the specific code via terminology search.

## Reference files (read the relevant one)

- `references/disease.md` — CancerPatient, Primary/Secondary Cancer Condition, Cancer Disease Status, History of Metastatic Cancer
- `references/staging.md` — TNM categories + stage group, CancerStage, LymphomaStage, staging methods, AJCC value sets
- `references/treatment.md` — medication request/administration, radiotherapy course summary + extensions, surgical procedure, termination reasons, procedure intent
- `references/assessment.md` — ECOG / Karnofsky / Lansky, Comorbidities, risk assessments, Deauville
- `references/genomics.md` — GenomicVariant, GenomicRegionStudied, GenomicsReport (component slices)
- `references/specimen-tumor.md` — HumanSpecimen, Tumor, TumorSize, TumorMarkerTest, histologic behavior/grade, morphology

## Worked example: Primary Cancer Condition

```json
{
  "resourceType": "Condition",
  "meta": { "profile": ["http://hl7.org/fhir/us/mcode/StructureDefinition/mcode-primary-cancer-condition"] },
  "clinicalStatus": { "coding": [{ "system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active" }] },
  "verificationStatus": { "coding": [{ "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status", "code": "confirmed" }] },
  "category": [{ "coding": [{ "system": "http://terminology.hl7.org/CodeSystem/condition-category", "code": "problem-list-item" }] }],
  "code": { "coding": [{ "system": "http://snomed.info/sct", "code": "408643008", "display": "Infiltrating duct carcinoma of breast" }] },
  "bodySite": [{ "coding": [{ "system": "http://snomed.info/sct", "code": "76752008", "display": "Breast structure" }] }],
  "subject": { "reference": "Patient/example" }
}
```
Note: `code` binds extensibly to PrimaryCancerDisorderVS (resolve via SNOMED/ICD-10-CM), `bodySite` to CancerBodyLocationVS. Stage is linked via `Condition.stage.assessment` → TNMStageGroup/CancerStage Observations.
