"""Phase 2 Part B: Condition.bodySite coded to SNOMED, gated on an active specialty IG."""
from __future__ import annotations

from core.augment.builders import build_fhir_resource
from core.augment.mcode import apply_specialty_profiles
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


# -- Deterministic backstop: a metastasis is not located in the primary organ ----

_CONDITION_PROFILES = _mcode_eff().rule("Condition").candidate_profiles


def _secondary(body_site: list[str]) -> dict:
    return {
        "resourceType": "Condition",
        "code": {"text": "metastatic breast carcinoma"},
        "bodySite": [{"text": s} for s in body_site],
    }


def _apply(resource: dict, primary_sites: set[str]) -> dict:
    return apply_specialty_profiles(
        resource, "Condition", _CONDITION_PROFILES, {}, primary_sites, primary_sites
    )


def test_backstop_drops_primary_organ_on_metastasis():
    res = _apply(_secondary(["breast"]), {"breast"})
    assert "bodySite" not in res


def test_backstop_keeps_distinct_metastatic_site():
    res = _apply(_secondary(["L3 vertebra"]), {"breast"})
    assert [b["text"] for b in res["bodySite"]] == ["L3 vertebra"]


def test_backstop_keeps_when_any_site_is_distinct():
    res = _apply(_secondary(["right breast", "bone"]), {"breast"})
    assert {b["text"] for b in res["bodySite"]} == {"right breast", "bone"}


def test_backstop_skips_when_no_primary_known():
    res = _apply(_secondary(["breast"]), set())
    assert [b["text"] for b in res["bodySite"]] == ["breast"]


def test_backstop_leaves_primary_condition_untouched():
    primary = {
        "resourceType": "Condition",
        "code": {"text": "invasive ductal carcinoma"},
        "bodySite": [{"text": "right breast"}],
    }
    res = apply_specialty_profiles(primary, "Condition", _CONDITION_PROFILES, {}, {"breast"}, {"breast"})
    assert [b["text"] for b in res["bodySite"]] == ["right breast"]
