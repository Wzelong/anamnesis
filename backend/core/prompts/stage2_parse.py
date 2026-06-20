"""Stage 2 parse + clean prompts — per-resource extraction rules.

Each `PROMPT_PARSE_*` constant is a developer prompt for a single FHIR
resource type. `PROMPT_CLEAN` is the within-note dedup / discard pass that
runs after parse. `PROMPTS_BY_TYPE` maps `RESOURCE_TYPES` -> parse prompt
for the dispatch in `extraction.py`.
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
- Include when the snippet names a disease, diagnosis, or problem AND uses assertive framing ("has", "diagnosed with", "history of", "presents with"). Emit with `negated=false` (default).
- SDOH exception: social or behavioral problems (food insecurity, housing instability, medication underdosing, financial hardship) may be included without an assertive verb.
- Exclude: staging (TNM, AJCC, grade), pathology or lab markers, procedures.
- Negation handling — emit a NAMED, SPECIFIC condition with `negated=true` when the snippet asserts the patient does NOT have it, has resolved it, or it has been ruled out:
  - "patient denies hypertension" → emit hypertension with `negated=true`
  - "no evidence of CHF on workup" → emit CHF with `negated=true`
  - "HTN resolved", "no longer has X" → emit X with `negated=true`
  - "ruled out PE" → emit pulmonary embolism with `negated=true`
  This is for conflict detection against the chart (existing active record vs. note-stated absence). Do NOT emit broad negative review-of-systems items ("denies chest pain", "no fever") — only specific named conditions.
- Exclude anatomical findings from procedures (e.g. "60% mid-LAD stenosis", "70% proximal RCA stenosis") — these are quantitative Observations from a catheterization or imaging study, not standalone diagnoses. Only emit the named disease ("coronary artery disease"), not its component lesions.
- Exclude allergies and intolerances ("allergic to penicillin", "NKDA", substance reactions) → these belong to AllergyIntolerance.
- Exclude family members' conditions ("family history of CAD", "father had MI") → these belong to FamilyMemberHistory. The family member's disease is not a patient Condition.
- Exclude tobacco use, smoking status, substance use, alcohol use → these are social-history Observations. Exception: only emit when the note frames it as a coded diagnosis (e.g. ICD line "F17.210 Nicotine dependence").
- Exclude ICD-10 / billing code lines that merely relabel an already-extracted condition — do not create a second item from the billing summary.
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
- `reasoning` is one short phrase that includes the item name and what triggered the extraction (e.g. "diagnosed with stable angina pectoris", "found 60% mid-LAD stenosis on cath"). Always include the noun phrase. Never emit a bare connector ("in the setting of", "due to", "secondary to") on its own — connectors signal a split, but the reasoning must still name the item.

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

Certainty
- definite: assertively stated ("diagnosed with", "confirmed", "has", "presents with").
- probable: strongly implied but not explicit ("consistent with", "likely", continuation of known condition).
- uncertain: hedged, vague, or secondhand ("? possible", "patient reports", "unconfirmed", "rule out").

Code search queries
- Emit `code_queries`: 2-4 short search strings that retrieve this concept from a keyword-based medical terminology (SNOMED, ICD-10). Phrase them the way the terminology names concepts, not the way the note abbreviates.
- Expand abbreviations to standard nomenclature (HFrEF -> "systolic heart failure", GERD -> "gastroesophageal reflux disease", CAD -> "coronary artery disease").
- Drop modifiers that derail keyword match but not the concept: laterality, vessel or lesion counts, severity adjectives, "NOS", "unspecified".
- Keep modifiers that change the code: type 1 vs type 2, acute vs chronic, primary vs secondary.
- The LAST query MUST be the bare core concept: the head noun(s) with ALL qualifiers stripped (cause, "due to"/"-induced", onset, site, severity, count), as a retrieval floor. Terminology titles rarely contain these qualifiers, so a stripped fallback is what actually matches:
  - "stable angina pectoris in the setting of CAD" -> last query "angina pectoris"
  - "post-stroke fatigue" -> last query "fatigue"
  - "ACE-inhibitor-induced cough" -> last query "cough"
- Order from the most precise terminology phrasing to that barest core concept. Never include codes.

Stop
Return the structured output. Do not deduplicate — the cleaner handles that.
"""


