import { useState, useRef, useCallback, type ReactNode } from 'react'
import { cn } from '@/lib/utils'

interface TooltipProps {
  content: string
  children: ReactNode
  side?: 'top' | 'bottom' | 'left' | 'right'
  className?: string
  delayMs?: number
}

export function Tooltip({ content, children, side = 'top', className, delayMs = 400 }: TooltipProps) {
  const [visible, setVisible] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const show = useCallback(() => {
    timerRef.current = setTimeout(() => setVisible(true), delayMs)
  }, [delayMs])

  const hide = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    setVisible(false)
  }, [])

  const positionClasses: Record<string, string> = {
    top: 'bottom-full left-1/2 -translate-x-1/2 mb-1.5',
    bottom: 'top-full left-1/2 -translate-x-1/2 mt-1.5',
    left: 'right-full top-1/2 -translate-y-1/2 mr-1.5',
    right: 'left-full top-1/2 -translate-y-1/2 ml-1.5',
  }

  return (
    <div className="relative inline-flex" onMouseEnter={show} onMouseLeave={hide} onFocus={show} onBlur={hide}>
      {children}
      {visible && (
        <div
          role="tooltip"
          className={cn(
            'absolute z-50 px-2.5 py-1.5 text-xs font-medium rounded-lg whitespace-nowrap pointer-events-none animate-fade-in',
            'bg-foreground text-background shadow-lg',
            positionClasses[side],
            className,
          )}
        >
          {content}
        </div>
      )}
    </div>
  )
}
