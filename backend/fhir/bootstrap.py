"""Load the James Lee demo bundle into the FHIR server (idempotent)."""
import json
from pathlib import Path

from fhir.client import FhirClient

BUNDLE_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "data"
    / "demo_patient"
    / "anamnesis-demo-bundle.json"
)

MRN_SYSTEM = "http://bayside.health/mrn"
MRN_VALUE = "BAY-0042-LEE"

PATIENT_LINKED_TYPES = [
    "Condition",
    "MedicationRequest",
    "AllergyIntolerance",
    "Observation",
    "Procedure",
    "FamilyMemberHistory",
    "Encounter",
    "DocumentReference",
]


def _ids(bundle: dict | None) -> list[str]:
    if not bundle:
        return []
    return [e["resource"]["id"] for e in bundle.get("entry", []) if e.get("resource", {}).get("id")]


async def _cascade_delete(client: FhirClient, patient_id: str) -> int:
    deleted = 0
    for rtype in PATIENT_LINKED_TYPES:
        found = await client.search(rtype, {"patient": patient_id})
        for rid in _ids(found):
            await client.delete(f"{rtype}/{rid}")
            deleted += 1

    try:
        provs = await client.search("Provenance", {"target": f"Patient/{patient_id}"})
        for rid in _ids(provs):
            await client.delete(f"Provenance/{rid}")
            deleted += 1
    except Exception:
        pass

    await client.delete(f"Patient/{patient_id}")
    deleted += 1
    return deleted


def _extract_patient_id(response_bundle: dict) -> str:
    import json as _json
    import re

    entries = response_bundle.get("entry", [])
    for entry in entries:
        resp = entry.get("response", {}) or {}
        location = resp.get("location") or ""
        match = re.search(r"(?:^|/)Patient/([^/?#]+)", location)
        if match:
            return match.group(1)

        resource = entry.get("resource") or {}
        if resource.get("resourceType") == "Patient" and resource.get("id"):
            return resource["id"]

    raise RuntimeError(
        "transaction response did not include a Patient location.\n"
        f"Full response:\n{_json.dumps(response_bundle, indent=2)[:2000]}"
    )


async def run(client: FhirClient) -> str:
    existing = await client.search("Patient", {"identifier": f"{MRN_SYSTEM}|{MRN_VALUE}"})
    for pid in _ids(existing):
        count = await _cascade_delete(client, pid)
        print(f"Deleted {count} resources for prior Patient/{pid}")

    bundle = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))
    response = await client.transaction(bundle)
    return _extract_patient_id(response)
