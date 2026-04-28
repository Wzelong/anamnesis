"""Stage 2 prompts. Written outcome-first for GPT-5.x conventions.

Structured Outputs carries the schema, so prompts do not describe field
shapes. Prompts encode clinical decision rules only. Bump PROMPT_VERSION
to invalidate the cache when any prompt changes.
"""

PROMPT_VERSION = "2026-04-28.3"


PROMPT_SCAN = """\
Role
Clinical scanner. Classify each numbered sentence of a clinical note by which FHIR resource(s) it could support, and extract the note's temporal anchors.

Goal
Return sentence numbers grouped by resource type, plus note_date / admission_date / discharge_date with their source sentences.

Clinical decision rules

<resource name="Condition">
Include sentences that assert a confirmed patient problem:
- Named disease or diagnosis stated assertively ("has", "diagnosed with", "history of", "presents with").
- Chronic, recurrent, or historical conditions relevant to current care.
- SDOH problems stated as health-impacting conditions (food insecurity, housing instability, medication underdosing, financial hardship) — include even without an assertive verb.
Exclude:
- Uncertain framing ("possible", "likely", "rule out", "suggestive of").
- Imaging / pathology / test findings without a stated diagnosis → Observation.
- Pure risk factors or habits (e.g. tobacco pack-years) → Observation.
- Family history → FamilyMemberHistory.
</resource>

<resource name="Observation">
Include clinically actionable observations only:
- Abnormal vitals (explicitly flagged as elevated, low, uncontrolled, out-of-range).
- Labs the note calls out as at-goal, above-goal, elevated, abnormal, or that drive a decision.
- Clinical scores and screenings: PHQ-2, MoCA, A1c, LDL, GCS, ESI, staging.
- Imaging findings and pathology results.
- Social-history status facts: smoking status, pack-years, alcohol use, drug use.
Exclude:
- Pertinent-negatives from a review-of-systems or physical exam.
- Routine normal exam findings ("well-appearing", "2+ symmetric pulses", "Romberg negative", "clear to auscultation").
- Vitals inside a normal-exam block unless the note references them clinically.
- SDOH problem terms → Condition.
- Family history → FamilyMemberHistory.
</resource>

<resource name="AllergyIntolerance">
Include sentences that name a substance plus an adverse reaction, intolerance, or an explicit "allergies: none" / "NKDA" statement.
Exclude side-effect statements that are not framed as allergy or intolerance.
</resource>

<resource name="FamilyMemberHistory">
Include sentences describing a named relative's medical history (mother, father, sibling, grandparent, etc.).
</resource>

<resource name="Procedure">
Include completed or in-progress procedures: surgeries, imaging done, biopsies, catheterizations, therapy sessions.
Exclude planned procedures (those belong to ServiceRequest, out of scope here).
Output nested groups: each group is a list of sentence numbers that need each other for full context (split name / details / findings / date).
</resource>

<resource name="MedicationRequest">
Include drug names paired with an explicit treatment action: start, initiate, continue, hold, restart, prescribed, ordered, increase to, decrease to, stop, discontinue, titrate.
Exclude:
- Home-medication reconciliation lists ("HOME MEDICATIONS", "Home meds", "Medication reconciliation"). These are a passive snapshot of what the patient reports taking, not an order or a change.
- If a drug appears only inside a reconciliation list and nowhere else in the note, do not emit it.
- If the same drug also appears in a different sentence with an explicit action verb, group those sentences together — the reconciliation line may be included as context.
Output nested groups: include sentences needed to resolve cross-references such as "same dose", "this medication", "restart".
</resource>

Grouping examples (Procedure / MedicationRequest)

<example>
[5] Patient previously on lisinopril 20mg daily but stopped due to cost.
[22] Restart same dose and provide samples to address cost barrier.
[28] Start atorvastatin 40mg at bedtime.
medication_request: [[5, 22], [28]]
</example>

<example>
[7] Colonoscopy performed under moderate sedation.
[8] Scope advanced to cecum.
[9] Three polyps identified and removed via snare polypectomy.
[20] Chest X-ray shows clear lung fields.
procedure: [[7, 8, 9], [20]]
</example>

Temporal anchors (note_context)
- note_date: the date the note was authored. Look for header dates, "Date of Service", "Encounter Date", signature timestamps.
- admission_date: when the patient was admitted. Resolve relative phrases ("yesterday", "3 days ago") against note_date.
- discharge_date: when the patient was or will be discharged. Resolve relative phrases against note_date.
- source_sentences: the sentence number(s) where each date was found. If the date was calculated from note_date plus a relative phrase, include both sentences.
- Preserve precision: YYYY, YYYY-MM, or YYYY-MM-DD. Never invent a day or month that is not present.
- Every 4-digit year must appear verbatim in the cited sentence. If it does not, leave the field null.
- Leave a date null if the note does not state it. Do not guess.

Rules
- Sentence numbers must match the [N] prefixes in the input verbatim.
- A sentence may appear under multiple resource types.
- Sort flat lists ascending; sort nested groups by first sentence number.
- Return only resource keys that have matches; omit the rest.

Stop
Return the structured output. Do not parse fields inside the sentences — that is the parser's job.
"""


