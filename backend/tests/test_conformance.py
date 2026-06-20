"""Layered conformance orchestrator (CONFORMANCE.md): L1 + L3 local, L2a/L2b remote."""
import asyncio

from fhir.conformance import assess_conformance, assess_local

SNOMED = "http://snomed.info/sct"
ICD10 = "http://hl7.org/fhir/sid/icd-10-cm"

VALID = {"resourceType": "Condition", "subject": {"reference": "Patient/1"},
         "code": {"coding": [{"system": SNOMED, "code": "1", "display": "x"}]}}
ICD_ONLY = {"resourceType": "Condition", "subject": {"reference": "Patient/1"},
            "code": {"coding": [{"system": ICD10, "code": "E11", "display": "x"}]}}
BAD_R4 = {"resourceType": "Condition", "subject": {"reference": "Patient/1"}, "code": "notacodeableconcept"}

OK_OO = (200, {"resourceType": "OperationOutcome", "issue": [{"severity": "information"}]})
ERR_OO = (200, {"resourceType": "OperationOutcome",
                "issue": [{"severity": "error", "diagnostics": "bad", "expression": ["Condition.code"]}]})
NO_OP = (404, {})


class _Stub:
    def __init__(self, ret):
        self._ret = ret
        self.calls: list = []

    async def validate(self, resource_type, resource, profile=None):
        self.calls.append((resource_type, profile))
        return self._ret


def _run(coro):
    return asyncio.run(coro)


def test_local_valid_r4():
    assert assess_local(VALID)["valid"] is True


def test_local_invalid_r4():
    r = assess_local(BAD_R4)
    assert r["valid"] is False and r["level"] == "r4"


def test_local_coding_subset_blocks():
    r = assess_local(ICD_ONLY, ["snomed"])
    assert r["valid"] is False and any(i["path"] == "Condition.code" for i in r["issues"])


def test_local_no_constraint_passes():
    assert assess_local(ICD_ONLY, None)["valid"] is True


def test_no_client_stays_local():
    r = _run(assess_conformance(VALID))
    assert r["level"] == "r4" and r["supported"] is False


def test_target_client_marks_profile_level():
    r = _run(assess_conformance(VALID, profiles=["http://p"], target_client=_Stub(OK_OO)))
    assert r["level"] == "profile" and r["supported"] is True and r["valid"] is True


def test_validator_supersedes_target():
    target, validator = _Stub(OK_OO), _Stub(OK_OO)
    r = _run(assess_conformance(VALID, profiles=["http://p"], target_client=target, validator=validator))
    assert r["level"] == "validator"
    assert validator.calls and not target.calls


def test_remote_error_invalidates():
    r = _run(assess_conformance(VALID, profiles=["http://p"], target_client=_Stub(ERR_OO)))
    assert r["valid"] is False and r["supported"] is True


def test_unsupported_remote_keeps_local_verdict():
    r = _run(assess_conformance(VALID, target_client=_Stub(NO_OP)))
    assert r["level"] == "r4" and r["supported"] is False and r["valid"] is True


def test_local_failure_persists_through_permissive_server():
    r = _run(assess_conformance(ICD_ONLY, allowed_systems=["snomed"], profiles=["http://p"], target_client=_Stub(OK_OO)))
    assert r["valid"] is False and r["supported"] is True
