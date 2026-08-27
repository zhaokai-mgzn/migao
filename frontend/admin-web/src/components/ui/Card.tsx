import { cn } from '@/lib/utils'

interface CardProps {
  children: React.ReactNode
  className?: string
}

export default function Card({ children, className }: CardProps) {
  return (
    <div className={cn('bg-white rounded-xl shadow-card border border-neutral-200', className)}>
      {children}
    </div>
  )
}
