"""Stage 2 Pydantic schemas.

Every candidate carries `source_sentences` (the universal provenance
primitive) and `reasoning` (a short audit string from the model). No
nested StringWithSource unions — source tracking is at the item level.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

FHIR_DATE_PATTERN = r"^\d{4}(-\d{2}(-\d{2})?)?$"
FhirDate = Annotated[str, StringConstraints(pattern=FHIR_DATE_PATTERN)]


class _Strict(BaseModel):
    model_config = {"extra": "forbid"}


class DatedField(_Strict):
    value: FhirDate | None = None
    source_sentences: list[int] = Field(default_factory=list)


class NoteContext(_Strict):
    note_date: DatedField = Field(default_factory=DatedField)
    admission_date: DatedField = Field(default_factory=DatedField)
    discharge_date: DatedField = Field(default_factory=DatedField)


class ScanResult(_Strict):
    note_context: NoteContext = Field(default_factory=NoteContext)
    condition: list[int] = Field(default_factory=list)
    observation: list[int] = Field(default_factory=list)
    allergy_intolerance: list[int] = Field(default_factory=list)
    family_member_history: list[int] = Field(default_factory=list)
    procedure: list[list[int]] = Field(default_factory=list)
    medication_request: list[list[int]] = Field(default_factory=list)


Certainty = Literal["definite", "probable", "uncertain"]


class ConditionItem(_Strict):
    source_sentences: list[int]
    reasoning: str = ""
    certainty: Certainty = "probable"
    category: Literal["diagnosis", "problem"]
    name: str
    severity: Literal["mild", "moderate", "severe"] | None = None
    onset: str | None = None
    body_site: list[str] | None = None
    caused_by: list[str] = Field(default_factory=list)
    negated: bool = False


class ConditionItemList(_Strict):
    items: list[ConditionItem] = Field(default_factory=list)


class ObservationItem(_Strict):
    source_sentences: list[int]
    reasoning: str = ""
    certainty: Certainty = "probable"
    name: str
    full_name: str | None = None
    value: str
    unit: str | None = None
    codeset_hint: Literal["LOINC", "SNOMED"] | None = None
    effective_date: FhirDate | None = None
    category: Literal[
        "vital-signs", "laboratory", "social-history", "exam", "imaging", "survey"
    ] | None = None


class ObservationItemList(_Strict):
    items: list[ObservationItem] = Field(default_factory=list)


class MedicationDose(_Strict):
    value: str
    unit: str


class MedicationItem(_Strict):
    source_sentences: list[int]
    reasoning: str = ""
    certainty: Certainty = "probable"
    name: str
    status: Literal[
        "active", "on-hold", "cancelled", "completed", "stopped", "draft", "unknown"
    ]
    intent: Literal[
        "proposal", "plan", "order", "original-order", "instance-order"
    ]
    route: str | None = None
    frequency: str | None = None
    dose: MedicationDose | None = None
    reason: str | None = None


class MedicationItemList(_Strict):
    items: list[MedicationItem] = Field(default_factory=list)


class ProcedureItem(_Strict):
    source_sentences: list[int]
    reasoning: str = ""
    certainty: Certainty = "probable"
    name: str
    status: Literal[
        "preparation", "in-progress", "not-done", "on-hold",
        "stopped", "completed", "entered-in-error", "unknown",
    ]
    category: Literal["surgical", "diagnostic", "counselling", "education"] | None = None
    performed: FhirDate | None = None
    reason: str | None = None
    body_site: list[str] | None = None
    outcome: str | None = None


class ProcedureItemList(_Strict):
    items: list[ProcedureItem] = Field(default_factory=list)


class AllergyItem(_Strict):
    source_sentences: list[int]
    reasoning: str = ""
    certainty: Certainty = "probable"
    substance: str
    category: Literal["food", "medication", "environment", "biologic"] | None = None
    criticality: Literal["low", "high", "unable-to-assess"] | None = None
    reaction: str | None = None
    severity: Literal["mild", "moderate", "severe"] | None = None
    onset_age: str | None = None
    exposure_route: str | None = None
    verification: Literal[
        "unconfirmed", "confirmed", "refuted", "entered-in-error"
    ] | None = None


class AllergyItemList(_Strict):
    items: list[AllergyItem] = Field(default_factory=list)


class FamilyMemberCondition(_Strict):
    name: str
    onset_age: str | None = None
    outcome: str | None = None


class FamilyMemberHistoryItem(_Strict):
    source_sentences: list[int]
    reasoning: str = ""
    certainty: Certainty = "probable"
    relationship: str
    conditions: list[FamilyMemberCondition] = Field(default_factory=list)


class FamilyMemberHistoryItemList(_Strict):
    items: list[FamilyMemberHistoryItem] = Field(default_factory=list)


class DedupGroup(_Strict):
    group: list[int]
    keep: int


class CleanerResult(_Strict):
    discard: list[int] = Field(default_factory=list)
    deduplicate: list[DedupGroup] = Field(default_factory=list)


class SourceRef(_Strict):
    document_id: str
    source_sentences: list[int]


class ResolvedCitation(_Strict):
    document_id: str
    sentence_numbers: list[int]
    char_start: int
    char_end: int
    text: str


class MergedCandidate(_Strict):
    resource_type: str
    item: dict
    source_refs: list[SourceRef]
    encounter_key: str | None = None
    merge_reasoning: str | None = None


class CodeSelectorResult(_Strict):
    code: str | None = None
    refined_search_term: str | None = None


class MergeDecision(_Strict):
    action: Literal["merge", "reassign", "keep"]
    group_ids: list[int]
    survivor_group_id: int
    target_resource_type: str | None = None
    reasoning: str


class MergeAdjudicationResult(_Strict):
    decisions: list[MergeDecision] = Field(default_factory=list)


RESOURCE_TYPES: tuple[str, ...] = (
    "Condition",
    "Observation",
    "MedicationRequest",
    "Procedure",
    "AllergyIntolerance",
    "FamilyMemberHistory",
)

ITEM_LIST_MODELS: dict[str, type[BaseModel]] = {
    "Condition": ConditionItemList,
    "Observation": ObservationItemList,
    "MedicationRequest": MedicationItemList,
    "Procedure": ProcedureItemList,
    "AllergyIntolerance": AllergyItemList,
    "FamilyMemberHistory": FamilyMemberHistoryItemList,
}

ITEM_MODELS: dict[str, type[BaseModel]] = {
    "Condition": ConditionItem,
    "Observation": ObservationItem,
    "MedicationRequest": MedicationItem,
    "Procedure": ProcedureItem,
    "AllergyIntolerance": AllergyItem,
    "FamilyMemberHistory": FamilyMemberHistoryItem,
}


class ChartMatch(_Strict):
    resource_id: str
    display: str
    match_type: Literal["exact_code", "ingredient", "display_text"] = "exact_code"
    resource: dict | None = None


class ConfidenceAxis(_Strict):
    score: float
    weight: float
    contribution: float
    reason: str


class ConfidenceBreakdown(_Strict):
    certainty: ConfidenceAxis
    coding: ConfidenceAxis


class ReconciliationResult(_Strict):
    candidate: MergedCandidate
    classification: Literal["NEW", "DUPLICATE", "UPDATING", "CONFLICTING"]
    reasoning: str
    chart_matches: list[ChartMatch] = Field(default_factory=list)
    confidence_score: float = 0.5
    confidence_tier: Literal["CONFIDENT", "REVIEW", "ATTENTION"] = "REVIEW"
    flags: list[str] = Field(default_factory=list)
    confidence_breakdown: ConfidenceBreakdown | None = None


class LLMReconcileResult(_Strict):
    index: int
    classification: Literal["NEW", "DUPLICATE", "UPDATING", "CONFLICTING"]
    reasoning: str


class LLMReconcileBatchResult(_Strict):
    decisions: list[LLMReconcileResult] = Field(default_factory=list)


class Proposal(_Strict):
    id: str
    resource_type: str
    resource: dict
    classification: Literal["NEW", "UPDATING", "CONFLICTING"]
    classification_reasoning: str
    extraction_reasoning: str
    merge_reasoning: str | None = None
    citations: list[ResolvedCitation]
    chart_matches: list[ChartMatch] = Field(default_factory=list)
    confidence_score: float
    confidence_tier: Literal["CONFIDENT", "REVIEW", "ATTENTION"]
    flags: list[str] = Field(default_factory=list)
    confidence_breakdown: ConfidenceBreakdown | None = None
    supersedes: list[str] = Field(default_factory=list)
