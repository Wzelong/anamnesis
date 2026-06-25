// Single source of truth for terminology code systems the pipeline can retrieve
// and ground (mirrors backend/core/systems.py). Adding a free system is one entry
// here. CPT/CDT are intentionally absent — licensed, not retrievable on a free key.

export interface SystemDef {
  key: string
  uri: string
  short: string
  label: string
}

export const SYSTEMS: Record<string, SystemDef> = {
  snomed: { key: "snomed", uri: "http://snomed.info/sct", short: "SNOMED", label: "SNOMED CT" },
  icd10: { key: "icd10", uri: "http://hl7.org/fhir/sid/icd-10-cm", short: "ICD-10", label: "ICD-10-CM" },
  icd10pcs: { key: "icd10pcs", uri: "http://www.cms.gov/Medicare/Coding/ICD10", short: "ICD-10-PCS", label: "ICD-10-PCS" },
  hcpcs: { key: "hcpcs", uri: "http://www.cms.gov/Medicare/Coding/HCPCSReleaseCodeSets", short: "HCPCS", label: "HCPCS" },
  loinc: { key: "loinc", uri: "http://loinc.org", short: "LOINC", label: "LOINC" },
  rxnorm: { key: "rxnorm", uri: "http://www.nlm.nih.gov/research/umls/rxnorm", short: "RxNorm", label: "RxNorm" },
}

const URI_TO_KEY: Record<string, string> = Object.fromEntries(
  Object.values(SYSTEMS).map((s) => [s.uri, s.key]),
)

export const shortLabel = (key: string): string => SYSTEMS[key]?.short ?? key
export const uriOf = (key: string): string => SYSTEMS[key]?.uri ?? key
export const keyOfUri = (uri: string): string => URI_TO_KEY[uri] ?? uri
export const labelForUri = (uri: string): string => SYSTEMS[URI_TO_KEY[uri]]?.label ?? uri
