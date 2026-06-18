"""Gemini (google-genai) structured-output calls + usage normalization.

One async helper, `generate_structured`, wraps the Gemini GenerateContent API
with a Pydantic response schema and returns the parsed model plus a usage dict
shaped like the telemetry layer expects (input / output / cached / reasoning
tokens), so `core.telemetry.record_call` and `core.pricing` stay unchanged.
"""
from __future__ import annotations

import copy
import logging
from functools import lru_cache
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel

from config import settings

log = logging.getLogger(__name__)

# Call sites still pass OpenAI-era effort words; map them to Gemini thinking levels.
_THINKING_LEVEL = {
    "none": "minimal",
    "minimal": "minimal",
    "low": "low",
    "medium": "medium",
    "high": "high",
}

# JSON Schema keywords Gemini's response_schema dialect does not accept.
_DROP_KEYS = {"additionalProperties", "$schema", "title", "default"}


@lru_cache(maxsize=128)
def _gemini_schema(model: type[BaseModel]) -> dict:
    """Pydantic model -> a schema Gemini accepts: $defs inlined, anyOf/null
    collapsed to `nullable`, unsupported keywords (additionalProperties, …) dropped.
    """
    js = model.model_json_schema()
    defs = js.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            return [walk(x) for x in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            target = copy.deepcopy(defs.get(node["$ref"].split("/")[-1], {}))
            target.update({k: v for k, v in node.items() if k != "$ref"})
            return walk(target)
        if "anyOf" in node:
            branches = node["anyOf"]
            non_null = [b for b in branches if b.get("type") != "null"]
            has_null = len(non_null) != len(branches)
            if len(non_null) == 1:
                merged = walk(non_null[0])
                if isinstance(merged, dict):
                    if has_null:
                        merged["nullable"] = True
                    if "description" in node:
                        merged.setdefault("description", node["description"])
                return merged
            node = {**node, "anyOf": [walk(b) for b in non_null]}
            if has_null:
                node["nullable"] = True
            return node
        return {k: walk(v) for k, v in node.items() if k not in _DROP_KEYS}

    return walk(js)


def build_client(api_key: str | None = None) -> genai.Client:
    """Gemini client for a BYOK key, falling back to the server key."""
    return genai.Client(api_key=api_key or settings.gemini_api_key)


def _normalize_usage(um: Any) -> dict | None:
    if um is None:
        return None
    thoughts = int(getattr(um, "thoughts_token_count", None) or 0)
    candidates = int(getattr(um, "candidates_token_count", None) or 0)
    return {
        # Thinking tokens bill at the output rate, so fold them into output_tokens
        # (mirrors OpenAI, where output_tokens already includes reasoning_tokens).
        "input_tokens": int(getattr(um, "prompt_token_count", None) or 0),
        "output_tokens": candidates + thoughts,
        "input_tokens_details": {"cached_tokens": int(getattr(um, "cached_content_token_count", None) or 0)},
        "output_tokens_details": {"reasoning_tokens": thoughts},
    }


async def generate_structured(
    client: genai.Client,
    model: str,
    *,
    system: str,
    user: str,
    schema: type[BaseModel],
    thinking: str = "low",
) -> tuple[BaseModel | None, dict | None, str | None]:
    """Return (parsed, usage, error). `error` is None on success."""
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json",
        response_json_schema=_gemini_schema(schema),
        thinking_config=types.ThinkingConfig(thinking_level=_THINKING_LEVEL.get(thinking, "low")),
    )
    try:
        resp = await client.aio.models.generate_content(model=model, contents=user, config=cfg)
    except Exception as exc:
        return None, None, f"{type(exc).__name__}: {exc}"

    usage = _normalize_usage(getattr(resp, "usage_metadata", None))
    text = getattr(resp, "text", None)
    if not text:
        return None, usage, "no_output_text"
    try:
        return schema.model_validate_json(text), usage, None
    except Exception as exc:
        return None, usage, f"parse_error: {type(exc).__name__}: {exc}"
