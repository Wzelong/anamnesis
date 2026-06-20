"""Stage 3 (L2a): opportunistic profile $validate against the target FHIR server."""
from __future__ import annotations

import asyncio

from fhir.profile_validate import validate_profile

COND = {"resourceType": "Condition", "meta": {"profile": ["http://p/cond"]}, "code": {"text": "x"}}

OK = (200, {"resourceType": "OperationOutcome", "issue": [{"severity": "information", "diagnostics": "All OK"}]})
ERR = (200, {"resourceType": "OperationOutcome", "issue": [
    {"severity": "error", "diagnostics": "Unknown code", "expression": ["Condition.code"]},
    {"severity": "warning", "diagnostics": "minor"},
]})
NOT_FOUND = (404, {"resourceType": "OperationOutcome", "issue": []})
NOT_OO = (200, {"resourceType": "Bundle"})


class _Stub:
    def __init__(self, ret):
        self._ret = ret
        self.calls: list = []

    async def validate(self, resource_type, resource, profile=None):
        self.calls.append((resource_type, profile))
        if isinstance(self._ret, Exception):
            raise self._ret
        return self._ret


def _run(coro):
    return asyncio.run(coro)


def test_no_client_unsupported():
    r = _run(validate_profile(None, COND, ["http://p/cond"]))
    assert r["supported"] is False and r["valid"] is None


def test_valid():
    c = _Stub(OK)
    r = _run(validate_profile(c, COND, ["http://p/cond"]))
    assert r["supported"] is True and r["valid"] is True
    assert c.calls == [("Condition", "http://p/cond")]


def test_invalid_surfaces_error_issue():
    r = _run(validate_profile(_Stub(ERR), COND, ["http://p/cond"]))
    assert r["supported"] is True and r["valid"] is False
    assert any(i["severity"] == "error" and i["path"] == "Condition.code" for i in r["issues"])


def test_unsupported_when_404():
    r = _run(validate_profile(_Stub(NOT_FOUND), COND, ["http://p/cond"]))
    assert r["supported"] is False


def test_unsupported_when_not_operation_outcome():
    r = _run(validate_profile(_Stub(NOT_OO), COND, ["http://p/cond"]))
    assert r["supported"] is False


def test_server_error_is_best_effort():
    r = _run(validate_profile(_Stub(RuntimeError("boom")), COND, ["http://p/cond"]))
    assert r["supported"] is False and r["valid"] is None


def test_no_profile_validates_base():
    c = _Stub(OK)
    _run(validate_profile(c, COND, []))
    assert c.calls == [("Condition", None)]
