"""One-shot script to re-baseline corpus codes to vector-DB-retrievable equivalents.

Replaces 19 (system, old_code) -> (new_code, new_display) pairs across:
  - code-reference.json
  - labels/*.json (expected_codes entries)
  - fixtures/*.json (any coding[] entries)

Augmentation_labels/*.json don't reference codes (only fact_ids and resource_ids),
so they're untouched.

Run from repo root:
  python benchmarks/eval-corpus-v1/apply_code_swaps.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CODE_REF = ROOT / "code-reference.json"
LABELS_DIR = ROOT / "labels"
FIXTURES_DIR = ROOT / "fixtures"

SHORT_TO_SYSTEM = {
    "SNOMED": "http://snomed.info/sct",
    "ICD-10": "http://hl7.org/fhir/sid/icd-10-cm",
    "LOINC": "http://loinc.org",
    "RxNorm": "http://www.nlm.nih.gov/research/umls/rxnorm",
}

SWAPS = [
    ("SNOMED", "84114007", "155377000", "Heart failure NOS"),
    ("SNOMED", "282825002", "195081002", "Paroxysmal atrial fibrillation"),
    ("SNOMED", "439729000", "431601000124105", "Chronic migraine without aura (disorder)"),
    ("SNOMED", "385627004", "449710006", "Cellulitis of lower limb (disorder)"),
    ("SNOMED", "91175000", "128613002", "Seizure disorder"),
    ("SNOMED", "15602001", "89239005", "Conversion disorder"),
    ("SNOMED", "59621000", "155296003", "Essential hypertension"),
    ("SNOMED", "302828002", "195516009", "Chronic venous insufficiency NOS"),
    ("SNOMED", "398665005", "139534004", "Syncope/vasovagal faint"),
    ("SNOMED", "195967001", "21341004", "Asthma"),
    ("SNOMED", "235595009", "102620007", "Gastroesophageal reflux"),
    ("SNOMED", "61582004", "195821000", "Allergic rhinitis NOS"),
    ("SNOMED", "49049000", "154999006", "Parkinson's disease"),
    ("SNOMED", "164847006", "142010003", "12 lead ECG"),
    ("SNOMED", "241601008", "816077007", "MRI of brain"),
    ("ICD-10", "G35", "G35D", "Multiple sclerosis, unspecified"),
    ("LOINC", "10230-1", "18043-0", "Left ventricular Ejection fraction by US"),
    ("LOINC", "8310-5", "8331-1", "Oral temperature"),
    ("LOINC", "59408-5", "59410-1", "Oxygen saturation in Arterial blood by Pulse oximetry --on room air"),
]

SOURCE_URLS = {
    ("SNOMED", "155377000"): "https://browser.ihtsdotools.org/?conceptId1=155377000",
    ("SNOMED", "195081002"): "https://browser.ihtsdotools.org/?conceptId1=195081002",
    ("SNOMED", "431601000124105"): "https://browser.ihtsdotools.org/?conceptId1=431601000124105",
    ("SNOMED", "449710006"): "https://browser.ihtsdotools.org/?conceptId1=449710006",
    ("SNOMED", "128613002"): "https://browser.ihtsdotools.org/?conceptId1=128613002",
    ("SNOMED", "89239005"): "https://browser.ihtsdotools.org/?conceptId1=89239005",
    ("SNOMED", "155296003"): "https://browser.ihtsdotools.org/?conceptId1=155296003",
    ("SNOMED", "195516009"): "https://browser.ihtsdotools.org/?conceptId1=195516009",
    ("SNOMED", "139534004"): "https://browser.ihtsdotools.org/?conceptId1=139534004",
    ("SNOMED", "21341004"): "https://browser.ihtsdotools.org/?conceptId1=21341004",
    ("SNOMED", "102620007"): "https://browser.ihtsdotools.org/?conceptId1=102620007",
    ("SNOMED", "195821000"): "https://browser.ihtsdotools.org/?conceptId1=195821000",
    ("SNOMED", "154999006"): "https://browser.ihtsdotools.org/?conceptId1=154999006",
    ("SNOMED", "142010003"): "https://browser.ihtsdotools.org/?conceptId1=142010003",
    ("SNOMED", "816077007"): "https://browser.ihtsdotools.org/?conceptId1=816077007",
    ("ICD-10", "G35D"): "https://clinicaltables.nlm.nih.gov/api/icd10cm/v3/search?terms=G35D",
    ("LOINC", "18043-0"): "https://loinc.org/18043-0/",
    ("LOINC", "8331-1"): "https://loinc.org/8331-1/",
    ("LOINC", "59410-1"): "https://loinc.org/59410-1/",
}


def patch_code_reference():
    data = json.loads(CODE_REF.read_text(encoding="utf-8"))
    by_key = {(e["system_short"], e["code"]): e for e in data["codes"]}
    swapped = 0
    for short, old_code, new_code, new_display in SWAPS:
        entry = by_key.get((short, old_code))
        if not entry:
            print(f"  WARN: {short}:{old_code} not in code-reference; skipping")
            continue
        entry["code"] = new_code
        entry["display"] = new_display
        entry["source_url"] = SOURCE_URLS.get((short, new_code), entry.get("source_url", ""))
        swapped += 1
    CODE_REF.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"code-reference.json: {swapped} entries swapped")


def patch_label(path: Path) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    swap_lookup = {(short, old): (new, disp) for short, old, new, disp in SWAPS}
    n = 0
    for fact in data.get("expected_facts", []):
        for ec in fact.get("expected_codes", []):
            key = (ec.get("system"), ec.get("code"))
            if key in swap_lookup:
                new_code, new_disp = swap_lookup[key]
                ec["code"] = new_code
                ec["display"] = new_disp
                n += 1
    if n:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return n


def patch_fixture(path: Path) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    swap_lookup = {(SHORT_TO_SYSTEM[short], old): (new, disp) for short, old, new, disp in SWAPS}
    n = 0

    def visit(node):
        nonlocal n
        if isinstance(node, dict):
            if "system" in node and "code" in node:
                key = (node["system"], node["code"])
                if key in swap_lookup:
                    new_code, new_disp = swap_lookup[key]
                    node["code"] = new_code
                    if "display" in node:
                        node["display"] = new_disp
                    n += 1
            for v in node.values():
                visit(v)
        elif isinstance(node, list):
            for v in node:
                visit(v)

    visit(data)
    if n:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return n


def main():
    patch_code_reference()

    label_total = 0
    for path in sorted(LABELS_DIR.glob("*.json")):
        n = patch_label(path)
        if n:
            print(f"  labels/{path.name}: {n} codes swapped")
            label_total += n
    print(f"labels/: {label_total} codes swapped across {len(list(LABELS_DIR.glob('*.json')))} files")

    fixture_total = 0
    for path in sorted(FIXTURES_DIR.glob("*.json")):
        if path.name == "fixtures-manifest.json":
            continue
        n = patch_fixture(path)
        if n:
            print(f"  fixtures/{path.name}: {n} codings swapped")
            fixture_total += n
    print(f"fixtures/: {fixture_total} codings swapped across {len(list(FIXTURES_DIR.glob('*.json')))} files")


if __name__ == "__main__":
    main()
