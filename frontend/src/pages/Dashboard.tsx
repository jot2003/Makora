import { useState, useRef } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Zap, Upload, Loader2, Radio, Mic, FileAudio, Sparkles } from 'lucide-react'
import { cn, API_BASE as API } from '@/lib/utils'
import { Select } from '@/components/ui/Select'
import { useAuth } from '@/stores/useAuth'

export default function Dashboard() {
  const navigate = useNavigate()
  const { t } = useTranslation()
  const { getHeaders } = useAuth()
  const { refreshMeetings } = useOutletContext<{ refreshMeetings: () => void }>()
  const [newName, setNewName] = useState('')
  const [mode, setMode] = useState('interview')
  const [language, setLanguage] = useState('ja')
  const [uploading, setUploading] = useState(false)
  const [uploadResult, setUploadResult] = useState<{ type: 'success' | 'error'; message: string } | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const createMeeting = async () => {
    const name = newName.trim() || `Session ${new Date().toLocaleTimeString()}`
    try {
      const r = await fetch(`${API}/api/meetings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getHeaders() },
        body: JSON.stringify({ name, mode }),
      })
      if (r.ok) {
        const m = await r.json()
        setNewName('')
        refreshMeetings()
        navigate(`/meeting/${m.id}`)
      }
    } catch {}
  }

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setUploading(true)
    setUploadResult(null)

    const formData = new FormData()
    formData.append('file', file)
    formData.append('language', language)
    formData.append('mode', mode)
    if (newName.trim()) formData.append('meeting_name', newName.trim())

    try {
      const r = await fetch(`${API}/api/upload`, { method: 'POST', body: formData, headers: getHeaders() })
      if (r.ok) {
        const data = await r.json()
        setUploadResult({
          type: 'success',
          message: `${data.segments} segments · ${Math.round(data.duration)}s · ${data.speakers?.join(', ') || 'N/A'}`,
        })
        refreshMeetings()
        setTimeout(() => navigate(`/meeting/${data.meeting_id}`), 1000)
      } else {
        const err = await r.json().catch(() => ({ detail: 'Failed' }))
        setUploadResult({ type: 'error', message: err.detail || 'Upload failed' })
      }
    } catch {
      setUploadResult({ type: 'error', message: 'Server unreachable' })
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <div className="flex-1 flex items-center justify-center p-8">
      <div className="w-full max-w-lg animate-fade-in-up">
        {/* Hero */}
        <div className="text-center mb-10">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-primary/20 to-primary/5 flex items-center justify-center mx-auto mb-4 shadow-lg shadow-primary/10">
            <Zap className="w-8 h-8 text-primary" />
          </div>
          <h1 className="text-3xl font-bold tracking-tight bg-gradient-to-r from-foreground to-foreground/70 bg-clip-text">{t('dashboard.title')}</h1>
          <p className="text-base text-muted-foreground mt-2">{t('dashboard.subtitle')}</p>
        </div>

        {/* Actions */}
        <div className="space-y-3">
          {/* Name input */}
          <input
            type="text"
            placeholder={t('dashboard.sessionName')}
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && createMeeting()}
            className="w-full h-11 bg-card border border-border rounded-xl px-4 text-sm placeholder:text-muted-foreground/50 focus:outline-none focus:ring-2 focus:ring-ring/30 focus:border-primary/40 transition-all duration-200"
          />

          {/* Options row */}
          <div className="flex gap-2">
            <Select
              value={mode}
              onChange={setMode}
              options={[
                { value: 'interview', label: 'Interview' },
                { value: 'meeting', label: 'Meeting' },
              ]}
              className="flex-1"
            />
            <Select
              value={language}
              onChange={setLanguage}
              options={[
                { value: 'ja', label: 'Japanese' },
                { value: 'en', label: 'English' },
                { value: 'zh', label: 'Chinese' },
                { value: 'ko', label: 'Korean' },
              ]}
              className="flex-1"
            />
          </div>

          {/* Buttons */}
          <div className="flex gap-2">
            <button
              onClick={createMeeting}
              className="flex-1 h-12 bg-gradient-to-r from-primary to-primary/90 text-primary-foreground rounded-xl text-sm font-semibold hover:shadow-lg hover:shadow-primary/20 active:scale-[0.98] transition-all duration-200 shadow-md flex items-center justify-center gap-2"
            >
              <Mic className="w-4.5 h-4.5" />
              {t('dashboard.startLive')}
            </button>

            <input ref={fileRef} type="file" accept=".mp3,.wav,.m4a,.mp4,.webm,.flac,.ogg" onChange={handleUpload} className="hidden" id="file-upload" disabled={uploading} />
            <label
              htmlFor="file-upload"
              className={cn(
                'h-11 px-5 rounded-xl text-sm font-medium flex items-center gap-2 cursor-pointer transition-all duration-200 border',
                uploading
                  ? 'border-border text-muted-foreground cursor-wait'
                  : 'border-border text-foreground hover:bg-accent active:scale-[0.98]',
              )}
            >
              {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
              {uploading ? t('dashboard.processing') : t('dashboard.import')}
            </label>
          </div>

          {/* Upload result */}
          {uploadResult && (
            <div className={cn(
              'text-[12px] px-3 py-2 rounded-lg animate-fade-in',
              uploadResult.type === 'error'
                ? 'bg-red-500/10 text-red-600 dark:text-red-400'
                : 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
            )}>
              {uploadResult.message}
            </div>
          )}
        </div>

        {/* Features */}
        <div className="mt-10 grid grid-cols-3 gap-3">
          {[
            { icon: Mic, label: t('dashboard.features.transcription'), desc: t('dashboard.features.transcriptionDesc'), color: 'text-emerald-500' },
            { icon: Sparkles, label: t('dashboard.features.intelligence'), desc: t('dashboard.features.intelligenceDesc'), color: 'text-primary' },
            { icon: FileAudio, label: t('dashboard.features.importAnalyze'), desc: t('dashboard.features.importAnalyzeDesc'), color: 'text-amber-500' },
          ].map(({ icon: Icon, label, desc, color }) => (
            <div key={label} className="rounded-xl border border-border/60 p-4 text-center hover:border-primary/30 hover:shadow-sm transition-all duration-200 group">
              <div className={cn('w-10 h-10 rounded-lg bg-muted/50 flex items-center justify-center mx-auto mb-3 group-hover:scale-105 transition-transform', color)}>
                <Icon className="w-5 h-5" />
              </div>
              <p className="text-sm font-medium">{label}</p>
              <p className="text-xs text-muted-foreground mt-1 leading-relaxed">{desc}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
