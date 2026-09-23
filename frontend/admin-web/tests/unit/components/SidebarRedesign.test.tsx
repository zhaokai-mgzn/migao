// case_ids: UI-028, PR-038, PR-106
/**
 * 侧边栏重设计的**新交互**判据（issue #5271）。
 *
 * 本文件与 `Sidebar.test.tsx` 的分工：那边判**既有能力不许退化**（图标、href、权限正负控、
 * `bg-primary-600` 高亮、折叠态不渲染组名），本文件判**四项新交互**：
 *
 *   ① **分组默认只展开「当前路由所在组」**（其余收起 ⇒ 组内项不渲染）——
 *      组标题是 `<button data-testid="sidebar-group-toggle-<key>" aria-expanded>`，
 *      同一组 wrapper 上有 `data-group-key="<key>"`，链接上有 `data-menu-key="<key>"`；
 *   ② **高亮自动展开所在组** —— `usePathname()` 变到别的组 ⇒ 该组自动展开；
 *      用户手动展开的其它组**不受影响**，手动**收起**当前组后也不会被立刻顶开；
 *   ③ **折叠态（`collapsed=true`）分组可见** —— 渲染 `data-testid="sidebar-group-anchor-<key>"`
 *      （`title` = 组名）+ 组图标；**组名文本不渲染**；此态下**所有组**的项都渲染（图标栏）；
 *   ④ **移动端抽屉** —— `<aside>` 恒 `w-60`；`mobileOpen=false` ⇒ `-translate-x-full`（桌面端
 *      `lg:translate-x-0`）；`mobileOpen=true` ⇒ `translate-x-0`；
 *   ⑤ 侧边栏的 `sidebar-search-trigger` 点击 ⇒ 调用 `onOpenSearch`（接通 ⌘K 面板）。
 *
 * 判据落在**具体 testid / 具体类名 / 具体 `data-menu-key` 序列**上，不用存在性断言。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'

let mockPermissions: string[] = ['*']
let mockRoles: string[] | undefined = ['admin']
vi.mock('@/store/auth', () => ({
  useAuthStore: () => ({ user: { name: '管理员', permissions: mockPermissions, roles: mockRoles } }),
}))

let mockPathname: string | null = '/dashboard'
vi.mock('next/navigation', () => ({
  usePathname: () => mockPathname,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}))

vi.mock('next/link', () => ({
  // preventDefault：jsdom 下 `<a href>` 的真跳转会打印 "Not implemented: navigation" 噪声
  //（真实 Next.js 的 <Link> 自己拦截客户端跳转；这里只需保留 href 与 onClick 语义）
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

let mockBriefingEnabled = true
vi.mock('@/lib/api', () => ({
  briefingApi: { getConfig: () => Promise.resolve({ data: { data: { enabled: mockBriefingEnabled } } }) },
}))

import Sidebar from '@/components/layout/Sidebar'

const GROUP_KEYS = [
  'workspace',
  'smart-customer-service',
  'product-center',
  'trade-center',
  'production-center',
  'inventory-center',
  'org-center',
]
const GROUP_NAMES: Record<string, string> = {
  workspace: '工作台',
  'smart-customer-service': '智能客服',
  'product-center': '商品与加工项',
  'trade-center': '交易管理',
  'production-center': '生产管理',
  'inventory-center': '仓储与物料',
  'org-center': '组织管理',
}
/** 21 项（含独立项）的渲染顺序 */
const ALL_MENU_KEYS = [
  'dashboard',
  'briefing',
  'human-sessions',
  'knowledge',
  'products',
  'processing',
  'orders',
  'after-sales',
  'customers',
  'finance',
  'production-board',
  'production-pool',
  'production-process',
  'production-piecework',
  'inbound-orders',
  'production-remnants',
  'production-saving-board',
  'employees',
  'roles',
  'settings',
  'notifications',
]

const menuKeys = () =>
  Array.from(document.querySelectorAll('[data-menu-key]')).map((el) => el.getAttribute('data-menu-key'))
const groupEl = (key: string) => document.querySelector(`[data-group-key="${key}"]`) as HTMLElement
const toggle = (key: string) => screen.getByTestId(`sidebar-group-toggle-${key}`)
const expandedState = () =>
  Object.fromEntries(GROUP_KEYS.map((k) => [k, toggle(k).getAttribute('aria-expanded')]))

