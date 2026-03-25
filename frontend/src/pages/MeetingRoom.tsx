import { useEffect, useRef, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  Mic, MicOff, X, Send, Settings,
  FileText, ListTodo, Clock, AlertTriangle,
  Loader2, Download, Plus, Trash2, Search, RefreshCw,
  ChevronDown, User, Building2, Languages, StickyNote,
  Upload, CheckCircle2, XCircle, Sparkles, Copy, Check,
} from 'lucide-react'
import { cn, API_BASE as API } from '@/lib/utils'
import { Badge } from '@/components/ui/Badge'
import { Select } from '@/components/ui/Select'
import { useWebSocket } from '@/stores/useWebSocket'
import { useMeeting, type MeetingMode } from '@/stores/useMeeting'
import { useAuth } from '@/stores/useAuth'

type RightTab = 'context' | 'summary' | 'actions' | 'timeline' | 'decisions'

interface MeetingData { name: string; mode: string; status: string; transcript_count: number }

export default function MeetingRoom() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { status: wsStatus, connect, send, lastMessage } = useWebSocket()
  const { t } = useTranslation()
  const meeting = useMeeting()
  const { getHeaders } = useAuth()
  const transcriptEndRef = useRef<HTMLDivElement>(null)
  const [showSettings, setShowSettings] = useState(false)
  const [meetingInfo, setMeetingInfo] = useState<MeetingData | null>(null)
  const [rightTab, setRightTab] = useState<RightTab>('context')
  const [transcript, setTranscript] = useState<{ speaker: string; text: string; translation_vi?: string }[]>([])
  const [summary, setSummary] = useState<any>(null)
  const [actions, setActions] = useState<any[]>([])
  const [timeline, setTimeline] = useState<any[]>([])
  const [decisions, setDecisions] = useState<any[]>([])
  const [loadingIntel, setLoadingIntel] = useState<string | null>(null)
  const [transcriptSearch, setTranscriptSearch] = useState('')
  const [contextOnly, setContextOnly] = useState(false)
  const [suggestionsEnabled, setSuggestionsEnabled] = useState(true)
  const [availableModels, setAvailableModels] = useState<{ id: string; label: string; is_reasoning?: boolean }[]>([])
  const [activeModel, setActiveModel] = useState('')
  const [answerLength, setAnswerLength] = useState(3)
  const [firstAudioReceived, setFirstAudioReceived] = useState(false)
  const [jpLevel, setJpLevel] = useState<'simple' | 'natural' | 'formal'>('natural')

  // Context state
  const [notes, setNotes] = useState<Record<string, string>>({ personal: '', company: '', general: '' })
  const [glossary, setGlossary] = useState<{ id: number; jp: string; reading: string; vi: string }[]>([])
  const [newGlossary, setNewGlossary] = useState({ jp: '', reading: '', vi: '' })
  const [documents, setDocuments] = useState<{ id: number; filename: string; category: string; uploaded_at: string }[]>([])
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({ profile: true, company: false, vocab: false, notes: false })
  const [uploadFeedback, setUploadFeedback] = useState<{ type: 'success' | 'error'; msg: string } | null>(null)
  const [uploading, setUploading] = useState(false)

  const headers = getHeaders()

  useEffect(() => {
    fetch(`${API}/api/meetings/${id}`, { headers }).then((r) => r.ok ? r.json() : null).then((data) => {
      if (data) {
        setMeetingInfo(data)
        meeting.setMode(data.mode)
        if (data.transcript_count > 0) {
          loadTranscript()
          if (data.status !== 'completed') loadSavedTranscriptIntoStore()
        }
      }
    }).catch(() => {})
    fetch(`${API}/api/settings/models`).then(r => r.ok ? r.json() : []).then((models: { id: string; label: string }[]) => {
      if (models.length > 0) { setAvailableModels(models); setActiveModel(models[0].id) }
    }).catch(() => {})
    return () => {
      if (meeting.status === 'active') send({ type: 'stop_meeting' })
      meeting.reset()
    }
  }, [id])

  useEffect(() => { if (meetingInfo?.status !== 'completed' && wsStatus === 'disconnected') connect() }, [meetingInfo, wsStatus])

  const wasConnectedRef = useRef(false)
  useEffect(() => {
    if (wsStatus === 'connected') {
      if (wasConnectedRef.current && meeting.status === 'active' && id) {
        send({ type: 'start_meeting', meeting_id: id, language: meeting.language, mode: meeting.mode, model_id: activeModel })
      }
      wasConnectedRef.current = true
    }
  }, [wsStatus])

  useEffect(() => {
    if (!lastMessage) return
    const msg = lastMessage
    switch (msg.type) {
      case 'interim':
        if (!firstAudioReceived) setFirstAudioReceived(true)
        meeting.addTranscriptLine({ id: `interim_${msg.speaker}`, text: msg.text as string, romaji: (msg.romaji as string) || '', speaker: (msg.speaker as string) || '', timestamp: Date.now(), isFinal: false })
        break
      case 'final':
        if (!firstAudioReceived) setFirstAudioReceived(true)
        meeting.addTranscriptLine({ id: `final_${Date.now()}`, text: msg.text as string, romaji: (msg.romaji as string) || '', speaker: (msg.speaker as string) || '', timestamp: Date.now(), isFinal: true })
        break
      case 'translation':
        meeting.updateLastLineForSpeaker(msg.speaker as string, { translationVi: msg.vi as string })
        break
      case 'suggestion_start': {
        let lineId = (msg.line_id as string) || ''
        if (!lineId) {
          const lastOther = [...meeting.transcript].reverse().find(t => t.speaker !== 'me' && t.isFinal)
          if (lastOther) lineId = lastOther.id
        }
        meeting.startSuggestionStream(lineId)
        break
      }
      case 'suggestion_chunk': meeting.appendSuggestionChunk(msg.field as string, msg.chunk as string); break
      case 'suggestion_done': {
        let doneLineId = (msg.line_id as string) || ''
        if (!doneLineId && meeting.activeSuggestionLineId) doneLineId = meeting.activeSuggestionLineId
        meeting.addSuggestion({ id: (msg.id as string) || `sg_${Date.now()}`, answerRomaji: (msg.answer_romaji as string) || '', answerVi: (msg.answer_vi as string) || '', pinned: false, timestamp: Date.now(), lineId: doneLineId })
        break
      }
      case 'now_discussing': meeting.setNowDiscussing(msg.topic as string); break
      case 'model_switched': setActiveModel((msg.model_id as string) || ''); break
      case 'answer_length_changed': setAnswerLength(typeof msg.length === 'number' ? msg.length : 3); break
      case 'jp_level_changed': setJpLevel((msg.level as 'simple' | 'natural' | 'formal') || 'natural'); break
    }
  }, [lastMessage])

  useEffect(() => { transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [meeting.transcript.length])

  const loadTranscript = async () => { try { const r = await fetch(`${API}/api/meetings/${id}/transcript`, { headers }); if (r.ok) setTranscript(await r.json()) } catch {} }

  const loadSavedTranscriptIntoStore = async () => {
    try {
      const r = await fetch(`${API}/api/meetings/${id}/transcript`, { headers })
      if (!r.ok) return
      const entries: { id: number; speaker: string; text: string; romaji: string; translation_vi: string; answer_romaji: string; answer_vi: string }[] = await r.json()
      for (const e of entries) {
        const lineId = `saved_${e.id}`
        meeting.addTranscriptLine({ id: lineId, text: e.text, romaji: e.romaji || '', speaker: e.speaker, timestamp: Date.now(), isFinal: true })
        if (e.translation_vi) meeting.updateLastLineForSpeaker(e.speaker, { translationVi: e.translation_vi })
        if (e.answer_romaji || e.answer_vi) {
          meeting.addSuggestion({ id: `sg_saved_${e.id}`, answerRomaji: e.answer_romaji || '', answerVi: e.answer_vi || '', pinned: false, timestamp: Date.now(), lineId })
        }
      }
    } catch {}
  }

  const loadIntelligence = async (type: 'summary' | 'actions' | 'timeline' | 'decisions') => {
    setLoadingIntel(type)
    try { const r = await fetch(`${API}/api/meetings/${id}/${type}`, { method: 'POST', headers }); if (r.ok) { const data = await r.json(); ({ summary: setSummary, actions: setActions, timeline: setTimeline, decisions: setDecisions })[type](data) } } catch {}
    setLoadingIntel(null)
  }

  const exportTranscript = async (format: 'txt' | 'html' = 'txt') => {
    try {
      const r = await fetch(`${API}/api/meetings/${id}/transcript/export?format=${format}`, { headers })
      if (r.ok) {
        const data = await r.json()
        if (format === 'html') {
          const blob = new Blob([data.html], { type: 'text/html;charset=utf-8' })
          const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = data.filename; a.click()
        } else {
          const blob = new Blob([data.text], { type: 'text/plain;charset=utf-8' })
          const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = data.filename; a.click()
        }
      }
    } catch {}
  }

  // ── Context loaders ──────────────────────────────────────
  const loadNotes = useCallback(async () => {
    if (!id) return
    try {
      const r = await fetch(`${API}/api/meetings/${id}/notes`, { headers })
      if (r.ok) {
        const data = await r.json()
        const map: Record<string, string> = { personal: '', company: '', general: '' }
        data.forEach((n: any) => { map[n.category] = n.content })
        setNotes(map)
      }
    } catch {}
  }, [id])

  const saveNote = useCallback(async (category: string, content: string) => {
    if (!id) return
    try { await fetch(`${API}/api/meetings/${id}/notes/${category}`, { method: 'PUT', headers: { 'Content-Type': 'application/json', ...headers }, body: JSON.stringify({ content }) }) } catch {}
  }, [id])

  const loadGlossary = useCallback(async () => {
    if (!id) return
    try { const r = await fetch(`${API}/api/meetings/${id}/glossary`, { headers }); if (r.ok) setGlossary(await r.json()) } catch {}
  }, [id])

  const addGlossaryEntry = async () => {
    if (!id || !newGlossary.jp.trim()) return
    try {
      const r = await fetch(`${API}/api/meetings/${id}/glossary`, { method: 'POST', headers: { 'Content-Type': 'application/json', ...headers }, body: JSON.stringify(newGlossary) })
      if (r.ok) { setNewGlossary({ jp: '', reading: '', vi: '' }); loadGlossary() }
    } catch {}
  }

  const deleteGlossaryEntry = async (entryId: number) => {
    if (!id) return
    try { await fetch(`${API}/api/meetings/${id}/glossary/${entryId}`, { method: 'DELETE', headers }); loadGlossary() } catch {}
  }

  const loadDocuments = useCallback(async () => {
    if (!id) return
    try { const r = await fetch(`${API}/api/meetings/${id}/documents`, { headers }); if (r.ok) setDocuments(await r.json()) } catch {}
  }, [id])

  const uploadDocument = async (file: File, category: string) => {
    if (!id) return
    setUploading(true)
    setUploadFeedback(null)
    const fd = new FormData()
    fd.append('file', file)
    fd.append('category', category)
    try {
      const r = await fetch(`${API}/api/meetings/${id}/documents`, { method: 'POST', headers, body: fd })
      if (r.ok) {
        loadDocuments()
        setUploadFeedback({ type: 'success', msg: `${file.name} uploaded` })
      } else {
        const err = await r.text()
        setUploadFeedback({ type: 'error', msg: `Upload failed: ${r.status} ${err.slice(0, 100)}` })
      }
    } catch (e: any) {
      setUploadFeedback({ type: 'error', msg: `Upload error: ${e.message || 'Network error'}` })
    }
    setUploading(false)
    setTimeout(() => setUploadFeedback(null), 4000)
  }

  const deleteDocument = async (docId: number) => {
    if (!id) return
    try { await fetch(`${API}/api/meetings/${id}/documents/${docId}`, { method: 'DELETE', headers }); loadDocuments() } catch {}
  }

  useEffect(() => {
    if (rightTab === 'context') {
      loadNotes()
      loadGlossary()
      loadDocuments()
    }
  }, [rightTab, id])

  const toggleSection = (key: string) => setExpandedSections(prev => ({ ...prev, [key]: !prev[key] }))

  const toggleSuggestions = () => {
    const next = !suggestionsEnabled
    setSuggestionsEnabled(next)
    send({ type: 'toggle_suggestions', enabled: next })
    if (!next) {
      meeting.clearAllSuggestions()
    }
  }

  const switchModel = (modelId: string) => {
    setActiveModel(modelId)
    send({ type: 'switch_model', model_id: modelId })
  }

  const switchAnswerLength = (n: number) => {
    const clamped = Math.max(1, Math.min(10, n))
    setAnswerLength(clamped)
    send({ type: 'set_answer_length', length: clamped })
  }

  const switchJpLevel = (level: string) => {
    setJpLevel(level as 'simple' | 'natural' | 'formal')
    send({ type: 'set_jp_level', level })
  }

  const requestSuggestion = (lineId: string, text: string, romaji: string, length?: string) => {
    if (!suggestionsEnabled) return
    meeting.dismissLineSuggestion(lineId)
    send({ type: 'request_suggestion', line_id: lineId, text, romaji, ...(length ? { length } : {}) })
  }

  const [copiedSuggestionId, setCopiedSuggestionId] = useState<string | null>(null)
  const copySuggestion = (text: string, lineId: string) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopiedSuggestionId(lineId)
      setTimeout(() => setCopiedSuggestionId(null), 2000)
    })
  }

  const renderWithPauses = (text: string) => {
    if (!text.includes(' / ')) return text
    return text.split(' / ').map((segment, i, arr) => (
      <span key={i}>
        {segment}
        {i < arr.length - 1 && <span className="inline-block w-2 mx-0.5 text-primary/30 select-none" aria-hidden>|</span>}
      </span>
    ))
  }

  const isActive = meeting.status === 'active'
  const isCompleted = meetingInfo?.status === 'completed'
  const hasTranscript = transcript.length > 0 || meeting.transcript.length > 0

  const toggleMeeting = () => {
    if (isActive) { send({ type: 'stop_meeting' }); meeting.setStatus('idle') }
    else if (wsStatus === 'connected') { setFirstAudioReceived(false); send({ type: 'start_meeting', meeting_id: id, language: meeting.language, mode: meeting.mode, model_id: activeModel }); meeting.setStatus('active'); meeting.setMeetingId(id || null) }
  }

  const switchMode = (m: string) => {
    meeting.setMode(m as MeetingMode)
    if (id) fetch(`${API}/api/meetings/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json', ...headers }, body: JSON.stringify({ mode: m }) }).catch(() => {})
  }

  const filteredTranscript = transcriptSearch
    ? transcript.filter(e => e.text.toLowerCase().includes(transcriptSearch.toLowerCase()) || e.speaker.toLowerCase().includes(transcriptSearch.toLowerCase()) || (e.translation_vi || '').toLowerCase().includes(transcriptSearch.toLowerCase()))
    : transcript

  const tabs: { key: RightTab; label: string; icon: any }[] = [
    { key: 'context', label: t('tabs.context'), icon: StickyNote },
    { key: 'summary', label: t('tabs.summary'), icon: FileText },
    { key: 'actions', label: t('tabs.actions'), icon: ListTodo },
    { key: 'timeline', label: t('tabs.timeline'), icon: Clock },
    { key: 'decisions', label: t('tabs.decisions'), icon: AlertTriangle },
  ]

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Top bar */}
      <div className="shrink-0 h-14 border-b border-border/50 px-5 flex items-center justify-between bg-card/30">
        <div className="flex items-center gap-3 min-w-0">
          <h2 className="text-base font-semibold truncate">{meetingInfo?.name || 'Loading...'}</h2>
          <Badge variant={meeting.mode === 'interview' ? 'default' : 'warning'}>{meeting.mode === 'interview' ? t('meeting.interview') : t('meeting.meetingMode')}</Badge>
          {isCompleted && <Badge variant="success">{t('meeting.completed')}</Badge>}
          {isActive && <Badge variant="success" dot>{t('meeting.recording')}</Badge>}
        </div>
        <div className="flex items-center gap-2">
          {!isCompleted && (
            <>
              <Select value={meeting.mode} onChange={switchMode} options={[{ value: 'interview', label: t('meeting.interview') }, { value: 'meeting', label: t('meeting.meetingMode') }]} size="sm" className="w-[120px]" />
              {availableModels.length > 1 && (
                <Select value={activeModel} onChange={switchModel} options={availableModels.map(m => ({ value: m.id, label: `${m.label}${m.is_reasoning ? ' (deep)' : ' (fast)'}` }))} size="sm" className="w-[180px]" />
              )}
              <button onClick={toggleSuggestions} className={cn('h-9 px-3 rounded-lg text-sm font-medium flex items-center gap-1.5 transition-colors', suggestionsEnabled ? 'bg-primary/10 text-primary hover:bg-primary/15' : 'bg-muted text-muted-foreground hover:text-foreground')}>
                <Sparkles className="w-4 h-4" />
                {suggestionsEnabled ? t('meeting.aiOn') : t('meeting.aiOff')}
              </button>
              <div className="flex items-center gap-1.5 h-9 px-2.5 rounded-lg border border-border/50 bg-background text-sm">
                <span className="text-muted-foreground whitespace-nowrap text-xs">{t('meeting.sentences', 'Sentences')}</span>
                <input type="number" min={1} max={10} value={answerLength} onChange={e => switchAnswerLength(parseInt(e.target.value) || 3)} className="w-10 h-6 text-center text-sm bg-transparent border-none outline-none appearance-none [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none" />
              </div>
              {meeting.language.startsWith('ja') && (
                <Select value={jpLevel} onChange={switchJpLevel} options={[{ value: 'simple', label: t('meeting.simpleJp') }, { value: 'natural', label: t('meeting.naturalJp') }, { value: 'formal', label: t('meeting.formalJp') }]} size="sm" className="w-[125px]" />
              )}
              <button onClick={() => setShowSettings(!showSettings)} className="h-9 w-9 rounded-lg flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-accent transition-colors">
                <Settings className="w-4.5 h-4.5" />
              </button>
            </>
          )}
          {hasTranscript && (
            <div className="flex items-center">
              <button onClick={() => exportTranscript('txt')} className="h-9 px-3 rounded-lg text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-accent transition-colors flex items-center gap-1.5">
                <Download className="w-4 h-4" /> TXT
              </button>
              <button onClick={() => exportTranscript('html')} className="h-9 px-3 rounded-lg text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-accent transition-colors flex items-center gap-1.5">
                <Download className="w-4 h-4" /> HTML
              </button>
            </div>
          )}
          {!isCompleted && (
            <button onClick={toggleMeeting}
              className={cn('h-10 px-5 rounded-lg text-sm font-semibold flex items-center gap-2 transition-all duration-200 active:scale-[0.97] ml-1 shadow-sm',
                isActive ? 'bg-red-500 text-white hover:bg-red-600 hover:shadow-red-500/20 hover:shadow-md' : 'bg-gradient-to-r from-primary to-primary/90 text-primary-foreground hover:shadow-primary/20 hover:shadow-md'
              )}>
              {isActive ? <MicOff className="w-4 h-4" /> : <Mic className="w-4 h-4" />}
              {isActive ? t('meeting.stop') : t('meeting.start')}
            </button>
          )}
        </div>
      </div>

      {/* Settings panel */}
      {showSettings && !isCompleted && (
        <div className="shrink-0 border-b border-border/50 bg-card/50 px-4 py-2 animate-fade-in-down flex items-center gap-3">
          <span className="text-xs text-muted-foreground">{t('meeting.language')}:</span>
          <Select value={meeting.language} onChange={(v) => { meeting.setLanguage(v); if (isActive) send({ type: 'switch_language', language: v }) }}
            options={[{ value: 'ja-JP', label: 'Japanese' }, { value: 'en-US', label: 'English' }, { value: 'zh-CN', label: 'Chinese' }, { value: 'ko-KR', label: 'Korean' }]} size="sm" className="w-[130px]" />
        </div>
      )}

      {/* Body */}
      <div className="flex-1 flex overflow-hidden">
        {/* Transcript */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Transcript search */}
          {(isCompleted && transcript.length > 0) && (
            <div className="shrink-0 px-4 py-2 border-b border-border/30">
              <div className="relative max-w-md">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground/40" />
                <input value={transcriptSearch} onChange={(e) => setTranscriptSearch(e.target.value)} placeholder="Search transcript..."
                  className="w-full h-8 pl-8 pr-3 rounded-lg border border-border/50 bg-background text-sm placeholder:text-muted-foreground/40 focus:outline-none focus:ring-2 focus:ring-ring/20 transition-all" />
              </div>
            </div>
          )}
          <div className="flex-1 overflow-y-auto">
            <div className="max-w-4xl mx-auto px-4 py-3">
              {meeting.nowDiscussing && (
                <div className="mb-3 px-4 py-2.5 rounded-lg bg-primary/5 border border-primary/15 animate-fade-in">
                  <p className="text-xs text-primary font-semibold uppercase tracking-wider">{t('meeting.nowDiscussing')}</p>
                  <p className="text-[15px] mt-0.5">{meeting.nowDiscussing}</p>
                </div>
              )}

              {meeting.transcript.length > 0 && (
                <div className="space-y-1.5">
                  {meeting.transcript.map((line) => {
                    const isOther = line.speaker !== 'me' && line.isFinal
                    const lineSuggestion = meeting.lineSuggestions[line.id]
                    const isStreaming = meeting.activeSuggestionLineId === line.id && meeting.streamingSuggestion

                    return (
                      <div key={line.id}>
                        <div className={cn('group relative px-4 py-3 rounded-lg text-base leading-relaxed transition-all duration-200',
                          line.isFinal ? 'bg-card border border-border/40' : 'opacity-40 border border-transparent',
                          line.speaker === 'me' && line.isFinal && 'border-emerald-500/20 bg-emerald-500/5',
                          (lineSuggestion || isStreaming) && isOther && 'border-primary/30 bg-primary/[0.03]'
                        )}>
                          <div className="flex items-start justify-between gap-2">
                            <div className="flex-1 min-w-0">
                              {line.speaker && <span className={cn('text-sm font-bold mr-2', line.speaker === 'me' ? 'text-emerald-600 dark:text-emerald-400' : 'text-primary')}>{line.speaker === 'me' ? 'You' : line.speaker}</span>}
                              {line.translationVi ? (
                                <>
                                  <span>{line.translationVi}</span>
                                  {line.romaji && <p className="text-sm text-muted-foreground/50 mt-0.5">{line.romaji}</p>}
                                </>
                              ) : (
                                <>
                                  <span className="text-muted-foreground">{line.romaji || line.text}</span>
                                  {!line.isFinal && <span className="inline-block w-1.5 h-4 bg-primary/40 animate-pulse ml-0.5 rounded-sm" />}
                                </>
                              )}
                            </div>
                            {isOther && !lineSuggestion && !isStreaming && suggestionsEnabled && (
                              <button
                                onClick={() => requestSuggestion(line.id, line.text, line.romaji)}
                                disabled={meeting.activeSuggestionLineId != null}
                                className="shrink-0 opacity-0 group-hover:opacity-100 h-7 px-2.5 rounded-md text-xs font-medium bg-primary/10 text-primary hover:bg-primary/20 active:scale-95 transition-all flex items-center gap-1 disabled:opacity-30 disabled:cursor-not-allowed"
                              >
                                <Sparkles className="w-3.5 h-3.5" />
                                {t('meeting.answer')}
                              </button>
                            )}
                          </div>
                        </div>

                        {isStreaming && meeting.streamingSuggestion && (
                          <div className="ml-5 mt-1.5 mb-2 rounded-lg border border-primary/25 bg-gradient-to-r from-primary/[0.06] to-primary/[0.02] px-4 py-3.5 text-base animate-fade-in shadow-sm">
                            <div className="flex items-center justify-between mb-2">
                              <span className="text-xs text-primary font-semibold flex items-center gap-1.5">
                                <Sparkles className="w-3.5 h-3.5" /> {t('meeting.aiAnswering')}
                              </span>
                              <LiveTimer startTime={meeting.suggestionStartTime} />
                            </div>
                            {meeting.streamingSuggestion.answerRomaji && <p className="leading-relaxed">{renderWithPauses(meeting.streamingSuggestion.answerRomaji)}</p>}
                            {meeting.streamingSuggestion.answerVi && <p className="text-sm text-muted-foreground mt-1.5">{meeting.streamingSuggestion.answerVi}</p>}
                            {!meeting.streamingSuggestion.answerRomaji && !meeting.streamingSuggestion.answerVi && (
                              <div className="flex items-center gap-2 text-muted-foreground">
                                <Loader2 className="w-4 h-4 animate-spin" />
                                <span className="text-sm">{t('meeting.thinking')}</span>
                              </div>
                            )}
                          </div>
                        )}

                        {lineSuggestion && (
                          <div className="ml-5 mt-1.5 mb-2 rounded-lg border border-primary/20 bg-gradient-to-r from-primary/[0.05] to-transparent px-4 py-3.5 text-base animate-fade-in shadow-sm">
                            <div className="flex items-center justify-between mb-2">
                              <span className="text-xs text-primary/70 font-semibold flex items-center gap-1.5">
                                <Sparkles className="w-3.5 h-3.5" /> {t('meeting.suggestedAnswer')}
                              </span>
                              <div className="flex items-center gap-1.5">
                                {lineSuggestion.elapsedMs != null && (
                                  <span className="text-xs font-mono text-muted-foreground/40">{(lineSuggestion.elapsedMs / 1000).toFixed(1)}s</span>
                                )}
                                <button
                                  onClick={() => requestSuggestion(line.id, line.text, line.romaji)}
                                  disabled={meeting.activeSuggestionLineId != null}
                                  className="h-7 px-2.5 rounded text-xs font-medium bg-primary/10 text-primary hover:bg-primary/20 transition-colors disabled:opacity-30"
                                  title="Re-answer"
                                >
                                  <RefreshCw className="w-3 h-3 inline mr-0.5" />
                                  Re-answer
                                </button>
                                <button
                                  onClick={() => copySuggestion(lineSuggestion.answerRomaji || lineSuggestion.answerVi, line.id)}
                                  className="p-1.5 rounded hover:bg-muted transition-colors text-muted-foreground/50 hover:text-foreground"
                                  title="Copy"
                                >
                                  {copiedSuggestionId === line.id ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
                                </button>
                                <button
                                  onClick={() => meeting.dismissLineSuggestion(line.id)}
                                  className="p-1.5 rounded hover:bg-muted transition-colors text-muted-foreground/50 hover:text-foreground"
                                  title="Dismiss"
                                >
                                  <X className="w-3.5 h-3.5" />
                                </button>
                              </div>
                            </div>
                            {lineSuggestion.answerRomaji && <p className="leading-relaxed whitespace-pre-wrap">{renderWithPauses(lineSuggestion.answerRomaji)}</p>}
                            {lineSuggestion.answerVi && <p className="text-sm text-muted-foreground mt-1.5 whitespace-pre-wrap">{lineSuggestion.answerVi}</p>}
                          </div>
                        )}
                      </div>
                    )
                  })}
                  <div ref={transcriptEndRef} />
                </div>
              )}

              {isCompleted && filteredTranscript.length > 0 && (
                <div className="space-y-1.5">
                  {filteredTranscript.map((entry, i) => (
                    <div key={i} className="px-4 py-3 rounded-lg text-base leading-relaxed bg-card border border-border/40 animate-fade-in"
                      style={{ animationDelay: `${Math.min(i, 12) * 25}ms`, animationFillMode: 'backwards' }}>
                      <span className="text-sm font-bold text-primary mr-2">{entry.speaker}</span>
                      <span>{entry.text}</span>
                      {entry.translation_vi && <p className="text-sm text-muted-foreground/50 mt-0.5">[VI] {entry.translation_vi}</p>}
                    </div>
                  ))}
                </div>
              )}

              {meeting.transcript.length === 0 && transcript.length === 0 && (
                <div className="flex items-center justify-center h-full min-h-[300px] text-muted-foreground animate-fade-in">
                  <div className="text-center">
                    {isActive && firstAudioReceived ? (
                      <>
                        <div className="flex items-center justify-center gap-1 mb-3">
                          {[1,2,3,4,5].map(i => (
                            <div key={i} className="w-1 bg-primary/60 rounded-full animate-pulse" style={{ height: `${12 + Math.random() * 16}px`, animationDelay: `${i * 0.15}s`, animationDuration: '0.8s' }} />
                          ))}
                        </div>
                        <p className="text-base text-primary/80 font-medium">{t('meeting.audioDetected', 'Audio detected, processing...')}</p>
                      </>
                    ) : isActive ? (
                      <>
                        <Mic className="w-10 h-10 mx-auto mb-3 opacity-30 animate-pulse" />
                        <p className="text-base">{t('meeting.waitingAudio', 'Waiting for audio...')}</p>
                      </>
                    ) : (
                      <>
                        <Mic className="w-10 h-10 mx-auto mb-3 opacity-15" />
                        <p className="text-base">{isCompleted ? t('meeting.noTranscript') : t('meeting.pressStart')}</p>
                      </>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
          {/* Manual answer input at bottom of transcript area */}
          {!isCompleted && (
            <div className="shrink-0 border-t border-border/50 px-5 py-3">
              <form onSubmit={(e) => {
                e.preventDefault()
                const input = e.currentTarget.elements.namedItem('answer') as HTMLInputElement
                if (input.value.trim()) {
                  send({ type: 'manual_answer', text: input.value.trim(), ai_refine: !contextOnly, context_only: contextOnly })
                  input.value = ''
                }
              }} className="max-w-4xl mx-auto flex gap-2.5">
                <button type="button" onClick={() => setContextOnly(!contextOnly)} title={contextOnly ? 'Context-only mode (saves to notes)' : 'AI refine mode'}
                  className={cn('h-10 px-3.5 rounded-lg text-sm font-medium shrink-0 transition-colors', contextOnly ? 'bg-amber-500/15 text-amber-600 dark:text-amber-400' : 'bg-muted text-muted-foreground hover:text-foreground')}>
                  {contextOnly ? 'CTX' : 'AI'}
                </button>
                <input name="answer" placeholder={contextOnly ? t('meeting.addToContext') : t('meeting.typeAnswer')}
                  className="flex-1 h-10 bg-background border border-border rounded-lg px-3.5 text-base placeholder:text-muted-foreground/40 focus:outline-none focus:ring-2 focus:ring-ring/30 transition-all duration-200" />
                <button type="submit" className="h-10 w-10 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 active:scale-95 transition-all duration-150 flex items-center justify-center">
                  <Send className="w-4.5 h-4.5" />
                </button>
              </form>
            </div>
          )}
        </div>

        {/* Right sidebar */}
        <aside className="w-[340px] shrink-0 border-l border-border/50 bg-card/30 flex flex-col">
          <div className="flex shrink-0 border-b border-border/50 overflow-x-auto">
            {tabs.map(({ key, label, icon: Icon }) => (
              <button key={key}
                onClick={() => { setRightTab(key); if (['summary', 'actions', 'timeline', 'decisions'].includes(key) && hasTranscript) { const dm: Record<string, any> = { summary, actions, timeline, decisions }; if (!dm[key] || (Array.isArray(dm[key]) && dm[key].length === 0)) loadIntelligence(key as any) } }}
                className={cn('shrink-0 py-3 px-3 text-sm font-medium flex flex-col items-center gap-1 transition-all duration-200 border-b-2',
                  rightTab === key ? 'text-primary border-primary' : 'text-muted-foreground border-transparent hover:text-foreground'
                )}>
                <Icon className="w-4 h-4" />
                {label}
              </button>
            ))}
          </div>

          <div className="flex-1 overflow-y-auto p-3">
            {rightTab === 'summary' && <IntelPanel loading={loadingIntel === 'summary'} data={summary} loadLabel="Generate Summary" onLoad={() => loadIntelligence('summary')}
              render={(d) => (
                <div className="space-y-4 text-sm">
                  <section><Label>Overview</Label><p className="leading-relaxed">{d.overview}</p></section>
                  {d.key_topics?.length > 0 && <section><Label>Key Topics</Label><div className="flex flex-wrap gap-1.5">{d.key_topics.map((t: string, i: number) => <Badge key={i} variant="outline">{t}</Badge>)}</div></section>}
                  {d.risks?.length > 0 && <section><Label>Risks</Label><ul className="space-y-1">{d.risks.map((r: string, i: number) => <li key={i} className="flex items-start gap-2"><AlertTriangle className="w-3 h-3 text-amber-500 mt-0.5 shrink-0" />{r}</li>)}</ul></section>}
                  {d.next_steps?.length > 0 && <section><Label>Next Steps</Label><ul className="space-y-1">{d.next_steps.map((n: string, i: number) => <li key={i} className="pl-3 border-l-2 border-primary/30">{n}</li>)}</ul></section>}
                </div>
              )} />}

            {rightTab === 'actions' && <IntelPanel loading={loadingIntel === 'actions'} data={actions.length > 0 ? actions : null} loadLabel="Extract Actions" onLoad={() => loadIntelligence('actions')}
              render={(data) => (
                <div className="space-y-2">{data.map((a: any, i: number) => (
                  <div key={i} className="rounded-lg border border-border/40 p-3 text-sm bg-card">
                    <p className="font-medium">{a.task}</p>
                    <div className="flex flex-wrap gap-1.5 mt-1.5 text-xs">
                      {a.owner && <span className="bg-muted text-muted-foreground px-2 py-0.5 rounded">{a.owner}</span>}
                      {a.deadline && <span className="bg-muted text-muted-foreground px-2 py-0.5 rounded">{a.deadline}</span>}
                      {a.priority && <Badge variant={a.priority === 'high' ? 'destructive' : a.priority === 'medium' ? 'warning' : 'outline'}>{a.priority}</Badge>}
                    </div>
                  </div>
                ))}</div>
              )} />}

            {rightTab === 'timeline' && <IntelPanel loading={loadingIntel === 'timeline'} data={timeline.length > 0 ? timeline : null} loadLabel="Generate Timeline" onLoad={() => loadIntelligence('timeline')}
              render={(data) => (
                <div className="relative pl-4 border-l-2 border-border/40 space-y-3">
                  {data.map((t: any, i: number) => (
                    <div key={i} className="relative">
                      <div className="absolute -left-[21px] top-1 w-2.5 h-2.5 rounded-full bg-primary/60 border-2 border-background" />
                      <p className="text-xs font-mono text-primary">{t.time}</p>
                      <p className="text-sm font-medium mt-0.5">{t.topic}</p>
                      {t.summary && <p className="text-xs text-muted-foreground mt-0.5">{t.summary}</p>}
                    </div>
                  ))}
                </div>
              )} />}

            {rightTab === 'decisions' && <IntelPanel loading={loadingIntel === 'decisions'} data={decisions.length > 0 ? decisions : null} loadLabel="Extract Decisions" onLoad={() => loadIntelligence('decisions')}
              render={(data) => (
                <div className="space-y-2">{data.map((d: any, i: number) => (
                  <div key={i} className="rounded-lg border border-border/40 p-3 text-sm bg-card">
                    <p className="font-medium">{d.decision}</p>
                    {d.reason && <p className="text-xs text-muted-foreground mt-1">Reason: {d.reason}</p>}
                    {d.context && <p className="text-xs text-muted-foreground">Context: {d.context}</p>}
                  </div>
                ))}</div>
              )} />}

            {/* Unified Context Tab */}
            {rightTab === 'context' && (
              <div className="animate-fade-in space-y-1">
                {/* Upload feedback toast */}
                {uploadFeedback && (
                  <div className={cn('flex items-center gap-2 px-3 py-2 rounded-lg text-sm animate-fade-in mb-2',
                    uploadFeedback.type === 'success' ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20' : 'bg-red-500/10 text-red-600 dark:text-red-400 border border-red-500/20'
                  )}>
                    {uploadFeedback.type === 'success' ? <CheckCircle2 className="w-3.5 h-3.5 shrink-0" /> : <XCircle className="w-3.5 h-3.5 shrink-0" />}
                    <span className="truncate">{uploadFeedback.msg}</span>
                  </div>
                )}

                {/* Section: My Profile */}
                <ContextSection
                  icon={<User className="w-4 h-4" />}
                  title={t('context.myProfile')}
                  subtitle={t('context.myProfileSub')}
                  expanded={expandedSections.profile}
                  onToggle={() => toggleSection('profile')}
                >
                  <textarea
                    value={notes.personal}
                    onChange={(e) => setNotes(prev => ({ ...prev, personal: e.target.value }))}
                    onBlur={() => saveNote('personal', notes.personal)}
                    placeholder={t('context.profilePlaceholder')}
                    className="w-full h-[100px] rounded-lg border border-border/40 bg-background p-2.5 text-sm placeholder:text-muted-foreground/40 focus:outline-none focus:ring-2 focus:ring-ring/20 resize-none transition-all"
                  />
                  <div className="mt-2">
                    <label className={cn('w-full h-9 rounded-lg border-2 border-dashed border-border/50 flex items-center justify-center gap-2 text-xs cursor-pointer transition-colors',
                      uploading ? 'opacity-50 pointer-events-none' : 'text-muted-foreground hover:border-primary/40 hover:text-primary'
                    )}>
                      {uploading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
                      {uploading ? t('common.uploading') : t('context.uploadCv')}
                      <input type="file" accept=".pdf,.docx,.txt" className="hidden" disabled={uploading} onChange={(e) => e.target.files?.[0] && uploadDocument(e.target.files[0], 'personal')} />
                    </label>
                  </div>
                  {documents.filter(d => d.category === 'personal').map(d => (
                    <div key={d.id} className="group flex items-center gap-2 px-2.5 py-1.5 mt-1.5 rounded-lg border border-border/30 bg-card text-sm hover:border-border/50 transition-colors">
                      <FileText className="w-3.5 h-3.5 text-primary/60 shrink-0" />
                      <span className="flex-1 truncate">{d.filename}</span>
                      <button onClick={() => deleteDocument(d.id)} className="p-0.5 rounded opacity-0 group-hover:opacity-60 hover:!opacity-100 hover:text-destructive transition-all">
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </div>
                  ))}
                </ContextSection>

                {/* Section: Company / JD */}
                <ContextSection
                  icon={<Building2 className="w-4 h-4" />}
                  title={t('context.companyJd')}
                  subtitle={t('context.companyJdSub')}
                  expanded={expandedSections.company}
                  onToggle={() => toggleSection('company')}
                >
                  <textarea
                    value={notes.company}
                    onChange={(e) => setNotes(prev => ({ ...prev, company: e.target.value }))}
                    onBlur={() => saveNote('company', notes.company)}
                    placeholder={t('context.companyPlaceholder')}
                    className="w-full h-[100px] rounded-lg border border-border/40 bg-background p-2.5 text-sm placeholder:text-muted-foreground/40 focus:outline-none focus:ring-2 focus:ring-ring/20 resize-none transition-all"
                  />
                  <div className="mt-2">
                    <label className={cn('w-full h-9 rounded-lg border-2 border-dashed border-border/50 flex items-center justify-center gap-2 text-xs cursor-pointer transition-colors',
                      uploading ? 'opacity-50 pointer-events-none' : 'text-muted-foreground hover:border-primary/40 hover:text-primary'
                    )}>
                      {uploading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
                      {uploading ? t('common.uploading') : t('context.uploadJd')}
                      <input type="file" accept=".pdf,.docx,.txt" className="hidden" disabled={uploading} onChange={(e) => e.target.files?.[0] && uploadDocument(e.target.files[0], 'company')} />
                    </label>
                  </div>
                  {documents.filter(d => d.category === 'company').map(d => (
                    <div key={d.id} className="group flex items-center gap-2 px-2.5 py-1.5 mt-1.5 rounded-lg border border-border/30 bg-card text-sm hover:border-border/50 transition-colors">
                      <FileText className="w-3.5 h-3.5 text-amber-500/60 shrink-0" />
                      <span className="flex-1 truncate">{d.filename}</span>
                      <button onClick={() => deleteDocument(d.id)} className="p-0.5 rounded opacity-0 group-hover:opacity-60 hover:!opacity-100 hover:text-destructive transition-all">
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </div>
                  ))}
                </ContextSection>

                {/* Section: Vocabulary */}
                <ContextSection
                  icon={<Languages className="w-4 h-4" />}
                  title={t('context.vocabulary')}
                  subtitle={`${glossary.length} term${glossary.length !== 1 ? 's' : ''}`}
                  expanded={expandedSections.vocab}
                  onToggle={() => toggleSection('vocab')}
                >
                  <div className="flex gap-1.5 mb-2">
                    <input value={newGlossary.jp} onChange={(e) => setNewGlossary(p => ({ ...p, jp: e.target.value }))} placeholder="JP term"
                      className="flex-1 h-8 rounded-md border border-border/40 bg-background px-2.5 text-sm placeholder:text-muted-foreground/40 focus:outline-none focus:ring-2 focus:ring-ring/20" />
                    <input value={newGlossary.reading} onChange={(e) => setNewGlossary(p => ({ ...p, reading: e.target.value }))} placeholder="Reading"
                      className="flex-1 h-8 rounded-md border border-border/40 bg-background px-2.5 text-sm placeholder:text-muted-foreground/40 focus:outline-none focus:ring-2 focus:ring-ring/20" />
                    <input value={newGlossary.vi} onChange={(e) => setNewGlossary(p => ({ ...p, vi: e.target.value }))} placeholder="Meaning"
                      className="flex-1 h-8 rounded-md border border-border/40 bg-background px-2.5 text-sm placeholder:text-muted-foreground/40 focus:outline-none focus:ring-2 focus:ring-ring/20" />
                    <button onClick={addGlossaryEntry} disabled={!newGlossary.jp.trim()} className="h-8 w-8 rounded-md bg-primary text-primary-foreground flex items-center justify-center hover:bg-primary/90 active:scale-95 transition-all disabled:opacity-40">
                      <Plus className="w-3.5 h-3.5" />
                    </button>
                  </div>
                  {glossary.length === 0 ? (
                    <p className="text-xs text-muted-foreground/40 text-center py-3">{t('context.vocabPlaceholder')}</p>
                  ) : (
                    <div className="space-y-0.5 max-h-[200px] overflow-y-auto">
                      {glossary.map((g) => (
                        <div key={g.id} className="group flex items-center gap-2 px-2.5 py-1.5 rounded-md text-sm hover:bg-accent/50 transition-colors">
                          <span className="font-medium text-foreground min-w-0 truncate">{g.jp}</span>
                          <span className="text-muted-foreground/60 min-w-0 truncate">{g.reading}</span>
                          <span className="text-muted-foreground/60 min-w-0 truncate ml-auto">{g.vi}</span>
                          <button onClick={() => deleteGlossaryEntry(g.id)} className="p-0.5 rounded opacity-0 group-hover:opacity-60 hover:!opacity-100 hover:text-destructive transition-all shrink-0">
                            <Trash2 className="w-2.5 h-2.5" />
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </ContextSection>

                {/* Section: Session Notes */}
                <ContextSection
                  icon={<StickyNote className="w-4 h-4" />}
                  title={t('context.sessionNotes')}
                  subtitle={t('context.sessionNotesSub')}
                  expanded={expandedSections.notes}
                  onToggle={() => toggleSection('notes')}
                >
                  <textarea
                    value={notes.general}
                    onChange={(e) => setNotes(prev => ({ ...prev, general: e.target.value }))}
                    onBlur={() => saveNote('general', notes.general)}
                    placeholder={t('context.notesPlaceholder')}
                    className="w-full h-[100px] rounded-lg border border-border/40 bg-background p-2.5 text-sm placeholder:text-muted-foreground/40 focus:outline-none focus:ring-2 focus:ring-ring/20 resize-none transition-all"
                  />
                </ContextSection>

                <p className="text-xs text-muted-foreground/40 text-center pt-2">{t('meeting.contextFedInfo')}</p>
              </div>
            )}
          </div>

        </aside>
      </div>
    </div>
  )
}

function Label({ children }: { children: React.ReactNode }) {
  return <h4 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">{children}</h4>
}

function ContextSection({ icon, title, subtitle, expanded, onToggle, children }: {
  icon: React.ReactNode; title: string; subtitle: string; expanded: boolean; onToggle: () => void; children: React.ReactNode
}) {
  return (
    <div className="rounded-lg border border-border/40 bg-card/50 overflow-hidden transition-all">
      <button onClick={onToggle} className="w-full flex items-center gap-3 px-3.5 py-3 text-left hover:bg-accent/30 transition-colors">
        <span className="text-primary/70">{icon}</span>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium leading-tight">{title}</p>
          <p className="text-xs text-muted-foreground/60 truncate">{subtitle}</p>
        </div>
        <ChevronDown className={cn('w-4 h-4 text-muted-foreground/40 transition-transform duration-200', expanded && 'rotate-180')} />
      </button>
      {expanded && (
        <div className="px-3 pb-3 animate-fade-in">
          {children}
        </div>
      )}
    </div>
  )
}

function LiveTimer({ startTime }: { startTime: number | null }) {
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    if (startTime == null) return
    const tick = () => setElapsed(performance.now() - startTime)
    tick()
    const id = setInterval(tick, 100)
    return () => clearInterval(id)
  }, [startTime])
  if (startTime == null) return null
  return <span className="text-sm font-mono text-primary/60 tabular-nums">{(elapsed / 1000).toFixed(1)}s</span>
}

function IntelPanel({ loading, data, loadLabel, onLoad, render }: { loading: boolean; data: any; loadLabel: string; onLoad: () => void; render: (d: any) => React.ReactNode }) {
  if (loading) return <div className="flex items-center gap-2 text-muted-foreground text-sm py-6 justify-center"><Loader2 className="w-4 h-4 animate-spin" /> Loading...</div>
  if (data) return <div className="animate-fade-in">{render(data)}</div>
  return <div className="text-center py-6"><button onClick={onLoad} className="text-sm text-primary hover:underline">{loadLabel}</button></div>
}
