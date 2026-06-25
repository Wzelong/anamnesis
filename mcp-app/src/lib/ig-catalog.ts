import type { IgCatalog, IgDef, Preset } from "../types"
import catalog from "../../../shared/ig/catalog.json"

// Read-only IG catalog, single source of truth shared with the backend
// (shared/ig/catalog.json → backend/core/ig_catalog.py). Drives the config UI
// (which resource types and coding systems to render); presets store only deltas
// over these defaults. Adding an IG is a JSON edit picked up by both sides.

export const IG_CATALOG = catalog as unknown as IgCatalog

export const BASE_IG = IG_CATALOG.base[0].id

export function igById(id: string | null | undefined): IgDef | undefined {
  if (!id) return undefined
  return [...IG_CATALOG.base, ...IG_CATALOG.specialties].find((d) => d.id === id)
}

export interface FixedGroup {
  title: string
  codes: { system: string; code: string; display: string }[]
}

export interface ProfileGroup {
  title: string
  profiles: string[]
}

// Effective stack for a resource type: base, then specialty overlay.
function stackFor(preset: Preset) {
  const base = igById(preset.ig.base) ?? IG_CATALOG.base[0]
  const specialty = preset.ig.specialty ? igById(preset.ig.specialty) : undefined
  return { base, specialty }
}

// FHIR profiles the active stack applies to a resource, grouped by IG — the
// "what's in the profile" surface in the config UI (read-only).
export function profileGroupsFor(preset: Preset, rt: string): ProfileGroup[] {
  const { base, specialty } = stackFor(preset)
  const groups: ProfileGroup[] = []
  const baseP = base.resources[rt]?.profiles
  if (baseP?.length) groups.push({ title: base.title, profiles: baseP })
  const specP = specialty?.resources[rt]?.profiles
  if (specP?.length) groups.push({ title: specialty!.title, profiles: specP })
  return groups
}

// Coding systems bound for a resource — specialty overlay wins, else base.
export function codingSystemsFor(preset: Preset, rt: string): string[] {
  const { base, specialty } = stackFor(preset)
  return specialty?.resources[rt]?.coding.systems ?? base.resources[rt]?.coding.systems ?? []
}

// Effective inclusion (specialty overlay wins).
export function inclusionFor(preset: Preset, rt: string): "required" | "supported" | "optional" {
  const { base, specialty } = stackFor(preset)
  return specialty?.resources[rt]?.inclusion ?? base.resources[rt]?.inclusion ?? "optional"
}

// "…/StructureDefinition/mcode-primary-cancer-condition" → "primary cancer condition"
export function profileLabel(url: string): string {
  const slug = url.split("/").pop() ?? url
  return slug.replace(/^(mcode|us-core)-/, "").replace(/-/g, " ")
}

// Codes the active profiles pin for a resource type, grouped by IG (base, then
// specialty) — read-only in the config UI. Mirrors backend ig_catalog.fixed_codings.
export function fixedGroupsFor(preset: Preset, rt: string): FixedGroup[] {
  const groups: FixedGroup[] = []
  const base = igById(preset.ig.base) ?? IG_CATALOG.base[0]
  const baseFixed = base.resources[rt]?.fixed
  if (baseFixed?.length) groups.push({ title: base.title, codes: baseFixed })
  const specialty = preset.ig.specialty ? igById(preset.ig.specialty) : undefined
  const specFixed = specialty?.resources[rt]?.fixed
  if (specFixed?.length) groups.push({ title: specialty!.title, codes: specFixed })
  return groups
}

export function emptyPreset(id: string, name: string): Preset {
  return { id, name, ig: { base: BASE_IG, specialty: null }, resources: {}, coding: {}, prompts: {}, extensions: [] }
}
