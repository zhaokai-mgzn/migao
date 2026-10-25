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

// 🔴 2026-10-17（issue #7087）：撤销「工作台」组（组 key `workspace`）—— 其唯一菜单项「经营看板」
// 升为**最前席位**一级项（见 `HEAD_KEYS`）；「每日简报」菜单项删除。
// 🔴 2026-10-20（issue #7369）：**6 组** —— 新增「供应链」组（入库单 / 供应商 / 采购单 从「仓储与物料」搬出）。
const GROUP_KEYS = [
  'customer-service',
  'trade-center',
  'production-center',
  'supply-chain',
  'inventory-center',
  'org-center',
]
const GROUP_NAMES: Record<string, string> = {
  'customer-service': '客户服务',
  'trade-center': '交易管理',
  'production-center': '生产管理',
  'supply-chain': '供应链',
  'inventory-center': '仓储与物料',
  'org-center': '组织管理',
}
/**
 * **最前席位**一级项（`standaloneHeadItems`）：渲染在**所有分组之前**、块
 * `data-testid="sidebar-standalone-head"`、**不受任何组的展开态影响**（这是与旧形态最大的差别：
 * 旧形态里「经营看板」是「工作台」组的组内项 ⇒ 该组收起时它**不渲染**）。
 */
// 报表中心（#7376）：同为最前席位、紧跟经营看板
const HEAD_KEYS = ['dashboard', 'reports']
const HEAD_TESTID = 'sidebar-standalone-head'
/**
 * 28 项（最前席位 → 全部分组 → 尾席位 → 独立项）的渲染顺序
 * （#5778；#5939 加「发货单」；#6404 加「库存明细」；**2026-10-06 方案 A1 重排 + 尾席位沉底**；
 *  **#6580 生产管理组收拢为 3 项、第二个一级项由「参数总览」改为「企业基础设置」**；
 *  **#7087 撤销「工作台」组 + 经营看板升最前席位 + 删「每日简报」菜单项**）。
 *
 * 本表**独立写死** ⇒ 顺序被无声改回 ⇒ 本用例当场红。
 */
