'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { ChevronLeft, ChevronRight, Search } from 'lucide-react'
import { useAuthStore } from '@/store/auth'
import { cn } from '@/lib/utils'
import Logo from '@/components/ui/Logo'
// #3002: 菜单配置单源化 —— menuGroups/standaloneItems 移至 @/config/menu，
// 与岗位权限弹窗共用，保证「权限分配」展示的菜单与真实侧边栏一致
import { menuGroups, standaloneItems, type MenuItem } from '@/config/menu'
// issue #5271: 图标注册表独立成模块 —— 原内联 `iconMap[...] || BarChart3` 的静默回落
// 现在有判据（tests/unit/lib/menu-icons.test.ts）
import { resolveMenuIcon } from '@/config/menu-icons'
// issue #5271: 过滤/高亮/搜索/展开判定抽成纯函数（可对「全部菜单项 × 全部路由」穷举断言）
import {
  filterMenuItems,
  visibleMenuGroups,
  resolveActivePath,
  resolveActiveGroupKey,
  initialExpandedGroups,
} from '@/lib/menu-nav'
import { briefingApi } from '@/lib/api'

interface SidebarProps {
  collapsed: boolean
  onToggle: () => void
  /** 移动端抽屉是否展开（issue #5271）；桌面端忽略此值 */
  mobileOpen?: boolean
  /** 移动端点击遮罩/菜单项后关闭抽屉（issue #5271） */
  onMobileClose?: () => void
  /** 打开命令面板（⌘K，issue #5271） */
  onOpenSearch?: () => void
}

/**
 * 侧边栏（issue #5271 重设计）。
 *
 * ## 四项交互（用户 2026-09-23 裁定）
 *
 *   ① **分组默认只展开「当前路由所在组」** —— 21 项不再一次全摊开；组标题带项数徽标，
 *      「东西没丢」一眼可见；找不到就用 ⌘K；
 *   ② **高亮自动展开所在组** —— 路由变化 ⇒ 自动展开该组（用户手动展开的其它组不受影响；
 *      手动**收起**当前组后不会被立刻顶开，见下方 effect 的收敛条件）；
 *   ③ **折叠态分组可见** —— 图标栏仍按组渲染「组图标 + 分隔线」锚点（`title` = 组名），
 *      不再是重设计前那种「一根分隔线、分组信息全丢」；
 *   ④ **移动端抽屉** —— 小屏是浮层（`-translate-x-full` / `translate-x-0`）+ 遮罩，
 *      桌面端才是常驻栏（`lg:translate-x-0`）⇒ 不再恒宽挤压内容区。
 *
 * ## 视觉
 *
 *   组标题去掉 `uppercase`（对中文完全无效）与叠在标题上的第二个图标；
 *   折叠指示由「换图标」改为**同一 chevron 旋转**（状态变化更连续）。
 */
