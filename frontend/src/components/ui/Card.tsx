import { cn } from '@/lib/utils'

type Variant = 'default' | 'outlined' | 'elevated' | 'glass'

interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: Variant
}

const variantStyles: Record<Variant, string> = {
  default: 'bg-card border border-border/50',
  outlined: 'bg-transparent border border-border/60',
  elevated: 'bg-card border border-border/30 shadow-md',
  glass: 'bg-card/60 backdrop-blur-xl border border-border/40',
}

export function Card({ variant = 'default', className, children, ...props }: CardProps) {
  return (
    <div className={cn('rounded-xl transition-colors', variantStyles[variant], className)} {...props}>
      {children}
    </div>
  )
}

export function CardHeader({ className, children, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('px-5 pt-5 pb-2', className)} {...props}>{children}</div>
}

export function CardContent({ className, children, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('px-5 pb-5', className)} {...props}>{children}</div>
}

export function CardTitle({ className, children, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h3 className={cn('text-base font-semibold tracking-tight', className)} {...props}>{children}</h3>
}

export function CardDescription({ className, children, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn('text-sm text-muted-foreground', className)} {...props}>{children}</p>
}
