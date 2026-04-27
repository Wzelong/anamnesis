"""CLI: load the demo patient bundle into the FHIR server.

Run from backend/:
    python -m scripts.bootstrap
"""
import asyncio
import os
import sys

from dotenv import load_dotenv

from fhir import bootstrap
from fhir.client import FhirClient


async def main() -> int:
    load_dotenv()
    url = os.environ.get("DEV_FHIR_BASE_URL")
    token = os.environ.get("DEV_FHIR_TOKEN")
    if not url or not token:
        print("error: DEV_FHIR_BASE_URL and DEV_FHIR_TOKEN must be set in .env", file=sys.stderr)
        print("       capture them from the ngrok inspector at http://127.0.0.1:4040", file=sys.stderr)
        return 2

    client = FhirClient(url, token)
    patient_id = await bootstrap.run(client)
    print(f"Loaded James Lee: Patient/{patient_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
