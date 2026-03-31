import { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  Plus, Mic, FileAudio, MessageSquare, PanelLeftClose, PanelLeft,
  Trash2, Settings, LogOut, ChevronDown, BarChart3,
} from 'lucide-react'
import { cn, API_BASE as API } from '@/lib/utils'
import { ThemeToggle } from '@/components/ui/ThemeToggle'
import { LanguageSwitcher } from '@/components/ui/LanguageSwitcher'
import { Select } from '@/components/ui/Select'
import { useAuth } from '@/stores/useAuth'

export interface Meeting {
  id: string
  name: string
  mode: string
  status: string
  created_at: string
  transcript_count: number
}

interface SidebarProps {
  meetings: Meeting[]
  onRefresh: () => void
}

export function Sidebar({ meetings, onRefresh }: SidebarProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const { t } = useTranslation()
  const { user, logout, getHeaders } = useAuth()
  const [collapsed, setCollapsed] = useState(() => typeof window !== 'undefined' && window.innerWidth < 768)
  const [mode, setMode] = useState<string>('interview')
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [userMenuOpen, setUserMenuOpen] = useState(false)

  const currentPath = location.pathname
  const currentMeetingId = currentPath.startsWith('/meeting/') ? currentPath.split('/meeting/')[1] : null

  const createMeeting = async () => {
    try {
      const r = await fetch(`${API}/api/meetings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getHeaders() },
        body: JSON.stringify({ name: `Session ${new Date().toLocaleTimeString()}`, mode }),
      })
      if (r.ok) {
        const m = await r.json()
        onRefresh()
        navigate(`/meeting/${m.id}`)
      }
    } catch {}
  }

  const deleteMeeting = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    try {
      const r = await fetch(`${API}/api/meetings/${id}`, { method: 'DELETE', headers: getHeaders() })
      if (r.ok || r.status === 204) {
        onRefresh()
        if (currentMeetingId === id) navigate('/')
      }
    } catch {}
  }

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const initials = user?.username?.slice(0, 2).toUpperCase() || '?'

  if (collapsed) {
    return (
      <div className="w-[50px] shrink-0 border-r border-border/50 bg-card/50 flex flex-col items-center py-2 gap-1 transition-all duration-300">
        <button onClick={() => setCollapsed(false)} className="p-2 rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent transition-colors" title="Expand">
          <PanelLeft className="w-4 h-4" />
        </button>
        <div className="w-6 h-px bg-border/60 my-1" />
        <button onClick={createMeeting} className="p-2 rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent transition-colors" title={t('nav.newSession')}>
          <Plus className="w-4 h-4" />
        </button>
        <button onClick={() => navigate('/chat')} className={cn('p-2 rounded-lg transition-colors', currentPath === '/chat' ? 'bg-accent text-foreground' : 'text-muted-foreground hover:text-foreground hover:bg-accent')} title={t('nav.knowledgeChat')}>
          <MessageSquare className="w-4 h-4" />
        </button>
        <button onClick={() => navigate('/usage')} className={cn('p-2 rounded-lg transition-colors', currentPath === '/usage' ? 'bg-accent text-foreground' : 'text-muted-foreground hover:text-foreground hover:bg-accent')} title={t('nav.usageDashboard')}>
          <BarChart3 className="w-4 h-4" />
        </button>
        <div className="flex-1" />
        <ThemeToggle />
        {user && (
          <button onClick={handleLogout} className="p-2 rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent transition-colors" title="Logout">
            <LogOut className="w-4 h-4" />
          </button>
        )}
      </div>
    )
  }

  const grouped = { today: [] as Meeting[], week: [] as Meeting[], older: [] as Meeting[] }
  const now = Date.now()
  const dayMs = 86400000
  meetings.forEach((m) => {
    const age = now - new Date(m.created_at).getTime()
    if (age < dayMs) grouped.today.push(m)
    else if (age < dayMs * 7) grouped.week.push(m)
    else grouped.older.push(m)
  })

  const renderGroup = (label: string, items: Meeting[]) => {
    if (items.length === 0) return null
    return (
      <div key={label} className="mb-3">
        <p className="text-xs font-semibold text-muted-foreground/60 uppercase tracking-wider px-3 mb-1.5">{label}</p>
        {items.map((m) => (
          <button
            key={m.id}
            onClick={() => navigate(`/meeting/${m.id}`)}
            onMouseEnter={() => setHoveredId(m.id)}
            onMouseLeave={() => setHoveredId(null)}
            className={cn(
              'group w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-all duration-150',
              currentMeetingId === m.id ? 'bg-primary/10 text-primary font-medium border-l-2 border-primary' : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground',
            )}
          >
            {m.id.startsWith('upload_') ? <FileAudio className="w-4.5 h-4.5 shrink-0 opacity-60" /> : <Mic className="w-4.5 h-4.5 shrink-0 opacity-60" />}
            <span className="text-[15px] truncate flex-1">{m.name}</span>
            {hoveredId === m.id && (
              <button onClick={(e) => deleteMeeting(m.id, e)} className="p-0.5 rounded opacity-0 group-hover:opacity-60 hover:!opacity-100 hover:bg-destructive/10 hover:text-destructive transition-all">
                <Trash2 className="w-3 h-3" />
              </button>
            )}
          </button>
        ))}
      </div>
    )
  }

  return (
    <div className="w-[280px] shrink-0 border-r border-border/50 bg-card/50 flex flex-col transition-all duration-300">
      {/* Top */}
      <div className="shrink-0 p-2.5 flex items-center gap-1">
        <button onClick={createMeeting} className="flex-1 h-10 flex items-center gap-2.5 px-3.5 rounded-lg text-[15px] font-semibold text-foreground hover:bg-accent transition-colors">
          <Plus className="w-4.5 h-4.5" />
          {t('nav.newSession')}
        </button>
        <button onClick={() => setCollapsed(true)} className="p-2 rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent transition-colors">
          <PanelLeftClose className="w-4.5 h-4.5" />
        </button>
      </div>

      {/* Chat + Usage links */}
      <div className="px-2.5 mb-1 space-y-0.5">
        <button onClick={() => navigate('/chat')}
          className={cn('w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-[15px] transition-all duration-150',
            currentPath === '/chat' ? 'bg-primary/10 text-primary font-medium border-l-2 border-primary' : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground',
          )}>
          <MessageSquare className="w-4.5 h-4.5" />
          {t('nav.knowledgeChat')}
        </button>
        <button onClick={() => navigate('/usage')}
          className={cn('w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-[15px] transition-all duration-150',
            currentPath === '/usage' ? 'bg-primary/10 text-primary font-medium border-l-2 border-primary' : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground',
          )}>
          <BarChart3 className="w-4.5 h-4.5" />
          {t('nav.usageDashboard')}
        </button>
      </div>

      <div className="h-px bg-border/40 mx-3 my-1" />

      {/* Session list */}
      <div className="flex-1 overflow-y-auto px-2 py-1">
        {meetings.length === 0 ? (
          <p className="text-xs text-muted-foreground/50 text-center py-8">{t('common.noSessionsYet')}</p>
        ) : (
          <>
            {renderGroup('Today', grouped.today)}
            {renderGroup('This week', grouped.week)}
            {renderGroup('Older', grouped.older)}
          </>
        )}
      </div>

      {/* Bottom — User + Settings */}
      <div className="shrink-0 border-t border-border/40">
        <div className="p-2 flex items-center gap-1">
          <ThemeToggle />
          <LanguageSwitcher />
          <Select value={mode} onChange={setMode}
            options={[{ value: 'interview', label: t('meeting.interview') }, { value: 'meeting', label: t('meeting.meetingMode') }]}
            size="sm" className="flex-1" />
          <button onClick={() => navigate('/settings')} className={cn('p-2 rounded-lg transition-colors', currentPath === '/settings' ? 'text-foreground bg-accent' : 'text-muted-foreground hover:text-foreground hover:bg-accent')}>
            <Settings className="w-4 h-4" />
          </button>
        </div>

        {user && (
          <div className="relative px-2 pb-2">
            <button
              onClick={() => setUserMenuOpen(!userMenuOpen)}
              className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-accent transition-colors"
            >
              {user.avatar_url ? (
                <img src={user.avatar_url} alt="" className="w-8 h-8 rounded-full object-cover" />
              ) : (
                <div className="w-8 h-8 rounded-full bg-primary/15 flex items-center justify-center text-xs font-semibold text-primary">{initials}</div>
              )}
              <div className="flex-1 text-left min-w-0">
                <p className="text-sm font-medium truncate">{user.username}</p>
                <p className="text-xs text-muted-foreground truncate">{user.email}</p>
              </div>
              <ChevronDown className={cn('w-3 h-3 text-muted-foreground transition-transform', userMenuOpen && 'rotate-180')} />
            </button>

            {userMenuOpen && (
              <div className="absolute bottom-full left-2 right-2 mb-1 rounded-lg border border-border bg-card shadow-lg overflow-hidden animate-scale-in origin-bottom z-50">
                <button onClick={handleLogout} className="w-full flex items-center gap-2 px-3 py-2.5 text-sm text-muted-foreground hover:text-foreground hover:bg-muted transition-colors">
                  <LogOut className="w-3.5 h-3.5" />
                  {t('nav.signOut')}
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
