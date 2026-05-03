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
    patient, conditions, medications, allergies, observations, family_history, procedures, encounters, documents = await asyncio.gather(
        client.read(f"Patient/{patient_id}"),
        client.search("Condition", params),
        client.search("MedicationRequest", params),
        client.search("AllergyIntolerance", params),
        client.search("Observation", params),
        client.search("FamilyMemberHistory", params),
        client.search("Procedure", params),
        client.search("Encounter", params),
        client.search("DocumentReference", params),
    )
    if not patient:
        raise ValueError(f"Patient/{patient_id} not found")

    cond = _entries(conditions)
    meds = _entries(medications)
    allergy = _entries(allergies)
    obs = _entries(observations)
    fhx = _entries(family_history)
    proc = _entries(procedures)
    enc = _entries(encounters)
    docs = _entries(documents)

    targets = [f"Patient/{patient_id}"]
    for resources, type_name in [
        (cond, "Condition"), (meds, "MedicationRequest"), (allergy, "AllergyIntolerance"),
        (obs, "Observation"), (fhx, "FamilyMemberHistory"), (proc, "Procedure"),
        (enc, "Encounter"), (docs, "DocumentReference"),
    ]:
        for r in resources:
            rid = r.get("id")
            if rid:
                targets.append(f"{type_name}/{rid}")

    pract_ids: set[str] = set()
    org_ids: set[str] = set()
    for resources in (cond, meds, allergy, obs, fhx, proc, enc, docs):
        for r in resources:
            _walk_refs(r, pract_ids, org_ids)

    provenance_task = client.search("Provenance", {"target": ",".join(targets)})
    pract_task = client.search("Practitioner", {"_id": ",".join(pract_ids)}) if pract_ids else None
    org_task = client.search("Organization", {"_id": ",".join(org_ids)}) if org_ids else None
    provenance_bundle, practitioner_bundle, organization_bundle = await asyncio.gather(
        provenance_task,
        pract_task or asyncio.sleep(0, result=None),
        org_task or asyncio.sleep(0, result=None),
    )
    provenances = _entries(provenance_bundle)

    for p in provenances:
        _walk_refs(p, pract_ids, org_ids)
    new_pract = pract_ids - {pr.get("id", "") for pr in _entries(practitioner_bundle)}
    new_org = org_ids - {o.get("id", "") for o in _entries(organization_bundle)}
    if new_pract:
        practitioner_bundle = await client.search("Practitioner", {"_id": ",".join(pract_ids)})
    if new_org:
        organization_bundle = await client.search("Organization", {"_id": ",".join(org_ids)})

    return PatientContext(
        patient=patient,
        conditions=cond,
        medications=meds,
        allergies=allergy,
        observations=obs,
        family_history=fhx,
        procedures=proc,
        encounters=enc,
        practitioners=_entries(practitioner_bundle),
        organizations=_entries(organization_bundle),
        documents=docs,
        provenances=provenances,
    )


def _walk_refs(node, practitioners: set[str], organizations: set[str]) -> None:
    if isinstance(node, dict):
        ref = node.get("reference")
        if isinstance(ref, str):
            if ref.startswith("Practitioner/"):
                practitioners.add(ref.split("/", 1)[1])
            elif ref.startswith("Organization/"):
                organizations.add(ref.split("/", 1)[1])
        for v in node.values():
            _walk_refs(v, practitioners, organizations)
    elif isinstance(node, list):
        for v in node:
            _walk_refs(v, practitioners, organizations)


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
