'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { ClipboardCheck, LayoutDashboard } from 'lucide-react'
import { cn } from '@/lib/utils'
import Logo from '@/components/ui/Logo'

const menuItems = [
  {
    name: '入驻审批',
    href: '/registrations',
    icon: ClipboardCheck,
  },
  {
    name: '平台概览',
    href: '/platform-dashboard',
    icon: LayoutDashboard,
    badge: '即将上线',
  },
  // 未来扩展预留：
  // { name: '租户管理', href: '/tenants', icon: Building2 },
  // { name: '平台设置', href: '/platform-settings', icon: Settings },
]

export default function PlatformSidebar() {
  const pathname = usePathname()

  const isActive = (href: string) => {
    return pathname === href || pathname.startsWith(href + '/')
  }

  return (
    <aside className="fixed left-0 top-16 bottom-0 w-60 bg-white border-r border-gray-200 z-40 flex flex-col">
      {/* Logo / 标题区域 */}
      <div className="px-5 py-5 border-b border-gray-100">
        <div className="flex items-center gap-2.5">
          <Logo size="small" />
          <div>
            <h2 className="text-sm font-semibold text-gray-900 leading-tight">
              米高
            </h2>
            <p className="text-xs text-gray-500 leading-tight">
              平台管理
            </p>
          </div>
        </div>
      </div>

      {/* 导航菜单 */}
      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        {menuItems.map((item) => {
          const Icon = item.icon
          const active = isActive(item.href)

          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors group',
                active
                  ? 'bg-blue-50 text-blue-700'
                  : 'text-gray-600 hover:text-gray-900 hover:bg-gray-50'
              )}
            >
              <Icon
                className={cn(
                  'w-5 h-5 shrink-0 transition-colors',
                  active ? 'text-blue-600' : 'text-gray-400 group-hover:text-gray-600'
                )}
              />
              <span className="flex-1">{item.name}</span>
              {item.badge && (
                <span className="px-1.5 py-0.5 text-[10px] font-medium leading-none rounded bg-amber-100 text-amber-700">
                  {item.badge}
                </span>
              )}
            </Link>
          )
        })}
      </nav>

      {/* 底部信息 */}
      <div className="px-5 py-4 border-t border-gray-100">
        <p className="text-xs text-gray-400">超级管理员专属</p>
      </div>
    </aside>
  )
}
