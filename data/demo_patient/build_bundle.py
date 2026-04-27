"""
Build the Anamnesis demo patient FHIR Bundle.

Patient: James Lee, 67yo male, established at Bayside Health.
Three documents in his chart from past 8 months:
  - Cardiology consult (Bayside, ~6 months ago)
  - ED discharge summary (Riverside Hospital - external, ~4 months ago)
  - Neurology follow-up (Bayside, ~2 months ago)

The bundle contains the EXISTING structured FHIR record + the document
references (with note text). Augmentation outputs are NOT in this bundle —
they are what the engine PRODUCES against this baseline.

Compliant with FHIR R4 + US Core 6.1.0 profiles.
"""

import json
import uuid
from datetime import date
from base64 import b64encode

# fhir.resources R4B has the validators we need (R4B is R4 + errata)
from fhir.resources.R4B.bundle import Bundle, BundleEntry, BundleEntryRequest
from fhir.resources.R4B.patient import Patient
from fhir.resources.R4B.practitioner import Practitioner
from fhir.resources.R4B.organization import Organization
from fhir.resources.R4B.condition import Condition
from fhir.resources.R4B.medicationrequest import MedicationRequest
from fhir.resources.R4B.encounter import Encounter
from fhir.resources.R4B.documentreference import DocumentReference
from fhir.resources.R4B.identifier import Identifier
from fhir.resources.R4B.humanname import HumanName
from fhir.resources.R4B.contactpoint import ContactPoint
from fhir.resources.R4B.address import Address
from fhir.resources.R4B.codeableconcept import CodeableConcept
from fhir.resources.R4B.coding import Coding
from fhir.resources.R4B.reference import Reference
from fhir.resources.R4B.extension import Extension
from fhir.resources.R4B.narrative import Narrative
from fhir.resources.R4B.dosage import Dosage
from fhir.resources.R4B.timing import Timing, TimingRepeat
from fhir.resources.R4B.quantity import Quantity
from fhir.resources.R4B.period import Period
from fhir.resources.R4B.attachment import Attachment

# ---------------------------------------------------------------------------
# Stable UUIDs (deterministic via uuid5 from a fixed namespace)
# ---------------------------------------------------------------------------
NS = uuid.UUID("00000000-0000-0000-0000-000000000001")
def U(name):
    return f"urn:uuid:{uuid.uuid5(NS, name)}"

# Resources
ORG_BAYSIDE   = U("org.bayside")
ORG_RIVERSIDE = U("org.riverside")
PRAC_KIM      = U("prac.kim")        # PCP
PRAC_PARK     = U("prac.park")       # Cardiologist
PRAC_BROWN    = U("prac.brown")      # ED physician
PRAC_CHEN     = U("prac.chen")       # Neurologist
PATIENT       = U("patient.lee")

COND_HTN     = U("cond.htn")
COND_T2DM    = U("cond.t2dm")
COND_HLD     = U("cond.hld")
COND_FATIGUE = U("cond.fatigue")

MED_LISINOPRIL  = U("med.lisinopril")
MED_ATORVA      = U("med.atorvastatin")
MED_METFORMIN   = U("med.metformin")
MED_ASPIRIN     = U("med.aspirin")

ENC_CARDIO  = U("enc.cardio")
ENC_ED      = U("enc.ed")
ENC_NEURO   = U("enc.neuro")

DOC_CARDIO  = U("doc.cardio")
DOC_ED      = U("doc.ed")
DOC_NEURO   = U("doc.neuro")

# ---------------------------------------------------------------------------
# Common code systems (constants for clarity)
# ---------------------------------------------------------------------------
SCT      = "http://snomed.info/sct"
LOINC    = "http://loinc.org"
ICD10    = "http://hl7.org/fhir/sid/icd-10-cm"
RXNORM   = "http://www.nlm.nih.gov/research/umls/rxnorm"
HL7_CC   = "http://terminology.hl7.org/CodeSystem/condition-clinical"
HL7_CV   = "http://terminology.hl7.org/CodeSystem/condition-ver-status"
HL7_CCAT = "http://terminology.hl7.org/CodeSystem/condition-category"
HL7_V3_ROLE = "http://terminology.hl7.org/CodeSystem/v2-0203"
HL7_V3_ACT  = "http://terminology.hl7.org/CodeSystem/v3-ActCode"
US_CORE_DOC_CAT = "http://hl7.org/fhir/us/core/CodeSystem/us-core-documentreference-category"
CDCREC   = "urn:oid:2.16.840.1.113883.6.238"  # Race & Ethnicity - CDC

