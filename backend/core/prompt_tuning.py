"""Prompt tuning (add-only): AI-draft a per-type addon from a clinician's intent and
test it against a note before saving.

Two lanes per resource type, mapped to where stage-2 rules live:
  * capture — add-only ROUTING rules layered onto the scan (recall: which sentences
    reach the type).
  * extract — add-only EXTRACTION rules layered onto the parse prompt (shape).

The base prompts are generalized and validated; addons only append. Drafting and testing
run on the clinician's BYOK Gemini key. The note is transient — used to draft and test,
never persisted (only the saved addon is).
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from core.effective_profile import resolve_effective_profile
from core.extraction import extract_candidates
from core.llm import build_client, generate_structured
from core.preprocess import preprocess_document
from core.prompts import PROMPT_SCAN, PROMPTS_BY_TYPE
from fhir.models import Document

_DRAFT_EXTRACT_SYSTEM = """\
You write add-only extraction rules for a clinical NLP pipeline.

A validated base prompt already extracts one FHIR resource type from sentences the scan \
routed to it. Given a shortcoming the clinician describes, produce a short block of \
ADDITIONAL rules that layer on top to fix how the item is extracted. The base is never \
replaced.

# Instructions
- Add or refine extraction behavior only. Never relax the base prompt's safety, citation, \
or output-format requirements — the addon is strictly additive.
- This lane shapes the extracted item (fields, splitting, naming) — not which sentences \
are found (that is the capture lane).
- Write rules that generalize. State the trigger and the action ("When the note records X, \
extract it as Y …"); never hardcode values copied from the example note.
- When a rule's purpose is not self-evident, name the intent in one clause.
- Keep it tight: a few precise rules beat many vague ones.
- When current rules are provided, revise them to fold in the new intent and return the \
full updated set, not a diff.

# Output
Markdown. One bullet per rule, key directive in **bold**. No preamble, no headers, no \
restating the base — only the rules."""

_DRAFT_CAPTURE_SYSTEM = """\
You revise the routing rules for the scan step of a clinical NLP pipeline.

The scan reads a numbered clinical note and decides which sentences to route to each FHIR \
resource type. A sentence it does not route is never extracted — routing is the recall \
gate. You are given the CURRENT routing rules for one type (its Include / Exclude block) \
and a shortcoming the clinician describes. Return the FULL revised routing rules for that \
type, edited to fix it.

# Instructions
- You may edit the rules directly — tighten an Include, relax or remove an Exclude that \
causes a real miss — but keep the block coherent and in the same Include/Exclude shape.
- Preserve routing-priority and cross-type boundaries unless the clinician's intent is \
specifically to change them.
- This lane decides which sentences belong to the type (recall) — not how to format the \
output (that is the extract lane).
- Write rules that generalize; never hardcode values copied from the example note.
- Return the complete updated rules, not a diff or only the changes.

# Output
The revised routing rules as plain text in the same Include / Exclude style as the input. \
No preamble, no headers, no <resource> wrapper — only the rules."""


class AddonDraft(BaseModel):
    addon: str = Field(description="Add-only rules, Markdown bullets")


def _draft_context(lane: str, resource_type: str) -> tuple[str, str]:
    if lane == "capture":
        return _DRAFT_CAPTURE_SYSTEM, PROMPT_SCAN
    return _DRAFT_EXTRACT_SYSTEM, PROMPTS_BY_TYPE[resource_type]


async def draft_addon(
    *, lane: str, resource_type: str, note: str, ideas: str, current_addon: str,
    gemini_key: str, model: str,
) -> str:
    """Draft or refine an add-only addon for one lane, grounded in the base prompt, an
    example note, and any current rules."""
    system, base = _draft_context(lane, resource_type)
    parts = [
        f"Resource type: {resource_type}",
        f"<base_prompt>\n{base}\n</base_prompt>",
    ]
    if note.strip():
        parts.append(f"<note>\n{note}\n</note>")
    if current_addon.strip():
        parts.append(f"<current_rules>\n{current_addon}\n</current_rules>")
    parts.append(f"<intent>\n{ideas}\n</intent>")
    parts.append("Write the additional rules as Markdown bullets.")

    parsed, _usage, error = await generate_structured(
        build_client(gemini_key), model, system=system, user="\n\n".join(parts),
        schema=AddonDraft, thinking="low",
    )
    if error or parsed is None:
        raise RuntimeError(error or "draft failed")
    return parsed.addon.strip()


def _ov(text: str) -> dict:
    return {"active_version": 1, "versions": [{"version": 1, "text": text}]}


async def test_addon(
    *, resource_type: str, note: str, capture: str, extract: str, gemini_key: str, model: str,
) -> dict:
    """Run prod Stage 1->2 (preprocess -> scan/parse/clean) on `note` with the draft capture
    and extract addons applied, scoped to one resource type. Same steps and model as
    production extraction; the note is never persisted. Returns {resource_type, items}."""
    client = build_client(gemini_key)
    pnote = preprocess_document(Document(id="tune-note", type="note", date="", author="", text=note))
    preset: dict = {}
    if extract.strip():
        preset["prompts"] = {resource_type: _ov(extract)}
    if capture.strip():
        preset["capture_prompts"] = {resource_type: _ov(capture)}
    eff = resolve_effective_profile(preset) if preset else None
    out = await extract_candidates(pnote, client, model=model, effective=eff)
    items = [i.model_dump(mode="json") for i in (out.candidates.get(resource_type) or [])]
    return {"resource_type": resource_type, "items": items}
