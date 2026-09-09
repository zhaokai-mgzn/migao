'use client'

import { useState, useEffect } from 'react'
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
  MessageCircle,
  Bot,
  Monitor,
  FolderTree,
  Calculator,
} from 'lucide-react'
import { useAuthStore } from '@/store/auth'
import { cn } from '@/lib/utils'
import Logo from '@/components/ui/Logo'
// #3002: 菜单配置单源化 —— menuGroups/standaloneItems 移至 @/config/menu，
// 与岗位权限弹窗共用，保证「权限分配」展示的菜单与真实侧边栏一致
import { menuGroups, standaloneItems, type MenuItem, type MenuGroup } from '@/config/menu'

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
  MessageCircle,
  Bot,
  Monitor,
  FolderTree,
  Calculator,
}

interface SidebarProps {
  collapsed: boolean
  onToggle: () => void
}

export default function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const pathname = usePathname()
  const { user } = useAuthStore()

  // 企业 Logo 加载失败标记：URL 失效/过期时回退到米高默认 Logo，避免空白
  const [logoFailed, setLogoFailed] = useState(false)

  // 企业 Logo 变化时重置失败标记
  useEffect(() => {
    setLogoFailed(false)
  }, [user?.tenantLogo])

  // 所有分组默认展开
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>(
    () => Object.fromEntries(menuGroups.map(g => [g.key, true]))
  )

  const toggleGroup = (key: string) => {
    setExpandedGroups(prev => ({ ...prev, [key]: !prev[key] }))
  }

  // 权限过滤
  const permissions = user?.permissions || []
  const hasAllPermissions = permissions.includes('*')

  const hasPermission = (code?: string) => {
    if (!code) return true              // 无权限码 = 所有人可见
    if (hasAllPermissions) return true   // admin (*) 通配符
    return permissions.includes(code)
  }

  const filterItems = (items: MenuItem[]) =>
    items.filter(item => {
      // adminOnly 保留作为额外防线
      if (item.adminOnly && !user?.roles?.includes('admin')) return false
      return hasPermission(item.permissionCode)
    })

  // 激活判定：前缀匹配（'/chat' 命中 '/chat' 自身）+ 最长前缀互斥单高亮。
  // 规则：当前路由在所有可见菜单项中只激活「最长匹配路径」的那一项。
  const matchesRoute = (itemPath: string, current: string) => {
    if (itemPath === '/dashboard') {
      return current === '/dashboard' || current === '/'
    }
    return current === itemPath || current.startsWith(itemPath + '/')
  }

  const activePath = (() => {
    const allPaths = [
      ...menuGroups.flatMap((g) => filterItems(g.children).map((i) => i.path)),
      ...filterItems(standaloneItems).map((i) => i.path),
    ]
    const hits = allPaths.filter((p) => matchesRoute(p, pathname))
    if (hits.length === 0) return null
    // 最长前缀胜出（路径互异，长度相同不可能同时命中）
    return hits.reduce((a, b) => (b.length > a.length ? b : a))
  })()

  const isActive = (path: string) => activePath === path

  return (
    <aside
      className={cn(
        'fixed left-0 top-0 h-full bg-[#171e30] transition-all duration-300 z-50',
        collapsed ? 'w-16' : 'w-60'
      )}
    >
      {/* Logo 区域 */}
      <div className={cn('flex items-center border-b border-white/5', collapsed ? 'h-14 justify-center' : 'h-16 py-3 px-4')}>
        <div className="flex items-center gap-3 overflow-hidden">
          {/* 企业 Logo（「企业基础信息」设置）优先，未设置或加载失败时回退米高默认 Logo */}
          {user?.tenantLogo && !logoFailed ? (
            <img
              src={user.tenantLogo}
              alt="企业 Logo"
              className="h-8 w-8 rounded-lg object-cover flex-shrink-0"
              onError={() => setLogoFailed(true)}
            />
          ) : (
            <Logo size="small" />
          )}
          {!collapsed && (
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold leading-tight text-white">
                {user?.tenantName || '米高'}
              </div>
              {user?.tenantName && (
                <div className="mt-0.5 text-[11px] leading-tight text-neutral-400">米高商家管理后台</div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* 导航菜单 */}
      <nav className="flex-1 py-2 px-2 overflow-y-auto" style={{ maxHeight: 'calc(100vh - 7rem)' }}>

        {/* 带子级的菜单组 */}
        {collapsed && <div className="mx-2 mb-3 border-t border-white/10" />}
        {menuGroups.map((group) => {
          const filteredChildren = filterItems(group.children)
          if (filteredChildren.length === 0) return null

          const GroupIcon = iconMap[group.icon] || LayoutDashboard
          const isExpanded = expandedGroups[group.key]

          return (
            <div key={group.key} className="mb-4">
              {/* 分组标题 */}
              {collapsed ? (
                <div className="mx-2 mb-1 border-t border-white/10" />
              ) : (
                <button
                  onClick={() => toggleGroup(group.key)}
                  className="group mb-1 flex w-full cursor-pointer items-center justify-between px-3 py-1"
                >
                  <div className="flex items-center gap-2">
                    <GroupIcon className="h-4 w-4 text-neutral-500 transition-colors group-hover:text-neutral-300" />
                    <span className="text-[11px] font-medium uppercase tracking-[0.14em] text-neutral-500 transition-colors group-hover:text-neutral-300">
                      {group.name}
                    </span>
                  </div>
                  {isExpanded ? (
                    <ChevronDown className="h-3.5 w-3.5 text-neutral-600 transition-colors group-hover:text-neutral-300" />
                  ) : (
                    <ChevronRight className="h-3.5 w-3.5 text-neutral-600 transition-colors group-hover:text-neutral-300" />
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
                          'relative flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors',
                          active
                            ? 'bg-primary-600 text-white shadow-sm'
                            : 'text-neutral-300 hover:bg-white/5 hover:text-white',
                          collapsed && 'justify-center px-2'
                        )}
                        title={collapsed ? item.name : undefined}
                      >
                        {active && (
                          <span className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-white/90" />
                        )}
                        <Icon className="h-5 w-5 flex-shrink-0" />
                        {!collapsed && <span className="whitespace-nowrap">{item.name}</span>}
                      </Link>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}

        {/* 一级独立菜单项 */}
        {collapsed && <div className="mx-2 mb-3 border-t border-white/10" />}
        <div className="space-y-0.5">
          {filterItems(standaloneItems).map((item) => {
            const Icon = iconMap[item.icon] || LayoutDashboard
            const active = isActive(item.path)
            return (
              <Link
                key={item.key}
                href={item.path}
                className={cn(
                  'relative flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors',
                  active
                    ? 'bg-primary-600 text-white shadow-sm'
                    : 'text-neutral-300 hover:bg-white/5 hover:text-white',
                  collapsed && 'justify-center px-2'
                )}
                title={collapsed ? item.name : undefined}
              >
                {active && (
                  <span className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-white/90" />
                )}
                <Icon className="h-5 w-5 flex-shrink-0" />
                {!collapsed && <span className="whitespace-nowrap">{item.name}</span>}
              </Link>
            )
          })}
        </div>
      </nav>

      {/* 底部折叠按钮 */}
      <div className="absolute bottom-0 left-0 right-0 border-t border-white/5 p-2">
        <button
          onClick={onToggle}
          className={cn(
            'flex w-full items-center justify-center rounded-md p-2 transition-colors',
            'text-neutral-500 hover:bg-white/5 hover:text-white',
            collapsed && 'px-2'
          )}
          title={collapsed ? '展开侧边栏' : '收起侧边栏'}
        >
          {collapsed ? (
            <ChevronRight className="h-5 w-5" />
          ) : (
            <>
              <ChevronLeft className="h-5 w-5" />
              <span className="ml-2 text-sm">收起</span>
            </>
          )}
        </button>
      </div>
    </aside>
  )
}
