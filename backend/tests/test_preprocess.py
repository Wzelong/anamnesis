import pytest

from core.preprocess import build_numbered_note, split_sentences
from fhir.local_bundle import documents_from_bundle, load_bundle


def _load_demo_notes() -> list[tuple[str, str]]:
    bundle = load_bundle()
    return [(doc.id, doc.text) for doc in documents_from_bundle(bundle)]


def test_decimal_not_split():
    spans = split_sentences("BP 120.5/80. Next sentence.")
    assert len(spans) == 2
    assert "120.5" in spans[0].text


def test_abbreviation_not_split():
    spans = split_sentences("Seen by Dr. Smith. Plan follows.")
    assert len(spans) == 2
    assert "Dr. Smith" in spans[0].text


def test_numbered_list_preserved():
    spans = split_sentences("Plan: 1. Labs. 2. Imaging.")
    assert len(spans) == 1


def test_allcaps_header_split():
    spans = split_sentences("ASSESSMENT\nEpigastric pain.")
    assert len(spans) == 2
    assert spans[0].text == "ASSESSMENT"
    assert spans[1].text == "Epigastric pain."


def test_sentence_numbers_contiguous():
    spans = split_sentences(
        "First sentence. Second sentence. Third sentence.\n\nNew paragraph here."
    )
    assert [s.number for s in spans] == list(range(1, len(spans) + 1))


_DEMO_NOTES = _load_demo_notes()


@pytest.mark.parametrize(
    "doc_id,text",
    _DEMO_NOTES,
    ids=[n[0] for n in _DEMO_NOTES],
)
def test_positions_exact_roundtrip(doc_id: str, text: str):
    spans = split_sentences(text)
    assert spans, f"no sentences produced for {doc_id}"
    for s in spans:
        assert s.text == text[s.start:s.end], f"position mismatch in {doc_id} span {s.number}"


def test_numbered_note_format():
    spans = split_sentences("First sentence. Second sentence.")
    numbered = build_numbered_note(spans)
    assert numbered.splitlines()[0].startswith("[1] ")
    assert numbered.splitlines()[1].startswith("[2] ")
    assert len(numbered.splitlines()) == len(spans)


def test_empty_input():
    assert split_sentences("") == []
    assert build_numbered_note([]) == ""
