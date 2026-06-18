"""BYOK secret sealing: encrypt at rest, redact to the iframe, decrypt in-process."""
import asyncio
import uuid

import pytest
from cryptography.fernet import Fernet

from config import settings
from core import byok


def _enable_byok():
    settings.config_secret_key = Fernet.generate_key().decode()


def test_seal_redact_unseal_roundtrip():
    _enable_byok()
    patch = {"fhir_ig": "us-core", "byok": {"gemini_api_key": "sk-secret-1234"}}

    sealed = byok.seal(patch)
    enc = sealed["byok"]["gemini_api_key"]
    assert "sk-secret-1234" not in str(sealed)          # no plaintext at rest
    assert byok._MARKER in enc and enc["last4"] == "1234"

    redacted = byok.redact(sealed)
    assert redacted["byok"]["gemini_api_key"] == {"set": True, "last4": "1234"}
    assert "sk-secret-1234" not in str(redacted)         # no plaintext to iframe
    assert byok._MARKER not in str(redacted)

    plain = byok.unseal(sealed)
    assert plain["byok"]["gemini_api_key"] == "sk-secret-1234"
    assert plain["fhir_ig"] == "us-core"                 # non-secret untouched


def test_placeholder_echo_does_not_wipe_secret():
    _enable_byok()
    # iframe echoes back the redacted placeholder; sealing must drop it so a
    # deep-merge leaves the stored key intact.
    sealed = byok.seal({"byok": {"gemini_api_key": {"set": True, "last4": "1234"}}})
    assert "gemini_api_key" not in sealed.get("byok", {})


def test_seal_without_key_rejects_secret():
    settings.config_secret_key = ""
    with pytest.raises(byok.SecretsDisabledError):
        byok.seal({"byok": {"gemini_api_key": "sk-x"}})
    # non-secret config still works with no key configured
    assert byok.seal({"fhir_ig": "mcode"}) == {"fhir_ig": "mcode"}


def test_set_config_stores_ciphertext_get_unseals():
    _enable_byok()
    from db import init_db
    from services import users

    sub = f"sub-{uuid.uuid4().hex}"

    async def run():
        await init_db()
        await users.register_session(sub)
        await users.set_config(sub, {"byok": {"gemini_api_key": "sk-live-9999"}})
        await users.set_config(sub, {"fhir_ig": "mcode"})   # deep-merge keeps byok
        return await users.get_config(sub)

    stored = asyncio.run(run())
    assert "sk-live-9999" not in str(stored)                 # ciphertext at rest
    assert byok.redact(stored)["byok"]["gemini_api_key"] == {"set": True, "last4": "9999"}
    assert byok.unseal(stored)["byok"]["gemini_api_key"] == "sk-live-9999"
    assert stored["fhir_ig"] == "mcode"
