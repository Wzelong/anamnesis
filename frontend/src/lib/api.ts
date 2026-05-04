const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8042"

export class ApiError extends Error {
  status: number
  detail: string
  constructor(status: number, detail: string) {
    super(detail)
    this.name = "ApiError"
    this.status = status
    this.detail = detail
  }
}

export async function apiFetch<T = unknown>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (body && typeof body.detail === "string") detail = body.detail
    } catch {}
    throw new ApiError(res.status, detail)
  }
  return res.json()
}

export const api = {
  checkAuth: (token: string) =>
    apiFetch("/api/auth/check", {
      headers: { Authorization: `Bearer ${token}` },
    }),

  listRuns: () => apiFetch("/api/runs"),

  deleteRuns: (ids: string[]) =>
    apiFetch("/api/runs/delete", {
      method: "POST",
      body: JSON.stringify({ ids }),
    }),

  reset: () => apiFetch("/api/reset", { method: "POST" }),

  seedDemo: () =>
    apiFetch<{ run_id: string }>("/api/seed-demo", { method: "POST" }),

  listProposals: (params: { runId?: string; patientId?: string }) => {
    const q = new URLSearchParams()
    if (params.runId) q.set("run_id", params.runId)
    if (params.patientId) q.set("patient_id", params.patientId)
    return apiFetch(`/api/proposals?${q}`)
  },

  getProposal: (id: string) => apiFetch(`/api/proposals/${id}`),

  getRunProgress: (runId: string) =>
    apiFetch<{
      status: string
      progress: {
        current_stage: string
        stages_completed: Array<{ name: string; [key: string]: unknown }>
      } | null
      started_at: string | null
      error: string | null
    }>(`/api/runs/${runId}/progress`),

  getDocuments: (runId: string) => apiFetch(`/api/runs/${runId}/documents`),

  getChart: (runId: string) => apiFetch(`/api/runs/${runId}/chart`),

  refreshChart: (runId: string) =>
    apiFetch(`/api/runs/${runId}/chart/refresh`, { method: "POST" }),

  acceptProposal: (id: string, token: string) =>
    apiFetch(`/api/proposals/${id}/accept`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    }),

  rejectProposal: (id: string, reason: string, token: string) =>
    apiFetch(`/api/proposals/${id}/reject`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify({ reason }),
    }),

  reopenProposal: (id: string, token: string) =>
    apiFetch(`/api/proposals/${id}/reopen`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    }),

  editProposal: (id: string, resource: Record<string, unknown>, token: string) =>
    apiFetch(`/api/proposals/${id}`, {
      method: "PUT",
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify({ resource }),
    }),

  chatStream: async (
    runId: string,
    body: {
      messages: Array<{ role: string; content: string }>
      selected_proposal_id: string | null
    },
    token: string,
    signal: AbortSignal,
  ): Promise<ReadableStream<Uint8Array>> => {
    const res = await fetch(`${BASE}/api/chat/${runId}/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(body),
      signal,
    })
    if (!res.ok || !res.body) {
      throw new Error(`${res.status} ${res.statusText}`)
    }
    return res.body
  },
}
