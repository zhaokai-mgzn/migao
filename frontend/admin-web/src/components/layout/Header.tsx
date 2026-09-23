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
  // 每日简报（issue #5071）：此前**没有条目** ⇒ 落兜底分支、面包屑只剩「工作台」一项，
  // §15.2「面包屑与侧边栏菜单名一致」不成立（与 #5034 的入库单是**同一形态**的漏改）。
  // ⚠️ 本表是 `find` 取**首个命中**、顺序敏感 ⇒ 前缀不得写宽（`p.startsWith('/b')` 会抢走别的匹配）。
  { match: (p) => p.startsWith('/briefing'), crumbs: [{ label: '工作台' }, { label: '每日简报' }] },

  // 智能客服组（与侧边栏"智能客服"分组对齐，#2969 知识库归入本组）
  { match: (p) => p.startsWith('/chat'), crumbs: [{ label: '智能客服' }, { label: '米宝 · 在线对话' }] },
  { match: (p) => p.startsWith('/agent-workspace/human-sessions'), crumbs: [{ label: '智能客服' }, { label: '在线接待' }] },
  { match: (p) => p.startsWith('/agent-workspace/sessions'), crumbs: [{ label: '智能客服' }, { label: '会话监控' }] },
  { match: (p) => p.startsWith('/agent-workspace'), crumbs: [{ label: '智能客服' }, { label: '客服工作台' }] },
  { match: (p) => p.startsWith('/knowledge'), crumbs: [{ label: '智能客服' }, { label: '知识库' }] },

  // 商品管理（与侧边栏"商品管理"分组对齐）
  { match: (p) => p.startsWith('/products'), crumbs: [{ label: '商品管理' }, { label: '商品列表' }] },
  { match: (p) => p.startsWith('/categories'), crumbs: [{ label: '商品管理' }, { label: '商品分类管理' }] },
  // 顺序敏感：/processing-orders 必须先于 /processing（find 按数组序取首个命中）
  // issue #4357：加工单并入生产管理组 ⇒ 本目录下只剩「生产明细」子路由（列表页已重定向）
  { match: (p) => p.startsWith('/processing-orders'), crumbs: [{ label: '生产管理' }, { label: '生产明细' }] },
  // issue #4490（含同日规格修订）：旧「加工项管理」(/processing) 已并入 /production/processing，
  // 且按用户裁定**归入商品管理组**（生产管理组不再有它）⇒ 面包屑必须跟着入口走，否则
  // §15.2「面包屑与侧边栏菜单名一致」不成立。本路径现为重定向，这里保留一条同口径的兜底。
  // issue #4542：菜单名 = 「加工项管理」（与服务端 `MenuController`/`AuthService` 同名）；
  // 该页仍是两个 tab（加工项 / 加工费组合），改名不减功能。
  { match: (p) => p.startsWith('/processing'), crumbs: [{ label: '商品管理' }, { label: '加工项管理' }] },

  // 生产管理组（与侧边栏"生产管理"分组对齐，issue #4357 补 —— 此前本组**无任何面包屑条目**
  // ⇒ 落进兜底分支显示「工作台 > 经营看板」，§15.2「面包屑与侧边栏菜单名一致」不成立）
  // 顺序敏感：更具体的子路径必须先于 /production
  // issue #4416：「工序库」并入「工艺配置」/production/routings（旧 /production/operations 已重定向）
  { match: (p) => p.startsWith('/production/routings'), crumbs: [{ label: '生产管理' }, { label: '工艺配置' }] },
  // 池看板（issue #5177）：**必须排在 `/production` 之前** —— 本表是 `find` 取**首个命中**，
  // `/production` 那条会抢走 `/production/pool`（面包屑会退化成「生产看板」= §15.2 不成立）。
  // 组名/菜单名与 `config/menu.ts` 的 `production-pool`、服务端两处菜单节点逐字一致。
  { match: (p) => p.startsWith('/production/pool'), crumbs: [{ label: '生产管理' }, { label: '池看板' }] },
  // 省料看板（issue #5159）：同样**必须排在 `/production` 之前**（本表 `find` 取首个命中，
  // `/production` 会抢走它 ⇒ 面包屑退化成「生产看板」= §15.2 不成立）。
  // 组名/菜单名与 `config/menu.ts` 的 `production-saving-board`、服务端两处菜单节点逐字一致。
  { match: (p) => p.startsWith('/production/saving-board'), crumbs: [{ label: '生产管理' }, { label: '省料看板' }] },
  // 余料台账（issue #5146 建页 / issue #5191 **进侧边栏**）：菜单项名 = 「余料台账」，
  // 与 `config/menu.ts` 的 `production-remnants`、服务端两处菜单节点**逐字一致**
  // （§15.2「面包屑末项 == 侧边栏菜单名」；守卫 tests/unit/lib/menu-breadcrumb-coverage.test.tsx）。
  // ⚠️ 必须排在下面的 `/production` 之前（本表 `find` 取首个命中，否则面包屑退化成「生产看板」）。
  { match: (p) => p.startsWith('/production/remnants'), crumbs: [{ label: '生产管理' }, { label: '余料台账' }] },
  // issue #4490（含同日规格修订）：加工项 + 加工费合并为 /production/processing（两个 tab），
  // 按用户裁定归**商品管理**组 ⇒ 面包屑写「商品管理 / 加工项管理」（#4542 改名后与服务端同名）。
  // 前缀同时覆盖旧路径 /production/processing-fees（它重定向到 ?tab=fees）⇒ 旧深链的面包屑也写该名。
  { match: (p) => p.startsWith('/production/processing'), crumbs: [{ label: '商品管理' }, { label: '加工项管理' }] },
  { match: (p) => p.startsWith('/production/piecework'), crumbs: [{ label: '生产管理' }, { label: '计件工资' }] },
  // /production = 加工单唯一入口（issue #4357 与原「加工单」菜单合并）
  { match: (p) => p.startsWith('/production'), crumbs: [{ label: '生产管理' }, { label: '生产看板' }] },
  // 入库单（issue #5071）：V111（#5034）新增菜单项时**漏了本表这一处** ⇒ 面包屑只剩「工作台」一项。
  // 组名/菜单名与侧边栏 `config/menu.ts` 的 `inbound-orders`（生产管理组）逐字一致。
  { match: (p) => p.startsWith('/inbound-orders'), crumbs: [{ label: '生产管理' }, { label: '入库单' }] },

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
