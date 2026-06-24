"""Stage 5 — deterministic match rules.

ChartIndex + per-resource-type matchers. Each `_match_*` returns
`(verdict, reasoning, chart_matches, raw_resources)` where verdict is one of
`NEW / DUPLICATE / UPDATING / CONFLICTING / AMBIGUOUS`. AMBIGUOUS hands the
candidate off to the LLM adjudicator in `core/reconcile.py`.

This module is the boring-but-important half of Stage 5: pure code-driven
rules that account for the great majority of classifications. The interesting
LLM call only fires for the residual AMBIGUOUS cases.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from core.schemas import ChartMatch, MergedCandidate
from fhir.models import PatientContext

MatchVerdict = Literal["NEW", "DUPLICATE", "UPDATING", "CONFLICTING", "AMBIGUOUS"]

NKDA_CODE = "409137002"
TOBACCO_LOINC = "72166-2"

_DOSE_RE = re.compile(r"\s+\d+(\.\d+)?(/\d+(\.\d+)?)?\s*(mg|mcg|g|ml|units?|%)\b.*", re.IGNORECASE)
_STRIP_PREFIXES = re.compile(
    r"^(essential|chronic|acute|mild|moderate|severe|minor|primary)\s+",
    re.IGNORECASE,
)

# Verbose RxNorm / SNOMED clinical-drug displays carry preambles, dose words,
# packaging suffixes, and chemical qualifiers that would otherwise prevent the
# ingredient-fallback from matching the chart's concise display. The next four
# patterns reduce a string like
#   "Product containing precisely carbidopa anhydrous (as carbidopa) 25 milligram
#    and levodopa 100 milligram/1 each conventional release oral tablet (clinical drug)"
# to "carbidopa / levodopa", which matches the chart side written as
# "carbidopa / levodopa".
_INGREDIENT_PREAMBLE_RE = re.compile(r"^product containing(?:\s+precisely)?\s+", re.IGNORECASE)
_INGREDIENT_TABLET_SUFFIX_RE = re.compile(r"\s*/\d+\s+each\s+.*$", re.IGNORECASE)
_INGREDIENT_PARENS_RE = re.compile(r"\s*\([^)]*\)\s*")
_INGREDIENT_INLINE_DOSE_RE = re.compile(
    r"\s+\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?\s*"
    r"(milligrams?|micrograms?|grams?|milliliters?|mg|mcg|g|ml)\b",
    re.IGNORECASE,
)
_INGREDIENT_QUALIFIERS_RE = re.compile(
    r"\b(anhydrous|monohydrate|dihydrate|trihydrate|sodium|potassium|calcium|"
    r"hydrochloride|hcl|sulfate|sulphate|maleate|tartrate|succinate|fumarate|"
    r"hemifumarate|mesylate|besylate|acetate|citrate|"
    r"oral tablet|oral capsule|oral solution|injectable solution|"
    r"conventional release|extended release|delayed release)\b",
    re.IGNORECASE,
)
_INGREDIENT_AND_RE = re.compile(r"\s+and\s+", re.IGNORECASE)
_INGREDIENT_SLASH_SPACING_RE = re.compile(r"\s*/\s*")

# Reasoning models occasionally cram the unit into MedicationDose.value
# ("25/100 mg") instead of leaving it in MedicationDose.unit. Normalize both
# sides of the dose comparison so a unit-bearing candidate doesn't fire a
# false UPDATING against a unitless chart dose extracted from dosageInstruction.
_DOSE_VALUE_TAIL_RE = re.compile(
    r"\s*(milligrams?|micrograms?|grams?|milliliters?|mg|mcg|g|ml|units?|%)\s*$",
    re.IGNORECASE,
)


def _normalize_dose_value(v) -> str:
    return _DOSE_VALUE_TAIL_RE.sub("", str(v)).strip()

_TOBACCO_CURRENT = {"current every day smoker", "current some day smoker",
                     "ongoing", "active", "smoker", "current smoker",
                     "light tobacco smoker", "heavy tobacco smoker"}
_TOBACCO_FORMER = {"former smoker", "quit", "former", "tobacco-free",
                    "ex-smoker", "quit smoking"}
_TOBACCO_NEVER = {"never smoker", "never", "non-smoker"}


def _normalize_ingredient(display: str) -> str:
    s = display.lower().strip()
    s = _INGREDIENT_PREAMBLE_RE.sub("", s)
    s = _INGREDIENT_TABLET_SUFFIX_RE.sub("", s)
    s = _INGREDIENT_PARENS_RE.sub(" ", s)
    s = _INGREDIENT_INLINE_DOSE_RE.sub(" ", s)
    s = _INGREDIENT_QUALIFIERS_RE.sub(" ", s)
    s = _DOSE_RE.sub("", s)
    s = _INGREDIENT_AND_RE.sub(" / ", s)
    s = _INGREDIENT_SLASH_SPACING_RE.sub(" / ", s)
    return re.sub(r"\s+", " ", s).strip()


def _normalize_display(text: str) -> str:
    t = text.lower().strip()
    t = _STRIP_PREFIXES.sub("", t).strip()
    return t


def _canonical_tobacco(value: str) -> str:
    v = value.lower().strip()
    if v in _TOBACCO_CURRENT or any(k in v for k in ("current", "ongoing", "active", "every day")):
        return "current"
    if v in _TOBACCO_FORMER or any(k in v for k in ("former", "quit", "tobacco-free", "ex-")):
        return "former"
    if v in _TOBACCO_NEVER or "never" in v:
        return "never"
    return v


def _normalize_code(system: str, code: str) -> tuple[str, str]:
    # ICD-10-CM is the only system that varies between dotted ("I50.22") and
    # dotless ("I5022") form across sources — retrieval APIs return dotless, FHIR
    # servers are dotted. Normalize symmetrically so exact-code matching works
    # regardless of which form each side carries.
    if "icd-10" in system.lower() or "icd10" in system.lower():
        return (system, code.replace(".", ""))
    return (system, code)


def _extract_codes(coding_list: list[dict]) -> set[tuple[str, str]]:
    return {_normalize_code(c["system"], c["code"]) for c in coding_list if "system" in c and "code" in c}


def _extract_fhir_codes(resource: dict, path: str = "code") -> set[tuple[str, str]]:
    node = resource
    for part in path.split("."):
        node = node.get(part, {})
        if not node:
            return set()
    codings = node.get("coding", []) if isinstance(node, dict) else []
    return {_normalize_code(c["system"], c["code"]) for c in codings if "system" in c and "code" in c}


def _fhir_display(resource: dict, path: str = "code") -> str:
    node = resource
    for part in path.split("."):
        node = node.get(part, {})
        if not node:
            return ""
    if isinstance(node, dict):
        return node.get("text", "") or next(
            (c.get("display", "") for c in node.get("coding", [])), ""
        )
    return ""


def _resource_id(resource: dict) -> str:
    return resource.get("id", "") or resource.get("fullUrl", "")


# ---------------------------------------------------------------------------
# ChartIndex
# ---------------------------------------------------------------------------

@dataclass
class ChartIndex:
    code_to_resources: dict[str, dict[tuple[str, str], list[dict]]]
    display_to_resources: dict[str, dict[str, list[dict]]]
    nkda_resources: list[dict]
    obs_by_loinc: dict[str, list[tuple[dict, str]]]
    med_by_ingredient: dict[str, list[dict]]

    @property
    def has_nkda(self) -> bool:
        return bool(self.nkda_resources)


def build_chart_index(ctx: PatientContext) -> ChartIndex:
    """Build lookup tables over the existing chart for fast reconcile-time matching.

    Returns a `ChartIndex` with three views per resource type plus three
    specialized indexes:
      * `code_map[rtype][(system, code)]` -> list of resources with that code
      * `display_map[rtype][lower(display)]` -> list of resources matching by name
      * `nkda_allergy` — the NKDA AllergyIntolerance, if present (drives
        CONFLICTING for any specific-allergy candidate)
      * `loinc_observations[loinc_code]` -> Observations sharing that LOINC
        (drives UPDATING when value changes)
      * `med_ingredients[ingredient]` -> MedicationRequests with that
        normalized ingredient (drives ingredient-fallback dose comparison)
    """
    code_map: dict[str, dict[tuple[str, str], list[dict]]] = {}
    display_map: dict[str, dict[str, list[dict]]] = {}

    for rtype, resources, code_path in [
        ("Condition", ctx.conditions, "code"),
        ("MedicationRequest", ctx.medications, "medicationCodeableConcept"),
        ("AllergyIntolerance", ctx.allergies, "code"),
        ("Procedure", ctx.procedures, "code"),
    ]:
        cm: dict[tuple[str, str], list[dict]] = {}
        dm: dict[str, list[dict]] = {}
        for r in resources:
            for pair in _extract_fhir_codes(r, code_path):
                cm.setdefault(pair, []).append(r)
            disp = _normalize_display(_fhir_display(r, code_path))
            if disp:
                dm.setdefault(disp, []).append(r)
        code_map[rtype] = cm
        display_map[rtype] = dm

    nkda_resources: list[dict] = []
    for a in ctx.allergies:
        for c in a.get("code", {}).get("coding", []):
            if c.get("code") == NKDA_CODE:
                nkda_resources.append(a)
                break

    obs_by_loinc: dict[str, list[tuple[dict, str]]] = {}
    for o in ctx.observations:
        for c in o.get("code", {}).get("coding", []):
            if c.get("system") == "http://loinc.org":
                val = (
                    o.get("valueCodeableConcept", {}).get("text", "")
                    or next(
                        (cd.get("display", "")
                         for cd in o.get("valueCodeableConcept", {}).get("coding", [])),
                        "",
                    )
                    or o.get("valueString", "")
                    or o.get("valueQuantity", {}).get("value", "")
                )
                obs_by_loinc.setdefault(c["code"], []).append((o, str(val)))

    med_by_ing: dict[str, list[dict]] = {}
    for m in ctx.medications:
        for c in m.get("medicationCodeableConcept", {}).get("coding", []):
            ing = _normalize_ingredient(c.get("display", ""))
            if ing:
                med_by_ing.setdefault(ing, []).append(m)

    fmh_cm: dict[tuple[str, str], list[dict]] = {}
    fmh_dm: dict[str, list[dict]] = {}
    for f in ctx.family_history:
        rel = f.get("relationship", {})
        for c in rel.get("coding", []):
            if "system" in c and "code" in c:
                fmh_cm.setdefault(_normalize_code(c["system"], c["code"]), []).append(f)
        disp = _normalize_display(rel.get("text", "") or next(
            (c.get("display", "") for c in rel.get("coding", [])), ""
        ))
        if disp:
            fmh_dm.setdefault(disp, []).append(f)
    code_map["FamilyMemberHistory"] = fmh_cm
    display_map["FamilyMemberHistory"] = fmh_dm

    return ChartIndex(
        code_to_resources=code_map,
        display_to_resources=display_map,
        nkda_resources=nkda_resources,
        obs_by_loinc=obs_by_loinc,
        med_by_ingredient=med_by_ing,
    )


# ---------------------------------------------------------------------------
# Per-resource-type matchers
# ---------------------------------------------------------------------------

_MatchResult = tuple[MatchVerdict, str, list[ChartMatch], list[dict]]

_DISCONTINUED_STATUSES = frozenset({"stopped", "cancelled", "completed", "entered-in-error"})


def _condition_clinical_status(resource: dict) -> str:
    cs = resource.get("clinicalStatus") or {}
    for c in cs.get("coding", []):
        code = c.get("code")
        if code:
            return code
    return "active"  # FHIR convention: unset clinicalStatus implies active


def _match_condition(c: MergedCandidate, idx: ChartIndex) -> _MatchResult:
    """Condition -> exact (system, code) match -> DUPLICATE; display overlap -> AMBIGUOUS (LLM); else NEW."""
    if c.item.get("negated"):
        return _match_condition_negated(c, idx)

    candidate_codes = _extract_codes(c.item.get("coding", []))
    chart_codes = idx.code_to_resources.get("Condition", {})

    for pair in candidate_codes:
        if pair in chart_codes:
            matched = chart_codes[pair]
            return (
                "DUPLICATE",
                f"exact code match {pair[1]}",
                [ChartMatch(resource_id=_resource_id(m), display=_fhir_display(m), match_type="exact_code", resource=m) for m in matched],
                matched,
            )

    name = _normalize_display(c.item.get("name", ""))
    chart_displays = idx.display_to_resources.get("Condition", {})
    for disp, resources in chart_displays.items():
        if name and (name in disp or disp in name):
            return (
                "AMBIGUOUS",
                f"display overlap: '{name}' ~ '{disp}'",
                [ChartMatch(resource_id=_resource_id(r), display=disp, match_type="display_text", resource=r) for r in resources],
                resources,
            )

    return ("NEW", "no match in chart", [], [])


def _match_condition_negated(c: MergedCandidate, idx: ChartIndex) -> _MatchResult:
    """Negated Condition -> CONFLICTING if chart has the active assertion; else DUPLICATE/NEW."""
    candidate_codes = _extract_codes(c.item.get("coding", []))
    chart_codes = idx.code_to_resources.get("Condition", {})
    name = _normalize_display(c.item.get("name", ""))
    chart_displays = idx.display_to_resources.get("Condition", {})

    matched: list[dict] = []
    matches: list[ChartMatch] = []

    for pair in candidate_codes:
        if pair in chart_codes:
            for m in chart_codes[pair]:
                matched.append(m)
                matches.append(ChartMatch(resource_id=_resource_id(m), display=_fhir_display(m), match_type="exact_code", resource=m))

    if not matched:
        for disp, resources in chart_displays.items():
            if name and (name in disp or disp in name):
                for r in resources:
                    matched.append(r)
                    matches.append(ChartMatch(resource_id=_resource_id(r), display=disp, match_type="display_text", resource=r))
                break

    if not matched:
        return ("NEW", "negated assertion has no chart anchor", [], [])

    active = [m for m in matched if _condition_clinical_status(m) == "active"]
    if active:
        display = _fhir_display(active[0]) or name
        return (
            "CONFLICTING",
            f"note negates this; chart shows active: {display}",
            matches,
            matched,
        )
    return (
        "DUPLICATE",
        "chart already records this as resolved/inactive",
        matches,
        matched,
    )


_DOSE_IN_TEXT_RE = re.compile(r"(\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?)\s*(mg|mcg|g|ml)\b", re.IGNORECASE)


def _extract_chart_dose(resource: dict) -> str:
    for di in resource.get("dosageInstruction", []):
        for dr in di.get("doseAndRate", []):
            q = dr.get("doseQuantity", {})
            v = q.get("value")
            if v is not None:
                return str(v)
        text = di.get("text", "")
        m = _DOSE_IN_TEXT_RE.search(text)
        if m:
            return m.group(1)
    return ""


def _find_ingredient_match(ing: str, idx: ChartIndex) -> list[dict] | None:
    if ing in idx.med_by_ingredient:
        return idx.med_by_ingredient[ing]
    for chart_ing, resources in idx.med_by_ingredient.items():
        if ing in chart_ing or chart_ing in ing:
            return resources
    return None


def _match_medication(c: MergedCandidate, idx: ChartIndex) -> _MatchResult:
    """MedicationRequest -> exact RxNorm -> DUPLICATE; ingredient match + dose diff -> UPDATING; same dose -> DUPLICATE."""
    if c.item.get("status") in _DISCONTINUED_STATUSES:
        return _match_medication_discontinued(c, idx)

    candidate_codes = _extract_codes(c.item.get("coding", []))
    chart_codes = idx.code_to_resources.get("MedicationRequest", {})

    for pair in candidate_codes:
        if pair in chart_codes:
            matched = chart_codes[pair]
            return (
                "DUPLICATE",
                f"exact RxNorm match {pair[1]}",
                [ChartMatch(resource_id=_resource_id(m), display=_fhir_display(m, "medicationCodeableConcept"), match_type="exact_code", resource=m) for m in matched],
                matched,
            )

    for coding in c.item.get("coding", []):
        ing = _normalize_ingredient(coding.get("display", ""))
        if not ing:
            ing = _normalize_ingredient(c.item.get("name", ""))
        if not ing:
            continue
        matched = _find_ingredient_match(ing, idx)
        if matched is None:
            continue

        cand_dose = c.item.get("dose", {})
        cand_dose_val = cand_dose.get("value", "") if isinstance(cand_dose, dict) else ""
        chart_dose = _extract_chart_dose(matched[0])

        matches = [ChartMatch(resource_id=_resource_id(m), display=_fhir_display(m, "medicationCodeableConcept"), match_type="ingredient", resource=m) for m in matched]
        cand_norm = _normalize_dose_value(cand_dose_val)
        chart_norm = _normalize_dose_value(chart_dose)
        if cand_norm and chart_norm and cand_norm != chart_norm:
            return ("UPDATING", f"same ingredient '{ing}', dose {chart_dose}->{cand_dose_val}", matches, matched)
        return ("DUPLICATE", f"same ingredient '{ing}'", matches, matched)

    return ("NEW", "no match in chart", [], [])


def _match_medication_discontinued(c: MergedCandidate, idx: ChartIndex) -> _MatchResult:
    """Discontinued MedicationRequest -> CONFLICTING when chart still has it active."""
    candidate_codes = _extract_codes(c.item.get("coding", []))
    chart_codes = idx.code_to_resources.get("MedicationRequest", {})

    matched: list[dict] = []
    matches: list[ChartMatch] = []

    for pair in candidate_codes:
        if pair in chart_codes:
            for m in chart_codes[pair]:
                matched.append(m)
                matches.append(ChartMatch(
                    resource_id=_resource_id(m),
                    display=_fhir_display(m, "medicationCodeableConcept"),
                    match_type="exact_code",
                    resource=m,
                ))

    if not matched:
        for coding in c.item.get("coding", []):
            ing = _normalize_ingredient(coding.get("display", ""))
            if not ing:
                ing = _normalize_ingredient(c.item.get("name", ""))
            if not ing:
                continue
            ing_matched = _find_ingredient_match(ing, idx)
            if ing_matched is None:
                continue
            for m in ing_matched:
                matched.append(m)
                matches.append(ChartMatch(
                    resource_id=_resource_id(m),
                    display=_fhir_display(m, "medicationCodeableConcept"),
                    match_type="ingredient",
                    resource=m,
                ))
            break

    if not matched:
        return ("NEW", "discontinuation has no chart anchor", [], [])

    active = [m for m in matched if m.get("status", "active") == "active"]
    if active:
        display = _fhir_display(active[0], "medicationCodeableConcept") or c.item.get("name", "")
        return (
            "CONFLICTING",
            f"note says discontinued; chart shows active: {display}",
            matches,
            matched,
        )
    return (
        "DUPLICATE",
        "chart already records this as discontinued",
        matches,
        matched,
    )


def _match_allergy(c: MergedCandidate, idx: ChartIndex) -> _MatchResult:
    """AllergyIntolerance -> CONFLICTING when chart asserts NKDA but candidate names a specific allergen; else exact-code DUPLICATE/NEW."""
    candidate_codes = _extract_codes(c.item.get("coding", []))

    is_specific_allergy = not any(code == NKDA_CODE for _, code in candidate_codes)
    if is_specific_allergy and idx.nkda_resources:
        substance = c.item.get("substance", "unknown")
        return (
            "CONFLICTING",
            f"chart records NKDA but candidate asserts allergy to {substance}",
            [ChartMatch(resource_id=_resource_id(r), display="No known drug allergy", match_type="exact_code", resource=r) for r in idx.nkda_resources],
            list(idx.nkda_resources),
        )

    chart_codes = idx.code_to_resources.get("AllergyIntolerance", {})
    for pair in candidate_codes:
        if pair in chart_codes:
            matched = chart_codes[pair]
            return (
                "DUPLICATE",
                f"exact allergy code match {pair[1]}",
                [ChartMatch(resource_id=_resource_id(m), display=_fhir_display(m), match_type="exact_code", resource=m) for m in matched],
                matched,
            )

    return ("NEW", "no match in chart", [], [])


def _match_observation(c: MergedCandidate, idx: ChartIndex) -> _MatchResult:
    """Observation -> LOINC code match + value comparison; UPDATING when value differs (with tobacco-status canonicalization)."""
    for coding in c.item.get("coding", []):
        if coding.get("system") != "http://loinc.org":
            continue
        loinc = coding.get("code", "")
        if loinc in idx.obs_by_loinc:
            chart_entries = idx.obs_by_loinc[loinc]
            chart_resource, chart_val = chart_entries[0]
            cand_val = c.item.get("value", "")

            if loinc == TOBACCO_LOINC:
                c_canon = _canonical_tobacco(cand_val)
                ch_canon = _canonical_tobacco(chart_val)
                if c_canon == ch_canon:
                    return (
                        "DUPLICATE",
                        f"same tobacco status: {c_canon}",
                        [ChartMatch(resource_id=_resource_id(chart_resource), display=chart_val, match_type="exact_code", resource=chart_resource)],
                        [chart_resource],
                    )
                return (
                    "UPDATING",
                    f"tobacco status changed: {ch_canon} -> {c_canon}",
                    [ChartMatch(resource_id=_resource_id(chart_resource), display=chart_val, match_type="exact_code", resource=chart_resource)],
                    [chart_resource],
                )

            if str(cand_val).strip().lower() == str(chart_val).strip().lower():
                return (
                    "DUPLICATE",
                    f"same LOINC {loinc}, same value",
                    [ChartMatch(resource_id=_resource_id(chart_resource), display=chart_val, match_type="exact_code", resource=chart_resource)],
                    [chart_resource],
                )
            return (
                "UPDATING",
                f"same LOINC {loinc}, value changed: '{chart_val}' -> '{cand_val}'",
                [ChartMatch(resource_id=_resource_id(chart_resource), display=chart_val, match_type="exact_code", resource=chart_resource)],
                [chart_resource],
            )

    return ("NEW", "no LOINC match in chart", [], [])


def _match_procedure(c: MergedCandidate, idx: ChartIndex) -> _MatchResult:
    """Procedure -> SNOMED code + same date -> DUPLICATE; same code different date -> NEW (separate instance)."""
    candidate_codes = _extract_codes(c.item.get("coding", []))
    chart_codes = idx.code_to_resources.get("Procedure", {})

    for pair in candidate_codes:
        if pair in chart_codes:
            matched = chart_codes[pair]
            cand_date = c.item.get("performed", "")
            for m in matched:
                chart_date = m.get("performedDateTime", "") or m.get("performedPeriod", {}).get("start", "")
                if cand_date and chart_date and cand_date == chart_date:
                    return (
                        "DUPLICATE",
                        f"same procedure code + date {cand_date}",
                        [ChartMatch(resource_id=_resource_id(m), display=_fhir_display(m), match_type="exact_code", resource=m)],
                        matched,
                    )
            return ("NEW", "same procedure code but different date", [], [])

    return ("NEW", "no match in chart", [], [])


def _match_family_history(c: MergedCandidate, idx: ChartIndex) -> _MatchResult:
    """FamilyMemberHistory -> relationship code match -> DUPLICATE; else NEW."""
    rel_coding = c.item.get("coding", [])
    candidate_rel_codes = _extract_codes(rel_coding)
    chart_codes = idx.code_to_resources.get("FamilyMemberHistory", {})

    for pair in candidate_rel_codes:
        if pair in chart_codes:
            return (
                "DUPLICATE",
                f"same relationship code {pair[1]}",
                [ChartMatch(resource_id=_resource_id(m), display="", match_type="exact_code", resource=m) for m in chart_codes[pair]],
                chart_codes[pair],
            )

    return ("NEW", "no match in chart", [], [])


_MATCHERS = {
    "Condition": _match_condition,
    "MedicationRequest": _match_medication,
    "AllergyIntolerance": _match_allergy,
    "Observation": _match_observation,
    "Procedure": _match_procedure,
    "FamilyMemberHistory": _match_family_history,
}
