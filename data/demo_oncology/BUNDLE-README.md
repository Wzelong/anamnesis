# Anamnesis mCODE Oncology Demo Bundle

The FHIR R4 / US Core 6.1.0 bundle that anchors the **mCODE oncology** demo.
Contains the existing structured record for **Margaret Sullivan** (the
augmentation engine's input) plus three oncology notes (its source material).
The mCODE augmentations are the engine's output and are *not* in this bundle.

This demo is the oncology counterpart to the James Lee bundle. Where James Lee
exercises US Core augmentation, this bundle exercises the **mCODE specialty IG**:
primary/secondary cancer conditions, TNM staging, tumor markers, performance
status, histologic grade, disease status, tumor size, and cancer-related
procedures/medications.

## Files

| File | Purpose |
|---|---|
| `oncology-demo-bundle.json` | FHIR R4 transaction Bundle (19 resources). POST to a FHIR server. |
| `note-1-oncology-consultation.md` | Medical oncology consult — staging + biomarkers (artifact view of the inline note). |
| `note-2-surgical-pathology.md` | Surgical pathology report — post-neoadjuvant resection. |
| `note-3-oncology-followup.md` | Oncology follow-up — progression to bone metastasis. |
| `build_bundle.py` | Builder; reads the three `.md` files and base64-embeds them. |
| `validate_bundle.py` | Structure + reference-integrity + note-decode checks (PASS). |

## Patient

**Margaret Sullivan**, 58yo female (DOB 1966-09-12), MRN OAK-0117-SUL,
established at **Oakwood Cancer Center**. White, Not Hispanic or Latino,
birth sex F (USCDI demographics populated).

## What's in the bundle (19 resources, baseline / pre-augmentation)

| Type | Count | Items |
|---|---|---|
| Organization | 2 | Oakwood Cancer Center (home), Lakeshore Imaging (outside) |
| Practitioner | 3 | Dr. Priya Rao (med onc), Dr. Ellen Voss (breast surgery), Dr. Mark Liu (radiology) |
| Patient | 1 | Margaret Sullivan |
| Condition | 3 | **Malignant neoplasm of right breast (bare — ICD-10 C50.911 only)**, Essential HTN, Osteopenia |
| MedicationRequest | 2 | Lisinopril 10 mg daily, calcium/vitamin D |
| Observation | 1 | Diagnostic mammography, BI-RADS 5 |
| Procedure | 1 | Core needle biopsy, right breast |
| Encounter | 3 | Onc consult (09/2025), surgery/pathology (12/2025), follow-up (02/2027) |
| DocumentReference | 3 | The three notes, full text base64 inline, LOINC-typed |

### What is deliberately NOT in the structured baseline

The cancer exists only as a **bare, under-coded problem-list entry** — ICD-10
`C50.911` with a generic name, **no SNOMED, no coded body site, no mCODE
profile, no staging, no biomarkers**. This mirrors how oncology data actually
sits in most EHRs: the diagnosis is on the list, but everything that makes it
*computable* is trapped in notes. The augmentations fill exactly that gap.

Also absent: TNM/stage, ER/PR/HER2, histologic grade, ECOG, tumor size,
cancer-related medications, the surgery record, disease status, and the
metastasis.

---

# Expected mCODE augmentations per note

This is the contract the engine satisfies with the **mCODE specialty preset
active**. Profiles below are the `mcode-*` `meta.profile` the engine attaches.
Exact extraction varies run-to-run (LLM); the demo freezes one run via
`dump_demo_proposals.py`. The structure below reflects a validated live run.

## Note 1 — Medical Oncology Consultation (Dr. Rao, 2025-09-18)

| Augmentation | mCODE profile | Key coding |
|---|---|---|
| Invasive ductal carcinoma, **right breast** | `primary-cancer-condition` | SNOMED 82711006 · bodySite 73056007 |
| Clinical primary tumor **cT2** | `tnm-primary-tumor-category` | LOINC 21905-5 (clinical) |
| Clinical regional nodes **cN1** | `tnm-regional-nodes-category` | LOINC 21906-3 |
| Clinical distant mets **cM0** | `tnm-distant-metastases-category` | LOINC 21907-1 |
| Stage group **IIB** | `tnm-stage-group` | LOINC 21908-9 |
| **ER positive** | `tumor-marker-test` | LOINC 16112-5 |
| **PR positive** | `tumor-marker-test` | LOINC 16113-3 |
| **HER2 negative (IHC 1+)** | `tumor-marker-test` | LOINC 18474-7 |
| Ki-67 | `tumor-marker-test` | LOINC 29593-1 |
| **Nottingham grade 2** | `histologic-grade` | NCIt C18000 |
| ECOG 1 | `ecog-performance-status` | LOINC 89247-1 |
| Doxorubicin / cyclophosphamide / paclitaxel | `cancer-related-medication-request` | RxNorm |

## Note 2 — Surgical Pathology (Dr. Voss, 2025-12-03)

| Augmentation | mCODE profile | Key coding |
|---|---|---|
| Residual invasive ductal carcinoma (multifocal → **one** condition) | `primary-cancer-condition` | SNOMED 82711006 |
| **Tumor size 1.1 cm** | `tumor-size` | LOINC 21889-1 (Quantity) |
| Pathologic primary tumor **ypT1c** | `tnm-primary-tumor-category` | LOINC 21899-0 (**pathologic**) |
| Pathologic nodes **ypN0** | `tnm-regional-nodes-category` | LOINC 21900-6 |
| Nottingham grade 2 | `histologic-grade` | NCIt C18000 |
| Disease status: **partial response** | `cancer-disease-status` | LOINC 97509-4 |
| **Partial mastectomy** | `cancer-related-surgical-procedure` | SNOMED 736754007 |

## Note 3 — Oncology Follow-up / Progression (Dr. Rao, 2027-02-10)

| Augmentation | mCODE profile | Key coding |
|---|---|---|
| **Metastatic carcinoma, L3 vertebra (secondary)** | `secondary-cancer-condition` | ICD-10 C79.51 · bodySite 731669001 |
| Disease status: **progression** | `cancer-disease-status` | LOINC 97509-4 |
| Stage group **IV** | `tnm-stage-group` | LOINC 21908-9 |
| ECOG 1 | `ecog-performance-status` | LOINC 89247-1 |
| ER positive / PR positive / HER2 negative (concordant) | `tumor-marker-test` | LOINC |
| Palbociclib / fulvestrant | `cancer-related-medication-request` | RxNorm 1601387 / 282357 |

---

# Deliberate clinical-intelligence touches

These reward careful inspection and distinguish a clinically aware engine from a
keyword extractor — and they are written into **clinically realistic prose**,
never engineered fields:

1. **HER2 *negative* is captured.** Most extractors drop negatives as
   pertinent-negatives; a HER2-negative result drives treatment, so mCODE keeps
   it. (Note 1, also spelled out as "human epidermal growth factor receptor 2".)
2. **Combined TNM is split.** "cT2 cN1 cM0, AJCC stage IIB" becomes three
   category observations *plus* a separate stage group — not one blob.
3. **Clinical vs pathologic codes.** Note 1's `cT2` codes to the clinical LOINC;
   Note 2's `ypT1c` codes to the *pathologic* LOINC — the engine reads the
   c/p/y prefix.
4. **Primary vs secondary.** The L3 lesion is named "metastatic / secondary," so
   it lands as a *secondary*-cancer-condition distinct from the primary — a
   keyword extractor would create a second primary.
5. **Context-linking.** The partial mastectomy has no explicit "for cancer"
   reason, yet is tagged cancer-related by **body-site match** to the breast
   cancer — while the patient's incidental procedures are not.
6. **Multifocality.** Two foci in one specimen collapse to **one** condition,
   not two cancers.
7. **Disease trajectory.** Disease status moves "partial response" → "progression"
   and stage IIB → IV across the timeline — queryable because each is structured.

---

# Three derived insights (agent reasoning over the mCODE-augmented record)

Only possible *because* the record is now mCODE-structured:

| # | Insight | Reasoning chain |
|---|---|---|
| A | **Endocrine therapy indicated; anti-HER2 therapy not** | ER+/PR+ tumor-marker observations + HER2-negative → HR-positive, HER2-negative phenotype |
| B | **Disease progressed IIB → IV on endocrine therapy** | stage-group + disease-status observations across time → trajectory is queryable |
| C | **Bone metastasis → bone-modifying-agent need + DEXA gap** | secondary-cancer-condition (bone) + baseline osteopenia + aromatase-inhibitor exposure |

The platform thesis: **clean structured oncology data unlocks downstream agent
value.** None of these insights is possible against the bare pre-augmentation
record.

---

# mCODE feature coverage

Every mCODE capability is exercised across the three notes: primary &
**secondary** cancer condition, coded bodySite, TNM categories (clinical &
pathologic), stage group, tumor markers (incl. negative), histologic grade,
ECOG, **cancer disease status**, **tumor size**, **cancer-related surgical
procedure** (incl. context-linking), cancer-related medication, multifocal
merge, and clinical/pathologic code selection.

---

# Conformance and validation

- **FHIR R4** (4.0.1) transaction bundle; **US Core 6.1.0** on the baseline.
- Augmentations additionally carry `mcode-*` profiles (mCODE STU4 / 4.0.0).
- Code systems: SNOMED CT, LOINC, ICD-10-CM, RxNorm, NCI Thesaurus (grade),
  plus HL7 terminologies and CDCREC demographics.
- All 38 `urn:uuid:` references resolve within the bundle; all three notes decode.

```
python build_bundle.py        # writes oncology-demo-bundle.json
python validate_bundle.py     # structure + reference integrity (PASS)
```

## A note on realism

The notes are written as clinically realistic oncology documents (modeled on the
register of real de-identified notes), **not** engineered to make extraction
succeed. Where the pipeline misses something on natural prose, that is honest
feedback about the pipeline — fixed generically (e.g. recognizing "human
epidermal growth factor receptor 2" as HER2), never papered over in the note.