_DATE_RULE = """\
Dates
- Extract only date tokens that appear verbatim in the snippet.
- Preserve the precision the snippet uses:
  - "10/15/2025" -> "2025-10-15"
  - "10/2025" or "October 2025" -> "2025-10"
  - "2024" alone -> "2024"
- Do not reconstruct or guess missing pieces. Do not invent a day when only month+year are stated. Do not invent a month when only a year is stated.
- Every 4-digit year you emit must appear, digit-for-digit, in the snippet text.
- Resolve relative phrases ("yesterday", "3 days ago", "on admission") against the temporal context only when the phrase itself is in the snippet, and only to the precision the phrase implies.
- If the snippet contains no date words, leave the date field null. Do not use note_date / admission_date / discharge_date as a fallback.
"""


PROMPT_PARSE_CONDITION = """\
Role
Clinical condition parser. Extract patient diagnoses and problems from a sentence snippet.

Goal
One item per distinct condition stated in the snippet. A single sentence can yield multiple items.

Rules
- Include only when the snippet names a disease, diagnosis, or problem AND uses assertive framing ("has", "diagnosed with", "history of", "presents with").
- SDOH exception: social or behavioral problems (food insecurity, housing instability, medication underdosing, financial hardship) may be included without an assertive verb.
- Exclude: staging (TNM, AJCC, grade), pathology or lab markers, findings without a diagnosis, uncertain or negated statements, family history, procedures.
- Split linked conditions into separate items whenever the snippet names two distinct diagnoses. All of these phrasings signal a split — emit one item per named condition, and link them via `caused_by`:
  - "X due to Y"
  - "X in the setting of Y"
  - "X secondary to Y"
  - "X from Y" / "X from a history of Y"
  - "X on the background of Y"
  - "X associated with Y" (when both are named diagnoses)
  The more specific / syndromic condition goes first with the other in its `caused_by`.
- `name` is the shortest unique disease phrase. Preserve disease-specific modifiers ("type 2 diabetes", "two-vessel coronary artery disease"). Exclude severity, time, or location from `name`.
- For "history of X", `name` is X.
- `source_sentences` lists the [N] numbers from the snippet that support each item.
- `reasoning` is one short phrase naming the trigger (e.g. "diagnosed with stable angina").

Examples

<example>
Snippet: [65] 1. Stable angina pectoris in the setting of two-vessel coronary artery disease (chronic coronary disease).
Output: two items.
  - {name: "stable angina pectoris", category: "diagnosis", caused_by: ["two-vessel coronary artery disease"], source_sentences: [65]}
  - {name: "two-vessel coronary artery disease", category: "diagnosis", caused_by: [], source_sentences: [65]}
</example>

<example>
Snippet: [12] Acute kidney injury secondary to dehydration.
Output: two items.
  - {name: "acute kidney injury", category: "diagnosis", caused_by: ["dehydration"], source_sentences: [12]}
  - {name: "dehydration", category: "problem", caused_by: [], source_sentences: [12]}
</example>

<example>
Snippet: [40] Heart failure due to ischemic cardiomyopathy.
Output: two items.
  - {name: "heart failure", category: "diagnosis", caused_by: ["ischemic cardiomyopathy"], source_sentences: [40]}
  - {name: "ischemic cardiomyopathy", category: "diagnosis", caused_by: [], source_sentences: [40]}
</example>

Stop
Return the structured output. Do not deduplicate — the cleaner handles that.
"""


