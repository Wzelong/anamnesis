"""
Build the Anamnesis mCODE oncology demo FHIR Bundle.

Patient: Margaret Sullivan, 58yo female, established at Oakwood Cancer Center.
Three documents from her breast-cancer course:
  - Medical oncology consultation (staging + biomarkers, 09/2025)
  - Surgical pathology report (post-neoadjuvant resection, 12/2025)
  - Oncology follow-up (progression to bone metastasis, 02/2027)

The bundle is the EXISTING structured record (deliberately under-coded: the
breast cancer is a bare ICD-10 problem-list entry, no mCODE structure) plus the
DocumentReferences. The mCODE augmentations are what the engine PRODUCES.

FHIR R4 transaction bundle, US Core 6.1.0 profiles. Notes are read from the
sibling note-*.md files (single source of truth).
"""
import json
import uuid
from base64 import b64encode
from pathlib import Path

HERE = Path(__file__).resolve().parent
NS = uuid.UUID("00000000-0000-0000-0000-000000000002")  # distinct from James Lee


def U(name):
    return f"urn:uuid:{uuid.uuid5(NS, name)}"


# Code systems
SCT = "http://snomed.info/sct"
LOINC = "http://loinc.org"
ICD10 = "http://hl7.org/fhir/sid/icd-10-cm"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
HL7_CC = "http://terminology.hl7.org/CodeSystem/condition-clinical"
HL7_CV = "http://terminology.hl7.org/CodeSystem/condition-ver-status"
HL7_CCAT = "http://terminology.hl7.org/CodeSystem/condition-category"
HL7_OBSCAT = "http://terminology.hl7.org/CodeSystem/observation-category"
HL7_MR = "http://terminology.hl7.org/CodeSystem/v2-0203"
HL7_ACT = "http://terminology.hl7.org/CodeSystem/v3-ActCode"
US_DOC_CAT = "http://hl7.org/fhir/us/core/CodeSystem/us-core-documentreference-category"
CDCREC = "urn:oid:2.16.840.1.113883.6.238"
USCORE = "http://hl7.org/fhir/us/core/StructureDefinition"
IHE_FMT = "http://ihe.net/fhir/ValueSet/IHE.FormatCode.codesystem"


def prof(name):
    return [f"{USCORE}/{name}"]


def cc(system, code, display, text=None):
    return {"coding": [{"system": system, "code": code, "display": display}], "text": text or display}


def cc_multi(codings, text):
    return {"coding": codings, "text": text}


def ref(urn, display=None):
    r = {"reference": urn}
    if display:
        r["display"] = display
    return r


def b64(text):
    return b64encode(text.encode("utf-8")).decode("ascii")


# UUIDs
ORG_OAKWOOD = U("org.oakwood")
ORG_LAKESHORE = U("org.lakeshore")
PRAC_RAO = U("prac.rao")
PRAC_VOSS = U("prac.voss")
PRAC_LIU = U("prac.liu")
PATIENT = U("patient.sullivan")
COND_BREAST = U("cond.breast")
COND_HTN = U("cond.htn")
COND_OSTEOPENIA = U("cond.osteopenia")
MED_LISINOPRIL = U("med.lisinopril")
MED_CALVITD = U("med.calvitd")
OBS_MAMMO = U("obs.mammo")
PROC_BIOPSY = U("proc.biopsy")
ENC_CONSULT = U("enc.consult")
ENC_SURGERY = U("enc.surgery")
ENC_FOLLOWUP = U("enc.followup")
DOC_CONSULT = U("doc.consult")
DOC_PATH = U("doc.path")
DOC_FOLLOWUP = U("doc.followup")

PT_NAME = "Margaret Sullivan"


# Organizations
def org(_id, name, line, city, state, zip_, phone, sysid):
    return {
        "resourceType": "Organization", "id": _id, "meta": {"profile": prof("us-core-organization")},
        "identifier": [{"system": sysid, "value": _id.upper()}], "active": True, "name": name,
        "type": [cc("http://terminology.hl7.org/CodeSystem/organization-type", "prov", "Healthcare Provider")],
        "telecom": [{"system": "phone", "value": phone, "use": "work"}],
        "address": [{"line": [line], "city": city, "state": state, "postalCode": zip_, "country": "US"}],
    }


