import { useState, useRef, useEffect } from 'react'
import { ChevronDown, Check } from 'lucide-react'
import { cn } from '@/lib/utils'

interface Option {
  value: string
  label: string
}

interface SelectProps {
  value: string
  onChange: (value: string) => void
  options: Option[]
  placeholder?: string
  className?: string
  size?: 'sm' | 'md'
}

export function Select({ value, onChange, options, placeholder, className, size = 'md' }: SelectProps) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const selected = options.find((o) => o.value === value)

  return (
    <div ref={ref} className={cn('relative', className)}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={cn(
          'flex items-center justify-between gap-2 w-full rounded-lg border border-border bg-background text-sm transition-all duration-200',
          'hover:border-foreground/20 focus:outline-none focus:ring-2 focus:ring-ring/40',
          size === 'sm' ? 'h-9 px-3 text-sm' : 'h-10 px-3.5',
          open && 'ring-2 ring-ring/40 border-primary/50',
        )}
      >
        <span className={cn(!selected && 'text-muted-foreground')}>
          {selected?.label || placeholder || 'Select...'}
        </span>
        <ChevronDown className={cn(
          'w-3.5 h-3.5 text-muted-foreground transition-transform duration-200',
          open && 'rotate-180',
        )} />
      </button>

      {open && (
        <div className="absolute z-50 mt-1 w-full min-w-[140px] rounded-lg border border-border bg-card shadow-lg animate-scale-in origin-top overflow-hidden">
          {options.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => { onChange(opt.value); setOpen(false) }}
              className={cn(
                'flex items-center justify-between w-full px-3 text-sm transition-colors',
                size === 'sm' ? 'py-2 text-sm' : 'py-2.5',
                opt.value === value
                  ? 'bg-primary/10 text-primary font-medium'
                  : 'text-foreground hover:bg-muted',
              )}
            >
              {opt.label}
              {opt.value === value && <Check className="w-3.5 h-3.5" />}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
