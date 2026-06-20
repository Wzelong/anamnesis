"""Base FHIR structural validation — conformance Layer 1 (see CONFORMANCE.md).

Validates a built resource dict against the FHIR R4B pydantic models from
`fhir.resources` before write. Catches datatypes, cardinality, and base-required
elements. Does NOT check US Core must-support / bindings — that is Layer 2 (the
profile `$validate`). R4B is the closest model set `fhir.resources` 8.x ships to
US Core's R4 (4.0.1); it validates our resource set faithfully.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from fhir.resources.R4B import get_fhir_model_class
from pydantic import ValidationError


@dataclass
class ValidationIssue:
    severity: str
    path: str
    message: str


@dataclass
class ValidationResult:
    valid: bool
    level: str = "r4"
    issues: list[ValidationIssue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "level": self.level,
            "issues": [asdict(i) for i in self.issues],
        }


def _error(path: str, message: str) -> ValidationIssue:
    return ValidationIssue(severity="error", path=path, message=message)


def validate_r4(resource: dict) -> ValidationResult:
    """Validate a resource dict against the base FHIR R4B model for its type."""
    rt = resource.get("resourceType")
    if not rt:
        return ValidationResult(valid=False, issues=[_error("resourceType", "missing resourceType")])
    try:
        model = get_fhir_model_class(rt)
    except (ValueError, KeyError):
        return ValidationResult(valid=False, issues=[_error("resourceType", f"unknown resource type: {rt}")])
    try:
        model.model_validate(resource)
    except ValidationError as exc:
        issues = [
            _error(".".join(str(p) for p in e.get("loc", ())), str(e.get("msg", "")))
            for e in exc.errors()
        ]
        return ValidationResult(valid=False, issues=issues)
    return ValidationResult(valid=True)
