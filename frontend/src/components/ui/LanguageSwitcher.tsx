import { useTranslation } from 'react-i18next'
import { Globe } from 'lucide-react'
import { cn } from '@/lib/utils'

const LANGS = ['en', 'vi', 'ja'] as const
const LABELS: Record<string, string> = { en: 'EN', vi: 'VI', ja: 'JA' }

export function LanguageSwitcher({ className }: { className?: string }) {
  const { i18n } = useTranslation()
  const lang = i18n.language

  const cycle = () => {
    const idx = LANGS.indexOf(lang as typeof LANGS[number])
    const next = LANGS[(idx + 1) % LANGS.length]
    i18n.changeLanguage(next)
    localStorage.setItem('app-lang', next)
  }

  return (
    <button
      onClick={cycle}
      className={cn(
        'h-8 px-2 rounded-lg text-xs font-medium flex items-center gap-1.5 transition-colors',
        'text-muted-foreground hover:text-foreground hover:bg-accent',
        className,
      )}
      title="Switch language"
    >
      <Globe className="w-3.5 h-3.5" />
      {LABELS[lang] || lang.toUpperCase()}
    </button>
  )
}
