"""End-to-end pipeline test: stages 0 through 8 using the local demo bundle.

Module-scoped fixtures chain stage outputs. Each stage gets its own test
class. Stages 3-8 are stubs that skip until implemented.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from core.preprocess import PreprocessedNote, preprocess_documents
from core.extraction import StageThreeOutput, StageTwoOutput, merge_across_notes
from core.code_candidates import StageFourOutput, code_candidates
from core.reconcile import StageFiveOutput, reconcile
from core.cache import JsonCache
from core.schemas import RESOURCE_TYPES, MergedCandidate
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
def stage3_output(stage2_output) -> StageThreeOutput:
    cache_dir = Path(__file__).resolve().parent.parent / ".cache" / "stage3"
    cache = JsonCache(cache_dir)
    key = "e2e_stage3"
    cached = cache.get(key)
    if cached is not None:
        try:
            return StageThreeOutput.from_json(cached)
        except Exception:
            pass

    from openai import AsyncOpenAI
    from config import Settings
    settings = Settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    result = asyncio.get_event_loop().run_until_complete(
        merge_across_notes(stage2_output, client, model=settings.openai_model_fast, cache=cache)
    )
    cache.put(key, result.to_json())
    return result


@pytest.fixture(scope="module")
def stage4_output(stage3_output) -> StageFourOutput:
    cache_dir = Path(__file__).resolve().parent.parent / ".cache" / "stage4"
    cache = JsonCache(cache_dir)
    key = "e2e_stage4"
    cached = cache.get(key)
    if cached is not None:
        try:
            return StageFourOutput.from_json(cached)
        except Exception:
            pass

    from openai import AsyncOpenAI
    from config import Settings
    settings = Settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    result = asyncio.get_event_loop().run_until_complete(
        code_candidates(stage3_output, client, model=settings.openai_model_fast)
    )
    cache.put(key, result.to_json())
    return result


@pytest.fixture(scope="module")
def stage5_output(stage4_output, patient_context):
    cache_dir = Path(__file__).resolve().parent.parent / ".cache" / "stage5"
    cache = JsonCache(cache_dir)
    key = "e2e_stage5"
    cached = cache.get(key)
    if cached is not None:
        try:
            return StageFiveOutput.from_json(cached)
        except Exception:
            pass

    from openai import AsyncOpenAI
    from config import Settings
    settings = Settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    result = asyncio.get_event_loop().run_until_complete(
        reconcile(stage4_output, patient_context, client, model=settings.openai_model_fast)
    )
    cache.put(key, result.to_json())
    return result


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

    def test_nkda_in_baseline(self, patient_context):
        assert len(patient_context.allergies) == 1
        nkda = patient_context.allergies[0]
        codes = [c["code"] for c in nkda.get("code", {}).get("coding", [])]
        assert "409137002" in codes

    def test_no_family_history_in_baseline(self, patient_context):
        assert len(patient_context.family_history) == 0

    def test_tobacco_observation_in_baseline(self, patient_context):
        assert len(patient_context.observations) == 1
        obs = patient_context.observations[0]
        codes = [c["code"] for c in obs.get("code", {}).get("coding", [])]
        assert "72166-2" in codes

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

    def test_output_type(self, stage3_output):
        assert isinstance(stage3_output, StageThreeOutput)
        assert len(stage3_output.candidates) > 0

    def test_fewer_than_stage2(self, stage2_output, stage3_output):
        s2_total = sum(
            len(items) for out in stage2_output for items in out.candidates.values()
        )
        assert len(stage3_output.candidates) < s2_total

    def test_all_have_source_refs(self, stage3_output):
        for c in stage3_output.candidates:
            assert c.source_refs, f"missing source_refs: {c.resource_type} {c.item.get('name', '?')}"
            for ref in c.source_refs:
                assert ref.document_id
                assert ref.source_sentences

    def test_valid_resource_types(self, stage3_output):
        for c in stage3_output.candidates:
            assert c.resource_type in RESOURCE_TYPES

    def _find(self, stage3_output, rtype, substring):
        return [
            c for c in stage3_output.candidates
            if c.resource_type == rtype
            and substring in (c.item.get("name") or c.item.get("substance") or c.item.get("relationship") or "").lower()
        ]

    def test_hypertension_merged(self, stage3_output):
        matches = self._find(stage3_output, "Condition", "hypertension")
        assert len(matches) == 1
        assert len(matches[0].source_refs) >= 2

    def test_t2dm_merged(self, stage3_output):
        matches = self._find(stage3_output, "Condition", "diabetes")
        assert len(matches) == 1
        assert len(matches[0].source_refs) >= 2

    def test_hyperlipidemia_merged(self, stage3_output):
        matches = self._find(stage3_output, "Condition", "hyperlipidemia")
        assert len(matches) == 1
        assert len(matches[0].source_refs) >= 2

    def test_penicillin_merged(self, stage3_output):
        matches = self._find(stage3_output, "AllergyIntolerance", "penicillin")
        assert len(matches) == 1
        assert len(matches[0].source_refs) >= 2

    def test_aspirin_merged(self, stage3_output):
        matches = self._find(stage3_output, "MedicationRequest", "aspirin")
        assert len(matches) == 1
        assert len(matches[0].source_refs) >= 2

    def test_different_bp_separate(self, stage3_output):
        bps = [
            c for c in stage3_output.candidates
            if c.resource_type == "Observation"
            and (c.item.get("name") or "").lower() == "bp"
        ]
        assert len(bps) >= 2

    def test_tobacco_statuses_separate(self, stage3_output):
        tobacco = [
            c for c in stage3_output.candidates
            if c.resource_type == "Observation"
            and "tobacco" in (c.item.get("name") or "").lower()
        ]
        assert len(tobacco) >= 2


# ===================================================================
# Stage 4 — Terminology Coding
# ===================================================================

class TestStage4TerminologyCoding:

    def test_output_type(self, stage4_output, stage3_output):
        assert isinstance(stage4_output, StageFourOutput)
        assert len(stage4_output.candidates) == len(stage3_output.candidates)

    def test_all_candidates_have_coding(self, stage4_output):
        for c in stage4_output.candidates:
            if c.resource_type == "FamilyMemberHistory":
                for cond in c.item.get("conditions") or []:
                    assert "coding" in cond, f"FMH condition missing coding: {cond}"
            else:
                assert "coding" in c.item, f"{c.resource_type} missing coding: {c.item.get('name')}"

    def test_coding_structure(self, stage4_output):
        for c in stage4_output.candidates:
            codings = c.item.get("coding") or []
            for entry in codings:
                assert "system" in entry or "text" in entry

    def test_conditions_have_codes(self, stage4_output):
        conditions = [c for c in stage4_output.candidates if c.resource_type == "Condition"]
        assert len(conditions) > 0
        coded = 0
        for cond in conditions:
            codings = cond.item.get("coding", [])
            has_real_code = any("code" in e for e in codings)
            if has_real_code:
                coded += 1
        assert coded >= len(conditions) - 1, f"Too many conditions without codes: {coded}/{len(conditions)}"

    def test_bp_has_fixed_loinc(self, stage4_output):
        bps = [
            c for c in stage4_output.candidates
            if c.resource_type == "Observation"
            and (c.item.get("name") or "").lower() in ("bp", "blood pressure")
        ]
        for bp in bps:
            codings = bp.item.get("coding", [])
            codes = {e.get("code") for e in codings}
            assert "85354-9" in codes, f"BP missing fixed LOINC 85354-9: {codings}"

    def test_tobacco_has_fixed_loinc(self, stage4_output):
        tobacco = [
            c for c in stage4_output.candidates
            if c.resource_type == "Observation"
            and "tobacco" in (c.item.get("name") or "").lower()
        ]
        assert len(tobacco) >= 1
        for t in tobacco:
            codings = t.item.get("coding", [])
            codes = {e.get("code") for e in codings}
            assert "72166-2" in codes, f"Tobacco missing fixed LOINC 72166-2: {codings}"

    def test_medications_have_rxnorm(self, stage4_output):
        meds = [c for c in stage4_output.candidates if c.resource_type == "MedicationRequest"]
        assert len(meds) > 0
        for med in meds:
            codings = med.item.get("coding", [])
            systems = {e.get("system") for e in codings if "system" in e}
            assert "http://www.nlm.nih.gov/research/umls/rxnorm" in systems or "text" in codings[0], \
                f"Med missing RxNorm: {med.item.get('name')}"

    def test_source_refs_preserved(self, stage4_output, stage3_output):
        for s4, s3 in zip(stage4_output.candidates, stage3_output.candidates):
            assert len(s4.source_refs) == len(s3.source_refs)


# ===================================================================
# Stage 5 — Reconcile vs Existing Chart
# ===================================================================

class TestStage5Reconcile:

    @staticmethod
    def _find(stage5_output, rtype, substring, field="name"):
        for r in stage5_output.results:
            if r.candidate.resource_type != rtype:
                continue
            val = r.candidate.item.get(field, "") or ""
            if substring.lower() in val.lower():
                return r
        return None

    def test_output_count(self, stage5_output, stage4_output):
        assert len(stage5_output.results) == len(stage4_output.candidates)

    def test_all_classified(self, stage5_output):
        for r in stage5_output.results:
            assert r.classification in ("NEW", "DUPLICATE", "UPDATING", "CONFLICTING")
            assert r.reasoning

    # -- DUPLICATE --

    def test_hypertension_duplicate(self, stage5_output):
        r = self._find(stage5_output, "Condition", "hypertension")
        assert r is not None, "hypertension candidate not found"
        assert r.classification == "DUPLICATE"

    def test_diabetes_duplicate(self, stage5_output):
        r = self._find(stage5_output, "Condition", "diabetes")
        assert r is not None, "diabetes candidate not found"
        assert r.classification == "DUPLICATE"

    def test_hyperlipidemia_duplicate(self, stage5_output):
        r = self._find(stage5_output, "Condition", "hyperlipidemia")
        assert r is not None, "hyperlipidemia candidate not found"
        assert r.classification == "DUPLICATE"

    def test_fatigue_duplicate(self, stage5_output):
        r = self._find(stage5_output, "Condition", "fatigue")
        assert r is not None, "fatigue candidate not found"
        assert r.classification == "DUPLICATE"

    def test_aspirin_duplicate(self, stage5_output):
        r = self._find(stage5_output, "MedicationRequest", "aspirin")
        assert r is not None, "aspirin candidate not found"
        assert r.classification == "DUPLICATE"

    def test_metformin_duplicate(self, stage5_output):
        r = self._find(stage5_output, "MedicationRequest", "metformin")
        assert r is not None, "metformin candidate not found"
        assert r.classification == "DUPLICATE"

    # -- UPDATING --

    def test_lisinopril_updating(self, stage5_output):
        r = self._find(stage5_output, "MedicationRequest", "lisinopril")
        assert r is not None, "lisinopril candidate not found"
        assert r.classification == "UPDATING"
        assert len(r.chart_matches) >= 1

    def test_tobacco_updating(self, stage5_output):
        for r in stage5_output.results:
            if r.candidate.resource_type != "Observation":
                continue
            codings = r.candidate.item.get("coding", [])
            loincs = [c.get("code") for c in codings if c.get("system") == "http://loinc.org"]
            val = (r.candidate.item.get("value") or "").lower()
            if "72166-2" in loincs and ("quit" in val or "former" in val or "cessation" in val or "tobacco-free" in val):
                assert r.classification == "UPDATING", f"tobacco cessation should be UPDATING, got {r.classification}"
                return
        pytest.skip("no tobacco cessation candidate found")

    # -- CONFLICTING --

    def test_penicillin_conflicting(self, stage5_output):
        r = self._find(stage5_output, "AllergyIntolerance", "penicillin", field="substance")
        assert r is not None, "penicillin candidate not found"
        assert r.classification == "CONFLICTING"

    def test_amoxicillin_conflicting(self, stage5_output):
        r = self._find(stage5_output, "AllergyIntolerance", "amoxicillin", field="substance")
        assert r is not None, "amoxicillin candidate not found"
        assert r.classification == "CONFLICTING"

    # -- NEW --

    def test_cad_new(self, stage5_output):
        r = self._find(stage5_output, "Condition", "coronary")
        assert r is not None, "CAD candidate not found"
        assert r.classification == "NEW"

    def test_angina_new(self, stage5_output):
        r = self._find(stage5_output, "Condition", "angina")
        assert r is not None, "angina candidate not found"
        assert r.classification == "NEW"

    def test_metoprolol_new(self, stage5_output):
        r = self._find(stage5_output, "MedicationRequest", "metoprolol")
        assert r is not None, "metoprolol candidate not found"
        assert r.classification == "NEW"

    def test_family_history_new(self, stage5_output):
        r = self._find(stage5_output, "FamilyMemberHistory", "father", field="relationship")
        assert r is not None, "father FMH candidate not found"
        assert r.classification == "NEW"

    def test_catheterization_new(self, stage5_output):
        r = self._find(stage5_output, "Procedure", "catheterization")
        assert r is not None, "catheterization candidate not found"
        assert r.classification == "NEW"

    # -- Provenance --

    def test_source_refs_preserved(self, stage5_output, stage4_output):
        for r, s4 in zip(stage5_output.results, stage4_output.candidates):
            assert len(r.candidate.source_refs) == len(s4.source_refs)


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
