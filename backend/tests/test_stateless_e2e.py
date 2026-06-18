"""Stateless review path: deterministic coverage of the proposal-shaping logic
(always runs) plus an opt-in end-to-end run of `run_extraction_ephemeral`
against the demo bundle (RUN_E2E=1; needs OPENAI_API_KEY + network).
"""
from __future__ import annotations

import os

import pytest

from core.schemas import (
    ChartMatch,
    ConfidenceAxis,
    ConfidenceBreakdown,
    Proposal,
    ResolvedCitation,
)
from services import proposals as svc

PROPOSAL_KEYS = {
    "id", "run_id", "resource_type", "classification", "confidence_tier",
    "confidence_score", "status", "display_label", "flags", "conflict_group_id",
    "resource", "citations", "classification_reasoning", "extraction_reasoning",
    "merge_reasoning", "confidence_breakdown", "chart_matches", "supersedes",
    "reviewed_at", "reviewed_by", "rejection_reason", "provenance_resource",
    "write_result",
}


def _axis() -> ConfidenceAxis:
    return ConfidenceAxis(score=0.9, weight=0.5, contribution=0.45, reason="clear")


def _full_proposal() -> Proposal:
    return Proposal(
        id="prop_full",
        resource_type="Condition",
        resource={"resourceType": "Condition", "code": {"text": "Hypertension"}},
        classification="NEW",
        classification_reasoning="not in chart",
        extraction_reasoning="stated in note",
        merge_reasoning="single mention",
        citations=[ResolvedCitation(
            document_id="doc-1", sentence_numbers=[3], char_start=10, char_end=22, text="hypertension",
        )],
        chart_matches=[ChartMatch(resource_id="Condition/1", display="HTN", match_type="display_text")],
        confidence_score=0.9128,
        confidence_tier="CONFIDENT",
        flags=["dose-missing"],
        confidence_breakdown=ConfidenceBreakdown(certainty=_axis(), coding=_axis()),
        supersedes=["Condition/old"],
        conflict_group_id="grp-1",
    )


def _min_proposal() -> Proposal:
    return Proposal(
        id="prop_min",
        resource_type="MedicationRequest",
        resource={"resourceType": "MedicationRequest", "medicationCodeableConcept": {"text": "Losartan"}},
        classification="UPDATING",
        classification_reasoning="r",
        extraction_reasoning="e",
        citations=[],
        confidence_score=0.5,
        confidence_tier="REVIEW",
    )


def test_proposal_to_dict_shape_and_values():
    d = svc._proposal_to_dict(_full_proposal(), "run_abc")

    assert set(d.keys()) == PROPOSAL_KEYS
    assert d["id"] == "prop_full"
    assert d["run_id"] == "run_abc"
    assert d["status"] == "pending"
    assert d["confidence_score"] == 0.913  # rounded to 3 places, float
    assert isinstance(d["confidence_score"], float)
    assert d["display_label"] == "Hypertension"
    assert d["flags"] == ["dose-missing"]
    assert d["supersedes"] == ["Condition/old"]
    assert d["conflict_group_id"] == "grp-1"

    # nested models are JSON-dumped, not left as pydantic objects
    assert d["citations"] == [{
        "document_id": "doc-1", "sentence_numbers": [3],
        "char_start": 10, "char_end": 22, "text": "hypertension",
    }]
    assert d["chart_matches"][0]["resource_id"] == "Condition/1"
    assert d["confidence_breakdown"]["certainty"]["score"] == 0.9

    # a fresh proposal has no review/write state
    for k in ("reviewed_at", "reviewed_by", "rejection_reason", "provenance_resource", "write_result"):
        assert d[k] is None

    import json
    json.dumps(d)  # must be JSON-serializable for the MCP tool result


def test_proposal_to_dict_handles_empty_optionals():
    d = svc._proposal_to_dict(_min_proposal(), "run_x")
    assert set(d.keys()) == PROPOSAL_KEYS
    assert d["citations"] == []
    assert d["chart_matches"] == []
    assert d["confidence_breakdown"] is None
    assert d["merge_reasoning"] is None
    assert d["display_label"] == "Losartan"


def test_display_label_variants():
    bp = {
        "resourceType": "Observation",
        "code": {"text": "Blood pressure"},
        "component": [
            {"code": {"text": "Systolic"}, "valueQuantity": {"value": 140, "unit": "mmHg"}},
            {"code": {"text": "Diastolic"}, "valueQuantity": {"value": 90, "unit": "mmHg"}},
        ],
    }
    assert svc._display_label(bp) == "BP 140/90 mmHg"
    assert svc._display_label({"resourceType": "AllergyIntolerance", "code": {"text": "Penicillin"}}) == "Penicillin"
    assert svc._display_label({"resourceType": "Condition", "code": {"text": "Diabetes"}}) == "Diabetes"


def test_documents_from_notes_deterministic_ids():
    a = svc._documents_from_notes(["Patient reports chest pain."], "External record", "2026-01-01")
    b = svc._documents_from_notes(["Patient reports chest pain."], "External record", "2026-01-01")
    assert a[0].id == b[0].id
    assert a[0].id.startswith(svc.INLINE_DOC_PREFIX)

    with pytest.raises(ValueError):
        svc._documents_from_notes(["", "   "], "External record", None)


@pytest.mark.skipif(
    not os.environ.get("RUN_E2E"),
    reason="integration: set RUN_E2E=1 (uses .env OPENAI_API_KEY; hits OpenAI + terminology APIs)",
)
def test_run_extraction_ephemeral_demo():
    import asyncio

    from db import init_db

    stages: list[str] = []

    async def run():
        await init_db()

        async def progress_cb(stage, detail=None):
            stages.append(stage)

        return await svc.run_extraction_ephemeral(
            patient_id=None, fhir_client=None, progress_cb=progress_cb,
        )

    result = asyncio.run(run())

    assert result["run_id"].startswith("run_")
    assert result["proposals"], "demo bundle should yield proposals"
    for p in result["proposals"]:
        assert set(p.keys()) == PROPOSAL_KEYS
        assert p["status"] == "pending"
    assert "stage6_assemble" in stages
    assert result["stats"]["total_documents"] >= 1
