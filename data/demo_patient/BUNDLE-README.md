# Anamnesis Demo Patient Bundle

The FHIR R4 / US Core 6.1.0 bundle that anchors the Anamnesis demo. Contains the existing structured record for **James Lee** (the augmentation engine's input) plus four clinical notes (the augmentation engine's source material). The resulting augmentations are the engine's output and are *not* in this bundle.

## Files

| File | Purpose |
|---|---|
| `anamnesis-demo-bundle.json` | The FHIR R4 transaction Bundle (~80 KB, 22 resources). POST this to your FHIR server. |
| `note-1-cardiology-consultation.md` | The cardiology consult note (artifact view of what's in the bundle). |
| `note-2-ed-discharge-summary.md` | The Riverside ED discharge summary (artifact view). |
| `note-3-neurology-followup.md` | The neurology follow-up note (artifact view). |
| Cardiology follow-up (2026-01-22) | A fourth `DocumentReference` lives base64-inline in the bundle (id `cardio-followup-conflict`). No standalone `.md` artifact; decode `content[0].attachment.data` if you need the prose. |
| `build_bundle.py` | Python builder. Edit and re-run if you want to change anything. |
| `validate_bundle.py` | Validator with structural + US Core profile + reference integrity checks. |

## Patient

**James Lee**, 67yo male (DOB 1958-11-15), MRN BAY-0042-LEE, established at **Bayside Health**.

Race: Asian. Ethnicity: Not Hispanic or Latino. Birth sex: M. (USCDI demographics extensions populated.)

## What's in the bundle (22 resources, baseline / pre-augmentation)

| Type | Count | Items |
|---|---|---|
| Organization | 2 | Bayside Health (home), Riverside Hospital (outside facility) |
| Practitioner | 4 | Dr. Anna Kim (PCP), Dr. David Park (cardiology), Dr. Tom Brown (Riverside ED), Dr. Lisa Chen (neurology) |
| Patient | 1 | James Lee |
| Condition | 4 | Essential HTN (2016), T2DM (2018), hyperlipidemia (2016), chronic post-stroke fatigue (2024) |
| MedicationRequest | 4 | Lisinopril 10mg daily, atorvastatin 40mg daily, metformin 1000mg BID, ASA 81mg daily |
| Encounter | 3 | Cardiology consult (10/20/2025), Riverside ED visit (12/15/2025), Neurology follow-up (2/23/2026) |
| DocumentReference | 4 | Four clinical notes with full text base64-encoded inline; LOINC-coded by document type |

## What is deliberately NOT in the structured baseline

These represent the gaps the augmentation engine fills:

- **No allergies** in the structured record (penicillin allergy lives in the ED note → CONFLICT)
- **No smoking status** (former-smoker status with quit date and pack-years is in the neuro note)
- **No family history** (father MI age 52 is in the neuro note)
- **No metoprolol prescription** (cardiology prescribed it, never made it back to the home structured record)
- **No stable angina or two-vessel CAD on the problem list** (cardiology diagnosed both)
- **No cardiac catheterization procedure record** (cardio note documents it; never structured)
- **Lisinopril dose still 10mg** (neuro note bumped it to 20mg)

---

# Expected results per note

This is the contract the augmentation engine has to satisfy against this baseline.

## Note 1 — Cardiology Consultation (Dr. David Park, 2025-10-20)

**4 augmentations**, all classified NEW.

### 1. Stable angina pectoris → `Condition`

- **Source span:** *"Stable angina pectoris in the setting of two-vessel coronary artery disease"* (Assessment & Plan #1)
- **Class:** `NEW` — not on existing problem list
- **Resource fields:**
  - `code`: SNOMED 233819005 (Stable angina) + ICD-10 I20.9 (Angina pectoris, unspecified)
  - `clinicalStatus`: `active`
  - `verificationStatus`: `confirmed`
  - `category`: `problem-list-item`
  - `recordedDate`: 2025-10-20
  - `asserter`/`recorder`: Dr. David Park

### 2. Two-vessel coronary artery disease → `Condition`

- **Source span:** *"two-vessel coronary artery disease"* and *"60% mid-LAD stenosis and 70% proximal RCA stenosis"* (HPI, Data Review, A&P #1)
- **Class:** `NEW`
- **Resource fields:**
  - `code`: SNOMED 53741008 (Coronary arteriosclerosis) + ICD-10 I25.10 (Atherosclerotic heart disease without angina pectoris)
  - `clinicalStatus`: `active`
  - `verificationStatus`: `confirmed`
  - `category`: `problem-list-item`

### 3. Diagnostic cardiac catheterization → `Procedure`

- **Source span:** *"Diagnostic left heart catheterization was performed by this provider on 10/15/2025... Findings: two-vessel coronary artery disease"* (HPI)
- **Class:** `NEW`
- **Engine extraction challenge:** Must extract the **performed date 2025-10-15** from the HPI prose, not default to the encounter date 2025-10-20. Small but real test of clinical-temporal reasoning that distinguishes a clinically aware engine from a keyword extractor.
- **Resource fields:**
  - `code`: SNOMED 41976001 (Cardiac catheterization)
  - `status`: `completed`
  - `performedDateTime`: `2025-10-15`
  - `performer.actor`: Dr. David Park
  - `outcome`: successful
  - `complication`: none

### 4. Metoprolol succinate 25 mg PO daily → `MedicationRequest`

- **Source span:** *"INITIATE metoprolol succinate 25 mg PO once daily as anti-anginal therapy and rate control"* (A&P #1)
- **Class:** `NEW` — never made it to the home structured record
- **Resource fields:**
  - `medicationCodeableConcept`: RxNorm 866427 (Metoprolol Succinate 25 MG Extended Release Oral Tablet)
  - `status`: `active`
  - `intent`: `order`
  - `authoredOn`: `2025-10-20`
  - `requester`: Dr. David Park
  - `dosageInstruction`: 25 mg PO once daily

---

## Note 2 — ED Discharge Summary (Dr. Tom Brown, Riverside Hospital, 2025-12-15)

**1 augmentation** — but it's the most important one in the demo: the **conflict**.

### 5. Penicillin allergy → `AllergyIntolerance`

- **Source span:** *"PENICILLIN — patient reports a rash as a child following an oral antibiotic course (estimated age 6 to 8). He describes the reaction as a non-pruritic, non-urticarial rash that resolved without intervention. NO history of facial swelling, lip or tongue swelling, throat tightness, breathing difficulty, hypotension, or anaphylaxis."* (Allergies)
- **Class:** `CONFLICTING` — directly contradicts the home record's "no known drug allergies"
- **Engine extraction challenge:** Beyond just identifying *that* there's an allergy, the engine should extract enough detail to support **risk stratification**. The note contains all the elements clinicians use to triage low-risk versus high-risk allergy labels — the engine should populate them so downstream agents can reason about delabeling candidacy.
- **Resource fields:**
  - `code`: RxNorm 7980 (Penicillin)
  - `clinicalStatus`: `active`
  - `verificationStatus`: `confirmed`
  - `type`: `allergy`
  - `category`: `medication`
  - `criticality`: `low` (derived from the documented absence of anaphylactic features)
  - `onsetAge`: ~7 years (derived from "estimated age 6 to 8")
  - `reaction.severity`: `mild`
  - `reaction.manifestation`: SNOMED 271807003 (Eruption of skin)
  - `reaction.exposureRoute`: SNOMED 26643006 (Oral route)
  - `note`: childhood reaction, cutaneous-only, no anaphylaxis, last exposure unknown

The richness of this resource — not just *"patient has penicillin allergy"* but *"patient has a low-risk childhood penicillin label with documented absence of anaphylactic features"* — is what powers the downstream **delabeling-candidate** insight in the closing visit-prep beat.

---

## Note 3 — Neurology Follow-up (Dr. Lisa Chen, 2026-02-23)

**3 augmentations**, the densest note. Tests the engine's ability to handle UPDATING classification, multi-section consolidation, and derived clinical flags.

### 6. Lisinopril dose change 10 → 20 mg → `MedicationRequest`

- **Source span:** *"Increase lisinopril from 10 mg to 20 mg PO once daily, in coordination with PCP for ongoing titration"* (A&P #2)
- **Supporting span:** *"Hypertension — uncontrolled in clinic today (168/95, confirmed with repeat measurement 164/93). Above goal of < 130/80 for secondary stroke prevention."*
- **Class:** `UPDATING` — same RxNorm-coded medication exists in the record, dose changed
- **Engine classification challenge:** Must distinguish UPDATING (same med, dose change) from CONFLICTING (which would suggest contradictory information requiring clinician attention). The signal is shared RxNorm ingredient code with different dose strength.
- **Resource fields (new MedicationRequest, supersedes the existing 10mg):**
  - `medicationCodeableConcept`: RxNorm 314077 (Lisinopril 20 MG Oral Tablet)
  - `status`: `active`
  - `intent`: `order`
  - `priorPrescription`: reference to existing Lisinopril 10mg MedicationRequest
  - `authoredOn`: `2026-02-23`
  - `requester`: Dr. Lisa Chen
  - `dosageInstruction`: 20 mg PO once daily

### 7. Smoking status: former smoker, quit ~3 months ago, 30 pack-year history → `Observation`

- **Source span:** *"Tobacco cessation: He successfully quit smoking approximately 3 months ago (early November 2025) and remains tobacco-free. He has an estimated 30 pack-year history (approximately 1 pack per day x 30 years prior to cessation)."* (Interval History)
- **Supporting spans:** *"former smoker, quit ~3 months ago, 30 pack-year history"* (Social History) and *"sustained 3 months, 30 pack-year history"* (A&P #3)
- **Class:** `NEW` — no prior smoking status documented anywhere in the structured record
- **Engine consolidation challenge:** The same fact appears in three different sections (Interval History, Social History, A&P). The engine should consolidate into a single Observation, not create three duplicates.
- **Resource fields:**
  - `code`: LOINC 72166-2 (Tobacco smoking status)
  - `status`: `final`
  - `category`: `social-history`
  - `valueCodeableConcept`: SNOMED 8517006 (Ex-smoker / Former smoker)
  - `effectiveDateTime`: `2026-02-23`
  - `component` (or related Observation): pack-year history = 30, with code LOINC 8663-7

### 8. Family history: father MI at age 52 → `FamilyMemberHistory`

- **Source span:** *"his father suffered a myocardial infarction at age 52 and survived; his father subsequently died of an unrelated cause at age 71"* (Interval History)
- **Class:** `NEW` — no family history documented in the structured record
- **Engine reasoning challenge:** The engine should recognize that *male first-degree relative with MI at age <55* meets the **premature CAD** criterion (per ATP III / ACC / ESC) and flag this. The flag is what powers the downstream "implications for lipid targets and primary prevention" reasoning.
- **Resource fields:**
  - `relationship`: SNOMED 9947004 (Father)
  - `condition.code`: SNOMED 22298006 (Myocardial infarction) + ICD-10 I21.9
  - `condition.onsetAge`: 52 years
  - `deceasedAge`: 71 (father died of unrelated cause)
  - Optional/computed: premature CAD flag = true (derived; not a standard FHIR field)

---

## Note 4 — Cardiology Follow-up, ACE-inhibitor cough (Dr. David Park, 2026-01-22)

Lives only as the base64 attachment on the `cardio-followup-conflict` DocumentReference; there is no `note-4-*.md` artifact.

Documents a 3-month follow-up after stable angina management. Patient developed a persistent dry cough about 3 weeks after starting lisinopril. Cardiology attributes it to ACE-inhibitor intolerance, **discontinues lisinopril 10 mg**, and **switches to losartan 50 mg PO daily**. Metoprolol, atorvastatin, ASA continued.

**Engine challenge:** the neurology note (note 3, 2026-02-23) increases lisinopril 10 → 20 mg, which contradicts this discontinuation one month earlier. The agent should surface this temporal conflict — both notes were written in good faith, but the chart timeline is incoherent without reconciliation. Expected augmentations include a status change on the existing lisinopril order, a NEW losartan MedicationRequest, and a flag on the ACE-inhibitor intolerance.

---

# Three derived insights (NOT augmentations — agent reasoning over the augmented record)

These appear in the **closing visit-prep beat** of the demo, not in the augmentation review screen. They demonstrate that consumer agents (e.g., the visit-prep agent) can do clinical reasoning *because* the structured record is now complete.

| # | Insight | Reasoning chain |
|---|---|---|
| A | Penicillin delabeling candidate per stewardship criteria | AllergyIntolerance with `criticality=low` + childhood onset + no anaphylactic features → meets PEN-FAST low-risk phenotype |
| B | BP still uncontrolled at 168/95; recommend further titration | Most recent BP Observation > target of 130/80 for secondary stroke prevention |
| C | Missing SGLT2 inhibitor or GLP-1 RA despite T2DM + ASCVD | T2DM Condition + CAD/stroke Condition + medication list lacks SGLT2/GLP-1 → care gap per current ADA/AHA guidance |

The platform thesis lands here: **clean structured data unlocks downstream agent value.** The visit-prep agent generates these insights only because the augmentations made the underlying facts queryable. None of these insights would have been possible against the pre-augmentation record.

---

# Conformance and validation

- **FHIR R4** (4.0.1)
- **US Core 6.1.0** profiles applied via `meta.profile` on each resource
- **Code systems:** SNOMED CT (`http://snomed.info/sct`), LOINC (`http://loinc.org`), ICD-10-CM (`http://hl7.org/fhir/sid/icd-10-cm`), RxNorm (`http://www.nlm.nih.gov/research/umls/rxnorm`), HL7 v3 ActCode and condition terminologies, US Core DocumentReference category, IHE format codes, OMB race/ethnicity (CDCREC)
- **References:** all 42 cross-resource references resolve via `urn:uuid:` to other entries in the bundle
- **All augmentation source spans verified findable** in the note text (whitespace-normalized substring match)

Validation results from `validate_bundle.py`:

```
Bundle: anamnesis-demo-bundle.json
Total entries: 22
Total Reference targets: 10
Total Codings: 53

=== ERRORS (0) ===

=== WARNINGS (0) ===

PASS
```

## How to load into Prompt Opinion's FHIR server

The bundle is `Bundle.type = "transaction"`. POST it to the FHIR server's base URL (not to `/Bundle`):

```http
POST https://<po-fhir-base>/
Content-Type: application/fhir+json
Authorization: Bearer <SHARP-token>

{...bundle JSON...}
```

The server will:
1. Assign real resource IDs to each entry
2. Resolve `urn:uuid:` references between resources to those new IDs
3. Return a `transaction-response` Bundle with the assigned IDs

If the platform supports bundle upload through the UI, use the "Upload FHIR Bundle" option in the Patients section. Verify after loading by checking that the patient appears in the patient list, the problem list shows 4 conditions, the medication list shows 4 active prescriptions, and 4 documents are accessible under the patient's chart.

## Re-running the build

```bash
pip install fhir.resources
python3 build_bundle.py        # writes anamnesis-demo-bundle.json
python3 validate_bundle.py     # runs all validation checks
```

## A note on the cardiac cath span

The cardio note uses *"left heart catheterization"* (the clinically precise term), not *"cardiac catheterization"* (the colloquial term). This is intentional — the augmentation engine should map both phrases to SNOMED 41976001 (Cardiac catheterization). It's a small piece of clinical synonym work that demonstrates the engine isn't doing keyword matching.

Similarly, the *cath performed date* (10/15/2025) is in HPI prose, not the encounter date (10/20/2025). The engine has to do clinical-temporal extraction, not default to the encounter timestamp. These small touches are deliberately included so traceability inspection rewards careful examination.
