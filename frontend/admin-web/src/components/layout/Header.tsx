'use client'

import { useState } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import {
  User,
  LogOut,
  ChevronDown,
  Phone,
  Briefcase,
  Building2,
} from 'lucide-react'
import { useAuthStore } from '@/store/auth'
import { cn } from '@/lib/utils'
import NotificationBell from './NotificationBell'

interface HeaderProps {
  title?: string
  breadcrumbs?: { label: string; href?: string }[]
}

// 路由 → 面包屑映射（与侧边栏菜单结构对齐 — #2969 七大组）
// 顺序敏感：更具体的子路径放在前面，避免被父路径前缀匹配
const ROUTE_BREADCRUMB_MAP: Array<{
  match: (path: string) => boolean
  crumbs: { label: string; href?: string }[]
}> = [
  // 工作台
  { match: (p) => p === '/' || p === '/dashboard', crumbs: [{ label: '工作台', href: '/dashboard' }, { label: '经营看板' }] },

  // 智能客服组（与侧边栏"智能客服"分组对齐，#2969 知识库归入本组）
  { match: (p) => p.startsWith('/chat'), crumbs: [{ label: '智能客服' }, { label: '米宝 · 在线对话' }] },
  { match: (p) => p.startsWith('/agent-workspace/human-sessions'), crumbs: [{ label: '智能客服' }, { label: '在线接待' }] },
  { match: (p) => p.startsWith('/agent-workspace/sessions'), crumbs: [{ label: '智能客服' }, { label: '会话监控' }] },
  { match: (p) => p.startsWith('/agent-workspace'), crumbs: [{ label: '智能客服' }, { label: '客服工作台' }] },
  { match: (p) => p.startsWith('/knowledge'), crumbs: [{ label: '智能客服' }, { label: '知识库' }] },

  // 商品管理（与侧边栏"商品管理"分组对齐）
  { match: (p) => p.startsWith('/products'), crumbs: [{ label: '商品管理' }, { label: '商品列表' }] },
  { match: (p) => p.startsWith('/categories'), crumbs: [{ label: '商品管理' }, { label: '商品分类管理' }] },
  { match: (p) => p.startsWith('/processing'), crumbs: [{ label: '商品管理' }, { label: '加工项管理' }] },

  // 订单管理（与侧边栏"订单管理"分组对齐）
  { match: (p) => p.startsWith('/orders'), crumbs: [{ label: '订单管理' }, { label: '订单列表' }] },
  { match: (p) => p.startsWith('/after-sales'), crumbs: [{ label: '订单管理' }, { label: '售后工单' }] },

  // 客户管理组（与侧边栏"客户管理"分组对齐，#2969 财务对账归入本组）
  { match: (p) => p.startsWith('/customers'), crumbs: [{ label: '客户管理' }, { label: '客户列表' }] },
  { match: (p) => p.startsWith('/finance'), crumbs: [{ label: '客户管理' }, { label: '财务对账' }] },

  // 组织管理组（与侧边栏"组织管理"分组对齐，#2969 员工/岗位权限/企业信息归入本组）
  { match: (p) => p.startsWith('/employees'), crumbs: [{ label: '组织管理' }, { label: '员工管理' }] },
  { match: (p) => p.startsWith('/roles'), crumbs: [{ label: '组织管理' }, { label: '岗位权限' }] },
  { match: (p) => p.startsWith('/settings'), crumbs: [{ label: '组织管理' }, { label: '企业基础信息' }] },

  // 通知中心（独立菜单，全员可见，与顶栏铃铛一致）
  { match: (p) => p.startsWith('/notifications'), crumbs: [{ label: '通知中心' }] },
]

function resolveBreadcrumbs(pathname: string | null): { label: string; href?: string }[] {
  if (!pathname) return [{ label: '经营看板' }]
  const matched = ROUTE_BREADCRUMB_MAP.find((m) => m.match(pathname))
  return matched ? matched.crumbs : [{ label: '工作台', href: '/dashboard' }]
}

