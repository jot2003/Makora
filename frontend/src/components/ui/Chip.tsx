import { type ReactNode } from 'react'
import { cn } from '@/lib/utils'

interface ChipProps {
  children: ReactNode
  active?: boolean
  onClick?: () => void
  icon?: ReactNode
  className?: string
  variant?: 'default' | 'primary' | 'success' | 'warning'
}

const variantClasses = {
  default: {
    active: 'bg-foreground/10 text-foreground border-foreground/20',
    inactive: 'bg-muted/50 text-muted-foreground border-border/50 hover:bg-muted hover:text-foreground',
  },
  primary: {
    active: 'bg-primary/10 text-primary border-primary/25',
    inactive: 'bg-muted/50 text-muted-foreground border-border/50 hover:bg-primary/5 hover:text-primary',
  },
  success: {
    active: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/25',
    inactive: 'bg-muted/50 text-muted-foreground border-border/50 hover:bg-emerald-500/5 hover:text-emerald-600',
  },
  warning: {
    active: 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/25',
    inactive: 'bg-muted/50 text-muted-foreground border-border/50 hover:bg-amber-500/5 hover:text-amber-600',
  },
}

export function Chip({ children, active = false, onClick, icon, className, variant = 'default' }: ChipProps) {
  const styles = variantClasses[variant]
  const Component = onClick ? 'button' : 'div'

  return (
    <Component
      onClick={onClick}
      className={cn(
        'inline-flex items-center gap-1.5 h-8 px-3 rounded-full text-xs font-medium border transition-all duration-200',
        onClick && 'cursor-pointer active:scale-[0.97]',
        active ? styles.active : styles.inactive,
        className,
      )}
    >
      {icon}
      {children}
    </Component>
  )
}
