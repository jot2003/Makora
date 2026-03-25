import { useTranslation } from 'react-i18next'
import { Globe } from 'lucide-react'
import { cn } from '@/lib/utils'

export function LanguageSwitcher({ className }: { className?: string }) {
  const { i18n } = useTranslation()
  const lang = i18n.language

  const toggle = () => {
    const next = lang === 'en' ? 'vi' : 'en'
    i18n.changeLanguage(next)
    localStorage.setItem('app-lang', next)
  }

  return (
    <button
      onClick={toggle}
      className={cn(
        'h-8 px-2 rounded-lg text-xs font-medium flex items-center gap-1.5 transition-colors',
        'text-muted-foreground hover:text-foreground hover:bg-accent',
        className,
      )}
      title={lang === 'en' ? 'Switch to Vietnamese' : 'Chuyển sang tiếng Anh'}
    >
      <Globe className="w-3.5 h-3.5" />
      {lang.toUpperCase()}
    </button>
  )
}
