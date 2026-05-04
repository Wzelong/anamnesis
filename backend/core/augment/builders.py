"""Per-resource-type FHIR builders + dispatch (`build_fhir_resource`)."""
from __future__ import annotations

from core.augment.citations import _resolve_encounter
from core.augment.config import (
    _ALLERGY_CLINICAL_SYSTEM,
    _ALLERGY_VERIFY_MAP,
    _ALLERGY_VERIFY_SYSTEM,
    _BP_LOINC,
    _COMPARATOR_MAP,
    _COND_CATEGORY_SYSTEM,
    _COND_CLINICAL_SYSTEM,
    _NUM_RE,
    _OBS_CATEGORY_SYSTEM,
    _TOBACCO_LOINC,
    _TOBACCO_SNOMED,
    _UCUM_CODES,
    CONDITION_CATEGORY_MAP,
    OBS_PROFILES,
    US_CORE_PROFILES,
)
from core.augment.helpers import (
    _allergy_verification,
    _cc,
    _cond_verification,
    _is_numeric,
    _is_valid_fhir_date,
    _normalize_coding,
    _parse_bp,
    _parse_onset_age,
    _strip_none,
)
from core.schemas import MergedCandidate


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
    """Build a US Core R4 resource dict for a candidate via the per-type dispatch.

    Routes by `candidate.resource_type` into the matching `_build_*` function
    in `_BUILDERS`. Patient-only resources (AllergyIntolerance,
    FamilyMemberHistory) get just `(item, patient_id)`; encounter-aware
    resources get the resolved `encounter_ref` and `note_date` for fallback
    dating.
    """
    builder = _BUILDERS.get(candidate.resource_type)
    if builder is None:
        raise ValueError(f"no builder for {candidate.resource_type}")
    encounter_ref = _resolve_encounter(candidate.encounter_key, enc_map)
    if candidate.resource_type in ("AllergyIntolerance", "FamilyMemberHistory"):
        return builder(candidate.item, patient_id)
    if candidate.resource_type in ("Observation", "MedicationRequest", "Procedure"):
        return builder(candidate.item, patient_id, encounter_ref, note_date=note_date)
    return builder(candidate.item, patient_id, encounter_ref)
