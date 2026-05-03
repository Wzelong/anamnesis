"""Write augmentations (resource + Provenance) back to the FHIR server.

Supports all three classifications:
- NEW: POST resource + Provenance
- UPDATING: PUT updated resource + POST Provenance
- CONFLICTING: POST new resource + Provenance (does not retire existing)

Multi-citation Provenance: each source document gets its own entity entry
and source-span extension, so the UI can highlight every corroborating note.
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

if TYPE_CHECKING:
    from context.auth import ReviewerIdentity

from fhir.client import FhirClient
from fhir.models import Document

SOURCE_SPAN_EXT_URL = "http://anamnesis.example.org/StructureDefinition/source-text-span"
PROVENANCE_AGENT_TYPE_SYSTEM = "http://terminology.hl7.org/CodeSystem/provenance-participant-type"
PROVENANCE_ACTIVITY_SYSTEM = "http://terminology.hl7.org/CodeSystem/v3-DataOperation"
US_CORE_DOCREF_PROFILE = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-documentreference"
US_CORE_DOCREF_CATEGORY_SYSTEM = "http://hl7.org/fhir/us/core/CodeSystem/us-core-documentreference-category"
LOINC_SYSTEM = "http://loinc.org"
DEFAULT_NOTE_LOINC = ("34109-9", "Note")

Classification = Literal["NEW", "UPDATING", "CONFLICTING"]


@dataclass
class Citation:
    document_ref: str
    start: int
    end: int
    text: str
    inline_document: Document | None = None


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


def _build_inline_documentreference(
    doc: Document,
    patient_id: str,
    *,
    attester: ReviewerIdentity | None = None,
) -> dict:
    encoded = base64.b64encode(doc.text.encode("utf-8")).decode("ascii")
    type_text = doc.type or "Note"
    type_cc: dict = {
        "coding": [{
            "system": LOINC_SYSTEM,
            "code": DEFAULT_NOTE_LOINC[0],
            "display": DEFAULT_NOTE_LOINC[1],
        }],
        "text": type_text,
    }
    resource: dict = {
        "resourceType": "DocumentReference",
        "meta": {"profile": [US_CORE_DOCREF_PROFILE]},
        "status": "current",
        "type": type_cc,
        "category": [{
            "coding": [{
                "system": US_CORE_DOCREF_CATEGORY_SYSTEM,
                "code": "clinical-note",
            }],
        }],
        "subject": {"reference": f"Patient/{patient_id}"},
        "content": [{
            "attachment": {
                "contentType": "text/plain; charset=UTF-8",
                "data": encoded,
            },
        }],
    }
    if doc.date:
        resource["date"] = doc.date
    if attester:
        author: dict = {"display": attester.display}
        if attester.fhir_reference:
            author["reference"] = attester.fhir_reference
        resource["author"] = [author]
    return resource


def _resolve_inline_citations(
    citations: list[Citation],
    patient_id: str,
    *,
    attester: ReviewerIdentity | None,
) -> tuple[list[dict], list[Citation]]:
    """Mint a DocumentReference bundle entry per unique inline source document.

    Returns (bundle_entries, rewritten_citations) where each rewritten
    citation pointing at an inline doc has its `document_ref` rewritten to
    the urn:uuid of the prepended DocumentReference entry, so the standard
    Provenance build path produces the right linkage.
    """
    inline_entries: list[dict] = []
    by_doc_id: dict[str, str] = {}
    rewritten: list[Citation] = []
    for c in citations:
        doc = c.inline_document
        if doc is None:
            rewritten.append(c)
            continue
        urn = by_doc_id.get(doc.id)
        if urn is None:
            urn = f"urn:uuid:{uuid4()}"
            by_doc_id[doc.id] = urn
            inline_entries.append({
                "fullUrl": urn,
                "resource": _build_inline_documentreference(doc, patient_id, attester=attester),
                "request": {"method": "POST", "url": "DocumentReference"},
            })
        rewritten.append(replace(c, document_ref=urn))
    return inline_entries, rewritten


_LOCATION_RE = re.compile(r"(?:^|/)([A-Z][A-Za-z]+)/([^/?#]+)")


def _ref_from_location(location: str) -> str | None:
    if not location:
        return None
    match = _LOCATION_RE.search(location)
    if not match:
        return None
    return f"{match.group(1)}/{match.group(2)}"


def _find_ref(entries: list[dict], resource_type: str, *, start: int = 0) -> str:
    for entry in entries[start:]:
        location = (entry.get("response") or {}).get("location") or ""
        ref = _ref_from_location(location)
        if ref and ref.startswith(f"{resource_type}/"):
            return ref
        resource = entry.get("resource") or {}
        if resource.get("resourceType") == resource_type and resource.get("id"):
            return f"{resource_type}/{resource['id']}"
    raise RuntimeError(f"transaction response had no {resource_type} entry")


async def _apply_new(
    client: FhirClient,
    proposal: AugmentationProposal,
    *,
    attester: ReviewerIdentity | None = None,
    patient_id: str = "",
) -> WriteResult:
    resource_type = proposal.resource.get("resourceType")
    if not resource_type:
        raise ValueError("proposal.resource missing resourceType")

    inline_entries, citations = _resolve_inline_citations(
        proposal.citations, patient_id, attester=attester,
    )

    urn_resource = f"urn:uuid:{uuid4()}"
    urn_prov = f"urn:uuid:{uuid4()}"

    provenance = build_provenance(urn_resource, citations, activity_code="CREATE", attester=attester)

    bundle = {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            *inline_entries,
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
    resource_ref = _find_ref(entries, resource_type, start=len(inline_entries))
    provenance_ref = _find_ref(entries, "Provenance", start=len(inline_entries) + 1)
    return WriteResult(resource_ref=resource_ref, provenance_ref=provenance_ref)


async def _apply_updating(
    client: FhirClient,
    proposal: AugmentationProposal,
    *,
    attester: ReviewerIdentity | None = None,
    patient_id: str = "",
) -> WriteResult:
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

    inline_entries, citations = _resolve_inline_citations(
        proposal.citations, patient_id, attester=attester,
    )

    urn_prov = f"urn:uuid:{uuid4()}"
    provenance = build_provenance(
        proposal.supersedes_ref, citations, activity_code="UPDATE", attester=attester,
    )

    bundle = {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            *inline_entries,
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
    provenance_ref = _find_ref(entries, "Provenance", start=len(inline_entries) + 1)
    return WriteResult(
        resource_ref=proposal.supersedes_ref,
        provenance_ref=provenance_ref,
        superseded_ref=proposal.supersedes_ref,
    )


async def _apply_conflicting(
    client: FhirClient,
    proposal: AugmentationProposal,
    *,
    attester: ReviewerIdentity | None = None,
    patient_id: str = "",
) -> WriteResult:
    resource_type = proposal.resource.get("resourceType")
    if not resource_type:
        raise ValueError("proposal.resource missing resourceType")

    inline_entries, citations = _resolve_inline_citations(
        proposal.citations, patient_id, attester=attester,
    )

    urn_resource = f"urn:uuid:{uuid4()}"
    urn_prov = f"urn:uuid:{uuid4()}"

    provenance = build_provenance(urn_resource, citations, activity_code="CREATE", attester=attester)

    bundle = {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            *inline_entries,
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
    resource_ref = _find_ref(entries, resource_type, start=len(inline_entries))
    provenance_ref = _find_ref(entries, "Provenance", start=len(inline_entries) + 1)
    return WriteResult(resource_ref=resource_ref, provenance_ref=provenance_ref)


async def apply_augmentation(
    client: FhirClient,
    proposal: AugmentationProposal,
    *,
    attester: ReviewerIdentity | None = None,
    patient_id: str = "",
) -> WriteResult:
    if proposal.classification == "NEW":
        return await _apply_new(client, proposal, attester=attester, patient_id=patient_id)
    if proposal.classification == "UPDATING":
        return await _apply_updating(client, proposal, attester=attester, patient_id=patient_id)
    if proposal.classification == "CONFLICTING":
        return await _apply_conflicting(client, proposal, attester=attester, patient_id=patient_id)
    raise ValueError(f"unknown classification: {proposal.classification}")
