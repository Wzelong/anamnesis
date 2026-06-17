import { ArrowDown, ArrowUp, Minus } from "lucide-react"
import type { ConfidenceBreakdown } from "../types"

type FlagDirection = "up" | "down" | "neutral"

const CONNECTOR_FRAGMENTS = new Set([
  "in the setting of", "due to", "secondary to", "associated with",
  "in association with", "from history of", "from a history of",
  "in the context of", "related to", "on the background of",
])

function isFragmentReasoning(value: string): boolean {
  const t = value.trim().toLowerCase().replace(/[.!?]+$/, "")
  if (!t) return true
  if (t.split(/\s+/).length < 3) return true
  return CONNECTOR_FRAGMENTS.has(t)
}

function flagDirection(f: string): FlagDirection {
  if (f === "Single mention") return "down"
  if (f.startsWith("Mentioned in")) return "up"
  if (f === "Stated assertively in source") return "up"
  if (f === "Source language is uncertain or secondhand") return "down"
  if (f === "No terminology code found — verify manually") return "down"
  if (f.startsWith("Coded in")) return "up"
  if (f.startsWith("Conflicts with:")) return "down"
  if (f === "Already in chart") return "up"
  if (f === "Approximate match — verify") return "down"
  return "neutral"
}

function axisDirection(score: number): FlagDirection {
  if (score >= 0.85) return "up"
  if (score <= 0.5) return "down"
  return "neutral"
}

const AXIS_LABELS: { key: keyof ConfidenceBreakdown; label: string }[] = [
  { key: "certainty", label: "Certainty" },
  { key: "coding", label: "Coding" },
]

export function ReasoningSections({
  extraction,
  classification,
  classificationKind,
  merge,
  flags,
  breakdown,
}: {
  extraction: string
  classification: string
  classificationKind?: string
  merge?: string | null
  flags: string[]
  breakdown?: ConfidenceBreakdown | null
}) {
  const classLabel =
    classificationKind === "UPDATING" || classificationKind === "CONFLICTING"
      ? "Why this classification"
      : "Compared to chart"
  return (
    <div className="mt-8 flex flex-col gap-6">
      <Section title="Confidence">
        {breakdown ? (
          <ConfidenceBreakdownTable breakdown={breakdown} />
        ) : flags.length > 0 ? (
          <ul className="flex flex-col gap-1.5">
            {flags.map((f) => (
              <li key={f} className="flex items-start gap-2 text-sm">
                <FlagIndicator direction={flagDirection(f)} />
                <span className="flex-1">{f}</span>
              </li>
            ))}
          </ul>
        ) : (
          <div className="text-sm text-muted-foreground">
            No specific signals — assigned by confidence score alone.
          </div>
        )}
      </Section>

      <Section title="Reasoning">
        <div className="flex flex-col gap-3">
          <ReasoningRow label="What the note said" value={extraction} skipFragments />
          <ReasoningRow label={classLabel} value={classification} />
          {merge && <ReasoningRow label="Across notes" value={merge} />}
        </div>
      </Section>
    </div>
  )
}

function ReasoningRow({ label, value, skipFragments }: { label: string; value: string; skipFragments?: boolean }) {
  if (!value) return null
  if (skipFragments && isFragmentReasoning(value)) return null
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[11px] text-muted-foreground">{label}</span>
      <span className="text-sm leading-snug">{value}</span>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground mb-2">
        {title}
      </div>
      {children}
    </div>
  )
}

function ConfidenceBreakdownTable({ breakdown }: { breakdown: ConfidenceBreakdown }) {
  const order: Record<FlagDirection, number> = { down: 0, neutral: 1, up: 2 }
  const rows = AXIS_LABELS.map(({ key, label }) => ({
    key, label, axis: breakdown[key], direction: axisDirection(breakdown[key].score),
  })).sort((a, b) => order[a.direction] - order[b.direction])

  return (
    <ul className="flex flex-col gap-1.5">
      {rows.map(({ key, label, axis, direction }) => (
        <li key={key} className="flex items-start gap-2 text-sm">
          <FlagIndicator direction={direction} />
          <span className="text-xs text-muted-foreground w-20 shrink-0 pt-0.5">{label}</span>
          <span className="flex-1">{axis.reason}</span>
        </li>
      ))}
    </ul>
  )
}

function FlagIndicator({ direction }: { direction: FlagDirection }) {
  if (direction === "up") {
    return <ArrowUp className="size-3 shrink-0 text-emerald-600 dark:text-emerald-400 mt-0.5" aria-label="boosts confidence" />
  }
  if (direction === "down") {
    return <ArrowDown className="size-3 shrink-0 text-destructive mt-0.5" aria-label="reduces confidence" />
  }
  return <Minus className="size-3 shrink-0 text-muted-foreground mt-0.5" aria-label="context" />
}
