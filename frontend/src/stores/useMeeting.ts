import { create } from 'zustand'

export type MeetingMode = 'interview' | 'meeting'
export type MeetingStatus = 'idle' | 'active' | 'completed'

export interface TranscriptLine {
  id: string
  text: string
  romaji: string
  speaker: string
  translationVi?: string
  timestamp: number
  isFinal: boolean
}

export interface Suggestion {
  id: string
  answerRomaji: string
  answerVi: string
  pinned: boolean
  timestamp: number
  streaming?: boolean
  elapsedMs?: number
  lineId?: string
}

interface MeetingState {
  meetingId: string | null
  mode: MeetingMode
  status: MeetingStatus
  language: string
  transcript: TranscriptLine[]
  suggestions: Suggestion[]
  nowDiscussing: string

  activeSuggestionLineId: string | null
  streamingSuggestion: { answerRomaji: string; answerVi: string } | null
  suggestionStartTime: number | null
  lineSuggestions: Record<string, Suggestion>

  setMeetingId: (id: string | null) => void
  setMode: (mode: MeetingMode) => void
  setStatus: (status: MeetingStatus) => void
  setLanguage: (lang: string) => void
  addTranscriptLine: (line: TranscriptLine) => void
  updateTranscriptLine: (id: string, updates: Partial<TranscriptLine>) => void
  updateLastLineForSpeaker: (speaker: string, updates: Partial<TranscriptLine>) => void
  startSuggestionStream: (lineId: string) => void
  appendSuggestionChunk: (field: string, chunk: string) => void
  addSuggestion: (s: Suggestion) => void
  dismissLineSuggestion: (lineId: string) => void
  clearAllSuggestions: () => void
  setNowDiscussing: (topic: string) => void
  reset: () => void
}

export const useMeeting = create<MeetingState>((set) => ({
  meetingId: null,
  mode: 'interview',
  status: 'idle',
  language: 'ja-JP',
  transcript: [],
  suggestions: [],
  nowDiscussing: '',
  activeSuggestionLineId: null,
  streamingSuggestion: null,
  suggestionStartTime: null,
  lineSuggestions: {},

  setMeetingId: (id) => set({ meetingId: id }),
  setMode: (mode) => set({ mode }),
  setStatus: (status) => set({ status }),
  setLanguage: (lang) => set({ language: lang }),

  addTranscriptLine: (line) =>
    set((s) => {
      if (!line.isFinal) {
        const interimId = `interim_${line.speaker}`
        const existing = s.transcript.findIndex(t => t.id === interimId)
        const updated = { ...line, id: interimId }
        if (existing >= 0) {
          const copy = [...s.transcript]
          copy[existing] = updated
          return { transcript: copy }
        }
        return { transcript: [...s.transcript.slice(-200), updated] }
      }
      const filtered = s.transcript.filter(t => t.id !== `interim_${line.speaker}`)
      return { transcript: [...filtered.slice(-200), line] }
    }),

  updateTranscriptLine: (id, updates) =>
    set((s) => ({
      transcript: s.transcript.map((t) =>
        t.id === id ? { ...t, ...updates } : t
      ),
    })),

  updateLastLineForSpeaker: (speaker, updates) =>
    set((s) => {
      let idx = [...s.transcript].reverse().findIndex(t => t.speaker === speaker && t.isFinal)
      if (idx < 0) {
        idx = [...s.transcript].reverse().findIndex(t => t.isFinal)
      }
      if (idx < 0) return {}
      const realIdx = s.transcript.length - 1 - idx
      const copy = [...s.transcript]
      copy[realIdx] = { ...copy[realIdx], ...updates }
      return { transcript: copy }
    }),

  startSuggestionStream: (lineId: string) =>
    set({
      activeSuggestionLineId: lineId,
      streamingSuggestion: { answerRomaji: '', answerVi: '' },
      suggestionStartTime: performance.now(),
    }),

  appendSuggestionChunk: (field, chunk) =>
    set((s) => {
      const current = s.streamingSuggestion || { answerRomaji: '', answerVi: '' }
      if (field === 'answer_romaji') {
        return { streamingSuggestion: { ...current, answerRomaji: current.answerRomaji + chunk } }
      } else if (field === 'answer_vi') {
        return { streamingSuggestion: { ...current, answerVi: current.answerVi + chunk } }
      }
      return {}
    }),

  addSuggestion: (suggestion) =>
    set((s) => {
      const elapsed = s.suggestionStartTime ? performance.now() - s.suggestionStartTime : undefined
      const lineId = suggestion.lineId || s.activeSuggestionLineId || ''
      const completed = { ...suggestion, elapsedMs: elapsed, lineId }
      const newLineSuggestions = lineId
        ? { ...s.lineSuggestions, [lineId]: completed }
        : s.lineSuggestions
      return {
        suggestions: [completed, ...s.suggestions].slice(0, 20),
        lineSuggestions: newLineSuggestions,
        streamingSuggestion: null,
        suggestionStartTime: null,
        activeSuggestionLineId: null,
      }
    }),

  dismissLineSuggestion: (lineId: string) =>
    set((s) => {
      const copy = { ...s.lineSuggestions }
      delete copy[lineId]
      return { lineSuggestions: copy }
    }),

  clearAllSuggestions: () =>
    set({
      suggestions: [],
      lineSuggestions: {},
      streamingSuggestion: null,
      activeSuggestionLineId: null,
      suggestionStartTime: null,
      nowDiscussing: '',
    }),

  setNowDiscussing: (topic) => set({ nowDiscussing: topic }),

  reset: () =>
    set({
      meetingId: null,
      status: 'idle',
      transcript: [],
      suggestions: [],
      nowDiscussing: '',
      activeSuggestionLineId: null,
      streamingSuggestion: null,
      suggestionStartTime: null,
      lineSuggestions: {},
    }),
}))
