import { type ReactNode } from 'react'
import { cn } from '@/lib/utils'

interface Tab {
  key: string
  label: string
  icon?: React.ComponentType<{ className?: string }>
}

interface TabsProps {
  tabs: Tab[]
  activeKey: string
  onChange: (key: string) => void
  className?: string
  variant?: 'underline' | 'pill'
}

export function Tabs({ tabs, activeKey, onChange, className, variant = 'underline' }: TabsProps) {
  if (variant === 'pill') {
    return (
      <div className={cn('flex gap-1 p-1 rounded-xl bg-muted/50', className)}>
        {tabs.map((tab) => {
          const Icon = tab.icon
          return (
            <button
              key={tab.key}
              onClick={() => onChange(tab.key)}
              className={cn(
                'flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-all duration-200',
                activeKey === tab.key
                  ? 'bg-card text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {Icon && <Icon className="w-3.5 h-3.5" />}
              {tab.label}
            </button>
          )
        })}
      </div>
    )
  }

  return (
    <div className={cn('flex border-b border-border/50 overflow-x-auto', className)}>
      {tabs.map((tab) => {
        const Icon = tab.icon
        return (
          <button
            key={tab.key}
            onClick={() => onChange(tab.key)}
            className={cn(
              'shrink-0 flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium transition-all duration-200 border-b-2',
              activeKey === tab.key
                ? 'text-primary border-primary'
                : 'text-muted-foreground border-transparent hover:text-foreground hover:border-border',
            )}
          >
            {Icon && <Icon className="w-4 h-4" />}
            {tab.label}
          </button>
        )
      })}
    </div>
  )
}

interface TabPanelProps {
  active: boolean
  children: ReactNode
  className?: string
}

export function TabPanel({ active, children, className }: TabPanelProps) {
  if (!active) return null
  return <div className={cn('animate-fade-in', className)}>{children}</div>
}
