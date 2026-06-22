"""Prompt tuning (add-only): AI-draft a per-type extraction addon from a clinician's
failing note + intent, and test it against that note before saving.

The base stage-2 prompts are generalized and validated; an addon only appends domain
rules (e.g. "record cancer stage as a separate Observation, not in the Condition
name"). Drafting and testing run on the clinician's BYOK Gemini key. The failing note
is transient — used to draft and test, never persisted (only the saved addon is).
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from core.effective_profile import resolve_effective_profile
from core.extraction import extract_candidates
from core.llm import build_client, generate_structured
from core.preprocess import preprocess_document
from core.prompts import PROMPTS_BY_TYPE
from fhir.models import Document

_DRAFT_SYSTEM = """\
You write add-only extraction rules for a clinical NLP pipeline. A validated base \
prompt already extracts a FHIR resource type from a clinical note; your job is to \
produce a short block of ADDITIONAL rules that layer on top of it to fix a specific \
shortcoming the clinician describes.

Rules for your output:
- Output only the additional rules as plain text — no preamble, no markdown headers, \
no restating the base prompt.
- Add or refine extraction behavior; never relax safety, citation, or output-format \
requirements from the base prompt.
- Be specific and general at once: phrase rules so they generalize to similar notes, \
not just the one example. Do not hardcode values copied from the sample note.
- Keep it concise — a few targeted rules, not an essay.
If a current draft is provided, refine it using the new intent rather than starting over."""


class AddonDraft(BaseModel):
    addon: str = Field(description="Add-only extraction rules as plain text, no preamble")


async def draft_addon(
    *, resource_type: str, note: str, ideas: str, current_addon: str, gemini_key: str, model: str,
) -> str:
    """Draft or refine an add-only addon from the failing note + the clinician's intent."""
    base = PROMPTS_BY_TYPE[resource_type]
    user = (
        f"Resource type: {resource_type}\n\n"
        f"Base extraction prompt (reference only, do not repeat it):\n{base}\n\n"
        f"A clinical note this type extracted poorly:\n{note}\n\n"
        f"What the clinician wants changed:\n{ideas}\n\n"
    )
    if current_addon.strip():
        user += f"Current addon draft to refine:\n{current_addon}\n\n"
    user += "Write the additional rules."

    parsed, _usage, error = await generate_structured(
        build_client(gemini_key), model, system=_DRAFT_SYSTEM, user=user, schema=AddonDraft, thinking="low",
    )
    if error or parsed is None:
        raise RuntimeError(error or "draft failed")
    return parsed.addon.strip()


def _items(out, resource_type: str) -> list[dict]:
    return [i.model_dump(mode="json") for i in (out.candidates.get(resource_type) or [])]


async def test_addon(*, resource_type: str, note: str, addon: str, gemini_key: str, model: str) -> dict:
    """Run stage-2 on `note` with and without the addon; return both item sets for a diff."""
    client = build_client(gemini_key)
    pnote = preprocess_document(Document(id="tune-note", type="note", date="", author="", text=note))

    base_out = await extract_candidates(pnote, client, model=model, effective=None)
    eff = resolve_effective_profile(
        {"prompts": {resource_type: {"active_version": 1, "versions": [{"version": 1, "text": addon}]}}}
    )
    addon_out = await extract_candidates(pnote, client, model=model, effective=eff)

    return {
        "resource_type": resource_type,
        "base": _items(base_out, resource_type),
        "addon": _items(addon_out, resource_type),
    }