US_CORE = "http://hl7.org/fhir/us/core/StructureDefinition"
def profile(name):
    return [f"{US_CORE}/{name}"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def cc(system, code, display, text=None):
    """Build a CodeableConcept with a single Coding."""
    return CodeableConcept(
        coding=[Coding(system=system, code=code, display=display)],
        text=text or display,
    )

def cc_multi(codings, text):
    """CodeableConcept with multiple codings (e.g., SNOMED + ICD-10)."""
    return CodeableConcept(coding=codings, text=text)

def ref(urn, display=None):
    return Reference(reference=urn, display=display)

def narrative(html):
    return Narrative(status="generated", div=f'<div xmlns="http://www.w3.org/1999/xhtml">{html}</div>')

# ---------------------------------------------------------------------------
# Organizations
# ---------------------------------------------------------------------------
bayside = Organization(
    id="bayside",
    meta={"profile": profile("us-core-organization")},
    text=narrative("<p>Bayside Health (home health system)</p>"),
    identifier=[Identifier(
        system="http://bayside.health/org-id",
        value="BAYSIDE-HQ",
    )],
    active=True,
    name="Bayside Health",
    type=[cc("http://terminology.hl7.org/CodeSystem/organization-type", "prov", "Healthcare Provider")],
    telecom=[ContactPoint(system="phone", value="+1-617-555-0100", use="work")],
    address=[Address(
        line=["100 Bayside Drive"],
        city="Boston", state="MA", postalCode="02110", country="US",
    )],
)

riverside = Organization(
    id="riverside",
    meta={"profile": profile("us-core-organization")},
    text=narrative("<p>Riverside Hospital (outside facility)</p>"),
    identifier=[Identifier(
        system="http://riverside.example.org/org-id",
        value="RIVERSIDE-1",
    )],
    active=True,
    name="Riverside Hospital",
    type=[cc("http://terminology.hl7.org/CodeSystem/organization-type", "prov", "Healthcare Provider")],
    telecom=[ContactPoint(system="phone", value="+1-555-555-0200", use="work")],
    address=[Address(
        line=["500 Riverside Way"],
        city="Cambridge", state="MA", postalCode="02139", country="US",
    )],
)

# ---------------------------------------------------------------------------
# Practitioners (US Core requires identifier, name)
# ---------------------------------------------------------------------------
def make_practitioner(_id, npi, family, given, prefix="Dr."):
    return Practitioner(
        id=_id,
        meta={"profile": profile("us-core-practitioner")},
        text=narrative(f"<p>{prefix} {given} {family}</p>"),
        identifier=[Identifier(
            system="http://hl7.org/fhir/sid/us-npi",
            value=npi,
        )],
        active=True,
        name=[HumanName(use="official", family=family, given=[given], prefix=[prefix])],
    )

prac_kim   = make_practitioner("kim",   "1234567890", "Kim",   "Anna")
prac_park  = make_practitioner("park",  "2345678901", "Park",  "David")
prac_brown = make_practitioner("brown", "3456789012", "Brown", "Tom")
prac_chen  = make_practitioner("chen",  "4567890123", "Chen",  "Lisa")

# ---------------------------------------------------------------------------
# Patient (US Core Patient: identifier, name, gender mandatory;
# race, ethnicity, birthsex, sex extensions for USCDI)
# ---------------------------------------------------------------------------
race_ext = Extension(
    url=f"{US_CORE}/us-core-race",
    extension=[
        Extension(url="ombCategory", valueCoding=Coding(
            system=CDCREC, code="2028-9", display="Asian"
        )),
        Extension(url="text", valueString="Asian"),
    ],
)
ethnicity_ext = Extension(
    url=f"{US_CORE}/us-core-ethnicity",
    extension=[
        Extension(url="ombCategory", valueCoding=Coding(
            system=CDCREC, code="2186-5", display="Not Hispanic or Latino"
        )),
        Extension(url="text", valueString="Not Hispanic or Latino"),
    ],
)
birthsex_ext = Extension(
    url=f"{US_CORE}/us-core-birthsex",
    valueCode="M",
)

patient = Patient(
    id="lee-james",
    meta={"profile": profile("us-core-patient")},
    extension=[race_ext, ethnicity_ext, birthsex_ext],
    text=narrative("<p>James Lee, 67yo male, MRN BAY-0042-LEE</p>"),
    identifier=[
        Identifier(
            use="usual",
            type=cc(HL7_V3_ROLE, "MR", "Medical Record Number"),
            system="http://bayside.health/mrn",
            value="BAY-0042-LEE",
        ),
    ],
    active=True,
    name=[HumanName(use="official", family="Lee", given=["James"])],
    telecom=[
        ContactPoint(system="phone", value="+1-617-555-0142", use="home"),
    ],
    gender="male",
    birthDate=date(1958, 11, 15),
    address=[Address(
        use="home",
        line=["12 Harborview Lane"],
        city="Boston", state="MA", postalCode="02129", country="US",
    )],
    managingOrganization=ref(ORG_BAYSIDE, "Bayside Health"),
)

# ---------------------------------------------------------------------------
# Conditions (US Core Condition Problems and Health Concerns)
# ---------------------------------------------------------------------------
def make_problem(_id, code_codings, text, onset, recorded):
    return Condition(
        id=_id,
        meta={"profile": profile("us-core-condition-problems-health-concerns")},
        text=narrative(f"<p>{text}</p>"),
        clinicalStatus=cc(HL7_CC, "active", "Active"),
        verificationStatus=cc(HL7_CV, "confirmed", "Confirmed"),
        category=[cc(HL7_CCAT, "problem-list-item", "Problem List Item")],
        code=cc_multi(code_codings, text),
        subject=ref(PATIENT, "James Lee"),
        onsetDateTime=onset,
        recordedDate=recorded,
        recorder=ref(PRAC_KIM, "Dr. Anna Kim"),
        asserter=ref(PRAC_KIM, "Dr. Anna Kim"),
    )

cond_htn = make_problem(
    "htn",
    [
        Coding(system=SCT, code="59621000", display="Essential hypertension"),
        Coding(system=ICD10, code="I10", display="Essential (primary) hypertension"),
    ],
    "Essential hypertension",
    onset="2016-03-15",
    recorded="2016-03-15",
)

cond_t2dm = make_problem(
    "t2dm",
    [
        Coding(system=SCT, code="44054006", display="Type 2 diabetes mellitus"),
        Coding(system=ICD10, code="E11.9", display="Type 2 diabetes mellitus without complications"),
    ],
    "Type 2 diabetes mellitus",
    onset="2018-05-20",
    recorded="2018-05-20",
)

cond_hld = make_problem(
    "hld",
    [
        Coding(system=SCT, code="55822004", display="Hyperlipidemia"),
        Coding(system=ICD10, code="E78.5", display="Hyperlipidemia, unspecified"),
    ],
    "Hyperlipidemia",
    onset="2016-03-15",
    recorded="2016-03-15",
)

cond_fatigue = make_problem(
    "post-stroke-fatigue",
    [
        # No precise SNOMED for "post-stroke fatigue" — we code Fatigue + sequelae context in text
        Coding(system=SCT, code="84229001", display="Fatigue"),
        Coding(system=ICD10, code="I69.398", display="Other sequelae of cerebral infarction"),
    ],
    "Chronic post-stroke fatigue (sequelae of minor ischemic stroke 2024)",
    onset="2024-04-15",
    recorded="2024-05-10",
)

# ---------------------------------------------------------------------------
# MedicationRequests (US Core MedicationRequest)
# ---------------------------------------------------------------------------
def make_med(_id, rxnorm_code, rxnorm_display, dose_text, freq, period_unit="d"):
    """Build a US Core MedicationRequest with reportedBoolean=False."""
    return MedicationRequest(
        id=_id,
        meta={"profile": profile("us-core-medicationrequest")},
        text=narrative(f"<p>{rxnorm_display} — {dose_text}</p>"),
        status="active",
        intent="order",
        reportedBoolean=False,  # Required: one of reportedBoolean/reportedReference
        medicationCodeableConcept=cc(RXNORM, rxnorm_code, rxnorm_display),
        subject=ref(PATIENT, "James Lee"),
        authoredOn="2024-08-01",
        requester=ref(PRAC_KIM, "Dr. Anna Kim"),
        dosageInstruction=[Dosage(
            text=dose_text,
            timing=Timing(repeat=TimingRepeat(frequency=freq, period=1, periodUnit=period_unit)),
            route=cc(SCT, "26643006", "Oral route"),
        )],
    )

med_lisinopril = make_med(
    "lisinopril-10",
    "314076",  # Lisinopril 10 MG Oral Tablet (RxNorm SCD)
    "Lisinopril 10 MG Oral Tablet",
    "Take 1 tablet (10 mg) by mouth once daily",
    freq=1,
)

med_atorvastatin = make_med(
    "atorvastatin-40",
    "617314",  # Atorvastatin 40 MG Oral Tablet
    "Atorvastatin 40 MG Oral Tablet",
    "Take 1 tablet (40 mg) by mouth once daily",
    freq=1,
)

med_metformin = make_med(
    "metformin-1000",
    "861007",  # Metformin hydrochloride 1000 MG Oral Tablet
    "Metformin hydrochloride 1000 MG Oral Tablet",
    "Take 1 tablet (1000 mg) by mouth twice daily",
    freq=2,
)

med_aspirin = make_med(
    "aspirin-81",
    "243670",  # Aspirin 81 MG Oral Tablet
    "Aspirin 81 MG Oral Tablet",
    "Take 1 tablet (81 mg) by mouth once daily",
    freq=1,
)

# ---------------------------------------------------------------------------
# Encounters (one per source note)
# ---------------------------------------------------------------------------
from fhir.resources.R4B.encounter import EncounterParticipant

def make_encounter(_id, profile_name, class_code, class_display, type_codings, type_text,
                   period_start, period_end, participant_practitioner_ref, participant_name,
                   service_provider_ref, reason_codings=None):
    return Encounter(
        id=_id,
        meta={"profile": profile(profile_name)},
        text=narrative(f"<p>{type_text}, {period_start[:10]}</p>"),
        identifier=[Identifier(
            system="http://bayside.health/encounter-id",
            value=f"ENC-{_id.upper()}",
        )],
        status="finished",
        **{"class": Coding(system=HL7_V3_ACT, code=class_code, display=class_display)},
        type=[CodeableConcept(coding=type_codings, text=type_text)],
        subject=ref(PATIENT, "James Lee"),
        participant=[EncounterParticipant(
            individual=ref(participant_practitioner_ref, participant_name),
            period=Period(start=period_start, end=period_end),
        )],
        period=Period(start=period_start, end=period_end),
        reasonCode=[CodeableConcept(coding=reason_codings, text=reason_codings[0].display)]
                   if reason_codings else None,
        serviceProvider=ref(service_provider_ref),
    )

enc_cardio = make_encounter(
    "cardio-consult",
    "us-core-encounter",
    "AMB", "ambulatory",
    [
        Coding(system=SCT, code="11429006", display="Consultation"),
        Coding(system=LOINC, code="11488-4", display="Consult note"),
    ],
    "Cardiology Consultation",
    "2025-10-20T10:30:00-04:00",
    "2025-10-20T11:42:00-04:00",
    PRAC_PARK, "Dr. David Park",
    ORG_BAYSIDE,
    reason_codings=[Coding(system=SCT, code="29857009", display="Chest pain")],
)

enc_ed = make_encounter(
    "ed-visit",
    "us-core-encounter",
    "EMER", "emergency",
    [
        Coding(system=SCT, code="50849002", display="Emergency room admission"),
    ],
    "Emergency Department Visit",
    "2025-12-15T14:20:00-05:00",
    "2025-12-15T18:52:00-05:00",
    PRAC_BROWN, "Dr. Tom Brown",
    ORG_RIVERSIDE,
    reason_codings=[Coding(system=SCT, code="21522001", display="Abdominal pain")],
)

enc_neuro = make_encounter(
    "neuro-followup",
    "us-core-encounter",
    "AMB", "ambulatory",
    [
        Coding(system=SCT, code="185349003", display="Encounter for check up"),
        Coding(system=LOINC, code="11488-4", display="Consult note"),
    ],
    "Neurology Follow-up",
    "2026-02-23T10:00:00-05:00",
    "2026-02-23T10:51:00-05:00",
    PRAC_CHEN, "Dr. Lisa Chen",
    ORG_BAYSIDE,
    reason_codings=[Coding(system=SCT, code="84229001", display="Fatigue")],
)

# ---------------------------------------------------------------------------
# DocumentReferences with full clinical note text
# ---------------------------------------------------------------------------
from fhir.resources.R4B.documentreference import (
    DocumentReferenceContent,
    DocumentReferenceContext,
)

CARDIO_NOTE = """\
═══════════════════════════════════════════════════════════════
   BAYSIDE HEALTH  |  DEPARTMENT OF CARDIOLOGY
   Outpatient Consultation Note
═══════════════════════════════════════════════════════════════

Patient:           LEE, JAMES
MRN:               BAY-0042-LEE
DOB:               11/15/1958  (66 y, M)
Encounter Date:    10/20/2025  10:30 EDT
Encounter ID:      ENC-CARDIO-CONSULT
Visit Type:        Outpatient Consultation, post-procedure
Service:           Cardiology
Attending:         David Park, MD
Referring:         Anna Kim, MD  (Bayside Family Medicine)
═══════════════════════════════════════════════════════════════


CHIEF COMPLAINT
Exertional chest pressure; post-catheterization follow-up and
finalization of medical management plan.


HISTORY OF PRESENT ILLNESS
Mr. James Lee is a 66-year-old male with a history of hypertension,
type 2 diabetes mellitus, hyperlipidemia, and minor ischemic stroke
(2024) who was referred by Dr. Anna Kim on 09/15/2025 for evaluation
of approximately six weeks of substernal chest pressure occurring
with moderate exertion (climbing two flights of stairs, walking
briskly uphill). Symptoms are reproducible, last 3 to 5 minutes,
and resolve fully with rest. There has been no progression to rest
or nocturnal pain, no associated dyspnea at rest, no syncope, and
no palpitations. CCS class II.

The patient was seen for initial cardiology evaluation on 09/22/2025
(separate note). Resting ECG demonstrated normal sinus rhythm with
non-specific lateral T-wave flattening; no acute ischemic changes.
Given typical anginal pattern, intermediate-to-high pretest
probability of obstructive disease, and presence of multiple ASCVD
risk factors, the decision was made to proceed with diagnostic
cardiac catheterization.

Diagnostic left heart catheterization was performed by this provider
on 10/15/2025. Refer to procedure report for full details. Findings:
two-vessel coronary artery disease, with 60% mid-LAD stenosis and
70% proximal RCA stenosis. No left main disease. No high-grade or
sub-occlusive lesions. LVEF preserved at 55%. Right radial access;
no procedural complications.

The patient returns today for review of findings and finalization
of medical management plan.


PAST MEDICAL HISTORY
- Essential hypertension (since 2016)
- Type 2 diabetes mellitus, on metformin (since 2018)
- Hyperlipidemia (since 2016)
- Minor ischemic stroke (2024) with chronic post-stroke fatigue
- Longstanding tobacco use


PAST SURGICAL HISTORY
None.


HOME MEDICATIONS  (reviewed and reconciled)
- Lisinopril 10 mg PO daily
- Atorvastatin 40 mg PO daily
- Metformin 1000 mg PO BID
- Aspirin 81 mg PO daily


ALLERGIES
No known drug allergies.


SOCIAL HISTORY
Lives with spouse. Independent in ADLs. Tobacco use ongoing per
patient; alcohol occasional; no illicit substances. Risk factor
modification discussed today.


REVIEW OF SYSTEMS
A complete 10-system review was performed and is negative except
as documented in the HPI.


VITAL SIGNS
BP  142/86  (right arm, seated, after 5 min rest)
HR  72  regular
RR  14
SpO2  98%  on room air
T  36.8 C
Wt  84 kg     Ht  175 cm     BMI  27.4


PHYSICAL EXAMINATION
General: Well-appearing, in no acute distress.
HEENT:   Atraumatic, normocephalic. No JVD.
CV:      Regular rate and rhythm. Normal S1 and S2. No S3, S4,
         murmur, rub, or gallop. PMI non-displaced.
Resp:    Clear to auscultation bilaterally. No wheezing or
         crackles.
Abd:     Soft, non-tender, non-distended. No bruits.
Ext:     No peripheral edema. Distal pulses 2+ and symmetric.
Access:  Right radial catheterization site healing well; no
         hematoma, no bruit, no pulse deficit.


DATA REVIEW
ECG today (10/20/2025): NSR rate 70, normal axis, no acute
  ST-T changes. Compared to 09/15/2025, unchanged.
Recent labs (09/15/2025): LDL 88, HDL 42, TG 142, A1c 7.2%,
  Cr 1.05, eGFR 78, K 4.1, Hgb 13.8.
Cardiac catheterization (10/15/2025) — see procedure report:
  two-vessel CAD as detailed in HPI; LVEF 55%.


ASSESSMENT AND PLAN

1. Stable angina pectoris in the setting of two-vessel coronary
   artery disease (chronic coronary disease).
   - No PCI was performed at catheterization given stable
     symptoms, absence of high-risk anatomic features, and an
     ISCHEMIA-aligned medical management strategy.
   - Continue aspirin 81 mg PO daily for secondary prevention.
   - Continue atorvastatin 40 mg PO daily; LDL goal < 70 mg/dL
     for ASCVD secondary prevention. LDL today 88 — discuss
     intensification with PCP if not at goal on repeat.
   - INITIATE metoprolol succinate 25 mg PO once daily as
     anti-anginal therapy and rate control. Titrate to resting
     heart rate of 55 to 60 bpm as tolerated.
   - Sublingual nitroglycerin 0.4 mg PRN for breakthrough
     chest pain; education and instructions provided. Rx sent.
   - Cardiac rehabilitation referral placed.
   - DAPT not indicated; diagnostic catheterization without
     stent placement.

2. Hypertension.
   - BP elevated today at 142/86. Defer titration to PCP for
     routine outpatient management.

3. Type 2 diabetes mellitus.
   - A1c 7.2% — at or near goal. Continue metformin.
   - Defer SGLT2 inhibitor or GLP-1 RA consideration to PCP
     given ASCVD-positive status per current guidelines.

4. Hyperlipidemia.
   - On high-intensity statin. Defer further lipid management
     to PCP.

5. History of minor ischemic stroke (2024).
   - Continue secondary stroke prevention; co-managed with
     neurology.

6. Tobacco use.
   - Counseled on cessation; nicotine replacement options and
     behavioral support discussed. Referral to PCP for
     cessation program.


FOLLOW-UP
Return to cardiology clinic in 3 months for symptom assessment
and tolerability of new anti-anginal therapy. Sooner for any
worsening of symptoms, rest pain, or new associated features.


PATIENT EDUCATION
Reviewed nature of coronary artery disease, rationale for medical
management strategy, expected effects of metoprolol, indications
for sublingual nitroglycerin, and warning signs requiring emergent
evaluation (rest pain, prolonged pain, dyspnea, syncope). Patient
verbalized understanding and stated agreement with the plan.


───────────────────────────────────────────────────────────────

David Park, MD
Bayside Health Cardiology
NPI: 2345678901
Electronically signed: 10/20/2025  11:42 EDT
"""

ED_NOTE = """\
═══════════════════════════════════════════════════════════════
   RIVERSIDE HOSPITAL  |  EMERGENCY DEPARTMENT
   Discharge Summary
═══════════════════════════════════════════════════════════════

Patient:           LEE, JAMES
DOB:               11/15/1958  (67 y, M)
Riverside MRN:     RIV-447821
Home MRN (rep'd):  BAY-0042-LEE  (Bayside Health)
Encounter Date:    12/15/2025
Arrival:           14:20 EST     Mode: walk-in
Discharge:         18:45 EST
Encounter ID:      RIV-ED-9912
ESI Triage Level:  3
Attending:         Tom Brown, MD
═══════════════════════════════════════════════════════════════


CHIEF COMPLAINT
Epigastric abdominal pain x 2 days.


HISTORY OF PRESENT ILLNESS
Mr. James Lee is a 67-year-old male presenting to the Riverside
Hospital ED with a 2-day history of intermittent epigastric
discomfort. The patient is currently traveling and unable to reach
his primary care team at Bayside Health.

He describes the pain as a dull, burning sensation, 4 out of 10 in
intensity, worse after meals, and partially relieved by sitting up.
Associated mild nausea without vomiting. No fevers, chills, melena,
hematochezia, or hematemesis. No chest pain, dyspnea, palpitations,
or diaphoresis at any time. No back or radiating pain. No urinary
or bowel changes. He has continued his home medications.

Of note, the patient reports recent cardiology evaluation for
exertional chest pain with two-vessel CAD on diagnostic
catheterization in October; he was started on a new heart
medication at that time. Given the patient's known coronary disease
and age, atypical anginal-equivalent presentation cannot be
excluded on history alone, and a cardiac workup was initiated.


PAST MEDICAL HISTORY  (per patient and home med list reconciliation)
- Hypertension
- Type 2 diabetes mellitus
- Hyperlipidemia
- Coronary artery disease, two-vessel (per recent cardiology eval)
- Minor ischemic stroke (2024)


PAST SURGICAL HISTORY
Diagnostic cardiac catheterization (10/2025), no PCI.


HOME MEDICATIONS  (per patient report)
- Lisinopril 10 mg PO daily
- Atorvastatin 40 mg PO daily
- Metformin 1000 mg PO BID
- Aspirin 81 mg PO daily
- Metoprolol succinate, dose unclear per patient


ALLERGIES
PENICILLIN — patient reports a rash as a child following an
oral antibiotic course (estimated age 6 to 8). He describes the
reaction as a non-pruritic, non-urticarial rash that resolved
without intervention. NO history of facial swelling, lip or tongue
swelling, throat tightness, breathing difficulty, hypotension, or
anaphylaxis. He has avoided penicillin and amoxicillin since.
No other known drug, food, or environmental allergies.


SOCIAL HISTORY
Married, traveling for family event. Tobacco use ongoing per
patient. Alcohol occasional. No illicit substances.


REVIEW OF SYSTEMS
Constitutional: No fever, no weight loss.
Cardiac:        No chest pain, dyspnea, palpitations.
Resp:           No cough, no shortness of breath.
GI:             As per HPI. No diarrhea, constipation, or
                bloody stool.
GU:             No dysuria, hematuria, or flank pain.
Neuro:          No headache, weakness, or focal symptoms.
All other systems negative.


VITAL SIGNS  (on arrival)
BP    138/82
HR    76, regular
RR    16
SpO2  98%  on room air
T     37.0 C
Pain  4/10  epigastric


PHYSICAL EXAMINATION
General:  Well-appearing, in no acute distress.
HEENT:    Atraumatic. Mucous membranes moist.
CV:       Regular rate and rhythm. No murmurs, rubs, or gallops.
          No JVD.
Resp:     Clear to auscultation bilaterally.
Abd:      Soft, non-distended. Mild epigastric tenderness to
          deep palpation without guarding, rebound, or rigidity.
          Murphy sign negative. No CVA tenderness. No palpable
          mass or hepatosplenomegaly. Bowel sounds present and
          normal.
Ext:      No edema. Distal pulses 2+ bilaterally.
Skin:     Warm and dry. No rash.
Neuro:    Alert and oriented x3. No focal deficits.


ED COURSE AND INVESTIGATIONS
Given known CAD and atypical presentation in a 67-year-old male,
cardiac etiology was investigated alongside primary GI workup.

ECG (14:35):           NSR at 74. No acute ST or T-wave changes.
                       No new findings compared with patient-reported
                       outpatient ECG.
Troponin I (15:05):    < 0.012 ng/mL  (negative)
Troponin I (17:30):    < 0.012 ng/mL  (negative; serial)
CBC:                   WBC 7.4, Hgb 13.6, Plt 232  (within normal limits)
CMP:                   Na 139, K 4.0, Cl 102, CO2 25, BUN 18,
                       Cr 1.04, glucose 142, AST 24, ALT 22,
                       Alk Phos 78, T.bili 0.7
Lipase:                34 U/L  (normal)
Urinalysis:            Unremarkable
CT abdomen/pelvis with IV contrast (15:20): No acute intra-abdominal
                       process. No free air, free fluid, bowel
                       obstruction, appendicitis, or pancreatic
                       inflammation. Hepatobiliary system without
                       cholelithiasis or ductal dilation. Incidental
                       small simple renal cyst, left.

Patient was monitored on telemetry throughout the ED course.
Symptoms improved spontaneously during observation. He tolerated
oral intake without recurrence of pain.


ASSESSMENT
1. Epigastric abdominal pain, presumed gastritis or non-ulcer
   dyspepsia. Reassuring history, exam, and imaging.
2. Acute coronary syndrome ruled out: two negative serial
   troponins, non-ischemic ECG, atypical features for ACS.
3. Penicillin allergy, low-severity historical label —
   recommend outpatient evaluation for possible delabeling.


DISPOSITION
Discharged home in stable condition, ambulatory, tolerating
oral intake. Patient verbalized understanding of diagnosis,
follow-up plan, and return precautions.


DISCHARGE MEDICATIONS
- Continue all home medications as previously prescribed.
- New: omeprazole 20 mg PO once daily for 14 days
       (available over-the-counter).
- Antacid PRN for breakthrough symptoms.


RETURN PRECAUTIONS
Return to the ED immediately for:
- Chest pain, pressure, or tightness
- Shortness of breath at rest
- Severe or worsening abdominal pain
- Vomiting blood or coffee-ground emesis
- Black, tarry, or bloody stools
- Fever above 38.5 C
- Lightheadedness, syncope, or sudden weakness


FOLLOW-UP
Primary care provider (Anna Kim, MD, Bayside Health) within
1 to 2 weeks for symptom reassessment and routine care.
Continue established cardiology follow-up at Bayside.


ICD-10  (final):  K29.70  Gastritis, unspecified, without bleeding
                  R10.13  Epigastric pain
                  Z87.891 Personal history of nicotine dependence


───────────────────────────────────────────────────────────────

Tom Brown, MD
Riverside Hospital, Department of Emergency Medicine
NPI: 3456789012
Electronically signed: 12/15/2025  18:52 EST
"""

NEURO_NOTE = """\
═══════════════════════════════════════════════════════════════
   BAYSIDE HEALTH  |  DEPARTMENT OF NEUROLOGY
   Outpatient Follow-up Note
═══════════════════════════════════════════════════════════════

Patient:           LEE, JAMES
MRN:               BAY-0042-LEE
DOB:               11/15/1958  (67 y, M)
Encounter Date:    02/23/2026  10:00 EST
Encounter ID:      ENC-NEURO-FOLLOWUP
Visit Type:        Outpatient Follow-up, Established Patient
Service:           Neurology — Stroke Clinic
Attending:         Lisa Chen, MD
PCP:               Anna Kim, MD  (Bayside Family Medicine)
═══════════════════════════════════════════════════════════════


REASON FOR VISIT
Routine 6-month follow-up for chronic post-stroke fatigue,
status-post minor ischemic stroke (2024). Last seen in clinic
08/19/2025.


INTERVAL HISTORY
Mr. James Lee returns for routine neurology follow-up. He continues
to experience mild-to-moderate daytime fatigue, most prominent in
the early afternoon, partially controlled with structured pacing
and afternoon rest. He estimates his fatigue is moderately improved
since his last visit, which he attributes to consistent participation
in outpatient occupational therapy (twice weekly x 4 months,
ongoing).

He denies recurrent transient or persistent focal neurological
symptoms: no new weakness, sensory changes, vision changes, speech
disturbance, gait disturbance, or seizure-like activity. No new
headaches. No cognitive complaints; the patient and his spouse both
report no new memory or executive concerns.

Sleep is adequate at 7 to 8 hours nightly with morning refreshment.
Mood is stable; no depressive symptoms. PHQ-2 today: 0.

Of note, the patient reports significant interval changes:

  - Tobacco cessation: He successfully quit smoking approximately
    3 months ago (early November 2025) and remains tobacco-free.
    He has an estimated 30 pack-year history (approximately 1
    pack per day x 30 years prior to cessation). He is using no
    nicotine replacement at this time.

  - Cardiology care: He was evaluated by cardiology in October
    2025 for exertional chest pain and underwent diagnostic
    cardiac catheterization. He reports being started on a new
    "heart medication" at that time but is uncertain of the
    name (per chart: metoprolol succinate 25 mg daily).

  - Family history: On detailed re-interview today, the patient
    reports that his father suffered a myocardial infarction at
    age 52 and survived; his father subsequently died of an
    unrelated cause at age 71. No prior strokes in immediate
    family. Mother and one sister are alive without known
    cardiovascular or neurological disease.


PAST MEDICAL HISTORY
- Minor ischemic stroke (2024); presumed small-vessel etiology
  per prior evaluation
- Chronic post-stroke fatigue
- Hypertension
- Type 2 diabetes mellitus
- Hyperlipidemia
- Coronary artery disease, two-vessel (cardiology, 10/2025)


HOME MEDICATIONS  (reviewed and reconciled)
- Lisinopril 10 mg PO daily
- Atorvastatin 40 mg PO daily
- Metformin 1000 mg PO BID
- Aspirin 81 mg PO daily
- Metoprolol succinate 25 mg PO daily  (new since last visit)


ALLERGIES
Penicillin — childhood rash, low-severity per ED documentation
12/2025. No other known drug allergies.


SOCIAL HISTORY
Lives with spouse. Independent in ADLs and IADLs. Tobacco: former
smoker, quit ~3 months ago, 30 pack-year history. Alcohol: rare,
< 1 drink per week. No illicit substances. Drives without
restriction.


FAMILY HISTORY
- Father: myocardial infarction at age 52 (survived); deceased
  age 71 of unrelated cause.
- Mother: alive, no known cardiovascular or neurological disease.
- Sister: alive, no known significant medical history.
- No family history of stroke, dementia, or seizure disorder.


REVIEW OF SYSTEMS
Neurological: As per HPI; no new focal symptoms, no headache, no
              cognitive complaints, no seizure activity.
Constitutional: Fatigue as documented; otherwise well.
All other systems: negative on 10-system review.


VITAL SIGNS
BP    168/95   (right arm, seated, after 5 min rest)
      164/93   (repeat, left arm)
HR    78, regular
RR    14
SpO2  98%  on room air
T     36.7 C
Wt    84 kg     Ht  175 cm     BMI  27.4


PHYSICAL EXAMINATION
General:        Well-appearing, in no acute distress.
Mental Status:  Alert, oriented x3. Fluent speech without aphasia
                or dysarthria. MoCA score 27/30 (stable from prior;
                lost points on delayed recall and serial subtraction).
Cranial Nerves: II-XII intact. Visual fields full to confrontation.
                EOMs intact without nystagmus. Facial sensation
                and strength symmetric. Tongue midline.
Motor:          5/5 strength throughout, bilaterally symmetric. No
                pronator drift. No tremor or asterixis.
Sensory:        Intact to light touch, pinprick, vibration, and
                proprioception in all four extremities.
Reflexes:       2+ and symmetric at biceps, triceps, patellae,
                Achilles. Plantar responses downgoing bilaterally.
Coordination:   Finger-to-nose and heel-to-shin intact.
                Rapid alternating movements normal.
Gait:           Normal-based, steady. Tandem gait intact.
                Romberg negative.


DATA REVIEW
Most recent brain MRI (06/2024, post-stroke): Small chronic
  lacunar infarct in the right corona radiata. No acute findings.
  No microbleeds. Mild chronic small-vessel ischemic changes.
Most recent labs (Bayside, 09/2025): A1c 7.2%, LDL 88, Cr 1.05,
  eGFR 78, K 4.1.
ECG (cardiology, 10/2025): NSR with non-specific lateral T-wave
  flattening; no acute changes.


ASSESSMENT AND PLAN

1. Chronic post-stroke fatigue — partially controlled, moderately
   improved on current management.
   - Continue outpatient occupational therapy program; reassess
     functional status at 6 months.
   - Reinforce sleep hygiene and structured activity pacing.
   - No medication change for fatigue at this time.

2. Hypertension — uncontrolled in clinic today (168/95, confirmed
   with repeat measurement 164/93). Above goal of < 130/80 for
   secondary stroke prevention.
   - Increase lisinopril from 10 mg to 20 mg PO once daily, in
     coordination with PCP for ongoing titration.
   - Recommend home BP monitoring with log review at PCP
     follow-up.
   - PCP follow-up within 4 weeks for BP recheck and further
     titration if needed; second-line agent (calcium channel
     blocker or thiazide) should be considered if not at goal.

3. Tobacco cessation — sustained 3 months, 30 pack-year history.
   - Reviewed health benefits of continued cessation. Positive
     reinforcement provided. Encouraged ongoing avoidance and
     offered referral to behavioral cessation support if any
     return of cravings.

4. Family history of premature coronary artery disease —
   father with MI at age 52.
   - Significant for risk stratification. Coordinate with
     cardiology and PCP for any implications regarding lipid
     targets and primary prevention of additional events.

5. Secondary stroke prevention.
   - Continue aspirin 81 mg daily and high-intensity statin
     (atorvastatin 40 mg daily).
   - BP control as above.
   - A1c remains near goal at 7.2%; defer diabetes
     intensification to PCP per current ADA guidance for
     ASCVD-positive patients.

6. Coronary artery disease — co-managed with cardiology.
   - Continue metoprolol succinate as prescribed by cardiology.
   - No neurology-specific changes.


FOLLOW-UP
Return to neurology in 6 months for routine post-stroke surveillance.
Sooner for any new neurological symptoms, recurrent stroke-like
events, or worsening of fatigue. Patient is aware of stroke warning
signs (FAST) and was reminded to call 911 for any acute focal
deficit.


PATIENT EDUCATION
Reviewed BP goal of < 130/80 for secondary stroke prevention,
rationale for lisinopril dose increase, importance of medication
adherence and home BP monitoring, and continued tobacco abstinence.
Discussed family history of premature CAD and its relevance to
ongoing cardiovascular risk management. Patient verbalized
understanding and agreement with the plan. Spouse present and
engaged throughout.


───────────────────────────────────────────────────────────────

Lisa Chen, MD
Bayside Health Neurology — Stroke Clinic
NPI: 4567890123
Electronically signed: 02/23/2026  10:51 EST
"""

def b64(text):
    return b64encode(text.encode("utf-8")).decode("ascii")

def make_doc(_id, doc_type_code, doc_type_display, note_text, date_str,
             author_ref, author_name, encounter_ref, custodian_ref, custodian_name):
    return DocumentReference(
        id=_id,
        meta={"profile": profile("us-core-documentreference")},
        text=narrative(f"<p>{doc_type_display}, {date_str[:10]}</p>"),
        identifier=[Identifier(
            system="http://bayside.health/document-id",
            value=f"DOC-{_id.upper()}",
        )],
        status="current",
        docStatus="final",
        type=cc(LOINC, doc_type_code, doc_type_display),
        category=[cc(US_CORE_DOC_CAT, "clinical-note", "Clinical Note")],
        subject=ref(PATIENT, "James Lee"),
        date=date_str,
        author=[ref(author_ref, author_name)],
        custodian=ref(custodian_ref, custodian_name),
        content=[DocumentReferenceContent(
            attachment=Attachment(
                contentType="text/plain; charset=utf-8",
                language="en-US",
                data=b64(note_text),
                title=doc_type_display,
            ),
            format=Coding(
                system="http://ihe.net/fhir/ValueSet/IHE.FormatCode.codesystem",
                code="urn:ihe:iti:xds:2017:mimeTypeSufficient",
                display="mimeType Sufficient",
            ),
        )],
        context=DocumentReferenceContext(
            encounter=[ref(encounter_ref)],
            period=Period(start=date_str, end=date_str),
        ),
    )

doc_cardio = make_doc(
    "cardio-consult-note",
    "11488-4", "Consult note",
    CARDIO_NOTE,
    "2025-10-20T11:00:00-04:00",
    PRAC_PARK, "Dr. David Park",
    ENC_CARDIO,
    ORG_BAYSIDE, "Bayside Health",
)

doc_ed = make_doc(
    "ed-discharge-summary",
    "18842-5", "Discharge summary",
    ED_NOTE,
    "2025-12-15T18:45:00-05:00",
    PRAC_BROWN, "Dr. Tom Brown",
    ENC_ED,
    ORG_RIVERSIDE, "Riverside Hospital",
)

doc_neuro = make_doc(
    "neuro-followup-note",
    "11488-4", "Consult note",
    NEURO_NOTE,
    "2026-02-23T10:45:00-05:00",
    PRAC_CHEN, "Dr. Lisa Chen",
    ENC_NEURO,
    ORG_BAYSIDE, "Bayside Health",
)

# ---------------------------------------------------------------------------
# Bundle assembly (transaction)
# ---------------------------------------------------------------------------
def entry(full_url, resource, resource_type):
    return BundleEntry(
        fullUrl=full_url,
        resource=resource,
        request=BundleEntryRequest(method="POST", url=resource_type),
    )

bundle = Bundle(
    id="anamnesis-demo-james-lee",
    type="transaction",
    timestamp="2026-04-27T08:30:00-04:00",
    entry=[
        # Organizations first (referenced by everyone)
        entry(ORG_BAYSIDE,   bayside,         "Organization"),
        entry(ORG_RIVERSIDE, riverside,       "Organization"),
        # Practitioners
        entry(PRAC_KIM,      prac_kim,        "Practitioner"),
        entry(PRAC_PARK,     prac_park,       "Practitioner"),
        entry(PRAC_BROWN,    prac_brown,      "Practitioner"),
        entry(PRAC_CHEN,     prac_chen,       "Practitioner"),
        # Patient
        entry(PATIENT,       patient,         "Patient"),
        # Conditions
        entry(COND_HTN,      cond_htn,        "Condition"),
        entry(COND_T2DM,     cond_t2dm,       "Condition"),
        entry(COND_HLD,      cond_hld,        "Condition"),
        entry(COND_FATIGUE,  cond_fatigue,    "Condition"),
        # Medications
        entry(MED_LISINOPRIL, med_lisinopril, "MedicationRequest"),
        entry(MED_ATORVA,     med_atorvastatin, "MedicationRequest"),
        entry(MED_METFORMIN,  med_metformin,  "MedicationRequest"),
        entry(MED_ASPIRIN,    med_aspirin,    "MedicationRequest"),
        # Encounters (3 specialty)
        entry(ENC_CARDIO,    enc_cardio,      "Encounter"),
        entry(ENC_ED,        enc_ed,          "Encounter"),
        entry(ENC_NEURO,     enc_neuro,       "Encounter"),
        # DocumentReferences (with note text inline)
        entry(DOC_CARDIO,    doc_cardio,      "DocumentReference"),
        entry(DOC_ED,        doc_ed,          "DocumentReference"),
        entry(DOC_NEURO,     doc_neuro,       "DocumentReference"),
    ],
)

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
out_path = "/home/claude/anamnesis-demo-bundle.json"
with open(out_path, "w") as f:
    f.write(bundle.model_dump_json(indent=2, exclude_none=True))

print(f"Bundle written to: {out_path}")
print(f"Entry count: {len(bundle.entry)}")
print(f"Resource counts:")
from collections import Counter
counts = Counter(e.resource.__class__.__name__ for e in bundle.entry)
for k, v in sorted(counts.items()):
    print(f"  {k}: {v}")
