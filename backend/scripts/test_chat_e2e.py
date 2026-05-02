"""End-to-end test for the chat agent.

Hits POST /api/chat/{run_id}/stream against a running backend, parses the SSE
stream, and prints events in a readable form. Picks the latest run + first
proposal automatically; mints a fresh review token via the auth helper.

Usage:
    cd backend && uv run python scripts/test_chat_e2e.py
    cd backend && uv run python scripts/test_chat_e2e.py --case search
    cd backend && uv run python scripts/test_chat_e2e.py --case all
    cd backend && uv run python scripts/test_chat_e2e.py --base http://localhost:8042
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

import httpx
from sqlalchemy import select

from context.auth import ReviewerIdentity, mint_review_token
from db import AsyncSessionLocal
from db.models import PipelineRun, ProposalRecord


CASES: dict[str, list[str]] = {
    "source": [
        "Show me the source quote behind this proposal.",
    ],
    "list": [
        "List all conflicting proposals in this run.",
    ],
    "chart": [
        "Does this duplicate or conflict with anything in the existing chart?",
    ],
    "search": [
        "Look up amoxicillin and penicillin in RxNorm.",
    ],
    "edit": [
        "Propose a small edit to set the clinicalStatus to 'active' on this proposal.",
    ],
    "multi": [
        "What's the strongest evidence for this proposal?",
        "Anything in the notes I might be missing?",
    ],
}


async def pick_run_and_proposal() -> tuple[str, str | None, str]:
    async with AsyncSessionLocal() as session:
        run = (await session.execute(
            select(PipelineRun).order_by(PipelineRun.started_at.desc()).limit(1)
        )).scalar_one_or_none()
        if run is None:
            print("No runs in DB. Run the pipeline first.", file=sys.stderr)
            sys.exit(2)
        proposal = (await session.execute(
            select(ProposalRecord)
            .where(ProposalRecord.run_id == run.id)
            .order_by(ProposalRecord.created_at)
            .limit(1)
        )).scalar_one_or_none()
        return run.id, proposal.id if proposal else None, run.patient_name or run.patient_id or run.id


async def mint_token() -> str:
    return await mint_review_token(ReviewerIdentity(display="chat-e2e-tester"))


class StreamPrinter:
    """Stateful pretty-printer: keeps text and reasoning streams flowing inline."""

    def __init__(self) -> None:
        self.last: str | None = None  # 'text' | 'reasoning' | 'event' | None

    def _newline_if_needed(self, kind: str) -> None:
        if self.last is not None and self.last != kind:
            sys.stdout.write("\n")

    def handle(self, event: dict) -> None:
        t = event.get("type")
        if t == "text":
            self._newline_if_needed("text")
            sys.stdout.write(str(event.get("delta", "")))
            self.last = "text"
        elif t == "reasoning":
            if self.last != "reasoning":
                self._newline_if_needed("reasoning")
                sys.stdout.write("\033[2m[reasoning] ")  # dim
            sys.stdout.write(str(event.get("summary", "")))
            self.last = "reasoning"
        elif t == "tool_call_start":
            self._end_dim()
            args = json.dumps(event.get("args", {}), ensure_ascii=False)
            sys.stdout.write(f"\n[tool→ {event.get('name')}] {args}")
            self.last = "event"
        elif t == "tool_call_result":
            self._end_dim()
            marker = "✓" if event.get("ok") else "✗"
            sys.stdout.write(f"\n[tool {marker} {event.get('id', '')[-6:]}] {event.get('summary', '')}")
            self.last = "event"
        elif t == "proposed_edit":
            self._end_dim()
            rt = (event.get("resource") or {}).get("resourceType", "?")
            sys.stdout.write(
                f"\n[proposed_edit] proposal={event.get('proposal_id')} "
                f"resourceType={rt} rationale={event.get('rationale', '')!r}"
            )
            self.last = "event"
        elif t == "error":
            self._end_dim()
            sys.stdout.write(f"\n\033[31m[ERROR] {event.get('message')}\033[0m")
            self.last = "event"
        elif t == "done":
            self._end_dim()
            sys.stdout.write("\n[done]")
            self.last = "event"
        sys.stdout.flush()

    def _end_dim(self) -> None:
        if self.last == "reasoning":
            sys.stdout.write("\033[0m")


async def stream_chat(
    base: str,
    token: str,
    run_id: str,
    selected_proposal_id: str | None,
    messages: list[dict],
) -> None:
    url = f"{base}/api/chat/{run_id}/stream"
    headers = {"Authorization": f"Bearer {token}"}
    body = {"messages": messages, "selected_proposal_id": selected_proposal_id}

    printer = StreamPrinter()
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, read=120.0)) as client:
        async with client.stream("POST", url, headers=headers, json=body) as resp:
            if resp.status_code != 200:
                txt = await resp.aread()
                print(f"\nHTTP {resp.status_code}: {txt.decode(errors='ignore')}", file=sys.stderr)
                sys.exit(1)
            buffer = ""
            async for chunk in resp.aiter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    raw, buffer = buffer.split("\n\n", 1)
                    line = next((l for l in raw.split("\n") if l.startswith("data:")), None)
                    if not line:
                        continue
                    payload = line[5:].strip()
                    if not payload:
                        continue
                    try:
                        event = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    printer.handle(event)


async def run_case(
    case: str,
    base: str,
    token: str,
    run_id: str,
    selected_proposal_id: str | None,
    patient_label: str,
) -> None:
    prompts = CASES[case]
    print(f"\n\n=== case: {case} ===")
    print(f"run={run_id}  proposal={selected_proposal_id}  patient={patient_label}")
    history: list[dict] = []
    for prompt in prompts:
        print(f"\n\n> {prompt}")
        history.append({"role": "user", "content": prompt})
        await stream_chat(base, token, run_id, selected_proposal_id, history)
        # Note: we don't capture the assistant reply into history since the SSE
        # stream gives us pieces; for multi-turn the second turn just resends
        # the user prompts. Good enough for smoke testing tool dispatch.


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8042")
    parser.add_argument(
        "--case",
        default="source",
        choices=[*CASES.keys(), "all"],
        help="Which test case to run (default: source).",
    )
    parser.add_argument("--run-id", default=None, help="Override run id.")
    parser.add_argument("--proposal-id", default=None, help="Override proposal id.")
    args = parser.parse_args()

    if args.run_id:
        run_id = args.run_id
        proposal_id = args.proposal_id
        patient_label = "(override)"
    else:
        run_id, proposal_id, patient_label = await pick_run_and_proposal()

    token = await mint_token()
    print(f"Minted token (last 6): …{token[-6:]}")

    cases = list(CASES.keys()) if args.case == "all" else [args.case]
    for case in cases:
        await run_case(case, args.base, token, run_id, proposal_id, patient_label)

    print("\n")


if __name__ == "__main__":
    asyncio.run(main())
