import { useState, useEffect } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Zap, Mail, Lock, Loader2, Github, Eye, EyeOff } from 'lucide-react'
import { cn, API_BASE as API } from '@/lib/utils'
import { useAuth } from '@/stores/useAuth'

export default function LoginPage() {
  const navigate = useNavigate()
  const { t } = useTranslation()
  const { login, loading, error, clearError } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPw, setShowPw] = useState(false)
  const [oauthProviders, setOauthProviders] = useState<{ google: boolean; github: boolean }>({ google: false, github: false })
  const [oauthLoading, setOauthLoading] = useState<string | null>(null)

  useEffect(() => {
    fetch(`${API}/api/auth/providers`)
      .then(r => r.ok ? r.json() : { google: false, github: false })
      .then(setOauthProviders)
      .catch(() => {})
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const ok = await login(email, password)
    if (ok) navigate('/')
  }

  const handleOAuth = (provider: 'google' | 'github') => {
    setOauthLoading(provider)
    window.location.href = `${API}/api/auth/${provider}`
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      <div className="w-full max-w-sm animate-fade-in-up">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="w-12 h-12 rounded-2xl bg-primary/10 flex items-center justify-center mx-auto mb-3">
            <Zap className="w-6 h-6 text-primary" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight">{t('auth.welcomeBack')}</h1>
          <p className="text-sm text-muted-foreground mt-1">{t('auth.signInTo')}</p>
        </div>

        {/* OAuth */}
        <div className="space-y-2 mb-6">
          <button
            onClick={() => handleOAuth('google')}
            disabled={oauthLoading === 'google'}
            className={cn(
              'w-full h-10 rounded-xl border border-border bg-card text-sm font-medium flex items-center justify-center gap-2 transition-colors',
              !oauthProviders.google
                ? 'opacity-40 cursor-not-allowed'
                : 'hover:bg-accent cursor-pointer'
            )}
          >
            {oauthLoading === 'google' ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <svg className="w-4 h-4" viewBox="0 0 24 24"><path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4"/><path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/><path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/><path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/></svg>
            )}
            {t('auth.continueGoogle')}
            {!oauthProviders.google && <span className="text-[9px] text-muted-foreground/60 ml-1">{t('auth.notConfigured')}</span>}
          </button>
          <button
            onClick={() => handleOAuth('github')}
            disabled={oauthLoading === 'github'}
            className={cn(
              'w-full h-10 rounded-xl border border-border bg-card text-sm font-medium flex items-center justify-center gap-2 transition-colors',
              !oauthProviders.github
                ? 'opacity-40 cursor-not-allowed'
                : 'hover:bg-accent cursor-pointer'
            )}
          >
            {oauthLoading === 'github' ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Github className="w-4 h-4" />
            )}
            {t('auth.continueGithub')}
            {!oauthProviders.github && <span className="text-[9px] text-muted-foreground/60 ml-1">{t('auth.notConfigured')}</span>}
          </button>
        </div>

        {/* Divider */}
        <div className="flex items-center gap-3 mb-6">
          <div className="flex-1 h-px bg-border" />
          <span className="text-[11px] text-muted-foreground uppercase tracking-wider">{t('auth.or')}</span>
          <div className="flex-1 h-px bg-border" />
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-3">
          {error && (
            <div className="text-[12px] text-red-600 dark:text-red-400 bg-red-500/10 rounded-lg px-3 py-2 animate-fade-in">
              {error}
            </div>
          )}
          <div className="relative">
            <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground/50" />
            <input
              type="email"
              placeholder={t('auth.email')}
              value={email}
              onChange={(e) => { setEmail(e.target.value); clearError() }}
              required
              className="w-full h-10 pl-9 pr-3 rounded-xl border border-border bg-card text-sm placeholder:text-muted-foreground/40 focus:outline-none focus:ring-2 focus:ring-ring/30 focus:border-primary/40 transition-all"
            />
          </div>
          <div className="relative">
            <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground/50" />
            <input
              type={showPw ? 'text' : 'password'}
              placeholder={t('auth.password')}
              value={password}
              onChange={(e) => { setPassword(e.target.value); clearError() }}
              required
              minLength={6}
              className="w-full h-10 pl-9 pr-9 rounded-xl border border-border bg-card text-sm placeholder:text-muted-foreground/40 focus:outline-none focus:ring-2 focus:ring-ring/30 focus:border-primary/40 transition-all"
            />
            <button type="button" onClick={() => setShowPw(!showPw)} className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground/40 hover:text-muted-foreground transition-colors">
              {showPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>
          <button
            type="submit"
            disabled={loading}
            className="w-full h-10 rounded-xl bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 active:scale-[0.98] transition-all disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {loading && <Loader2 className="w-4 h-4 animate-spin" />}
            {t('auth.signIn')}
          </button>
        </form>

        <p className="text-center text-sm text-muted-foreground mt-6">
          {t('auth.noAccount')}{' '}
          <Link to="/register" className="text-primary hover:underline font-medium">{t('auth.signUp')}</Link>
        </p>
      </div>
    </div>
  )
}
