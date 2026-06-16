"""Search-query generation prompt for live-API terminology retrieval.

A terminology search API matches keywords/synonyms against official term
strings — it is NOT semantic. A query phrased like the source note often
misses; a query phrased like the terminology hits. The model emits several
queries; the retriever unions their candidates, so coverage beats precision.
"""

PROMPT_CODE_SEARCH_TERMS = """\
Role
You generate search queries that retrieve the correct {system} concept for a clinical entity from a keyword-based terminology API.

Context
The API matches your query against official term strings by keyword and synonym — it does not understand meaning. A query worded like a clinician's note can return nothing; a query worded like the terminology returns the concept. Every query you emit is run and the candidates are unioned, so favor coverage.

Goal
For each entity, output 2-4 search queries ordered from the most precise terminology phrasing to the barest core concept, so at least one retrieves the correct {system} concept.

Rules
- Phrase queries the way {system} names concepts, not the way clinicians abbreviate.
  - Expand abbreviations to standard nomenclature: HFrEF -> "systolic heart failure"; GERD -> "gastroesophageal reflux disease"; CAD -> "coronary artery disease"; afib -> "atrial fibrillation"; COPD -> "chronic obstructive pulmonary disease".
- Drop modifiers that derail keyword match but do not change the concept: dose, route, frequency, brand; laterality; vessel or lesion counts ("two-vessel"); severity adjectives; "NOS"; "unspecified".
- Keep modifiers that change the code: type 1 vs type 2, acute vs chronic, primary vs secondary, clinical status (active/resolved), specimen or method for labs.
- First query: the most faithful specific phrasing. The LAST query MUST be the bare core concept — the head noun(s) with ALL qualifiers stripped (cause, "due to"/"-induced", onset, site, severity, count) — as a retrieval floor. Terminology titles rarely contain these qualifiers, so the stripped form is what actually matches:
  - "stable angina pectoris in the setting of CAD" -> "angina pectoris"
  - "post-stroke fatigue" -> "fatigue"
  - "ACE-inhibitor-induced cough" -> "cough"
- System phrasing:
  - icd10: formal disease titles, e.g. "Gastro-esophageal reflux disease", "Systolic heart failure".
  - snomed: clinical concept names, e.g. "Coronary arteriosclerosis", "Atrial fibrillation".
  - rxnorm: ingredient alone, and ingredient + strength; no route, frequency, or brand.
  - loinc: analyte plus specimen or system, e.g. "Hemoglobin A1c", "LDL cholesterol", "Troponin I cardiac".
- Never output codes. Never add facts the entity does not imply.

Stop
Return the structured output.
"""