oakwood = org("oakwood", "Oakwood Cancer Center", "240 Oakwood Parkway", "Chicago", "IL", "60601",
              "+1-312-555-0170", "http://oakwoodcancer.example.org/org-id")
lakeshore = org("lakeshore", "Lakeshore Imaging", "88 Lakeshore Blvd", "Chicago", "IL", "60611",
                "+1-312-555-0190", "http://lakeshoreimaging.example.org/org-id")


# Practitioners
def practitioner(_id, npi, family, given, prefix="Dr."):
    return {
        "resourceType": "Practitioner", "id": _id, "meta": {"profile": prof("us-core-practitioner")},
        "identifier": [{"system": "http://hl7.org/fhir/sid/us-npi", "value": npi}], "active": True,
        "name": [{"use": "official", "family": family, "given": [given], "prefix": [prefix]}],
    }


prac_rao = practitioner("rao", "5234567890", "Rao", "Priya")
prac_voss = practitioner("voss", "6345678901", "Voss", "Ellen")
prac_liu = practitioner("liu", "7456789012", "Liu", "Mark")


# Patient
patient = {
    "resourceType": "Patient", "id": "sullivan-margaret", "meta": {"profile": prof("us-core-patient")},
    "extension": [
        {"url": f"{USCORE}/us-core-race", "extension": [
            {"url": "ombCategory", "valueCoding": {"system": CDCREC, "code": "2106-3", "display": "White"}},
            {"url": "text", "valueString": "White"}]},
        {"url": f"{USCORE}/us-core-ethnicity", "extension": [
            {"url": "ombCategory", "valueCoding": {"system": CDCREC, "code": "2186-5", "display": "Not Hispanic or Latino"}},
            {"url": "text", "valueString": "Not Hispanic or Latino"}]},
        {"url": f"{USCORE}/us-core-birthsex", "valueCode": "F"},
    ],
    "identifier": [{"use": "usual", "type": cc(HL7_MR, "MR", "Medical Record Number"),
                    "system": "http://oakwoodcancer.example.org/mrn", "value": "OAK-0117-SUL"}],
    "active": True, "name": [{"use": "official", "family": "Sullivan", "given": ["Margaret"]}],
    "telecom": [{"system": "phone", "value": "+1-312-555-0117", "use": "home"}],
    "gender": "female", "birthDate": "1966-09-12",
    "address": [{"use": "home", "line": ["55 Linden Court"], "city": "Chicago", "state": "IL",
                 "postalCode": "60614", "country": "US"}],
    "managingOrganization": ref(ORG_OAKWOOD, "Oakwood Cancer Center"),
}


# Conditions
def problem(_id, codings, text, onset, recorded, recorder=PRAC_RAO, recorder_name="Dr. Priya Rao"):
    return {
        "resourceType": "Condition", "id": _id,
        "meta": {"profile": prof("us-core-condition-problems-health-concerns")},
        "clinicalStatus": cc(HL7_CC, "active", "Active"),
        "verificationStatus": cc(HL7_CV, "confirmed", "Confirmed"),
        "category": [cc(HL7_CCAT, "problem-list-item", "Problem List Item")],
        "code": cc_multi(codings, text), "subject": ref(PATIENT, PT_NAME),
        "onsetDateTime": onset, "recordedDate": recorded,
        "recorder": ref(recorder, recorder_name), "asserter": ref(recorder, recorder_name),
    }


# Deliberately under-coded baseline: ICD-10 only, generic name, NO body site, NO mCODE.
cond_breast = problem("breast-ca",
                      [{"system": ICD10, "code": "C50.911", "display": "Malignant neoplasm of unspecified site of right female breast"}],
                      "Malignant neoplasm of right breast", "2025-09-04", "2025-09-08")
cond_htn = problem("htn",
                   [{"system": SCT, "code": "59621000", "display": "Essential hypertension"},
                    {"system": ICD10, "code": "I10", "display": "Essential (primary) hypertension"}],
                   "Essential hypertension", "2014-06-01", "2014-06-01")
