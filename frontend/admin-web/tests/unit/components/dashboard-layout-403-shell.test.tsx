// case_ids: DF-007, UI-028
/**
 * 403 面不再吞掉整页（issue #6758）—— **真 Sidebar** 渲染版判据。
 *
 * ## 为什么与 `tests/unit/lib/auth-guard.test.tsx` 的 403 用例并存
 *
 * 那边把 Sidebar / Header 换成了替身（只判「layout 有没有渲染它们」），本文件**不替身化 Sidebar**：
 * 用**真菜单 + 真权限过滤**渲染，判据落在具体节点上（`[data-menu-key="human-sessions"]` 取得到、
 * 且它的 `href` 指向客服能去的那一页）—— 这是现场形态的逐字复刻：
 *
 *   客服岗位（`agent:session` / `knowledge:view` / `after_sales:view` / `customer:view`，
 *   **不含** `dashboard:view`）登录 ⇒ 落 `/dashboard` ⇒ 该路由守卫不过。
 *   修前 `(dashboard)/layout.tsx` 的 `permissionDenied` 分支**在渲染 Sidebar 之前**就
 *   `return <AccessDenied />` ⇒ **整页外壳消失**，只剩一张「无权访问该页面」卡片，
 *   该员工明明持客服全套权限却**没有任何导航出口**（只能手输 URL）。
 *
 * 本文件的判据 = 「403 时侧边栏真的还在、能走到有权限的功能」；反向对照 = 该账号菜单里
 * **没有**「经营看板」（没有 `dashboard:view`，菜单过滤是真在跑，不是把 21 项全画出来）。
 *
 * 红证（注入式）：把 `permissionDenied` 的 `return <AccessDenied />` 移回 Sidebar 渲染之前
 * ⇒ 「403 时侧边栏在」这条当场红。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'

// 真 Sidebar 用 `useAuthStore()`（不带 selector）；layout 的 `usePermission()` 用
// `useAuthStore(s => s.user)` ⇒ mock 必须两种调用形态都支持。
const mockState = vi.fn()
vi.mock('@/store/auth', () => ({
  useAuthStore: (...args: any[]) => (args.length ? args[0](mockState()) : mockState()),
}))

const mockUsePathname = vi.fn()
vi.mock('next/navigation', () => ({
  usePathname: () => mockUsePathname(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), refresh: vi.fn(), back: vi.fn(), forward: vi.fn() }),
}))

vi.mock('next/link', () => ({
  // preventDefault：jsdom 下 `<a href>` 的真跳转会打印 "Not implemented: navigation" 噪声
  default: ({ children, href, onClick, ...props }: any) => (
    <a
      href={href}
      onClick={(e: any) => {
        e.preventDefault()
        onClick?.(e)
      }}
      {...props}
    >
      {children}
    </a>
  ),
}))

vi.mock('@/components/ui/Logo', () => ({
  default: (props: any) => <span data-testid="logo" {...props} />,
}))

// 只替身「外壳的其余部分」—— 被判的 Sidebar **保持真实**
vi.mock('@/components/layout/Header', () => ({ default: () => <div data-testid="header">Header</div> }))
vi.mock('@/components/layout/CommandPalette', () => ({ default: () => null }))
vi.mock('@/components/ai-assistant/FloatingAssistant', () => ({ default: () => null }))

// 简报企业开关：静默关（本用例不涉及）
vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<any>()),
  briefingApi: { getConfig: () => Promise.resolve({ data: { data: { enabled: false } } }) },
}))

import DashboardLayout from '@/app/(dashboard)/layout'

/** 客服岗位账号（种子 `customer_service` 的四码；**不含** `dashboard:view`） */
const CUSTOMER_SERVICE_USER = {
  id: '9',
  username: 'kefu',
  name: '客服小王',
  roles: ['customer_service'],
  permissions: ['agent:session', 'knowledge:view', 'after_sales:view', 'customer:view'],
}

describe('(dashboard)/layout 403 面保留外壳（issue #6758）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    cleanup()
    // 落点 = /dashboard（修前登录硬编码落点，issue #6758 的现场形态）；该账号无 dashboard:view
    mockUsePathname.mockReturnValue('/dashboard')
    mockState.mockReturnValue({ user: CUSTOMER_SERVICE_USER, isAuthenticated: true })
  })

  it('permissionDenied ⇒ 主内容区是 403 面，但侧边栏仍在（客服能走到「在线接待」）', () => {
    render(
      <DashboardLayout>
        <div data-testid="denied-child">这一页的内容不该渲染</div>
      </DashboardLayout>
    )

    // ① 主内容区 = 403 面（不再是整页替换）
    expect(screen.getByText('无权访问该页面')).toBeInTheDocument()
    expect(screen.queryByTestId('denied-child')).not.toBeInTheDocument()

    // ② 外壳仍在：Header + **真 Sidebar 的节点**可取到
    expect(screen.getByTestId('header')).toBeInTheDocument()
    // 客服能去的那一页在菜单里（分组默认收起 ⇒ 先展开「客户服务」组）
    fireEvent.click(screen.getByTestId('sidebar-group-toggle-customer-service'))
    // ⚠️ 不写存在性弱断言（`not.toBeNull` 之类触不到业务数据，且新增测试弱断言**一律 fail-closed**）——
    // 直接钉「命中几项 + 指向哪 + 叫什么」。
    const hits = document.querySelectorAll('[data-menu-key="human-sessions"]')
    expect(hits).toHaveLength(1)
    expect(hits[0].getAttribute('href')).toBe('/agent-workspace/human-sessions')
    expect(hits[0].textContent).toContain('在线接待')

    // ③ 反向对照：菜单过滤是真在跑 —— 该账号没有 dashboard:view，「经营看板」不在菜单里
    expect(document.querySelector('[data-menu-key="dashboard"]')).toBeNull()
  })
})
