"""Validate the oncology demo bundle: structure, reference integrity, note decoding.

Independent of the Anamnesis backend — pure FHIR/JSON checks.
"""
import base64
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUNDLE = HERE / "oncology-demo-bundle.json"


def main() -> int:
    data = json.loads(BUNDLE.read_text(encoding="utf-8"))
    entries = data.get("entry", [])
    errors: list[str] = []
    warnings: list[str] = []

    full_urls = {e.get("fullUrl") for e in entries}

    def walk_refs(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "reference" and isinstance(v, str):
                    yield v
                else:
                    yield from walk_refs(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from walk_refs(v)

    ref_count = 0
    coding_count = 0
    for e in entries:
        res = e.get("resource", {})
        if e.get("fullUrl") != f"urn:uuid:{__import__('uuid').uuid5(__import__('uuid').UUID('00000000-0000-0000-0000-000000000002'), '')}":
            pass
        for r in walk_refs(res):
            if r.startswith("urn:uuid:"):
                ref_count += 1
                if r not in full_urls:
                    errors.append(f"{res.get('resourceType')}/{res.get('id')}: unresolved reference {r}")

        def count_codings(o):
            nonlocal coding_count
            if isinstance(o, dict):
                if "coding" in o and isinstance(o["coding"], list):
                    coding_count += len(o["coding"])
                for v in o.values():
                    count_codings(v)
            elif isinstance(o, list):
                for v in o:
                    count_codings(v)
        count_codings(res)

        if res.get("resourceType") == "DocumentReference":
            try:
                raw = res["content"][0]["attachment"]["data"]
                text = base64.b64decode(raw).decode("utf-8")
                if "SULLIVAN, MARGARET" not in text:
                    warnings.append(f"{res.get('id')}: decoded note missing patient banner")
            except Exception as ex:  # noqa: BLE001
                errors.append(f"{res.get('id')}: note decode failed: {ex}")

    print(f"Bundle: {BUNDLE.name}")
    print(f"Total entries: {len(entries)}")
    print(f"Total urn:uuid references: {ref_count}")
    print(f"Total codings: {coding_count}")
    print("Resource types:", dict(Counter(e["resource"]["resourceType"] for e in entries)))
    print()
    print(f"=== ERRORS ({len(errors)}) ===")
    for e in errors:
        print(" ", e)
    print(f"=== WARNINGS ({len(warnings)}) ===")
    for w in warnings:
        print(" ", w)
    print()
    print("PASS" if not errors else "FAIL")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
