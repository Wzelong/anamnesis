"""Stage 6: assemble augmentation proposals with valid FHIR R4 resources."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from uuid import uuid4

from core.preprocess import PreprocessedNote
from core.reconcile import StageFiveOutput
from core.schemas import ChartMatch, MergedCandidate, Proposal, ResolvedCitation, SourceRef
from fhir.models import PatientContext

log = logging.getLogger(__name__)

_BP_LOINC = "85354-9"
_TOBACCO_LOINC = "72166-2"
_NUM_RE = re.compile(r"^[<>≤≥]?\s*[\d.]+$")
_BP_RE = re.compile(r"(\d+)\s*/\s*(\d+)")
_AGE_RE = re.compile(r"(\d+)")

US_CORE_PROFILES: dict[str, str] = {
    "Condition": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-condition-problems-health-concerns",
    "MedicationRequest": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-medicationrequest",
    "Procedure": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-procedure",
    "AllergyIntolerance": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-allergyintolerance",
}

OBS_PROFILES: dict[str, str] = {
    "vital-signs": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-vital-signs",
    "laboratory": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-observation-lab",
    "social-history": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-smokingstatus",
}

CERTAINTY_TO_VERIFICATION: dict[str, str] = {
    "definite": "confirmed",
    "probable": "provisional",
    "uncertain": "unconfirmed",
}

CONDITION_CATEGORY_MAP: dict[str, str] = {
    "diagnosis": "encounter-diagnosis",
    "problem": "problem-list-item",
}

_COND_CLINICAL_SYSTEM = "http://terminology.hl7.org/CodeSystem/condition-clinical"
_COND_VERIFY_SYSTEM = "http://terminology.hl7.org/CodeSystem/condition-ver-status"
_COND_CATEGORY_SYSTEM = "http://terminology.hl7.org/CodeSystem/condition-category"
_OBS_CATEGORY_SYSTEM = "http://terminology.hl7.org/CodeSystem/observation-category"
_ALLERGY_CLINICAL_SYSTEM = "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical"
_ALLERGY_VERIFY_SYSTEM = "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_none(d: dict | list) -> dict | list:
    if isinstance(d, list):
        return [_strip_none(v) for v in d if v is not None]
    if not isinstance(d, dict):
        return d
    out = {}
    for k, v in d.items():
        if v is None:
            continue
        if isinstance(v, dict):
            v = _strip_none(v)
            if not v:
                continue
        elif isinstance(v, list):
            v = _strip_none(v)
            if not v:
                continue
        out[k] = v
    return out


def _cc(coding: list[dict], text: str) -> dict:
    return {"coding": coding, "text": text}


def _verification_status(certainty: str, system: str) -> dict:
    code = CERTAINTY_TO_VERIFICATION.get(certainty, "provisional")
    return {"coding": [{"system": system, "code": code}]}


def _parse_bp(value_str: str) -> tuple[int, int] | None:
    m = _BP_RE.search(value_str)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _parse_onset_age(s: str) -> int | None:
    m = _AGE_RE.search(s)
    return int(m.group(1)) if m else None


def _is_numeric(v: str) -> bool:
    return bool(_NUM_RE.match(v.strip()))


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


# ---------------------------------------------------------------------------
# FHIR resource builders
# ---------------------------------------------------------------------------

def _build_condition(item: dict, patient_id: str, encounter_ref: str | None) -> dict:
    cat_code = CONDITION_CATEGORY_MAP.get(item.get("category", ""), "problem-list-item")
    resource: dict = {
        "resourceType": "Condition",
        "meta": {"profile": [US_CORE_PROFILES["Condition"]]},
        "clinicalStatus": {"coding": [{"system": _COND_CLINICAL_SYSTEM, "code": "active"}]},
        "verificationStatus": _verification_status(item.get("certainty", "probable"), _COND_VERIFY_SYSTEM),
        "category": [{"coding": [{"system": _COND_CATEGORY_SYSTEM, "code": cat_code}]}],
        "code": _cc(item.get("coding", []), item.get("name", "")),
        "subject": {"reference": f"Patient/{patient_id}"},
    }
    if item.get("onset"):
        resource["onsetDateTime"] = item["onset"]
    if item.get("severity"):
        resource["severity"] = {"text": item["severity"]}
    if item.get("body_site"):
        resource["bodySite"] = [{"text": s} for s in item["body_site"]]
    if encounter_ref:
        resource["encounter"] = {"reference": encounter_ref}
    return _strip_none(resource)


def _build_observation(item: dict, patient_id: str, encounter_ref: str | None) -> dict:
    cat = item.get("category", "exam")
    profile = OBS_PROFILES.get(cat)

    codings = item.get("coding", [])
    loinc_codes = [c.get("code") for c in codings if c.get("system") == "http://loinc.org"]

    if _TOBACCO_LOINC in loinc_codes:
        profile = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-smokingstatus"

    resource: dict = {
        "resourceType": "Observation",
        "status": "final",
        "category": [{"coding": [{"system": _OBS_CATEGORY_SYSTEM, "code": cat}]}],
        "code": _cc(codings, item.get("full_name") or item.get("name", "")),
        "subject": {"reference": f"Patient/{patient_id}"},
    }
    if profile:
        resource["meta"] = {"profile": [profile]}

    value_str = item.get("value", "")
    unit = item.get("unit")

    if _BP_LOINC in loinc_codes:
        bp = _parse_bp(value_str)
        if bp:
            resource["component"] = [
                {
                    "code": {"coding": [{"system": "http://loinc.org", "code": "8480-6", "display": "Systolic blood pressure"}]},
                    "valueQuantity": {"value": bp[0], "unit": "mmHg", "system": "http://unitsofmeasure.org", "code": "mm[Hg]"},
                },
                {
                    "code": {"coding": [{"system": "http://loinc.org", "code": "8462-4", "display": "Diastolic blood pressure"}]},
                    "valueQuantity": {"value": bp[1], "unit": "mmHg", "system": "http://unitsofmeasure.org", "code": "mm[Hg]"},
                },
            ]
        else:
            resource["valueString"] = value_str
    elif _TOBACCO_LOINC in loinc_codes or cat == "social-history":
        resource["valueCodeableConcept"] = {"text": value_str}
    elif unit and _is_numeric(value_str):
        try:
            resource["valueQuantity"] = {"value": float(value_str.strip().lstrip("<>≤≥ ")), "unit": unit}
        except ValueError:
            resource["valueString"] = f"{value_str} {unit}".strip()
    else:
        resource["valueString"] = value_str

    if item.get("effective_date"):
        resource["effectiveDateTime"] = item["effective_date"]
    if encounter_ref:
        resource["encounter"] = {"reference": encounter_ref}
    return _strip_none(resource)


def _build_medication_request(item: dict, patient_id: str, encounter_ref: str | None) -> dict:
    resource: dict = {
        "resourceType": "MedicationRequest",
        "meta": {"profile": [US_CORE_PROFILES["MedicationRequest"]]},
        "status": item.get("status", "active"),
        "intent": item.get("intent", "order"),
        "medicationCodeableConcept": _cc(item.get("coding", []), item.get("name", "")),
        "subject": {"reference": f"Patient/{patient_id}"},
    }

    dose = item.get("dose")
    route = item.get("route")
    frequency = item.get("frequency")
    if dose or route or frequency:
        parts = []
        dosage: dict = {}
        if dose and isinstance(dose, dict):
            parts.append(f"{dose.get('value', '')} {dose.get('unit', '')}".strip())
            try:
                dosage["doseAndRate"] = [{"doseQuantity": {"value": float(dose["value"]), "unit": dose.get("unit", "")}}]
            except (ValueError, KeyError):
                pass
        if route:
            parts.append(route)
        if frequency:
            parts.append(frequency)
        dosage["text"] = " ".join(parts)
        resource["dosageInstruction"] = [dosage]

    if item.get("reason"):
        resource["reasonCode"] = [{"text": item["reason"]}]
    if encounter_ref:
        resource["encounter"] = {"reference": encounter_ref}
    return _strip_none(resource)


def _build_procedure(item: dict, patient_id: str, encounter_ref: str | None) -> dict:
    resource: dict = {
        "resourceType": "Procedure",
        "meta": {"profile": [US_CORE_PROFILES["Procedure"]]},
        "status": item.get("status", "completed"),
        "code": _cc(item.get("coding", []), item.get("name", "")),
        "subject": {"reference": f"Patient/{patient_id}"},
    }
    if item.get("performed"):
        resource["performedDateTime"] = item["performed"]
    if item.get("body_site"):
        resource["bodySite"] = [{"text": s} for s in item["body_site"]]
    if item.get("reason"):
        resource["reasonCode"] = [{"text": item["reason"]}]
    if item.get("outcome"):
        resource["outcome"] = {"text": item["outcome"]}
    if encounter_ref:
        resource["encounter"] = {"reference": encounter_ref}
    return _strip_none(resource)


def _build_allergy_intolerance(item: dict, patient_id: str) -> dict:
    verification = item.get("verification")
    if verification:
        verify_code = verification
    else:
        verify_code = CERTAINTY_TO_VERIFICATION.get(item.get("certainty", "probable"), "provisional")

    resource: dict = {
        "resourceType": "AllergyIntolerance",
        "meta": {"profile": [US_CORE_PROFILES["AllergyIntolerance"]]},
        "clinicalStatus": {"coding": [{"system": _ALLERGY_CLINICAL_SYSTEM, "code": "active"}]},
        "verificationStatus": {"coding": [{"system": _ALLERGY_VERIFY_SYSTEM, "code": verify_code}]},
        "code": _cc(item.get("coding", []), item.get("substance", "")),
        "patient": {"reference": f"Patient/{patient_id}"},
    }
    if item.get("category"):
        resource["category"] = [item["category"]]
    if item.get("criticality"):
        resource["criticality"] = item["criticality"]
    reaction_block: dict = {}
    if item.get("reaction"):
        reaction_block["manifestation"] = [{"text": item["reaction"]}]
    if item.get("severity"):
        reaction_block["severity"] = item["severity"]
    if item.get("exposure_route"):
        reaction_block["exposureRoute"] = {"text": item["exposure_route"]}
    if reaction_block:
        if "manifestation" not in reaction_block:
            reaction_block["manifestation"] = [{"text": "unknown"}]
        resource["reaction"] = [reaction_block]
    return _strip_none(resource)


def _build_family_member_history(item: dict, patient_id: str) -> dict:
    conditions = []
    for cond in item.get("conditions", []):
        c: dict = {"code": _cc(cond.get("coding", []), cond.get("name", ""))}
        if cond.get("onset_age"):
            age_val = _parse_onset_age(cond["onset_age"])
            if age_val is not None:
                c["onsetAge"] = {"value": age_val, "unit": "a", "system": "http://unitsofmeasure.org", "code": "a"}
        if cond.get("outcome"):
            c["outcome"] = {"text": cond["outcome"]}
        conditions.append(c)

    resource: dict = {
        "resourceType": "FamilyMemberHistory",
        "status": "completed",
        "patient": {"reference": f"Patient/{patient_id}"},
        "relationship": _cc(item.get("coding", []), item.get("relationship", "")),
    }
    if conditions:
        resource["condition"] = conditions
    return _strip_none(resource)


_BUILDERS: dict[str, object] = {
    "Condition": _build_condition,
    "Observation": _build_observation,
    "MedicationRequest": _build_medication_request,
    "Procedure": _build_procedure,
    "AllergyIntolerance": _build_allergy_intolerance,
    "FamilyMemberHistory": _build_family_member_history,
}


def build_fhir_resource(candidate: MergedCandidate, patient_id: str, enc_map: dict[str, str]) -> dict:
    builder = _BUILDERS.get(candidate.resource_type)
    if builder is None:
        raise ValueError(f"no builder for {candidate.resource_type}")
    encounter_ref = _resolve_encounter(candidate.encounter_key, enc_map)
    if candidate.resource_type in ("AllergyIntolerance", "FamilyMemberHistory"):
        return builder(candidate.item, patient_id)
    return builder(candidate.item, patient_id, encounter_ref)


# ---------------------------------------------------------------------------
# Citation resolution
# ---------------------------------------------------------------------------

def resolve_citations(
    source_refs: list[SourceRef],
    notes_by_doc_id: dict[str, PreprocessedNote],
) -> list[ResolvedCitation]:
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


# ---------------------------------------------------------------------------
# StageSixOutput + entry point
# ---------------------------------------------------------------------------

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
    notes_by_doc = {n.document_id: n for n in notes}
    patient_id = patient_context.patient["id"]
    enc_map = _build_encounter_map(patient_context, notes)

    proposals: list[Proposal] = []
    for result in stage5.results:
        if result.classification == "DUPLICATE":
            continue
        resource = build_fhir_resource(result.candidate, patient_id, enc_map)
        citations = resolve_citations(result.candidate.source_refs, notes_by_doc)
        supersedes = (
            [m.resource_id for m in result.chart_matches]
            if result.classification == "UPDATING" else []
        )
        conflicts_with = (
            [m.resource_id for m in result.chart_matches]
            if result.classification == "CONFLICTING" else []
        )
        proposals.append(Proposal(
            id=uuid4().hex,
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
            supersedes=supersedes,
            conflicts_with=conflicts_with,
        ))

    by_class = {}
    for p in proposals:
        by_class[p.classification] = by_class.get(p.classification, 0) + 1
    log.info("stage6 assembled %d proposals: %s", len(proposals), by_class)

    return StageSixOutput(proposals=proposals)
