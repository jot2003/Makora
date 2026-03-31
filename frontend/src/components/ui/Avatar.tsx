import { cn } from '@/lib/utils'

const SPEAKER_COLORS = [
  'bg-blue-500/15 text-blue-600 dark:text-blue-400',
  'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400',
  'bg-violet-500/15 text-violet-600 dark:text-violet-400',
  'bg-amber-500/15 text-amber-600 dark:text-amber-400',
  'bg-rose-500/15 text-rose-600 dark:text-rose-400',
  'bg-cyan-500/15 text-cyan-600 dark:text-cyan-400',
]

const SPEAKER_BORDER_COLORS = [
  'border-blue-500/30',
  'border-emerald-500/30',
  'border-violet-500/30',
  'border-amber-500/30',
  'border-rose-500/30',
  'border-cyan-500/30',
]

function colorIndex(name: string): number {
  let hash = 0
  for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash)
  return Math.abs(hash) % SPEAKER_COLORS.length
}

interface AvatarProps {
  name: string
  src?: string | null
  size?: 'xs' | 'sm' | 'md' | 'lg'
  isMe?: boolean
  className?: string
}

const sizes = {
  xs: 'w-5 h-5 text-[9px]',
  sm: 'w-7 h-7 text-[10px]',
  md: 'w-8 h-8 text-xs',
  lg: 'w-10 h-10 text-sm',
}

export function Avatar({ name, src, size = 'sm', isMe, className }: AvatarProps) {
  const initials = name.slice(0, 2).toUpperCase()
  const idx = isMe ? 1 : colorIndex(name)
  const colorClass = isMe ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400' : SPEAKER_COLORS[idx]

  if (src) {
    return <img src={src} alt={name} className={cn('rounded-full object-cover', sizes[size], className)} />
  }

  return (
    <div className={cn('rounded-full flex items-center justify-center font-bold shrink-0', sizes[size], colorClass, className)}>
      {initials}
    </div>
  )
}

export function getSpeakerBorderColor(name: string, isMe?: boolean): string {
  if (isMe) return 'border-emerald-500/30'
  return SPEAKER_BORDER_COLORS[colorIndex(name)]
}

export function getSpeakerColor(name: string, isMe?: boolean): string {
  if (isMe) return SPEAKER_COLORS[1]
  return SPEAKER_COLORS[colorIndex(name)]
}
