from core.extraction import _apply_cleaner, _build_snippet
from core.preprocess import SentenceSpan, split_sentences
from core.schemas import (
    CleanerResult,
    ConditionItem,
    DedupGroup,
    NoteContext,
    ScanResult,
)


def test_scan_result_defaults():
    sr = ScanResult()
    assert sr.condition == []
    assert sr.procedure == []
    assert sr.note_context.note_date.value is None


def test_scan_result_from_dict():
    sr = ScanResult.model_validate({
        "note_context": {
            "note_date": {"value": "2025-10-20", "source_sentences": [3]},
            "admission_date": {},
            "discharge_date": {},
        },
        "condition": [12, 15],
        "procedure": [[7, 8, 9]],
    })
    assert sr.note_context.note_date.value == "2025-10-20"
    assert sr.condition == [12, 15]
    assert sr.procedure == [[7, 8, 9]]


def _make_condition(idx: int, name: str, source_sentences=(1,)) -> ConditionItem:
    return ConditionItem(
        source_sentences=list(source_sentences),
        reasoning=f"item{idx}",
        category="diagnosis",
        name=name,
    )


def test_cleaner_discard():
    items = [_make_condition(1, "real"), _make_condition(2, "see above")]
    result = CleanerResult(discard=[2])
    survivors = _apply_cleaner(items, result)
    assert [s.name for s in survivors] == ["real"]


def test_cleaner_deduplicate_merges_source_sentences():
    items = [
        _make_condition(1, "Type 2 DM", source_sentences=[5]),
        _make_condition(2, "T2DM", source_sentences=[22]),
        _make_condition(3, "Type 2 Diabetes Mellitus", source_sentences=[40]),
    ]
    result = CleanerResult(deduplicate=[DedupGroup(group=[1, 2, 3], keep=3)])
    survivors = _apply_cleaner(items, result)
    assert len(survivors) == 1
    assert survivors[0].name == "Type 2 Diabetes Mellitus"
    assert survivors[0].source_sentences == [5, 22, 40]


def test_cleaner_invalid_indices_ignored():
    items = [_make_condition(1, "a"), _make_condition(2, "b")]
    result = CleanerResult(discard=[99], deduplicate=[DedupGroup(group=[5, 6], keep=5)])
    survivors = _apply_cleaner(items, result)
    assert len(survivors) == 2


def test_build_snippet_preserves_numbering():
    spans = [
        SentenceSpan(number=5, start=0, end=10, text="Start A."),
        SentenceSpan(number=8, start=20, end=30, text="Middle B."),
        SentenceSpan(number=22, start=40, end=55, text="End same dose."),
    ]
    by_number = {s.number: s for s in spans}
    snippet = _build_snippet([5, 22], by_number)
    assert snippet == "[5] Start A.\n[22] End same dose."


def test_build_snippet_skips_missing_numbers():
    spans = [SentenceSpan(number=3, start=0, end=8, text="Only one.")]
    by_number = {s.number: s for s in spans}
    snippet = _build_snippet([3, 99], by_number)
    assert snippet == "[3] Only one."


def test_condition_item_requires_category_and_name():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ConditionItem(source_sentences=[1], category="diagnosis")
