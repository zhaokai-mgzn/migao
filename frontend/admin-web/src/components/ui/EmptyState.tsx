'use client'

import { Package, Search, FileX, Inbox } from 'lucide-react'
import { cn } from '@/lib/utils'

interface EmptyStateProps {
  title?: string
  description?: string
  icon?: 'package' | 'search' | 'file' | 'inbox'
  action?: React.ReactNode
  className?: string
}

const iconMap = {
  package: Package,
  search: Search,
  file: FileX,
  inbox: Inbox,
}

const EmptyState = ({
  title = '暂无数据',
  description = '当前列表为空',
  icon = 'inbox',
  action,
  className,
}: EmptyStateProps) => {
  const Icon = iconMap[icon]

  return (
    <div className={cn('flex flex-col items-center justify-center py-12 px-4', className)}>
      <div className="w-16 h-16 bg-gray-100 rounded-full flex items-center justify-center mb-4">
        <Icon className="w-8 h-8 text-gray-400" />
      </div>
      <h3 className="text-base font-medium text-gray-900 mb-1">{title}</h3>
      <p className="text-sm text-gray-500 text-center max-w-xs mb-4">{description}</p>
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

export default EmptyState