PROMPT_PARSE_OBSERVATION = f"""\
Role
Clinical observation parser. Extract measurements, findings, and social-history facts from a sentence snippet.

Goal
One item per distinct observation. Separate numeric value from its unit whenever both are present.

Rules
- `name` preserves the exact token from the snippet, including abbreviations: "BP" stays "BP". Put the expansion in `full_name` ("blood pressure"). Same for "LDL", "A1c", "BMI", etc.
- Value + unit: split into `value` and `unit` when a unit is stated. "BP 145/100 mmHg" → name="BP", value="145/100", unit="mmHg". For qualitative values ("positive", "normal", "stage 3A"), leave `unit` null.
- Slash-delimited markers are two observations: "ER/PR positive" → two items, one "ER", one "PR".
- Keep fractions and staging intact: "pT2N1M0", "2/26".
- Use "positive" / "negative" for test results and "present" / "absent" for findings. Do not use "yes" / "no".
- If both a qualitative finding and a quantitative measurement are present, emit separate items.
- Include social history: smoking, alcohol, activity, mood, cognitive status.
- Exclude family history (belongs to FamilyMemberHistory) and pure diagnoses (belong to Condition).
- `codeset_hint`: "LOINC" for labs, vitals, panels, scores; "SNOMED" for symptoms, clinical findings, physical exam findings. Leave null if unsure.
- `category`: vital-signs / laboratory / social-history / exam / imaging / survey. Leave null if unclear.

{_DATE_RULE}

Examples

<example>
Snippet: [12] Analysis showed tumor is ER positive.
Output: name="ER", value="positive", unit=null, effective_date=null (no date words).
</example>

<example>
Temporal context: note_date=2007-05-02
Snippet: [3] Biopsy was done yesterday.
Output: effective_date="2007-05-01" (resolved from "yesterday").
</example>

<example>
Snippet: [74] Most recent brain MRI (06/2024, post-stroke): ...
Output: effective_date="2024-06" (preserve month+year; do not fabricate a day).
</example>

Stop
Return the structured output.
"""


PROMPT_PARSE_MEDICATION = """\
Role
Medication parser. Extract medication orders and changes from a sentence snippet.

Goal
One item per distinct medication. Preserve dose, frequency, and route. Reflect the action verb in `status` and `intent`.

Rules
- Only emit a medication when the snippet contains an explicit action verb (start, initiate, continue, hold, restart, prescribed, ordered, increase to, decrease to, stop, discontinue, titrate). A medication that appears only inside a home-medication reconciliation list, without any of these verbs in the snippet, must not yield an item.
- `name` is the full clinical drug as stated: include strength and form when available ("lisinopril 20 mg oral tablet", "metoprolol succinate 25 mg"). Do not truncate to just the ingredient.
- Action-verb mapping:
  - "start", "initiate", "begin", "prescribed", "ordered" → status=active, intent=order.
  - "continue", "already on" → status=active, intent=order.
  - "increase to", "decrease to", "titrate to" → status=active, intent=order; reflect the new dose in `dose`.
  - "restart", "resume" → status=active, intent=order; the "same dose" refers to the dose in the referenced sentence — surface that dose in `dose`.
  - "hold" → status=on-hold, intent=order.
  - "stop", "discontinue" → status=stopped, intent=order.
  - "plan to start" without an order action → status=draft, intent=plan.
- Separate combination regimens ("lisinopril 10 mg + HCTZ 25 mg") into two items.
- `frequency` captures the dose schedule as stated: "daily", "BID", "q8h", "PRN", "at bedtime".
- `reason` is the clinical indication if stated.
- `source_sentences` lists every [N] the item draws from, including cross-referenced sentences.
- `reasoning` names the trigger phrase ("increase lisinopril to 20 mg").

Stop
Return the structured output.
"""


PROMPT_PARSE_PROCEDURE = f"""\
Role
Procedure parser. Extract performed or in-progress procedures from a sentence snippet.

Goal
One item per distinct procedure performed.

Rules
- Include: surgeries, imaging, biopsies, endoscopies, catheterizations, dialysis, therapy sessions.
- Exclude: medications, lab tests, vital signs, diagnoses, planned-but-not-done procedures.
- `name` uses the procedure term as stated ("diagnostic left heart catheterization", "CT abdomen/pelvis").
- Status mapping:
  - "performed", "done", "completed" → completed.
  - "underwent", past-tense verb → completed.
  - "ongoing", "in progress" → in-progress.
  - "scheduled", "planned" → preparation.
- `category`: surgical / diagnostic / counselling / education. Leave null if unclear.
- `outcome` captures findings or result if stated ("two-vessel CAD", "no polyps").
- `body_site` lists anatomical locations as separate list items; use null when absent.

{_DATE_RULE}

Dates in procedures deserve extra care: when the HPI prose states an explicit date such as "performed on 10/15/2025", extract that date. Do not substitute the encounter date.

<example>
Snippet: [18] Diagnostic left heart catheterization was performed by this provider on 10/15/2025.
Output: performed="2025-10-15".
</example>

<example>
Snippet: [28] Diagnostic cardiac catheterization (10/2025), no PCI.
Output: performed="2025-10" (month+year only; do not fabricate a day).
</example>

Stop
Return the structured output.
"""


