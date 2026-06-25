# mCODE Assessment Domain

Performance status, comorbidities, and risk assessments. The performance-status profiles all derive from `us-core-observation-clinical-result`, pin `.code` to a fixed scale code, and bind `interpretation` to a LOINC answer list.

## Performance status

| Profile | `.code` (fixed) | value / interpretation |
|---|---|---|
| ecog-performance-status | LOINC 89247-1 | grade 0–5; `interpretation` **required** LOINC answer list LL529-9 |
| karnofsky-performance-status | LOINC 89243-0 | score 0–100; `interpretation` **required** LOINC answer list LL4986-7 |
| lansky-play-performance-status | NCIt C38144 | pediatric play score 0–100; `interpretation` extensible LanskyPlayPerformanceVS |

Common shape (all): `status` 1..1 MS, `code` 1..1 MS (fixed above), `subject` 1..1 MS, `effective[x]` 0..1 MS, `value[x]` 0..1 MS, `dataAbsentReason` 0..1 MS, `interpretation` MS.

ECOG/Karnofsky put the actual grade in `interpretation` (from the LOINC answer list) and may also carry the numeric in `value`. ECOG grades: 0 (fully active) → 5 (dead). Karnofsky: 100 (normal) → 0 (dead), in steps of 10.

## Comorbidities (Observation → us-core-simple-observation)

A structured roll-up of comorbid conditions relative to an index (primary) cancer condition.

| Element | Card | MS | Binding |
|---|---|---|---|
| status | 1..1 | ✓ | required: observation-status |
| code | 1..1 | ✓ | **fixed SNOMED 398192003** "Co-morbid conditions" |
| subject | 1..1 | ✓ | Patient |
| value[x] | 0..1 | ✓ | |

Extensions (MS) carry the actual comorbidity data three ways: free-form list, a specified comorbidity category, or absent-comorbidity assertions — via the `comorbidities-elements` / `related-condition` extensions referencing Condition resources.

## DeauvilleScale (Observation → us-core-observation-clinical-result)

5-point PET response scale for Hodgkin / aggressive NHL.

| Element | Card | MS | Binding |
|---|---|---|---|
| code | 1..1 | ✓ | **fixed SNOMED 708895006** "Deauville five point scale" |
| interpretation | 0..* | ✓ | extensible: DeauvilleScaleVS (the 1–5 score) |
| value[x], dataAbsentReason | 0..1 | ✓ | |

## Risk assessments

`CancerRiskAssessment` is the parent (Observation → us-core-simple-observation); `code` preferred RiskAssessmentTypeVS, `value[x]` example RiskAssessmentVS. Two disease-specific children pin the code:

| Profile | `.code` (fixed) | `.value[x]` |
|---|---|---|
| ALL-risk-assessment | NCIt C167435 | extensible ALLRiskAssessmentVS: `C122457` standard risk, `C122458` high risk |
| rhabdomyosarcoma-risk-assessment | NCIt C148010 | required RhabdomyosarcomaAssessmentValueVS: `723505004` low, `C102402` intermediate, `723509005` high |
