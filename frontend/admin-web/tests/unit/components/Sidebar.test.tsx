// case_ids: HR-001, DF-007, UI-005, UI-011, UI-028, PR-038, PR-106, UI-067
/**
 * 侧边栏（`Sidebar.tsx`）——**既有能力不许退化**的判据（issue #5271 按新 IA 重写期望文案）。
 *
 * ## 与 `SidebarRedesign.test.tsx` 的分工
 *
 * 本文件守**能力面**：21 项一项不少不减（逐项名 + href + `data-menu-key` 序列）、
 * 图标、`bg-primary-600` 高亮与互斥单高亮、权限过滤正负控、空组整组隐藏、
 * 折叠态不渲染组名。新交互面（默认展开态 / 路由联动 / 折叠态分组锚点 / 移动端抽屉 / ⌘K 入口）
 * 在 `tests/unit/components/SidebarRedesign.test.tsx`。
 *
 * ## ⚠️ 重设计带来的一处**结构性**变化（不是判据放宽）
 *
 * 新 IA 下**分组默认只展开当前路由所在组** ⇒ 想断言「其它组的项在不在」就必须
 * **先展开该组**（`data-testid="sidebar-group-toggle-<key>"`）。因此下列用例里凡断言
 * 非当前组项的，都先调 `expandGroups(...)` / `expandAll()` —— 断言本身**一条没删、没放宽**
 * （有 `expect(links).toHaveLength(21)` 这类**更强**的新钉子作反向证明）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within, cleanup } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// Mock useAuthStore
const mockUseAuthStore = vi.fn()
vi.mock('@/store/auth', () => ({
  useAuthStore: (...args: any[]) => mockUseAuthStore(...args),
}))

// Mock next/link
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

// Mock next/navigation
const mockUsePathname = vi.fn()
vi.mock('next/navigation', () => ({
  usePathname: () => mockUsePathname(),
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
  }),
}))

// Mock Logo component
vi.mock('@/components/ui/Logo', () => ({
  default: (props: any) => <span data-testid="logo" {...props} />,
}))

// 简报企业开关（issue #3468）：显式 mock ⇒ 「开关开/关」两种可见性都可判（不再依赖真实网络失败）
let mockBriefingEnabled = false
vi.mock('@/lib/api', () => ({
  briefingApi: { getConfig: () => Promise.resolve({ data: { data: { enabled: mockBriefingEnabled } } }) },
}))

import Sidebar from '@/components/layout/Sidebar'
// #5877：一级项的插入位（席位常量 = 三源同批表达的同一件事）
import { STANDALONE_TOP_AFTER_GROUP_KEY } from '@/config/menu'

/** issue #5778 新 IA：**6 组**（key / 组名 / 组内项顺序；组内顺序 **2026-10-06 方案 A1** 重排） */
const GROUPS: { key: string; name: string; items: [string, string][] }[] = [
  { key: 'workspace', name: '工作台', items: [['dashboard', '经营看板'], ['briefing', '每日简报']] },
  {
    key: 'customer-service',
    name: '客户服务',
    items: [
      ['human-sessions', '在线接待'],
      ['knowledge', '知识库'],
      ['after-sales', '售后工单'],
      ['customers', '客户列表'],
    ],
  },
  { key: 'trade-center', name: '交易管理', items: [['orders', '订单列表'], ['finance', '财务对账']] },
  {
    key: 'production-center',
    name: '生产管理',
    // 🔴 2026-10-09（issue #6580）：「加工项管理」「工艺配置」两个菜单项按用户裁定**移除**
    //（功能体并入一级项「企业基础设置」页内的配置域）⇒ 本组由 5 项收拢为 3 项。
    items: [
      ['production-board', '生产看板'],
      ['production-pool', '智能派单'],
      ['production-piecework', '计件工资'],
    ],
  },
  {
    key: 'inventory-center',
    name: '仓储与物料',
    items: [
      ['inbound-orders', '入库单'],
      ['stock-ledger', '库存明细'],
      ['shipments', '发货单'],
      ['production-remnants', '余料台账'],
      ['production-saving-board', '省料看板'],
    ],
  },
  {
    key: 'org-center',
    name: '组织管理',
    // #6580：「企业基础设置」升为**一级项**（不再占组织管理组的组内席位）
    items: [['employees', '员工管理'], ['roles', '岗位权限']],
  },
]
/**
 * 一级项（**不占组**）：#5778 起「商品管理」不再占一个单成员组；
 * #6573（2026-10-08 用户裁定方案 C）起**并列第二个**一级项；**#6580 起该席位改为「企业基础设置」**
 *（原「参数总览」随本页并入而撤掉，`/settings`，由组织管理组的组内项升为一级项）。
 * **用户 2026-10-06 裁定**起二者都渲染在 `STANDALONE_TOP_AFTER_GROUP_KEY`（现取**最后一个组**）之后
 * ⇒ 排在**所有分组之后**、尾部独立项之前（顺序 = 数组顺序：products → settings）。
 */
const STANDALONE_TOP_KEYS = ['products', 'settings']
/** 一级项的插入位（本表独立写死，不从实现反推） */
const TOP_SLOT_KEY = 'org-center'
const GROUP_KEYS = GROUPS.map((g) => g.key)
/**
 * 展开全部组后应渲染的 **21 项**（**全部分组 → 一级项 → 尾部独立项**，== `flattenMenu` 顺序）。
 * ⚠️ 2026-10-06 起 `TOP_SLOT_KEY` = **最后一个组** ⇒ 一级项落在这条序列的**末尾附近**（通知中心之前）。
 */
const ALL_MENU_KEYS = [
  ...GROUPS.flatMap((g) => g.items.map(([k]) => k)),
  ...STANDALONE_TOP_KEYS,
  'notifications',
]

const groupButton = (key: string) => screen.getByTestId(`sidebar-group-toggle-${key}`)
/** 展开指定组（幂等：已展开则不点）—— 新 IA 默认只展开当前路由所在组 */
function expandGroups(...keys: string[]) {
  for (const key of keys) {
    const btn = groupButton(key)
    if (btn.getAttribute('aria-expanded') === 'false') fireEvent.click(btn)
  }
}
const expandAll = () => expandGroups(...GROUP_KEYS)
const menuKeys = () =>
  Array.from(document.querySelectorAll('[data-menu-key]')).map((el) => el.getAttribute('data-menu-key'))
const activeKeys = () =>
  Array.from(document.querySelectorAll('nav a'))
    .filter((a) => a.className.includes('bg-primary-600'))
    .map((a) => a.getAttribute('data-menu-key'))
const linkFor = (name: string) => screen.getByText(name).closest('a')!

