import type { App } from "@modelcontextprotocol/ext-apps"
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js"

export interface ProgressEvent {
  progress: number
  total?: number
  message?: string
}

export function parseStructured<T>(res: CallToolResult): T | null {
  if (res.structuredContent) return res.structuredContent as T
  const text = (res.content?.[0] as { text?: string } | undefined)?.text
  if (!text) return null
  try {
    return JSON.parse(text) as T
  } catch {
    return null
  }
}

export function resultText(res: CallToolResult): string {
  const c = res.content?.[0] as { text?: string } | undefined
  return c?.text ?? ""
}

export interface CallOptions {
  onprogress?: (p: ProgressEvent) => void
  timeout?: number
  maxTotalTimeout?: number
}

export async function callTool(
  app: App,
  name: string,
  args: Record<string, unknown> = {},
  opts?: CallOptions | ((p: ProgressEvent) => void),
): Promise<CallToolResult> {
  const o: CallOptions = typeof opts === "function" ? { onprogress: opts } : opts ?? {}
  return app.callServerTool(
    { name, arguments: args },
    {
      resetTimeoutOnProgress: true,
      ...(o.timeout ? { timeout: o.timeout } : {}),
      ...(o.maxTotalTimeout ? { maxTotalTimeout: o.maxTotalTimeout } : {}),
      ...(o.onprogress ? { onprogress: (p) => o.onprogress!(p as unknown as ProgressEvent) } : {}),
    },
  )
}

export async function setDisplayMode(app: App, fullscreen: boolean): Promise<string> {
  try {
    const r = await app.requestDisplayMode({ mode: fullscreen ? "fullscreen" : "inline" })
    return r.mode
  } catch {
    return "inline"
  }
}
