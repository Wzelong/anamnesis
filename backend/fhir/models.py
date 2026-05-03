"""Plain dataclasses for reading FHIR data into Python."""
from dataclasses import dataclass, field


@dataclass
class Document:
    id: str
    type: str
    date: str
    author: str
    text: str
    encounter_id: str | None = None


@dataclass
class PatientContext:
    patient: dict
    conditions: list[dict] = field(default_factory=list)
    medications: list[dict] = field(default_factory=list)
    allergies: list[dict] = field(default_factory=list)
    observations: list[dict] = field(default_factory=list)
    family_history: list[dict] = field(default_factory=list)
    procedures: list[dict] = field(default_factory=list)
    encounters: list[dict] = field(default_factory=list)
    practitioners: list[dict] = field(default_factory=list)
    organizations: list[dict] = field(default_factory=list)
    documents: list[dict] = field(default_factory=list)
    provenances: list[dict] = field(default_factory=list)
