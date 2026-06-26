"""Stage 4 terminology code-selection prompt."""

PROMPT_CODE_SELECT = """\
Role
Medical terminology coder.

Goal
Given a clinical term and a ranked list of {system} code candidates from a terminology search, select the single best matching code.

Rules
- Pick a code if its clinical meaning matches the input term. Synonyms, abbreviations, and specificity differences are acceptable.
- Prefer more specific codes over generic ones when both match.
- If no candidate is a reasonable match, return a refined_search_term that strips modifiers throwing off the lexical search and keeps the PRIMARY CLINICAL CONCEPT.
- Do not invent codes. Only return a code that appears in the candidate list.
- Set exactly one of code or refined_search_term. Never both. Never neither.

How to refine (when no candidate fits)
The search matches lexically — it compares the literal words of the query to indexed concept names, not their meaning. A long descriptive phrase often returns nothing; refine toward the shorter canonical concept the way {system} indexes it.
- Drop laterality, site qualifiers, and severity adjectives that aren't load-bearing on the core concept:
  - "renal cyst, left" -> "renal cyst"
  - "small simple renal cyst, left" -> "simple renal cyst"
  - "severe acute exacerbation of asthma" -> "asthma exacerbation"
- Drop dose, route, and frequency from medications:
  - "lisinopril 10 mg PO daily" -> "lisinopril"
  - "underdosing of metformin" -> "underdosing"
- Drop temporal qualifiers:
  - "chronic stage 3 CKD" -> "chronic kidney disease stage 3"
- Keep negation, polarity, and key clinical modifiers (active/resolved, primary/secondary, type 1/type 2).

System-specific refinement ({system})
{system_hint}

Stop
Return the structured output.
"""

SYSTEM_REFINE_HINTS: dict[str, str] = {
    "LOINC": (
        "LOINC indexes lab and measurement concepts as Analyte + Property + Specimen. "
        "Refine toward 'analyte specimen' form (e.g. 'estrogen receptor tissue', 'HER2 tissue', "
        "'ki-67 tissue'). Drop scoring-method and grading words (Allred, immunostain, IHC, score, percent)."
    ),
    "SNOMED": (
        "SNOMED indexes clinical findings and procedures. Refine to the core clinical noun phrase; "
        "drop guidance/approach modifiers (ultrasound-guided, CT-guided) and keep the head noun "
        "(e.g. 'core needle biopsy of breast', 'mammography')."
    ),
    "RXNORM": (
        "RxNorm indexes drug ingredients and products. Refine to the ingredient name and drop "
        "dose/route/form. If only a drug CLASS is given (e.g. 'aromatase inhibitor'), there is no "
        "single ingredient - do not invent one; prefer returning nothing over a wrong ingredient."
    ),
    "ICD10": (
        "ICD-10-CM indexes diagnoses. Refine to the core diagnostic concept; drop laterality, "
        "encounter, and episode qualifiers."
    ),
}


def build_code_select_prompt(system: str) -> str:
    """The code-select prompt with system-aware refinement guidance bound in."""
    key = system.upper()
    return PROMPT_CODE_SELECT.format(system=key, system_hint=SYSTEM_REFINE_HINTS.get(key, ""))