describe('Sidebar', () => {
  const user = userEvent.setup()
  const mockOnToggle = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    mockBriefingEnabled = false
    mockUsePathname.mockReturnValue('/dashboard')
    mockUseAuthStore.mockReturnValue({
      user: { id: '1', username: 'admin', name: '管理员', permissions: ['*'], roles: ['admin'] },
    })
  })

  // ── 基础结构 ──

  it('should render the sidebar with logo', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expect(screen.getByTestId('logo')).toBeInTheDocument()
  })

  it('未设置企业 Logo 时回退观星台默认 Logo', () => {
    mockUseAuthStore.mockReturnValue({
      user: { id: '1', username: 'admin', name: '管理员', roles: ['admin'], permissions: ['*'], tenantName: '测试企业' },
    })
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expect(screen.getByTestId('logo')).toBeInTheDocument()
    expect(screen.queryByAltText('企业 Logo')).not.toBeInTheDocument()
  })

  it('已设置企业 Logo 时展示 img，加载失败后回退默认 Logo', () => {
    mockUseAuthStore.mockReturnValue({
      user: { id: '1', username: 'admin', name: '管理员', roles: ['admin'], permissions: ['*'], tenantLogo: 'https://oss.example.com/logo.png' },
    })
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const img = screen.getByAltText('企业 Logo')
    expect(img).toHaveAttribute('src', 'https://oss.example.com/logo.png')
    expect(screen.queryByTestId('logo')).not.toBeInTheDocument()

    // Logo URL 失效 → 回退默认 Logo，避免空白
    fireEvent.error(img)
    expect(screen.getByTestId('logo')).toBeInTheDocument()
    expect(screen.queryByAltText('企业 Logo')).not.toBeInTheDocument()
  })

  it('should render all menu items（issue #5778 新 IA：6 组 + 2 一级项 + 独立项 = 21 项（#6404 +库存明细；#6580 生产组收拢 + 一级项改「企业基础设置」））', async () => {
    mockBriefingEnabled = true
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    // 分组标题（#5778 重排后六大组：客户服务 / 交易管理 / 生产管理 / 仓储与物料 / 组织管理）
    expect(screen.getByText('工作台')).toBeInTheDocument()
    expect(screen.getByText('客户服务')).toBeInTheDocument()
    expect(screen.getByText('交易管理')).toBeInTheDocument()
    expect(screen.getByText('生产管理')).toBeInTheDocument()
    expect(screen.getByText('仓储与物料')).toBeInTheDocument()
    expect(screen.getByText('组织管理')).toBeInTheDocument()
    // 🔴 旧组名不再出现：#5778 起「商品与加工项」撤销、「智能客服」改判为「客户服务」，
    // 且「商品管理」不再是**组名**（它是一级项，不渲染组标题）⇒ 这里按「组标题」断言它不出现。
    expect(screen.queryByText('商品与加工项')).not.toBeInTheDocument()
    expect(screen.queryByText('智能客服')).not.toBeInTheDocument()
    expect(screen.queryByText('订单管理')).not.toBeInTheDocument()
    expect(screen.queryByText('客户管理')).not.toBeInTheDocument()

    // 非当前组（/dashboard ⇒ 只展开工作台）的项必须先展开该组才可见
    // （简报开关是**异步 effect**：先等它落地，否则下面那条 21 项断言会因时序而假红）
    await waitFor(() => expect(screen.getByText('每日简报')).toBeInTheDocument())
    expandAll()
    // 子菜单项：21 项**一项不少不减**
    expect(menuKeys()).toEqual(ALL_MENU_KEYS)
    for (const [, name] of GROUPS.flatMap((g) => g.items)) {
      expect(screen.getByText(name)).toBeInTheDocument()
    }
    // UI-005/UI-011: **客户服务**分组下 在线接待 + 知识库（#3094 黄金策·在线对话 菜单入口已移除，对话经右下角 FAB）；#2969 知识库并入本组；#3081 AI 客服配置已合并进企业基础信息
    // #5778：客户列表 / 售后工单也并入本组
    expect(screen.queryByText('黄金策 · 在线对话')).not.toBeInTheDocument()
    // 每日简报由企业开关控制（#3468）：开关开 ⇒ 可见
    expect(screen.getByText('每日简报')).toBeInTheDocument()
    // #1403: 商品分类管理已移出侧边栏，入口内嵌到新增商品页
    expect(screen.queryByText('商品分类管理')).not.toBeInTheDocument()
    // 旧菜单名（#4490 的合并名，用码点构造以免在源码里再写出它）不再出现在侧边栏（issue #4542 改名）
    expect(screen.queryByText('\u52a0\u5de5\u9879\u4e0e\u52a0\u5de5\u8d39')).not.toBeInTheDocument()
    // UI-005: 「机器人设置」已更名为「AI 客服配置」，不再出现旧名
    expect(screen.queryByText('机器人设置')).not.toBeInTheDocument()
    // #2969: 「角色权限」已改名「岗位权限」，旧名不再出现
    expect(screen.queryByText('角色权限')).not.toBeInTheDocument()
  })

  it('21 项一项不少不减：`data-menu-key` 序列逐值 == 新 IA（全部分组 → 一级项 → 独立项）', async () => {
    mockBriefingEnabled = true
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    await waitFor(() => expect(groupButton('workspace').getAttribute('aria-expanded')).toBe('true'))
    expandAll()
    // 🔴 2026-10-06 用户裁定（方案 A1）：组内重排 + 一级项「商品管理」排在**所有分组之后**；
    // 🔴 #6580：「企业基础设置」是**第二个**一级项（紧随其后、通知中心之前）—— 它由组织管理组的
    // 组内项升为一级项（原席位是「参数总览」）；生产管理组收拢为 3 项。
    // 客户服务组含 在线接待/知识库/售后工单/客户列表
    expect(menuKeys()).toEqual([
      'dashboard', 'briefing',
      'human-sessions', 'knowledge', 'after-sales', 'customers',
      'orders', 'finance',
      'production-board', 'production-pool', 'production-piecework',
      'inbound-orders', 'stock-ledger', 'shipments', 'production-remnants', 'production-saving-board',
      'employees', 'roles',
      'products',
      'settings',
      'notifications',
    ])
    expect(menuKeys()).toHaveLength(21)
  })

  it('简报开关关 ⇒ 恰少「每日简报」（briefingToggle 过滤条件独立于权限码）', async () => {
    mockBriefingEnabled = false
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expandAll()
    expect(screen.queryByText('每日简报')).not.toBeInTheDocument()
    expect(screen.getByText('经营看板')).toBeInTheDocument()
    expect(menuKeys()).toEqual(ALL_MENU_KEYS.filter((k) => k !== 'briefing'))
  })

  it('should render navigation links with correct paths', async () => {
    mockBriefingEnabled = true
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    await waitFor(() => expect(screen.getByText('每日简报')).toBeInTheDocument())
    expandAll()
    expect(linkFor('经营看板')).toHaveAttribute('href', '/dashboard')
    expect(linkFor('每日简报')).toHaveAttribute('href', '/briefing')
    expect(linkFor('商品管理')).toHaveAttribute('href', '/products')
    // #6580：第二个一级项「企业基础设置」→ /settings（「加工项管理」「工艺配置」已不是菜单项）
    expect(linkFor('企业基础设置')).toHaveAttribute('href', '/settings')
    expect(linkFor('订单列表')).toHaveAttribute('href', '/orders')
    expect(linkFor('售后工单')).toHaveAttribute('href', '/after-sales')
    expect(linkFor('客户列表')).toHaveAttribute('href', '/customers')
    expect(linkFor('财务对账')).toHaveAttribute('href', '/finance')
    expect(linkFor('生产看板')).toHaveAttribute('href', '/production')
    expect(linkFor('智能派单')).toHaveAttribute('href', '/production/pool')
    expect(linkFor('计件工资')).toHaveAttribute('href', '/production/piecework')
    // issue #5271：面料进出与消耗移入新组「仓储与物料」（原生产管理组）
    expect(linkFor('入库单')).toHaveAttribute('href', '/inbound-orders')
    expect(linkFor('余料台账')).toHaveAttribute('href', '/production/remnants')
    expect(linkFor('省料看板')).toHaveAttribute('href', '/production/saving-board')
    expect(linkFor('员工管理')).toHaveAttribute('href', '/employees')
    expect(linkFor('岗位权限')).toHaveAttribute('href', '/roles')
    // #3094: 黄金策 · 在线对话 菜单入口已移除（侧边栏不再渲染 /chat 链接）
    expect(screen.queryByText('黄金策 · 在线对话')).not.toBeInTheDocument()
    expect(linkFor('在线接待')).toHaveAttribute('href', '/agent-workspace/human-sessions')
    expect(linkFor('知识库')).toHaveAttribute('href', '/knowledge')
    expect(linkFor('通知中心')).toHaveAttribute('href', '/notifications')
  })

  // ── 折叠状态 ──

  it('should hide text labels when collapsed', () => {
    render(<Sidebar collapsed={true} onToggle={mockOnToggle} />)
    for (const g of GROUPS) {
      expect(screen.queryByText(g.name)).not.toBeInTheDocument()
    }
    expect(screen.queryByText('观星台')).not.toBeInTheDocument()
    // 菜单名文本同样不渲染（此态下只有图标）
    expect(screen.queryByText('商品列表')).not.toBeInTheDocument()
    expect(screen.queryByText('经营看板')).not.toBeInTheDocument()
  })

  it('should show expand button when collapsed', () => {
    render(<Sidebar collapsed={true} onToggle={mockOnToggle} />)
    expect(screen.getByTitle('展开侧边栏')).toBeInTheDocument()
  })

  it('should show collapse button when expanded', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expect(screen.getByText('收起')).toBeInTheDocument()
  })

  it('should call onToggle when collapse button is clicked', async () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    await user.click(screen.getByText('收起'))
    expect(mockOnToggle).toHaveBeenCalledTimes(1)
  })

  // ── 高亮激活 ──

  function getActiveClass(el: HTMLElement) {
    return el.className
  }

  it('should highlight active menu item for /dashboard', () => {
    mockUsePathname.mockReturnValue('/dashboard')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const link = linkFor('经营看板')
    expect(getActiveClass(link)).toContain('bg-primary-600')
  })

  it('should highlight active menu item for /products', () => {
    mockUsePathname.mockReturnValue('/products')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    // #5778：「商品管理」升为**一级项**（#5877 起渲染在「工作台」组之后、不属任何组）⇒ 它**恒渲染**，无需展开任何组
    const link = linkFor('商品管理')
    expect(getActiveClass(link)).toContain('bg-primary-600')
  })

  it('should not highlight inactive menu items', () => {
    mockUsePathname.mockReturnValue('/dashboard')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    // 非当前组默认收起 ⇒ 先展开「客户服务」再断言它**不高亮**（断言强度不变）
    expandGroups('customer-service')
    const link = linkFor('客户列表')
    expect(getActiveClass(link)).not.toContain('bg-primary-600')
  })

  it('should highlight nested route for /products/123', () => {
    mockUsePathname.mockReturnValue('/products/123')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const link = linkFor('商品管理')
    expect(getActiveClass(link)).toContain('bg-primary-600')
  })

  it('should highlight for root path as dashboard', () => {
    mockUsePathname.mockReturnValue('/')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const link = linkFor('经营看板')
    expect(getActiveClass(link)).toContain('bg-primary-600')
  })

  // ── 前缀嵌套路由互斥单高亮（#3094 黄金策菜单已移除：/chat 无侧边栏入口，在线接待不重复高亮）──

  it('/chat 时无侧边栏菜单高亮（黄金策入口已移除，对话经右下角 FAB）', () => {
    mockUsePathname.mockReturnValue('/chat')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expect(screen.queryByText('黄金策 · 在线对话')).not.toBeInTheDocument()
    // /chat 不属于任何菜单项 ⇒ 无组可展开；展开智能客服后「在线接待」仍在 DOM 且不得高亮
    expandGroups('customer-service')
    const humanLink = linkFor('在线接待')
    expect(getActiveClass(humanLink)).not.toContain('bg-primary-600')
  })

  it('/chat 时侧边栏无高亮菜单项（#3094 黄金策入口已移除）', async () => {
    mockBriefingEnabled = true
    mockUsePathname.mockReturnValue('/chat')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    // /chat 不属于任何菜单项 ⇒ **全部组默认收起**（这本身就是「无高亮」的一种形态）；
    // 展开全部组后再断言「21 项都在 DOM 里，仍然一个都不高亮」
    expandAll()
    await waitFor(() => expect(document.querySelectorAll('nav a')).toHaveLength(21))
    expect(activeKeys()).toEqual([])
  })

  it('/orders/new 时「订单列表」高亮（嵌套路由前缀匹配回归保护）', () => {
    mockUsePathname.mockReturnValue('/orders/new')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    // #5778：交易管理组现为「订单列表 + 财务对账」（售后工单已移入客户服务组）——
    // 同组对照项随之换成「财务对账」，断言**强度一条没减**（仍是「前缀命中只高亮订单列表」）。
    expandGroups('trade-center')
    const ordersLink = linkFor('订单列表')
    const financeLink = linkFor('财务对账')
    expect(getActiveClass(ordersLink)).toContain('bg-primary-600')
    expect(getActiveClass(financeLink)).not.toContain('bg-primary-600')
  })

  it('前缀同时命中（/production/pool ↔ /production）时**只有一项**高亮 —— 最长前缀胜出', () => {
    mockUsePathname.mockReturnValue('/production/pool')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expect(activeKeys()).toEqual(['production-pool'])
    expect(getActiveClass(linkFor('智能派单'))).toContain('bg-primary-600')
    expect(getActiveClass(linkFor('生产看板'))).not.toContain('bg-primary-600')
  })

  // ── 分组折叠/展开 ──

  it('should toggle group expansion when clicking group header', async () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    // /dashboard ⇒ 「组织管理」默认**收起**（新交互 ①），故先点开、再点收。
    // ⚠️ #5778：原锚点「商品与加工项」组已撤销（商品列表升为一级项 ⇒ 不再有单成员组），
    // 本用例改用「组织管理」（3 项、非当前路由所在组）—— 断言的**强度一条没减**。
    expect(screen.queryByText('员工管理')).not.toBeInTheDocument()
    expect(groupButton('org-center').getAttribute('aria-expanded')).toBe('false')

    await user.click(screen.getByText('组织管理'))
    expect(screen.getByText('员工管理')).toBeInTheDocument()
    expect(groupButton('org-center').getAttribute('aria-expanded')).toBe('true')

    await user.click(screen.getByText('组织管理'))
    expect(screen.queryByText('员工管理')).not.toBeInTheDocument()
    expect(groupButton('org-center').getAttribute('aria-expanded')).toBe('false')
  })

  // ── 独立菜单项 ──

  it('should render standalone items exactly once each', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    // #5271: 交易管理是**唯一**的合并组（原「订单管理」+「客户管理」组的客户列表/财务对账）
    expect(screen.getAllByText('交易管理').length).toBe(1)
    // #5778：「商品管理」现在是一级项（渲染恰一次，但不是组标题）
    expect(screen.getAllByText('商品管理').length).toBe(1)
    // #3081: AI 客服配置已移除（合并进企业基础信息），不再渲染
    expect(screen.queryByText('AI 客服配置')).not.toBeInTheDocument()
    // #2969: 岗位权限归入组织管理组（唯一）—— 该组默认收起，先展开；通知中心仍为独立菜单（唯一）
    expandGroups('org-center')
    expect(screen.getAllByText('岗位权限').length).toBe(1)
    expect(screen.getAllByText('通知中心').length).toBe(1)
  })

  // ── UI-005: 智能客服大类分组与图标 ──

  it('（2026-10-06 用户裁定 / #6580）**两个**一级项都在**所有分组之后**、「通知中心」之前（DOM 顺序）', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const follows = (a: HTMLElement, b: HTMLElement) =>
      (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0
    const productItem = linkFor('商品管理')
    const settingsItem = linkFor('企业基础设置')
    const workspace = screen.getByText('工作台')
    const customerService = screen.getByText('客户服务')
    const trade = screen.getByText('交易管理')
    const org = screen.getByText('组织管理')
    const notifications = screen.getByText('通知中心')
    // 🔴 位置 = **所有分组之后**（用户 2026-10-06 裁定：11 个大菜单项并列 ⇒ 一级项沉底）
    expect(follows(workspace, productItem)).toBe(true)
    expect(follows(org, productItem)).toBe(true)
    // #6580：第二个一级项同在分组之后（不是「只有第一个沉底」）
    expect(follows(workspace, settingsItem)).toBe(true)
    expect(follows(org, settingsItem)).toBe(true)
    expect(follows(productItem, notifications)).toBe(true)
    expect(follows(settingsItem, notifications)).toBe(true)
    // 两者之间的顺序 = `standaloneTopItems` 数组顺序（商品管理 → 企业基础设置）
    expect(follows(productItem, settingsItem)).toBe(true)
    // 组顺序不受影响（判别力：这条与「一级项的位置」是两件事）
    expect(follows(customerService, trade)).toBe(true)
    // 判别力：旧口径（一级项夹在「工作台」与「客户服务」之间）在下面两条上会给出 true ⇒ 现在就红
    expect(follows(productItem, workspace)).toBe(false)
    expect(follows(productItem, customerService)).toBe(false)
    expect(follows(settingsItem, workspace)).toBe(false)
    expect(follows(settingsItem, customerService)).toBe(false)
    // 席位常量与渲染位必须同源（改常量而不改判据 = 无声漂移）
    expect(STANDALONE_TOP_AFTER_GROUP_KEY).toBe(TOP_SLOT_KEY)
  })

  it('（#5877）一级项用**板块入口**规格（与组头同级排版 + 不旋转 chevron + 分隔线 + 无星标）', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const link = linkFor('商品管理')
    // 一整行可点的一级项：常态颜色/悬停与组头同级（不是与组内项同级的 text-sm text-neutral-300）
    expect(link.className).toContain('text-neutral-400')
    expect(link.className).toContain('hover:bg-white/5')
    expect(link.className).toContain('hover:text-neutral-200')
    // 文案 = 组头规格
    const label = within(link).getByText('商品管理')
    expect(label.className).toContain('text-xs')
    expect(label.className).toContain('font-medium')
    expect(label.className).toContain('tracking-wide')
    // 对照：组头也是同一套排版（「板块入口」= 与组头同级，而不是随口一说）
    const groupLabel = screen.getByText('工作台')
    for (const cls of ['text-xs', 'font-medium', 'tracking-wide']) {
      expect(groupLabel.className).toContain(cls)
    }
    // 图标 = 组头同款尺寸
    const icon = within(link).getByTestId('icon-package')
    expect(icon.getAttribute('class')).toContain('h-3.5')
    expect(icon.getAttribute('class')).toContain('w-3.5')
    // 右端 = **不旋转**的 ChevronRight（表示「直达」，不是可展开的组）
    const chevron = within(link).getByTestId('icon-chevron-right')
    expect(chevron.getAttribute('class')).toContain('text-neutral-600')
    expect(chevron.getAttribute('class')).not.toContain('rotate-90')
    // 与上方之间（head 组之后）有分隔线：仓内既有同款
    expect(screen.getByTestId('sidebar-standalone-top').className).toContain('border-t')
    // 无星标：一级项不可收藏
    expect(within(link).queryByTestId('sidebar-pin-products')).toBeNull()
  })

  it('（#5877）一级项无星标；组内项与尾部独立项**仍有**星标（对照：不是星标整体被删）', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expect(screen.queryByTestId('sidebar-pin-products')).toBeNull()
    // #6580：第二个一级项（「企业基础设置」，席位原属「参数总览」）同样是「板块入口」⇒ 也没有星标
    expect(screen.queryByTestId('sidebar-pin-settings')).toBeNull()
    expandGroups('trade-center')
    expect(screen.getByTestId('sidebar-pin-orders')).toBeInTheDocument()
    expect(screen.getByTestId('sidebar-pin-notifications')).toBeInTheDocument()
  })

  it('（#5877）折叠态：一级项按组锚点同款处理（图标居中、title = 菜单名、不渲染文字）', () => {
    render(<Sidebar collapsed={true} onToggle={mockOnToggle} />)
    const link = document.querySelector('[data-menu-key="products"]') as HTMLAnchorElement
    expect(link).toBeTruthy()
    expect(link.className).toContain('justify-center')
    expect(link.getAttribute('title')).toBe('商品管理')
    expect(screen.queryByText('商品管理')).not.toBeInTheDocument()
    expect(within(link).queryByTestId('sidebar-pin-products')).toBeNull()
  })

  it('（2026-10-06 方案 A1）「客户服务」组内顺序：在线接待 → 知识库 → 售后工单 → 客户列表', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expandGroups('customer-service')
    const groupContainer = screen.getByText('客户服务').closest('[data-group-key]') as HTMLElement
    const links = groupContainer.querySelectorAll('a')
    expect(links.length).toBe(4)
    expect(links[0].textContent).toContain('在线接待')
    expect(links[1].textContent).toContain('知识库')
    expect(links[2].textContent).toContain('售后工单')
    expect(links[3].textContent).toContain('客户列表')
  })

  it('「在线接待」已从「工作台」分组移除（工作台仅剩经营看板）', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const workspaceGroup = screen.getByText('工作台').closest('[data-group-key]') as HTMLElement
    expect(within(workspaceGroup).getByText('经营看板')).toBeInTheDocument()
    expect(within(workspaceGroup).queryByText('在线接待')).not.toBeInTheDocument()
    // 工作台组内一个链接都没有 /chat 或在线接待（组内项**只有**经营看板，开关关时）
    expect(Array.from(workspaceGroup.querySelectorAll('a')).map((a) => a.getAttribute('href'))).toEqual([
      '/dashboard',
    ])
    // 在线接待整体仍存在（#5778 起移入「客户服务」分组）
    expandGroups('customer-service')
    expect(screen.getByText('在线接待')).toBeInTheDocument()
  })

  it('「在线接待」渲染 Headphones 图标，与「经营看板」BarChart3 图标明确区分', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expandGroups('customer-service')
    const humanLink = linkFor('在线接待')
    expect(within(humanLink).getByTestId('icon-headphones')).toBeInTheDocument()
    expect(within(humanLink).queryByTestId('icon-bar-chart3')).not.toBeInTheDocument()
    const dashboardLink = linkFor('经营看板')
    expect(within(dashboardLink).getByTestId('icon-bar-chart3')).toBeInTheDocument()
  })

  it('（#5778）「客户服务」组渲染 MessageSquare 图标（#3081 AI 客服配置菜单已移除）', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const groupButtonEl = screen.getByText('客户服务').closest('button')!
    // ⚠️ 组图标**不得**与组内任一项同图（判据 = 图标两两不同，issue #5582）——
    // 曾用 Headphones（与组内「在线接待」同图）⇒ 实测判红；改用空闲的 MessageSquare。
    expect(within(groupButtonEl).getByTestId('icon-message-square')).toBeInTheDocument()
    expect(within(groupButtonEl).queryByTestId('icon-headphones')).not.toBeInTheDocument()
  })

  it('「黄金策·在线对话」菜单入口已移除（#3094：智能体对话经右下角浮动按钮进入）', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expect(screen.queryByText('黄金策 · 在线对话')).not.toBeInTheDocument()
  })

  // ── 权限过滤 ──

  describe('Permission-based menu filtering', () => {
    it('should show all menu items for admin user with * permission', async () => {
      mockBriefingEnabled = true
      mockUseAuthStore.mockReturnValue({
        user: { id: '1', username: 'admin', name: '管理员', permissions: ['*'], roles: ['admin'] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      await waitFor(() => expect(groupButton('workspace').getAttribute('aria-expanded')).toBe('true'))
      expect(screen.getByText('工作台')).toBeInTheDocument()
      // 七大组头（含 #5271 新增的「仓储与物料」）
      for (const g of GROUPS) {
        expect(screen.getByText(g.name)).toBeInTheDocument()
      }
      expandAll()
      for (const [, name] of GROUPS.flatMap((g) => g.items)) {
        expect(screen.getByText(name)).toBeInTheDocument()
      }
      // #1403: 商品分类管理已移出侧边栏
      expect(screen.queryByText('商品分类管理')).not.toBeInTheDocument()
      expect(screen.getByText('通知中心')).toBeInTheDocument()
      // UI-005/UI-011: admin 可见智能客服大类及其子菜单（#3094 黄金策·在线对话 入口已移除）
      expect(screen.queryByText('黄金策 · 在线对话')).not.toBeInTheDocument()
      expect(menuKeys()).toHaveLength(21)
    })

    it('should filter out items user has no permission for', () => {
      mockUseAuthStore.mockReturnValue({
        user: { id: '2', username: 'operator', name: '运营', permissions: ['dashboard:view', 'order:list', 'product:list'], roles: ['operator'] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      // 有权限的（组头恒在；项要先展开该组）
      expect(screen.getByText('工作台')).toBeInTheDocument()
      // #5778：「商品管理」是**一级项**（恒渲染，不需要展开任何组）
      expect(screen.getByText('商品管理')).toBeInTheDocument()
      expect(screen.getByText('交易管理')).toBeInTheDocument()
      expandGroups('trade-center')
      expect(screen.getByText('订单列表')).toBeInTheDocument()
      expect(screen.getByText('订单列表')).toBeInTheDocument()
      // 无权限的
      expect(screen.queryByText('商品分类管理')).not.toBeInTheDocument()
      expect(screen.queryByText('加工项管理')).not.toBeInTheDocument()
      expect(screen.queryByText('售后工单')).not.toBeInTheDocument()
      // #5271: 客户列表/财务对账与订单列表**同组**（交易管理）⇒ 无码时只有它们从组内消失，组本身仍在
      expect(screen.queryByText('客户列表')).not.toBeInTheDocument()
      expect(screen.queryByText('财务对账')).not.toBeInTheDocument()
      // 旧「客户管理」组已不存在（#5271 并入交易管理）
      expect(screen.queryByText('客户管理')).not.toBeInTheDocument()
      // #2969: 组织管理组（员工+岗位权限+企业信息）整组隐藏
      expect(screen.queryByText('组织管理')).not.toBeInTheDocument()
      expect(screen.queryByText('员工管理')).not.toBeInTheDocument()
      expect(screen.queryByText('岗位权限')).not.toBeInTheDocument()
      expect(screen.queryByText('企业基础信息')).not.toBeInTheDocument()
      // 生产管理整组隐藏（四项都要 production:view / processing:view，本组权限一个都不持）
      expect(screen.queryByText('生产管理')).not.toBeInTheDocument()
      expect(screen.queryByText('入库单')).not.toBeInTheDocument()
      expect(screen.queryByText('余料台账')).not.toBeInTheDocument()
      // 🔴 issue #5699（P4）：省料看板节点码 = 该页读码 `product:list`（不再是 processing:manage）
      // ⇒ 本组权限含它 ⇒ 「仓储与物料」只剩省料看板 + 库存明细两项（不再是「整组隐藏」；库存明细 #6404 同取 `product:list`）。
      expect(screen.getByText('仓储与物料')).toBeInTheDocument()
      expandGroups('inventory-center')
      expect(screen.getByText('省料看板')).toBeInTheDocument()
      // 无 knowledge:view（知识库节点码，issue #5246 起为**读**码）→ 入口隐藏；通知中心全员可见
      expect(screen.queryByText('知识库')).not.toBeInTheDocument()
      expect(screen.getByText('通知中心')).toBeInTheDocument()
      // 可见项**精确**清单（渲染顺序）：
      // 🔴 本用例的可见项里**没有** `org-center`（员工管理要 employee:list）⇒ 一级项挂到**可见分组末尾**
      // （回落方向 = 「挂到末尾」，**不是**跳到最前）
      // 经营看板 → 订单列表 → **库存明细**（2026-10-06：紧随入库单）→ **发货单**
      // （#5939：与订单列表同码 order:list）→ 省料看板 → 商品管理（一级项）→ 通知中心
      expect(menuKeys()).toEqual(
        ['dashboard', 'orders', 'stock-ledger', 'shipments', 'production-saving-board', 'products',
          'notifications'])
      // UI-005/UI-011: 无 agent:session / knowledge:view / customer:view / after_sales:view →
      // **客户服务**整组隐藏（#5778 组名改判；#3081 已移除 AI 客服配置菜单）
      expect(screen.queryByText('客户服务')).not.toBeInTheDocument()
      expect(screen.queryByText('黄金策 · 在线对话')).not.toBeInTheDocument()
      expect(screen.queryByText('在线接待')).not.toBeInTheDocument()
    })

    it('零权限 ⇒ 只剩「通知中心」（#5699 P4：经营看板也按 dashboard:view 门控，不再是「无码全员可见」）', () => {
      mockUseAuthStore.mockReturnValue({
        user: { id: '3', username: 'newbie', name: '新人', permissions: [], roles: [] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      // 🔴 #5699 P4：经营看板节点码 = `dashboard:view` ⇒ 零权限时**工作台整组不渲染**
      //（此前它无码 ⇒ 全员可见，而页面/路由守卫都要码 = 「看得见、点进去 403」）。
      expect(screen.queryByText('工作台')).not.toBeInTheDocument()
      expect(screen.queryByText('经营看板')).not.toBeInTheDocument()
      // 分组标题应该都不在（含工作台在内，七组全空 ⇒ 整组剔除）
      for (const name of ['工作台', '客户服务', '交易管理', '订单管理', '商品与加工项', '智能客服', '生产管理', '仓储与物料', '组织管理', '客户管理']) {
        expect(screen.queryByText(name)).not.toBeInTheDocument()
      }
      expect(screen.queryByText('员工管理')).not.toBeInTheDocument()
      // 零权限唯一可见项：通知中心（**两侧都无码**，见 RBAC 的 FAIL_OPEN_PAGES 台账）
      expect(screen.getByText('通知中心')).toBeInTheDocument()
      expect(menuKeys()).toEqual(['notifications'])
      // 零权限不可见：知识库（需 knowledge:view —— issue #5246 起节点用读码）、每日简报（需 dashboard:view + 开关）
      expect(screen.queryByText('知识库')).not.toBeInTheDocument()
      expect(screen.queryByText('每日简报')).not.toBeInTheDocument()
    })

    it('有 agent:session → 保留「在线接待」（#3094 黄金策·在线对话 菜单已移除不渲染；#3081 无 AI 客服配置菜单）', () => {
      mockUseAuthStore.mockReturnValue({
        user: { id: '5', username: 'cs', name: '客服', permissions: ['agent:session'], roles: [] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      expect(screen.getByText('客户服务')).toBeInTheDocument()
      expandGroups('customer-service')
      expect(screen.queryByText('黄金策 · 在线对话')).not.toBeInTheDocument()
      expect(screen.getByText('在线接待')).toBeInTheDocument()
      expect(screen.queryByText('AI 客服配置')).not.toBeInTheDocument()
      // 组内**只有**在线接待（知识库要 knowledge:view —— issue #5246 起节点用读码）
      expect(menuKeys()).toEqual(['human-sessions', 'notifications'])   // #5699 P4：经营看板要 dashboard:view
    })

    it('仅 knowledge:view → 隐藏「在线接待」，保留「知识库」（#3094 黄金策入口已移除）', () => {
      // issue #5246（已合入 main）：『知识库』节点码从写码 `knowledge:manage` 换成**读码**
      // `knowledge:view`（拆读写：只想看知识卡片的岗位不该被授予增删改发布权）⇒ 入口可见性按读码判。
      mockUseAuthStore.mockReturnValue({
        user: { id: '6', username: 'kb', name: '知识管理员', permissions: ['knowledge:view'], roles: [] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      expect(screen.getByText('客户服务')).toBeInTheDocument()
      expandGroups('customer-service')
      expect(screen.getByText('知识库')).toBeInTheDocument()
      expect(screen.queryByText('黄金策 · 在线对话')).not.toBeInTheDocument()
      expect(screen.queryByText('在线接待')).not.toBeInTheDocument()
      expect(menuKeys()).toEqual(['knowledge', 'notifications'])   // #5699 P4：同上
    })

    it('仅 knowledge:manage（**写**码、无读码）→ 知识库入口隐藏（issue #5246 的读写分权口径）', () => {
      // 反面钉法：节点码是读码 ⇒ 只持写码的岗位看不到页面（内置岗位无人如此：admin 走 `*`，
      // 客服/运营持读码）。这与后端「写端点仍要 knowledge:manage」并不矛盾：写权限 ≠ 页面可见性；
      // 自定义岗位若只勾写码，需商家同时勾读码才能看到入口（已在 CHANGELOG/RBAC 登记）。
      mockUseAuthStore.mockReturnValue({
        user: { id: '7', username: 'kbw', name: '知识编辑', permissions: ['knowledge:manage'], roles: [] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      expect(screen.queryByText('知识库')).not.toBeInTheDocument()
      expect(screen.queryByText('客户服务')).not.toBeInTheDocument()
      // 组内四项都不可见 ⇒ 客户服务**整组剔除**（空组不渲染）；#5699 P4 后经营看板也需 dashboard:view
      expect(menuKeys()).toEqual(['notifications'])
    })

    it('售后工单走**读**码 after_sales:view；只持写码 order:refund ⇒ 入口隐藏（issue #5246）', () => {
      // 同族反面钉法在交易管理组上取一次：『售后工单』节点码 = `after_sales:view`（读码），
      // `order:refund` 是不挂在菜单节点上的**写**码 ⇒ 它不进可见性判定（否则「能退款」被当成「该看到入口」）。
      mockUseAuthStore.mockReturnValue({
        user: { id: '8', username: 'as', name: '售后', permissions: ['after_sales:view'], roles: [] },
      })
      const { unmount } = render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      // #5778：售后工单已随「服务客户」动线移入**客户服务**组（原交易管理组）
      expandGroups('customer-service')
      expect(screen.getByText('售后工单')).toBeInTheDocument()
      expect(screen.queryByText('订单列表')).not.toBeInTheDocument()
      expect(menuKeys()).toEqual(['after-sales', 'notifications'])   // #5699 P4：经营看板要 dashboard:view
      unmount()

      mockUseAuthStore.mockReturnValue({
        user: { id: '9', username: 'asw', name: '售后写', permissions: ['order:refund'], roles: [] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      expect(screen.queryByText('售后工单')).not.toBeInTheDocument()
      // 组内无可见项 ⇒ **客户服务**整组剔除（#5778：售后工单已在该组）；#5699 P4 后经营看板也需 dashboard:view
      expect(screen.queryByText('客户服务')).not.toBeInTheDocument()
      expect(screen.queryByText('交易管理')).not.toBeInTheDocument()
      expect(menuKeys()).toEqual(['notifications'])
    })

    it('两个子菜单均不可见时「智能客服」大类整组隐藏（#3094）', () => {
      mockUseAuthStore.mockReturnValue({
        user: { id: '7', username: 'nocs', name: '无客服权限', permissions: ['dashboard:view'], roles: [] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      expect(screen.queryByText('智能客服')).not.toBeInTheDocument()
      expect(screen.queryByText('黄金策 · 在线对话')).not.toBeInTheDocument()
      expect(screen.queryByText('在线接待')).not.toBeInTheDocument()
      expect(screen.queryByText('知识库')).not.toBeInTheDocument()
    })

    // #1403: 商品分类管理移出侧边栏
    it('should NOT show 商品分类管理 even for admin user (#1403)', () => {
      mockUseAuthStore.mockReturnValue({
        user: { id: '1', username: 'admin', name: '管理员', permissions: ['*'], roles: ['admin'] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      expect(screen.queryByText('商品分类管理')).not.toBeInTheDocument()
    })

    it('should hide entire group when all children are filtered out', () => {
      mockUseAuthStore.mockReturnValue({
        user: { id: '4', username: 'partial', name: '部分权限', permissions: ['dashboard:view', 'order:list'], roles: [] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      // 交易管理 group should show (has order:list)
      expect(screen.getByText('交易管理')).toBeInTheDocument()
      expandGroups('trade-center')
      expect(screen.getByText('订单列表')).toBeInTheDocument()
      // 但售后工单不应该出现
      expect(screen.queryByText('售后工单')).not.toBeInTheDocument()
      // 商品与加工项 group should be completely hidden（无 product:list / processing:manage）
      expect(screen.queryByText('商品与加工项')).not.toBeInTheDocument()
      expect(menuKeys()).toEqual(['dashboard', 'orders', 'notifications'])
    })

    // ── #5271 新组的权限边界（正负控：菜单可见性与页面门禁同码，不互相顶替）──

    it('入库单（inbound:view）与余料台账（processing:manage）**互不顶替**：正负控双向', async () => {
      // ① 只有 inbound:view ⇒ 仓储与物料组仍在（入库单可见），余料台账/省料看板不在
      mockUseAuthStore.mockReturnValue({
        user: { id: '8', username: 'wh', name: '仓管', permissions: ['inbound:view'], roles: [] },
      })
      const { unmount } = render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      expect(screen.getByText('仓储与物料')).toBeInTheDocument()
      expandGroups('inventory-center')
      expect(screen.getByText('入库单')).toBeInTheDocument()
      expect(screen.queryByText('余料台账')).not.toBeInTheDocument()
      expect(screen.queryByText('省料看板')).not.toBeInTheDocument()
      expect(menuKeys()).toEqual(['inbound-orders', 'notifications'])   // #5699 P4：经营看板要 dashboard:view
      unmount()

      // ② 只有 processing:manage ⇒ 入库单**不在**（独立门禁，不因同组而放行），余料台账/省料看板在
      mockUseAuthStore.mockReturnValue({
        user: { id: '9', username: 'op', name: '生产', permissions: ['processing:manage'], roles: [] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      // ⚠️ 只展开仓储组：生产组在本组权限下**整组被剔除**（没有 toggle 可点）——
      // 这本身就是 #5699 P4 后的读数（生产组四项分别要 production:view / processing:view）。
      expandGroups('inventory-center')
      expect(screen.getByText('余料台账')).toBeInTheDocument()
      expect(screen.queryByText('入库单')).not.toBeInTheDocument()
      // issue #5291：生产看板/计件工资 改挂读码 production:view ⇒ 只持 processing:manage 时不在
      //（#6580：「加工项管理」「工艺配置」两个菜单项已移除）；
      // 🔴 issue #5699（P4）：省料看板节点码 = 该页读码 `product:list`，**智能派单节点码 = processing:view**
      // ⇒ 只持 processing:manage 时两者都**不在**（仓储组只剩余料台账、生产组整组剔除）。
      expect(screen.queryByText('省料看板')).not.toBeInTheDocument()
      expect(screen.queryByText('智能派单')).not.toBeInTheDocument()
      expect(screen.queryByText('生产管理')).not.toBeInTheDocument()
      expect(menuKeys()).toEqual(['production-remnants', 'notifications'])
    })
  })

  // ── 菜单图标两两不同（issue #5582）─────────────────────────────────────────────

  it('🔴 菜单图标两两不同（渲染面）：21 项的图标互不重复（issue #5582）', async () => {
    // 用户实测「左侧菜单栏有部分子菜单的图标完全一样」——数据层去重（menu-icons.test.ts 判据④）
    // 只证明**配置**不重复；这里证明**渲染出来**的图标也不重复（§15.1 结果可见）。
    // 「每日简报」挂在企业简报开关上（`briefingToggle`，缺省关 ⇒ 不渲染）⇒ 本判据要先把它打开，
    // 否则 21 项只到 20 项（本单实测踩过一次：`Unable to find text: 每日简报`）。
    mockBriefingEnabled = true
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    // 简报开关的可见性是**异步**拉配置决定的（同文件既有用例的写法）⇒ 等它到位再展开
    await waitFor(() => expect(screen.getByText('每日简报')).toBeInTheDocument())
    expandAll()

    // #5778：加上**一级项**「商品管理」（#5877 起渲染在「工作台」组之后、不属于任何组）；
    // #6580：并列第二个一级项「企业基础设置」（紧随其后的板块入口，席位原属「参数总览」）
    const items: [string, string][] = [
      ['products', '商品管理'],
      ['settings', '企业基础设置'],
      ...GROUPS.flatMap((g) => g.items),
      ['notifications', '通知中心'],
    ]
    const byIcon = new Map<string, string[]>()
    for (const [, name] of items) {
      const link = linkFor(name)
      // tests/setup.ts 的 lucide 夹具把每个图标渲染成 `data-testid="icon-<kebab>"` ⇒ 从**渲染结果**反读图标名
      const icon =
        link.querySelector('[data-testid^="icon-"]')?.getAttribute('data-testid')?.replace(/^icon-/, '') ?? '(无图标)'
      byIcon.set(icon, [...(byIcon.get(icon) ?? []), name])
    }

    const collisions = [...byIcon.entries()]
      .filter(([, names]) => names.length > 1)
      .map(([icon, names]) => `${icon} → ${names.join('、')}`)

    expect(items, '面非空自证：21 项（2 一级项 + 18 组内项 + 通知中心；#6404 +库存明细；#6580 生产组收拢 + 一级项改「企业基础设置」）').toHaveLength(21)
    expect(
      collisions,
      `以下菜单项在侧边栏里渲染出**同一个图标**（紧挨着出现 = 没有区分度，issue #5582）：\n${collisions.join('\n')}\n`
        + '出口：给后出现的那一项换一个语义相近的 lucide 图标（menu.ts + menu-icons.ts + tests/setup.ts 白名单三处同批）。',
    ).toEqual([])
    expect(byIcon.size).toBe(items.length)
  })

  // ── 「常用（收藏）」渲染面（#5778：用户自己钉 4~6 项，pin 在侧边栏顶部）──

  describe('常用（收藏）', () => {
    beforeEach(() => {
      window.localStorage.clear()
      mockBriefingEnabled = true
      mockUsePathname.mockReturnValue('/dashboard')
      mockUseAuthStore.mockReturnValue({
        user: { id: '1', username: 'admin', name: '管理员', permissions: ['*'], roles: ['admin'] },
      })
    })

    it('未钉任何项 ⇒ **整个「常用」区不渲染**（不留空标题），且每项有一枚可点的星标', async () => {
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      await waitFor(() => expect(groupButton('workspace').getAttribute('aria-expanded')).toBe('true'))
      expect(document.querySelector('[data-group-key="pinned"]')).toBeNull()
      expect(screen.queryByText('常用')).not.toBeInTheDocument()
      // 星标在（当前项恒显、其余 hover 才显 —— 但按钮元素一直在 DOM 里）
      // ⚠️ 交易管理组默认收起 ⇒ 先展开再断言（不是「找不到就等于没有」）
      expandGroups('trade-center')
      expect(screen.getByTestId('sidebar-pin-orders')).toBeInTheDocument()
      expect(screen.getByTestId('sidebar-pin-orders').getAttribute('data-pinned')).toBe('false')
    })

    it('点星标 ⇒ 该项进入顶部「常用」区（`data-group-key="pinned"`）+ 计数 `1/6` + 落盘 localStorage', async () => {
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      await waitFor(() => expect(groupButton('workspace').getAttribute('aria-expanded')).toBe('true'))
      expandGroups('trade-center')

      fireEvent.click(screen.getByTestId('sidebar-pin-orders'))

      const pinnedSec = document.querySelector('[data-group-key="pinned"]') as HTMLElement
      expect(pinnedSec).toBeTruthy()
      expect(within(pinnedSec).getByText('常用')).toBeInTheDocument()
      expect(screen.getByTestId('sidebar-pinned-count').textContent).toBe('1/6')
      // 钉住的项在「常用」区里可点，且 href 正确
      expect(within(pinnedSec).getByText('订单列表')).toBeInTheDocument()
      expect(within(pinnedSec).getByText('订单列表').closest('a')).toHaveAttribute('href', '/orders')
      // 渲染序（#5877）：**常用**区在最顶部 → 「工作台」组 → 一级项 → 其余组 → 尾部独立项
      const allKeys = menuKeys()
      expect(allKeys[0]).toBe('orders')
      expect(allKeys[1]).toBe('dashboard')
      expect(allKeys.indexOf('products')).toBeGreaterThan(allKeys.indexOf('briefing'))
      // 反恒真：orders 在交易管理组里**也**渲染（常用区是快捷方式，不是搬家）
      expect(allKeys.filter((k) => k === 'orders')).toHaveLength(2)
      // 落盘（键名与纯函数同源常量）
      const raw = window.localStorage.getItem('migao.sidebar.pinned.v1')
      expect(JSON.parse(raw!)).toEqual(['orders'])
      // 星标状态翻成已钉（钉住后该项在「常用」区与域内各一枚 ⇒ 两枚都是已钉态）
      const pins = screen.getAllByTestId('sidebar-pin-orders')
      expect(pins.length).toBeGreaterThanOrEqual(2)
      for (const el of pins) expect(el.getAttribute('data-pinned')).toBe('true')
    })

    it('🔴 取消钉住 ⇒ 「常用」区消失（清单为空）+ 落盘为空表', async () => {
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      await waitFor(() => expect(groupButton('workspace').getAttribute('aria-expanded')).toBe('true'))
      expandGroups('trade-center')

      fireEvent.click(screen.getByTestId('sidebar-pin-orders'))
      expect(document.querySelector('[data-group-key="pinned"]')).toBeTruthy()

      // 「常用」区里那一枚永远可见 ⇒ 再点它即取消（取「常用」区内的那一枚，避开拓扑歧义）
      const pinnedSec = document.querySelector('[data-group-key="pinned"]') as HTMLElement
      fireEvent.click(within(pinnedSec).getByTestId('sidebar-pin-orders'))
      expect(document.querySelector('[data-group-key="pinned"]')).toBeNull()
      expect(JSON.parse(window.localStorage.getItem('migao.sidebar.pinned.v1')!)).toEqual([])
    })

    it('启动时从 localStorage 恢复（惰性：首帧为空、effect 后出现）—— 恢复的项不可见（无权）则整区不渲染', async () => {
      window.localStorage.setItem('migao.sidebar.pinned.v1', JSON.stringify(['orders']))
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      await waitFor(() => {
        expect(document.querySelector('[data-group-key="pinned"]')).toBeTruthy()
      })
      // 换成只持 product:list 的账号 ⇒ orders 无权 ⇒ 常用区整区消失（权限优先于偏好）
      cleanup()
      window.localStorage.setItem('migao.sidebar.pinned.v1', JSON.stringify(['orders']))
      mockUseAuthStore.mockReturnValue({
        user: { id: '2', username: 'pm', name: '商品', permissions: ['product:list'], roles: [] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      await waitFor(() => expect(screen.getByText('商品管理')).toBeInTheDocument())
      expect(document.querySelector('[data-group-key="pinned"]')).toBeNull()
    })

    it('🔴 localStorage 里残留一级项 `products` ⇒ 「常用」区**不出现**它（只剩 orders，计数 1/6）', async () => {
      // 旧版本用户可以钉过它（那时它还有星标）⇒ 升级后必须**静默丢弃**，不能出现两条一模一样的入口
      window.localStorage.setItem('migao.sidebar.pinned.v1', JSON.stringify(['products', 'orders']))
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      // 正信号：先等「常用」区真的出现（否则下面两条可能是「还没恢复完」的假绿）
      await waitFor(() => expect(document.querySelector('[data-group-key="pinned"]')).toBeTruthy())
      const pinnedSec = document.querySelector('[data-group-key="pinned"]') as HTMLElement
      expect(within(pinnedSec).queryByText('商品管理')).toBeNull()
      expect(within(pinnedSec).getByText('订单列表')).toBeInTheDocument()
      expect(screen.getByTestId('sidebar-pinned-count').textContent).toBe('1/6')
      // 一级项本身**照旧渲染一次**（不进「常用」≠ 从侧边栏消失）
      expect(screen.getAllByText('商品管理')).toHaveLength(1)
      expect(menuKeys().filter((k) => k === 'products')).toHaveLength(1)
    })

    it('钉满 6 项后再钉第 7 项 ⇒ **被拒**（计数停在 6/6、localStorage 不含第 7 项）', async () => {
      // 🔴 #6580：原第 6 项用 `settings` —— 它已升为**一级项**（板块入口无星标、不可钉）⇒
      // 换成同为组内项的「发货单」（组内项才有星标），本用例的口径（钉满 6 项后被拒）一字不变。
      const six = ['orders', 'finance', 'customers', 'employees', 'roles', 'shipments']
      window.localStorage.setItem('migao.sidebar.pinned.v1', JSON.stringify(six))
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      await waitFor(() => expect(document.querySelector('[data-group-key="pinned"]')).toBeTruthy())
      expect(screen.getByTestId('sidebar-pinned-count').textContent).toBe('6/6')

      expandGroups('inventory-center')
      fireEvent.click(screen.getByTestId('sidebar-pin-inbound-orders'))

      expect(screen.getByTestId('sidebar-pinned-count').textContent).toBe('6/6')
      expect(JSON.parse(window.localStorage.getItem('migao.sidebar.pinned.v1')!)).toEqual(six)
      expect(screen.getByTestId('sidebar-pin-inbound-orders').getAttribute('data-pinned')).toBe('false')
    })
  })
})
