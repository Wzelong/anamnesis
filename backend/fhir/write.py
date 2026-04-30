"""Write augmentations (resource + Provenance) back to the FHIR server.

Supports all three classifications:
- NEW: POST resource + Provenance
- UPDATING: PUT updated resource + POST Provenance
- CONFLICTING: POST new resource + Provenance (does not retire existing)

Multi-citation Provenance: each source document gets its own entity entry
and source-span extension, so the UI can highlight every corroborating note.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

if TYPE_CHECKING:
    from context.auth import ReviewerIdentity

from fhir.client import FhirClient

SOURCE_SPAN_EXT_URL = "http://anamnesis.example.org/StructureDefinition/source-text-span"
PROVENANCE_AGENT_TYPE_SYSTEM = "http://terminology.hl7.org/CodeSystem/provenance-participant-type"
PROVENANCE_ACTIVITY_SYSTEM = "http://terminology.hl7.org/CodeSystem/v3-DataOperation"

Classification = Literal["NEW", "UPDATING", "CONFLICTING"]


@dataclass
class Citation:
    document_ref: str
    start: int
    end: int
    text: str


@dataclass
class AugmentationProposal:
    classification: Classification
    resource: dict
    citations: list[Citation] = field(default_factory=list)
    supersedes_ref: str | None = None


@dataclass
class WriteResult:
    resource_ref: str
    provenance_ref: str
    superseded_ref: str | None = None


def build_provenance(
    target_urn: str,
    citations: list[Citation],
    *,
    activity_code: str = "CREATE",
    actor_name: str = "Anamnesis",
    attester: ReviewerIdentity | None = None,
) -> dict:
    entities = []
    extensions = []
    seen_docs: set[str] = set()

    for c in citations:
        if c.document_ref not in seen_docs:
            entities.append({"role": "source", "what": {"reference": c.document_ref}})
            seen_docs.add(c.document_ref)
        extensions.append({
            "url": SOURCE_SPAN_EXT_URL,
            "extension": [
                {"url": "documentRef", "valueString": c.document_ref},
                {"url": "start", "valueInteger": c.start},
                {"url": "end", "valueInteger": c.end},
                {"url": "text", "valueString": c.text},
            ],
        })

    agents = [{
        "type": {"coding": [{"system": PROVENANCE_AGENT_TYPE_SYSTEM, "code": "author"}]},
        "who": {"display": actor_name},
    }]
    if attester:
        who: dict = {"display": attester.display}
        if attester.fhir_reference:
            who["reference"] = attester.fhir_reference
        agents.append({
            "type": {"coding": [{"system": PROVENANCE_AGENT_TYPE_SYSTEM, "code": "attester"}]},
            "who": who,
        })

    return {
        "resourceType": "Provenance",
        "meta": {"profile": ["http://hl7.org/fhir/us/core/StructureDefinition/us-core-provenance"]},
        "target": [{"reference": target_urn}],
        "recorded": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "activity": {
            "coding": [{"system": PROVENANCE_ACTIVITY_SYSTEM, "code": activity_code}],
        },
        "agent": agents,
        "entity": entities,
        "extension": extensions,
    }


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


async def _apply_new(client: FhirClient, proposal: AugmentationProposal, *, attester: ReviewerIdentity | None = None) -> WriteResult:
    resource_type = proposal.resource.get("resourceType")
    if not resource_type:
        raise ValueError("proposal.resource missing resourceType")

    urn_resource = f"urn:uuid:{uuid4()}"
    urn_prov = f"urn:uuid:{uuid4()}"

    provenance = build_provenance(urn_resource, proposal.citations, activity_code="CREATE", attester=attester)

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


async def _apply_updating(client: FhirClient, proposal: AugmentationProposal, *, attester: ReviewerIdentity | None = None) -> WriteResult:
    resource_type = proposal.resource.get("resourceType")
    if not resource_type:
        raise ValueError("proposal.resource missing resourceType")
    if not proposal.supersedes_ref:
        raise ValueError("UPDATING proposal must have supersedes_ref")

    existing = await client.read(proposal.supersedes_ref)
    if not existing:
        raise RuntimeError(f"superseded resource {proposal.supersedes_ref} not found")

    resource_id = existing.get("id")
    updated = {**proposal.resource, "id": resource_id}

    if "meta" in existing:
        updated.setdefault("meta", {})["versionId"] = existing["meta"].get("versionId")

    urn_prov = f"urn:uuid:{uuid4()}"
    provenance = build_provenance(
        proposal.supersedes_ref, proposal.citations, activity_code="UPDATE", attester=attester,
    )

    bundle = {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {
                "fullUrl": f"urn:uuid:{uuid4()}",
                "resource": updated,
                "request": {"method": "PUT", "url": proposal.supersedes_ref},
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
    provenance_ref = _find_ref(entries, "Provenance")
    return WriteResult(
        resource_ref=proposal.supersedes_ref,
        provenance_ref=provenance_ref,
        superseded_ref=proposal.supersedes_ref,
    )


async def _apply_conflicting(client: FhirClient, proposal: AugmentationProposal, *, attester: ReviewerIdentity | None = None) -> WriteResult:
    resource_type = proposal.resource.get("resourceType")
    if not resource_type:
        raise ValueError("proposal.resource missing resourceType")

    urn_resource = f"urn:uuid:{uuid4()}"
    urn_prov = f"urn:uuid:{uuid4()}"

    provenance = build_provenance(urn_resource, proposal.citations, activity_code="CREATE", attester=attester)

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


async def apply_augmentation(client: FhirClient, proposal: AugmentationProposal, *, attester: ReviewerIdentity | None = None) -> WriteResult:
    if proposal.classification == "NEW":
        return await _apply_new(client, proposal, attester=attester)
    if proposal.classification == "UPDATING":
        return await _apply_updating(client, proposal, attester=attester)
    if proposal.classification == "CONFLICTING":
        return await _apply_conflicting(client, proposal, attester=attester)
    raise ValueError(f"unknown classification: {proposal.classification}")
