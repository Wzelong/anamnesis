import { usePathname } from "next/navigation"
import { create } from "zustand"
import { api } from "./api"
import type { ChatMessage, Proposal, ProposalDetail, Run } from "./types"

const SLIDING_WINDOW_USER_TURNS = 10
let chatAbortController: AbortController | null = null
let chatMsgCounter = 0
let chatReasoningBuffer = ""

function extractReasoningTitle(raw: string): string {
  const trimmed = raw.replace(/^\s*\*+\s*/, "")
  const closing = trimmed.indexOf("**")
  return (closing >= 0 ? trimmed.slice(0, closing) : trimmed).trim()
}
const nextMsgId = () => `m_${Date.now().toString(36)}_${(chatMsgCounter++).toString(36)}`

const TOKEN_STORAGE_KEY = "anamnesis.review_token"

function persistToken(token: string | null) {
  if (typeof window === "undefined") return
  if (token) window.localStorage.setItem(TOKEN_STORAGE_KEY, token)
  else window.localStorage.removeItem(TOKEN_STORAGE_KEY)
}

export function readPersistedToken(): string | null {
  if (typeof window === "undefined") return null
  return window.localStorage.getItem(TOKEN_STORAGE_KEY)
}

interface AppState {
  runs: Run[]
  runsLoading: boolean
  runsHydrated: boolean
  selectedRunIds: Set<string>

  proposals: Proposal[]
  loading: boolean
  error: string | null
  actionError: string | null
  runId: string | null
  token: string | null
  tokenValid: boolean | null

  selectedProposalIds: Set<string>

  selectedId: string | null
  selectedDetail: ProposalDetail | null
  detailLoading: boolean

  runPanelOverride: boolean | null
  rightTab: "notes" | "chart" | "chat"
  contentView: "detail" | "right"

  chatByRun: Record<string, ChatMessage[]>
  chatStreaming: boolean
  chatStatus: string | null
  chatError: string | null

  fetchRuns: () => Promise<void>
  toggleRunSelection: (id: string) => void
  selectAllRuns: (allIds: string[]) => void
  clearRunSelection: () => void
  deleteSelectedRuns: () => Promise<void>
  clearActionError: () => void
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
  setContentView: (v: "detail" | "right") => void
  sendChatMessage: (text: string) => Promise<void>
  stopChat: () => void
  applyProposedEdit: (messageId: string) => Promise<void>
  dismissProposedEdit: (messageId: string) => void
  resetChatForRun: (runId: string) => void
  reset: () => void
}

