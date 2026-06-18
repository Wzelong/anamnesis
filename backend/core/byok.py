"""Field-level encryption for BYOK secrets in `app_user.config`.

Secret fields (API keys) are Fernet-encrypted at rest under `CONFIG_SECRET_KEY`
and only ever decrypted in-process to build a client. The iframe sees a presence
flag (`set` + `last4`), never plaintext. Keying a secret to an unverified `sub`
is forbidden, so the tools that read/write config are token-verified (AUTH.md).

Three operations:
  * `seal`   — encrypt secret fields in a patch before it is stored.
  * `redact` — replace encrypted fields with presence flags for the iframe.
  * `unseal` — decrypt in-process (pipeline use only; never returned to caller).
"""
from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from config import settings

SECRET_FIELDS = frozenset({"gemini_api_key", "umls_api_key"})
_MARKER = "_enc"  # key present on an encrypted value dict


class SecretsDisabledError(RuntimeError):
    """A secret was supplied but no CONFIG_SECRET_KEY is configured."""


@lru_cache(maxsize=4)
def _fernet_for(key: str) -> Fernet:
    # Derive a valid Fernet key from any secret so CONFIG_SECRET_KEY can be an
    # arbitrary string (e.g. Render's generateValue), not a pre-formatted key.
    derived = base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest())
    return Fernet(derived)


def _fernet() -> Fernet | None:
    key = settings.config_secret_key
    return _fernet_for(key) if key else None


def _is_marker(v: object) -> bool:
    return isinstance(v, dict) and _MARKER in v


def seal(patch: dict) -> dict:
    """Return a copy of `patch` with SECRET_FIELDS plaintext encrypted.

    A non-empty plaintext secret is encrypted into a marker. An already-sealed
    marker passes through. Any other value for a secret field (a redaction
    placeholder, empty, None) is dropped so a deep-merge leaves the stored
    secret unchanged — the iframe echoing back a placeholder never wipes a key.
    """
    return _seal_walk(patch, _fernet())


def _seal_walk(obj: object, f: Fernet | None) -> object:
    if not isinstance(obj, dict):
        return obj
    out: dict = {}
    for k, v in obj.items():
        if k in SECRET_FIELDS:
            if isinstance(v, str) and v.strip():
                if f is None:
                    raise SecretsDisabledError(
                        "CONFIG_SECRET_KEY is required to store a secret"
                    )
                out[k] = {_MARKER: f.encrypt(v.encode()).decode(), "last4": v.strip()[-4:]}
            elif _is_marker(v):
                out[k] = v
            # else: drop -> unchanged on merge
        elif isinstance(v, dict):
            out[k] = _seal_walk(v, f)
        else:
            out[k] = v
    return out


def redact(config: dict) -> dict:
    """Replace encrypted fields with `{set, last4}`; never returns plaintext."""
    return _redact_walk(config)


def _redact_walk(obj: object) -> object:
    if _is_marker(obj):
        return {"set": True, "last4": obj.get("last4")}
    if isinstance(obj, dict):
        return {k: _redact_walk(v) for k, v in obj.items()}
    return obj


def unseal(config: dict) -> dict:
    """Decrypt secret fields to plaintext. In-process use only — never returned
    to the iframe. A missing key or undecryptable value yields None."""
    return _unseal_walk(config, _fernet())


def _unseal_walk(obj: object, f: Fernet | None) -> object:
    if _is_marker(obj):
        if f is None:
            return None
        try:
            return f.decrypt(obj[_MARKER].encode()).decode()
        except (InvalidToken, ValueError):
            return None
    if isinstance(obj, dict):
        return {k: _unseal_walk(v, f) for k, v in obj.items()}
    return obj


def deep_merge(base: dict, patch: dict) -> dict:
    """Recursive merge so a nested patch (e.g. `byok`) does not clobber siblings."""
    out = dict(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out
