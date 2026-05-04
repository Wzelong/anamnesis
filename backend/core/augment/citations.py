"""Citation resolution and encounter mapping for Stage 6 assembly."""
from __future__ import annotations

import logging

from core.preprocess import PreprocessedNote
from core.schemas import ResolvedCitation, SourceRef
from fhir.models import PatientContext

log = logging.getLogger(__name__)


def _build_encounter_map(
    patient_context: PatientContext,
    notes: list[PreprocessedNote],
) -> dict[str, str]:
    enc_ids = {e["id"] for e in patient_context.encounters if "id" in e}
    enc_map: dict[str, str] = {}
    for note in notes:
        if note.encounter_id and note.document_id:
            for eid in enc_ids:
                if eid in note.document_id or note.document_id.replace("-note", "").replace("-summary", "") == eid:
                    enc_map[note.encounter_id] = f"Encounter/{eid}"
                    break
            if note.encounter_id not in enc_map:
                for e in patient_context.encounters:
                    enc_map.setdefault(note.encounter_id, f"Encounter/{e['id']}")
    return enc_map


def _resolve_encounter(key: str | None, enc_map: dict[str, str]) -> str | None:
    if not key:
        return None
    if key.startswith("Encounter/"):
        return key
    return enc_map.get(key)


def resolve_citations(
    source_refs: list[SourceRef],
    notes_by_doc_id: dict[str, PreprocessedNote],
) -> list[ResolvedCitation]:
    """Convert sentence-number citations into character-span citations.

    Each `SourceRef` carries the sentence numbers that supported a candidate.
    This walks the preprocessed sentence positions, merges contiguous runs
    (e.g. sentences [12, 13, 14] -> one citation spanning all three), and
    splits non-contiguous runs into multiple citations. The resulting char
    spans are byte-exact offsets into `note.original_text` so the UI can
    highlight in place and Stage 8 Provenance can record an unambiguous
    `source-text-span` extension.
    """
    citations: list[ResolvedCitation] = []
    for ref in source_refs:
        note = notes_by_doc_id.get(ref.document_id)
        if not note:
            log.warning("document_id %s not found in preprocessed notes", ref.document_id)
            continue
        span_map = {s.number: s for s in note.sentences}
        valid = sorted(n for n in ref.source_sentences if n in span_map)
        if not valid:
            continue
        runs: list[list[int]] = []
        current_run: list[int] = [valid[0]]
        for i in range(1, len(valid)):
            if valid[i] == current_run[-1] + 1:
                current_run.append(valid[i])
            else:
                runs.append(current_run)
                current_run = [valid[i]]
        runs.append(current_run)

        for run in runs:
            start = span_map[run[0]].start
            end = span_map[run[-1]].end
            citations.append(ResolvedCitation(
                document_id=ref.document_id,
                sentence_numbers=run,
                char_start=start,
                char_end=end,
                text=note.original_text[start:end],
            ))
    return citations
