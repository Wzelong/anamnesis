# mCODE Treatment Domain

Cancer-related medications, radiotherapy, and surgery. The cancer-relatedness is enforced by constraining `reasonCode`/`reasonReference` to a cancer condition.

## CancerRelatedMedicationRequest (MedicationRequest → us-core-medicationrequest)

A prescription/consumption record for cancer treatment.

| Element | Card | MS | Binding |
|---|---|---|---|
| status | 1..1 | ✓ | required: medicationrequest-status |
| statusReason | 0..1 | ✓ | preferred: TreatmentTerminationReasonVS |
| intent | 1..1 | ✓ | required: medicationrequest-intent |
| medication[x] | 1..1 | ✓ | extensible: cancer medication VS (OID 2.16.840.1.113762.1.4.1010.4) → **RxNorm** |
| subject | 1..1 | ✓ | Patient |
| reasonCode | 0..* | ✓ | extensible: CancerDisorderVS (the cancer being treated) |
| reasonReference | 0..* | ✓ | → Primary/SecondaryCancerCondition |
| dosageInstruction, dispenseRequest | 0..* | ✓ | doseAndRate.dose preferred ucum-common |

Treatment-intent extension (`procedure-intent` pattern) may carry curative/palliative intent — see ProcedureIntentVS below.

## CancerRelatedMedicationAdministration (MedicationAdministration, base R4)

Records an actual administration (the chemo "give" event). Same cancer-relatedness constraints.

| Element | Card | MS | Binding |
|---|---|---|---|
| status | 1..1 | ✓ | required: medication-admin-status |
| statusReason | 0..* | ✓ | preferred: TreatmentTerminationReasonVS |
| medication[x] | 1..1 | ✓ | extensible: cancer medication VS → RxNorm |
| subject | 1..1 | ✓ | Patient |
| effective[x] | 1..1 | ✓ | when administered |
| reasonCode | 0..* | ✓ | extensible: CancerDisorderVS |
| reasonReference | 0..* | ✓ | → cancer Condition |

## RadiotherapyCourseSummary (Procedure → us-core-procedure)

Summary of a radiotherapy course: intent, termination reason, modalities, techniques, sessions, doses.

| Element | Card | MS | Binding |
|---|---|---|---|
| status | 1..1 | ✓ | required: event-status |
| statusReason | 0..1 | ✓ | preferred: TreatmentTerminationReasonVS |
| code | 1..1 | ✓ | **fixed SNOMED 1217123003** "Radiotherapy course of treatment" |
| subject | 1..1 | ✓ | Patient |
| performed[x] | 0..1 | ✓ | period of the course |
| reasonCode / reasonReference | 0..* | ✓ | the cancer treated (CancerDisorderVS) |
| bodySite | 0..* | ✓ | extensible: RadiotherapyTreatmentLocationVS |

Must-support extensions carry the structured detail:
- `radiotherapy-modality-and-technique` — wraps `radiotherapy-modality` (RadiotherapyModalityVS, 12 codes) + `radiotherapy-technique` (RadiotherapyTechniqueVS, 18 codes)
- `radiotherapy-sessions` — number of fractions/sessions (integer)
- `procedure-intent` — ProcedureIntentVS

Companion profiles: **RadiotherapyVolume** (BodyStructure — a planning/treatment volume; morphology RadiotherapyVolumeTypeVS, location + qualifier VS) and the dose-delivered extension. Use these when modeling per-volume dose.

## CancerRelatedSurgicalProcedure (Procedure → us-core-procedure)

| Element | Card | MS | Binding |
|---|---|---|---|
| status | 1..1 | ✓ | required: event-status |
| code | 1..1 | ✓ | extensible: CancerRelatedSurgicalProcedureVS (SNOMED, CPT) |
| subject | 1..1 | ✓ | Patient |
| reasonCode / reasonReference | 0..* | ✓ | cancer condition (CancerDisorderVS) |
| bodySite | 0..* | ✓ | example: body-site (+ laterality/location-qualifier extensions) |

## Shared value sets

**TreatmentTerminationReasonVS** (SNOMED, 11): `266721009` absent response · `407563006` not tolerated · `160932005` financial · `105480006` patient refusal · `184081006` moved away · `309846006` not available · `399307001` lost to follow-up · `419620001` death · `7058009` noncompliance · `443729008` clinical-trial completion · `77386006` pregnancy.

**ProcedureIntentVS** (SNOMED, 8): `373808002` curative · `363676003` palliative · `399707004` supportive · `261004008` diagnostic · `129428001` preventive · `429892002` guidance · `360156006` screening · `447295008` forensic.

**RadiotherapyModalityVS** (12, SNOMED): teleradiotherapy protons `10611004` / electrons `45643008` / neutrons `80347004` / carbon ions `1156505006` / photons `1156506007`; brachytherapy LDR `1156708005`, permanent seeds `169359004`, pulsed `1156384006`, HDR `394902000`; radiopharmaceutical `440252007`.

**RadiotherapyTechniqueVS** (18, SNOMED): IMRT `441799006`, VMAT `1156530009`, 3D-CRT `1162782007`, 2D `1156526006`, intraoperative `168524008`, FLASH `1163157007`, plus particle/brachytherapy techniques.
