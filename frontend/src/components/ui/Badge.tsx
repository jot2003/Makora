import { cn } from '@/lib/utils'

interface BadgeProps {
  children: React.ReactNode
  variant?: 'default' | 'success' | 'warning' | 'destructive' | 'outline' | 'secondary'
  dot?: boolean
  className?: string
}

const variants: Record<string, string> = {
  default: 'bg-primary/10 text-primary dark:bg-primary/15',
  success: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
  warning: 'bg-amber-500/10 text-amber-600 dark:text-amber-400',
  destructive: 'bg-red-500/10 text-red-600 dark:text-red-400',
  outline: 'border border-border text-muted-foreground bg-transparent',
  secondary: 'bg-secondary text-secondary-foreground',
}

const dotColors: Record<string, string> = {
  default: 'bg-primary',
  success: 'bg-emerald-500',
  warning: 'bg-amber-500',
  destructive: 'bg-red-500',
  outline: 'bg-muted-foreground',
  secondary: 'bg-secondary-foreground',
}

export function Badge({ children, variant = 'default', dot, className }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-sm font-medium leading-none tracking-wide transition-colors',
        variants[variant],
        className,
      )}
    >
      {dot && <span className={cn('w-1.5 h-1.5 rounded-full', dotColors[variant])} />}
      {children}
    </span>
  )
}
