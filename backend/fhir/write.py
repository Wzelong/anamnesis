"""Write augmentations (resource + Provenance) back to the FHIR server.

Generic substrate: knows nothing about specific resource types, codes, or the
demo patient. Callers build the resource dict; this module links it to a source
document via Provenance and POSTs both atomically.
"""
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fhir.resources.R4B.provenance import Provenance

from fhir.client import FhirClient

SOURCE_SPAN_EXT_URL = "http://anamnesis.example.org/StructureDefinition/source-text-span"
PROVENANCE_AGENT_TYPE_SYSTEM = "http://terminology.hl7.org/CodeSystem/provenance-participant-type"

Classification = Literal["NEW", "UPDATING", "CONFLICTING", "CORROBORATING"]


@dataclass
class SourceSpan:
    start: int
    end: int
    text: str


@dataclass
class AugmentationProposal:
    classification: Classification
    resource: dict
    source_document_ref: str
    source_span: SourceSpan
    supersedes_resource_ref: str | None = None
    stop_reason: str | None = None


@dataclass
class WriteResult:
    resource_ref: str
    provenance_ref: str
    superseded_ref: str | None = None


def build_provenance(
    target_urn: str,
    source_document_ref: str,
    source_span: SourceSpan,
    actor_name: str = "Anamnesis",
) -> dict:
    prov = Provenance(
        target=[{"reference": target_urn}],
        recorded=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        agent=[{
            "type": {"coding": [{"system": PROVENANCE_AGENT_TYPE_SYSTEM, "code": "author"}]},
            "who": {"display": actor_name},
        }],
        entity=[{
            "role": "source",
            "what": {"reference": source_document_ref},
        }],
        extension=[{
            "url": SOURCE_SPAN_EXT_URL,
            "extension": [
                {"url": "start", "valueInteger": source_span.start},
                {"url": "end", "valueInteger": source_span.end},
                {"url": "text", "valueString": source_span.text},
            ],
        }],
    )
    return prov.model_dump(mode="json", exclude_none=True)


_LOCATION_RE = re.compile(r"(?:^|/)([A-Z][A-Za-z]+)/([^/?#]+)")


def _ref_from_location(location: str) -> str | None:
    if not location:
        return None
    match = _LOCATION_RE.search(location)
    if not match:
        return None
    return f"{match.group(1)}/{match.group(2)}"


def _find_ref(entries: list[dict], resource_type: str) -> str:
    for entry in entries:
        location = (entry.get("response") or {}).get("location") or ""
        ref = _ref_from_location(location)
        if ref and ref.startswith(f"{resource_type}/"):
            return ref
        resource = entry.get("resource") or {}
        if resource.get("resourceType") == resource_type and resource.get("id"):
            return f"{resource_type}/{resource['id']}"
    raise RuntimeError(f"transaction response had no {resource_type} entry")


async def _apply_new(client: FhirClient, proposal: AugmentationProposal) -> WriteResult:
    resource_type = proposal.resource.get("resourceType")
    if not resource_type:
        raise ValueError("proposal.resource missing resourceType")

    urn_resource = f"urn:uuid:{uuid4()}"
    urn_prov = f"urn:uuid:{uuid4()}"

    provenance = build_provenance(
        target_urn=urn_resource,
        source_document_ref=proposal.source_document_ref,
        source_span=proposal.source_span,
    )

    bundle = {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {
                "fullUrl": urn_resource,
                "resource": proposal.resource,
                "request": {"method": "POST", "url": resource_type},
            },
            {
                "fullUrl": urn_prov,
                "resource": provenance,
                "request": {"method": "POST", "url": "Provenance"},
            },
        ],
    }

    response = await client.transaction(bundle)
    entries = response.get("entry", [])
    resource_ref = _find_ref(entries, resource_type)
    provenance_ref = _find_ref(entries, "Provenance")
    return WriteResult(resource_ref=resource_ref, provenance_ref=provenance_ref)


async def apply_augmentation(client: FhirClient, proposal: AugmentationProposal) -> WriteResult:
    if proposal.classification == "NEW":
        return await _apply_new(client, proposal)
    if proposal.classification == "UPDATING":
        raise NotImplementedError("UPDATING not implemented in Phase 2")
    if proposal.classification == "CONFLICTING":
        raise NotImplementedError("CONFLICTING not implemented in Phase 2")
    if proposal.classification == "CORROBORATING":
        raise NotImplementedError("CORROBORATING not implemented in Phase 2")
    raise ValueError(f"unknown classification: {proposal.classification}")
