import type { ComponentProps } from "react"
import { createRoot } from "react-dom/client"
import {
  App as McpApp,
  PostMessageTransport,
  applyDocumentTheme,
  applyHostStyleVariables,
} from "@modelcontextprotocol/ext-apps"
import { ReviewApp } from "./components/review-app"
import { Toaster } from "./components/ui/sonner"
import { parseStructured } from "./mcp"
import type { PatientHeader } from "./types"
import "./styles.css"

type ReviewProps = ComponentProps<typeof ReviewApp>
function App(props: ReviewProps) {
  return (
    <>
      <ReviewApp {...props} />
      <Toaster />
    </>
  )
}

const isMcp = window.location.origin === "null" || window.parent !== window

function applyContext(ctx: any) {
  if (ctx?.theme) applyDocumentTheme(ctx.theme)
  if (ctx?.styles?.variables) applyHostStyleVariables(ctx.styles.variables)
  if (ctx?.safeAreaInsets) {
    const { top, right, bottom, left } = ctx.safeAreaInsets
    document.body.style.padding = `${top}px ${right}px ${bottom}px ${left}px`
  }
}

export async function start(paint: (m: string, c?: string) => void) {
  const root = createRoot(document.getElementById("root")!)

  if (!isMcp) {
    const raw = new URLSearchParams(window.location.search).get("preview")
    const preview = (raw === "loading" || raw === "flow" || raw === "ready" ? raw : "flow") as
      | "loading" | "flow" | "ready"
    root.render(
      <App
        app={null}
        header={{
          patient_id: "demo", patient_name: "James Lee", birth_date: "1958-11-15", sex: "male", mrn: "BAY-0042-LEE",
          user: {
            user_key: "sub-demo", display_name: "Dr. Demo", is_returning: true, seen_count: 2,
            first_seen_at: "2026-06-01T00:00:00Z", last_seen_at: "2026-06-18T00:00:00Z", config: {},
          },
        }}
        preview={preview}
      />,
    )
    return
  }

  paint("Connecting to host…")
  const app = new McpApp({ name: "Anamnesis Review", version: "0.1.0" })
  let header: PatientHeader | null = null
  const gotResult = new Promise<void>((resolve) => {
    app.ontoolresult = (r) => {
      header = parseStructured<PatientHeader>(r as any)
      resolve()
    }
  })
  app.ontoolinput = () => {}
  app.onhostcontextchanged = (ctx) => applyContext(ctx)

  const connected = await Promise.race([
    app
      .connect(new PostMessageTransport(window.parent, window.parent))
      .then(() => true)
      .catch((e) => {
        paint("connect() threw: " + String(e), "#c00")
        return false
      }),
    new Promise<boolean>((r) => setTimeout(() => r(false), 5000)),
  ])

  if (!connected) {
    paint("Host handshake did not complete (5s). Rendering app shell anyway…", "#a60")
    setTimeout(() => root.render(<App app={app} header={header} />), 1200)
    return
  }

  await Promise.race([gotResult, new Promise((r) => setTimeout(r, 1500))])
  root.render(<App app={app} header={header} />)
}
