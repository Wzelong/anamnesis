# mCODE Specimen & Tumor Domain

Physical specimens, tumor body structures, and tumor characterization (size, morphology, histology, markers).

## HumanSpecimen (Specimen → us-core-specimen)

A specimen taken for oncology testing.

| Element | Card | MS | Binding |
|---|---|---|---|
| identifier | 0..* | ✓ | one slice typed `BodyStructure` (links to source structure) |
| status | 0..1 | ✓ | required: specimen-status |
| type | 1..1 | ✓ | **extensible: HumanSpecimenTypeVS** (HL7 v2-0487) |
| collection.bodySite | 0..1 | ✓ | example body-site + laterality/location-qualifier extensions |

HumanSpecimenTypeVS (v2-0487, 33 codes): common ones — `TISS` Tissue · `TUMOR` Tumor · `BLD` Whole blood · `BON` Bone · `MAR` Marrow · `CSF` CSF · `PLR` Pleural fluid · `SAL` Saliva · `SKN` Skin · `SPT` Sputum.

## Tumor (BodyStructure)

Identifies a tumor *in situ* (not removed). Aim for one resource per tumor, tracked over time.

| Element | Card | MS | Binding |
|---|---|---|---|
| identifier | 1..* | ✓ | stable id to track the tumor across observations |
| morphology | 0..1 | ✓ | extensible: TumorMorphologyCodeVS (ICD-O-3, SNOMED) |
| location | 1..1 | ✓ | extensible: CancerBodyLocationVS (SNOMED) |
| locationQualifier | 0..* | ✓ | required: BodyLocationAndLateralityQualifierVS |
| patient | 1..1 | ✓ | |

Carries a `related-condition` extension (url fixed) → the cancer Condition. TumorSize and other observations reference the Tumor via `focus`/`bodySite`.

## TumorSize (Observation, base R4)

Dimensions of a tumor. Note: base Observation, not US Core.

| Element | Card | MS | Binding |
|---|---|---|---|
| code | 1..1 | ✓ | **fixed LOINC 21889-1** "Size Tumor" |
| subject | 1..1 | ✓ | Patient |
| focus | 0..1 | ✓ | → the Tumor BodyStructure |
| method | 0..1 | ✓ | extensible: TumorSizeMethodVS |
| component | 1..* | ✓ | dimensions, each in mm/cm |

Component slices (fixed LOINC code, value `Quantity` with **required TumorSizeUnitsVS** = `mm` or `cm`):
- `33728-7` longest dimension (1..1, required)
- `33729-5` other dimensions (0..2)

## TumorMarkerTest (Observation → us-core-observation-lab)

Result of a tumor marker test (ER, PR, HER2, PSA, CA-125, etc.).

| Element | Card | MS | Binding |
|---|---|---|---|
| category | 1..1 | ✓ | fixed `laboratory` |
| code | 1..1 | ✓ | extensible: TumorMarkerTestVS (LOINC, 513 codes — search) |
| subject | 1..1 | ✓ | Patient |
| value[x] | 1..1 | ✓ | Quantity, CodeableConcept, ratio, or string per marker |
| specimen | 0..1 | ✓ | → HumanSpecimen |

## Histology / morphology

| Profile | base | `.code` (fixed) | `.value[x]` | method |
|---|---|---|---|---|
| histologic-behavior-and-type | us-core-observation-lab | LOINC 31206-6 | extensible HistologicBehaviorAndTypeVS (**ICD-O-3** morphology, e.g. `8500/3`) | — |
| histologic-grade | us-core-observation-lab | NCIt C18000 | extensible HistologicGradeVS | extensible HistologicGradingSystemVS |
| tumor-morphology | us-core-simple-observation | LOINC 77753-2 | — (ICD-O-3 / SNOMED morphology) | — |

HistologicGradeVS (SNOMED, 3): `1155708003` low · `1286893008` intermediate · `1155707008` high. HistologicGradingSystemVS (18 systems): Gleason `106241006`, Nottingham `449205006`, Fuhrman `396192007`, WHO CNS `277460003`, FNCLCC `426757001`, etc.

ICD-O-3 morphology codes use the form `8500/3` (4-digit type `/` 1-digit behavior). The behavior-and-type value set isn't expanded in the IG (IP reasons) — bind by URL and supply the ICD-O-3 code with system `http://terminology.hl7.org/CodeSystem/icd-o-3`.
