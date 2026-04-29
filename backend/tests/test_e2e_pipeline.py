"""End-to-end pipeline test: stages 0 through 8 using the local demo bundle.

Module-scoped fixtures chain stage outputs. Each stage gets its own test
class. Stages 3-8 are stubs that skip until implemented.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.preprocess import PreprocessedNote, preprocess_documents
from core.extraction import StageTwoOutput
from core.schemas import RESOURCE_TYPES
from fhir.local_bundle import load_demo_data
from fhir.models import Document, PatientContext

STAGE2_OUTPUT_DIR = Path(__file__).resolve().parent.parent / ".cache" / "stage2_output"

DATE_TO_LOCAL_ID = {
    "2025-10": "cardio-consult-note",
    "2025-12": "ed-discharge-summary",
    "2026-02": "neuro-followup-note",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def stage0_output() -> tuple[PatientContext, list[Document]]:
    return load_demo_data()


@pytest.fixture(scope="module")
def patient_context(stage0_output) -> PatientContext:
    return stage0_output[0]


@pytest.fixture(scope="module")
def documents(stage0_output) -> list[Document]:
    return stage0_output[1]


@pytest.fixture(scope="module")
def stage1_output(documents) -> list[PreprocessedNote]:
    return preprocess_documents(documents)


@pytest.fixture(scope="module")
def stage2_output(stage1_output) -> list[StageTwoOutput]:
    if not STAGE2_OUTPUT_DIR.exists():
        pytest.skip("no stage2 cache present")

    outputs: list[StageTwoOutput] = []
    for path in sorted(STAGE2_OUTPUT_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        note_date = (data.get("note_context") or {}).get("note_date", {}).get("value", "")
        for prefix, local_id in DATE_TO_LOCAL_ID.items():
            if note_date.startswith(prefix):
                data["document_id"] = local_id
                break
        outputs.append(StageTwoOutput.from_json(data))

    if not outputs:
        pytest.skip("stage2 cache is empty")
    return outputs


@pytest.fixture(scope="module")
def stage3_output(stage2_output):
    return stage2_output


@pytest.fixture(scope="module")
def stage4_output(stage3_output):
    return stage3_output


@pytest.fixture(scope="module")
def stage5_output(stage4_output, patient_context):
    return stage4_output


@pytest.fixture(scope="module")
def stage6_output(stage5_output):
    return stage5_output


@pytest.fixture(scope="module")
def stage7_output(stage6_output):
    return stage6_output


@pytest.fixture(scope="module")
def stage8_proposals(stage6_output):
    return []


# ===================================================================
# Stage 0 — Chart Load
# ===================================================================

class TestStage0ChartLoad:

    def test_patient_identity(self, patient_context):
        p = patient_context.patient
        assert p.get("resourceType") == "Patient"
        names = p.get("name", [])
        assert any("Lee" in (n.get("family") or "") for n in names)

    def test_patient_demographics(self, patient_context):
        p = patient_context.patient
        assert p.get("birthDate") == "1958-11-15"
        assert p.get("gender") == "male"

    def test_conditions_count(self, patient_context):
        assert len(patient_context.conditions) == 4

    def test_conditions_include_expected(self, patient_context):
        displays = set()
        for c in patient_context.conditions:
            for coding in (c.get("code", {}).get("coding") or []):
                displays.add(coding.get("display", "").lower())
        for term in ("hypertension", "diabetes", "hyperlipidemia", "fatigue"):
            assert any(term in d for d in displays), f"missing condition: {term}"

    def test_medications_count(self, patient_context):
        assert len(patient_context.medications) == 4

    def test_medications_include_expected(self, patient_context):
        displays = set()
        for m in patient_context.medications:
            for coding in (m.get("medicationCodeableConcept", {}).get("coding") or []):
                displays.add(coding.get("display", "").lower())
        for drug in ("lisinopril", "atorvastatin", "metformin", "aspirin"):
            assert any(drug in d for d in displays), f"missing med: {drug}"

    def test_no_allergies_in_baseline(self, patient_context):
        assert len(patient_context.allergies) == 0

    def test_no_family_history_in_baseline(self, patient_context):
        assert len(patient_context.family_history) == 0

    def test_no_observations_in_baseline(self, patient_context):
        assert len(patient_context.observations) == 0

    def test_no_procedures_in_baseline(self, patient_context):
        assert len(patient_context.procedures) == 0

    def test_encounters_count(self, patient_context):
        assert len(patient_context.encounters) == 3

    def test_documents_count(self, documents):
        assert len(documents) == 3

    def test_documents_have_text(self, documents):
        for doc in documents:
            assert len(doc.text) > 500, f"doc {doc.id} text too short"

    def test_documents_have_metadata(self, documents):
        for doc in documents:
            assert doc.date, f"doc {doc.id} missing date"
            assert doc.author, f"doc {doc.id} missing author"
            assert doc.type, f"doc {doc.id} missing type"


# ===================================================================
# Stage 1 — Preprocess
# ===================================================================

class TestStage1Preprocess:

    def test_three_notes(self, stage1_output):
        assert len(stage1_output) == 3

    def test_sentences_count(self, stage1_output):
        for note in stage1_output:
            assert len(note.sentences) > 30, (
                f"{note.document_id} only has {len(note.sentences)} sentences"
            )

    def test_position_roundtrip(self, stage1_output):
        for note in stage1_output:
            for s in note.sentences:
                assert s.text == note.original_text[s.start:s.end], (
                    f"position mismatch in {note.document_id} sentence {s.number}"
                )

    def test_contiguous_numbering(self, stage1_output):
        for note in stage1_output:
            numbers = [s.number for s in note.sentences]
            assert numbers == list(range(1, len(note.sentences) + 1))

    def test_numbered_note_format(self, stage1_output):
        for note in stage1_output:
            lines = note.numbered_note.splitlines()
            assert len(lines) == len(note.sentences)
            for i, line in enumerate(lines):
                assert line.startswith(f"[{i + 1}] ")

    def test_document_dates_parsed(self, stage1_output):
        for note in stage1_output:
            assert note.document_date is not None, f"{note.document_id} has no date"

    def test_cardiology_has_catheterization(self, stage1_output):
        cardio = [n for n in stage1_output if "cardio" in n.document_id]
        assert len(cardio) == 1
        assert "catheterization" in cardio[0].original_text.lower()

    def test_ed_has_penicillin(self, stage1_output):
        ed = [n for n in stage1_output if "ed-" in n.document_id]
        assert len(ed) == 1
        assert "penicillin" in ed[0].original_text.lower()

    def test_neuro_has_smoking_and_family_history(self, stage1_output):
        neuro = [n for n in stage1_output if "neuro" in n.document_id]
        assert len(neuro) == 1
        text = neuro[0].original_text.lower()
        assert "pack-year" in text or "pack year" in text
        assert "father" in text


# ===================================================================
# Stage 2 — Extract Candidates (from cache)
# ===================================================================

class TestStage2ExtractCandidates:

    def test_three_outputs(self, stage2_output):
        assert len(stage2_output) == 3

    def test_note_context_present(self, stage2_output):
        for out in stage2_output:
            assert out.note_context is not None
            assert out.note_context.note_date.value is not None

    def test_valid_resource_types(self, stage2_output):
        for out in stage2_output:
            for rtype in out.candidates:
                assert rtype in RESOURCE_TYPES, f"unexpected type: {rtype}"

    def test_total_candidates_reasonable(self, stage2_output):
        total = sum(
            len(items) for out in stage2_output for items in out.candidates.values()
        )
        assert total > 20

    # --- 8 demo contract augmentations ---

    def _by_id(self, stage2_output, substring):
        matches = [o for o in stage2_output if substring in o.document_id]
        assert len(matches) == 1
        return matches[0]

    def test_cardio_angina(self, stage2_output):
        out = self._by_id(stage2_output, "cardio")
        names = [c.name.lower() for c in out.candidates.get("Condition", [])]
        assert any("angina" in n for n in names)

    def test_cardio_cad(self, stage2_output):
        out = self._by_id(stage2_output, "cardio")
        names = [c.name.lower() for c in out.candidates.get("Condition", [])]
        assert any("coronary" in n for n in names)

    def test_cardio_catheterization(self, stage2_output):
        out = self._by_id(stage2_output, "cardio")
        names = [p.name.lower() for p in out.candidates.get("Procedure", [])]
        assert any("catheter" in n for n in names)

    def test_cardio_metoprolol(self, stage2_output):
        out = self._by_id(stage2_output, "cardio")
        names = [m.name.lower() for m in out.candidates.get("MedicationRequest", [])]
        assert any("metoprolol" in n for n in names)

    def test_ed_penicillin(self, stage2_output):
        out = self._by_id(stage2_output, "ed-")
        substances = [a.substance.lower() for a in out.candidates.get("AllergyIntolerance", [])]
        assert any("penicillin" in s for s in substances)

    def test_neuro_lisinopril(self, stage2_output):
        out = self._by_id(stage2_output, "neuro")
        names = [m.name.lower() for m in out.candidates.get("MedicationRequest", [])]
        assert any("lisinopril" in n for n in names)

    def test_neuro_smoking(self, stage2_output):
        out = self._by_id(stage2_output, "neuro")
        texts = [
            f"{o.name.lower()} {o.value.lower()}"
            for o in out.candidates.get("Observation", [])
        ]
        assert any("tobacco" in t or "smok" in t for t in texts)

    def test_neuro_family_history(self, stage2_output):
        out = self._by_id(stage2_output, "neuro")
        fmh = out.candidates.get("FamilyMemberHistory", [])
        assert len(fmh) >= 1
        assert any("father" in f.relationship.lower() for f in fmh)

    def test_all_candidates_have_source_sentences(self, stage2_output):
        for out in stage2_output:
            for rtype, items in out.candidates.items():
                for item in items:
                    assert item.source_sentences, (
                        f"{out.document_id}/{rtype}: missing source_sentences"
                    )


# ===================================================================
# Stage 3 — Cross-note Dedupe (stub)
# ===================================================================

class TestStage3CrossNoteDedupe:

    @pytest.mark.skip(reason="Stage 3 not implemented")
    def test_duplicate_conditions_merged(self, stage3_output):
        pass

    @pytest.mark.skip(reason="Stage 3 not implemented")
    def test_merged_have_multiple_source_refs(self, stage3_output):
        pass


# ===================================================================
# Stage 4 — Terminology Coding (stub)
# ===================================================================

class TestStage4TerminologyCoding:

    @pytest.mark.skip(reason="Stage 4 not implemented")
    def test_conditions_have_snomed(self, stage4_output):
        pass

    @pytest.mark.skip(reason="Stage 4 not implemented")
    def test_medications_have_rxnorm(self, stage4_output):
        pass

    @pytest.mark.skip(reason="Stage 4 not implemented")
    def test_observations_have_loinc(self, stage4_output):
        pass


# ===================================================================
# Stage 5 — Classify vs Existing Chart (stub)
# ===================================================================

class TestStage5Classify:

    @pytest.mark.skip(reason="Stage 5 not implemented")
    def test_angina_new(self, stage5_output, patient_context):
        pass

    @pytest.mark.skip(reason="Stage 5 not implemented")
    def test_lisinopril_updating(self, stage5_output, patient_context):
        pass

    @pytest.mark.skip(reason="Stage 5 not implemented")
    def test_existing_conditions_duplicate(self, stage5_output, patient_context):
        pass


# ===================================================================
# Stage 6 — Assemble Proposal (stub)
# ===================================================================

class TestStage6AssembleProposal:

    @pytest.mark.skip(reason="Stage 6 not implemented")
    def test_eight_proposals(self, stage6_output):
        pass

    @pytest.mark.skip(reason="Stage 6 not implemented")
    def test_proposals_have_provenance(self, stage6_output):
        pass


# ===================================================================
# Stage 7 — Review MCP + REST (stub)
# ===================================================================

class TestStage7Review:

    @pytest.mark.skip(reason="Stage 7 not implemented")
    def test_list_proposals(self, stage7_output):
        pass

    @pytest.mark.skip(reason="Stage 7 not implemented")
    def test_accept_proposal(self, stage7_output):
        pass

    @pytest.mark.skip(reason="Stage 7 not implemented")
    def test_reject_proposal(self, stage7_output):
        pass


# ===================================================================
# Stage 8 — Write-back (stub)
# ===================================================================

class TestStage8WriteBack:

    @pytest.mark.skip(reason="Stage 8 needs mock FhirClient")
    def test_new_creates_resource_and_provenance(self, stage8_proposals):
        pass

    @pytest.mark.skip(reason="Stage 8 needs mock FhirClient")
    def test_provenance_has_source_span(self, stage8_proposals):
        pass
