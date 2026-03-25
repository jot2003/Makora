import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Settings, Plus, Trash2, Check, X, Loader2, Zap, RefreshCw } from 'lucide-react'
import { useAuth } from '@/stores/useAuth'
import { cn, API_BASE as API } from '@/lib/utils'
import { Select } from '@/components/ui/Select'

interface UserSettingsData {
  overlay_font_size: number
  overlay_opacity: number
  overlay_max_history: number
  energy_threshold: number
  default_language: string
}

interface Provider {
  id: number
  name: string
  provider_type: string
  endpoint: string
  deployment: string
  is_active: boolean
  has_key: boolean
}

export default function SettingsPage() {
  const { t } = useTranslation()
  const { user, getHeaders } = useAuth()
  const headers = getHeaders()
  const [settings, setSettings] = useState<UserSettingsData>({
    overlay_font_size: 16, overlay_opacity: 90, overlay_max_history: 8,
    energy_threshold: 200, default_language: 'ja-JP',
  })
  const [providers, setProviders] = useState<Provider[]>([])
  const [editProvider, setEditProvider] = useState<{ name: string; provider_type: string; api_key: string; endpoint: string; deployment: string } | null>(null)
  const [testResult, setTestResult] = useState<{ ok: boolean; error?: string } | null>(null)
  const [saving, setSaving] = useState(false)
  const [detectedModels, setDetectedModels] = useState<string[]>([])
  const [section, setSection] = useState<'providers' | 'overlay' | 'audio' | 'account'>('providers')

  useEffect(() => {
    loadSettings()
    loadProviders()
  }, [])

  const loadSettings = async () => {
    try { const r = await fetch(`${API}/api/settings`, { headers }); if (r.ok) setSettings(await r.json()) } catch {}
  }

  const saveSettings = async (updated: Partial<UserSettingsData>) => {
    const merged = { ...settings, ...updated }
    setSettings(merged)
    setSaving(true)
    try { await fetch(`${API}/api/settings`, { method: 'PUT', headers: { 'Content-Type': 'application/json', ...headers }, body: JSON.stringify(merged) }) } catch {}
    setSaving(false)
  }

  const loadProviders = async () => {
    try { const r = await fetch(`${API}/api/settings/providers`, { headers }); if (r.ok) setProviders(await r.json()) } catch {}
  }

  const createProvider = async () => {
    if (!editProvider) return
    try {
      const r = await fetch(`${API}/api/settings/providers`, { method: 'POST', headers: { 'Content-Type': 'application/json', ...headers }, body: JSON.stringify(editProvider) })
      if (r.ok) { setEditProvider(null); loadProviders() }
    } catch {}
  }

  const deleteProvider = async (id: number) => {
    try { await fetch(`${API}/api/settings/providers/${id}`, { method: 'DELETE', headers }); loadProviders() } catch {}
  }

  const activateProvider = async (id: number) => {
    try { await fetch(`${API}/api/settings/providers/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json', ...headers }, body: JSON.stringify({ is_active: true }) }); loadProviders() } catch {}
  }

  const testProvider = async (id: number) => {
    setTestResult(null)
    try { const r = await fetch(`${API}/api/settings/providers/${id}/test`, { method: 'POST', headers }); if (r.ok) setTestResult(await r.json()) } catch { setTestResult({ ok: false, error: 'Connection failed' }) }
  }

  const detectModels = async (id: number) => {
    setDetectedModels([])
    try { const r = await fetch(`${API}/api/settings/providers/${id}/models`, { headers }); if (r.ok) { const d = await r.json(); setDetectedModels(d.models || []) } } catch {}
  }

  const sections = [
    { key: 'providers' as const, label: t('settings.aiProviders'), icon: Zap },
    { key: 'overlay' as const, label: t('settings.overlay'), icon: Settings },
    { key: 'audio' as const, label: t('settings.audio'), icon: Settings },
    { key: 'account' as const, label: t('settings.account'), icon: Settings },
  ]

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-3xl mx-auto p-6">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
            <Settings className="w-5 h-5 text-primary" />
          </div>
          <div>
            <h1 className="text-lg font-semibold">{t('settings.title')}</h1>
            <p className="text-[12px] text-muted-foreground">{user?.email}</p>
          </div>
          {saving && <Loader2 className="w-4 h-4 animate-spin text-muted-foreground ml-auto" />}
        </div>

        {/* Section tabs */}
        <div className="flex gap-1 mb-6 border-b border-border/50">
          {sections.map(({ key, label }) => (
            <button key={key} onClick={() => setSection(key)}
              className={cn('px-4 py-2 text-[13px] font-medium border-b-2 transition-colors',
                section === key ? 'text-primary border-primary' : 'text-muted-foreground border-transparent hover:text-foreground')}>
              {label}
            </button>
          ))}
        </div>

        {/* AI Providers */}
        {section === 'providers' && (
          <div className="space-y-4 animate-fade-in">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-[14px] font-medium">AI Providers</h3>
                <p className="text-[11px] text-muted-foreground">Configure Azure OpenAI or custom LLM endpoints</p>
              </div>
              <button onClick={() => setEditProvider({ name: '', provider_type: 'azure', api_key: '', endpoint: '', deployment: '' })}
                className="h-8 px-3 rounded-lg bg-primary text-primary-foreground text-[12px] font-medium flex items-center gap-1.5 hover:bg-primary/90 active:scale-[0.97] transition-all">
                <Plus className="w-3.5 h-3.5" /> Add Provider
              </button>
            </div>

            {editProvider && (
              <div className="rounded-xl border border-primary/20 bg-primary/5 p-4 space-y-3 animate-fade-in">
                <input value={editProvider.name} onChange={(e) => setEditProvider({ ...editProvider, name: e.target.value })} placeholder="Provider name (e.g. Azure Production)" className="w-full h-9 rounded-lg border border-border bg-background px-3 text-[13px] placeholder:text-muted-foreground/40 focus:outline-none focus:ring-2 focus:ring-ring/20" />
                <input value={editProvider.endpoint} onChange={(e) => setEditProvider({ ...editProvider, endpoint: e.target.value })} placeholder="Endpoint URL" className="w-full h-9 rounded-lg border border-border bg-background px-3 text-[13px] placeholder:text-muted-foreground/40 focus:outline-none focus:ring-2 focus:ring-ring/20" />
                <div className="flex gap-2">
                  <input value={editProvider.api_key} onChange={(e) => setEditProvider({ ...editProvider, api_key: e.target.value })} placeholder="API Key" type="password" className="flex-1 h-9 rounded-lg border border-border bg-background px-3 text-[13px] placeholder:text-muted-foreground/40 focus:outline-none focus:ring-2 focus:ring-ring/20" />
                  <input value={editProvider.deployment} onChange={(e) => setEditProvider({ ...editProvider, deployment: e.target.value })} placeholder="Deployment/Model" className="flex-1 h-9 rounded-lg border border-border bg-background px-3 text-[13px] placeholder:text-muted-foreground/40 focus:outline-none focus:ring-2 focus:ring-ring/20" />
                </div>
                <div className="flex gap-2">
                  <button onClick={createProvider} className="h-8 px-4 rounded-lg bg-primary text-primary-foreground text-[12px] font-medium hover:bg-primary/90 transition-colors flex items-center gap-1.5"><Check className="w-3.5 h-3.5" /> Save</button>
                  <button onClick={() => setEditProvider(null)} className="h-8 px-4 rounded-lg border border-border text-[12px] font-medium hover:bg-accent transition-colors flex items-center gap-1.5"><X className="w-3.5 h-3.5" /> Cancel</button>
                </div>
              </div>
            )}

            {providers.length === 0 && !editProvider && (
              <div className="text-center py-10 text-muted-foreground">
                <Zap className="w-8 h-8 mx-auto mb-2 opacity-20" />
                <p className="text-[13px]">No providers configured</p>
                <p className="text-[11px] text-muted-foreground/60">Add an Azure OpenAI provider to get started</p>
              </div>
            )}

            {providers.map((p) => (
              <div key={p.id} className={cn('group rounded-xl border p-4 transition-colors', p.is_active ? 'border-primary/30 bg-primary/5' : 'border-border/50 bg-card')}>
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-[14px] font-medium">{p.name}</span>
                    {p.is_active && <span className="text-[10px] font-semibold text-primary bg-primary/10 px-2 py-0.5 rounded-full">Active</span>}
                  </div>
                  <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    {!p.is_active && (
                      <button onClick={() => activateProvider(p.id)} className="h-7 px-2 rounded-md text-[11px] text-primary hover:bg-primary/10 transition-colors">Activate</button>
                    )}
                    <button onClick={() => testProvider(p.id)} className="h-7 px-2 rounded-md text-[11px] text-muted-foreground hover:bg-accent transition-colors">Test</button>
                    <button onClick={() => detectModels(p.id)} className="h-7 px-2 rounded-md text-[11px] text-muted-foreground hover:bg-accent transition-colors flex items-center gap-1"><RefreshCw className="w-3 h-3" /> Models</button>
                    <button onClick={() => deleteProvider(p.id)} className="h-7 px-2 rounded-md text-[11px] text-destructive hover:bg-destructive/10 transition-colors">Delete</button>
                  </div>
                </div>
                <div className="flex gap-4 text-[11px] text-muted-foreground">
                  <span>Type: {p.provider_type}</span>
                  <span>Model: {p.deployment || '-'}</span>
                  <span>Key: {p.has_key ? '***' : 'none'}</span>
                </div>
                {p.endpoint && <p className="text-[10px] text-muted-foreground/60 mt-1 truncate">{p.endpoint}</p>}
              </div>
            ))}

            {testResult && (
              <div className={cn('rounded-lg p-3 text-[12px] animate-fade-in', testResult.ok ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400' : 'bg-red-500/10 text-red-700 dark:text-red-400')}>
                {testResult.ok ? 'Connection successful!' : `Error: ${testResult.error}`}
              </div>
            )}

            {detectedModels.length > 0 && (
              <div className="rounded-lg bg-muted/50 p-3 text-[12px] animate-fade-in">
                <p className="font-medium mb-1">Detected models:</p>
                <div className="flex flex-wrap gap-1.5">
                  {detectedModels.map((m) => <span key={m} className="px-2 py-0.5 rounded bg-card border border-border text-[11px]">{m}</span>)}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Overlay Settings */}
        {section === 'overlay' && (
          <div className="space-y-5 animate-fade-in">
            <h3 className="text-[14px] font-medium">Overlay Settings</h3>
            <SliderSetting label="Font Size" value={settings.overlay_font_size} min={10} max={32} unit="px"
              onChange={(v) => saveSettings({ overlay_font_size: v })} />
            <SliderSetting label="Opacity" value={settings.overlay_opacity} min={20} max={100} unit="%"
              onChange={(v) => saveSettings({ overlay_opacity: v })} />
            <SliderSetting label="Max History Lines" value={settings.overlay_max_history} min={3} max={20}
              onChange={(v) => saveSettings({ overlay_max_history: v })} />
          </div>
        )}

        {/* Audio Settings */}
        {section === 'audio' && (
          <div className="space-y-5 animate-fade-in">
            <h3 className="text-[14px] font-medium">Audio Settings</h3>
            <SliderSetting label="Energy Threshold" value={settings.energy_threshold} min={50} max={1000}
              onChange={(v) => saveSettings({ energy_threshold: v })} />
            <div>
              <label className="text-[12px] text-muted-foreground mb-1.5 block">Default Language</label>
              <Select value={settings.default_language} onChange={(v) => saveSettings({ default_language: v })}
                options={[{ value: 'ja-JP', label: 'Japanese' }, { value: 'en-US', label: 'English' }, { value: 'zh-CN', label: 'Chinese' }, { value: 'ko-KR', label: 'Korean' }]} size="md" className="w-[200px]" />
            </div>
          </div>
        )}

        {/* Account */}
        {section === 'account' && (
          <div className="space-y-4 animate-fade-in">
            <h3 className="text-[14px] font-medium">Account</h3>
            <div className="rounded-xl border border-border/50 p-4">
              <div className="flex items-center gap-3">
                {user?.avatar_url ? (
                  <img src={user.avatar_url} alt="" className="w-12 h-12 rounded-full object-cover" />
                ) : (
                  <div className="w-12 h-12 rounded-full bg-primary/15 flex items-center justify-center text-lg font-semibold text-primary">
                    {user?.username?.slice(0, 2).toUpperCase()}
                  </div>
                )}
                <div>
                  <p className="font-medium">{user?.username}</p>
                  <p className="text-[12px] text-muted-foreground">{user?.email}</p>
                  <p className="text-[10px] text-muted-foreground/60 capitalize">Provider: {user?.provider}</p>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function SliderSetting({ label, value, min, max, unit, onChange }: { label: string; value: number; min: number; max: number; unit?: string; onChange: (v: number) => void }) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <label className="text-[12px] text-muted-foreground">{label}</label>
        <span className="text-[12px] font-mono font-medium">{value}{unit || ''}</span>
      </div>
      <input type="range" min={min} max={max} value={value} onChange={(e) => onChange(Number(e.target.value))}
        className="w-full h-1.5 rounded-lg appearance-none bg-border cursor-pointer accent-primary" />
    </div>
  )
}