export const useAppStore = create<AppState>((set, get) => ({
  runs: [],
  runsLoading: false,
  runsHydrated: false,
  selectedRunIds: new Set(),

  proposals: [],
  loading: false,
  error: null,
  actionError: null,
  runId: null,
  token: null,
  tokenValid: null,

  selectedProposalIds: new Set(),

  selectedId: null,
  selectedDetail: null,
  detailLoading: false,

  runPanelOverride: null,
  rightTab: "notes",
  contentView: "detail",

  chatByRun: {},
  chatStreaming: false,
  chatStatus: null,
  chatError: null,

  fetchRuns: async () => {
    set({ runsLoading: true })
    try {
      const data = (await api.listRuns()) as Run[]
      const visible = new Set(data.map((r) => r.id))
      const filtered = new Set([...get().selectedRunIds].filter((id) => visible.has(id)))
      set({ runs: data, runsLoading: false, runsHydrated: true, selectedRunIds: filtered })
    } catch {
      set({ runsLoading: false, runsHydrated: true })
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
    set({ actionError: null })
    let results: Array<{ write_result?: unknown }>
    try {
      results = await Promise.all(
        ids.map((id) => api.acceptProposal(id, token) as Promise<{ write_result?: unknown }>),
      )
    } catch (e) {
      set({ actionError: e instanceof Error ? e.message : "Accept failed" })
      return
    }
    set({ selectedProposalIds: new Set() })
    if (runId) {
      const wrote = results.some((r) => Boolean(r?.write_result))
      if (wrote) {
        const { refreshChart } = await import("@/components/layout/right-panel-data")
        await refreshChart(runId).catch(() => {})
      }
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
    const { token, runId } = get()
    if (!token) return
    set({ actionError: null })
    let result: { write_result?: unknown } | undefined
    try {
      result = (await api.acceptProposal(id, token)) as { write_result?: unknown } | undefined
    } catch (e) {
      set({ actionError: e instanceof Error ? e.message : "Accept failed" })
      return
    }
    set({
      proposals: get().proposals.map((p) =>
        p.id === id ? { ...p, status: "accepted" } : p,
      ),
    })
    if (get().selectedId === id) await get().fetchDetail(id)
    if (runId && result?.write_result) {
      const { refreshChart } = await import("@/components/layout/right-panel-data")
      await refreshChart(runId).catch(() => {})
    }
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

  setToken: (token) => {
    persistToken(token)
    set({ token, tokenValid: token ? null : false })
    if (!token) return
    api.checkAuth(token)
      .then(() => set({ tokenValid: true }))
      .catch(() => {
        persistToken(null)
        set({ token: null, tokenValid: false })
      })
  },

  setSelectedId: (id) => {
    if (id === null) {
      set({ selectedId: null, selectedDetail: null, actionError: null })
      return
    }
    set({ selectedId: id, actionError: null })
    get().fetchDetail(id)
  },

  clearActionError: () => set({ actionError: null }),

  fetchDetail: async (id) => {
    set({ detailLoading: true })
    try {
      const data = (await api.getProposal(id)) as ProposalDetail
      if (get().selectedId !== id) return
      set({ selectedDetail: data, detailLoading: false })
    } catch {
      if (get().selectedId !== id) return
      set({ detailLoading: false })
    }
  },

  setRunPanelOverride: (v) => set({ runPanelOverride: v }),

  setRightTab: (tab) => set({ rightTab: tab }),

  setContentView: (v) => set({ contentView: v }),

  resetChatForRun: (runId) => {
    const next = { ...get().chatByRun }
    delete next[runId]
    set({ chatByRun: next })
  },

  stopChat: () => {
    chatAbortController?.abort()
    chatAbortController = null
    set({ chatStreaming: false, chatStatus: null })
  },

  sendChatMessage: async (text) => {
    const { runId, token, selectedId, chatByRun } = get()
    if (!runId || !text.trim()) return
    if (!token) {
      set({ chatError: "Sign in with the review link to chat." })
      return
    }

    const trimmed = text.trim()
    const userMsg: ChatMessage = { id: nextMsgId(), role: "user", content: trimmed }
    const existing = chatByRun[runId] ?? []
    const next = [...existing, userMsg]
    set({
      chatByRun: { ...chatByRun, [runId]: next },
      chatStreaming: true,
      chatStatus: "Thinking",
      chatError: null,
    })

    const payload = buildSlidingWindow(next)
    const ctrl = new AbortController()
    chatAbortController = ctrl

    try {
      const stream = await api.chatStream(
        runId,
        { messages: payload, selected_proposal_id: selectedId },
        token,
        ctrl.signal,
      )
      await consumeChatStream(stream, runId)
    } catch (err) {
      if (ctrl.signal.aborted) return
      set({ chatError: err instanceof Error ? err.message : "Chat failed" })
    } finally {
      if (chatAbortController === ctrl) chatAbortController = null
      set({ chatStreaming: false, chatStatus: null })
    }
  },

  applyProposedEdit: async (messageId) => {
    const { runId, token, chatByRun } = get()
    if (!runId || !token) return
    const msgs = chatByRun[runId] ?? []
    const msg = msgs.find((m) => m.id === messageId)
    if (!msg?.proposedEdit || msg.proposedEdit.status !== "pending") return

    const { proposalId, resource } = msg.proposedEdit
    try {
      await get().editProposal(proposalId, resource)
      updateChatMessage(messageId, runId, (m) => ({
        ...m,
        proposedEdit: m.proposedEdit && { ...m.proposedEdit, status: "applied" },
      }))
    } catch (err) {
      set({ chatError: err instanceof Error ? err.message : "Edit failed" })
    }
  },

  dismissProposedEdit: (messageId) => {
    const { runId } = get()
    if (!runId) return
    updateChatMessage(messageId, runId, (m) => ({
      ...m,
      proposedEdit: m.proposedEdit && { ...m.proposedEdit, status: "dismissed" },
    }))
  },

  reset: () => {
    chatAbortController?.abort()
    chatAbortController = null
    persistToken(null)
    set({
      runs: [],
      runsLoading: false,
      selectedRunIds: new Set(),
      proposals: [],
      loading: false,
      error: null,
      runId: null,
      token: null,
      tokenValid: null,
      selectedProposalIds: new Set(),
      selectedId: null,
      selectedDetail: null,
      detailLoading: false,
      chatByRun: {},
      chatStreaming: false,
      chatStatus: null,
      chatError: null,
    })
  },
}))

function buildSlidingWindow(messages: ChatMessage[]): Array<{ role: string; content: string }> {
  const userIdxs: number[] = []
  for (let i = 0; i < messages.length; i++) {
    if (messages[i].role === "user") userIdxs.push(i)
  }
  const cutoff = userIdxs.length > SLIDING_WINDOW_USER_TURNS
    ? userIdxs[userIdxs.length - SLIDING_WINDOW_USER_TURNS]
    : 0
  return messages
    .slice(cutoff)
    .filter((m) => (m.role === "user" || m.role === "assistant") && m.content)
    .map((m) => ({ role: m.role, content: m.content }))
}

function updateChatMessage(
  messageId: string,
  runId: string,
  updater: (m: ChatMessage) => ChatMessage,
) {
  const state = useAppStore.getState()
  const list = state.chatByRun[runId]
  if (!list) return
  const idx = list.findIndex((m) => m.id === messageId)
  if (idx === -1) return
  const next = list.slice()
  next[idx] = updater(list[idx])
  useAppStore.setState({ chatByRun: { ...state.chatByRun, [runId]: next } })
}

function pushChatMessage(runId: string, msg: ChatMessage) {
  const state = useAppStore.getState()
  const list = state.chatByRun[runId] ?? []
  useAppStore.setState({
    chatByRun: { ...state.chatByRun, [runId]: [...list, msg] },
  })
}

function appendToLastAssistantText(runId: string, delta: string): string {
  const state = useAppStore.getState()
  const list = state.chatByRun[runId] ?? []
  const last = list[list.length - 1]
  if (last && last.role === "assistant" && !last.toolName && !last.proposedEdit) {
    const updated: ChatMessage = { ...last, content: last.content + delta }
    const next = list.slice(0, -1).concat(updated)
    useAppStore.setState({ chatByRun: { ...state.chatByRun, [runId]: next } })
    return last.id
  }
  const newMsg: ChatMessage = { id: nextMsgId(), role: "assistant", content: delta }
  useAppStore.setState({
    chatByRun: { ...state.chatByRun, [runId]: [...list, newMsg] },
  })
  return newMsg.id
}

const HUMAN_TOOL_NAME: Record<string, string> = {
  list_proposals: "Listing proposals",
  get_proposal: "Reading proposal",
  get_chart: "Reading chart",
  get_doc: "Reading document",
  search_codes: "Searching codes",
  propose_edit: "Drafting edit",
}

async function consumeChatStream(stream: ReadableStream<Uint8Array>, runId: string) {
  const reader = stream.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const events = buffer.split("\n\n")
    buffer = events.pop() ?? ""
    for (const raw of events) {
      const line = raw.split("\n").find((l) => l.startsWith("data:"))
      if (!line) continue
      const json = line.slice(5).trim()
      if (!json) continue
      try {
        handleChatEvent(JSON.parse(json), runId)
      } catch {
        // ignore malformed event
      }
    }
  }
}

function handleChatEvent(
  event: { type: string; [k: string]: unknown },
  runId: string,
) {
  switch (event.type) {
    case "text":
      appendToLastAssistantText(runId, String(event.delta ?? ""))
      chatReasoningBuffer = ""
      useAppStore.setState({ chatStatus: null })
      break
    case "reasoning":
      chatReasoningBuffer += String(event.summary ?? "")
      useAppStore.setState({ chatStatus: extractReasoningTitle(chatReasoningBuffer) || null })
      break
    case "tool_call_start": {
      const name = String(event.name ?? "")
      chatReasoningBuffer = ""
      useAppStore.setState({ chatStatus: HUMAN_TOOL_NAME[name] ?? name })
      break
    }
    case "tool_call_result": {
      break
    }
    case "proposed_edit": {
      const proposalId = String(event.proposal_id ?? "")
      const resource = (event.resource as Record<string, unknown>) ?? {}
      const rationale = String(event.rationale ?? "")
      pushChatMessage(runId, {
        id: nextMsgId(),
        role: "assistant",
        content: "",
        proposedEdit: { proposalId, resource, rationale, status: "pending" },
      })
      break
    }
    case "error":
      useAppStore.setState({ chatError: String(event.message ?? "Chat error") })
      break
    case "done":
      chatReasoningBuffer = ""
      useAppStore.setState({ chatStatus: null })
      break
  }
}

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
