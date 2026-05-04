"""Run the pipeline against selected benchmark notes and export results as a fixture.

One-time script. Run from backend/:
    python -m scripts.export_demo_fixture
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_DISABLE_XET"] = "1"
os.environ["HF_HUB_VERBOSITY"] = "error"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

BENCH_DIR = Path(__file__).resolve().parent.parent.parent / "benchmarks" / "eval-corpus-v1"
FIXTURE_DIR = BENCH_DIR / "fixtures"
NOTES_DIR = BENCH_DIR / "notes"
AUG_LABELS_DIR = BENCH_DIR / "augmentation_labels"
OUTPUT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "demo_fixture.json"

SELECTED_NOTES = [
    "C1-cardiology-stable-angina-followup",
    "C2-cardiology-hfref-gdmt-optimization",
    "E1-ed-cellulitis-iv-to-po",
    "N1-neurology-migraine-prophylaxis",
    "E3-ed-multicomplaint-dictation",
]

PATIENT_PROFILES = {
    "C1-cardiology-stable-angina-followup": {
        "name": [{"use": "official", "family": "Washington", "given": ["Denise"]}],
        "gender": "female",
        "birthDate": "1968-03-14",
        "extension": [
            {"url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race",
             "extension": [{"url": "ombCategory", "valueCoding": {"system": "urn:oid:2.16.840.1.113883.6.238", "code": "2054-5", "display": "Black or African American"}},
                           {"url": "text", "valueString": "Black or African American"}]},
            {"url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-ethnicity",
             "extension": [{"url": "ombCategory", "valueCoding": {"system": "urn:oid:2.16.840.1.113883.6.238", "code": "2186-5", "display": "Not Hispanic or Latino"}},
                           {"url": "text", "valueString": "Not Hispanic or Latino"}]},
        ],
    },
    "C2-cardiology-hfref-gdmt-optimization": {
        "name": [{"use": "official", "family": "Kowalski", "given": ["Walter"]}],
        "gender": "male",
        "birthDate": "1955-08-22",
        "extension": [
            {"url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race",
             "extension": [{"url": "ombCategory", "valueCoding": {"system": "urn:oid:2.16.840.1.113883.6.238", "code": "2106-3", "display": "White"}},
                           {"url": "text", "valueString": "White"}]},
        ],
    },
    "E1-ed-cellulitis-iv-to-po": {
        "name": [{"use": "official", "family": "Reyes", "given": ["Marco"]}],
        "gender": "male",
        "birthDate": "1992-01-07",
        "extension": [
            {"url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race",
             "extension": [{"url": "ombCategory", "valueCoding": {"system": "urn:oid:2.16.840.1.113883.6.238", "code": "2106-3", "display": "White"}},
                           {"url": "text", "valueString": "White"}]},
            {"url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-ethnicity",
             "extension": [{"url": "ombCategory", "valueCoding": {"system": "urn:oid:2.16.840.1.113883.6.238", "code": "2135-2", "display": "Hispanic or Latino"}},
                           {"url": "text", "valueString": "Hispanic or Latino"}]},
        ],
    },
    "N1-neurology-migraine-prophylaxis": {
        "name": [{"use": "official", "family": "Nguyen", "given": ["Linh"]}],
        "gender": "female",
        "birthDate": "1999-06-11",
        "extension": [
            {"url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race",
             "extension": [{"url": "ombCategory", "valueCoding": {"system": "urn:oid:2.16.840.1.113883.6.238", "code": "2028-9", "display": "Asian"}},
                           {"url": "text", "valueString": "Asian"}]},
        ],
    },
    "E3-ed-multicomplaint-dictation": {
        "name": [{"use": "official", "family": "Patterson", "given": ["David"]}],
        "gender": "male",
        "birthDate": "1978-11-30",
        "extension": [
            {"url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race",
             "extension": [{"url": "ombCategory", "valueCoding": {"system": "urn:oid:2.16.840.1.113883.6.238", "code": "2106-3", "display": "White"}},
                           {"url": "text", "valueString": "White"}]},
        ],
    },
}

REJECT_REASONS = [
    "Patient denies current use of this medication per recent visit.",
    "Duplicate of existing chart entry — more recent documentation available.",
]


def _load_pair(stem: str):
    aug = json.loads((AUG_LABELS_DIR / f"{stem}.json").read_text(encoding="utf-8"))
    bundle_name = aug["paired_bundle"]
    bundle_path = FIXTURE_DIR / f"{bundle_name}.json"
    note_text = (NOTES_DIR / f"{stem}.txt").read_text(encoding="utf-8")
    return bundle_path, note_text, aug


def _serialize_dt(v):
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    raise TypeError(f"Cannot serialize {type(v)}")


async def main() -> int:
    from db import init_db, AsyncSessionLocal
    from fhir.local_bundle import load_demo_data
    from fhir.models import Document
    from services import proposals as proposal_svc
    from services import run_snapshot
    from context.auth import ReviewerIdentity, mint_review_token
    from db.models import PipelineRun, ProposalRecord, LLMCall

    await init_db()

    all_run_ids = []

    for stem in SELECTED_NOTES:
        print(f"\n{'='*60}")
        print(f"Running: {stem}")
        bundle_path, note_text, aug = _load_pair(stem)

        pc, _ = load_demo_data(bundle_path)

        profile = PATIENT_PROFILES.get(stem, {})
        if profile:
            pc.patient.update(profile)

        patient_name = None
        names = pc.patient.get("name", [])
        if names:
            n = names[0]
            given = " ".join(n.get("given", []))
            family = n.get("family", "")
            patient_name = f"{given} {family}".strip() or None

        doc = Document(
            id=aug.get("note_id", stem.split("-", 1)[0]),
            type="Progress note",
            date="2026-04-01",
            author="Benchmark corpus",
            text=note_text,
            encounter_id=None,
        )

        async with AsyncSessionLocal() as session:
            result = await proposal_svc._run_with_documents(
                pc, [doc], session,
                triggered_by="api:inline",
            )
            run_id = result["run_id"]
            all_run_ids.append(run_id)
            print(f"  Run {run_id}: {result.get('total_proposals', 0)} proposals")

            # Accept top CONFIDENT proposals, reject ATTENTION ones
            proposals = await proposal_svc.list_proposals(session, run_id=run_id)
            reviewer = ReviewerIdentity(display="Demo Reviewer")
            accepted = 0
            rejected = 0
            for p in proposals:
                if p["status"] != "pending":
                    continue
                if accepted < 2 and p["confidence_tier"] == "CONFIDENT":
                    await proposal_svc.accept_proposal(p["id"], session, reviewer=reviewer)
                    accepted += 1
                elif rejected < 1 and p["confidence_tier"] in ("ATTENTION", "REVIEW"):
                    reason = REJECT_REASONS[rejected % len(REJECT_REASONS)]
                    await proposal_svc.reject_proposal(p["id"], reason, session, reviewer=reviewer)
                    rejected += 1
            print(f"  Accepted: {accepted}, Rejected: {rejected}")

    reviewer = ReviewerIdentity(display="Demo Reviewer")
    token = await mint_review_token(reviewer)

    print(f"\nExporting fixture with {len(all_run_ids)} runs...")

    fixture = {"runs": [], "proposals": [], "llm_calls": [], "snapshots": {}, "review_token": {}}

    async with AsyncSessionLocal() as session:
        from sqlalchemy import select

        for run_id in all_run_ids:
            run = (await session.execute(
                select(PipelineRun).where(PipelineRun.id == run_id)
            )).scalar_one()
            fixture["runs"].append({
                "id": run.id,
                "patient_id": run.patient_id,
                "patient_name": run.patient_name,
                "triggered_by": run.triggered_by,
                "status": run.status,
                "started_at": run.started_at.isoformat(),
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "meta_json": run.meta_json,
            })

            props = (await session.execute(
                select(ProposalRecord).where(ProposalRecord.run_id == run_id)
            )).scalars().all()
            for p in props:
                fixture["proposals"].append({
                    "id": p.id,
                    "run_id": p.run_id,
                    "patient_id": p.patient_id,
                    "resource_type": p.resource_type,
                    "classification": p.classification,
                    "confidence_tier": p.confidence_tier,
                    "confidence_score": float(p.confidence_score),
                    "status": p.status,
                    "resource_json": p.resource_json,
                    "citations_json": p.citations_json,
                    "metadata_json": p.metadata_json,
                    "created_at": p.created_at.isoformat(),
                    "reviewed_at": p.reviewed_at.isoformat() if p.reviewed_at else None,
                    "reviewed_by": p.reviewed_by,
                })

            calls = (await session.execute(
                select(LLMCall).where(LLMCall.run_id == run_id)
            )).scalars().all()
            for c in calls:
                fixture["llm_calls"].append({
                    "id": c.id,
                    "run_id": c.run_id,
                    "document_id": c.document_id,
                    "stage": c.stage,
                    "call_type": c.call_type,
                    "model": c.model,
                    "prompt_version": c.prompt_version,
                    "input_tokens": c.input_tokens,
                    "output_tokens": c.output_tokens,
                    "reasoning_tokens": c.reasoning_tokens,
                    "cached_tokens": c.cached_tokens,
                    "latency_ms": c.latency_ms,
                    "usd_cost": float(c.usd_cost),
                    "status": c.status,
                    "error": c.error,
                    "started_at": c.started_at.isoformat(),
                    "finished_at": c.finished_at.isoformat(),
                })

            snapshot = run_snapshot.read(run_id)
            if snapshot:
                from dataclasses import asdict
                pc, docs = snapshot
                fixture["snapshots"][run_id] = {
                    "patient_context": asdict(pc),
                    "documents": [asdict(d) for d in docs],
                }

    from db.models import ReviewToken
    async with AsyncSessionLocal() as session:
        rt = (await session.execute(
            select(ReviewToken).where(ReviewToken.token == token)
        )).scalar_one()
        fixture["review_token"] = {
            "token": rt.token,
            "display": rt.display,
            "fhir_reference": rt.fhir_reference,
            "expires_at": rt.expires_at.isoformat(),
            "created_at": rt.created_at.isoformat(),
        }

    OUTPUT_PATH.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
    size_mb = OUTPUT_PATH.stat().st_size / 1024 / 1024
    print(f"\nExported to {OUTPUT_PATH} ({size_mb:.1f} MB)")
    print(f"  Runs: {len(fixture['runs'])}")
    print(f"  Proposals: {len(fixture['proposals'])}")
    print(f"  LLM calls: {len(fixture['llm_calls'])}")
    print(f"  Snapshots: {len(fixture['snapshots'])}")
    print(f"  Token: {token}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