# NOTE for maintainers: the "current-value preference" rule below (single item
# when the same observation appears with multiple values) is a tactical
# accommodation for reconcile.py:_match_observation, which keys matching on
# LOINC code only. It cannot represent context-distinguished pairs like
# home-BP vs clinic-BP, pre-op vs post-op A1c, or pain-on-arrival vs
# pain-post-treatment. Once the reconciler grows context awareness (LOINC
# subcode, category, or effective_date discrimination), revisit this rule and
# allow multiple observations of the same type when they carry distinct
# context — extraction shouldn't drop information the downstream can use.
PROMPT_PARSE_OBSERVATION = f"""\
Role
Clinical observation parser. Extract measurements, findings, and social-history facts from a sentence snippet.

Goal
One item per distinct observation. Separate numeric value from its unit whenever both are present.

Include only observations that are clinically significant — abnormal, decision-driving, or specifically called out by the clinician:
- Abnormal vitals explicitly flagged as elevated, uncontrolled, low, or out-of-range.
- Labs the note highlights as abnormal, at-goal, above-goal, or that drive a clinical decision.
- Clinical scores and screenings: PHQ-2, MoCA, A1c, LDL, GCS, staging.
- Imaging findings with clinical significance (positive findings, incidental findings requiring follow-up).
- Social and behavioral status facts in the USCDI social-determinants set: tobacco use, alcohol use, substance or drug use, occupation, and sexual orientation. These have dedicated US Core observation profiles, so capture them as standing status facts even when stated as routine history rather than tied to a decision — this is the one exception to the clinical-significance filter above. `name` is the status label ("occupation", "alcohol use", "sexual orientation", "tobacco use"); `value` is the stated fact ("welder", "2 drinks/day", "former smoker").

Exclude — do not extract:
- Administrative data: arrival time, triage level, ESI, bed assignment, disposition time.
- Demographic facts that belong on other resources, not Observation: marital status, religion, primary language, contact information, living arrangement. (Occupation and sexual orientation ARE captured as social-history observations — see the include list above.)
- Pertinent negatives: any finding where the value is "absent", "negative", "none", "unremarkable", "within normal limits", "no evidence of", "not seen", "denied". This is a hard rule — if the observation's value would be "absent" or "negative", do not emit it.
- Routine normal exam findings: "well-appearing", "NSR", "clear to auscultation", "symmetric pulses", "normal axis", "oral intake tolerated".
- Routine normal vitals: HR, RR, SpO2, Temp within normal range and not flagged by the clinician. A BP like 138/82 in an ED note where it is not called out as elevated is routine.
- Bulk normal lab panels: when the note says a panel is "within normal limits" or "unremarkable", do not extract individual normal values. Only extract individual labs that are abnormal or that the note specifically discusses as decision-driving.
- Duplicate representations of the same measurement (e.g. "Troponin < 0.012 ng/mL" and "Troponin negative" are the same — emit only the quantitative version). Similarly, "pain intensity 4" and "Pain 4/10" are the same — emit once.
- Care-plan targets and goals: "BP goal < 130/80", "LDL target < 70" — these are treatment targets, not measured observations.
- Procedures or events described as observations: "cardiac catheterization performed", "cardiology evaluation" — these belong to Procedure, not Observation.
- Named diseases or diagnoses: "coronary artery disease: two-vessel" is a Condition, not an Observation. Quantitative measurements from that procedure (e.g. "60% stenosis", "LVEF 55%") are valid observations; the disease label is not.
- Temporal references that are not measurements: "quit ~3 months ago" is context for the smoking status, not a separate observation.
- Family history (belongs to FamilyMemberHistory).

Rules
- `name` preserves the exact token from the snippet, including abbreviations: "BP" stays "BP". Put the expansion in `full_name` ("blood pressure"). Same for "LDL", "A1c", "BMI", etc.
- For named clinical scoring instruments (MoCA, PHQ-2, PHQ-9, GAD-7, GCS, NIHSS, MDS-UPDRS, NYHA, MMSE, CHA2DS2-VASc, etc.), `name` MUST be the instrument name (e.g. "MoCA", "MDS-UPDRS Part III", "NYHA"), not a generic word like "Score" or "Total". Resolve the instrument name from any nearby sentence that introduces the score — if sentence [N] says "MoCA administered" and sentence [N+1] says "Score 21/30", emit one item with name="MoCA", full_name="Montreal Cognitive Assessment", value="21/30", source_sentences=[N, N+1]. Always emit the score; never skip it because the instrument name is in a different sentence. Put the expanded title in `full_name`.
- When the same observation appears multiple times in the snippet with different values (e.g. "LVEF 30% at baseline, now 40%", "A1c was 8.2%, today 7.1%"), emit ONE item carrying the most recent / encounter-current value. Do not emit the historical anchor as a separate item or use it as the canonical value.
- Value + unit: split into `value` and `unit` when a unit is stated. "BP 145/100 mmHg" → name="BP", value="145/100", unit="mmHg". For qualitative values ("positive", "normal", "stage 3A"), leave `unit` null.
- Slash-delimited markers are two observations: "ER/PR positive" → two items, one "ER", one "PR".
- Keep fractions and staging intact: "pT2N1M0", "2/26".
- Use "positive" / "negative" for test results and "present" / "absent" for findings. Do not use "yes" / "no".
- If both a qualitative finding and a quantitative measurement are present, emit separate items.
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

<example>
Snippet:
[12] Depression screening: PHQ-9 completed via tablet.
[13] Total 14/27. Patient endorses sleep disturbance and anhedonia.
Output: name="PHQ-9", full_name="Patient Health Questionnaire-9", value="14/27", category="survey", codeset_hint="LOINC", source_sentences=[12, 13]. The total score MUST be emitted as one item; do not skip it because the score sentence does not name the instrument.
</example>

<example>
Snippet:
[34] Latest A1c (2026-04-12): 6.8%, down from 9.4% at last year's annual visit.
Output: name="A1c", full_name="hemoglobin A1c", value="6.8", unit="%", category="laboratory", codeset_hint="LOINC", source_sentences=[34]. Use the current encounter value (6.8), not the historical baseline (9.4).
</example>

<example>
Snippet: [8] Social history: works as a welder; drinks 3-4 beers on weekends; never smoker.
Output: three social-history items.
  - name="occupation", value="welder", category="social-history".
  - name="alcohol use", value="3-4 beers on weekends", category="social-history".
  - name="tobacco use", value="never smoker", category="social-history".
</example>

<example>
Snippet: [21] Patient identifies as gay and lives with his partner.
Output: name="sexual orientation", value="gay", category="social-history". Living arrangement and partner status are demographic context — do not emit.
</example>

Certainty
- definite: directly measured or reported with a specific value ("BP 142/86", "A1c 7.2%", "HR 72").
- probable: value implied or approximate ("elevated blood pressure", "heart rate in the 70s").
- uncertain: reported secondhand or hedged ("patient states occasional alcohol use", "per outside records").

Code search queries
- Emit `code_queries`: 2-4 short search strings that retrieve this observation from a keyword-based terminology (LOINC, SNOMED). Phrase them as the terminology names the analyte plus specimen or system: "Hemoglobin A1c", "LDL cholesterol", "Troponin I cardiac".
- Expand abbreviations (A1c -> "hemoglobin A1c"); drop values, units, and qualifiers. Keep specimen or method when it changes the code.
- The LAST query MUST be the bare analyte/finding with qualifiers stripped, as a retrieval floor ("LDL cholesterol, fasting" -> "LDL cholesterol"). Never include codes.

Stop
Return the structured output.
"""


