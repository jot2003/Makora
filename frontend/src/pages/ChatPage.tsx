import { useState, useRef, useEffect } from 'react'
import { Send, Loader2, Bot, User, Sparkles } from 'lucide-react'
import { cn } from '@/lib/utils'

const API = 'http://localhost:8000'

interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources?: { meeting_id: string; speaker: string; text: string }[]
}

const SUGGESTIONS = [
  'What did we decide about pricing?',
  'Summarize the last interview',
  'What are the open action items?',
  'When did we first discuss AI features?',
]

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length, loading])

  const sendMessage = async (text?: string) => {
    const query = (text || input).trim()
    if (!query || loading) return
    setInput('')

    setMessages((prev) => [...prev, { id: `u_${Date.now()}`, role: 'user', content: query }])
    setLoading(true)

    try {
      const r = await fetch(`${API}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query }),
      })
      if (r.ok) {
        const data = await r.json()
        setMessages((prev) => [...prev, { id: `a_${Date.now()}`, role: 'assistant', content: data.answer, sources: data.sources }])
      } else {
        setMessages((prev) => [...prev, { id: `e_${Date.now()}`, role: 'assistant', content: 'Could not get a response.' }])
      }
    } catch {
      setMessages((prev) => [...prev, { id: `e_${Date.now()}`, role: 'assistant', content: 'Server unreachable.' }])
    } finally {
      setLoading(false)
      inputRef.current?.focus()
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-2xl mx-auto px-5 py-6">
          {messages.length === 0 && (
            <div className="text-center py-20 animate-fade-in-up">
              <div className="w-12 h-12 rounded-2xl bg-primary/10 flex items-center justify-center mx-auto mb-4">
                <Sparkles className="w-6 h-6 text-primary" />
              </div>
              <h2 className="text-lg font-semibold mb-1">Knowledge Copilot</h2>
              <p className="text-sm text-muted-foreground mb-8">Search across all your meeting transcripts and notes</p>
              <div className="grid grid-cols-2 gap-2 max-w-md mx-auto">
                {SUGGESTIONS.map((s, i) => (
                  <button key={i} onClick={() => sendMessage(s)}
                    className="text-left px-3.5 py-2.5 rounded-xl text-[12px] text-muted-foreground border border-border/60 hover:border-foreground/15 hover:bg-card transition-all duration-200 animate-fade-in leading-snug"
                    style={{ animationDelay: `${i * 60}ms`, animationFillMode: 'backwards' }}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="space-y-5">
            {messages.map((msg) => (
              <div key={msg.id} className="animate-fade-in">
                {msg.role === 'user' ? (
                  <div className="flex gap-3">
                    <div className="w-7 h-7 rounded-full bg-primary flex items-center justify-center shrink-0 mt-0.5">
                      <User className="w-3.5 h-3.5 text-primary-foreground" />
                    </div>
                    <div className="flex-1 pt-0.5">
                      <p className="text-[11px] font-semibold mb-1">You</p>
                      <p className="text-[13px] leading-relaxed">{msg.content}</p>
                    </div>
                  </div>
                ) : (
                  <div className="flex gap-3">
                    <div className="w-7 h-7 rounded-full bg-card border border-border flex items-center justify-center shrink-0 mt-0.5">
                      <Sparkles className="w-3.5 h-3.5 text-primary" />
                    </div>
                    <div className="flex-1 pt-0.5">
                      <p className="text-[11px] font-semibold mb-1">Copilot</p>
                      <div className="text-[13px] leading-relaxed whitespace-pre-wrap">{msg.content}</div>
                      {msg.sources && msg.sources.length > 0 && (
                        <div className="mt-3 space-y-1">
                          <p className="text-[10px] text-muted-foreground font-semibold uppercase tracking-wider">Sources</p>
                          {msg.sources.map((s, i) => (
                            <div key={i} className="text-[11px] text-muted-foreground bg-muted/50 rounded-lg px-3 py-2 border border-border/30">
                              <span className="font-medium text-foreground/70">{s.meeting_id}</span>
                              {s.speaker && <span className="ml-1.5 opacity-50">({s.speaker})</span>}
                              <p className="mt-0.5 opacity-50 line-clamp-2">{s.text}</p>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            ))}

            {loading && (
              <div className="flex gap-3 animate-fade-in">
                <div className="w-7 h-7 rounded-full bg-card border border-border flex items-center justify-center shrink-0">
                  <Sparkles className="w-3.5 h-3.5 text-primary" />
                </div>
                <div className="pt-1">
                  <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    Searching meetings...
                  </div>
                </div>
              </div>
            )}
          </div>
          <div ref={scrollRef} />
        </div>
      </div>

      {/* Input */}
      <div className="shrink-0 px-5 pb-5 pt-2">
        <div className="max-w-2xl mx-auto">
          <div className="relative rounded-2xl border border-border bg-card shadow-sm focus-within:ring-2 focus-within:ring-ring/30 focus-within:border-primary/40 transition-all duration-200">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask about your meetings..."
              rows={1}
              className="w-full resize-none bg-transparent px-4 py-3 pr-12 text-[13px] placeholder:text-muted-foreground/40 focus:outline-none min-h-[44px] max-h-[120px]"
              disabled={loading}
              style={{ height: Math.min(120, Math.max(44, input.split('\n').length * 20 + 24)) }}
            />
            <button
              type="button"
              onClick={() => sendMessage()}
              disabled={loading || !input.trim()}
              className={cn(
                'absolute right-2 bottom-2 h-8 w-8 rounded-lg flex items-center justify-center transition-all duration-200',
                input.trim()
                  ? 'bg-primary text-primary-foreground hover:bg-primary/90 active:scale-90'
                  : 'text-muted-foreground/30',
              )}
            >
              <Send className="w-4 h-4" />
            </button>
          </div>
          <p className="text-[10px] text-muted-foreground/40 text-center mt-2">Meeting Copilot searches across all your transcripts and meeting notes</p>
        </div>
      </div>
    </div>
  )
}
