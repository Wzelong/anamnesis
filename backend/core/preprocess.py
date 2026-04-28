"""Stage 1: position-preserving sentence splitter for clinical notes.

Pure/deterministic, no I/O. Splitter rules adapted from text2fhir's
`_preprocessing.py` but rewritten to emit exact character offsets in the
original text so downstream stages can cite byte-accurate source spans.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from fhir.models import Document


PROTECTED_ABBR: tuple[str, ...] = (
    "Dr", "Mr", "Mrs", "Ms", "Prof", "Rev",
    "MD", "PhD", "DO", "DDS", "RN", "NP", "PA", "MA", "MS", "BSN", "MPH",
    "No", "Pt", "St", "Ave", "Blvd", "Dept", "Fig", "Inc", "Ltd", "Corp",
    "vs", "etc", "ie", "eg", "et al",
    "qd", "q.d", "qhs", "q.h.s", "bid", "b.i.d", "tid", "t.i.d", "qid", "q.i.d",
    "prn", "p.r.n", "qam", "qpm", "qod", "q.o.d",
)

ROMAN_PREV: dict[str, str] = {
    "ii": "i", "iii": "ii", "iv": "iii", "v": "iv", "vi": "v",
    "vii": "vi", "viii": "vii", "ix": "viii", "x": "ix",
    "xi": "x", "xii": "xi", "xiii": "xii", "xiv": "xiii", "xv": "xiv",
    "xvi": "xv", "xvii": "xvi", "xviii": "xvii", "xix": "xviii", "xx": "xix",
}

MARKER_PATTERNS: tuple[str, ...] = (
    r"(\d+)\.",
    r"([a-z])[.)]",
    r"([A-Z])[.)]",
    r"(i{1,3}|iv|v|vi{0,3}|ix|x)\.",
)

SPLIT_PATTERN = re.compile(
    r"(?:\.\s+(?=[A-Z])|\.\n|(?<!:)\n(?=[A-Z][a-z])|(?<!:)\n(?=[A-Z]{2,}(?:\s|$))|\n(?=\|))"
)

_ROMAN_SET = frozenset(ROMAN_PREV.keys()) | frozenset(ROMAN_PREV.values())


@dataclass(frozen=True)
class SentenceSpan:
    number: int
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class PreprocessedNote:
    document_id: str
    document_date: datetime | None
    original_text: str
    sentences: tuple[SentenceSpan, ...]
    numbered_note: str


def _is_list_marker(s: str) -> bool:
    if s.isdigit():
        return True
    if len(s) == 1 and s.isalpha():
        return True
    return s.lower() in _ROMAN_SET


def _previous_marker(marker: str) -> str | None:
    if marker.isdigit():
        n = int(marker)
        return str(n - 1) if n > 1 else None
    if len(marker) == 1 and marker.isalpha():
        if marker in ("a", "A"):
            return None
        return chr(ord(marker) - 1)
    return ROMAN_PREV.get(marker.lower())


def _protected_list_positions(text: str) -> set[int]:
    protected: set[int] = set()
    for pat in MARKER_PATTERNS:
        matches = list(re.finditer(pat, text))
        for i in range(len(matches) - 1):
            curr, nxt = matches[i], matches[i + 1]
            if nxt.start() - curr.end() > 200:
                continue
            if _previous_marker(nxt.group(1)) == curr.group(1):
                protected.add(curr.end() - 1)
                protected.add(nxt.end() - 1)
    return protected


def _is_protected_split(text: str, start: int, protected: set[int]) -> bool:
    if start in protected:
        return True

    ch = text[start]

    if ch == ".":
        if start > 0 and start + 1 < len(text) and text[start - 1].isdigit() and text[start + 1].isdigit():
            return True
        if start + 1 < len(text) and text[start + 1] == ".":
            return True
        if start > 0 and text[start - 1] == ".":
            return True
        if start > 0 and text[start - 1].isupper():
            if start == 1 or text[start - 2] in " \n\t,:()[]":
                return True
        if start > 0:
            marker_end = start - 1
            marker_start = marker_end
            while marker_start > 0 and text[marker_start - 1] != "\n":
                marker_start -= 1
            marker = text[marker_start:marker_end + 1]
            if _is_list_marker(marker) and (marker_start == 0 or text[marker_start - 1] == "\n"):
                return True

    for abbr in PROTECTED_ABBR:
        n = len(abbr)
        if start < n:
            continue
        if text[start - n:start].lower() != abbr.lower():
            continue
        if start == n or text[start - n - 1] in " \n\t":
            return True

    return False


def _emit_span(text: str, start: int, end: int, number: int) -> SentenceSpan | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if end <= start:
        return None
    return SentenceSpan(number=number, start=start, end=end, text=text[start:end])


def split_sentences(text: str) -> list[SentenceSpan]:
    if not text:
        return []

    protected = _protected_list_positions(text)
    valid_ends: list[tuple[int, int]] = []
    for m in SPLIT_PATTERN.finditer(text):
        if _is_protected_split(text, m.start(), protected):
            continue
        sentence_end = m.start() + 1 if text[m.start()] == "." else m.start()
        next_start = m.end()
        valid_ends.append((sentence_end, next_start))

    spans: list[SentenceSpan] = []
    cursor = 0
    number = 1
    for sentence_end, next_start in valid_ends:
        span = _emit_span(text, cursor, sentence_end, number)
        if span is not None:
            if span.text != text[span.start:span.end]:
                raise RuntimeError("splitter position invariant violated")
            spans.append(span)
            number += 1
        cursor = next_start

    tail = _emit_span(text, cursor, len(text), number)
    if tail is not None:
        if tail.text != text[tail.start:tail.end]:
            raise RuntimeError("splitter position invariant violated")
        spans.append(tail)

    return spans


def build_numbered_note(spans: list[SentenceSpan]) -> str:
    lines = []
    for s in spans:
        display = re.sub(r"\s+", " ", s.text).strip()
        lines.append(f"[{s.number}] {display}")
    return "\n".join(lines)


def _parse_document_date(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def preprocess_document(doc: Document) -> PreprocessedNote:
    sentences = split_sentences(doc.text)
    return PreprocessedNote(
        document_id=doc.id,
        document_date=_parse_document_date(doc.date),
        original_text=doc.text,
        sentences=tuple(sentences),
        numbered_note=build_numbered_note(sentences),
    )


def preprocess_documents(docs: list[Document]) -> list[PreprocessedNote]:
    return [preprocess_document(d) for d in docs]