const ALL_MENU_KEYS = [
  // 最前席位（issue #7087）：恒渲染、在所有组之前
  ...HEAD_KEYS,
  'human-sessions',
  'knowledge',
  'after-sales',
  'customers',
  'price-books', 'orders',
  'finance',
  'production-board',
  'production-pool',
  'production-piecework',
  'quality-inspections', 'rework-orders',
  'inbound-orders', 'suppliers', 'purchase-orders',
  'stock-ledger',
  'stocktakes',
      'outbound-orders',
  'shipments',
  'production-remnants',
  'production-saving-board',
  'employees',
  'roles',
  'products',
  // #6580：第二个一级项（紧随「商品管理」，顺序 = `standaloneTopItems` 数组顺序）
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

  it('① /dashboard：**最前席位**「经营看板」照渲染，6 个分组**全部收起**（它不入任何组）', async () => {
    render(<Sidebar collapsed={false} onToggle={() => {}} />)
    // 🔴 issue #7087：/dashboard 属最前席位 ⇒ 没有任何组会被自动展开（旧形态里它属「工作台」组、
    // 该组展开、组内两项渲染）。最前席位 + 尾席位 + 尾部项都**不受组的展开态影响**。
    await waitFor(() => expect(menuKeys()).toEqual([...HEAD_KEYS, 'products', 'settings', 'notifications']))
    expect(expandedState()).toEqual({
      'customer-service': 'false',
      'trade-center': 'false',
      'production-center': 'false',
      'supply-chain': 'false',
      'inventory-center': 'false',
      'org-center': 'false',
    })
    // 收起组的项**不渲染**（不是「渲染了但隐藏」）
    expect(document.querySelector('[data-menu-key="orders"]')).toBeNull()
    // 判别力：旧形态（「工作台」组）会让下面两条红
    expect(document.querySelector('[data-group-key="workspace"]')).toBeNull()
    expect(screen.queryByText('工作台')).toBeNull()
  })

  it('① /orders：只展开「交易管理」；最前席位**恒在**（不随组收起而消失）', async () => {
    mockPathname = '/orders'
    render(<Sidebar collapsed={false} onToggle={() => {}} />)
    await waitFor(() =>
      // #5778：交易管理组只剩「销售订单 + 财务对账」；2026-10-06：尾席位「商品管理」恒渲染，
      // 且因它排在**所有分组之后** ⇒ 落在「交易管理」两项之后、「通知中心」之前；
      // 🔴 #7087：最前席位「经营看板」恒渲染（在**所有分组之前**）—— 旧形态下它此时**不渲染**
      //（属「工作台」组且该组收起）。
      expect(menuKeys()).toEqual(['dashboard', 'reports', 'price-books', 'orders', 'finance', 'products',
        'settings', 'notifications']),
    )
    expect(toggle('trade-center').getAttribute('aria-expanded')).toBe('true')
    expect(document.querySelector('[data-menu-key="dashboard"]')).toHaveAttribute('href', '/dashboard')
    // 收起组的项不渲染（对照：非当前组的组内项真的不在 DOM 里）
    expect(document.querySelector('[data-menu-key="human-sessions"]')).toBeNull()
    // 独立项恒在（不属于任何组）
    expect(
      document.querySelector<HTMLAnchorElement>('[data-menu-key="notifications"]'),
    ).toHaveAttribute('href', '/notifications')
  })

  it('① 组标题可点：点开一个收起组 ⇒ 该组项出现且 aria-expanded 变 true；再点 ⇒ 收起', async () => {
    render(<Sidebar collapsed={false} onToggle={() => {}} />)
    await waitFor(() => expect(menuKeys()).toEqual([...HEAD_KEYS, 'products', 'settings', 'notifications']))

    fireEvent.click(toggle('inventory-center'))
    expect(toggle('inventory-center').getAttribute('aria-expanded')).toBe('true')
    // issue #7369：本组只留 库存 → 出库 → 台账 → 分析（单据三项已搬去「供应链」组）
    expect(menuKeys()).toEqual([
      ...HEAD_KEYS,
      'stock-ledger',
  'stocktakes',
      'outbound-orders',
      'shipments',
      'production-remnants',
      'production-saving-board',
      'products',
      'settings',
      'notifications',
    ])

    fireEvent.click(toggle('inventory-center'))
    expect(toggle('inventory-center').getAttribute('aria-expanded')).toBe('false')
    expect(menuKeys()).toEqual([...HEAD_KEYS, 'products', 'settings', 'notifications'])
  })

  it('① 组 key 与组名逐一对齐（**6 组**；「常用」未钉任何项 ⇒ 不渲染，故 `data-group-key` = 6）', async () => {
    render(<Sidebar collapsed={false} onToggle={() => {}} />)
    await waitFor(() => expect(menuKeys()).toContain('dashboard'))
    expect(document.querySelectorAll('[data-group-key]')).toHaveLength(6)
    for (const key of GROUP_KEYS) {
      expect(groupEl(key).getAttribute('data-group-key')).toBe(key)
      expect(toggle(key).textContent).toContain(GROUP_NAMES[key])
    }
    // 🔴 最前席位**不是**分组（`data-group-key` 里没有它）—— 它是「一级项」席位
    expect(document.querySelector('[data-group-key="dashboard"]')).toBeNull()
  })

  // ── ② 高亮自动展开所在组 ──

  it('② 路由变化 ⇒ 新所在组自动展开；已手动展开的其它组不受影响', async () => {
    const { rerender } = render(<Sidebar collapsed={false} onToggle={() => {}} />)
    // /dashboard 属**最前席位**（不入组）⇒ 初值**没有**任何组展开（旧形态是「工作台」展开）
    await waitFor(() => expect(menuKeys()).toEqual([...HEAD_KEYS, 'products', 'settings', 'notifications']))

    // 用户先手动展开「仓储与物料」
    fireEvent.click(toggle('inventory-center'))
    expect(toggle('inventory-center').getAttribute('aria-expanded')).toBe('true')

    mockPathname = '/production/pool'
    rerender(<Sidebar collapsed={false} onToggle={() => {}} />)

    expect(toggle('production-center').getAttribute('aria-expanded')).toBe('true')
    // 已手动展开的「仓储与物料」保持展开（用户意图不被顶掉）
    expect(toggle('inventory-center').getAttribute('aria-expanded')).toBe('true')
    expect(menuKeys()).toEqual([
      // 最前席位恒在（不分组的项不受展开态影响）：经营看板 → 报表中心（#7376）
      'dashboard', 'reports',
      // 🔴 #6580：生产管理组只剩「作业看板 → 智能派单 → 计件工资」（加工项管理/工艺配置已移除）
      'production-board',
      'production-pool',
      'production-piecework',
      'quality-inspections',
  'rework-orders',
      // issue #7369：仓储与物料组只留 库存 → 出库 → 台账 → 分析（单据三项在「供应链」组，未展开 ⇒ 不渲染）
      'stock-ledger',
  'stocktakes',
      'outbound-orders',
      'shipments',
      'production-remnants',
      'production-saving-board',
      'products',          // 尾席位一级项：所有分组之后
      'settings',          // #6580：第二个一级项（紧随「商品管理」）
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
    // /dashboard 属最前席位 ⇒ 初值 6 组全收起
    await waitFor(() => expect(menuKeys()).toEqual([...HEAD_KEYS, 'products', 'settings', 'notifications']))

    mockPathname = '/orders'
    rerender(<Sidebar collapsed={false} onToggle={() => {}} />)
    expect(toggle('trade-center').getAttribute('aria-expanded')).toBe('true')

    mockPathname = '/production/pool'
    rerender(<Sidebar collapsed={false} onToggle={() => {}} />)
    expect(toggle('production-center').getAttribute('aria-expanded')).toBe('true')
    expect(toggle('trade-center').getAttribute('aria-expanded')).toBe('true')
  })

  // ── ③ 折叠态：分组可判定，组名文本不渲染，所有组的项都在 ──

  it('③ 折叠态：**6 个** `sidebar-group-anchor-<key>` 都在，`title` == 组名', async () => {
    render(<Sidebar collapsed onToggle={() => {}} />)
    await waitFor(() =>
      expect(menuKeys()).toHaveLength(28),
    )
    for (const key of GROUP_KEYS) {
      const anchor = screen.getByTestId(`sidebar-group-anchor-${key}`)
      expect(anchor.getAttribute('title')).toBe(GROUP_NAMES[key])
    }
    // 折叠态没有组标题按钮（分组信息由 anchor 承担）。
    // 🔴 #7087：最前席位**不是**分组 ⇒ 它**没有** `sidebar-group-anchor-dashboard` 这枚锚点
    expect(document.querySelectorAll('[data-testid^="sidebar-group-toggle-"]')).toHaveLength(0)
    expect(screen.queryByTestId('sidebar-group-anchor-dashboard')).toBeNull()
    // anchor 是普通 div（不是按钮）—— 折叠态没有可点的组标题
    expect(screen.getByTestId('sidebar-group-anchor-customer-service').tagName).toBe('DIV')
  })

  it('③ 折叠态：**组名文本**与**菜单名文本**都不渲染（原判据仍须成立）', async () => {
    render(<Sidebar collapsed onToggle={() => {}} />)
    await waitFor(() => expect(menuKeys()).toHaveLength(28))
    for (const name of Object.values(GROUP_NAMES)) {
      expect(screen.queryByText(name)).toBeNull()
    }
    for (const name of ['经营看板', '通知中心', '销售订单', '余料台账', '岗位权限']) {
      expect(screen.queryByText(name)).toBeNull()
    }
    // 但链接元素**在**（图标栏），且文本被剥掉（只剩图标）
    expect(document.querySelector('[data-menu-key="orders"]')!.textContent).toBe('')
    // 🔴 #7087：最前席位同样按「图标栏」处理（图标在、文本剥掉）
    expect(document.querySelector('[data-menu-key="dashboard"]')!.textContent).toBe('')
    // #5778：交易管理组只剩 2 项（销售订单 / 财务对账），客户侧已移入「客户服务」组
    // 价格本（#7375 段 3）加入后三项；#7374 曾加「审批中心」⇒ 四项；🔴 #7593（用户裁定）撤掉审批中心
    //（入口改顶栏 `ApprovalBell`）⇒ 回到**三项**：价格本 → 销售订单 → 财务对账
    expect(within(groupEl('trade-center')).getAllByRole('link')).toHaveLength(3)
  })

  it('③ 折叠态：**所有组**的项都渲染（图标栏），项 key 序列 == 28 项全量（#6404 +库存明细；#6580 生产组收拢；#7087 撤工作台组 + 最前席位）', async () => {
    render(<Sidebar collapsed onToggle={() => {}} />)
    await waitFor(() => expect(menuKeys()).toHaveLength(28))
    expect(menuKeys()).toEqual(ALL_MENU_KEYS)
    // 每组项数与其组内项数一致（分组信息没丢）；「工作台」组已撤销 ⇒ 探针换成首组
    expect(within(groupEl('customer-service')).getAllByRole('link')).toHaveLength(4)
    // 🔴 #6580：生产管理组 5 → **3 项**（加工项管理/工艺配置已移除）；组织管理组 3 → **2 项**；
    // #7140 加「质检记录」、#7377 加「返工单」⇒ 现为 **5 项**
    //（「企业基础设置」升为一级项）；🔴 #7140：生产管理组再 **+1**（「质检记录」）⇒ 现 **4 项**
    expect(within(groupEl('production-center')).getAllByRole('link')).toHaveLength(5)
    // #7369 段 4 + 2026-10-20 新 IA：仓储与物料组由 7 项回到 **4 项**（入库单 / 供应商 / 采购单
    // 已整组搬去新组「供应链」）；#7373 再 +「盘点单」⇒ **5 项**
    expect(within(groupEl('inventory-center')).getAllByRole('link')).toHaveLength(6)
    // issue #7369：新组「供应链」= 入库单 → 供应商 → 采购单
    expect(within(groupEl('supply-chain')).getAllByRole('link')).toHaveLength(3)
    expect(within(groupEl('org-center')).getAllByRole('link')).toHaveLength(2)
    // 🔴 #7087：最前席位**不在**任何组里（它挂在 `sidebar-standalone-head` 块上）
    // 最前席位是**两项**（经营看板 + 报表中心，#7376）
    expect(within(screen.getByTestId(HEAD_TESTID)).getAllByRole('link')).toHaveLength(2)
  })

  it('③ 折叠态高亮仍生效：/production/pool ⇒ 该项带 `bg-primary-600`，且只有它一个', async () => {
    mockPathname = '/production/pool'
    render(<Sidebar collapsed onToggle={() => {}} />)
    await waitFor(() => expect(menuKeys()).toHaveLength(28))
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
    // 🔴 #7087：/dashboard 属**最前席位**（不入任何组）⇒ 6 组全收起，
    // 因此这一屏 = 最前席位 + 尾席位两项 + 尾部项（旧形态里它是「工作台」组的组内项）
    expect(menuKeys()).toEqual(['dashboard', 'reports', 'products', 'settings', 'notifications'])
  })
})