describe('Sidebar 重设计 · 新交互（issue #5271 / UI-028）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockPermissions = ['*']
    mockRoles = ['admin']
    mockBriefingEnabled = true
    mockPathname = '/dashboard'
  })

  // ── ① 默认只展开当前路由所在组 ──

  it('① /dashboard：只有「工作台」aria-expanded=true，其余 6 组全 false', async () => {
    render(<Sidebar collapsed={false} onToggle={() => {}} />)
    await waitFor(() => expect(menuKeys()).toEqual(['dashboard', 'briefing', 'notifications']))
    expect(expandedState()).toEqual({
      workspace: 'true',
      'smart-customer-service': 'false',
      'product-center': 'false',
      'trade-center': 'false',
      'production-center': 'false',
      'inventory-center': 'false',
      'org-center': 'false',
    })
    // 收起组的项**不渲染**（不是「渲染了但隐藏」）
    expect(document.querySelector('[data-menu-key="orders"]')).toBeNull()
  })

  it('① /orders：只展开「交易管理」，工作台组的项随之不渲染', async () => {
    mockPathname = '/orders'
    render(<Sidebar collapsed={false} onToggle={() => {}} />)
    await waitFor(() =>
      expect(menuKeys()).toEqual(['orders', 'after-sales', 'customers', 'finance', 'notifications']),
    )
    expect(toggle('trade-center').getAttribute('aria-expanded')).toBe('true')
    expect(toggle('workspace').getAttribute('aria-expanded')).toBe('false')
    expect(document.querySelector('[data-menu-key="dashboard"]')).toBeNull()
    // 独立项恒在（不属于任何组）
    expect(
      document.querySelector<HTMLAnchorElement>('[data-menu-key="notifications"]'),
    ).toHaveAttribute('href', '/notifications')
  })

  it('① 组标题可点：点开一个收起组 ⇒ 该组项出现且 aria-expanded 变 true；再点 ⇒ 收起', async () => {
    render(<Sidebar collapsed={false} onToggle={() => {}} />)
    await waitFor(() => expect(menuKeys()).toEqual(['dashboard', 'briefing', 'notifications']))

    fireEvent.click(toggle('inventory-center'))
    expect(toggle('inventory-center').getAttribute('aria-expanded')).toBe('true')
    expect(menuKeys()).toEqual([
      'dashboard',
      'briefing',
      'inbound-orders',
      'production-remnants',
      'production-saving-board',
      'notifications',
    ])

    fireEvent.click(toggle('inventory-center'))
    expect(toggle('inventory-center').getAttribute('aria-expanded')).toBe('false')
    expect(menuKeys()).toEqual(['dashboard', 'briefing', 'notifications'])
  })

  it('① 组 key 与组名逐一对齐（7 组，`data-group-key` + 组标题按钮同源）', async () => {
    render(<Sidebar collapsed={false} onToggle={() => {}} />)
    await waitFor(() => expect(toggle('workspace').getAttribute('aria-expanded')).toBe('true'))
    expect(document.querySelectorAll('[data-group-key]')).toHaveLength(7)
    for (const key of GROUP_KEYS) {
      expect(groupEl(key).getAttribute('data-group-key')).toBe(key)
      expect(toggle(key).textContent).toContain(GROUP_NAMES[key])
    }
  })

  // ── ② 高亮自动展开所在组 ──

  it('② 路由变化 ⇒ 新所在组自动展开；已手动展开的其它组不受影响', async () => {
    const { rerender } = render(<Sidebar collapsed={false} onToggle={() => {}} />)
    await waitFor(() => expect(toggle('workspace').getAttribute('aria-expanded')).toBe('true'))

    // 用户先手动展开「仓储与物料」
    fireEvent.click(toggle('inventory-center'))
    expect(toggle('inventory-center').getAttribute('aria-expanded')).toBe('true')

    mockPathname = '/production/pool'
    rerender(<Sidebar collapsed={false} onToggle={() => {}} />)

    expect(toggle('production-center').getAttribute('aria-expanded')).toBe('true')
    // 另外两组保持各自的状态（工作台：初值展开；仓储与物料：手动展开）
    expect(toggle('workspace').getAttribute('aria-expanded')).toBe('true')
    expect(toggle('inventory-center').getAttribute('aria-expanded')).toBe('true')
    expect(menuKeys()).toEqual([
      'dashboard',
      'briefing',
      'production-board',
      'production-pool',
      'production-process',
      'production-piecework',
      'inbound-orders',
      'production-remnants',
      'production-saving-board',
      'notifications',
    ])
  })

  it('② 手动**收起**当前组后不会被立刻顶开（用户意图优先）', async () => {
    mockPathname = '/orders'
    const { rerender } = render(<Sidebar collapsed={false} onToggle={() => {}} />)
    await waitFor(() => expect(toggle('trade-center').getAttribute('aria-expanded')).toBe('true'))

    fireEvent.click(toggle('trade-center'))
    expect(toggle('trade-center').getAttribute('aria-expanded')).toBe('false')

    rerender(<Sidebar collapsed={false} onToggle={() => {}} />)
    expect(toggle('trade-center').getAttribute('aria-expanded')).toBe('false')
  })

  it('② 连续换组：每一次都自动展开当时所在组（/dashboard → /orders → /production/pool）', async () => {
    const { rerender } = render(<Sidebar collapsed={false} onToggle={() => {}} />)
    await waitFor(() => expect(toggle('workspace').getAttribute('aria-expanded')).toBe('true'))

    mockPathname = '/orders'
    rerender(<Sidebar collapsed={false} onToggle={() => {}} />)
    expect(toggle('trade-center').getAttribute('aria-expanded')).toBe('true')

    mockPathname = '/production/pool'
    rerender(<Sidebar collapsed={false} onToggle={() => {}} />)
    expect(toggle('production-center').getAttribute('aria-expanded')).toBe('true')
    expect(toggle('trade-center').getAttribute('aria-expanded')).toBe('true')
  })

  // ── ③ 折叠态：分组可判定，组名文本不渲染，所有组的项都在 ──

  it('③ 折叠态：7 个 `sidebar-group-anchor-<key>` 都在，`title` == 组名', async () => {
    render(<Sidebar collapsed onToggle={() => {}} />)
    await waitFor(() =>
      expect(menuKeys()).toHaveLength(21),
    )
    for (const key of GROUP_KEYS) {
      const anchor = screen.getByTestId(`sidebar-group-anchor-${key}`)
      expect(anchor.getAttribute('title')).toBe(GROUP_NAMES[key])
    }
    // 折叠态没有组标题按钮（分组信息由 anchor 承担）
    expect(document.querySelectorAll('[data-testid^="sidebar-group-toggle-"]')).toHaveLength(0)
    // anchor 是普通 div（不是按钮）—— 折叠态没有可点的组标题
    expect(screen.getByTestId('sidebar-group-anchor-workspace').tagName).toBe('DIV')
  })

  it('③ 折叠态：**组名文本**与**菜单名文本**都不渲染（原判据仍须成立）', async () => {
    render(<Sidebar collapsed onToggle={() => {}} />)
    await waitFor(() => expect(menuKeys()).toHaveLength(21))
    for (const name of Object.values(GROUP_NAMES)) {
      expect(screen.queryByText(name)).toBeNull()
    }
    for (const name of ['经营看板', '通知中心', '订单列表', '余料台账', '岗位权限']) {
      expect(screen.queryByText(name)).toBeNull()
    }
    // 但链接元素**在**（图标栏），且文本被剥掉（只剩图标）
    expect(document.querySelector('[data-menu-key="orders"]')!.textContent).toBe('')
    expect(within(groupEl('trade-center')).getAllByRole('link')).toHaveLength(4)
  })

  it('③ 折叠态：**所有组**的项都渲染（图标栏），项 key 序列 == 21 项全量', async () => {
    render(<Sidebar collapsed onToggle={() => {}} />)
    await waitFor(() => expect(menuKeys()).toHaveLength(21))
    expect(menuKeys()).toEqual(ALL_MENU_KEYS)
    // 每组项数与其组内项数一致（分组信息没丢）
    expect(within(groupEl('workspace')).getAllByRole('link')).toHaveLength(2)
    expect(within(groupEl('production-center')).getAllByRole('link')).toHaveLength(4)
    expect(within(groupEl('inventory-center')).getAllByRole('link')).toHaveLength(3)
    expect(within(groupEl('org-center')).getAllByRole('link')).toHaveLength(3)
  })

  it('③ 折叠态高亮仍生效：/production/pool ⇒ 该项带 `bg-primary-600`，且只有它一个', async () => {
    mockPathname = '/production/pool'
    render(<Sidebar collapsed onToggle={() => {}} />)
    await waitFor(() => expect(menuKeys()).toHaveLength(21))
    const active = document.querySelector('[data-menu-key="production-pool"]') as HTMLElement
    expect(active.className).toContain('bg-primary-600')
    expect(
      Array.from(document.querySelectorAll('[data-menu-key]')).filter((el) =>
        el.className.includes('bg-primary-600'),
      ),
    ).toHaveLength(1)
  })

  // ── ④ 移动端抽屉 ──

  it('④ 抽屉类名：恒 `w-60`；关闭态 `-translate-x-full` + 桌面 `lg:translate-x-0`；打开态 `translate-x-0`', () => {
    const { rerender } = render(<Sidebar collapsed={false} onToggle={() => {}} mobileOpen={false} />)
    const aside = screen.getByTestId('sidebar')
    expect(aside.tagName).toBe('ASIDE')
    expect(aside.className).toContain('w-60')
    expect(aside.className).toContain('-translate-x-full')
    expect(aside.className).toContain('lg:translate-x-0')
    expect(aside.className).not.toContain(' translate-x-0')

    rerender(<Sidebar collapsed={false} onToggle={() => {}} mobileOpen />)
    expect(aside.className).toContain('translate-x-0')
    expect(aside.className).not.toContain('-translate-x-full')
    expect(aside.className).not.toContain('lg:translate-x-0')
    // 恒宽（移动端不因 collapsed 缩窄 —— 缩窄只在 lg+ 生效）
    expect(aside.className).toContain('w-60')
    expect(aside.className).toContain('lg:w-60')
  })

  it('④ 抽屉与折叠正交：collapsed=true 时仍是 `w-60`（移动端满宽）+ `lg:w-16`（桌面图标栏）', () => {
    render(<Sidebar collapsed onToggle={() => {}} mobileOpen />)
    const aside = screen.getByTestId('sidebar')
    expect(aside.className).toContain('w-60')
    expect(aside.className).toContain('lg:w-16')
    expect(aside.className).toContain('translate-x-0')
  })

  it('④ mobileOpen 缺省 = 关（不传也能编译，且默认藏在屏外）', () => {
    render(<Sidebar collapsed={false} onToggle={() => {}} />)
    expect(screen.getByTestId('sidebar').className).toContain('-translate-x-full')
  })

  it('④ 点菜单项触发 onMobileClose（跳页后收掉浮层）', async () => {
    const onMobileClose = vi.fn()
    render(<Sidebar collapsed={false} onToggle={() => {}} mobileOpen onMobileClose={onMobileClose} />)
    fireEvent.click(document.querySelector('[data-menu-key="dashboard"]')!)
    expect(onMobileClose).toHaveBeenCalledTimes(1)
    expect(onMobileClose).toHaveBeenCalledWith(expect.anything())
  })

  // ── ⑤ 搜索入口接通 ⌘K ──

  it('⑤ `sidebar-search-trigger` 点击触发 onOpenSearch（展开态，含 ⌘K 提示）', async () => {
    const onOpenSearch = vi.fn()
    render(<Sidebar collapsed={false} onToggle={() => {}} onOpenSearch={onOpenSearch} />)
    const trigger = screen.getByTestId('sidebar-search-trigger')
    expect(trigger.textContent).toContain('搜索菜单')
    expect(trigger.textContent).toContain('⌘K')

    fireEvent.click(trigger)
    expect(onOpenSearch).toHaveBeenCalledTimes(1)
  })

  it('⑤ 折叠态搜索入口仍在（图标按钮，title=搜索菜单），点击同样触发 onOpenSearch', () => {
    const onOpenSearch = vi.fn()
    render(<Sidebar collapsed onToggle={() => {}} onOpenSearch={onOpenSearch} />)
    const trigger = screen.getByTestId('sidebar-search-trigger')
    expect(trigger.getAttribute('title')).toBe('搜索菜单')
    expect(trigger.textContent).toBe('')

    fireEvent.click(trigger)
    expect(onOpenSearch).toHaveBeenCalledTimes(1)
  })

  it('⑤ 未传 onOpenSearch 时点击不崩（可选 prop）', () => {
    render(<Sidebar collapsed={false} onToggle={() => {}} />)
    fireEvent.click(screen.getByTestId('sidebar-search-trigger'))
    // 点击后侧边栏结构照常（没有 onClick 也不抛）
    expect(screen.getByTestId('sidebar-search-trigger').textContent).toContain('搜索菜单')
    expect(menuKeys()).toEqual(['dashboard', 'notifications'])
  })
})