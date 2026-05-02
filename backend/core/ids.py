"""Short, human-friendly IDs for surfaces an LLM agent has to echo back.

Crockford base32 alphabet (no i, l, o, u) avoids visual ambiguity, and a type
prefix keeps run vs. proposal IDs from being mixed up.
"""
from __future__ import annotations

import secrets

_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"
_DEFAULT_LENGTH = 8


def short_id(prefix: str, length: int = _DEFAULT_LENGTH) -> str:
    body = "".join(secrets.choice(_ALPHABET) for _ in range(length))
    return f"{prefix}_{body}"
