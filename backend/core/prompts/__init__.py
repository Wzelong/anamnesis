"""Pipeline prompts. Written outcome-first for GPT-5.x conventions.

Structured Outputs carries the schema, so prompts do not describe field
shapes. Prompts encode clinical decision rules only. Bump `PROMPT_VERSION`
to invalidate the cache when any prompt changes.

Submodules group prompts by pipeline stage; everything is re-exported here so
existing call sites (`from core.prompts import PROMPT_SCAN`, etc.) keep
working unchanged.
"""

# Bumping this string invalidates every JsonCache entry that mixes it into
# its key — Stage 2 (note_hash, model, prompt_version), Stage 3 (scope,
# prompt_version, sorted_group_keys), Stage 4 (term, code_system,
# prompt_version), and the doc guardrail (model, prompt_version, sha256(text)).
# Bump on any prompt edit so cached results from the old prompt don't bleed
# into a new run.
PROMPT_VERSION = "2026-06-26.02"

from core.prompts.stage1_scan import PROMPT_SCAN
from core.prompts.stage2_parse import (
    PROMPT_CLEAN,
    PROMPT_PARSE_ALLERGY,
    PROMPT_PARSE_CONDITION,
    PROMPT_PARSE_FAMILY_HISTORY,
    PROMPT_PARSE_MEDICATION,
    PROMPT_PARSE_OBSERVATION,
    PROMPT_PARSE_PROCEDURE,
    PROMPTS_BY_TYPE,
)
from core.prompts.stage3_merge import PROMPT_MERGE_ADJUDICATE
from core.prompts.stage4_coding import (
    PROMPT_CODE_SELECT,
    SYSTEM_REFINE_HINTS,
    build_code_select_prompt,
)
from core.prompts.stage5_reconcile import PROMPT_RECONCILE, RECONCILE_TYPE_RULES

__all__ = [
    "PROMPT_VERSION",
    "PROMPT_SCAN",
    "PROMPT_CLEAN",
    "PROMPT_PARSE_ALLERGY",
    "PROMPT_PARSE_CONDITION",
    "PROMPT_PARSE_FAMILY_HISTORY",
    "PROMPT_PARSE_MEDICATION",
    "PROMPT_PARSE_OBSERVATION",
    "PROMPT_PARSE_PROCEDURE",
    "PROMPTS_BY_TYPE",
    "PROMPT_MERGE_ADJUDICATE",
    "PROMPT_CODE_SELECT",
    "SYSTEM_REFINE_HINTS",
    "build_code_select_prompt",
    "PROMPT_RECONCILE",
    "RECONCILE_TYPE_RULES",
]
