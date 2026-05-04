"""Stage 6 entry point: turn reconciled candidates into clinician-reviewable proposals."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from core.augment.builders import build_fhir_resource
from core.augment.citations import _build_encounter_map, resolve_citations
from core.augment.helpers import _is_negated_assertion
from core.ids import short_id
from core.preprocess import PreprocessedNote
from core.reconcile import StageFiveOutput
from core.schemas import Proposal
from fhir.models import PatientContext

log = logging.getLogger(__name__)


@dataclass
class StageSixOutput:
    proposals: list[Proposal] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"proposals": [p.model_dump(mode="json") for p in self.proposals]}

    @classmethod
    def from_json(cls, data: dict) -> StageSixOutput:
        return cls(
            proposals=[Proposal.model_validate(p) for p in data["proposals"]],
        )


def assemble_proposals(
    stage5: StageFiveOutput,
    notes: list[PreprocessedNote],
    patient_context: PatientContext,
) -> StageSixOutput:
    """Stage 6: turn reconciled candidates into clinician-reviewable Proposal records.

    Three jobs, all deterministic — no LLM calls, no I/O:
      1. **Filter.** Drop DUPLICATEs (already in chart) and any NEW candidate
         flagged as a negated assertion (e.g. "denies chest pain").
      2. **Build FHIR resources.** Dispatch via `build_fhir_resource` into
         the per-type builders; the result conforms to US Core R4 where a
         profile exists.
      3. **Resolve citations.** Sentence numbers become byte-exact
         char spans on `note.original_text` via `resolve_citations`, then
         the proposal carries the chart-match refs and the confidence
         breakdown forwarded from Stage 5.

    Output is a list of `Proposal` records ready for the review surface.
    No FHIR write happens here — Stage 8 fires only on accept.
    """
    notes_by_doc = {n.document_id: n for n in notes}
    patient_id = patient_context.patient["id"]
    enc_map = _build_encounter_map(patient_context, notes)

    doc_dates: dict[str, str] = {}
    for note in notes:
        if note.document_date:
            doc_dates[note.document_id] = note.document_date.strftime("%Y-%m-%d")

    proposals: list[Proposal] = []
    for result in stage5.results:
        if result.classification == "DUPLICATE":
            continue
        if result.classification == "NEW" and _is_negated_assertion(result.candidate):
            continue
        note_date = None
        for sr in result.candidate.source_refs:
            note_date = doc_dates.get(sr.document_id)
            if note_date:
                break
        resource = build_fhir_resource(result.candidate, patient_id, enc_map, note_date=note_date)
        citations = resolve_citations(result.candidate.source_refs, notes_by_doc)
        supersedes = (
            [m.resource_id for m in result.chart_matches]
            if result.classification == "UPDATING" else []
        )
        proposals.append(Proposal(
            id=short_id("prop"),
            resource_type=result.candidate.resource_type,
            resource=resource,
            classification=result.classification,
            classification_reasoning=result.reasoning,
            extraction_reasoning=result.candidate.item.get("reasoning", ""),
            merge_reasoning=result.candidate.merge_reasoning,
            citations=citations,
            chart_matches=result.chart_matches,
            confidence_score=result.confidence_score,
            confidence_tier=result.confidence_tier,
            flags=result.flags,
            confidence_breakdown=result.confidence_breakdown,
            supersedes=supersedes,
        ))

    by_class = {}
    for p in proposals:
        by_class[p.classification] = by_class.get(p.classification, 0) + 1
    log.info("stage6 assembled %d proposals: %s", len(proposals), by_class)
    return StageSixOutput(proposals=proposals)
