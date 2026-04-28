# Anamnesis Evaluation Corpus v1

## Purpose

This corpus exists to evaluate clinical fact extraction systems against synthetic clinical notes drawn from three common specialty contexts — cardiology, emergency department, and neurology. It is a held-out evaluation asset, intentionally content-distinct from the Anamnesis demo patient bundle (`data/demo_patient/`). A reviewer can point any extraction system (whether the Anamnesis pipeline or a third-party MCP) at these 18 notes, compare its output against the per-note label JSON, and derive recall, precision, false-positive rate, and code-accuracy metrics.

## Composition

18 notes total, one patient per note, distributed as follows:

| Specialty | Clean | Messy | Trap | Total |
|-----------|-------|-------|------|-------|
| Cardiology | 2 (C1, C2) | 2 (C3, C4) | 2 (C5, C6) | 6 |
| Emergency Department | 2 (E1, E2) | 2 (E3, E4) | 2 (E5, E6) | 6 |
| Neurology | 2 (N1, N2) | 2 (N3, N4) | 2 (N5, N6) | 6 |

Tiers:
- **Clean** (3,500–5,500 chars): well-structured, specialty-appropriate detail; no surprises.
- **Messy** (1,200–3,000 chars): realistic EMR variation — abbreviations, dictation flavor, sparse sections.
- **Trap** (3,500–5,000 chars): clean format but contain a deliberate failure-mode signal that naive extractors will mis-handle.

See `manifest.json` for computed totals (total chars, per-category fact counts, per-trap-type non-fact counts, code reference size).

## What this corpus does NOT claim

- **Not real clinical data.** Every note is synthetic. Any resemblance to a real patient, provider, or institution is coincidental.
- **No PHI.** All identifiers (names, MRNs, DOBs, addresses, NPIs) are obviously fictional.
- **Single-annotator labels.** Labels were produced by the Anamnesis project team. There is no inter-rater reliability data. Do not interpret label agreement as a ground-truth indicator for a clinical decision-support system.
- **Not a substitute for clinician validation.** Any extraction system evaluated against this corpus must still be validated against a clinician-reviewed, real-world dataset before production use.
- **English-only, US-centric.** Units, drug formularies, guideline references, and coding conventions (ICD-10-CM, US-edition SNOMED CT) reflect US practice as of 2026.
- **Limited specialty coverage.** Three specialties, roughly selected to match the Anamnesis demo scope. The corpus does not cover obstetrics, oncology, psychiatry, pediatrics beyond a single ED note, surgery, or primary care chronic-disease management.
- **Limited size.** 18 notes is small. The corpus is designed to surface failure modes qualitatively, not to drive high-power statistical claims.

## Construction methodology

Each note was drafted by hand, one at a time, in interleave order across specialties (C1 → E1 → N1 → C2 → ...) to prevent voice convergence. Every clinical detail (diagnosis, drug, dose, lab, score) that became a labeled fact had its terminology code verified against an authoritative browser *before* the prose was committed:

- **SNOMED CT**: SNOMED International browser (`browser.ihtsdotools.org`)
- **ICD-10-CM**: NLM Clinical Tables API and CMS 2026 tabular
- **LOINC**: Regenstrief LOINC search (`loinc.org/{code}/`)
- **RxNorm**: NLM RxNav (`mor.nlm.nih.gov/RxNav/`)

Every code used anywhere in a label file is registered in `code-reference.json` with its system, code, display, source URL, verification date, and list of labels that reference it. The `validate_corpus.py` script asserts that every labeled code resolves to a reference entry and that no reference entry is unused.

Labels were produced immediately after each note was drafted. Every `verbatim_span` in a label is a character-for-character substring of its note (enforced by `validate_corpus.py` check 5a). Content distinctness from the Anamnesis demo patient (`data/demo_patient/anamnesis-demo-bundle.json`) is enforced by a banned-token regex run across all notes.

## Label schema

Each label file (`labels/{NoteID}-{specialty}-{slug}.json`) conforms to:

```json
{
  "note_id": "C1",
  "filename": "C1-cardiology-stable-angina-followup.txt",
  "specialty": "cardiology",
  "tier": "clean",
  "patient_pseudo_demographics": {
    "age": 58, "sex": "female", "race": "black-or-african-american", "ethnicity": "non-hispanic"
  },
  "expected_facts": [
    {
      "id": "C1-F1",
      "category": "condition",
      "verbatim_span": "<exact substring of the note>",
      "expected_codes": [
        {"system": "SNOMED", "code": "<verified>", "display": "<verified>"},
        {"system": "ICD-10", "code": "<verified>", "display": "<verified>"}
      ],
      "expected_attributes": {
        "clinicalStatus": "active",
        "verificationStatus": "confirmed",
        "category": "problem-list-item"
      },
      "section": "ASSESSMENT AND PLAN",
      "notes": "Why this is a fact, as judged by the labeler."
    }
  ],
  "expected_non_facts": [
    {
      "id": "C1-N1",
      "trap_type": "negation",
      "verbatim_span": "<exact substring>",
      "should_not_produce": "Condition: Left main coronary artery disease",
      "rationale": "Explicitly negated in HPI."
    }
  ],
  "metadata": {
    "char_count": 4231,
    "section_count": 12,
    "labeled_by": "team",
    "labeled_date": "2026-04-28"
  }
}
```

**Enumerated values.**

- `specialty` ∈ {`cardiology`, `emergency_department`, `neurology`}
- `tier` ∈ {`clean`, `messy`, `trap`}
- `category` ∈ {`condition`, `medication_request`, `observation`, `procedure`, `allergy_intolerance`, `family_member_history`}
- `trap_type` ∈ {`negation`, `family_attributed`, `ruled_out`, `hypothetical`, `historical_resolved`, `wrong_subject`, `multi_section_consolidation`, `severity_inference`}

**`expected_attributes` by category** (mirrors demo bundle FHIR field names):

- `condition`: `clinicalStatus`, `verificationStatus`, `category`
- `medication_request`: `status`, `intent`, `dose`, `frequency`, `route`
- `observation`: `status`, `category`, `value`
- `procedure`: `status`, `performedDate`
- `allergy_intolerance`: `clinicalStatus`, `verificationStatus`, `criticality`, `severity`
- `family_member_history`: `relationship`, `conditionCode`, `onsetAge`

All fields are optional when the note does not support them, but the validator prefers that extractable attributes be captured.

## Known limitations

- **Synthetic origin.** Language patterns may subtly differ from real EMR prose in ways not captured by the banned-token check.
- **Single annotator.** No inter-rater reliability; no second-reviewer audit pass.
- **Small N.** 18 notes is enough to surface qualitative failure modes but not to power statistical comparisons with tight confidence intervals.
- **Specialty scope.** Matches the Anamnesis demo scope (cardiology, ED, neurology). Generalization to other specialties is not supported.
- **Coding depth.** Conditions are dual-coded (SNOMED + ICD-10) as in the demo bundle; Observations, Procedures, AllergyIntolerance, and MedicationRequest are single-system coded. An extractor that produces different coding conventions may need display-string matching rather than code-exact matching.
- **Date handling.** Encounter dates are scattered across 2024–2026 to avoid temporal clustering, but the "current date" framing assumes the evaluator is running near 2026.

## How to run a system against the corpus

1. **Load each note.** Read `notes/{NoteID}-{specialty}-{slug}.txt` as UTF-8 text.
2. **Run your extractor.** Produce a list of extracted resources (Condition, Observation, MedicationRequest, Procedure, AllergyIntolerance, FamilyMemberHistory).
3. **Load the matching label.** Read `labels/{NoteID}-{specialty}-{slug}.json`.
4. **Compare.**

   Suggested metrics:
   - **Recall**: fraction of `expected_facts` recovered by the extractor.
   - **Precision**: fraction of extractor outputs that correspond to an `expected_facts` entry.
   - **False-positive rate**: fraction of extractor outputs that match an `expected_non_facts` entry (a fact the system should have rejected).
   - **Code accuracy**: when the extractor produces a code, does the `(system, code)` match the labeled codes?
   - **Span localization**: if the extractor records the source span, does it overlap the labeled `verbatim_span`?

5. **Tier-stratified reporting.** Report metrics separately for clean, messy, and trap tiers. Expect the trap tier to dominate false-positive rate for weak extractors.

For the Anamnesis backend specifically, a suggested runner would load each note into the Stage-1 preprocess step and run the full pipeline (Stages 2–6) with `apply=false`, then compare the resulting `AugmentationProposal` records against the labels.

## Versioning

This corpus is **v1.0.0**. Future versions may correct errors in individual notes or labels. Each release publishes the SHA-256 of `manifest.json` as a reproducibility anchor. When citing this corpus in results, include both the version string and the manifest SHA-256 so the exact corpus state can be reproduced.

Reported issues, clarifications, and planned revisions are tracked in the Anamnesis project repository.