PROMPT_PARSE_MEDICATION = """\
Role
Medication parser. Extract medication orders and changes from a sentence snippet.

Goal
One item per distinct medication. Preserve dose, frequency, and route. Reflect the action verb in `status` and `intent`.

Rules
- Only emit a medication when the snippet contains an explicit, drug-specific action verb OR a continuation-state phrase. Action verbs: start, initiate, continue [drug name], hold, restart, prescribed, ordered, increase to, decrease to, stop, discontinue, titrate, received, administered, given, dosed. Continuation-state phrases (assessment / plan style): "on [drug]", "taking [drug]", "treated with [drug]", "managed with [drug]", "anticoagulated with [drug]" — these confirm the patient is currently on the named drug and treat as a continuation order. A blanket "continue all home medications" is not drug-specific — it must not yield items.
- A valid item must name a specific identifiable drug (e.g. "metoprolol", "omeprazole", "lisinopril"). Generic references without a drug name — "home medications", "heart medication", "current regimen", "same meds" — must not yield items.
- Home-medication reconciliation lists enumerate what the patient takes. They are not orders. If the snippet is a reconciliation block ("HOME MEDICATIONS - Lisinopril 10 mg, Atorvastatin 40 mg...") paired only with "continue all home medications", emit zero items — no individual drug was started, changed, or stopped.
- `name` is the full clinical drug as stated: include strength and form when available ("lisinopril 20 mg oral tablet", "metoprolol succinate 25 mg"). Do not truncate to just the ingredient.
- Action-verb mapping:
  - "start", "initiate", "begin", "prescribed", "ordered" → status=active, intent=order.
  - "continue", "already on", "on [drug]", "taking", "treated with", "managed with", "anticoagulated with" → status=active, intent=order. Treat as a continuation order: the patient is currently on the named drug and the visit confirms it.
  - "increase to", "decrease to", "titrate to" → status=active, intent=order; reflect the new dose in `dose`.
  - "restart", "resume" → status=active, intent=order; the "same dose" refers to the dose in the referenced sentence — surface that dose in `dose`.
  - "hold" → status=on-hold, intent=order.
  - "stop", "discontinue", "no longer takes", "off" + drug → status=stopped, intent=order. Always emit when explicit — this enables conflict detection against the chart's active medication list.
  - "received", "administered", "given", "dosed" + drug → status=completed, intent=order. Captures one-time administrations during this encounter (typical ED course or inpatient: "Received IV ceftriaxone 2 g x 1 dose", "given IV ketorolac 30 mg"). The dose was actually given, so the medication belongs in the chart as a completed event, not skipped.
  - "plan to start" without an order action → status=draft, intent=plan.
- Separate combination regimens ("lisinopril 10 mg + HCTZ 25 mg") into two items.
- `frequency` captures the dose schedule as stated: "daily", "BID", "q8h", "PRN", "at bedtime".
- `reason` is the clinical indication if stated.
- `source_sentences` lists every [N] the item draws from, including cross-referenced sentences.
- `reasoning` names the trigger phrase ("increase lisinopril to 20 mg").

Examples

<example>
Snippet:
[23] He has continued his home medications.
[29] HOME MEDICATIONS - Lisinopril 10 mg PO daily - Atorvastatin 40 mg PO daily - Metformin 1000 mg PO BID - Aspirin 81 mg PO daily
[97] DISCHARGE MEDICATIONS - Continue all home medications as previously prescribed.
Output: zero items. "Continue all home medications" is a blanket continuation. No individual drug was started, changed, or stopped.
</example>

<example>
Snippet:
[97] DISCHARGE MEDICATIONS - Continue all home medications as previously prescribed.
[98] - New: omeprazole 20 mg PO once daily for 14 days.
Output: one item — omeprazole 20 mg PO. The "New:" tag is an explicit order action.
</example>

<example>
Snippet:
[14] Patient received IV vancomycin 1 g x 1 dose in the ED along with IV normal saline 1 L.
Output: one item — vancomycin 1 g IV, status=completed, frequency="x 1 dose". (IV normal saline is a fluid, not a medication; do not emit.)
</example>

<example>
Snippet:
[18] Received IV fluids (lactated Ringer's 1 L), IV ondansetron 4 mg, IV hydromorphone 0.5 mg, and IV famotidine 20 mg.
Output: three items — ondansetron 4 mg IV, hydromorphone 0.5 mg IV, famotidine 20 mg IV. All status=completed (one-time ED administrations). Skip lactated Ringer's (fluid, not medication).
</example>

<example>
Snippet:
[27] 1. AFib anticoagulated w/ warfarin (INR goal 2-3). Last INR 2.4. Continue current dose.
Output: one item — warfarin, status=active (continuation). The "anticoagulated w/" phrase confirms the patient is currently on warfarin. The continuation is established by the assessment-style sentence; do not skip just because there is no explicit "continue [drug]" verb at the start.
</example>

Certainty
- definite: explicit order or active prescription ("start metoprolol 25 mg", "continue lisinopril", "new: omeprazole").
- probable: medication mentioned in context implying use ("on aspirin", "home medications include").
- uncertain: dose or drug unclear ("started on some beta blocker", "may have been on a statin").

Code search queries
- Emit `code_queries`: 2-4 search strings to retrieve this drug from RxNorm. Use the ingredient alone and the ingredient + strength; drop route, frequency, and brand.
  - "lisinopril 20 mg oral tablet" -> ["lisinopril 20 mg", "lisinopril"]
- Never include codes.

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
  - "prior", "previous", "earlier", "outside facility" + named procedure with a stated date → completed. The procedure happened before this encounter; record it with the stated date so it lands in the chart's procedure history.
  - "ongoing", "in progress" → in-progress.
  - "scheduled", "planned", "ordered" (without a performed date) → preparation.
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

<example>
Snippet: [55] Prior colonoscopy (2024-08, outside facility): two tubular adenomas removed; otherwise unremarkable.
Output: name="colonoscopy", performed="2024-08", status=completed, outcome="two tubular adenomas removed; otherwise unremarkable". "Prior" with a stated date is a completed procedure that belongs in the chart history.
</example>

Certainty
- definite: procedure clearly performed ("catheterization was performed", "CT obtained", "ECG showed").
- probable: procedure referenced but details limited ("had a scan", "imaging consistent with").
- uncertain: procedure mentioned vaguely or from outside records ("reportedly had surgery", "per outside records").

Code search queries
- Emit `code_queries`: 2-4 search strings that retrieve this procedure from SNOMED, phrased the way the terminology names it ("Left heart catheterization", "Computed tomography of abdomen").
- Expand abbreviations; drop laterality and incidental qualifiers; keep the core procedure.
- The LAST query MUST be the bare procedure name with qualifiers stripped, as a retrieval floor ("diagnostic left heart catheterization" -> "heart catheterization"). Never include codes.

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

Certainty
- definite: confirmed allergy with documented reaction ("confirmed penicillin allergy — anaphylaxis").
- probable: reported allergy with plausible history ("patient reports rash with amoxicillin as a child").
- uncertain: vague or secondhand ("thinks they might be allergic", "family says patient had a reaction").

Code search queries
- Emit `substance_queries`: 2-4 search strings for the substance, phrased as a terminology names it ("penicillin", "penicillin antibiotic"; "sulfonamide", "sulfa"). The LAST must be the bare substance class/ingredient with brand and formulation stripped, as a retrieval floor ("amoxicillin-clavulanate" -> "amoxicillin").
- Emit `reaction_queries`: 2-4 search strings for the reaction when one is stated ("anaphylaxis", "urticaria"); leave empty if no reaction is given.
- Expand abbreviations; drop non-essential modifiers; never include codes.

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

Certainty
- definite: specific relative with specific condition ("father had MI at age 52").
- probable: relative and condition named but details vague ("family history of heart disease").
- uncertain: secondhand or vague ("patient thinks a grandparent may have had diabetes").

Code search queries
- For each entry in `conditions`, emit `queries`: 2-4 search strings that retrieve that condition from SNOMED, phrased the way the terminology names it (expand abbreviations, drop severity and laterality, keep type and acuity). The LAST must be the bare core concept with all qualifiers stripped ("early-onset coronary artery disease" -> "coronary artery disease"), as a retrieval floor. Never include codes.

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
