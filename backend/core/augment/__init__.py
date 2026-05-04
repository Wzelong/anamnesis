"""Stage 6: assemble augmentation proposals with valid FHIR R4 resources.

Submodules separate concerns:
  * `config` — US Core profile URLs, terminology system URIs, lookup maps.
  * `helpers` — small validation / parsing helpers (`_strip_none`, `_cc`,
    `_normalize_icd10`, etc.).
  * `builders` — per-resource-type FHIR builders + dispatch entry point
    `build_fhir_resource`.
  * `citations` — sentence-number -> char-span resolution (`resolve_citations`)
    and encounter mapping.
  * `assembly` — Stage 6 entry point `assemble_proposals` + `StageSixOutput`
    dataclass.

Public symbols are re-exported here so existing call sites
(`from core.augment import assemble_proposals`, etc.) keep working.
"""

from core.augment.assembly import StageSixOutput, assemble_proposals
from core.augment.builders import build_fhir_resource
from core.augment.citations import resolve_citations

__all__ = [
    "StageSixOutput",
    "assemble_proposals",
    "build_fhir_resource",
    "resolve_citations",
]
