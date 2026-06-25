"""The catalog `fixed` roster must cover every code the pipeline pins, so the
read-only display + the codeset allow-list never miss a profile-fixed code."""
from core.code_candidates import US_CORE_FIXED
from core.ig_catalog import fixed_codings
from core.mcode_obs import MCODE_OBS, _TNM, _LOINC
from core.systems import SYSTEM_URIS, URI_TO_KEY


def _codes(entries):
    return {(e["system"], e["code"]) for e in entries}


def test_us_core_roster_covers_pipeline_fixed():
    roster = _codes(fixed_codings("us-core@6.1.0", None, "Observation"))
    for code, _display in US_CORE_FIXED.values():
        assert (SYSTEM_URIS["loinc"], code) in roster
    assert (SYSTEM_URIS["loinc"], "72166-2") in roster  # smoking status


def test_mcode_roster_covers_pipeline_fixed():
    roster = _codes(fixed_codings("us-core@6.1.0", "mcode@4.0.0", "Observation"))
    for e in MCODE_OBS:
        assert (e["system"], e["code"]) in roster
    for _letter, (_prof, clin, _path) in _TNM.items():
        assert (_LOINC, clin[0]) in roster


def test_fixed_systems_are_known():
    for e in fixed_codings("us-core@6.1.0", "mcode@4.0.0", "Observation"):
        assert e["system"] in URI_TO_KEY


def test_no_fixed_for_unbound_types():
    assert fixed_codings("us-core@6.1.0", "mcode@4.0.0", "Condition") == []
