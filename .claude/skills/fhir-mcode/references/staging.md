# mCODE Staging Domain

Cancer staging splits into **TNM** (the individual T/N/M categories plus the overall stage group) and **general/other** systems (CancerStage parent, LymphomaStage). Staging Observations attach to the cancer via `PrimaryCancerCondition.stage.assessment`.

The data model: three TNM category Observations (T, N, M) are referenced by one TNMStageGroup Observation via `hasMember`, and the stage group's `focus` points at the cancer Condition.

## Inheritance

```
us-core-simple-observation
 └─ mcode-cancer-stage ............ CancerStage (parent for stage observations)
     ├─ mcode-tnm-stage-group ..... TNMStageGroup
     └─ mcode-lymphoma-stage ...... LymphomaStage
 └─ mcode-tnm-category ............ TNMCategory (parent for T/N/M)
     ├─ mcode-tnm-primary-tumor-category
     ├─ mcode-tnm-regional-nodes-category
     └─ mcode-tnm-distant-metastases-category
```

## TNMStageGroup (Observation → mcode-cancer-stage)

Overall AJCC stage group.

| Element | Card | MS | Binding |
|---|---|---|---|
| status | 1..1 | ✓ | required: observation-status |
| code | 1..1 | ✓ | preferred: TNMStageGroupStagingTypeVS |
| subject | 1..1 | ✓ | Patient |
| focus | 1..1 | ✓ | → the cancer Condition |
| value[x] | 0..1 | ✓ | preferred: TNMStageGroupVS (CodeableConcept; 141 AJCC codes — search, not enumerable here) |
| method | 1..1 | ✓ | extensible: TNMStagingMethodVS |
| hasMember | 0..3 | ✓ | → the T, N, M category Observations |
| component | 0..* | | prognostic factors (preferred VS) |

`code` — pick by clinical vs pathologic:
| code (SNOMED) | meaning |
|---|---|
| 399390009 | TNM stage grouping (unspecified) |
| 399537006 | Clinical TNM stage grouping (cTNM) |
| 399588009 | Pathologic TNM stage grouping (pTNM) |

## TNM category profiles (Observation → mcode-tnm-category)

All three share: `status` 1..1 MS, `subject` 1..1 MS, `method` 1..1 MS (extensible TNMStagingMethodVS), `code` 1..1 MS and `value[x]` 0..1 MS (both preferred). They differ only by which staging-type VS binds `code` and which category VS binds `value[x]`.

| Profile | `.code` VS (staging type) | `.value[x]` VS (category) |
|---|---|---|
| tnm-primary-tumor-category | TNMPrimaryTumorStagingTypeVS | TNMPrimaryTumorCategoryVS (118 codes) |
| tnm-regional-nodes-category | TNMRegionalNodesStagingTypeVS | TNMRegionalNodesCategoryVS (59) |
| tnm-distant-metastases-category | TNMDistantMetastasesStagingTypeVS | TNMDistantMetastasesCategoryVS (28) |

**`.code` staging-type codes** (SNOMED; pick clinical `c…` vs pathologic `p…`):
| Profile | unspecified | clinical | pathologic |
|---|---|---|---|
| T (primary tumor) | 78873005 | 399504009 (cT) | 384625004 (pT) |
| N (regional nodes) | 277206009 | 399534004 (cN) | 371494008 (pN) |
| M (distant metastases) | 277208005 | 399387003 (cM) | 371497001 (pM) |

The category `value[x]` codes are SNOMED concepts prefixed "American Joint Committee on Cancer", e.g. cM0 = `1229901006`, cM1 = `1229903009`, cN0 = `1229967007`, pN1 = `1229951001`. These are large enumerations — search the category VS for the exact c/p value rather than guessing the SNOMED id.

## CancerStage (Observation → us-core-simple-observation)

Parent for non-TNM staging (and grade/classification). `code` preferred CancerStageTypeVS (64 codes: TNM, FIGO, Dukes, Ann Arbor, etc.), `value[x]` preferred CancerStageValueVS, `method` MS preferred CancerStagingMethodVS (58 systems — AJCC, FIGO, Dukes, Binet, Rai, ISS…). Use directly only when no more-specific staging profile fits.

## LymphomaStage (Observation → mcode-cancer-stage)

Ann Arbor / Cotswold / Lugano staging.

| Element | Card | MS | Binding |
|---|---|---|---|
| code | 1..1 | ✓ | **fixed SNOMED 385388004** "Lymphoma stage" |
| value[x] | 0..1 | ✓ | **required: LymphomaStageValueVS** |
| method | 1..1 | ✓ | **required: LymphomaStagingMethodVS** (which of Ann Arbor / Cotswold / Lugano) |
| component | | | fixed-code component slices for stage modifier (`106252000`), nature of staging (`277366005` → ClinOrPathModifierVS), bulky disease (`260873006` → LymphomaStageBulkyModifierVS) |

ClinOrPathModifierVS (SNOMED): `260998006` cS clinical staging · `261023001` pathological staging.

## Staging methods

**TNMStagingMethodVS** (5 codes) — AJCC editions: `444256004` (6th), `443830009` (7th), `897275008` (8th), `1269566009` (9th); plus UICC `C188404` (NCIt). **CancerStagingMethodVS** (58 codes) covers the full range of named systems (FIGO by site, Dukes, Modified Astler-Coller, Binet, Rai, ISS/R-ISS, Breslow, Clark, Gleason context, Ann Arbor variants).
