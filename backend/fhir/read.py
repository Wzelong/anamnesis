"""Async read helpers returning typed Python representations of FHIR data."""
import asyncio
import base64

from fhir.client import FhirClient
from fhir.models import Document, PatientContext


def _entries(bundle: dict | None) -> list[dict]:
    if not bundle:
        return []
    return [e["resource"] for e in bundle.get("entry", []) if e.get("resource")]


async def read_patient_context(client: FhirClient, patient_id: str) -> PatientContext:
    params = {"patient": patient_id}
    patient, conditions, medications, allergies, observations, family_history, procedures, encounters = await asyncio.gather(
        client.read(f"Patient/{patient_id}"),
        client.search("Condition", params),
        client.search("MedicationRequest", params),
        client.search("AllergyIntolerance", params),
        client.search("Observation", params),
        client.search("FamilyMemberHistory", params),
        client.search("Procedure", params),
        client.search("Encounter", params),
    )
    if not patient:
        raise ValueError(f"Patient/{patient_id} not found")

    return PatientContext(
        patient=patient,
        conditions=_entries(conditions),
        medications=_entries(medications),
        allergies=_entries(allergies),
        observations=_entries(observations),
        family_history=_entries(family_history),
        procedures=_entries(procedures),
        encounters=_entries(encounters),
    )


async def _decode_attachment(client: FhirClient, attachment: dict) -> str:
    data = attachment.get("data")
    if data:
        try:
            return base64.b64decode(data).decode("utf-8", errors="replace")
        except Exception:
            return ""

    url = attachment.get("url")
    if url:
        response = await client._request("GET", url)
        if response.status_code >= 400:
            return ""
        ctype = response.headers.get("content-type", "")
        if "json" in ctype:
            body = response.json()
            b64 = body.get("data") if isinstance(body, dict) else None
            if b64:
                try:
                    return base64.b64decode(b64).decode("utf-8", errors="replace")
                except Exception:
                    return ""
            return ""
        return response.content.decode("utf-8", errors="replace")

    return ""


async def read_documents(client: FhirClient, patient_id: str) -> list[Document]:
    bundle = await client.search("DocumentReference", {"patient": patient_id})
    resources = _entries(bundle)

    async def _parse_one(res: dict) -> Document:
        contents = res.get("content") or []
        attachment = contents[0].get("attachment", {}) if contents else {}
        text = await _decode_attachment(client, attachment)

        type_field = res.get("type", {}) or {}
        coding = (type_field.get("coding") or [{}])[0]
        type_label = coding.get("display") or type_field.get("text") or ""

        authors = res.get("author") or []
        author = authors[0].get("display", "") if authors else ""

        ctx = res.get("context") or {}
        enc_refs = ctx.get("encounter") or []
        enc_ref = enc_refs[0].get("reference", "") if enc_refs else ""
        enc_id = enc_ref if enc_ref else None

        return Document(
            id=res.get("id", ""),
            type=type_label,
            date=res.get("date", ""),
            author=author,
            text=text,
            encounter_id=enc_id or None,
        )

    return list(await asyncio.gather(*[_parse_one(r) for r in resources]))
