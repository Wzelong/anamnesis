"""
Validation pass on the Anamnesis demo bundle.

Checks:
1. Bundle structure (transaction type, all entries have request)
2. Reference integrity — every Reference.reference points to a fullUrl in the bundle
3. US Core profile-specific must-haves (per profile)
4. Code system URIs are correct (RxNorm, SNOMED, LOINC, etc.)
5. RxNorm codes look real (basic regex)
6. Note text is decodable from base64
7. Cross-resource sanity (practitioner orgs match, etc.)
"""

import json
import re
import sys
from base64 import b64decode
from collections import defaultdict

PATH = "/home/claude/anamnesis-demo-bundle.json"
with open(PATH) as f:
    bundle = json.load(f)

errors = []
warnings = []

def err(msg):
    errors.append(msg)
def warn(msg):
    warnings.append(msg)

# ---------------------------------------------------------------------------
# 1. Bundle structure
# ---------------------------------------------------------------------------
if bundle.get("resourceType") != "Bundle":
    err("Top-level resourceType is not Bundle")
if bundle.get("type") != "transaction":
    err(f"Bundle.type is {bundle.get('type')!r}, expected 'transaction'")

entries = bundle.get("entry", [])
if not entries:
    err("Bundle has no entries")

# Index by fullUrl
by_url = {}
for i, e in enumerate(entries):
    fu = e.get("fullUrl")
    if not fu:
        err(f"Entry {i} missing fullUrl")
        continue
    if fu in by_url:
        err(f"Duplicate fullUrl: {fu}")
    by_url[fu] = e
    req = e.get("request")
    if not req or req.get("method") != "POST" or not req.get("url"):
        err(f"Entry {fu} has bad request element")

