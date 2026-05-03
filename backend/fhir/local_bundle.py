"""Load PatientContext + Documents from a FHIR bundle JSON without a server.

Produces identical types to fhir/read.py so downstream stages are unaware
of the data source. Used for offline development and e2e testing.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

from fhir.models import Document, PatientContext

BUNDLE_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "data"
    / "demo_patient"
    / "anamnesis-demo-bundle.json"
)

_PATIENT_LINKED_TYPES = {
    "Condition": "conditions",
    "MedicationRequest": "medications",
    "AllergyIntolerance": "allergies",
    "Observation": "observations",
    "FamilyMemberHistory": "family_history",
    "Procedure": "procedures",
    "Encounter": "encounters",
    "Practitioner": "practitioners",
    "Organization": "organizations",
    "DocumentReference": "documents",
    "Provenance": "provenances",
}


def load_bundle(path: Path = BUNDLE_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def patient_context_from_bundle(bundle: dict) -> PatientContext:
    patient: dict | None = None
    lists: dict[str, list[dict]] = {field: [] for field in _PATIENT_LINKED_TYPES.values()}

    for entry in bundle.get("entry", []):
        res = entry.get("resource", {})
        rtype = res.get("resourceType")
        if rtype == "Patient":
            patient = res
        elif rtype in _PATIENT_LINKED_TYPES:
            lists[_PATIENT_LINKED_TYPES[rtype]].append(res)

    if not patient:
        raise ValueError("No Patient resource in bundle")

    return PatientContext(patient=patient, **lists)


def documents_from_bundle(bundle: dict) -> list[Document]:
    docs: list[Document] = []
    for entry in bundle.get("entry", []):
        res = entry.get("resource", {})
        if res.get("resourceType") != "DocumentReference":
            continue

        contents = res.get("content") or []
        attachment = contents[0].get("attachment", {}) if contents else {}
        data = attachment.get("data")
        text = ""
        if data:
            try:
                text = base64.b64decode(data).decode("utf-8", errors="replace")
            except Exception:
                pass

        type_field = res.get("type", {}) or {}
        coding = (type_field.get("coding") or [{}])[0]
        type_label = coding.get("display") or type_field.get("text") or ""

        authors = res.get("author") or []
        author = authors[0].get("display", "") if authors else ""

        ctx = res.get("context") or {}
        enc_refs = ctx.get("encounter") or []
        enc_ref = enc_refs[0].get("reference", "") if enc_refs else ""
        enc_id = enc_ref if enc_ref else None

        docs.append(Document(
            id=res.get("id", ""),
            type=type_label,
            date=res.get("date", ""),
            author=author,
            text=text,
            encounter_id=enc_id or None,
        ))
    return docs


def load_demo_data(path: Path = BUNDLE_PATH) -> tuple[PatientContext, list[Document]]:
    bundle = load_bundle(path)
    return patient_context_from_bundle(bundle), documents_from_bundle(bundle)
