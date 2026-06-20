import type { IgCatalog, IgDef, Preset } from "../types"

// Read-only IG catalog shipped with the app. Drives the config UI (which
// resource types and coding systems to render); presets store only deltas over
// these defaults. Graduates to a backend tool once IG manifests are authored.

export const BASE_IG = "us-core@6.1.0"

const US = "http://hl7.org/fhir/us/core/StructureDefinition"
const MCODE = "http://hl7.org/fhir/us/mcode/StructureDefinition"

export const IG_CATALOG: IgCatalog = {
  base: [
    {
      id: "us-core@6.1.0",
      title: "US Core 6.1.0",
      resources: {
        Condition: { inclusion: "supported", profiles: [`${US}/us-core-condition-problems-health-concerns`], coding: { systems: ["snomed", "icd10"] }, defaultEnabled: true },
        MedicationRequest: { inclusion: "supported", profiles: [`${US}/us-core-medicationrequest`], coding: { systems: ["rxnorm"] }, defaultEnabled: true },
        AllergyIntolerance: { inclusion: "supported", profiles: [`${US}/us-core-allergyintolerance`], coding: { systems: ["snomed", "rxnorm"] }, defaultEnabled: true },
        Observation: { inclusion: "supported", profiles: [`${US}/us-core-observation-clinical-result`], coding: { systems: ["loinc", "snomed"] }, defaultEnabled: true },
        Procedure: { inclusion: "supported", profiles: [`${US}/us-core-procedure`], coding: { systems: ["snomed"] }, defaultEnabled: true },
        FamilyMemberHistory: { inclusion: "optional", profiles: [], coding: { systems: ["snomed"] }, defaultEnabled: true },
      },
    },
  ],
  specialties: [
    {
      id: "mcode@4.0.0",
      title: "mCODE 4.0.0 (Oncology)",
      dependsOn: ["us-core@6.1.0"],
      resources: {
        Condition: { inclusion: "required", profiles: [`${MCODE}/mcode-primary-cancer-condition`, `${MCODE}/mcode-secondary-cancer-condition`], coding: { systems: ["snomed", "icd10"] }, defaultEnabled: true },
        Observation: { inclusion: "supported", profiles: [`${MCODE}/mcode-tnm-stage-group`, `${MCODE}/mcode-tumor-marker-test`], coding: { systems: ["loinc", "snomed"] }, defaultEnabled: true },
        MedicationRequest: { inclusion: "supported", profiles: [`${MCODE}/mcode-cancer-related-medication-request`], coding: { systems: ["rxnorm"] }, defaultEnabled: true },
        Procedure: { inclusion: "supported", profiles: [`${MCODE}/mcode-cancer-related-surgical-procedure`], coding: { systems: ["snomed"] }, defaultEnabled: true },
      },
    },
  ],
}

export function igById(id: string | null | undefined): IgDef | undefined {
  if (!id) return undefined
  return [...IG_CATALOG.base, ...IG_CATALOG.specialties].find((d) => d.id === id)
}

export function emptyPreset(id: string, name: string): Preset {
  return { id, name, ig: { base: BASE_IG, specialty: null }, resources: {}, coding: {}, prompts: {}, extensions: [] }
}