cond_osteopenia = problem("osteopenia",
                          [{"system": SCT, "code": "312894000", "display": "Osteopenia"},
                           {"system": ICD10, "code": "M85.80", "display": "Other specified disorders of bone density and structure, unspecified site"}],
                          "Osteopenia", "2022-03-01", "2022-03-01")


# Medications
def med(_id, code, display, dose_text, authored):
    return {
        "resourceType": "MedicationRequest", "id": _id, "meta": {"profile": prof("us-core-medicationrequest")},
        "status": "active", "intent": "order", "reportedBoolean": False,
        "medicationCodeableConcept": cc(RXNORM, code, display), "subject": ref(PATIENT, PT_NAME),
        "authoredOn": authored, "requester": ref(PRAC_RAO, "Dr. Priya Rao"),
        "dosageInstruction": [{"text": dose_text, "route": cc(SCT, "26643006", "Oral route")}],
    }


med_lisinopril = med("lisinopril-10", "314076", "Lisinopril 10 MG Oral Tablet",
                     "Take 1 tablet (10 mg) by mouth once daily", "2024-01-15")
med_calvitd = med("cal-vitd", "1303736", "Calcium Carbonate 600 MG / Cholecalciferol 400 unit Oral Tablet",
                  "Take 1 tablet by mouth twice daily", "2022-03-01")


# Baseline Observation: screening/diagnostic mammography BI-RADS 5
obs_mammo = {
    "resourceType": "Observation", "id": "mammo-birads",
    "meta": {"profile": prof("us-core-observation-clinical-result")},
    "status": "final",
    "category": [cc(HL7_OBSCAT, "imaging", "Imaging")],
    "code": cc(LOINC, "42168-6", "Breast - Mammogram diagnostic"),
    "subject": ref(PATIENT, PT_NAME), "effectiveDateTime": "2025-08-28",
    "performer": [ref(PRAC_LIU, "Dr. Mark Liu")],
    "valueCodeableConcept": cc(LOINC, "LA25911-2", "BI-RADS 5: Highly suggestive of malignancy"),
}

# Baseline Procedure: diagnostic core needle biopsy
proc_biopsy = {
    "resourceType": "Procedure", "id": "core-biopsy", "meta": {"profile": prof("us-core-procedure")},
    "status": "completed", "code": cc(SCT, "122548005", "Biopsy of breast"),
    "subject": ref(PATIENT, PT_NAME), "performedDateTime": "2025-09-04",
    "bodySite": [cc(SCT, "73056007", "Right breast structure")],
}


# Encounters
def encounter(_id, class_code, class_disp, type_codings, type_text, start, end, prac, prac_name, sp):
    return {
        "resourceType": "Encounter", "id": _id, "meta": {"profile": prof("us-core-encounter")},
        "identifier": [{"system": "http://oakwoodcancer.example.org/encounter-id", "value": f"ENC-{_id.upper()}"}],
        "status": "finished", "class": {"system": HL7_ACT, "code": class_code, "display": class_disp},
        "type": [cc_multi(type_codings, type_text)], "subject": ref(PATIENT, PT_NAME),
        "participant": [{"individual": ref(prac, prac_name), "period": {"start": start, "end": end}}],
        "period": {"start": start, "end": end}, "serviceProvider": ref(sp),
    }


enc_consult = encounter("onc-consult", "AMB", "ambulatory",
                        [{"system": SCT, "code": "11429006", "display": "Consultation"},
                         {"system": LOINC, "code": "11488-4", "display": "Consult note"}],
                        "Medical Oncology Consultation", "2025-09-18T09:00:00-05:00", "2025-09-18T10:04:00-05:00",
                        PRAC_RAO, "Dr. Priya Rao", ORG_OAKWOOD)
enc_surgery = encounter("onc-surgery", "AMB", "ambulatory",
                        [{"system": SCT, "code": "274441001", "display": "Breast surgery"},
                         {"system": LOINC, "code": "11526-1", "display": "Pathology study"}],
                        "Breast Surgery and Pathology", "2025-12-03T07:30:00-06:00", "2025-12-03T11:00:00-06:00",
                        PRAC_VOSS, "Dr. Ellen Voss", ORG_OAKWOOD)
