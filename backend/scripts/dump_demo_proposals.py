"""Run the real pipeline against the local demo bundle and dump the full
proposal set to mcp-app/src/demo/proposals.json for the UI fixture."""
import asyncio
import json
import os
from pathlib import Path

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

from services import proposals as svc

OUT = Path(__file__).resolve().parent.parent.parent / "mcp-app" / "src" / "demo" / "proposals.json"


async def main() -> None:
    result = await svc.run_extraction_ephemeral(None, triggered_by="fixture:dump")
    payload = {
        "run_id": result["run_id"],
        "patient_id": result["patient_id"],
        "documents": result["documents"],
        "proposals": result["proposals"],
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {len(result['proposals'])} proposals, {len(result['documents'])} docs -> {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
