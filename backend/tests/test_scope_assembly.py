"""Integration: a preset value-set scope drops out-of-set resources at assembly (Stage 6)."""
from core.augment.assembly import assemble_proposals
from core.effective_profile import resolve_effective_profile
from core.reconcile import StageFiveOutput
from core.schemas import MergedCandidate, ReconciliationResult
from fhir.models import PatientContext

SNOMED = "http://snomed.info/sct"
ICD10 = "http://hl7.org/fhir/sid/icd-10-cm"


def _result(name, system, code):
    cand = MergedCandidate(
        resource_type="Condition",
        item={"name": name, "coding": [{"system": system, "code": code, "display": name}], "certainty": "definite"},
        source_refs=[],
    )
    return ReconciliationResult(candidate=cand, classification="NEW", reasoning="x")


def _stage5():
    return StageFiveOutput(results=[
        _result("Diabetes", SNOMED, "44054006"),
        _result("Hypertension", ICD10, "I10"),
    ])


def _ctx():
    return PatientContext(patient={"id": "p1"})


def _codes(out):
    return [p.resource["code"]["coding"][0]["code"] for p in out.proposals]


def _preset(coding):
    return {"id": "p", "ig": {"base": "us-core@6.1.0", "specialty": None}, "coding": coding}


def test_legacy_subset_migrates_to_pinned_restrict():
    eff = resolve_effective_profile(_preset({"Condition": {"subset": [{"system": SNOMED, "code": "44054006"}]}}))
    rule = eff.rule("Condition")
    assert rule.pinned == [{"system": SNOMED, "code": "44054006"}]
    assert rule.coding_systems == []  # restrict: no open system


def test_restrict_drops_out_of_set():
    eff = resolve_effective_profile(_preset({"Condition": {"systems": [], "codes": [{"system": SNOMED, "code": "44054006"}]}}))
    out = assemble_proposals(_stage5(), [], _ctx(), effective=eff)
    assert _codes(out) == ["44054006"]  # Hypertension (ICD-10 I10) not open, not pinned -> dropped


def test_extend_keeps_open_plus_pinned():
    eff = resolve_effective_profile(_preset({"Condition": {"systems": ["snomed", "icd10"], "codes": [{"system": SNOMED, "code": "44054006"}]}}))
    out = assemble_proposals(_stage5(), [], _ctx(), effective=eff)
    assert sorted(_codes(out)) == ["44054006", "I10"]  # both systems open -> nothing dropped


def test_no_codeset_keeps_all():
    eff = resolve_effective_profile(_preset({}))
    out = assemble_proposals(_stage5(), [], _ctx(), effective=eff)
    assert sorted(_codes(out)) == ["44054006", "I10"]


def test_no_effective_keeps_all():
    out = assemble_proposals(_stage5(), [], _ctx(), effective=None)
    assert sorted(_codes(out)) == ["44054006", "I10"]
