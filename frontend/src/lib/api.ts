const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8042"

export async function apiFetch<T = unknown>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
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

  listProposals: (params: { runId?: string; patientId?: string }) => {
    const q = new URLSearchParams()
    if (params.runId) q.set("run_id", params.runId)
    if (params.patientId) q.set("patient_id", params.patientId)
    return apiFetch(`/api/proposals?${q}`)
  },

  getProposal: (id: string) => apiFetch(`/api/proposals/${id}`),

  getDocuments: (runId: string) => apiFetch(`/api/runs/${runId}/documents`),

  getChart: (runId: string) => apiFetch(`/api/runs/${runId}/chart`),

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

  editProposal: (id: string, resource: Record<string, unknown>, token: string) =>
    apiFetch(`/api/proposals/${id}`, {
      method: "PUT",
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify({ resource }),
    }),
}
