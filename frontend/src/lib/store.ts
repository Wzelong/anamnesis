import { create } from "zustand"
import { api } from "./api"
import type { Proposal, ProposalDetail, Run } from "./types"

interface AppState {
  runs: Run[]
  runsLoading: boolean

  proposals: Proposal[]
  loading: boolean
  error: string | null
  runId: string | null
  token: string | null

  selectedId: string | null
  selectedDetail: ProposalDetail | null
  detailLoading: boolean

  runPanelOpen: boolean

  fetchRuns: () => Promise<void>
  fetchProposals: (runId: string) => Promise<void>
  setToken: (token: string | null) => void
  setSelectedId: (id: string | null) => void
  fetchDetail: (id: string) => Promise<void>
  toggleRunPanel: () => void
  reset: () => void
}

export const useAppStore = create<AppState>((set, get) => ({
  runs: [],
  runsLoading: false,

  proposals: [],
  loading: false,
  error: null,
  runId: null,
  token: null,

  selectedId: null,
  selectedDetail: null,
  detailLoading: false,

  runPanelOpen: true,

  fetchRuns: async () => {
    set({ runsLoading: true })
    try {
      const data = (await api.listRuns()) as Run[]
      set({ runs: data, runsLoading: false })
    } catch {
      set({ runsLoading: false })
    }
  },

  fetchProposals: async (runId) => {
    if (get().runId === runId && get().proposals.length > 0) return
    set({ loading: true, error: null, runId, selectedId: null, selectedDetail: null })
    try {
      const data = (await api.listProposals({ runId })) as Proposal[]
      set({ proposals: data, loading: false })
    } catch (e) {
      set({ error: e instanceof Error ? e.message : "Failed to load", loading: false })
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

  toggleRunPanel: () => set((s) => ({ runPanelOpen: !s.runPanelOpen })),

  reset: () =>
    set({
      runs: [],
      runsLoading: false,
      proposals: [],
      loading: false,
      error: null,
      runId: null,
      token: null,
      selectedId: null,
      selectedDetail: null,
      detailLoading: false,
    }),
}))