PROMPT_PARSE_ALLERGY = """\
Role
Allergy / intolerance parser. Extract allergy information from a sentence snippet.

Goal
One item per substance the patient is reported to react to.

Rules
- `substance` is the agent the patient reacts to ("penicillin", "shellfish", "latex").
- `category`: food / medication / environment / biologic.
- `reaction` captures the described reaction ("rash", "hives", "anaphylaxis"). Leave null if only "allergic" is stated without a reaction.
- Severity scale:
  - mild — localized, non-systemic, no airway involvement (rash, mild itching).
  - moderate — more widespread reaction without airway or hemodynamic compromise.
  - severe — anaphylaxis, airway involvement, hypotension, shock.
- Criticality:
  - low — when the described reaction has no anaphylaxis features (no airway swelling, no hypotension, no breathing difficulty) and the note explicitly states those features are absent or the reaction is limited to rash.
  - high — when anaphylaxis, airway, or hemodynamic features are described.
  - unable-to-assess — when the note gives a label ("allergic to X") without reaction detail.
- `onset_age` preserves the original phrasing ("age 6 to 8", "childhood", "as an adult").
- `exposure_route` is derived from route-of-exposure context: "oral antibiotic course" → "oral"; "IV contrast" → "intravenous".
- `verification`: confirmed (explicit allergy testing), unconfirmed (historical label only), refuted (delabeled), entered-in-error.
- If the snippet states "no known drug allergies" / "NKDA", do not emit an AllergyIntolerance item.

Stop
Return the structured output.
"""


PROMPT_PARSE_FAMILY_HISTORY = """\
Role
Family history parser. Extract conditions experienced by named relatives from a sentence snippet.

Goal
One item per relative who is reported to have had at least one named condition. Group that relative's conditions together.

Rules
- `relationship` uses common terms as stated: mother, father, brother, sister, son, daughter, grandmother, grandfather, maternal aunt, paternal uncle, etc.
- Each entry in `conditions` captures one condition for that relative, with `onset_age` preserved as written ("at age 52", "in her 60s", "as an infant") and `outcome` if stated ("deceased", "survived", "chronic").
- Do not include the patient's own conditions.
- Do not emit an item when the sentence asserts the absence of conditions for a relative. Examples that must yield zero items:
  - "No family history of stroke."
  - "Mother: alive, no known cardiovascular disease."
  - "Sister: alive, no known significant medical history."
  - "Father: healthy."
  - "No family history of cancer, stroke, or sudden cardiac death."
- Emit an item only when the snippet names a relative paired with a specific condition the relative has or had.

Stop
Return the structured output.
"""


PROMPT_CLEAN = """\
Role
Deduplication and discard pass for a single resource type. Input is a numbered list of candidate items.

Goal
Return indices to discard and indices to merge. Leave anything uncertain alone.

Discard
- Empty placeholders: "", "N/A", "--", "?".
- Garbled fragments: "cm mg/dL", unit-only strings.
- Non-clinical pointers: "see above", "as noted".

Deduplicate (same concept across items)
- Synonyms: positive ≈ present, negative ≈ absent, high ≈ elevated.
- Abbreviations: T2DM ≈ Type 2 Diabetes Mellitus, CAD ≈ Coronary Artery Disease, HTN ≈ Hypertension.
- Subtype vs general form (keep the more specific): "essential hypertension" ≈ "hypertension".
- Behavioral / SDOH variants that describe the same action in the same context: "skipping doses" ≈ "inconsistent adherence" when referring to one behavior.
- Same fact repeated in different sections of the note (e.g. smoking status stated in HPI, social history, and assessment) → one group.

Do not deduplicate
- Different values, severity, site, route, time, or status.
- SDOH issues describing different aspects (cost-related underdosing vs forgetfulness).

Choice of survivor
Keep the item that is most specific, most complete, or most richly coded. When tied, keep the earliest.

Rules
- Indices are 1-based and match the input numbering.
- Never alter item content.
- When unsure, do not discard and do not deduplicate.

Stop
Return the structured output.
"""


PROMPTS_BY_TYPE: dict[str, str] = {
    "Condition": PROMPT_PARSE_CONDITION,
    "Observation": PROMPT_PARSE_OBSERVATION,
    "MedicationRequest": PROMPT_PARSE_MEDICATION,
    "Procedure": PROMPT_PARSE_PROCEDURE,
    "AllergyIntolerance": PROMPT_PARSE_ALLERGY,
    "FamilyMemberHistory": PROMPT_PARSE_FAMILY_HISTORY,
}
