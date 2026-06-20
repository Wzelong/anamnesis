# Conformance — US Core 6.1.0 (mCODE-ready)

Fixed v1 design for FHIR conformance. Anamnesis is an **extraction** tool: it surfaces
clinical facts buried in unstructured notes and writes them back. "US Core 6.1.0
complete" means everything we **write** conforms to its profile, we cover the
**high-yield** USCDI clinical classes, and we **validate before write**.

See [DIRECTION.md](DIRECTION.md) for the framework vision and [Architecture.md](Architecture.md)
for the system as built.

## Base IG decision

- **Base IG: US Core 6.1.0 (STU6).** Pinned.
- **Target specialty: mCODE 4.0.0 (STU4)**, which `dependsOn hl7.fhir.us.core#6.1.0` — so
  US Core 6.1.0 is mCODE's exact substrate. Building US Core 6.1.0 correctly *is* building
  mCODE's foundation. mCODE also `dependsOn` `genomics-reporting#2.0.0` (out of scope),
  `hl7.terminology.r4#6.2.0`, `hl7.fhir.uv.extensions.r4#5.2.0`.

## Producible set — value-driven (extraction-yield × use-case)

Drive the set by *what's buried in narrative* × *use-case value*, not the USCDI checklist.
Result Observations (labs/vitals) are usually already structured → low augmentation yield
(support when present, don't chase them).

| Resource | In narrative? | Use-case value | Tier |
|---|---|---|---|
| **Condition** | High | Payer HCC/RAF, problem completeness | 1 (have) |
| **FamilyMemberHistory** | Very high (never coded) | Hereditary risk, screening gaps (HEDIS/USPSTF) | 1 — **base FHIR** (US Core has no FMH profile) |
| **AllergyIntolerance** | High | Safety, med reconciliation | 1 (have) |
| **Procedure** | High | History, HCC | 1 (have) |
| **MedicationRequest** | High (OTC, outside, adherence) | Med reconciliation | 1 (have) — `reported=true` for patient-stated (US Core has **no** MedicationStatement) |
| **Social / SDOH Observations** (smoking, alcohol/substance, occupation, sexual-orientation) | Very high | SDOH/quality (Z-codes), USCDI v3 | 1 — smoking have, rest to add |
| Immunization | Medium (often registry) | Care gaps | 2 |
| **Result Observations** (labs/vitals) | Low (already structured) | High *if* from outside records | 2 — conform when present, don't chase |
| DiagnosticReport, Goal, ServiceRequest, Device, MedicationDispense, Specimen, QuestionnaireResponse, CarePlan | Low / order-side | Situational | Omit v1 |

**Read-as-context** (loaded, not produced): Patient, Encounter, Practitioner(Role),
Organization, Location, Coverage, CareTeam, RelatedPerson.

**Use-case = a preset axis.** An HCC / Risk-Adjustment preset weights Condition; a
Screening-Gaps preset weights FamilyMemberHistory + social. The preset framework already
supports this — presets are not only US Core vs mCODE.

## Validation — locked for v1: L1 + L2a

- **L1 — in-process base R4.** Validate every built resource is valid R4 before write via
  `fhir.resources` (already a dependency, currently unused). Catches datatypes, cardinality,
  base-required fields. No network. *Not* must-support/bindings.
- **L2a — opportunistic profile `$validate`.** Call the SHARP target server's
  `{Resource}/$validate?profile={usCore}` when its CapabilityStatement advertises the op +
  US Core. Zero new infra; best-effort; skip when unsupported.
- **L2b / L3 (future) — dedicated validator + terminology.** A HAPI / `org.hl7.fhir.validator`
  service with the US Core 6.1.0 package + terminology loaded, run **external** (Java; the
  Python-on-Render app HTTP-calls it). Authoritative `$validate` + `$expand` +
  `$validate-code`; powers preset coding-subset enforcement. Prod hard-gate.

Placement: a pre-write step in `fhir/write.py:apply_augmentation`; result attaches to the
proposal as `conformance` (UI badge). Soft-flag in demo, hard-gate in prod (configurable).

## mCODE-readiness guardrails (bake in now, or rewrite later)

mCODE profiles **derive from** US Core profiles (constrain + extend). To avoid a foundation
rewrite when mCODE lands:

1. **`meta.profile` is a resolved LIST** from the effective IG, not a single hardcoded URL —
   an mCODE Condition conforms to US Core Condition *and* mCODE PrimaryCancerCondition.
2. **Builders take the EffectiveProfile and apply layered overlays** (extra extensions,
   codings, tighter bindings) — not monolithic US-Core-only logic.
3. **One generic extension-apply step** for IG-declared *and* user extensions (mCODE is
   extension-heavy: histology-morphology-behavior, laterality, …).
4. **Terminology routing is IG-driven** — never assume snomed/rxnorm/loinc/icd10 is the
   universe. mCODE adds **ICD-O-3** (morphology) + **AJCC** (staging): a known retriever gap.
5. **Resolve allows specialty-only + base-FHIR resource types** (mCODE Tumor ⊂ BodyStructure,
   Specimen) — the base+specialty merge adds, not just constrains.
6. **Genomics group is out of scope** (separate `genomics-reporting` IG, structured molecular
   data, not narrative extraction).

## Staged roadmap

- **Stage 0 — reconcile + pin (this change).** FamilyMemberHistory → base FHIR (drop the
  bogus `us-core-familymemberhistory` canonical); add `US_CORE_VERSION = "6.1.0"`; align the
  frontend `ig-catalog.ts` ↔ backend builders ↔ this include/omit table.
- **Stage 1 — L1 R4 validation.** `fhir/validate.py` over `fhir.resources`; call in
  assembly/write; attach `conformance`; builder tests go green.
- **Stage 2 — complete producible profiles, overlay-ready.** Social/SDOH Observations;
  `MedicationRequest.reported`; specific vital-sign profiles (Tier 2). Refactor builders to
  EffectiveProfile-in / profile-list + extension-apply-out (guardrails 1–3).
- **Stage 3 — L2a opportunistic `$validate`** against the SHARP server; attach profile conformance.
- **Stage 4 — L2b/L3 dedicated validator + terminology;** coding-subset enforcement; prod gate.
- **Stage 5 — UI:** conformance badge per proposal; per-preset validation strictness.

## Known gaps / future

- **ICD-O-3 (morphology) + AJCC (staging)** retrievers — required for mCODE, absent today.
- **Genomics** — out (separate IG, structured).
- US Core version is currently asserted only via unversioned canonicals; L2b pins the package.
