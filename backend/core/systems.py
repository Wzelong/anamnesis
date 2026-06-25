"""Single source of truth for terminology code systems.

Two tiers:
- RETRIEVABLE: the pipeline has a live retriever + can $validate-code (free on a
  UMLS key). These may be "open" — free-coded from a note.
- known but non-retrievable: canonical URI only. Usable in a codeset (pinned
  codes, asserted from the source / a value set), never free-coded or grounded.
  Covers the mCODE roster (CPT, ICD-O-3, NCIT, HGNC, ...). CPT/CDT are licensed.

Adding a free retrievable system: add its URI + UMLS source abbreviation and list
it in RETRIEVABLE. Adding a codeset-only system: just its URI.
"""
from __future__ import annotations

SYSTEM_URIS: dict[str, str] = {
    # retrievable
    "snomed": "http://snomed.info/sct",
    "loinc": "http://loinc.org",
    "rxnorm": "http://www.nlm.nih.gov/research/umls/rxnorm",
    "icd10": "http://hl7.org/fhir/sid/icd-10-cm",
    "icd10pcs": "http://www.cms.gov/Medicare/Coding/ICD10",
    "hcpcs": "http://www.cms.gov/Medicare/Coding/HCPCSReleaseCodeSets",
    # known, codeset-only (no retriever / not groundable here)
    "cpt": "http://www.ama-assn.org/go/cpt",
    "icdo3": "http://terminology.hl7.org/CodeSystem/icd-o-3",
    "ncit": "http://ncicb.nci.nih.gov/xml/owl/EVS/Thesaurus.owl",
    "hgnc": "http://www.genenames.org",
    "hgvs": "http://varnomen.hgvs.org",
    "sequenceontology": "http://www.sequenceontology.org/",
    "ucum": "http://unitsofmeasure.org",
}

RETRIEVABLE: set[str] = {"snomed", "loinc", "rxnorm", "icd10", "icd10pcs", "hcpcs"}

# UMLS source abbreviations for systems retrieved via the UMLS search API. Systems
# served by other backends (RxNav, NLM Clinical Tables) are absent by design.
UMLS_SAB: dict[str, str] = {
    "snomed": "SNOMEDCT_US",
    "icd10pcs": "ICD10PCS",
    "hcpcs": "HCPCS",
}

URI_TO_KEY: dict[str, str] = {uri: key for key, uri in SYSTEM_URIS.items()}

# URIs we can authoritatively $validate-code (= retrievable systems).
VALIDATABLE_URIS: set[str] = {SYSTEM_URIS[k] for k in RETRIEVABLE}