export default function Sidebar({
  collapsed,
  onToggle,
  mobileOpen = false,
  onMobileClose,
  onOpenSearch,
}: SidebarProps) {
  const pathname = usePathname()
  const { user } = useAuthStore()

  // 企业 Logo 加载失败标记：URL 失效/过期时回退到米高默认 Logo，避免空白
  const [logoFailed, setLogoFailed] = useState(false)

  // 企业 Logo 变化时重置失败标记
  useEffect(() => {
    setLogoFailed(false)
  }, [user?.tenantLogo])

  // 智能每日经营简报企业开关（issue #3468）：开关关闭 → 菜单隐藏（红线 3）
  const [briefingEnabled, setBriefingEnabled] = useState(false)
  useEffect(() => {
    briefingApi.getConfig()
      .then((res) => setBriefingEnabled(!!res.data.data?.enabled))
      .catch(() => setBriefingEnabled(false))
  }, [])

  // ── 权限过滤（纯函数，issue #5271）──
  const filterOpts = { permissions: user?.permissions || [], roles: user?.roles, briefingEnabled }
  const groups = visibleMenuGroups(menuGroups, filterOpts)
  const standalone = filterMenuItems(standaloneItems, filterOpts)

  // ── 高亮：最长前缀胜出（沿用重设计前的口径）──
  const activePath = resolveActivePath(
    [
      ...groups.flatMap((g) => g.children.map((i) => i.path)),
      ...standalone.map((i) => i.path),
    ],
    pathname,
  )
  const isActive = (path: string) => activePath === path

  const activeGroupKey = resolveActiveGroupKey(groups, pathname)

  // ── 分组展开态：初值 = 只展开当前所在组；路由变化 ⇒ 自动展开新所在组 ──
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>(() =>
    initialExpandedGroups(groups, activeGroupKey),
  )

  useEffect(() => {
    if (!activeGroupKey) return
    // 收敛条件：已展开则该引用原样返回（不触发重渲染）；用户手动收起后不会被反复顶开
    setExpandedGroups((prev) => (prev[activeGroupKey] ? prev : { ...prev, [activeGroupKey]: true }))
  }, [activeGroupKey])

  const toggleGroup = (key: string) => {
    setExpandedGroups((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  return (
    <aside
      data-testid="sidebar"
      className={cn(
        'fixed left-0 top-0 z-50 flex h-full w-60 flex-col bg-[#171e30] transition-transform duration-300',
        collapsed ? 'lg:w-16' : 'lg:w-60',
        // 移动端抽屉：默认藏在屏幕左侧外；桌面端恒在左侧
        mobileOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0',
      )}
    >
      {/* Logo 区域 */}
      <div className={cn('flex items-center border-b border-white/5', collapsed ? 'h-14 justify-center' : 'h-16 py-3 px-4')}>
        <div className="flex items-center gap-3 overflow-hidden">
          {/* 企业 Logo（「企业基础信息」设置）优先，未设置或加载失败时回退米高默认 Logo */}
          {user?.tenantLogo && !logoFailed ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={user.tenantLogo}
              alt="企业 Logo"
              className="h-8 w-8 flex-shrink-0 rounded-lg object-cover"
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

      {/* 菜单搜索入口（⌘K，issue #5271）—— 21 项不再靠眼扫 */}
      {collapsed ? (
        <button
          type="button"
          data-testid="sidebar-search-trigger"
          onClick={onOpenSearch}
          title="搜索菜单"
          className="mx-auto my-2 flex h-9 w-9 items-center justify-center rounded-lg text-neutral-400 transition-colors hover:bg-white/5 hover:text-white"
        >
          <Search className="h-4 w-4" />
        </button>
      ) : (
        <button
          type="button"
          data-testid="sidebar-search-trigger"
          onClick={onOpenSearch}
          className="mx-3 my-2 flex items-center gap-2 rounded-lg bg-white/5 px-3 py-2 text-xs text-neutral-400 transition-colors hover:bg-white/10 hover:text-white"
        >
          <Search className="h-3.5 w-3.5" />
          <span className="flex-1 text-left">搜索菜单</span>
          <kbd className="rounded border border-white/10 px-1.5 py-0.5 text-[10px] text-neutral-500">⌘K</kbd>
        </button>
      )}

      {/* 导航菜单 */}
      <nav className="flex-1 overflow-y-auto px-2 py-1">
        {groups.map((group) => {
          const GroupIcon = resolveMenuIcon(group.icon)
          const isExpanded = !!expandedGroups[group.key]

          return (
            <div key={group.key} data-group-key={group.key} className="mb-4">
              {collapsed ? (
                // 折叠态：分组信息**不再丢失** —— 组图标锚点（title = 组名）+ 细分割线
                <div
                  data-testid={`sidebar-group-anchor-${group.key}`}
                  title={group.name}
                  className="mb-1 flex flex-col items-center gap-1 pt-2"
                >
                  <span className="h-px w-6 bg-white/10" />
                  <GroupIcon className="h-3.5 w-3.5 text-neutral-500" />
                </div>
              ) : (
                <button
                  type="button"
                  data-testid={`sidebar-group-toggle-${group.key}`}
                  aria-expanded={isExpanded}
                  onClick={() => toggleGroup(group.key)}
                  className="group mb-1 flex w-full cursor-pointer items-center gap-2 rounded-md px-3 py-1.5 text-left transition-colors hover:bg-white/5"
                >
                  <GroupIcon className="h-3.5 w-3.5 flex-shrink-0 text-neutral-500 transition-colors group-hover:text-neutral-300" />
                  <span className="flex-1 text-xs font-medium tracking-wide text-neutral-400 transition-colors group-hover:text-neutral-200">
                    {group.name}
                  </span>
                  {/* 项数徽标：收起时也知道组里有几项（「东西没丢」） */}
                  <span className="rounded bg-white/5 px-1.5 py-0.5 text-[10px] leading-none text-neutral-500">
                    {group.children.length}
                  </span>
                  <ChevronRight
                    className={cn(
                      'h-3.5 w-3.5 flex-shrink-0 text-neutral-600 transition-transform group-hover:text-neutral-300',
                      isExpanded && 'rotate-90',
                    )}
                  />
                </button>
              )}

              {(collapsed || isExpanded) && (
                <div className="space-y-0.5">
                  {group.children.map((item: MenuItem) => {
                    const Icon = resolveMenuIcon(item.icon)
                    const active = isActive(item.path)
                    return (
                      <Link
                        key={item.key}
                        href={item.path}
                        onClick={onMobileClose}
                        data-menu-key={item.key}
                        className={cn(
                          'relative flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors',
                          active
                            ? 'bg-primary-600 text-white shadow-sm'
                            : 'text-neutral-300 hover:bg-white/5 hover:text-white',
                          collapsed && 'justify-center px-2',
                        )}
                        title={collapsed ? item.name : undefined}
                      >
                        {active && (
                          <span className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-white/90" />
                        )}
                        <Icon className="h-5 w-5 flex-shrink-0" />
                        {!collapsed && <span className="truncate">{item.name}</span>}
                      </Link>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}

        {/* 一级独立菜单项 */}
        {standalone.length > 0 && !collapsed && (
          <div className="my-2 border-t border-white/5" />
        )}
        <div className="space-y-0.5">
          {standalone.map((item) => {
            const Icon = resolveMenuIcon(item.icon)
            const active = isActive(item.path)
            return (
              <Link
                key={item.key}
                href={item.path}
                onClick={onMobileClose}
                data-menu-key={item.key}
                className={cn(
                  'relative flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors',
                  active
                    ? 'bg-primary-600 text-white shadow-sm'
                    : 'text-neutral-300 hover:bg-white/5 hover:text-white',
                  collapsed && 'justify-center px-2',
                )}
                title={collapsed ? item.name : undefined}
              >
                {active && (
                  <span className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-white/90" />
                )}
                <Icon className="h-5 w-5 flex-shrink-0" />
                {!collapsed && <span className="truncate">{item.name}</span>}
              </Link>
            )
          })}
        </div>
      </nav>

      {/* 底部折叠按钮（桌面端）—— 移动端抽屉另有「关闭」语义，由遮罩承担 */}
      <div className="border-t border-white/5 p-2">
        <button
          type="button"
          onClick={onToggle}
          className={cn(
            'hidden w-full items-center justify-center rounded-md p-2 transition-colors lg:flex',
            'text-neutral-500 hover:bg-white/5 hover:text-white',
            collapsed && 'px-2',
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