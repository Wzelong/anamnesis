import { usePathname } from "next/navigation"
import { create } from "zustand"
import { api } from "./api"
import type { Proposal, ProposalDetail, Run } from "./types"

interface AppState {
  runs: Run[]
  runsLoading: boolean
  selectedRunIds: Set<string>

  proposals: Proposal[]
  loading: boolean
  error: string | null
  runId: string | null
  token: string | null

  selectedProposalIds: Set<string>

  selectedId: string | null
  selectedDetail: ProposalDetail | null
  detailLoading: boolean

  runPanelOverride: boolean | null
  rightTab: "notes" | "chart" | "chat"

  fetchRuns: () => Promise<void>
  toggleRunSelection: (id: string) => void
  selectAllRuns: (allIds: string[]) => void
  clearRunSelection: () => void
  deleteSelectedRuns: () => Promise<void>
  fetchProposals: (runId: string) => Promise<void>
  toggleProposalSelection: (id: string) => void
  selectAllProposals: (allIds: string[]) => void
  clearProposalSelection: () => void
  bulkAcceptSelected: () => Promise<void>
  bulkRejectSelected: (reason: string) => Promise<void>
  acceptProposal: (id: string) => Promise<void>
  rejectProposal: (id: string, reason: string) => Promise<void>
  editProposal: (id: string, resource: Record<string, unknown>) => Promise<void>
  setToken: (token: string | null) => void
  setSelectedId: (id: string | null) => void
  fetchDetail: (id: string) => Promise<void>
  setRunPanelOverride: (v: boolean | null) => void
  setRightTab: (tab: "notes" | "chart" | "chat") => void
  reset: () => void
}

export const useAppStore = create<AppState>((set, get) => ({
  runs: [],
  runsLoading: false,
  selectedRunIds: new Set(),

  proposals: [],
  loading: false,
  error: null,
  runId: null,
  token: null,

  selectedProposalIds: new Set(),

  selectedId: null,
  selectedDetail: null,
  detailLoading: false,

  runPanelOverride: null,
  rightTab: "notes",

  fetchRuns: async () => {
    set({ runsLoading: true })
    try {
      const data = (await api.listRuns()) as Run[]
      const visible = new Set(data.map((r) => r.id))
      const filtered = new Set([...get().selectedRunIds].filter((id) => visible.has(id)))
      set({ runs: data, runsLoading: false, selectedRunIds: filtered })
    } catch {
      set({ runsLoading: false })
    }
  },

  toggleRunSelection: (id) => {
    const next = new Set(get().selectedRunIds)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    set({ selectedRunIds: next })
  },

  selectAllRuns: (allIds) => {
    const current = get().selectedRunIds
    const allSelected = allIds.length > 0 && allIds.every((id) => current.has(id))
    set({ selectedRunIds: allSelected ? new Set() : new Set(allIds) })
  },

  clearRunSelection: () => set({ selectedRunIds: new Set() }),

  deleteSelectedRuns: async () => {
    const ids = [...get().selectedRunIds]
    if (ids.length === 0) return
    await api.deleteRuns(ids)
    set({ selectedRunIds: new Set() })
    await get().fetchRuns()
  },

  fetchProposals: async (runId) => {
    if (get().runId === runId && get().proposals.length > 0) return
    set({
      loading: true,
      error: null,
      runId,
      selectedProposalIds: new Set(),
    })
    try {
      const data = (await api.listProposals({ runId })) as Proposal[]
      set({ proposals: data, loading: false })
    } catch (e) {
      set({ error: e instanceof Error ? e.message : "Failed to load", loading: false })
    }
  },

  toggleProposalSelection: (id) => {
    const next = new Set(get().selectedProposalIds)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    set({ selectedProposalIds: next })
  },

  selectAllProposals: (allIds) => {
    const current = get().selectedProposalIds
    const allSelected = allIds.length > 0 && allIds.every((id) => current.has(id))
    set({ selectedProposalIds: allSelected ? new Set() : new Set(allIds) })
  },

  clearProposalSelection: () => set({ selectedProposalIds: new Set() }),

  bulkAcceptSelected: async () => {
    const { selectedProposalIds, proposals, token, runId } = get()
    if (!token || selectedProposalIds.size === 0) return
    const ids = [...selectedProposalIds]
    const allConfident = ids.every((id) => {
      const p = proposals.find((x) => x.id === id)
      return p?.confidence_tier === "CONFIDENT"
    })
    if (!allConfident) return
    await Promise.all(ids.map((id) => api.acceptProposal(id, token)))
    set({ selectedProposalIds: new Set() })
    if (runId) {
      set({ proposals: [], runId: null })
      await get().fetchProposals(runId)
    }
  },

  bulkRejectSelected: async (reason) => {
    const { selectedProposalIds, token, runId } = get()
    if (!token || selectedProposalIds.size === 0) return
    const ids = [...selectedProposalIds]
    await Promise.all(ids.map((id) => api.rejectProposal(id, reason, token)))
    set({ selectedProposalIds: new Set() })
    if (runId) {
      set({ proposals: [], runId: null })
      await get().fetchProposals(runId)
    }
  },

  acceptProposal: async (id) => {
    const { token } = get()
    if (!token) return
    await api.acceptProposal(id, token)
    set({
      proposals: get().proposals.map((p) =>
        p.id === id ? { ...p, status: "accepted" } : p,
      ),
    })
    if (get().selectedId === id) await get().fetchDetail(id)
  },

  rejectProposal: async (id, reason) => {
    const { token } = get()
    if (!token) return
    await api.rejectProposal(id, reason, token)
    set({
      proposals: get().proposals.map((p) =>
        p.id === id ? { ...p, status: "rejected" } : p,
      ),
    })
    if (get().selectedId === id) await get().fetchDetail(id)
  },

  editProposal: async (id, resource) => {
    const { token } = get()
    if (!token) return
    await api.editProposal(id, resource, token)
    if (get().selectedId === id) await get().fetchDetail(id)
    const { runId } = get()
    if (runId) {
      const data = (await api.listProposals({ runId })) as Proposal[]
      set({ proposals: data })
    }
  },

  setToken: (token) => set({ token }),

  setSelectedId: (id) => {
    set({ selectedId: id, selectedDetail: null })
    if (id) get().fetchDetail(id)
  },

  fetchDetail: async (id) => {
    set({ detailLoading: true })
    try {
      const data = (await api.getProposal(id)) as ProposalDetail
      set({ selectedDetail: data, detailLoading: false })
    } catch {
      set({ detailLoading: false })
    }
  },

  setRunPanelOverride: (v) => set({ runPanelOverride: v }),

  setRightTab: (tab) => set({ rightTab: tab }),

  reset: () =>
    set({
      runs: [],
      runsLoading: false,
      selectedRunIds: new Set(),
      proposals: [],
      loading: false,
      error: null,
      runId: null,
      token: null,
      selectedProposalIds: new Set(),
      selectedId: null,
      selectedDetail: null,
      detailLoading: false,
    }),
}))

export function useRunPanelOpen(): boolean {
  const pathname = usePathname()
  const override = useAppStore((s) => s.runPanelOverride)
  return override ?? pathname === "/"
}

export function useToggleRunPanel(): () => void {
  const pathname = usePathname()
  return () => {
    const cur = useAppStore.getState().runPanelOverride ?? pathname === "/"
    useAppStore.setState({ runPanelOverride: !cur })
  }
}
