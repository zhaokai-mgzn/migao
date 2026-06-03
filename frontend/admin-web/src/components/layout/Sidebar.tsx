'use client'

import { useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  BarChart3,
  Package,
  Scissors,
  BookOpen,
  Settings,
  Bell,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  ClipboardList,
  Users,
  ShieldCheck,
  Building2,
  LucideIcon,
  LayoutDashboard,
  Store,
  ShoppingCart,
  UserCircle,
  Headphones,
  MessageSquare,
  Monitor,
  Zap,
  FolderTree,
} from 'lucide-react'
import { useAuthStore } from '@/store/auth'
import { cn } from '@/lib/utils'
import Logo from '@/components/ui/Logo'

// 图标映射
const iconMap: Record<string, LucideIcon> = {
  BarChart3,
  Package,
  Scissors,
  BookOpen,
  Settings,
  Bell,
  ClipboardList,
  Users,
  ShieldCheck,
  Building2,
  LayoutDashboard,
  Store,
  ShoppingCart,
  UserCircle,
  Headphones,
  MessageSquare,
  Monitor,
  Zap,
  FolderTree,
}

interface MenuItem {
  key: string
  name: string
  icon: string
  path: string
  adminOnly?: boolean
}

interface MenuGroup {
  key: string
  name: string
  icon: string
  children: MenuItem[]
}

interface SidebarProps {
  collapsed: boolean
  onToggle: () => void
}

const menuGroups: MenuGroup[] = [
  {
    key: 'workspace',
    name: '工作台',
    icon: 'LayoutDashboard',
    children: [
      { key: 'dashboard', name: '数据看板', icon: 'BarChart3', path: '/dashboard' },
    ],
  },
  {
    key: 'product-center',
    name: '商品中心',
    icon: 'Store',
    children: [
      { key: 'products', name: '商品管理', icon: 'Package', path: '/products' },
      { key: 'categories', name: '商品分类', icon: 'FolderTree', path: '/categories' },
      { key: 'processing', name: '加工项管理', icon: 'Scissors', path: '/processing' },
    ],
  },
  {
    key: 'trade-center',
    name: '交易中心',
    icon: 'ShoppingCart',
    children: [
      { key: 'orders', name: '订单管理', icon: 'ClipboardList', path: '/orders' },
      { key: 'after-sales', name: '售后管理', icon: 'ShieldCheck', path: '/after-sales' },
    ],
  },
  {
    key: 'customer-center',
    name: '客户中心',
    icon: 'UserCircle',
    children: [
      { key: 'customers', name: '客户管理', icon: 'Users', path: '/customers' },
    ],
  },
  {
    key: 'agent-center',
    name: '客服中心',
    icon: 'Headphones',
    children: [
      { key: 'agent-workspace', name: '客服工作台', icon: 'MessageSquare', path: '/agent-workspace' },
      { key: 'agent-sessions', name: '会话监控', icon: 'Monitor', path: '/agent-workspace/sessions' },
      { key: 'quick-replies', name: '快捷回复', icon: 'Zap', path: '/agent-workspace/quick-replies' },
      { key: 'employees', name: '客服团队', icon: 'Users', path: '/employees' },
    ],
  },
  {
    key: 'system',
    name: '系统管理',
    icon: 'Settings',
    children: [
      { key: 'roles', name: '角色权限', icon: 'ShieldCheck', path: '/roles', adminOnly: true },
      { key: 'notifications', name: '通知中心', icon: 'Bell', path: '/notifications' },
      { key: 'settings', name: '系统设置', icon: 'Settings', path: '/settings' },
    ],
  },
]

