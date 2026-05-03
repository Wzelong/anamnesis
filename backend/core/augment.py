"""Stage 6: assemble augmentation proposals with valid FHIR R4 resources."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from core.ids import short_id

from core.preprocess import PreprocessedNote
from core.reconcile import _DISCONTINUED_STATUSES, StageFiveOutput
from core.schemas import ChartMatch, MergedCandidate, Proposal, ResolvedCitation, SourceRef
from fhir.models import PatientContext

log = logging.getLogger(__name__)

_BP_LOINC = "85354-9"
_TOBACCO_LOINC = "72166-2"
_FHIR_DATE_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
_NUM_RE = re.compile(r"^([<>≤≥]?)\s*([\d.]+)$")
_BP_RE = re.compile(r"(\d+)\s*/\s*(\d+)")
_AGE_RE = re.compile(r"(\d+)")
_ICD10_DOT_RE = re.compile(r"^([A-Z]\d{2})(\d+)$")

US_CORE_PROFILES: dict[str, str] = {
    "Condition-problem": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-condition-problems-health-concerns",
    "Condition-encounter": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-condition-encounter-diagnosis",
    "MedicationRequest": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-medicationrequest",
    "Procedure": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-procedure",
    "AllergyIntolerance": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-allergyintolerance",
    "FamilyMemberHistory": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-familymemberhistory",
    "Provenance": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-provenance",
}

OBS_PROFILES: dict[str, str] = {
    "vital-signs": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-vital-signs",
    "laboratory": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-observation-lab",
    "survey": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-observation-screening-assessment",
    "exam": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-simple-observation",
    "imaging": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-observation-clinical-result",
    "bp": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-blood-pressure",
    "smokingstatus": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-smokingstatus",
}

_COMPARATOR_MAP = {"<": "<", ">": ">", "≤": "<=", "≥": ">="}

_CONDITION_VERIFY_MAP: dict[str, str] = {
    "definite": "confirmed",
    "probable": "provisional",
    "uncertain": "unconfirmed",
}

_ALLERGY_VERIFY_MAP: dict[str, str] = {
    "definite": "confirmed",
    "probable": "unconfirmed",
    "uncertain": "unconfirmed",
}

CONDITION_CATEGORY_MAP: dict[str, str] = {
    "diagnosis": "encounter-diagnosis",
    "problem": "problem-list-item",
}

_TOBACCO_SNOMED: dict[str, tuple[str, str]] = {
    "current": ("449868002", "Current every day smoker"),
    "ongoing": ("449868002", "Current every day smoker"),
    "active": ("449868002", "Current every day smoker"),
    "former": ("8517006", "Former smoker"),
    "quit": ("8517006", "Former smoker"),
    "never": ("266919005", "Never smoker"),
    "non-smoker": ("266919005", "Never smoker"),
}

_UCUM_CODES: dict[str, str] = {
    "%": "%", "mg": "mg", "mg/dL": "mg/dL", "g/dL": "g/dL",
    "mEq/L": "meq/L", "mmol/L": "mmol/L", "ng/mL": "ng/mL",
    "mmHg": "mm[Hg]", "kg": "kg", "cm": "cm", "bpm": "/min",
    "breaths/min": "/min", "kg/m2": "kg/m2",
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

def _is_negated_assertion(c: MergedCandidate) -> bool:
    if c.resource_type == "Condition" and c.item.get("negated"):
        return True
    if c.resource_type == "MedicationRequest" and c.item.get("status") in _DISCONTINUED_STATUSES:
        return True
    return False


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
    valid = [c for c in coding if c.get("system") and c.get("code")]
    if valid:
        return {"coding": valid, "text": text}
    fallback_text = text or next(
        (c.get("text") or c.get("display") or "" for c in coding if c.get("text") or c.get("display")),
        "",
    )
    return {"text": fallback_text} if fallback_text else {}


def _cond_verification(certainty: str) -> dict:
    code = _CONDITION_VERIFY_MAP.get(certainty, "provisional")
    return {"coding": [{"system": _COND_VERIFY_SYSTEM, "code": code}]}


def _allergy_verification(certainty: str) -> dict:
    code = _ALLERGY_VERIFY_MAP.get(certainty, "unconfirmed")
    return {"coding": [{"system": _ALLERGY_VERIFY_SYSTEM, "code": code}]}


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


def _normalize_icd10(code: str) -> str:
    m = _ICD10_DOT_RE.match(code.strip())
    if m:
        return f"{m.group(1)}.{m.group(2)}"
    return code


def _normalize_coding(coding_list: list[dict]) -> list[dict]:
    out = []
    for c in coding_list:
        c = dict(c)
        if c.get("system") == "http://hl7.org/fhir/sid/icd-10-cm" and c.get("code"):
            c["code"] = _normalize_icd10(c["code"])
        out.append(c)
    return out


def _is_valid_fhir_date(s: str) -> bool:
    return bool(_FHIR_DATE_RE.match(s))


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
    if cat_code == "encounter-diagnosis" and encounter_ref:
        profile = US_CORE_PROFILES["Condition-encounter"]
    else:
        profile = US_CORE_PROFILES["Condition-problem"]
        cat_code = "problem-list-item"

    certainty = item.get("certainty", "probable")
    verify = _cond_verification(certainty)

    resource: dict = {
        "resourceType": "Condition",
        "meta": {"profile": [profile]},
        "verificationStatus": verify,
        "category": [{"coding": [{"system": _COND_CATEGORY_SYSTEM, "code": cat_code}]}],
        "code": _cc(_normalize_coding(item.get("coding", [])), item.get("name", "")),
        "subject": {"reference": f"Patient/{patient_id}"},
    }

    verify_code = verify["coding"][0]["code"]
    if verify_code != "entered-in-error":
        resource["clinicalStatus"] = {"coding": [{"system": _COND_CLINICAL_SYSTEM, "code": "active"}]}

    onset = item.get("onset")
    if onset:
        if _is_valid_fhir_date(onset):
            resource["onsetDateTime"] = onset
        else:
            resource["onsetString"] = onset

    if item.get("severity"):
        resource["severity"] = {"text": item["severity"]}
    if item.get("body_site"):
        resource["bodySite"] = [{"text": s} for s in item["body_site"]]
    if encounter_ref:
        resource["encounter"] = {"reference": encounter_ref}
    return _strip_none(resource)


def _build_observation(item: dict, patient_id: str, encounter_ref: str | None, *, note_date: str | None = None) -> dict:
    cat = item.get("category", "exam")

    codings = item.get("coding", [])
    loinc_codes = [c.get("code") for c in codings if c.get("system") == "http://loinc.org"]

    is_tobacco = _TOBACCO_LOINC in loinc_codes
    is_bp = _BP_LOINC in loinc_codes

    if is_bp:
        profile = OBS_PROFILES["bp"]
    elif is_tobacco:
        profile = OBS_PROFILES["smokingstatus"]
    else:
        profile = OBS_PROFILES.get(cat)

    resource: dict = {
        "resourceType": "Observation",
        "status": "final",
        "category": [{"coding": [{"system": _OBS_CATEGORY_SYSTEM, "code": cat}]}],
        "code": _cc(codings, item.get("full_name") or item.get("name", "")),
        "subject": {"reference": f"Patient/{patient_id}"},
    }
    if profile:
        resource["meta"] = {"profile": [profile]}

    effective = item.get("effective_date")
    if effective:
        resource["effectiveDateTime"] = effective
    elif note_date:
        resource["effectiveDateTime"] = note_date

    value_str = item.get("value", "")
    unit = item.get("unit")

    if is_bp:
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
    elif is_tobacco:
        vcc: dict = {"text": value_str}
        v_lower = value_str.lower().strip()
        for key, (code, display) in _TOBACCO_SNOMED.items():
            if key in v_lower:
                vcc["coding"] = [{"system": "http://snomed.info/sct", "code": code, "display": display}]
                break
        resource["valueCodeableConcept"] = vcc
    elif cat == "social-history":
        resource["valueCodeableConcept"] = {"text": value_str}
    elif unit and _is_numeric(value_str):
        m = _NUM_RE.match(value_str.strip())
        if m:
            comp_char, num_str = m.group(1), m.group(2)
            qty: dict = {"value": float(num_str), "unit": unit}
            if comp_char and comp_char in _COMPARATOR_MAP:
                qty["comparator"] = _COMPARATOR_MAP[comp_char]
            ucum = _UCUM_CODES.get(unit)
            if ucum:
                qty["system"] = "http://unitsofmeasure.org"
                qty["code"] = ucum
            resource["valueQuantity"] = qty
        else:
            resource["valueString"] = f"{value_str} {unit}".strip()
    else:
        resource["valueString"] = value_str

    if encounter_ref:
        resource["encounter"] = {"reference": encounter_ref}
    return _strip_none(resource)


def _build_medication_request(item: dict, patient_id: str, encounter_ref: str | None, *, note_date: str | None = None) -> dict:
    resource: dict = {
        "resourceType": "MedicationRequest",
        "meta": {"profile": [US_CORE_PROFILES["MedicationRequest"]]},
        "status": item.get("status", "active"),
        "intent": item.get("intent", "order"),
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/medicationrequest-category", "code": "outpatient"}]}],
        "reportedBoolean": True,
        "medicationCodeableConcept": _cc(item.get("coding", []), item.get("name", "")),
        "subject": {"reference": f"Patient/{patient_id}"},
        "requester": {"reference": f"Patient/{patient_id}"},
    }
    if note_date:
        resource["authoredOn"] = note_date

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


def _build_procedure(item: dict, patient_id: str, encounter_ref: str | None, *, note_date: str | None = None) -> dict:
    resource: dict = {
        "resourceType": "Procedure",
        "meta": {"profile": [US_CORE_PROFILES["Procedure"]]},
        "status": item.get("status", "completed"),
        "code": _cc(item.get("coding", []), item.get("name", "")),
        "subject": {"reference": f"Patient/{patient_id}"},
    }
    performed = item.get("performed") or note_date
    if performed:
        resource["performedDateTime"] = performed
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
    if verification and verification in ("unconfirmed", "confirmed", "refuted", "entered-in-error"):
        verify_code = verification
    else:
        verify_code = _ALLERGY_VERIFY_MAP.get(item.get("certainty", "probable"), "unconfirmed")

    resource: dict = {
        "resourceType": "AllergyIntolerance",
        "meta": {"profile": [US_CORE_PROFILES["AllergyIntolerance"]]},
        "verificationStatus": {"coding": [{"system": _ALLERGY_VERIFY_SYSTEM, "code": verify_code}]},
        "code": _cc(item.get("coding", []), item.get("substance", "")),
        "patient": {"reference": f"Patient/{patient_id}"},
    }
    if verify_code != "entered-in-error":
        resource["clinicalStatus"] = {"coding": [{"system": _ALLERGY_CLINICAL_SYSTEM, "code": "active"}]}
    if item.get("category"):
        resource["category"] = [item["category"]]
    if item.get("criticality"):
        resource["criticality"] = item["criticality"]
    if item.get("onset_age"):
        age_val = _parse_onset_age(item["onset_age"])
        if age_val is not None:
            resource["onsetAge"] = {"value": age_val, "unit": "a", "system": "http://unitsofmeasure.org", "code": "a"}
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
        "meta": {"profile": [US_CORE_PROFILES["FamilyMemberHistory"]]},
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


def build_fhir_resource(
    candidate: MergedCandidate,
    patient_id: str,
    enc_map: dict[str, str],
    *,
    note_date: str | None = None,
) -> dict:
    builder = _BUILDERS.get(candidate.resource_type)
    if builder is None:
        raise ValueError(f"no builder for {candidate.resource_type}")
    encounter_ref = _resolve_encounter(candidate.encounter_key, enc_map)
    if candidate.resource_type in ("AllergyIntolerance", "FamilyMemberHistory"):
        return builder(candidate.item, patient_id)
    if candidate.resource_type in ("Observation", "MedicationRequest", "Procedure"):
        return builder(candidate.item, patient_id, encounter_ref, note_date=note_date)
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
