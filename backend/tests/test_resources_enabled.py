"""Stage 2b-2: a preset's disabled resource types are dropped from stage 2."""
from __future__ import annotations

from core.effective_profile import resolve_effective_profile
from core.extraction import StageTwoOutput
from core.schemas import NoteContext
from services.proposals import _filter_disabled_types


def _s2(types: list[str]) -> StageTwoOutput:
    return StageTwoOutput(document_id="d", note_context=NoteContext(),
                          candidates={t: ["item"] for t in types})


def test_no_op_when_all_enabled():
    out = _filter_disabled_types([_s2(["Condition", "Procedure", "Observation"])],
                                 resolve_effective_profile(None))
    assert set(out[0].candidates) == {"Condition", "Procedure", "Observation"}


def test_drops_disabled_type():
    eff = resolve_effective_profile({"id": "p", "resources": {"Procedure": {"enabled": False}}})
    out = _filter_disabled_types([_s2(["Condition", "Procedure", "Observation"])], eff)
    assert set(out[0].candidates) == {"Condition", "Observation"}


def test_multiple_disabled():
    eff = resolve_effective_profile({"id": "p", "resources": {
        "Procedure": {"enabled": False}, "AllergyIntolerance": {"enabled": False}}})
    out = _filter_disabled_types([_s2(["Condition", "Procedure", "AllergyIntolerance"])], eff)
    assert set(out[0].candidates) == {"Condition"}
