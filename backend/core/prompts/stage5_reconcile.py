"""Stage 5 reconcile-vs-chart prompt + per-resource-type rules."""

RECONCILE_TYPE_RULES: dict[str, str] = {
    "Condition": "Same disease at different specificity levels (e.g. 'fatigue' vs 'chronic post-stroke fatigue') is DUPLICATE, not NEW.",
    "MedicationRequest": "Same drug ingredient with different dose or frequency is UPDATING. Same ingredient with equivalent dose is DUPLICATE.",
    "AllergyIntolerance": "A specific allergy contradicting a 'no known drug allergy' (NKDA) assertion is CONFLICTING.",
    "Observation": "Same LOINC code with a different measured or reported value is UPDATING.",
    "Procedure": "Same procedure code on the same date is DUPLICATE. Same code on a different date is a separate instance (NEW).",
    "FamilyMemberHistory": "Same relationship with same condition is DUPLICATE. Same relationship with new conditions is NEW.",
}

PROMPT_RECONCILE = """\
Role
Clinical reconciliation classifier for {resource_type} resources.

Goal
For each numbered pair of (candidate from clinical notes, existing chart resource), classify the candidate.

Classifications
- DUPLICATE: same clinical entity, no meaningful difference.
- UPDATING: same entity with a meaningful change (new dose, new value, changed severity or status).
- CONFLICTING: candidate directly contradicts the chart record.
- NEW: different clinical entity despite superficial textual similarity.

{type_rules}

When uncertain, prefer NEW over DUPLICATE — it is safer to surface a potential duplicate to a clinician than to silently suppress a real finding.

Stop
Return one classification per numbered pair. Match the index field to the pair number.
"""
