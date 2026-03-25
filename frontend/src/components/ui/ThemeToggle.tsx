import { Moon, Sun } from 'lucide-react'
import { useTheme } from '@/stores/useTheme'
import { cn } from '@/lib/utils'

export function ThemeToggle({ className }: { className?: string }) {
  const { theme, toggle } = useTheme()

  return (
    <button
      onClick={toggle}
      className={cn(
        'relative inline-flex h-8 w-8 items-center justify-center rounded-lg',
        'text-muted-foreground hover:text-foreground hover:bg-accent',
        'transition-all duration-200 focus-ring',
        className,
      )}
      aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
    >
      <Sun
        className={cn(
          'h-4 w-4 transition-all duration-300',
          theme === 'dark' ? 'rotate-90 scale-0 opacity-0' : 'rotate-0 scale-100 opacity-100',
        )}
        style={{ position: 'absolute' }}
      />
      <Moon
        className={cn(
          'h-4 w-4 transition-all duration-300',
          theme === 'dark' ? 'rotate-0 scale-100 opacity-100' : '-rotate-90 scale-0 opacity-0',
        )}
        style={{ position: 'absolute' }}
      />
    </button>
  )
}
