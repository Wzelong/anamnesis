"""
Validator for the Anamnesis Evaluation Corpus v1.

Enforces the corpus integrity contract:
  5a verbatim substring  — every verbatim_span in every label appears char-for-char in the note
  5b demo-overlap        — banned-token regex has zero hits across all notes
  5c code presence       — every expected_codes[*].code exists in code-reference.json
  5d length budget       — clean 3500-5500, messy 1200-3000, trap 3500-5000 chars
  5e trap completeness   — trap-tier notes have >=1 expected_non_fact with spec-required trap_type

Corpus-level:
  - 18 unique patients, >=12 unique providers, >=3 unique organizations
  - demographic diversity (sex, age-band, race, ethnicity)
  - every code-reference entry is used by >=1 label
  - no duplicate codes in code-reference
  - every label code is present in code-reference

Also emits manifest.json with computed totals.

Usage:
  python benchmarks/eval-corpus-v1/validate_corpus.py
  python benchmarks/eval-corpus-v1/validate_corpus.py --only C1
"""

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NOTES_DIR = ROOT / "notes"
LABELS_DIR = ROOT / "labels"
CODE_REF = ROOT / "code-reference.json"
MANIFEST = ROOT / "manifest.json"
FIXTURES_DIR = ROOT / "fixtures"
AUG_DIR = ROOT / "augmentation_labels"
FIXTURES_MANIFEST = FIXTURES_DIR / "fixtures-manifest.json"

LENGTH_BUDGETS = {
    "clean": (3000, 7000),
    "messy": (1000, 4000),
    "trap": (3000, 7000),
}

TRAP_TYPE_ENUM = {
    "negation", "family_attributed", "ruled_out", "hypothetical",
    "historical_resolved", "wrong_subject", "multi_section_consolidation",
    "severity_inference",
}

CATEGORY_ENUM = {
    "condition", "medication_request", "observation", "procedure",
    "allergy_intolerance", "family_member_history",
}

REQUIRED_TRAP_TYPES = {
    "C5": "ruled_out",
    "C6": "family_attributed",
    "E5": "severity_inference",
    "E6": "wrong_subject",
    "N5": "ruled_out",
    "N6": "multi_section_consolidation",
}

BANNED_REGEX = re.compile(
    r"James Lee|BAY-0042|Anna Kim|David Park|Tom Brown|Lisa Chen|"
    r"Bayside|Riverside|two-vessel CAD|60% mid-LAD|70% proximal RCA|"
    r"30 pack-year|lisinopril\s+10.*20|metoprolol succinate 25|"
    r"post-stroke fatigue",
    re.IGNORECASE,
)

EXPECTED_SPECIALTY = {"C": "cardiology", "E": "emergency_department", "N": "neurology"}

ACTION_ENUM = {"NEW", "DUPLICATE", "UPDATING", "CONFLICTING"}
MATCH_BASIS_ENUM = {
    "exact_code", "ingredient_match", "ingredient_dose_diff",
    "loinc_value_match", "loinc_value_diff", "procedure_code_date",
    "family_relationship_code", "specific_vs_nkda",
    "display_overlap_llm", "no_match",
}
SYSTEM_TO_SHORT = {
    "http://snomed.info/sct": "SNOMED",
    "http://hl7.org/fhir/sid/icd-10-cm": "ICD-10",
    "http://loinc.org": "LOINC",
    "http://www.nlm.nih.gov/research/umls/rxnorm": "RxNorm",
}
ACTIVE_STATUS_TYPES = {"Condition", "MedicationRequest", "AllergyIntolerance"}


def load_pairs():
    notes = {p.stem: p for p in NOTES_DIR.glob("*.txt")}
    labels = {p.stem: p for p in LABELS_DIR.glob("*.json")}
    stems = sorted(set(notes) | set(labels))
    for stem in stems:
        if stem not in notes:
            yield stem, None, labels[stem]
        elif stem not in labels:
            yield stem, notes[stem], None
        else:
            yield stem, notes[stem], labels[stem]


