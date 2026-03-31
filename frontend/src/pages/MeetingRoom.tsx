import { useEffect, useRef, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  Mic, MicOff, X, Send, Settings, Monitor, MessageCircle,
  FileText, ListTodo, Clock, AlertTriangle, MoreHorizontal,
  Loader2, Download, Plus, Trash2, Search, RefreshCw,
  ChevronDown, ChevronRight, User, Building2, Languages, StickyNote,
  Upload, CheckCircle2, XCircle, Sparkles, Copy, Check,
  PanelRightClose, PanelRight, Lightbulb, BarChart3,
} from 'lucide-react'
import { cn, API_BASE as API } from '@/lib/utils'
import { Badge } from '@/components/ui/Badge'
import { Select } from '@/components/ui/Select'
import { Chip } from '@/components/ui/Chip'
import { Tooltip } from '@/components/ui/Tooltip'
import { Dropdown, DropdownItem } from '@/components/ui/Dropdown'
import { Avatar, getSpeakerBorderColor } from '@/components/ui/Avatar'
import { Tabs, TabPanel } from '@/components/ui/Tabs'
import { useWebSocket } from '@/stores/useWebSocket'
import { useMeeting, type MeetingMode } from '@/stores/useMeeting'
import { useAuth } from '@/stores/useAuth'

type RightTab = 'context' | 'strategy' | 'insights'

interface MeetingData { name: string; mode: string; status: string; transcript_count: number }

