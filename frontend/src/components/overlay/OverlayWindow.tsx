import { useEffect, useRef, useState, useCallback, type FC } from 'react'
import { Pin, X, Send, Minimize2, ChevronUp } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useWebSocket } from '@/stores/useWebSocket'
import { useMeeting } from '@/stores/useMeeting'

const MAX_VISIBLE = 8

export default function OverlayWindow() {
  const { status: wsStatus, connect, lastMessage, send } = useWebSocket()
  const meeting = useMeeting()
  const scrollRef = useRef<HTMLDivElement>(null)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const [collapsed, setCollapsed] = useState(false)
  const [manualText, setManualText] = useState('')
  const lastFinalCountRef = useRef(0)

  useEffect(() => {
    if (wsStatus !== 'connected') connect()
  }, [])

  useEffect(() => {
    if (!lastMessage) return
    const msg = lastMessage
    switch (msg.type) {
      case 'interim':
        meeting.addTranscriptLine({ id: `interim_${msg.speaker}`, text: msg.text as string, romaji: (msg.romaji as string) || '', speaker: (msg.speaker as string) || '', timestamp: Date.now(), isFinal: false })
        break
      case 'final':
        meeting.addTranscriptLine({ id: `final_${Date.now()}`, text: msg.text as string, romaji: (msg.romaji as string) || '', speaker: (msg.speaker as string) || '', timestamp: Date.now(), isFinal: true })
        break
      case 'translation':
        meeting.updateLastLineForSpeaker(msg.speaker as string, { translationVi: msg.vi as string })
        break
      case 'suggestion_start': meeting.startSuggestionStream((msg.line_id as string) || ''); break
      case 'suggestion_chunk': meeting.appendSuggestionChunk(msg.field as string, msg.chunk as string); break
      case 'suggestion_done': meeting.addSuggestion({ id: (msg.id as string) || `sg_${Date.now()}`, answerRomaji: (msg.answer_romaji as string) || '', answerVi: (msg.answer_vi as string) || '', pinned: false, timestamp: Date.now(), lineId: (msg.line_id as string) || '' }); break
      case 'now_discussing': meeting.setNowDiscussing(msg.topic as string); break
    }
  }, [lastMessage])

  const debouncedScroll = useCallback(() => {
    const finalCount = meeting.transcript.filter(l => l.isFinal).length
    if (finalCount > lastFinalCountRef.current) {
      lastFinalCountRef.current = finalCount
      requestAnimationFrame(() => {
        scrollRef.current?.scrollIntoView({ behavior: 'smooth' })
      })
    }
  }, [meeting.transcript])

  useEffect(() => { debouncedScroll() }, [meeting.transcript.length])

  const recentTranscript = meeting.transcript.slice(-MAX_VISIBLE)
  const finalLines = recentTranscript.filter(l => l.isFinal)
  const interimLine = recentTranscript.find(l => !l.isFinal)
  const pinnedSuggestions = meeting.suggestions.filter((s) => s.pinned)
  const latestSuggestion = meeting.suggestions.find((s) => !s.pinned)

  const handleManualSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!manualText.trim()) return
    send({ type: 'manual_answer', text: manualText.trim(), ai_refine: true })
    setManualText('')
  }

  return (
    <div className="h-screen w-screen flex flex-col select-none" style={{ WebkitAppRegion: 'drag' } as React.CSSProperties}>
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-black/70 backdrop-blur-xl border-b border-white/8">
        <div className="flex items-center gap-2">
          <span className={cn('w-1.5 h-1.5 rounded-full', wsStatus === 'connected' ? 'bg-emerald-400 animate-pulse' : 'bg-red-400')} />
          <span className="text-[10px] text-white/50 font-medium tracking-wide">Copilot</span>
        </div>
        <div className="flex items-center gap-1" style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}>
          <button onClick={() => setCollapsed(!collapsed)} className="p-1 rounded hover:bg-white/10 transition-colors">
            {collapsed ? <ChevronUp className="w-3 h-3 text-white/50" /> : <Minimize2 className="w-3 h-3 text-white/50" />}
          </button>
        </div>
      </div>

      {!collapsed && (
        <div className="flex-1 flex flex-col overflow-hidden bg-black/60 backdrop-blur-xl">
          {/* Now discussing */}
          {meeting.nowDiscussing && (
            <div className="px-3 py-1.5 bg-blue-500/10 border-b border-blue-500/15 transition-all duration-300">
              <p className="text-[9px] text-blue-300/70 font-medium uppercase tracking-wider">Topic</p>
              <p className="text-[11px] text-white/85 leading-tight">{meeting.nowDiscussing}</p>
            </div>
          )}

          {/* Captions — locked final + floating interim */}
          <div ref={scrollContainerRef} className="flex-1 overflow-y-auto px-3 py-2 space-y-0.5 scroll-smooth">
            {finalLines.map((line, idx) => (
              <div key={line.id} className="text-[11px] leading-relaxed text-white/90 transition-opacity duration-300"
                style={{ opacity: 0.4 + (idx / finalLines.length) * 0.6 }}>
                {line.speaker && (
                  <span className={cn('font-medium mr-1 text-[9px]', line.speaker === 'me' ? 'text-emerald-400/70' : 'text-blue-300/70')}>
                    [{line.speaker === 'me' ? 'You' : line.speaker}]
                  </span>
                )}
                <span>{line.translationVi || line.romaji || line.text}</span>
                {line.translationVi && line.romaji && <span className="text-white/25 ml-1 text-[9px]">{line.romaji}</span>}
              </div>
            ))}

            {/* Interim (currently speaking) */}
            {interimLine && (
              <div className="text-[11px] leading-relaxed text-white/40 italic border-l-2 border-white/10 pl-2 transition-all duration-200">
                {interimLine.speaker && (
                  <span className="text-white/30 font-medium mr-1 text-[9px]">[{interimLine.speaker === 'me' ? 'You' : interimLine.speaker}]</span>
                )}
                <span>{interimLine.romaji || interimLine.text}</span>
                <span className="inline-block w-1 h-2.5 bg-white/30 animate-pulse ml-0.5 rounded-sm" />
              </div>
            )}
            <div ref={scrollRef} />
          </div>

          {/* Suggestions */}
          <div className="border-t border-white/8">
            {meeting.streamingSuggestion && (
              <div className="px-3 py-2 bg-purple-500/8">
                <div className="flex items-center justify-between mb-0.5">
                  <p className="text-[9px] text-purple-300/70 font-medium">AI thinking...</p>
                  <OverlayLiveTimer startTime={meeting.suggestionStartTime} />
                </div>
                {meeting.streamingSuggestion.answerRomaji && <p className="text-[11px] text-white/85 leading-relaxed">{meeting.streamingSuggestion.answerRomaji}</p>}
                {meeting.streamingSuggestion.answerVi && <p className="text-[9px] text-white/40 mt-0.5">{meeting.streamingSuggestion.answerVi}</p>}
              </div>
            )}

            {pinnedSuggestions.map((sg) => (
              <div key={sg.id} className="px-3 py-2 bg-amber-500/8 border-b border-amber-500/15">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    {sg.answerRomaji && <p className="text-[11px] text-white/85 leading-relaxed">{sg.answerRomaji}</p>}
                    {sg.answerVi && <p className="text-[9px] text-white/40 mt-0.5">{sg.answerVi}</p>}
                  </div>
                  <button onClick={() => meeting.dismissLineSuggestion(sg.id)} className="p-0.5 rounded hover:bg-white/10 shrink-0" style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}>
                    <X className="w-2.5 h-2.5 text-white/30" />
                  </button>
                </div>
              </div>
            ))}

            {latestSuggestion && (
              <div className="px-3 py-2 bg-purple-500/8">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                      <p className="text-[9px] text-purple-300/60 font-medium">Suggestion</p>
                      {latestSuggestion.elapsedMs != null && <span className="text-[9px] font-mono text-purple-300/40">{(latestSuggestion.elapsedMs / 1000).toFixed(1)}s</span>}
                    </div>
                    {latestSuggestion.answerRomaji && <p className="text-[11px] text-white/85 leading-relaxed">{latestSuggestion.answerRomaji}</p>}
                    {latestSuggestion.answerVi && <p className="text-[9px] text-white/40 mt-0.5">{latestSuggestion.answerVi}</p>}
                  </div>
                  <div className="flex flex-col gap-0.5 shrink-0" style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}>
                    <button onClick={() => {}} className="p-0.5 rounded hover:bg-white/10" title="Pin"><Pin className="w-2.5 h-2.5 text-white/30" /></button>
                    <button onClick={() => meeting.dismissLineSuggestion(latestSuggestion.id)} className="p-0.5 rounded hover:bg-white/10" title="Dismiss"><X className="w-2.5 h-2.5 text-white/30" /></button>
                  </div>
                </div>
              </div>
            )}

            {/* Manual input */}
            <form onSubmit={handleManualSubmit} className="flex gap-1 px-2 py-1.5 bg-black/40" style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}>
              <input value={manualText} onChange={(e) => setManualText(e.target.value)} placeholder="Type answer..."
                className="flex-1 bg-white/5 border border-white/8 rounded px-2 py-1 text-[11px] text-white placeholder:text-white/20 focus:outline-none focus:border-white/15 transition-colors" />
              <button type="submit" className="p-1.5 rounded bg-purple-500/15 hover:bg-purple-500/25 transition-colors">
                <Send className="w-2.5 h-2.5 text-purple-300/70" />
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

function OverlayLiveTimer({ startTime }: { startTime: number | null }) {
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    if (startTime == null) return
    const tick = () => setElapsed(performance.now() - startTime)
    tick()
    const id = setInterval(tick, 100)
    return () => clearInterval(id)
  }, [startTime])
  if (startTime == null) return null
  return <span className="text-[9px] font-mono text-purple-300/40 tabular-nums">{(elapsed / 1000).toFixed(1)}s</span>
}
