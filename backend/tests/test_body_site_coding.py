"""Phase 2 Part B: Condition.bodySite coded to SNOMED, gated on an active specialty IG."""
from __future__ import annotations

from core.augment.builders import build_fhir_resource
from core.code_candidates import _code_body_site, _extract_search_terms
from core.effective_profile import resolve_effective_profile
from core.schemas import MergedCandidate

SNOMED = "http://snomed.info/sct"
MCODE_PRESET = {"id": "p", "ig": {"base": "us-core@6.1.0", "specialty": "mcode@4.0.0"}}


def _mcode_eff():
    return resolve_effective_profile(MCODE_PRESET)


def test_gate_off_without_specialty():
    item = {"name": "carcinoma", "body_site": ["right breast"]}
    assert _code_body_site(resolve_effective_profile(None), "Condition", item) is False


def test_gate_off_without_body_site():
    assert _code_body_site(_mcode_eff(), "Condition", {"name": "carcinoma"}) is False


def test_gate_on_with_specialty_and_body_site():
    item = {"name": "carcinoma", "body_site": ["right breast"]}
    assert _code_body_site(_mcode_eff(), "Condition", item) is True


def test_body_site_terms_emitted_when_enabled():
    item = {"name": "carcinoma", "body_site": ["right breast", "axilla"]}
    terms = _extract_search_terms("Condition", item, ["snomed", "icd10"], code_body_site=True)
    assert terms[0][0] == "code"
    sites = [t for t in terms if t[0] == "body_site"]
    assert [t[1] for t in sites] == ["right breast", "axilla"]
    assert all(t[3] == ["snomed"] for t in sites)


def test_no_body_site_terms_when_disabled():
    item = {"name": "carcinoma", "body_site": ["right breast"]}
    terms = _extract_search_terms("Condition", item, ["snomed"], code_body_site=False)
    assert all(t[0] == "code" for t in terms)


def _candidate(item: dict) -> MergedCandidate:
    return MergedCandidate(resource_type="Condition", item=item, source_refs=[])


def test_builder_emits_coded_body_site():
    bs = {"system": SNOMED, "code": "76752008", "display": "Breast structure"}
    item = {"name": "carcinoma", "coding": [{"system": SNOMED, "code": "1", "display": "carcinoma"}],
            "body_site": ["right breast"], "body_site_coding": [bs]}
    res = build_fhir_resource(_candidate(item), "pt1", {})
    assert res["bodySite"] == [{"coding": [bs], "text": "right breast"}]


def test_builder_text_fallback_when_uncoded():
    item = {"name": "carcinoma", "coding": [{"system": SNOMED, "code": "1", "display": "x"}],
            "body_site": ["right breast"]}
    res = build_fhir_resource(_candidate(item), "pt1", {})
    assert res["bodySite"] == [{"text": "right breast"}]


def test_builder_partial_coding_alignment():
    bs = {"system": SNOMED, "code": "91723000", "display": "Anatomical structure"}
    item = {"name": "carcinoma", "coding": [{"system": SNOMED, "code": "1", "display": "x"}],
            "body_site": ["right breast", "axilla"], "body_site_coding": [bs, None]}
    res = build_fhir_resource(_candidate(item), "pt1", {})
    assert res["bodySite"] == [{"coding": [bs], "text": "right breast"}, {"text": "axilla"}]
