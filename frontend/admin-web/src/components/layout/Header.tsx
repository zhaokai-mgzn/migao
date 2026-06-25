'use client'

import { useRouter, usePathname } from 'next/navigation'
import {
  User,
  LogOut,
  ChevronDown,
  Settings,
} from 'lucide-react'
import { useAuthStore } from '@/store/auth'
import { cn } from '@/lib/utils'
import NotificationBell from './NotificationBell'

interface HeaderProps {
  title?: string
  breadcrumbs?: { label: string; href?: string }[]
}

// 路由 → 面包屑映射（与侧边栏菜单结构对齐）
// 顺序敏感：更具体的子路径放在前面，避免被父路径前缀匹配
const ROUTE_BREADCRUMB_MAP: Array<{
  match: (path: string) => boolean
  crumbs: { label: string; href?: string }[]
}> = [
  // 工作台
  { match: (p) => p === '/' || p === '/dashboard', crumbs: [{ label: '工作台', href: '/dashboard' }, { label: '数据看板' }] },

  // 商品管理（与侧边栏"商品管理"分组对齐）
  { match: (p) => p.startsWith('/products'), crumbs: [{ label: '商品管理' }, { label: '商品列表' }] },
  { match: (p) => p.startsWith('/categories'), crumbs: [{ label: '商品管理' }, { label: '商品分类管理' }] },
  { match: (p) => p.startsWith('/processing'), crumbs: [{ label: '商品管理' }, { label: '加工项管理' }] },
  { match: (p) => p.startsWith('/knowledge'), crumbs: [{ label: '商品管理' }, { label: '知识库管理' }] },

  // 订单管理（与侧边栏"订单管理"分组对齐）
  { match: (p) => p.startsWith('/orders'), crumbs: [{ label: '订单管理' }, { label: '订单列表' }] },
  { match: (p) => p.startsWith('/after-sales'), crumbs: [{ label: '订单管理' }, { label: '售后工单' }] },

  // 客服中心 — 子路由优先
  { match: (p) => p.startsWith('/agent-workspace/sessions'), crumbs: [{ label: '客服中心' }, { label: '会话监控' }] },
  { match: (p) => p.startsWith('/agent-workspace/quick-replies'), crumbs: [{ label: '客服中心' }, { label: '快捷回复' }] },
  { match: (p) => p.startsWith('/agent-workspace'), crumbs: [{ label: '客服中心' }, { label: '客服工作台' }] },
  { match: (p) => p.startsWith('/chat/config'), crumbs: [{ label: '机器人设置' }] },
  { match: (p) => p.startsWith('/chat'), crumbs: [{ label: '客服中心' }, { label: '在线对话' }] },

  // 系统管理（不在侧边栏主菜单，但在通知/角色页面使用）
  { match: (p) => p.startsWith('/roles'), crumbs: [{ label: '系统管理' }, { label: '角色权限' }] },
  { match: (p) => p.startsWith('/notifications'), crumbs: [{ label: '系统管理' }, { label: '通知中心' }] },

  // 侧边栏独立菜单项（单级面包屑，名称与侧边栏严格一致）
  { match: (p) => p.startsWith('/customers'), crumbs: [{ label: '客户管理' }] },
  { match: (p) => p.startsWith('/finance'), crumbs: [{ label: '财务对账' }] },
  { match: (p) => p.startsWith('/employees'), crumbs: [{ label: '员工管理' }] },
  { match: (p) => p.startsWith('/settings'), crumbs: [{ label: '企业基础信息' }] },
]

function resolveBreadcrumbs(pathname: string | null): { label: string; href?: string }[] {
  if (!pathname) return [{ label: '数据看板' }]
  const matched = ROUTE_BREADCRUMB_MAP.find((m) => m.match(pathname))
  return matched ? matched.crumbs : [{ label: '工作台', href: '/dashboard' }]
}

export default function Header({ title, breadcrumbs }: HeaderProps) {
  const router = useRouter()
  const pathname = usePathname()
  const { user, logout } = useAuthStore()

  const handleLogout = async () => {
    await logout()
    router.push('/login')
  }

  // 优先级：显式 breadcrumbs > 显式 title > 基于路由的动态面包屑
  const resolvedBreadcrumbs = breadcrumbs ?? (title ? null : resolveBreadcrumbs(pathname))
  const pageTitle = title || resolvedBreadcrumbs?.[resolvedBreadcrumbs.length - 1]?.label || '数据看板'

  return (
    <header className="h-14 bg-white border-b border-gray-200 flex items-center justify-between px-6 sticky top-0 z-40">
      {/* 左侧：面包屑 / 页面标题 */}
      <div className="flex items-center">
        {resolvedBreadcrumbs ? (
          <nav className="flex items-center text-sm">
            {resolvedBreadcrumbs.map((crumb, index) => {
              const isLast = index === resolvedBreadcrumbs.length - 1
              return (
                <div key={`${crumb.label}-${index}`} className="flex items-center">
                  {index > 0 && (
                    <span className="mx-2 text-gray-400">/</span>
                  )}
                  {crumb.href && !isLast ? (
                    <a
                      href={crumb.href}
                      className="text-gray-500 hover:text-primary-600 transition-colors"
                    >
                      {crumb.label}
                    </a>
                  ) : (
                    <span
                      className={cn(
                        isLast
                          ? 'text-gray-900 font-medium'
                          : 'text-gray-500'
                      )}
                    >
                      {crumb.label}
                    </span>
                  )}
                </div>
              )
            })}
          </nav>
        ) : (
          <h1 className="text-base font-medium text-gray-900">{pageTitle}</h1>
        )}
      </div>

      {/* 右侧：通知 + 用户信息 */}
      <div className="flex items-center gap-4">
        {/* 通知铃铛 */}
        <NotificationBell />

        {/* 用户下拉菜单 */}
        <div className="relative group">
          <button className="flex items-center gap-2 p-1.5 pr-3 rounded-lg hover:bg-gray-100 transition-colors">
            {/* 头像 */}
            <div className="w-8 h-8 bg-primary-100 rounded-full flex items-center justify-center">
              <User className="w-4 h-4 text-primary-600" />
            </div>
            {/* 昵称 */}
            <span className="text-sm text-gray-700 hidden sm:block">
              {user?.name || user?.nickname || user?.username || '管理员'}
            </span>
            <ChevronDown className="w-4 h-4 text-gray-400 hidden sm:block" />
          </button>

          {/* 下拉菜单 */}
          <div className={cn(
            'absolute right-0 top-full mt-1 w-48 py-1',
            'bg-white rounded-lg shadow-card border border-gray-100',
            'opacity-0 invisible group-hover:opacity-100 group-hover:visible',
            'transition-all duration-200'
          )}>
            <div className="px-4 py-2 border-b border-gray-100">
              <p className="text-sm font-medium text-gray-900">
                {user?.name || user?.nickname || user?.username || '管理员'}
              </p>
              <p className="text-xs text-gray-500">
                {user?.email || user?.username || ''}
              </p>
            </div>
            {user?.roles?.includes('super_admin') && (
              <a
                href="https://ops.migaozn.com"
                target="_blank"
                rel="noopener noreferrer"
                className="w-full flex items-center gap-2 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
              >
                <Settings className="w-4 h-4" />
                平台管理
              </a>
            )}
            <button
              onClick={handleLogout}
              className="w-full flex items-center gap-2 px-4 py-2 text-sm text-red-600 hover:bg-red-50 transition-colors"
            >
              <LogOut className="w-4 h-4" />
              退出登录
            </button>
          </div>
        </div>
      </div>
    </header>
  )
}
