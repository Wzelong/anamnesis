import { ScanText, Settings } from "lucide-react"
import type { PatientHeader } from "../types"

export function Landing({
  header,
  logoUrl,
  onAugment,
  onConfigure,
}: {
  header: PatientHeader | null
  logoUrl: string
  onAugment: () => void
  onConfigure: () => void
}) {
  const name = header?.patient_name ?? "this patient"
  return (
    <div className="flex-1 min-h-0 overflow-y-auto flex items-center justify-center px-4 py-6">
      <div className="w-full max-w-[380px] flex flex-col items-center text-center space-y-3">
        <img src={logoUrl} alt="Anamnesis" width={36} height={36} className="size-9" />
        <div className="space-y-1">
          <h1 className="text-base font-semibold tracking-tight">Augment {name}'s chart</h1>
          <p className="text-xs text-muted-foreground leading-relaxed">
            Reads the source notes and proposes FHIR additions for your review — nothing
            is written until you approve.
          </p>
        </div>

        <div className="w-full space-y-2">
          <button
            onClick={onAugment}
            className="w-full h-9 text-sm rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors cursor-pointer font-medium inline-flex items-center justify-center gap-2"
          >
            <ScanText className="size-4" />
            Augment chart
          </button>
          <button
            onClick={onConfigure}
            className="w-full h-9 text-sm rounded-md border hover:bg-accent transition-colors cursor-pointer font-medium inline-flex items-center justify-center gap-2"
          >
            <Settings className="size-3.5" />
            Configure
          </button>
        </div>
      </div>
    </div>
  )
}
