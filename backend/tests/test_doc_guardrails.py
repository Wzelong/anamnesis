from core.doc_guardrails import (
    MAX_BYTES,
    MIN_PRINTABLE_RATIO,
    RejectedDocument,
    deterministic_check,
)
from fhir.models import Document


def _doc(text: str, doc_id: str = "doc-1") -> Document:
    return Document(id=doc_id, type="Progress note", date="2026-04-01", author="t", text=text, encounter_id=None)


def test_accepts_normal_clinical_text():
    assert deterministic_check(_doc("Pt with HTN, on lisinopril 10 mg daily.")) is None


def test_rejects_empty():
    r = deterministic_check(_doc(""))
    assert isinstance(r, RejectedDocument) and r.reason == "empty"


def test_rejects_whitespace_only():
    r = deterministic_check(_doc("  \n\t\r\n   "))
    assert isinstance(r, RejectedDocument) and r.reason == "empty"


def test_rejects_oversized():
    r = deterministic_check(_doc("a" * (MAX_BYTES + 1)))
    assert isinstance(r, RejectedDocument) and r.reason == "too_large"


def test_accepts_at_size_limit():
    assert deterministic_check(_doc("a" * MAX_BYTES)) is None


def test_rejects_low_printable_ratio():
    payload = "\x00\x01\x02\x03\x04\x05\x06\x07" * 100 + "valid"
    r = deterministic_check(_doc(payload))
    assert isinstance(r, RejectedDocument) and r.reason == "non_text"


def test_accepts_at_printable_threshold():
    text = "a" * int(100 * MIN_PRINTABLE_RATIO) + "\x00" * (100 - int(100 * MIN_PRINTABLE_RATIO))
    assert deterministic_check(_doc(text)) is None
