"""E2E coverage of the agent-supplied notes path.

Exercises the new code paths only — no live LLM. Two parts:
  1. _documents_from_notes + run snapshot round-trip + ProposalRecord shape.
  2. apply_augmentation with an inline-document citation produces a
     transaction bundle whose Provenance points at the just-minted
     DocumentReference (US Core profile, base64 inline content).
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from context.auth import ReviewerIdentity
from fhir.models import Document, PatientContext
from fhir.write import (
    AugmentationProposal,
    Citation,
    US_CORE_DOCREF_CATEGORY_SYSTEM,
    US_CORE_DOCREF_PROFILE,
    apply_augmentation,
)
from services import proposals as proposal_svc
from services import run_snapshot

INLINE_ID_RE = re.compile(r"^inline_[0-9a-f]{12}$")


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "inline.db"
    monkeypatch.setattr(run_snapshot, "SNAPSHOT_DIR", tmp_path / "runs")

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    sm = async_sessionmaker(engine, expire_on_commit=False)

    import db as db_pkg
    import db.session as session_mod
    from db.models import Base

    monkeypatch.setattr(db_pkg, "AsyncSessionLocal", sm)
    monkeypatch.setattr(session_mod, "AsyncSessionLocal", sm)

    async def _init():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(_init())
    yield
    asyncio.run(engine.dispose())


def _run(coro):
    return asyncio.run(coro)


def test_documents_from_notes_ids_are_deterministic_and_prefixed():
    notes = ["Patient on metformin 500 mg BID for type 2 diabetes.",
             "Outside cardiology consult: stage 1 hypertension noted."]
    docs = proposal_svc._documents_from_notes(notes, "External record", "2026-05-02T00:00:00Z")
    assert len(docs) == 2
    for d in docs:
        assert INLINE_ID_RE.match(d.id), d.id
        assert d.type == "External record"
        assert d.date == "2026-05-02T00:00:00Z"
        assert d.encounter_id is None

    again = proposal_svc._documents_from_notes(notes, "External record", "2026-05-02T00:00:00Z")
    assert [d.id for d in docs] == [d.id for d in again]

    docs2 = proposal_svc._documents_from_notes(notes + ["different content"], "External record", "2026-05-02T00:00:00Z")
    assert {d.id for d in docs}.issubset({d.id for d in docs2})


def test_documents_from_notes_rejects_empty():
    with pytest.raises(ValueError):
        proposal_svc._documents_from_notes([], "External record", None)
    with pytest.raises(ValueError):
        proposal_svc._documents_from_notes(["   ", ""], "External record", None)


def test_run_snapshot_round_trip_preserves_inline_documents():
    docs = proposal_svc._documents_from_notes(
        ["Patient on metformin 500 mg BID."],
        "External record",
        "2026-05-02T00:00:00Z",
    )
    pc = PatientContext(patient={"id": "p-1", "resourceType": "Patient"})
    run_snapshot.write("run_test", pc, docs)
    out = run_snapshot.read("run_test")
    assert out is not None
    pc_out, docs_out = out
    assert pc_out.patient["id"] == "p-1"
    assert len(docs_out) == 1
    assert docs_out[0].id == docs[0].id
    assert docs_out[0].text == docs[0].text
    assert docs_out[0].type == "External record"


def test_inline_proposal_record_lists_with_inline_doc_id_in_citations():
    async def run():
        from db import AsyncSessionLocal, PipelineRun, ProposalRecord

        docs = proposal_svc._documents_from_notes(
            ["Patient has hypertension."], "External record", "2026-05-02T00:00:00Z",
        )
        run_snapshot.write("run_x", PatientContext(patient={"id": "p-1"}), docs)
        cite = {
            "document_id": docs[0].id,
            "char_start": 0,
            "char_end": len(docs[0].text),
            "text": docs[0].text,
            "sentence_numbers": [1],
        }
        async with AsyncSessionLocal() as session:
            session.add(PipelineRun(
                id="run_x",
                patient_id="p-1",
                triggered_by="api:inline",
                status="completed",
                started_at=datetime.now(timezone.utc),
            ))
            session.add(ProposalRecord(
                id="prop_x",
                run_id="run_x",
                patient_id="p-1",
                resource_type="Condition",
                classification="NEW",
                confidence_tier="REVIEW",
                confidence_score=Decimal("0.7"),
                status="pending",
                resource_json=json.dumps({"resourceType": "Condition", "code": {"text": "Hypertension"}}),
                citations_json=json.dumps([cite]),
                metadata_json=json.dumps({"flags": [], "supersedes": []}),
                created_at=datetime.now(timezone.utc),
            ))
            await session.commit()

            results = await proposal_svc.list_proposals(session, run_id="run_x")
        assert len(results) == 1
        assert results[0]["id"] == "prop_x"
    _run(run())


class _StubClient:
    """Minimal FhirClient surface — only `transaction` is used by apply_augmentation NEW/CONFLICTING."""

    def __init__(self):
        self.captured: dict | None = None

    async def transaction(self, bundle: dict) -> dict:
        self.captured = bundle
        entries_out = []
        for i, entry in enumerate(bundle["entry"]):
            rt = entry["resource"]["resourceType"]
            entries_out.append({"response": {"status": "201 Created", "location": f"{rt}/srv-{i}/_history/1"}})
        return {"resourceType": "Bundle", "type": "transaction-response", "entry": entries_out}


def test_accept_writes_us_core_documentreference_for_inline_source():
    text = "Patient has stage 1 hypertension since 2024."
    inline = Document(
        id="inline_abcdef012345",
        type="External record",
        date="2026-05-02T00:00:00Z",
        author="",
        text=text,
        encounter_id=None,
    )
    proposal = AugmentationProposal(
        classification="NEW",
        resource={
            "resourceType": "Condition",
            "code": {"text": "Hypertension"},
            "subject": {"reference": "Patient/p-1"},
        },
        citations=[Citation(
            document_ref="DocumentReference/inline_abcdef012345",
            start=0,
            end=len(text),
            text=text,
            inline_document=inline,
        )],
    )
    stub = _StubClient()
    attester = ReviewerIdentity(display="Dr. Smith", fhir_reference="Practitioner/p99")

    result = _run(apply_augmentation(stub, proposal, attester=attester, patient_id="p-1"))

    bundle = stub.captured
    assert bundle is not None
    entries = bundle["entry"]
    assert len(entries) == 3, [e["resource"]["resourceType"] for e in entries]

    docref_entry, condition_entry, prov_entry = entries

    docref = docref_entry["resource"]
    assert docref["resourceType"] == "DocumentReference"
    assert US_CORE_DOCREF_PROFILE in docref["meta"]["profile"]
    assert docref["status"] == "current"
    assert docref["type"]["coding"][0]["code"] == "34109-9"
    assert docref["type"]["text"] == "External record"
    assert any(
        coding.get("system") == US_CORE_DOCREF_CATEGORY_SYSTEM and coding.get("code") == "clinical-note"
        for cat in docref["category"]
        for coding in cat.get("coding", [])
    )
    assert docref["subject"]["reference"] == "Patient/p-1"
    attachment = docref["content"][0]["attachment"]
    assert attachment["contentType"].startswith("text/plain")
    assert base64.b64decode(attachment["data"]).decode("utf-8") == text
    assert docref["author"][0]["display"] == "Dr. Smith"
    assert docref["author"][0]["reference"] == "Practitioner/p99"

    assert condition_entry["resource"]["resourceType"] == "Condition"
    cond_urn = condition_entry["fullUrl"]
    docref_urn = docref_entry["fullUrl"]
    assert cond_urn.startswith("urn:uuid:")
    assert docref_urn.startswith("urn:uuid:")
    assert cond_urn != docref_urn

    prov = prov_entry["resource"]
    assert prov["resourceType"] == "Provenance"
    assert prov["target"][0]["reference"] == cond_urn
    entity_refs = [e["what"]["reference"] for e in prov["entity"]]
    assert entity_refs == [docref_urn], entity_refs
    span_refs = [
        ext["extension"][0]["valueString"]
        for ext in prov.get("extension", [])
        if ext.get("url", "").endswith("source-text-span")
    ]
    assert span_refs == [docref_urn]
    agent_types = [a["type"]["coding"][0]["code"] for a in prov["agent"]]
    assert "author" in agent_types and "attester" in agent_types

    assert result.resource_ref.startswith("Condition/")
    assert result.provenance_ref.startswith("Provenance/")
