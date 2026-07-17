'use client'

import { cn } from '@/lib/utils'

interface StatusBadgeProps {
  /** 显示文本 */
  label: string
  /** Tailwind 颜色类名，如 'bg-amber-50 text-amber-700 border-amber-200' */
  color: string
  /** 是否显示左侧小圆点 */
  dot?: boolean
  className?: string
  onClick?: () => void
}

const StatusBadge = ({ label, color, dot = false, className, onClick }: StatusBadgeProps) => {
  return (
    <span
      onClick={onClick}
      title={label}
      className={cn(
        'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium border whitespace-nowrap truncate',
        onClick && 'cursor-pointer hover:opacity-80 transition-opacity',
        color,
        className
      )}
    >
      {dot && <span className="w-1.5 h-1.5 rounded-full flex-shrink-0 bg-current opacity-60" />}
      {label}
    </span>
  )
}

export default StatusBadge