# ---------------------------------------------------------------------------
# 2. Reference integrity
# ---------------------------------------------------------------------------
def find_refs(obj, path=""):
    """Yield (path, reference_string) for every Reference in obj."""
    if isinstance(obj, dict):
        if "reference" in obj and isinstance(obj["reference"], str):
            # Looks like a Reference type
            yield (path, obj["reference"])
        for k, v in obj.items():
            yield from find_refs(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            yield from find_refs(item, f"{path}[{i}]")

ref_targets = defaultdict(list)
for e in entries:
    full_url = e["fullUrl"]
    res = e["resource"]
    rtype = res["resourceType"]
    for path, target in find_refs(res, f"{rtype}({full_url})"):
        ref_targets[target].append(path)

# Verify every urn:uuid reference points to an entry in the bundle
for target, paths in ref_targets.items():
    if target.startswith("urn:uuid:"):
        if target not in by_url:
            err(f"Reference target not found in bundle: {target} (referenced by {paths[0]})")

# ---------------------------------------------------------------------------
# 3. US Core profile must-haves (selected critical checks)
# ---------------------------------------------------------------------------

def get_resources(resource_type):
    return [(e["fullUrl"], e["resource"]) for e in entries if e["resource"]["resourceType"] == resource_type]

# Patient
for full_url, p in get_resources("Patient"):
    if not p.get("identifier"):
        err(f"{full_url} Patient missing identifier")
    if not p.get("name"):
        err(f"{full_url} Patient missing name")
    if not p.get("gender"):
        err(f"{full_url} Patient missing gender (mandatory)")
    # Race + ethnicity + birthsex extensions (USCDI required)
    ext_urls = [x.get("url") for x in p.get("extension", [])]
    for needed in [
        "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race",
        "http://hl7.org/fhir/us/core/StructureDefinition/us-core-ethnicity",
        "http://hl7.org/fhir/us/core/StructureDefinition/us-core-birthsex",
    ]:
        if needed not in ext_urls:
            warn(f"Patient missing USCDI extension: {needed}")

# Practitioner
for full_url, pr in get_resources("Practitioner"):
    if not pr.get("identifier"):
        err(f"{full_url} Practitioner missing identifier (NPI)")
    if not pr.get("name"):
        err(f"{full_url} Practitioner missing name")

# Organization
for full_url, o in get_resources("Organization"):
    if not o.get("identifier"):
        err(f"{full_url} Organization missing identifier")
    if not o.get("name"):
        err(f"{full_url} Organization missing name")
    if "active" not in o:
        warn(f"{full_url} Organization missing active")
    if not o.get("address"):
        warn(f"{full_url} Organization missing address (must support)")

# Condition
for full_url, c in get_resources("Condition"):
    if not c.get("clinicalStatus"):
        err(f"{full_url} Condition missing clinicalStatus")
    if not c.get("verificationStatus"):
        err(f"{full_url} Condition missing verificationStatus")
    cats = c.get("category", [])
    cat_codes = [coding.get("code") for cat in cats for coding in cat.get("coding", [])]
    if not any(code in {"problem-list-item", "health-concern", "encounter-diagnosis"} for code in cat_codes):
        err(f"{full_url} Condition category not valid (expected problem-list-item / health-concern / encounter-diagnosis)")
    if not c.get("code"):
        err(f"{full_url} Condition missing code")
    if not c.get("subject"):
        err(f"{full_url} Condition missing subject")

# MedicationRequest
for full_url, m in get_resources("MedicationRequest"):
    for field in ["status", "intent", "subject", "authoredOn", "requester"]:
        if not m.get(field):
            err(f"{full_url} MedicationRequest missing {field}")
    if not (m.get("medicationCodeableConcept") or m.get("medicationReference")):
        err(f"{full_url} MedicationRequest missing medication[x]")
    # US Core requires reportedBoolean OR reportedReference
    if "reportedBoolean" not in m and "reportedReference" not in m:
        err(f"{full_url} MedicationRequest missing reported[x] (must support)")

# Encounter
for full_url, e in get_resources("Encounter"):
    for field in ["status", "class", "subject", "type", "period"]:
        if not e.get(field):
            err(f"{full_url} Encounter missing {field}")
    if not e.get("participant"):
        err(f"{full_url} Encounter missing participant")
    if not e.get("reasonCode") and not e.get("reasonReference"):
        warn(f"{full_url} Encounter missing reasonCode/reasonReference (must support)")

# DocumentReference
for full_url, d in get_resources("DocumentReference"):
    for field in ["status", "type", "category", "subject", "date", "author", "content"]:
        if not d.get(field):
            err(f"{full_url} DocumentReference missing {field}")
    cats = d.get("category", [])
    cat_codes = [coding.get("code") for cat in cats for coding in cat.get("coding", [])]
    if "clinical-note" not in cat_codes:
        err(f"{full_url} DocumentReference missing 'clinical-note' category")
    for content in d.get("content", []):
        att = content.get("attachment", {})
        if not att.get("contentType"):
            err(f"{full_url} DocumentReference content.attachment missing contentType")
        if not (att.get("data") or att.get("url")):
            err(f"{full_url} DocumentReference content.attachment missing data or url")

# ---------------------------------------------------------------------------
# 4. Code system URIs
# ---------------------------------------------------------------------------
EXPECTED_SYSTEMS = {
    "snomed": "http://snomed.info/sct",
    "loinc": "http://loinc.org",
    "icd10": "http://hl7.org/fhir/sid/icd-10-cm",
    "rxnorm": "http://www.nlm.nih.gov/research/umls/rxnorm",
}
def collect_codings(obj):
    """Yield all Coding-like dicts."""
    if isinstance(obj, dict):
        if "system" in obj and "code" in obj:
            yield obj
        for v in obj.values():
            yield from collect_codings(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from collect_codings(item)

all_codings = list(collect_codings(bundle))
systems_used = {c["system"] for c in all_codings if "system" in c}

# Check for typos in expected systems
for c in all_codings:
    sys_url = c.get("system", "")
    # SNOMED canonical
    if "snomed" in sys_url.lower() and sys_url != "http://snomed.info/sct":
        err(f"Non-canonical SNOMED system URI: {sys_url}")
    # LOINC canonical
    if "loinc" in sys_url.lower() and sys_url != "http://loinc.org":
        err(f"Non-canonical LOINC system URI: {sys_url}")
    # RxNorm canonical
    if "rxnorm" in sys_url.lower() and sys_url != "http://www.nlm.nih.gov/research/umls/rxnorm":
        err(f"Non-canonical RxNorm system URI: {sys_url}")

# ---------------------------------------------------------------------------
# 5. RxNorm codes look like RxNorm (numeric)
# ---------------------------------------------------------------------------
RXNORM_RE = re.compile(r"^\d+$")
for c in all_codings:
    if c.get("system") == EXPECTED_SYSTEMS["rxnorm"]:
        code = c.get("code", "")
        if not RXNORM_RE.match(code):
            err(f"Invalid RxNorm code format: {code!r}")

# ---------------------------------------------------------------------------
# 6. Note text decodable
# ---------------------------------------------------------------------------
for full_url, d in get_resources("DocumentReference"):
    for content in d.get("content", []):
        data = content.get("attachment", {}).get("data")
        if data:
            try:
                decoded = b64decode(data).decode("utf-8")
                if len(decoded) < 200:
                    warn(f"{full_url} note text very short: {len(decoded)} chars")
            except Exception as ex:
                err(f"{full_url} note text not decodable: {ex}")

# ---------------------------------------------------------------------------
# 7. Cross-resource sanity
# ---------------------------------------------------------------------------
# Patient managingOrganization should be Bayside, not Riverside
patient_resources = get_resources("Patient")
if patient_resources:
    p = patient_resources[0][1]
    mo = p.get("managingOrganization", {}).get("reference", "")
    bayside_url = next((u for u, e in by_url.items()
                        if e["resource"]["resourceType"] == "Organization"
                        and e["resource"].get("name") == "Bayside Health"), None)
    if mo != bayside_url:
        warn(f"Patient.managingOrganization should reference Bayside Health, got {mo}")

# ED encounter should reference Riverside; cardio/neuro should reference Bayside
riverside_url = next((u for u, e in by_url.items()
                      if e["resource"]["resourceType"] == "Organization"
                      and e["resource"].get("name") == "Riverside Hospital"), None)
for full_url, enc in get_resources("Encounter"):
    sp = enc.get("serviceProvider", {}).get("reference", "")
    rtype = enc["type"][0]["text"] if enc.get("type") else ""
    if "Emergency" in rtype:
        if sp != riverside_url:
            err(f"ED encounter {full_url} should be at Riverside, got {sp}")
    else:
        if sp != bayside_url:
            err(f"Non-ED encounter {full_url} should be at Bayside, got {sp}")

# Document author/encounter linkage
docs = get_resources("DocumentReference")
encs_by_url = {u: e for u, e in get_resources("Encounter")}
for full_url, d in docs:
    ctx_encs = d.get("context", {}).get("encounter", [])
    if not ctx_encs:
        warn(f"{full_url} DocumentReference missing context.encounter")
        continue
    enc_ref = ctx_encs[0].get("reference")
    if enc_ref not in encs_by_url:
        err(f"{full_url} DocumentReference points to unknown encounter {enc_ref}")
        continue
    enc = encs_by_url[enc_ref]
    enc_practitioner = enc["participant"][0]["individual"]["reference"]
    doc_author = d["author"][0]["reference"]
    if enc_practitioner != doc_author:
        warn(f"{full_url} document author ({doc_author}) ≠ encounter practitioner ({enc_practitioner})")

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
print(f"Bundle: {PATH}")
print(f"Total entries: {len(entries)}")
print(f"Total Reference targets: {len(ref_targets)}")
print(f"Total Codings: {len(all_codings)}")
print(f"Code systems used:")
for s in sorted(systems_used):
    print(f"  - {s}")
print()
print(f"=== ERRORS ({len(errors)}) ===")
for e in errors:
    print(f"  ✗ {e}")
print()
print(f"=== WARNINGS ({len(warnings)}) ===")
for w in warnings:
    print(f"  ⚠ {w}")
print()
if errors:
    print("FAIL")
    sys.exit(1)
else:
    print("PASS")