export default function MeetingRoom() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { status: wsStatus, connect, send, lastMessage } = useWebSocket()
  const { t } = useTranslation()
  const meeting = useMeeting()
  const { getHeaders } = useAuth()
  const transcriptEndRef = useRef<HTMLDivElement>(null)
  const [showToolbar, setShowToolbar] = useState(true)
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
  const [answerLength, setAnswerLength] = useState<number | 'auto'>(3)
  const [firstAudioReceived, setFirstAudioReceived] = useState(false)
  const [jpLevel, setJpLevel] = useState<'simple' | 'natural' | 'formal'>('natural')
  const [rightPanelOpen, setRightPanelOpen] = useState(true)
  const [strategyMessages, setStrategyMessages] = useState<{ role: 'user' | 'assistant'; content: string }[]>([])
  const [strategyInput, setStrategyInput] = useState('')
  const [strategySending, setStrategySending] = useState(false)
  const [insightExpanded, setInsightExpanded] = useState<Record<string, boolean>>({ summary: true })

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
    fetch(`${API}/api/settings/models`, { headers }).then(r => r.ok ? r.json() : []).then((models: { id: string; label: string }[]) => {
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
        const blob = format === 'html'
          ? new Blob([data.html], { type: 'text/html;charset=utf-8' })
          : new Blob([data.text], { type: 'text/plain;charset=utf-8' })
        const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = data.filename; a.click()
      }
    } catch {}
  }

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
    if (rightTab === 'context') { loadNotes(); loadGlossary(); loadDocuments() }
  }, [rightTab, id])

  const toggleSection = (key: string) => setExpandedSections(prev => ({ ...prev, [key]: !prev[key] }))

  const toggleSuggestions = () => {
    const next = !suggestionsEnabled
    setSuggestionsEnabled(next)
    send({ type: 'toggle_suggestions', enabled: next })
    if (!next) meeting.clearAllSuggestions()
  }

  const switchModel = (modelId: string) => { setActiveModel(modelId); send({ type: 'switch_model', model_id: modelId }) }

  const switchAnswerLength = (val: number | 'auto') => {
    if (val === 'auto') { setAnswerLength('auto'); send({ type: 'set_answer_length', length: 0 }) }
    else { const clamped = Math.max(1, Math.min(10, val)); setAnswerLength(clamped); send({ type: 'set_answer_length', length: clamped }) }
  }

  const switchJpLevel = (level: string) => { setJpLevel(level as 'simple' | 'natural' | 'formal'); send({ type: 'set_jp_level', level }) }

  const requestSuggestion = (lineId: string, text: string, romaji: string, length?: string) => {
    if (!suggestionsEnabled) return
    meeting.dismissLineSuggestion(lineId)
    send({ type: 'request_suggestion', line_id: lineId, text, romaji, ...(length ? { length } : {}) })
  }

  const [copiedSuggestionId, setCopiedSuggestionId] = useState<string | null>(null)
  const copySuggestion = (text: string, lineId: string) => {
    navigator.clipboard.writeText(text).then(() => { setCopiedSuggestionId(lineId); setTimeout(() => setCopiedSuggestionId(null), 2000) })
  }

  const renderWithPauses = (text: string) => {
    if (!text.includes(' / ')) return text
    return text.split(' / ').map((segment, i, arr) => (
      <span key={i}>{segment}{i < arr.length - 1 && <span className="inline-block w-2 mx-0.5 text-primary/30 select-none" aria-hidden>|</span>}</span>
    ))
  }

  const isActive = meeting.status === 'active'
  const isCompleted = meetingInfo?.status === 'completed'
  const hasTranscript = transcript.length > 0 || meeting.transcript.length > 0

  const toggleMeeting = () => {
    if (isActive) { send({ type: 'stop_meeting' }); meeting.setStatus('idle') }
    else if (wsStatus === 'connected') { setFirstAudioReceived(false); send({ type: 'start_meeting', meeting_id: id, language: meeting.language, mode: meeting.mode, model_id: activeModel }); meeting.setStatus('active'); meeting.setMeetingId(id || null) }
  }

  const sendStrategyMessage = async () => {
    const msg = strategyInput.trim()
    if (!msg || strategySending) return
    const newMsgs = [...strategyMessages, { role: 'user' as const, content: msg }]
    setStrategyMessages(newMsgs)
    setStrategyInput('')
    setStrategySending(true)
    try {
      const recentTranscript = meeting.transcript.slice(-10).map(l => `${l.speaker}: ${l.translationVi || l.text}`).join('\n')
      const r = await fetch(`${API}/api/meetings/${id}/strategy-chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...headers },
        body: JSON.stringify({ message: msg, context: { transcript: recentTranscript, notes: notes.personal, company: notes.company }, history: newMsgs.slice(-10) }),
      })
      if (r.ok) { const data = await r.json(); setStrategyMessages(prev => [...prev, { role: 'assistant', content: data.reply }]) }
      else setStrategyMessages(prev => [...prev, { role: 'assistant', content: 'Failed to get response.' }])
    } catch { setStrategyMessages(prev => [...prev, { role: 'assistant', content: 'Network error.' }]) }
    finally { setStrategySending(false) }
  }

  const switchMode = (m: string) => {
    meeting.setMode(m as MeetingMode)
    if (id) fetch(`${API}/api/meetings/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json', ...headers }, body: JSON.stringify({ mode: m }) }).catch(() => {})
  }

  const filteredTranscript = transcriptSearch
    ? transcript.filter(e => e.text.toLowerCase().includes(transcriptSearch.toLowerCase()) || e.speaker.toLowerCase().includes(transcriptSearch.toLowerCase()) || (e.translation_vi || '').toLowerCase().includes(transcriptSearch.toLowerCase()))
    : transcript

  const sidebarTabs = [
    { key: 'context', label: t('tabs.context'), icon: StickyNote },
    { key: 'strategy', label: t('tabs.strategy', 'Strategy'), icon: MessageCircle },
    { key: 'insights', label: t('tabs.insights', 'Insights'), icon: Lightbulb },
  ]

  const activeModelLabel = availableModels.find(m => m.id === activeModel)?.label || activeModel
  const jpLevelLabels: Record<string, string> = { simple: t('meeting.simpleJp'), natural: t('meeting.naturalJp'), formal: t('meeting.formalJp') }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* ═══ HEADER — Tier 1: Identity + Primary Action ═══ */}
      <div className="shrink-0 h-14 border-b border-border/50 px-4 md:px-6 flex items-center justify-between bg-card/40">
        <div className="flex items-center gap-3 min-w-0">
          <h2 className="text-base font-semibold truncate max-w-[200px] md:max-w-none">{meetingInfo?.name || 'Loading...'}</h2>
          <div className="hidden sm:flex items-center gap-1.5">
            <Badge variant={meeting.mode === 'interview' ? 'default' : 'warning'}>{meeting.mode === 'interview' ? t('meeting.interview') : t('meeting.meetingMode')}</Badge>
            {isCompleted && <Badge variant="success">{t('meeting.completed')}</Badge>}
            {isActive && <Badge variant="success" dot>{t('meeting.recording')}</Badge>}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {hasTranscript && (
            <Dropdown
              trigger={
                <button className="h-9 px-3 rounded-xl text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-accent transition-colors flex items-center gap-1.5">
                  <Download className="w-4 h-4" />
                  <span className="hidden sm:inline">{t('meeting.export', 'Export')}</span>
                </button>
              }
              align="right"
            >
              <DropdownItem onClick={() => exportTranscript('txt')}>
                <FileText className="w-4 h-4" /> Export TXT
              </DropdownItem>
              <DropdownItem onClick={() => exportTranscript('html')}>
                <FileText className="w-4 h-4" /> Export HTML
              </DropdownItem>
            </Dropdown>
          )}

          {!isCompleted && (
            <button onClick={toggleMeeting}
              className={cn('h-10 px-5 rounded-xl text-sm font-semibold flex items-center gap-2 transition-all duration-200 active:scale-[0.97] shadow-sm',
                isActive
                  ? 'bg-red-500 text-white hover:bg-red-600 shadow-red-500/10'
                  : 'bg-gradient-to-r from-primary to-primary/90 text-primary-foreground shadow-primary/10 hover:shadow-md'
              )}>
              {isActive ? <MicOff className="w-4 h-4" /> : <Mic className="w-4 h-4" />}
              {isActive ? t('meeting.stop') : t('meeting.start')}
            </button>
          )}

          <button onClick={() => setRightPanelOpen(!rightPanelOpen)} className="h-9 w-9 rounded-xl flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-accent transition-colors">
            {rightPanelOpen ? <PanelRightClose className="w-4 h-4" /> : <PanelRight className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* ═══ HEADER — Tier 2: AI Toolbar (chip groups) ═══ */}
      {!isCompleted && (
        <div className={cn('shrink-0 border-b border-border/30 bg-muted/20 transition-all duration-200 overflow-hidden', showToolbar ? 'py-2 px-4 md:px-6' : 'h-0 py-0')}>
          <div className="flex flex-wrap items-center gap-2">
            <Select value={meeting.mode} onChange={switchMode} options={[{ value: 'interview', label: t('meeting.interview') }, { value: 'meeting', label: t('meeting.meetingMode') }]} size="sm" className="w-[110px]" />

            <div className="w-px h-5 bg-border/50 hidden sm:block" />

            <Chip active={suggestionsEnabled} onClick={toggleSuggestions} variant="primary" icon={<Sparkles className="w-3.5 h-3.5" />}>
              {suggestionsEnabled ? t('meeting.aiOn') : t('meeting.aiOff')}
            </Chip>

            {availableModels.length > 1 && (
              <Dropdown
                trigger={<Chip icon={<BarChart3 className="w-3.5 h-3.5" />}>{activeModelLabel}</Chip>}
              >
                {availableModels.map(m => (
                  <DropdownItem key={m.id} active={m.id === activeModel} onClick={() => switchModel(m.id)}>
                    {m.label}{m.is_reasoning ? ' (deep)' : ' (fast)'}
                  </DropdownItem>
                ))}
              </Dropdown>
            )}

            <Chip
              icon={<span className="text-[10px] font-bold">#</span>}
              onClick={() => switchAnswerLength(answerLength === 'auto' ? 3 : 'auto')}
              active={answerLength === 'auto'}
            >
              {answerLength === 'auto' ? 'Auto' : (
                <>
                  <input type="number" min={1} max={10} value={answerLength as number}
                    onClick={e => e.stopPropagation()}
                    onChange={e => switchAnswerLength(parseInt(e.target.value) || 3)}
                    className="w-6 h-4 text-center text-xs bg-transparent border-none outline-none appearance-none [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
                  /> {t('meeting.sentences', 'sent.')}
                </>
              )}
            </Chip>

            {meeting.language.startsWith('ja') && (
              <Dropdown trigger={<Chip icon={<Languages className="w-3.5 h-3.5" />}>{jpLevelLabels[jpLevel]}</Chip>}>
                {(['simple', 'natural', 'formal'] as const).map(lvl => (
                  <DropdownItem key={lvl} active={jpLevel === lvl} onClick={() => switchJpLevel(lvl)}>{jpLevelLabels[lvl]}</DropdownItem>
                ))}
              </Dropdown>
            )}

            <div className="flex-1" />

            {typeof window !== 'undefined' && (window as any).electronAPI && (
              <Tooltip content="Toggle Overlay">
                <button onClick={() => (window as any).electronAPI.toggleOverlay()} className="h-8 w-8 rounded-lg flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-accent transition-colors">
                  <Monitor className="w-4 h-4" />
                </button>
              </Tooltip>
            )}

            <Tooltip content={t('meeting.settings', 'Settings')}>
              <Dropdown
                trigger={
                  <button className="h-8 w-8 rounded-lg flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-accent transition-colors">
                    <Settings className="w-4 h-4" />
                  </button>
                }
                align="right"
              >
                <div className="px-3 py-2">
                  <p className="text-xs font-medium text-muted-foreground mb-2">{t('meeting.language')}</p>
                  <Select value={meeting.language} onChange={(v) => { meeting.setLanguage(v); if (isActive) send({ type: 'switch_language', language: v }) }}
                    options={[{ value: 'ja-JP', label: 'Japanese' }, { value: 'en-US', label: 'English' }, { value: 'zh-CN', label: 'Chinese' }, { value: 'ko-KR', label: 'Korean' }]} size="sm" />
                </div>
              </Dropdown>
            </Tooltip>

            <Tooltip content={showToolbar ? t('meeting.hideToolbar', 'Collapse toolbar') : t('meeting.showToolbar', 'Show toolbar')}>
              <button onClick={() => setShowToolbar(!showToolbar)} className="h-8 w-8 rounded-lg flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-accent transition-colors">
                <ChevronDown className={cn('w-4 h-4 transition-transform', !showToolbar && 'rotate-180')} />
              </button>
            </Tooltip>
          </div>
        </div>
      )}

      {/* Collapsed toolbar toggle */}
      {!isCompleted && !showToolbar && (
        <button onClick={() => setShowToolbar(true)} className="shrink-0 h-6 border-b border-border/30 bg-muted/10 flex items-center justify-center text-muted-foreground/50 hover:text-muted-foreground hover:bg-muted/20 transition-colors">
          <ChevronDown className="w-3.5 h-3.5" />
        </button>
      )}

      {/* ═══ BODY ═══ */}
      <div className="flex-1 flex overflow-hidden">
        {/* ── Transcript Column ── */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {(isCompleted && transcript.length > 0) && (
            <div className="shrink-0 px-4 py-2 border-b border-border/30">
              <div className="relative content-md mx-auto">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground/40" />
                <input value={transcriptSearch} onChange={(e) => setTranscriptSearch(e.target.value)} placeholder={t('meeting.searchTranscript', 'Search transcript...')}
                  className="w-full h-8 pl-8 pr-3 rounded-xl border border-border/50 bg-background text-sm placeholder:text-muted-foreground/40 focus:outline-none focus:ring-2 focus:ring-ring/20 transition-all" />
              </div>
            </div>
          )}

          <div className="flex-1 overflow-y-auto">
            <div className="content-lg mx-auto px-4 py-4">
              {meeting.nowDiscussing && (
                <div className="mb-4 px-4 py-3 rounded-xl bg-primary/5 border border-primary/15 animate-fade-in">
                  <p className="text-[10px] text-primary font-bold uppercase tracking-widest">{t('meeting.nowDiscussing')}</p>
                  <p className="text-sm mt-0.5 font-medium">{meeting.nowDiscussing}</p>
                </div>
              )}

              {/* ── Live Transcript ── */}
              {meeting.transcript.length > 0 && (
                <div className="space-y-1">
                  {meeting.transcript.map((line) => {
                    const isMe = line.speaker === 'me'
                    const isOther = !isMe && line.isFinal
                    const lineSuggestion = meeting.lineSuggestions[line.id]
                    const isStreaming = meeting.activeSuggestionLineId === line.id && meeting.streamingSuggestion

                    return (
                      <div key={line.id} className="animate-fade-in">
                        {/* Transcript line */}
                        <div className={cn(
                          'group relative flex gap-3 px-3 py-2.5 rounded-xl transition-all duration-200',
                          line.isFinal ? 'hover:bg-card' : 'opacity-50',
                          isMe && line.isFinal && 'border-l-2 border-emerald-500/40',
                          isOther && line.isFinal && 'border-l-2',
                          isOther && line.isFinal && getSpeakerBorderColor(line.speaker),
                          (lineSuggestion || isStreaming) && isOther && 'bg-primary/[0.02]'
                        )}>
                          {line.isFinal && (
                            <Avatar name={line.speaker || '?'} size="sm" isMe={isMe} className="mt-0.5" />
                          )}
                          <div className="flex-1 min-w-0">
                            {line.speaker && line.isFinal && (
                              <span className={cn('text-xs font-bold', isMe ? 'text-emerald-600 dark:text-emerald-400' : 'text-primary/70')}>
                                {isMe ? 'You' : line.speaker}
                              </span>
                            )}
                            {line.translationVi ? (
                              <div>
                                <p className="text-sm leading-relaxed">{line.translationVi}</p>
                                {line.romaji && <p className="text-xs text-muted-foreground/40 mt-0.5">{line.romaji}</p>}
                              </div>
                            ) : (
                              <div className="flex items-center">
                                <span className={cn('text-sm', !line.isFinal && 'text-muted-foreground')}>{line.romaji || line.text}</span>
                                {!line.isFinal && <span className="inline-block w-1 h-4 bg-primary/40 animate-pulse ml-0.5 rounded-full" />}
                              </div>
                            )}
                          </div>

                          {isOther && !lineSuggestion && !isStreaming && suggestionsEnabled && (
                            <Tooltip content={t('meeting.answer')}>
                              <button
                                onClick={() => requestSuggestion(line.id, line.text, line.romaji)}
                                disabled={meeting.activeSuggestionLineId != null}
                                className="shrink-0 opacity-0 group-hover:opacity-100 h-7 w-7 rounded-lg bg-primary/10 text-primary hover:bg-primary/20 active:scale-95 transition-all flex items-center justify-center disabled:opacity-30 disabled:cursor-not-allowed"
                              >
                                <Sparkles className="w-3.5 h-3.5" />
                              </button>
                            </Tooltip>
                          )}
                        </div>

                        {/* Streaming suggestion */}
                        {isStreaming && meeting.streamingSuggestion && (
                          <div className="ml-10 mt-1 mb-3 rounded-xl border border-primary/20 bg-gradient-to-br from-primary/[0.04] to-transparent px-4 py-3 animate-fade-in">
                            <div className="flex items-center justify-between mb-2">
                              <span className="text-[10px] text-primary font-bold uppercase tracking-widest flex items-center gap-1.5">
                                <Sparkles className="w-3 h-3" /> {t('meeting.aiAnswering')}
                              </span>
                              <LiveTimer startTime={meeting.suggestionStartTime} />
                            </div>
                            {meeting.streamingSuggestion.answerRomaji && <p className="text-sm leading-relaxed">{renderWithPauses(meeting.streamingSuggestion.answerRomaji)}</p>}
                            {meeting.streamingSuggestion.answerVi && <p className="text-xs text-muted-foreground mt-1.5">{meeting.streamingSuggestion.answerVi}</p>}
                            {!meeting.streamingSuggestion.answerRomaji && !meeting.streamingSuggestion.answerVi && (
                              <div className="flex items-center gap-2 text-muted-foreground">
                                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                <span className="text-xs">{t('meeting.thinking')}</span>
                              </div>
                            )}
                          </div>
                        )}

                        {/* Completed suggestion */}
                        {lineSuggestion && (
                          <div className="group/sg ml-10 mt-1 mb-3 rounded-xl border border-primary/15 bg-gradient-to-br from-primary/[0.03] to-transparent px-4 py-3 animate-fade-in relative">
                            <div className="flex items-center gap-2 mb-2">
                              <Sparkles className="w-3 h-3 text-primary/50" />
                              <span className="text-[10px] text-primary/60 font-bold uppercase tracking-widest flex-1">{t('meeting.suggestedAnswer')}</span>
                              {lineSuggestion.elapsedMs != null && (
                                <span className="text-[10px] font-mono text-muted-foreground/30">{(lineSuggestion.elapsedMs / 1000).toFixed(1)}s</span>
                              )}
                            </div>

                            {lineSuggestion.answerRomaji && <p className="text-sm leading-relaxed whitespace-pre-wrap">{renderWithPauses(lineSuggestion.answerRomaji)}</p>}
                            {lineSuggestion.answerVi && <p className="text-xs text-muted-foreground mt-1.5 whitespace-pre-wrap">{lineSuggestion.answerVi}</p>}

                            {/* Hover action bar */}
                            <div className="opacity-0 group-hover/sg:opacity-100 transition-opacity absolute bottom-2 right-2 flex items-center gap-0.5 bg-card/90 backdrop-blur-sm border border-border/50 rounded-lg px-1 py-0.5 shadow-sm">
                              <Tooltip content="Re-answer">
                                <button onClick={() => requestSuggestion(line.id, line.text, line.romaji)} disabled={meeting.activeSuggestionLineId != null}
                                  className="h-7 w-7 rounded-md flex items-center justify-center text-muted-foreground hover:text-primary hover:bg-primary/10 transition-colors disabled:opacity-30">
                                  <RefreshCw className="w-3.5 h-3.5" />
                                </button>
                              </Tooltip>
                              <Tooltip content="Elaborate">
                                <button onClick={() => send({ type: 'elaborate', previous_answer: lineSuggestion.answerRomaji || lineSuggestion.answerVi, original_question: line.text })} disabled={meeting.activeSuggestionLineId != null}
                                  className="h-7 w-7 rounded-md flex items-center justify-center text-muted-foreground hover:text-amber-600 hover:bg-amber-500/10 transition-colors disabled:opacity-30">
                                  <ChevronDown className="w-3.5 h-3.5" />
                                </button>
                              </Tooltip>
                              <Tooltip content="Copy">
                                <button onClick={() => copySuggestion(lineSuggestion.answerRomaji || lineSuggestion.answerVi, line.id)}
                                  className="h-7 w-7 rounded-md flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted transition-colors">
                                  {copiedSuggestionId === line.id ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
                                </button>
                              </Tooltip>
                              <Tooltip content="Dismiss">
                                <button onClick={() => meeting.dismissLineSuggestion(line.id)}
                                  className="h-7 w-7 rounded-md flex items-center justify-center text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors">
                                  <X className="w-3.5 h-3.5" />
                                </button>
                              </Tooltip>
                            </div>
                          </div>
                        )}
                      </div>
                    )
                  })}
                  <div ref={transcriptEndRef} />
                </div>
              )}

              {/* ── Completed transcript ── */}
              {isCompleted && filteredTranscript.length > 0 && (
                <div className="space-y-1">
                  {filteredTranscript.map((entry, i) => (
                    <div key={i} className="flex gap-3 px-3 py-2.5 rounded-xl hover:bg-card transition-colors animate-fade-in"
                      style={{ animationDelay: `${Math.min(i, 12) * 25}ms`, animationFillMode: 'backwards' }}>
                      <Avatar name={entry.speaker || '?'} size="sm" className="mt-0.5" />
                      <div className="flex-1 min-w-0">
                        <span className="text-xs font-bold text-primary/70">{entry.speaker}</span>
                        <p className="text-sm leading-relaxed">{entry.text}</p>
                        {entry.translation_vi && <p className="text-xs text-muted-foreground/40 mt-0.5">[VI] {entry.translation_vi}</p>}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* ── Empty state ── */}
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
                        <p className="text-sm text-primary/80 font-medium">{t('meeting.audioDetected', 'Audio detected, processing...')}</p>
                      </>
                    ) : isActive ? (
                      <>
                        <Mic className="w-10 h-10 mx-auto mb-3 opacity-30 animate-pulse" />
                        <p className="text-sm">{t('meeting.waitingAudio', 'Waiting for audio...')}</p>
                      </>
                    ) : (
                      <>
                        <Mic className="w-10 h-10 mx-auto mb-3 opacity-15" />
                        <p className="text-sm">{isCompleted ? t('meeting.noTranscript') : t('meeting.pressStart')}</p>
                      </>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* ═══ MANUAL INPUT — Segmented control ═══ */}
          {!isCompleted && (
            <div className="shrink-0 border-t border-border/40 bg-card/20 px-4 py-3">
              <form onSubmit={(e) => {
                e.preventDefault()
                const input = e.currentTarget.elements.namedItem('answer') as HTMLInputElement
                if (input.value.trim()) {
                  send({ type: 'manual_answer', text: input.value.trim(), ai_refine: !contextOnly, context_only: contextOnly })
                  input.value = ''
                }
              }} className="content-lg mx-auto">
                <div className="flex gap-2 items-end">
                  <div className="flex-1 rounded-xl border border-border/50 bg-background overflow-hidden focus-within:ring-2 focus-within:ring-ring/20 transition-all">
                    <div className="flex items-center gap-0.5 px-2 pt-2">
                      <button type="button" onClick={() => setContextOnly(false)}
                        className={cn('px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors', !contextOnly ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:text-foreground')}>
                        <Sparkles className="w-3 h-3 inline mr-1" />{t('meeting.aiMode', 'AI Answer')}
                      </button>
                      <button type="button" onClick={() => setContextOnly(true)}
                        className={cn('px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors', contextOnly ? 'bg-amber-500/10 text-amber-600 dark:text-amber-400' : 'text-muted-foreground hover:text-foreground')}>
                        <StickyNote className="w-3 h-3 inline mr-1" />{t('meeting.ctxMode', 'Context Note')}
                      </button>
                    </div>
                    <input name="answer" placeholder={contextOnly ? t('meeting.addToContext') : t('meeting.typeAnswer')}
                      className="w-full h-10 px-3 text-sm bg-transparent border-none outline-none placeholder:text-muted-foreground/40" />
                  </div>
                  <button type="submit" className="h-10 w-10 shrink-0 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 active:scale-95 transition-all flex items-center justify-center shadow-sm">
                    <Send className="w-4 h-4" />
                  </button>
                </div>
              </form>
            </div>
          )}
        </div>

        {/* ═══ RIGHT SIDEBAR ═══ */}
        <aside className={cn('w-[300px] md:w-[340px] shrink-0 border-l border-border/40 bg-card/20 flex flex-col transition-all duration-200', !rightPanelOpen && 'hidden')}>
          <div className="shrink-0 p-2">
            <Tabs tabs={sidebarTabs} activeKey={rightTab} onChange={(k) => setRightTab(k as RightTab)} variant="pill" />
          </div>

          <div className="flex-1 overflow-y-auto p-3">
            {/* ── Insights Tab (consolidated) ── */}
            <TabPanel active={rightTab === 'insights'}>
              <div className="space-y-1.5">
                <InsightSection
                  title={t('tabs.summary', 'Summary')} icon={<FileText className="w-4 h-4" />}
                  expanded={!!insightExpanded.summary} onToggle={() => setInsightExpanded(p => ({ ...p, summary: !p.summary }))}
                  loading={loadingIntel === 'summary'} data={summary} onLoad={() => loadIntelligence('summary')} hasTranscript={hasTranscript}
                  render={(d) => (
                    <div className="space-y-3 text-sm">
                      <p className="leading-relaxed">{d.overview}</p>
                      {d.key_topics?.length > 0 && <div className="flex flex-wrap gap-1.5">{d.key_topics.map((t: string, i: number) => <Badge key={i} variant="outline">{t}</Badge>)}</div>}
                      {d.risks?.length > 0 && <ul className="space-y-1">{d.risks.map((r: string, i: number) => <li key={i} className="flex items-start gap-2 text-xs"><AlertTriangle className="w-3 h-3 text-amber-500 mt-0.5 shrink-0" />{r}</li>)}</ul>}
                      {d.next_steps?.length > 0 && <ul className="space-y-1">{d.next_steps.map((n: string, i: number) => <li key={i} className="text-xs pl-3 border-l-2 border-primary/30">{n}</li>)}</ul>}
                    </div>
                  )}
                />
                <InsightSection
                  title={t('tabs.actions', 'Actions')} icon={<ListTodo className="w-4 h-4" />}
                  expanded={!!insightExpanded.actions} onToggle={() => setInsightExpanded(p => ({ ...p, actions: !p.actions }))}
                  loading={loadingIntel === 'actions'} data={actions.length > 0 ? actions : null} onLoad={() => loadIntelligence('actions')} hasTranscript={hasTranscript}
                  render={(data) => (
                    <div className="space-y-2">{data.map((a: any, i: number) => (
                      <div key={i} className="rounded-lg border border-border/30 p-2.5 text-xs bg-card/50">
                        <p className="font-medium text-sm">{a.task}</p>
                        <div className="flex flex-wrap gap-1 mt-1.5">
                          {a.owner && <span className="bg-muted text-muted-foreground px-2 py-0.5 rounded">{a.owner}</span>}
                          {a.deadline && <span className="bg-muted text-muted-foreground px-2 py-0.5 rounded">{a.deadline}</span>}
                          {a.priority && <Badge variant={a.priority === 'high' ? 'destructive' : a.priority === 'medium' ? 'warning' : 'outline'}>{a.priority}</Badge>}
                        </div>
                      </div>
                    ))}</div>
                  )}
                />
                <InsightSection
                  title={t('tabs.timeline', 'Timeline')} icon={<Clock className="w-4 h-4" />}
                  expanded={!!insightExpanded.timeline} onToggle={() => setInsightExpanded(p => ({ ...p, timeline: !p.timeline }))}
                  loading={loadingIntel === 'timeline'} data={timeline.length > 0 ? timeline : null} onLoad={() => loadIntelligence('timeline')} hasTranscript={hasTranscript}
                  render={(data) => (
                    <div className="relative pl-4 border-l-2 border-border/30 space-y-3">
                      {data.map((t: any, i: number) => (
                        <div key={i} className="relative">
                          <div className="absolute -left-[21px] top-1 w-2.5 h-2.5 rounded-full bg-primary/60 border-2 border-background" />
                          <p className="text-[10px] font-mono text-primary">{t.time}</p>
                          <p className="text-xs font-medium mt-0.5">{t.topic}</p>
                          {t.summary && <p className="text-[11px] text-muted-foreground mt-0.5">{t.summary}</p>}
                        </div>
                      ))}
                    </div>
                  )}
                />
                <InsightSection
                  title={t('tabs.decisions', 'Decisions')} icon={<AlertTriangle className="w-4 h-4" />}
                  expanded={!!insightExpanded.decisions} onToggle={() => setInsightExpanded(p => ({ ...p, decisions: !p.decisions }))}
                  loading={loadingIntel === 'decisions'} data={decisions.length > 0 ? decisions : null} onLoad={() => loadIntelligence('decisions')} hasTranscript={hasTranscript}
                  render={(data) => (
                    <div className="space-y-2">{data.map((d: any, i: number) => (
                      <div key={i} className="rounded-lg border border-border/30 p-2.5 text-xs bg-card/50">
                        <p className="font-medium text-sm">{d.decision}</p>
                        {d.reason && <p className="text-muted-foreground mt-1">Reason: {d.reason}</p>}
                        {d.context && <p className="text-muted-foreground">Context: {d.context}</p>}
                      </div>
                    ))}</div>
                  )}
                />
              </div>
            </TabPanel>

            {/* ── Strategy Chat Tab ── */}
            <TabPanel active={rightTab === 'strategy'}>
              <div className="flex flex-col h-full">
                <div className="flex-1 overflow-y-auto space-y-2 mb-2">
                  {strategyMessages.length === 0 && (
                    <div className="text-center py-8 text-muted-foreground/50">
                      <MessageCircle className="w-8 h-8 mx-auto mb-2 opacity-20" />
                      <p className="text-xs max-w-[200px] mx-auto">{t('strategy.placeholder', 'Ask the AI for strategy advice based on your meeting context')}</p>
                    </div>
                  )}
                  {strategyMessages.map((m, i) => (
                    <div key={i} className={cn('rounded-xl px-3 py-2.5 text-sm animate-fade-in', m.role === 'user' ? 'bg-primary/10 ml-8' : 'bg-muted/50 mr-6')}>
                      <p className="whitespace-pre-wrap leading-relaxed text-xs">{m.content}</p>
                    </div>
                  ))}
                  {strategySending && (
                    <div className="flex items-center gap-2 px-3 py-2 text-muted-foreground">
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      <span className="text-xs">{t('common.thinking', 'Thinking...')}</span>
                    </div>
                  )}
                </div>
                <form onSubmit={(e) => { e.preventDefault(); sendStrategyMessage() }} className="flex gap-1.5 shrink-0">
                  <input value={strategyInput} onChange={(e) => setStrategyInput(e.target.value)} placeholder={t('strategy.inputPlaceholder', 'Ask strategy question...')} disabled={strategySending}
                    className="flex-1 h-9 rounded-xl border border-border/50 bg-background px-3 text-xs placeholder:text-muted-foreground/40 focus:outline-none focus:ring-2 focus:ring-ring/20 disabled:opacity-50" />
                  <button type="submit" disabled={strategySending || !strategyInput.trim()} className="h-9 w-9 shrink-0 rounded-xl bg-primary text-primary-foreground flex items-center justify-center hover:bg-primary/90 active:scale-95 transition-all disabled:opacity-40">
                    <Send className="w-3.5 h-3.5" />
                  </button>
                </form>
              </div>
            </TabPanel>

            {/* ── Context Tab ── */}
            <TabPanel active={rightTab === 'context'}>
              <div className="space-y-1.5">
                {uploadFeedback && (
                  <div className={cn('flex items-center gap-2 px-3 py-2 rounded-xl text-xs animate-fade-in mb-2',
                    uploadFeedback.type === 'success' ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20' : 'bg-red-500/10 text-red-600 dark:text-red-400 border border-red-500/20'
                  )}>
                    {uploadFeedback.type === 'success' ? <CheckCircle2 className="w-3.5 h-3.5 shrink-0" /> : <XCircle className="w-3.5 h-3.5 shrink-0" />}
                    <span className="truncate">{uploadFeedback.msg}</span>
                  </div>
                )}

                <ContextSection icon={<User className="w-4 h-4" />} title={t('context.myProfile')} subtitle={t('context.myProfileSub')}
                  expanded={expandedSections.profile} onToggle={() => toggleSection('profile')}>
                  <textarea value={notes.personal} onChange={(e) => setNotes(prev => ({ ...prev, personal: e.target.value }))} onBlur={() => saveNote('personal', notes.personal)}
                    placeholder={t('context.profilePlaceholder')}
                    className="w-full h-[90px] rounded-lg border border-border/30 bg-background p-2.5 text-xs placeholder:text-muted-foreground/40 focus:outline-none focus:ring-2 focus:ring-ring/20 resize-none" />
                  <label className={cn('mt-2 w-full h-8 rounded-lg border-2 border-dashed border-border/40 flex items-center justify-center gap-2 text-[11px] cursor-pointer transition-colors',
                    uploading ? 'opacity-50 pointer-events-none' : 'text-muted-foreground hover:border-primary/40 hover:text-primary')}>
                    {uploading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Upload className="w-3 h-3" />}
                    {uploading ? t('common.uploading') : t('context.uploadCv')}
                    <input type="file" accept=".pdf,.docx,.txt" className="hidden" disabled={uploading} onChange={(e) => e.target.files?.[0] && uploadDocument(e.target.files[0], 'personal')} />
                  </label>
                  {documents.filter(d => d.category === 'personal').map(d => (
                    <div key={d.id} className="group flex items-center gap-2 px-2.5 py-1.5 mt-1.5 rounded-lg border border-border/20 bg-card/50 text-xs hover:border-border/40 transition-colors">
                      <FileText className="w-3 h-3 text-primary/60 shrink-0" />
                      <span className="flex-1 truncate">{d.filename}</span>
                      <button onClick={() => deleteDocument(d.id)} className="p-0.5 rounded opacity-0 group-hover:opacity-60 hover:!opacity-100 hover:text-destructive transition-all"><Trash2 className="w-2.5 h-2.5" /></button>
                    </div>
                  ))}
                </ContextSection>

                <ContextSection icon={<Building2 className="w-4 h-4" />} title={t('context.companyJd')} subtitle={t('context.companyJdSub')}
                  expanded={expandedSections.company} onToggle={() => toggleSection('company')}>
                  <textarea value={notes.company} onChange={(e) => setNotes(prev => ({ ...prev, company: e.target.value }))} onBlur={() => saveNote('company', notes.company)}
                    placeholder={t('context.companyPlaceholder')}
                    className="w-full h-[90px] rounded-lg border border-border/30 bg-background p-2.5 text-xs placeholder:text-muted-foreground/40 focus:outline-none focus:ring-2 focus:ring-ring/20 resize-none" />
                  <label className={cn('mt-2 w-full h-8 rounded-lg border-2 border-dashed border-border/40 flex items-center justify-center gap-2 text-[11px] cursor-pointer transition-colors',
                    uploading ? 'opacity-50 pointer-events-none' : 'text-muted-foreground hover:border-primary/40 hover:text-primary')}>
                    {uploading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Upload className="w-3 h-3" />}
                    {uploading ? t('common.uploading') : t('context.uploadJd')}
                    <input type="file" accept=".pdf,.docx,.txt" className="hidden" disabled={uploading} onChange={(e) => e.target.files?.[0] && uploadDocument(e.target.files[0], 'company')} />
                  </label>
                  {documents.filter(d => d.category === 'company').map(d => (
                    <div key={d.id} className="group flex items-center gap-2 px-2.5 py-1.5 mt-1.5 rounded-lg border border-border/20 bg-card/50 text-xs hover:border-border/40 transition-colors">
                      <FileText className="w-3 h-3 text-amber-500/60 shrink-0" />
                      <span className="flex-1 truncate">{d.filename}</span>
                      <button onClick={() => deleteDocument(d.id)} className="p-0.5 rounded opacity-0 group-hover:opacity-60 hover:!opacity-100 hover:text-destructive transition-all"><Trash2 className="w-2.5 h-2.5" /></button>
                    </div>
                  ))}
                </ContextSection>

                <ContextSection icon={<Languages className="w-4 h-4" />} title={t('context.vocabulary')} subtitle={`${glossary.length} term${glossary.length !== 1 ? 's' : ''}`}
                  expanded={expandedSections.vocab} onToggle={() => toggleSection('vocab')}>
                  <div className="flex gap-1 mb-2">
                    <input value={newGlossary.jp} onChange={(e) => setNewGlossary(p => ({ ...p, jp: e.target.value }))} placeholder="JP"
                      className="flex-1 min-w-0 h-7 rounded-md border border-border/30 bg-background px-2 text-xs placeholder:text-muted-foreground/40 focus:outline-none focus:ring-1 focus:ring-ring/20" />
                    <input value={newGlossary.reading} onChange={(e) => setNewGlossary(p => ({ ...p, reading: e.target.value }))} placeholder="Reading"
                      className="flex-1 min-w-0 h-7 rounded-md border border-border/30 bg-background px-2 text-xs placeholder:text-muted-foreground/40 focus:outline-none focus:ring-1 focus:ring-ring/20" />
                    <input value={newGlossary.vi} onChange={(e) => setNewGlossary(p => ({ ...p, vi: e.target.value }))} placeholder="Meaning"
                      className="flex-1 min-w-0 h-7 rounded-md border border-border/30 bg-background px-2 text-xs placeholder:text-muted-foreground/40 focus:outline-none focus:ring-1 focus:ring-ring/20" />
                    <button onClick={addGlossaryEntry} disabled={!newGlossary.jp.trim()} className="h-7 w-7 shrink-0 rounded-md bg-primary text-primary-foreground flex items-center justify-center hover:bg-primary/90 active:scale-95 transition-all disabled:opacity-40">
                      <Plus className="w-3 h-3" />
                    </button>
                  </div>
                  {glossary.length === 0 ? (
                    <p className="text-[11px] text-muted-foreground/40 text-center py-3">{t('context.vocabPlaceholder')}</p>
                  ) : (
                    <div className="space-y-0.5 max-h-[180px] overflow-y-auto">
                      {glossary.map((g) => (
                        <div key={g.id} className="group flex items-center gap-2 px-2 py-1 rounded-md text-xs hover:bg-accent/30 transition-colors">
                          <span className="font-medium truncate">{g.jp}</span>
                          <span className="text-muted-foreground/50 truncate">{g.reading}</span>
                          <span className="text-muted-foreground/50 truncate ml-auto">{g.vi}</span>
                          <button onClick={() => deleteGlossaryEntry(g.id)} className="p-0.5 rounded opacity-0 group-hover:opacity-60 hover:!opacity-100 hover:text-destructive transition-all shrink-0">
                            <Trash2 className="w-2.5 h-2.5" />
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </ContextSection>

                <ContextSection icon={<StickyNote className="w-4 h-4" />} title={t('context.sessionNotes')} subtitle={t('context.sessionNotesSub')}
                  expanded={expandedSections.notes} onToggle={() => toggleSection('notes')}>
                  <textarea value={notes.general} onChange={(e) => setNotes(prev => ({ ...prev, general: e.target.value }))} onBlur={() => saveNote('general', notes.general)}
                    placeholder={t('context.notesPlaceholder')}
                    className="w-full h-[90px] rounded-lg border border-border/30 bg-background p-2.5 text-xs placeholder:text-muted-foreground/40 focus:outline-none focus:ring-2 focus:ring-ring/20 resize-none" />
                </ContextSection>

                <p className="text-[10px] text-muted-foreground/30 text-center pt-2">{t('meeting.contextFedInfo')}</p>
              </div>
            </TabPanel>
          </div>
        </aside>
      </div>
    </div>
  )
}

/* ─── Local Helper Components ─── */

function ContextSection({ icon, title, subtitle, expanded, onToggle, children }: {
  icon: React.ReactNode; title: string; subtitle: string; expanded: boolean; onToggle: () => void; children: React.ReactNode
}) {
  return (
    <div className="rounded-xl border border-border/30 bg-card/30 overflow-hidden transition-all">
      <button onClick={onToggle} className="w-full flex items-center gap-3 px-3.5 py-2.5 text-left hover:bg-accent/20 transition-colors">
        <span className="text-primary/60">{icon}</span>
        <div className="flex-1 min-w-0">
          <p className="text-xs font-semibold leading-tight">{title}</p>
          <p className="text-[10px] text-muted-foreground/50 truncate">{subtitle}</p>
        </div>
        <ChevronDown className={cn('w-3.5 h-3.5 text-muted-foreground/30 transition-transform duration-200', expanded && 'rotate-180')} />
      </button>
      {expanded && <div className="px-3 pb-3 animate-fade-in">{children}</div>}
    </div>
  )
}

function InsightSection({ title, icon, expanded, onToggle, loading, data, onLoad, render, hasTranscript }: {
  title: string; icon: React.ReactNode; expanded: boolean; onToggle: () => void
  loading: boolean; data: any; onLoad: () => void; render: (d: any) => React.ReactNode; hasTranscript: boolean
}) {
  return (
    <div className="rounded-xl border border-border/30 bg-card/30 overflow-hidden">
      <button onClick={() => { onToggle(); if (!expanded && !data && !loading && hasTranscript) onLoad() }}
        className="w-full flex items-center gap-2.5 px-3.5 py-2.5 text-left hover:bg-accent/20 transition-colors">
        <span className="text-primary/60">{icon}</span>
        <span className="flex-1 text-xs font-semibold">{title}</span>
        {loading && <Loader2 className="w-3 h-3 animate-spin text-primary" />}
        <ChevronRight className={cn('w-3.5 h-3.5 text-muted-foreground/30 transition-transform duration-200', expanded && 'rotate-90')} />
      </button>
      {expanded && (
        <div className="px-3 pb-3 animate-fade-in">
          {loading ? (
            <div className="flex items-center gap-2 text-muted-foreground text-xs py-4 justify-center"><Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading...</div>
          ) : data ? (
            render(data)
          ) : (
            <div className="text-center py-4">
              <button onClick={onLoad} disabled={!hasTranscript} className="text-xs text-primary hover:underline disabled:opacity-40 disabled:no-underline">
                {hasTranscript ? 'Generate' : 'No transcript yet'}
              </button>
            </div>
          )}
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
  return <span className="text-[10px] font-mono text-primary/50 tabular-nums">{(elapsed / 1000).toFixed(1)}s</span>
}