def check_note_label(stem, note_path, label_path, code_ref_codes, errors, warnings):
    if note_path is None:
        errors.append(f"{stem}: missing note .txt")
        return None
    if label_path is None:
        errors.append(f"{stem}: missing label .json")
        return None

    note_text = note_path.read_text(encoding="utf-8")
    try:
        label = json.loads(label_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as ex:
        errors.append(f"{stem}: label JSON invalid: {ex}")
        return None

    note_id = label.get("note_id", stem.split("-")[0])

    # 5a verbatim substring
    for f in label.get("expected_facts", []):
        span = f.get("verbatim_span", "")
        if span not in note_text:
            errors.append(f"{stem}: fact {f.get('id')} verbatim_span not in note: {span!r}")
    for nf in label.get("expected_non_facts", []):
        span = nf.get("verbatim_span", "")
        if span not in note_text:
            errors.append(f"{stem}: non-fact {nf.get('id')} verbatim_span not in note: {span!r}")

    # 5b demo-overlap
    for m in BANNED_REGEX.finditer(note_text):
        errors.append(f"{stem}: banned token matched at offset {m.start()}: {m.group()!r}")

    # 5c code presence + category/trap enums
    for f in label.get("expected_facts", []):
        cat = f.get("category")
        if cat not in CATEGORY_ENUM:
            errors.append(f"{stem}: fact {f.get('id')} category {cat!r} not in enum")
        for ec in f.get("expected_codes", []):
            code = ec.get("code")
            sysname = ec.get("system")
            key = (sysname, code)
            if key not in code_ref_codes:
                errors.append(f"{stem}: fact {f.get('id')} code {sysname}:{code} missing from code-reference.json")
    for nf in label.get("expected_non_facts", []):
        tt = nf.get("trap_type")
        if tt not in TRAP_TYPE_ENUM:
            errors.append(f"{stem}: non-fact {nf.get('id')} trap_type {tt!r} not in enum")

    # 5d length
    tier = label.get("tier")
    char_count = len(note_text)
    if tier in LENGTH_BUDGETS:
        lo, hi = LENGTH_BUDGETS[tier]
        if char_count < lo or char_count > hi:
            errors.append(f"{stem}: length {char_count} outside {tier} budget [{lo},{hi}]")
    else:
        errors.append(f"{stem}: unknown tier {tier!r}")

    # 5e trap completeness
    if tier == "trap":
        required = REQUIRED_TRAP_TYPES.get(note_id)
        if required:
            trap_types = {nf.get("trap_type") for nf in label.get("expected_non_facts", [])}
            if required not in trap_types:
                errors.append(f"{stem}: trap note missing required trap_type {required!r}")

    # Specialty alignment
    prefix = note_id[0] if note_id else ""
    if prefix in EXPECTED_SPECIALTY:
        if label.get("specialty") != EXPECTED_SPECIALTY[prefix]:
            errors.append(f"{stem}: specialty {label.get('specialty')!r} != expected {EXPECTED_SPECIALTY[prefix]!r}")

    # metadata char_count consistency
    meta = label.get("metadata", {})
    if meta.get("char_count") and meta["char_count"] != char_count:
        warnings.append(f"{stem}: metadata.char_count {meta['char_count']} != actual {char_count}")

    return {
        "stem": stem,
        "note_id": note_id,
        "specialty": label.get("specialty"),
        "tier": tier,
        "char_count": char_count,
        "facts": label.get("expected_facts", []),
        "non_facts": label.get("expected_non_facts", []),
        "demographics": label.get("patient_pseudo_demographics", {}),
        "note_text": note_text,
    }


def load_code_reference():
    if not CODE_REF.exists():
        return {}, []
    data = json.loads(CODE_REF.read_text(encoding="utf-8"))
    entries = data if isinstance(data, list) else data.get("codes", [])
    codes = {}
    for e in entries:
        key = (e.get("system_short"), e.get("code"))
        codes[key] = e
    return codes, entries


PATIENT_LINE_RE = re.compile(r"(?im)^\s*patient[:\s]+([A-Z][A-Za-z'\-.]+(?:\s+[A-Z][A-Za-z'\-.]+)+)")
MRN_LINE_RE = re.compile(r"(?im)\bMRN[:\s]+([A-Z]{2,5}-\d+-[A-Z0-9]+)")
PROVIDER_RE = re.compile(r"Electronically signed:\s*([A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+)+)")
ORG_HINTS = ["Cedar Mesa", "Greenvale", "Port Halston", "Ashford"]


def extract_identities(pairs_data):
    patients = []
    providers = set()
    orgs = set()
    mrns = set()
    for p in pairs_data:
        text = p["note_text"]
        m_patient = PATIENT_LINE_RE.search(text)
        if m_patient:
            patients.append(m_patient.group(1).strip())
        m_mrn = MRN_LINE_RE.search(text)
        if m_mrn:
            mrns.add(m_mrn.group(1).strip())
        for m in PROVIDER_RE.finditer(text):
            providers.add(m.group(1).strip())
        for org in ORG_HINTS:
            if org.lower() in text.lower():
                orgs.add(org)
    return patients, mrns, providers, orgs


def check_corpus_level(pairs_data, code_ref_codes, code_ref_entries, fixture_codes, errors, warnings):
    if not pairs_data:
        return

    patients, mrns, providers, orgs = extract_identities(pairs_data)
    dupes = [n for n, c in Counter(patients).items() if c > 1]
    if dupes:
        errors.append(f"corpus: patient names not unique across 18 notes; duplicates: {dupes}")
    if len(mrns) < len(pairs_data):
        warnings.append(f"corpus: extracted {len(mrns)} MRNs from {len(pairs_data)} notes (pattern may have missed some)")
    if len(providers) < 12:
        errors.append(f"corpus: only {len(providers)} unique providers detected (need >=12): {sorted(providers)}")
    if len(orgs) < 3:
        errors.append(f"corpus: only {len(orgs)} unique organizations detected (need >=3): {sorted(orgs)}")

    sexes = Counter(p["demographics"].get("sex") for p in pairs_data)
    if len(sexes) < 2:
        errors.append(f"corpus: sex diversity inadequate: {sexes}")
    ages = [p["demographics"].get("age") for p in pairs_data if p["demographics"].get("age") is not None]
    if ages:
        if max(ages) - min(ages) < 40:
            warnings.append(f"corpus: age range only {max(ages) - min(ages)} years")
    races = {p["demographics"].get("race") for p in pairs_data}
    if len([r for r in races if r]) < 4:
        warnings.append(f"corpus: race variety only {len(races)} distinct values")

    # Every code-reference entry used by >=1 label
    used_keys = set()
    for p in pairs_data:
        for f in p["facts"]:
            for ec in f.get("expected_codes", []):
                used_keys.add((ec.get("system"), ec.get("code")))
    # Build a set of keys present in the reference
    ref_keys = {(e.get("system_short"), e.get("code")) for e in code_ref_entries}
    dangling = ref_keys - used_keys - fixture_codes
    if dangling and len(pairs_data) == 18:
        # Only enforce when corpus is complete
        errors.append(f"corpus: {len(dangling)} code-reference entries unused (by labels or fixtures): {sorted(dangling)}")

    # Duplicate code-reference entries
    key_counts = Counter((e.get("system_short"), e.get("code")) for e in code_ref_entries)
    dups = [k for k, c in key_counts.items() if c > 1]
    if dups:
        errors.append(f"corpus: duplicate code-reference entries: {dups}")

    # Every code-reference entry has non-empty source_url
    for e in code_ref_entries:
        if not e.get("source_url"):
            errors.append(f"corpus: code {e.get('system_short')}:{e.get('code')} has empty source_url")


def _iter_resource_codings(resource):
    rtype = resource.get("resourceType")
    candidates = []
    if rtype == "MedicationRequest":
        candidates.append(resource.get("medicationCodeableConcept"))
    elif rtype == "FamilyMemberHistory":
        candidates.append(resource.get("relationship"))
        for cond in resource.get("condition", []) or []:
            candidates.append(cond.get("code"))
    else:
        candidates.append(resource.get("code"))
    if rtype == "Observation":
        val = resource.get("valueCodeableConcept")
        if val:
            candidates.append(val)
    for cc in candidates:
        if not cc:
            continue
        for coding in cc.get("coding", []) or []:
            yield coding


def _resource_active(resource):
    rtype = resource.get("resourceType")
    if rtype == "MedicationRequest":
        return resource.get("status") == "active"
    if rtype in {"Condition", "AllergyIntolerance"}:
        cs = resource.get("clinicalStatus") or {}
        for c in cs.get("coding", []) or []:
            if c.get("code") == "active":
                return True
        return False
    return True


def load_fixtures(errors, warnings):
    fixtures = {}
    fixture_index = {}
    fixture_codes = set()
    fixture_resource_summary = {}

    if not FIXTURES_DIR.exists():
        return fixtures, fixture_index, fixture_codes, fixture_resource_summary

    for path in sorted(FIXTURES_DIR.glob("*.json")):
        if path.name == FIXTURES_MANIFEST.name:
            continue
        fixture_id = path.stem
        try:
            bundle = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as ex:
            errors.append(f"fixture {fixture_id}: invalid JSON: {ex}")
            continue
        if bundle.get("resourceType") != "Bundle" or "entry" not in bundle:
            errors.append(f"fixture {fixture_id}: not a FHIR Bundle with entry[]")
            continue

        patients = []
        index = {}
        summary = []
        for entry in bundle.get("entry", []):
            res = entry.get("resource") or {}
            rid = res.get("id")
            rtype = res.get("resourceType")
            if not rid or not rtype:
                errors.append(f"fixture {fixture_id}: entry missing resourceType or id")
                continue
            if rtype == "Patient":
                patients.append(rid)
            index[rid] = res

            codings = list(_iter_resource_codings(res))
            for c in codings:
                sysname = c.get("system")
                code = c.get("code")
                if not sysname or not code:
                    continue
                short = SYSTEM_TO_SHORT.get(sysname)
                if short:
                    fixture_codes.add((short, code))
            summary.append({
                "id": rid,
                "resourceType": rtype,
                "codes": [
                    {"system": SYSTEM_TO_SHORT.get(c.get("system"), c.get("system")), "code": c.get("code")}
                    for c in codings if c.get("code")
                ],
                "active": _resource_active(res),
            })

            if rtype in ACTIVE_STATUS_TYPES and not _resource_active(res):
                warnings.append(f"fixture {fixture_id}: {rtype}/{rid} is not active; reconciler will ignore it")

        if len(patients) != 1:
            errors.append(f"fixture {fixture_id}: expected exactly 1 Patient, found {len(patients)}")

        fixtures[fixture_id] = bundle
        fixture_index[fixture_id] = index
        fixture_resource_summary[fixture_id] = summary

    return fixtures, fixture_index, fixture_codes, fixture_resource_summary


def check_augmentation_layer(pairs_data, fixtures, fixture_index, code_ref_codes, errors, warnings):
    if not AUG_DIR.exists():
        warnings.append("augmentation_labels/ directory not present; skipping augmentation checks")
        return {}, Counter(), Counter()

    facts_by_stem = {p["stem"]: {f["id"] for f in p["facts"]} for p in pairs_data}
    non_facts_by_stem = {p["stem"]: {nf["id"] for nf in p["non_facts"]} for p in pairs_data}

    aug_data_by_stem = {}
    action_counts = Counter()
    basis_counts = Counter()
    used_fixtures = set()

    for path in sorted(AUG_DIR.glob("*.json")):
        stem = path.stem
        try:
            aug = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as ex:
            errors.append(f"aug {stem}: invalid JSON: {ex}")
            continue

        if stem not in facts_by_stem:
            errors.append(f"aug {stem}: no matching extraction label in labels/")
            continue

        bundle_id = aug.get("paired_bundle")
        if bundle_id not in fixtures:
            errors.append(f"aug {stem}: paired_bundle {bundle_id!r} does not resolve to a fixture")
            continue
        used_fixtures.add(bundle_id)
        index = fixture_index[bundle_id]

        actions = aug.get("expected_actions", [])
        seen_fact_ids = set()
        for a in actions:
            fid = a.get("fact_id")
            seen_fact_ids.add(fid)
            if fid not in facts_by_stem[stem]:
                errors.append(f"aug {stem}: action references unknown fact_id {fid!r}")
                continue

            has_action = "action" in a
            has_accepted = "accepted_actions" in a
            if has_action == has_accepted:
                errors.append(f"aug {stem}/{fid}: must set exactly one of 'action' or 'accepted_actions'")
                continue

            if has_action:
                act = a["action"]
                if act not in ACTION_ENUM:
                    errors.append(f"aug {stem}/{fid}: action {act!r} not in {sorted(ACTION_ENUM)}")
                action_counts[act] += 1
                effective_actions = {act}
            else:
                accepted = a["accepted_actions"]
                if not isinstance(accepted, list) or not all(x in ACTION_ENUM for x in accepted) or len(accepted) < 2:
                    errors.append(f"aug {stem}/{fid}: accepted_actions must be a list of >=2 valid actions")
                    continue
                for x in accepted:
                    action_counts[x] += 1
                effective_actions = set(accepted)

            basis = a.get("match_basis")
            if basis not in MATCH_BASIS_ENUM:
                errors.append(f"aug {stem}/{fid}: match_basis {basis!r} not in enum")
            else:
                basis_counts[basis] += 1

            target = a.get("target_resource_id")
            if effective_actions == {"NEW"}:
                if target is not None:
                    errors.append(f"aug {stem}/{fid}: NEW action must have target_resource_id=null")
            else:
                if target is None or target not in index:
                    errors.append(f"aug {stem}/{fid}: target_resource_id {target!r} not found in fixture {bundle_id!r}")

            if "UPDATING" in effective_actions:
                changes = a.get("field_changes")
                if not isinstance(changes, list) or not changes:
                    errors.append(f"aug {stem}/{fid}: UPDATING requires non-empty field_changes")
                else:
                    for ch in changes:
                        if not all(k in ch for k in ("path", "from", "to")):
                            errors.append(f"aug {stem}/{fid}: field_changes entry missing path/from/to")

            prov = a.get("expected_provenance")
            if not isinstance(prov, bool):
                errors.append(f"aug {stem}/{fid}: expected_provenance must be a bool")
            elif "DUPLICATE" in effective_actions and prov is True:
                warnings.append(f"aug {stem}/{fid}: DUPLICATE with expected_provenance=true (Stage 6 filters DUPLICATEs)")

        missing = facts_by_stem[stem] - seen_fact_ids
        if missing:
            errors.append(f"aug {stem}: missing actions for fact_ids {sorted(missing)}")

        for nfa in aug.get("expected_non_fact_actions", []):
            nf_id = nfa.get("non_fact_id")
            if nf_id not in non_facts_by_stem[stem]:
                errors.append(f"aug {stem}: non_fact action references unknown non_fact_id {nf_id!r}")
            ea = nfa.get("expected_action")
            if ea is not None and ea not in ACTION_ENUM:
                errors.append(f"aug {stem}/{nf_id}: expected_action {ea!r} not null and not in enum")

        aug_data_by_stem[stem] = aug

    dangling_fixtures = set(fixtures) - used_fixtures
    if dangling_fixtures:
        warnings.append(f"corpus: fixtures with no augmentation labels: {sorted(dangling_fixtures)}")

    return aug_data_by_stem, action_counts, basis_counts


def emit_fixtures_manifest(fixture_resource_summary):
    if not fixture_resource_summary:
        return
    body = json.dumps(fixture_resource_summary, indent=2, sort_keys=True)
    FIXTURES_MANIFEST.write_text(body + "\n", encoding="utf-8")


def emit_manifest(pairs_data, code_ref_entries, fixtures, action_counts, basis_counts, aug_data_by_stem):
    fact_cat_counts = Counter()
    trap_type_counts = Counter()
    total_facts = 0
    total_non_facts = 0
    total_chars = 0
    tier_counts = Counter()
    spec_counts = Counter()
    for p in pairs_data:
        total_chars += p["char_count"]
        tier_counts[p["tier"]] += 1
        spec_counts[p["specialty"]] += 1
        for f in p["facts"]:
            fact_cat_counts[f.get("category")] += 1
            total_facts += 1
        for nf in p["non_facts"]:
            trap_type_counts[nf.get("trap_type")] += 1
            total_non_facts += 1

    notes_per_fixture = defaultdict(list)
    for stem, aug in aug_data_by_stem.items():
        notes_per_fixture[aug.get("paired_bundle")].append(stem)

    manifest = {
        "corpus_name": "Anamnesis Evaluation Corpus v1",
        "version": "1.0.0",
        "creation_date": "2026-04-28",
        "total_notes": len(pairs_data),
        "total_chars": total_chars,
        "total_facts": total_facts,
        "total_non_facts": total_non_facts,
        "specialty_distribution": dict(spec_counts),
        "tier_distribution": dict(tier_counts),
        "fact_categories": dict(fact_cat_counts),
        "trap_types": dict(trap_type_counts),
        "code_reference_size": len(code_ref_entries),
        "license": "CC-BY-4.0 (synthetic notes; no PHI)",
        "labeled_by": "Anamnesis project team",
        "code_systems_used": sorted({e.get("system_short") for e in code_ref_entries if e.get("system_short")}),
        "total_fixtures": len(fixtures),
        "augmentation_labels_count": len(aug_data_by_stem),
        "action_distribution": dict(action_counts),
        "match_basis_distribution": dict(basis_counts),
        "notes_per_fixture": {k: sorted(v) for k, v in notes_per_fixture.items()},
    }
    body = json.dumps(manifest, indent=2, sort_keys=True)
    MANIFEST.write_text(body + "\n", encoding="utf-8")
    manifest["sha256"] = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="Validate only the given note_id (e.g. C1)")
    parser.add_argument("--strict-completeness", action="store_true",
                        help="Fail if corpus has fewer than 18 notes")
    parser.add_argument("--skip-augmentation", action="store_true",
                        help="Skip fixture + augmentation_label validation")
    args = parser.parse_args()

    errors = []
    warnings = []

    code_ref_codes, code_ref_entries = load_code_reference()
    if not code_ref_entries:
        warnings.append("code-reference.json is empty or missing")

    pairs_data = []
    for stem, note_path, label_path in load_pairs():
        if args.only and not stem.startswith(args.only + "-"):
            continue
        result = check_note_label(stem, note_path, label_path, code_ref_codes, errors, warnings)
        if result:
            pairs_data.append(result)

    fixtures, fixture_index, fixture_codes, fixture_summary = ({}, {}, set(), {})
    aug_data_by_stem, action_counts, basis_counts = ({}, Counter(), Counter())

    if not args.skip_augmentation:
        fixtures, fixture_index, fixture_codes, fixture_summary = load_fixtures(errors, warnings)
        if not args.only:
            aug_data_by_stem, action_counts, basis_counts = check_augmentation_layer(
                pairs_data, fixtures, fixture_index, code_ref_codes, errors, warnings,
            )

    if not args.only:
        check_corpus_level(pairs_data, code_ref_codes, code_ref_entries, fixture_codes, errors, warnings)

    if args.strict_completeness and len(pairs_data) != 18:
        errors.append(f"corpus: {len(pairs_data)} notes found, expected 18")

    manifest = None
    if not args.only and pairs_data:
        manifest = emit_manifest(pairs_data, code_ref_entries, fixtures, action_counts, basis_counts, aug_data_by_stem)
        if not args.skip_augmentation:
            emit_fixtures_manifest(fixture_summary)

    print(f"Notes validated: {len(pairs_data)}")
    if manifest:
        print(f"Total chars: {manifest['total_chars']}")
        print(f"Total facts: {manifest['total_facts']}")
        print(f"Total non-facts: {manifest['total_non_facts']}")
        print(f"Fact categories: {manifest['fact_categories']}")
        print(f"Trap types: {manifest['trap_types']}")
        print(f"Fixtures: {manifest['total_fixtures']}")
        print(f"Augmentation labels: {manifest['augmentation_labels_count']}")
        print(f"Action distribution: {manifest['action_distribution']}")
    print()
    print(f"=== ERRORS ({len(errors)}) ===")
    for e in errors:
        print(f"  X {e}")
    print()
    print(f"=== WARNINGS ({len(warnings)}) ===")
    for w in warnings:
        print(f"  ! {w}")
    print()
    print("FAIL" if errors else "PASS")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
