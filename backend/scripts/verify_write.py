"""Smoke test: write a metoprolol MedicationRequest + Provenance for James Lee,
then round-trip read back to confirm both landed with the source-span extension.

Run from backend/:
    python -m scripts.verify_write
"""
import asyncio
import base64
import os
import re
import sys

from dotenv import load_dotenv
from fhir.resources.R4B.medicationrequest import MedicationRequest

from fhir.client import FhirClient
from fhir.write import (
    SOURCE_SPAN_EXT_URL,
    AugmentationProposal,
    Citation,
    apply_augmentation,
)

MRN_SYSTEM = "http://bayside.health/mrn"
MRN_VALUE = "BAY-0042-LEE"
CARDIO_LOINC = "11488-4"
CARDIO_AUTHOR = "Dr. David Park"
TARGET_QUOTE = "INITIATE metoprolol succinate 25 mg PO once daily as anti-anginal therapy and rate control"

RXNORM_SYSTEM = "http://www.nlm.nih.gov/research/umls/rxnorm"
SCT_SYSTEM = "http://snomed.info/sct"
US_CORE_MEDREQ = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-medicationrequest"


async def _find_patient_id(client: FhirClient) -> str:
    bundle = await client.search("Patient", {"identifier": f"{MRN_SYSTEM}|{MRN_VALUE}"})
    entries = (bundle or {}).get("entry") or []
    if not entries:
        raise RuntimeError(f"No patient found with MRN {MRN_VALUE}. Run scripts.bootstrap first.")
    return entries[0]["resource"]["id"]


async def _find_cardio_note(client: FhirClient, patient_id: str) -> tuple[str, str]:
    bundle = await client.search(
        "DocumentReference",
        {"patient": patient_id, "type": f"http://loinc.org|{CARDIO_LOINC}"},
    )
    entries = (bundle or {}).get("entry") or []
    for entry in entries:
        res = entry["resource"]
        authors = res.get("author") or []
        if authors and authors[0].get("display") == CARDIO_AUTHOR:
            attachment = (res.get("content") or [{}])[0].get("attachment") or {}
            data = attachment.get("data") or ""
            text = base64.b64decode(data).decode("utf-8", errors="replace") if data else ""
            return res["id"], text
    raise RuntimeError(f"No cardiology note (LOINC {CARDIO_LOINC}) by {CARDIO_AUTHOR} found")


def _compute_citation(note_text: str, doc_id: str) -> Citation:
    pattern = re.compile(r"\s+".join(re.escape(w) for w in TARGET_QUOTE.split()))
    match = pattern.search(note_text)
    if not match:
        raise RuntimeError("Target quote not found in cardiology note")
    return Citation(
        document_ref=f"DocumentReference/{doc_id}",
        start=match.start(), end=match.end(), text=match.group(0),
    )


def _build_metoprolol_request(patient_id: str) -> dict:
    medreq = MedicationRequest(
        meta={"profile": [US_CORE_MEDREQ]},
        status="active",
        intent="order",
        reportedBoolean=False,
        medicationCodeableConcept={
            "coding": [{
                "system": RXNORM_SYSTEM,
                "code": "866427",
                "display": "Metoprolol Succinate 25 MG Extended Release Oral Tablet",
            }],
            "text": "Metoprolol Succinate 25 mg",
        },
        subject={"reference": f"Patient/{patient_id}"},
        authoredOn="2025-10-20",
        requester={"display": CARDIO_AUTHOR},
        dosageInstruction=[{
            "text": "25 mg PO once daily",
            "route": {"coding": [{
                "system": SCT_SYSTEM,
                "code": "26643006",
                "display": "Oral route",
            }]},
        }],
    )
    return medreq.model_dump(mode="json", exclude_none=True)


async def _assert_roundtrip(
    client: FhirClient,
    resource_ref: str,
    provenance_ref: str,
    source_document_ref: str,
    span: SourceSpan,
) -> None:
    resource = await client.read(resource_ref)
    assert resource, f"{resource_ref} not readable"
    codings = (resource.get("medicationCodeableConcept") or {}).get("coding") or []
    assert any(c.get("code") == "866427" for c in codings), "RxNorm 866427 missing on resource"

    provenance = await client.read(provenance_ref)
    assert provenance, f"{provenance_ref} not readable"
    target_ref = (provenance.get("target") or [{}])[0].get("reference")
    assert target_ref == resource_ref, f"Provenance.target mismatch: {target_ref} != {resource_ref}"

    entity_what = ((provenance.get("entity") or [{}])[0].get("what") or {}).get("reference")
    assert entity_what == source_document_ref, (
        f"Provenance.entity.what mismatch: {entity_what} != {source_document_ref}"
    )

    ext_blocks = [e for e in (provenance.get("extension") or []) if e.get("url") == SOURCE_SPAN_EXT_URL]
    assert ext_blocks, "source-span extension missing from Provenance"
    sub = {x["url"]: x for x in (ext_blocks[0].get("extension") or [])}
    assert sub.get("start", {}).get("valueInteger") == span.start
    assert sub.get("end", {}).get("valueInteger") == span.end
    assert sub.get("text", {}).get("valueString") == span.text
    assert sub.get("documentRef", {}).get("valueString") == source_document_ref


async def main() -> int:
    load_dotenv()
    url = os.environ.get("DEV_FHIR_BASE_URL")
    token = os.environ.get("DEV_FHIR_TOKEN")
    if not url or not token:
        print("error: DEV_FHIR_BASE_URL and DEV_FHIR_TOKEN must be set in .env", file=sys.stderr)
        return 2

    client = FhirClient(url, token)

    patient_id = await _find_patient_id(client)
    print(f"Patient: Patient/{patient_id}")

    doc_id, note_text = await _find_cardio_note(client, patient_id)
    print(f"Cardiology note: DocumentReference/{doc_id}")

    citation = _compute_citation(note_text, doc_id)
    preview = citation.text[:70] + ("..." if len(citation.text) > 70 else "")
    print(f"Source span: [{citation.start}..{citation.end}] {preview}")

    proposal = AugmentationProposal(
        classification="NEW",
        resource=_build_metoprolol_request(patient_id),
        citations=[citation],
    )

    result = await apply_augmentation(client, proposal)
    print(f"Wrote {result.resource_ref}")
    print(f"Wrote {result.provenance_ref}")

    await _assert_roundtrip(
        client,
        result.resource_ref,
        result.provenance_ref,
        citation.document_ref,
        citation,
    )
    print("Round-trip verified ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
