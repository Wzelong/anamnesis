import {
  ClipboardList,
  Microscope,
  Pill,
  Scissors,
  ShieldAlert,
  Users,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"

export const RESOURCE_ICON: Record<string, LucideIcon> = {
  Condition: ClipboardList,
  MedicationRequest: Pill,
  Observation: Microscope,
  Procedure: Scissors,
  AllergyIntolerance: ShieldAlert,
  FamilyMemberHistory: Users,
}

export const RESOURCE_LABEL: Record<string, string> = {
  Condition: "Condition",
  MedicationRequest: "Medication",
  Observation: "Observation",
  Procedure: "Procedure",
  AllergyIntolerance: "Allergy",
  FamilyMemberHistory: "Family hx",
}

export const CLASSIFICATION_LABEL: Record<string, string> = {
  NEW: "New",
  UPDATING: "Update",
  CONFLICTING: "Conflict",
}

export const CLASSIFICATION_VARIANT: Record<string, "outline" | "secondary" | "destructive"> = {
  NEW: "secondary",
  UPDATING: "secondary",
  CONFLICTING: "secondary",
}

export const TIER_DOT: Record<string, string> = {
  ATTENTION: "bg-red-500",
  REVIEW: "bg-amber-500",
  CONFIDENT: "bg-transparent",
}

export const TIER_TEXT: Record<string, string> = {
  ATTENTION: "text-destructive",
  REVIEW: "text-warning-fg",
  CONFIDENT: "text-success-fg",
}

export const TIER_BADGE: Record<string, string> = {
  ATTENTION: "border-destructive/30 bg-destructive/10 text-destructive",
  REVIEW: "border-warning-border bg-warning-bg text-warning-fg",
  CONFIDENT: "border-success-border bg-success-bg text-success-fg",
}

export const TIER_LABEL: Record<string, string> = {
  ATTENTION: "Attention",
  REVIEW: "Caution",
  CONFIDENT: "Confident",
}