export default function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const pathname = usePathname()
  const { user } = useAuthStore()

  // 所有分组默认展开
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>(
    () => Object.fromEntries(menuGroups.map(g => [g.key, true]))
  )

  const toggleGroup = (key: string) => {
    setExpandedGroups(prev => ({ ...prev, [key]: !prev[key] }))
  }

  // 权限过滤
  const isAdmin = user?.roles?.includes('admin')

  const filterChildren = (children: MenuItem[]) =>
    children.filter(item => {
      if (item.adminOnly) return isAdmin
      return true
    })

  const isActive = (path: string) => {
    if (path === '/dashboard') {
      return pathname === '/dashboard' || pathname === '/'
    }
    return pathname.startsWith(path)
  }

  return (
    <aside
      className={cn(
        'fixed left-0 top-0 h-full bg-slate-900 transition-all duration-300 z-50',
        collapsed ? 'w-16' : 'w-60'
      )}
    >
      {/* Logo 区域 */}
      <div className={cn('flex items-center px-4 border-b border-slate-800', collapsed ? 'h-14 justify-center' : 'h-16 py-3')}>
        <div className="flex items-center gap-3 overflow-hidden">
          <Logo size="small" />
          {!collapsed && (
            <div className="min-w-0">
              <div className="text-white font-semibold text-sm leading-tight truncate">
                {user?.tenantName || '有客'}
              </div>
              {user?.tenantName && (
                <div className="text-slate-400 text-[11px] leading-tight mt-0.5">有客</div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* 导航菜单 */}
      <nav className="flex-1 py-2 px-2 overflow-y-auto" style={{ maxHeight: 'calc(100vh - 7rem)' }}>
        {menuGroups.map((group, groupIndex) => {
          const filteredChildren = filterChildren(group.children)
          if (filteredChildren.length === 0) return null

          const GroupIcon = iconMap[group.icon] || LayoutDashboard
          const isExpanded = expandedGroups[group.key]

          return (
            <div key={group.key} className={cn(groupIndex > 0 && 'mt-4')}>
              {/* 分组标题 */}
              {collapsed ? (
                // 收起时显示分隔线
                groupIndex > 0 && (
                  <div className="mx-2 mb-2 border-t border-slate-700" />
                )
              ) : (
                <button
                  onClick={() => toggleGroup(group.key)}
                  className="w-full flex items-center justify-between px-3 py-1.5 mb-1 group cursor-pointer"
                >
                  <div className="flex items-center gap-2">
                    <GroupIcon className="w-4 h-4 text-slate-400" />
                    <span className="text-xs text-slate-400 uppercase tracking-wider font-medium">
                      {group.name}
                    </span>
                  </div>
                  {isExpanded ? (
                    <ChevronDown className="w-3.5 h-3.5 text-slate-500 group-hover:text-slate-300 transition-colors" />
                  ) : (
                    <ChevronRight className="w-3.5 h-3.5 text-slate-500 group-hover:text-slate-300 transition-colors" />
                  )}
                </button>
              )}

              {/* 子菜单项 */}
              {(collapsed || isExpanded) && (
                <div className="space-y-0.5">
                  {filteredChildren.map((item) => {
                    const Icon = iconMap[item.icon] || BarChart3
                    const active = isActive(item.path)

                    return (
                      <Link
                        key={item.key}
                        href={item.path}
                        className={cn(
                          'flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors',
                          active
                            ? 'bg-primary-600 text-white'
                            : 'text-slate-300 hover:bg-slate-800 hover:text-white',
                          collapsed && 'justify-center px-2'
                        )}
                        title={collapsed ? item.name : undefined}
                      >
                        <Icon className="w-5 h-5 flex-shrink-0" />
                        {!collapsed && (
                          <span className="whitespace-nowrap">{item.name}</span>
                        )}
                      </Link>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}
      </nav>

      {/* 底部折叠按钮 */}
      <div className="absolute bottom-0 left-0 right-0 p-2 border-t border-slate-800">
        <button
          onClick={onToggle}
          className={cn(
            'w-full flex items-center justify-center p-2 rounded-md',
            'text-slate-400 hover:bg-slate-800 hover:text-white transition-colors',
            collapsed && 'px-2'
          )}
          title={collapsed ? '展开侧边栏' : '收起侧边栏'}
        >
          {collapsed ? (
            <ChevronRight className="w-5 h-5" />
          ) : (
            <>
              <ChevronLeft className="w-5 h-5" />
              <span className="ml-2 text-sm">收起</span>
            </>
          )}
        </button>
      </div>
    </aside>
  )
}