enc_followup = encounter("onc-followup", "AMB", "ambulatory",
                         [{"system": SCT, "code": "185349003", "display": "Encounter for check up"},
                          {"system": LOINC, "code": "11488-4", "display": "Consult note"}],
                         "Medical Oncology Follow-up", "2027-02-10T10:30:00-06:00", "2027-02-10T11:18:00-06:00",
                         PRAC_RAO, "Dr. Priya Rao", ORG_OAKWOOD)


# DocumentReferences (notes read from .md files)
def doc(_id, loinc_code, loinc_disp, note_file, date_str, author, author_name, enc, custodian, custodian_name):
    text = (HERE / note_file).read_text(encoding="utf-8")
    return {
        "resourceType": "DocumentReference", "id": _id, "meta": {"profile": prof("us-core-documentreference")},
        "identifier": [{"system": "http://oakwoodcancer.example.org/document-id", "value": f"DOC-{_id.upper()}"}],
        "status": "current", "docStatus": "final", "type": cc(LOINC, loinc_code, loinc_disp),
        "category": [cc(US_DOC_CAT, "clinical-note", "Clinical Note")], "subject": ref(PATIENT, PT_NAME),
        "date": date_str, "author": [ref(author, author_name)], "custodian": ref(custodian, custodian_name),
        "content": [{"attachment": {"contentType": "text/plain; charset=utf-8", "language": "en-US",
                                     "data": b64(text), "title": loinc_disp},
                     "format": {"system": IHE_FMT, "code": "urn:ihe:iti:xds:2017:mimeTypeSufficient",
                                "display": "mimeType Sufficient"}}],
        "context": {"encounter": [ref(enc)], "period": {"start": date_str, "end": date_str}},
    }


doc_consult = doc("onc-consult-note", "11488-4", "Consult note", "note-1-oncology-consultation.md",
                  "2025-09-18T10:04:00-05:00", PRAC_RAO, "Dr. Priya Rao", ENC_CONSULT, ORG_OAKWOOD, "Oakwood Cancer Center")
doc_path = doc("surgical-pathology-report", "11526-1", "Pathology study", "note-2-surgical-pathology.md",
               "2025-12-05T09:00:00-06:00", PRAC_VOSS, "Dr. Ellen Voss", ENC_SURGERY, ORG_OAKWOOD, "Oakwood Cancer Center")
doc_followup = doc("onc-followup-note", "11488-4", "Consult note", "note-3-oncology-followup.md",
                   "2027-02-10T11:18:00-06:00", PRAC_RAO, "Dr. Priya Rao", ENC_FOLLOWUP, ORG_OAKWOOD, "Oakwood Cancer Center")


def entry(urn, resource):
    return {"fullUrl": urn, "resource": resource,
            "request": {"method": "POST", "url": resource["resourceType"]}}


bundle = {
    "resourceType": "Bundle", "id": "anamnesis-demo-oncology-sullivan", "type": "transaction",
    "timestamp": "2027-03-01T08:30:00-06:00",
    "entry": [
        entry(ORG_OAKWOOD, oakwood), entry(ORG_LAKESHORE, lakeshore),
        entry(PRAC_RAO, prac_rao), entry(PRAC_VOSS, prac_voss), entry(PRAC_LIU, prac_liu),
        entry(PATIENT, patient),
        entry(COND_BREAST, cond_breast), entry(COND_HTN, cond_htn), entry(COND_OSTEOPENIA, cond_osteopenia),
        entry(MED_LISINOPRIL, med_lisinopril), entry(MED_CALVITD, med_calvitd),
        entry(OBS_MAMMO, obs_mammo), entry(PROC_BIOPSY, proc_biopsy),
        entry(ENC_CONSULT, enc_consult), entry(ENC_SURGERY, enc_surgery), entry(ENC_FOLLOWUP, enc_followup),
        entry(DOC_CONSULT, doc_consult), entry(DOC_PATH, doc_path), entry(DOC_FOLLOWUP, doc_followup),
    ],
}

if __name__ == "__main__":
    out = HERE / "oncology-demo-bundle.json"
    out.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    from collections import Counter
    counts = Counter(e["resource"]["resourceType"] for e in bundle["entry"])
    print(f"Wrote {out}")
    print(f"Entries: {len(bundle['entry'])}")
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v}")