export default function Header({ title, breadcrumbs }: HeaderProps) {
  const router = useRouter()
  const pathname = usePathname()
  const { user, logout } = useAuthStore()
  // #3099: 用户下拉卡片改为点击展开（原 group-hover 悬停触发）
  const [userMenuOpen, setUserMenuOpen] = useState(false)

  const displayName = user?.name || user?.nickname || user?.username || '管理员'

  const handleLogout = async () => {
    setUserMenuOpen(false)
    await logout()
    router.push('/login')
  }

  // 优先级：显式 breadcrumbs > 显式 title > 基于路由的动态面包屑
  const resolvedBreadcrumbs = breadcrumbs ?? (title ? null : resolveBreadcrumbs(pathname))
  const pageTitle = title || resolvedBreadcrumbs?.[resolvedBreadcrumbs.length - 1]?.label || '经营看板'

  return (
    <header className="sticky top-0 z-40 flex h-14 items-center justify-between border-b border-neutral-200/80 bg-white/85 px-6 backdrop-blur-sm">
      {/* 左侧：面包屑 / 页面标题 */}
      <div className="flex items-center">
        {resolvedBreadcrumbs ? (
          <nav className="flex items-center text-sm">
            {resolvedBreadcrumbs.map((crumb, index) => {
              const isLast = index === resolvedBreadcrumbs.length - 1
              return (
                <div key={`${crumb.label}-${index}`} className="flex items-center">
                  {index > 0 && (
                    <span className="mx-2 text-neutral-300">/</span>
                  )}
                  {crumb.href && !isLast ? (
                    <a
                      href={crumb.href}
                      className="text-neutral-500 transition-colors hover:text-primary-600"
                    >
                      {crumb.label}
                    </a>
                  ) : (
                    <span
                      className={cn(
                        isLast
                          ? 'font-medium text-neutral-900'
                          : 'text-neutral-500'
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
          <h1 className="text-base font-medium text-neutral-900">{pageTitle}</h1>
        )}
      </div>

      {/* 右侧：通知 + 用户信息 */}
      <div className="flex items-center gap-3">
        {/* 通知铃铛 */}
        <NotificationBell />

        {/* 用户下拉菜单（#3099: 点击展开 + 姓名默认展示 + 卡片信息丰富） */}
        <div className="relative">
          <button
            aria-label="用户菜单"
            aria-expanded={userMenuOpen}
            onClick={() => setUserMenuOpen((v) => !v)}
            className="relative z-50 flex items-center gap-2 rounded-lg p-1.5 pr-3 transition-colors hover:bg-neutral-100"
          >
            {/* 头像：有 avatar 用图片，否则姓名首字 */}
            {user?.avatar ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={user.avatar}
                alt="用户头像"
                className="h-8 w-8 rounded-full object-cover shadow-sm"
              />
            ) : (
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-primary-400 to-primary-600 text-sm font-semibold text-white shadow-sm">
                {displayName.charAt(0) || <User className="h-4 w-4 text-white" />}
              </div>
            )}
            {/* 默认展示当前登录用户名称（#3099） */}
            <span className="hidden text-sm text-neutral-700 sm:block">{displayName}</span>
            <ChevronDown className="hidden h-4 w-4 text-neutral-400 sm:block" />
          </button>

          {/* 点击展开的下拉卡片（非 hover） */}
          {userMenuOpen && (
            <>
              {/* 点击卡片外任意处关闭 */}
              <div className="fixed inset-0 z-40" onClick={() => setUserMenuOpen(false)} />
              <div className="absolute right-0 top-full z-50 mt-1 w-64 rounded-xl border border-neutral-200 bg-white shadow-card-hover">
                {/* 卡片头部：头像 + 姓名 + 账号/邮箱 */}
                <div className="flex items-center gap-3 border-b border-neutral-100 px-4 py-3">
                  {user?.avatar ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={user.avatar}
                      alt="用户头像"
                      className="h-10 w-10 rounded-full object-cover shadow-sm"
                    />
                  ) : (
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-primary-400 to-primary-600 text-base font-semibold text-white shadow-sm">
                      {displayName.charAt(0) || <User className="h-5 w-5 text-white" />}
                    </div>
                  )}
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-neutral-900">{displayName}</p>
                    <p className="truncate text-xs text-neutral-500">
                      {user?.email || user?.username || ''}
                    </p>
                  </div>
                </div>

                {/* 丰富信息：#3099 手机号 / 岗位 / 所属企业 */}
                <div className="space-y-2 px-4 py-3 text-sm">
                  <div className="flex items-center gap-2 text-neutral-600">
                    <Phone className="h-3.5 w-3.5 text-neutral-400" />
                    <span className="w-14 shrink-0 text-neutral-400">手机号</span>
                    <span className="truncate text-neutral-800">{user?.username || '-'}</span>
                  </div>
                  <div className="flex items-center gap-2 text-neutral-600">
                    <Briefcase className="h-3.5 w-3.5 text-neutral-400" />
                    <span className="w-14 shrink-0 text-neutral-400">岗位</span>
                    <span className="truncate text-neutral-800">{user?.position || '-'}</span>
                  </div>
                  <div className="flex items-center gap-2 text-neutral-600">
                    <Building2 className="h-3.5 w-3.5 text-neutral-400" />
                    <span className="w-14 shrink-0 text-neutral-400">所属企业</span>
                    <span className="truncate text-neutral-800">{user?.tenantName || '-'}</span>
                  </div>
                </div>

                <button
                  onClick={handleLogout}
                  className="flex w-full items-center gap-2 border-t border-neutral-100 px-4 py-2.5 text-sm text-red-600 transition-colors hover:bg-red-50"
                >
                  <LogOut className="h-4 w-4" />
                  退出登录
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </header>
  )
}
