'use client'

import { cn } from '@/lib/utils'

interface BadgeProps {
  children: React.ReactNode
  variant?: 'success' | 'warning' | 'error' | 'default' | 'danger' | 'info'
  className?: string
  onClick?: () => void
  /** hover tooltip 完整文本，默认取 children 字符串 */
  title?: string
}

const Badge = ({ children, variant = 'default', className, onClick, title }: BadgeProps) => {
  const variants = {
    success: 'bg-green-50 text-green-700 border-green-200',
    warning: 'bg-amber-50 text-amber-700 border-amber-200',
    error: 'bg-red-50 text-red-700 border-red-200',
    danger: 'bg-red-50 text-red-700 border-red-200',
    info: 'bg-blue-50 text-blue-700 border-blue-200',
    default: 'bg-gray-50 text-gray-700 border-gray-200',
  }

  // 提取 children 中的文本作为默认 tooltip
  const badgeTitle = title ?? (typeof children === 'string' ? children : undefined)

  return (
    <span
      onClick={onClick}
      title={badgeTitle}
      className={cn(
        'inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border whitespace-nowrap truncate',
        onClick && 'cursor-pointer',
        variants[variant],
        className
      )}
    >
      {children}
    </span>
  )
}

export default Badge
