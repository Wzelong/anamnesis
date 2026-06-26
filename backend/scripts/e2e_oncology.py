"""E2E: run the mCODE-enabled pipeline against the Margaret Sullivan oncology
bundle and report terminology coding coverage per proposal."""
import asyncio
import json
import os
from pathlib import Path

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

from fhir.local_bundle import load_demo_data
from core.effective_profile import resolve_effective_profile
from services.proposals import _execute_stages, _proposal_to_dict

ONCOLOGY_BUNDLE = (
    Path(__file__).resolve().parents[2]
    / "data" / "demo_oncology" / "oncology-demo-bundle.json"
)


def _codings(resource: dict) -> list[dict]:
    """Pull every coding[] across the resource's coded fields, flat."""
    out = []

    def walk(node, path):
        if isinstance(node, dict):
            if "coding" in node and isinstance(node["coding"], list):
                for c in node["coding"]:
                    out.append({"path": path, **{k: c.get(k) for k in ("system", "code", "display")}})
            for k, v in node.items():
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(resource, resource.get("resourceType", "?"))
    return out


async def main() -> None:
    patient_context, documents = load_demo_data(ONCOLOGY_BUNDLE)
    preset = {"id": "mcode-test", "ig": {"specialty": "mcode@4.0.0"}}
    effective = resolve_effective_profile(preset)

    print(f"docs={len(documents)} preset=mcode@4.0.0 specialty={effective.ig_specialty}\n")

    async def progress(stage, detail=None):
        print(f"  [{stage}] {detail or ''}")

    stage6 = await _execute_stages(
        patient_context, documents, progress_cb=progress, use_cache=False, effective=effective,
    )

    proposals = [_proposal_to_dict(p, "e2e") for p in stage6.proposals]
    print(f"\n=== {len(proposals)} proposals ===\n")

    coded = uncoded = 0
    for p in proposals:
        res = p.get("resource") or {}
        rtype = res.get("resourceType")
        label = p.get("label") or p.get("title") or "?"
        cls = p.get("classification")
        profiles = (res.get("meta") or {}).get("profile") or []
        prof_short = [u.rsplit("/", 1)[-1] for u in profiles]
        cods = _codings(res)
        # codings on the primary clinical field (code / valueCodeableConcept etc.), exclude fixed category/meta
        primary = [c for c in cods if c["system"] and not c["path"].endswith("category.coding")]
        has_real = any(c.get("code") for c in primary)
        if has_real:
            coded += 1
        else:
            uncoded += 1
        flag = "OK " if has_real else "MISSING"
        print(f"[{flag}] {rtype:14} {cls:12} {label[:50]:50} profiles={prof_short}")
        for c in cods:
            print(f"         {c['path']:48} {str(c['system']):10} {str(c['code']):12} {c['display']}")
        print()

    out = Path(__file__).resolve().parent / "e2e_oncology_out.json"
    out.write_text(json.dumps([p for p in proposals], indent=2), encoding="utf-8")
    print(f"coded={coded} uncoded={uncoded} -> {out}")


if __name__ == "__main__":
    asyncio.run(main())
