"""VSAC FHIR terminology client: value-set expansion + code grounding."""
import asyncio
import base64

import pytest

from fhir import terminology as tx
from fhir.terminology import TerminologyError, expand_valueset, ground_codes, is_oid, validate_code


def _run(coro):
    return asyncio.run(coro)


def _vs(codes, total=None):
    contains = [{"system": s, "code": c, "display": d} for s, c, d in codes]
    return {"resourceType": "ValueSet", "expansion": {"total": total, "contains": contains}}


class _Stub:
    """Returns queued (status, body) per call; records url/params."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list = []

    async def __call__(self, url, headers, params):
        self.calls.append({"url": url, "headers": headers, "params": params})
        return self._responses[len(self.calls) - 1]


def test_is_oid():
    assert is_oid("2.16.840.1.113883.3.464.1003.103.12.1001")
    assert is_oid("urn:oid:2.16.840.1.113883.3.464")
    assert not is_oid("http://cts.nlm.nih.gov/fhir/ValueSet/x")
    assert not is_oid("Diabetes")


def test_auth_header_is_apikey_basic():
    h = tx._auth_header("SECRET")
    assert h["Authorization"] == "Basic " + base64.b64encode(b"apikey:SECRET").decode()
    assert h["Accept"] == "application/fhir+json"


def test_expand_requires_key():
    with pytest.raises(TerminologyError):
        _run(expand_valueset("2.16.1", ""))


def test_expand_by_oid_single_page():
    stub = _Stub([(200, _vs([("http://snomed.info/sct", "44054006", "Diabetes")], total=1))])
    codes = _run(expand_valueset("2.16.840.1.1", "KEY", get=stub))
    assert codes == [{"system": "http://snomed.info/sct", "code": "44054006", "display": "Diabetes"}]
    assert "/ValueSet/2.16.840.1.1/$expand" in stub.calls[0]["url"]
    assert "url" not in stub.calls[0]["params"]


def test_expand_by_url_uses_url_param():
    stub = _Stub([(200, _vs([("s", "c", "d")], total=1))])
    _run(expand_valueset("http://example.org/vs/diabetes", "KEY", get=stub))
    assert stub.calls[0]["url"].endswith("/ValueSet/$expand")
    assert stub.calls[0]["params"]["url"] == "http://example.org/vs/diabetes"


def test_expand_pages_until_total():
    page1 = [("http://snomed.info/sct", str(i), "d") for i in range(tx._PAGE)]
    page2 = [("http://snomed.info/sct", "x1", "d"), ("http://snomed.info/sct", "x2", "d")]
    stub = _Stub([(200, _vs(page1, total=tx._PAGE + 2)), (200, _vs(page2, total=tx._PAGE + 2))])
    codes = _run(expand_valueset("2.16.1", "KEY", get=stub))
    assert len(codes) == tx._PAGE + 2
    assert [c["params"]["offset"] for c in stub.calls] == [0, tx._PAGE]


def test_expand_dedupes():
    dup = [("http://loinc.org", "1", "a"), ("http://loinc.org", "1", "a"), ("http://loinc.org", "2", "b")]
    stub = _Stub([(200, _vs(dup, total=3))])
    codes = _run(expand_valueset("2.16.1", "KEY", get=stub))
    assert len(codes) == 2


def test_expand_raises_on_error():
    stub = _Stub([(500, None)])
    with pytest.raises(TerminologyError):
        _run(expand_valueset("2.16.1", "KEY", get=stub))


def _vc(result: bool):
    return (200, {"resourceType": "Parameters", "parameter": [{"name": "result", "valueBoolean": result}]})


def test_validate_code_true_false():
    assert _run(validate_code("http://snomed.info/sct", "44054006", "KEY", get=_Stub([_vc(True)]))) is True
    assert _run(validate_code("http://snomed.info/sct", "000", "KEY", get=_Stub([_vc(False)]))) is False


def test_validate_code_non_200_is_false():
    assert _run(validate_code("s", "c", "KEY", get=_Stub([(404, None)]))) is False


def test_ground_codes_drops_unvalidated():
    codes = [
        {"system": "http://snomed.info/sct", "code": "real", "display": "x"},
        {"system": "http://snomed.info/sct", "code": "fake", "display": "y"},
    ]
    stub = _Stub([_vc(True), _vc(False)])
    kept = _run(ground_codes(codes, "KEY", get=stub))
    assert [c["code"] for c in kept] == ["real"]
