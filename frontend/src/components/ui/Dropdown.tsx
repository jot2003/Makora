import { useState, useRef, useEffect, type ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { ChevronDown } from 'lucide-react'

interface DropdownProps {
  trigger: ReactNode
  children: ReactNode
  align?: 'left' | 'right'
  className?: string
}

export function Dropdown({ trigger, children, align = 'left', className }: DropdownProps) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    if (open) document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  return (
    <div ref={ref} className={cn('relative inline-flex', className)}>
      <div onClick={() => setOpen(!open)} className="cursor-pointer">
        {trigger}
      </div>
      {open && (
        <div
          className={cn(
            'absolute top-full mt-1 z-50 min-w-[160px] rounded-xl border border-border bg-card shadow-lg animate-scale-in origin-top overflow-hidden',
            align === 'right' ? 'right-0' : 'left-0',
          )}
          onClick={() => setOpen(false)}
        >
          {children}
        </div>
      )}
    </div>
  )
}

interface DropdownItemProps {
  children: ReactNode
  onClick?: () => void
  active?: boolean
  className?: string
}

export function DropdownItem({ children, onClick, active, className }: DropdownItemProps) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'w-full flex items-center gap-2 px-3 py-2 text-sm text-left transition-colors',
        active ? 'bg-primary/10 text-primary font-medium' : 'text-foreground hover:bg-muted',
        className,
      )}
    >
      {children}
    </button>
  )
}

export { ChevronDown as DropdownIcon }
