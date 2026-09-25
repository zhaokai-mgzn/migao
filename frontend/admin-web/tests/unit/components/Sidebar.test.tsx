// case_ids: HR-001, DF-007, UI-005, UI-011, UI-028, PR-038, PR-106
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
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
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

/** issue #5271 新 IA：7 组（key / 组名 / 组内项顺序） */
const GROUPS: { key: string; name: string; items: [string, string][] }[] = [
  { key: 'workspace', name: '工作台', items: [['dashboard', '经营看板'], ['briefing', '每日简报']] },
  { key: 'smart-customer-service', name: '智能客服', items: [['human-sessions', '在线接待'], ['knowledge', '知识库']] },
  { key: 'product-center', name: '商品与加工项', items: [['products', '商品列表'], ['processing', '加工项管理']] },
  {
    key: 'trade-center',
    name: '交易管理',
    items: [['orders', '订单列表'], ['after-sales', '售后工单'], ['customers', '客户列表'], ['finance', '财务对账']],
  },
  {
    key: 'production-center',
    name: '生产管理',
    items: [
      ['production-board', '生产看板'],
      ['production-pool', '智能派单'],
      ['production-process', '工艺配置'],
      ['production-piecework', '计件工资'],
    ],
  },
  {
    key: 'inventory-center',
    name: '仓储与物料',
    items: [
      ['inbound-orders', '入库单'],
      ['production-remnants', '余料台账'],
      ['production-saving-board', '省料看板'],
    ],
  },
  {
    key: 'org-center',
    name: '组织管理',
    items: [['employees', '员工管理'], ['roles', '岗位权限'], ['settings', '企业基础信息']],
  },
]
const GROUP_KEYS = GROUPS.map((g) => g.key)
/** 展开全部组后应渲染的 21 项（分组项在前、独立项在后） */
const ALL_MENU_KEYS = [...GROUPS.flatMap((g) => g.items.map(([k]) => k)), 'notifications']

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

  it('未设置企业 Logo 时回退米高默认 Logo', () => {
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

  it('should render all menu items（issue #5271 新 IA：7 组 21 项）', async () => {
    mockBriefingEnabled = true
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    // 分组标题（#5271 重排后七大组：商品与加工项 / 交易管理 / 生产管理 / 仓储与物料）
    expect(screen.getByText('工作台')).toBeInTheDocument()
    expect(screen.getByText('智能客服')).toBeInTheDocument()
    expect(screen.getByText('商品与加工项')).toBeInTheDocument()
    expect(screen.getByText('交易管理')).toBeInTheDocument()
    expect(screen.getByText('生产管理')).toBeInTheDocument()
    expect(screen.getByText('仓储与物料')).toBeInTheDocument()
    expect(screen.getByText('组织管理')).toBeInTheDocument()
    // 旧组名不再出现（#5271：商品管理 → 商品与加工项；订单管理/客户管理 → 交易管理）
    expect(screen.queryByText('商品管理')).not.toBeInTheDocument()
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
    // UI-005/UI-011: 智能客服分组下 在线接待 + 知识库（#3094 米宝·在线对话 菜单入口已移除，对话经右下角 FAB）；#2969 知识库并入本组；#3081 AI 客服配置已合并进企业基础信息
    expect(screen.queryByText('米宝 · 在线对话')).not.toBeInTheDocument()
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

  it('21 项一项不少不减：`data-menu-key` 序列逐值 == 新 IA（分组项在前、独立项在后）', async () => {
    mockBriefingEnabled = true
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    await waitFor(() => expect(groupButton('workspace').getAttribute('aria-expanded')).toBe('true'))
    expandAll()
    expect(menuKeys()).toEqual([
      'dashboard', 'briefing',
      'human-sessions', 'knowledge',
      'products', 'processing',
      'orders', 'after-sales', 'customers', 'finance',
      'production-board', 'production-pool', 'production-process', 'production-piecework',
      'inbound-orders', 'production-remnants', 'production-saving-board',
      'employees', 'roles', 'settings',
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
    expect(linkFor('商品列表')).toHaveAttribute('href', '/products')
    expect(linkFor('加工项管理')).toHaveAttribute('href', '/production/processing')
    expect(linkFor('订单列表')).toHaveAttribute('href', '/orders')
    expect(linkFor('售后工单')).toHaveAttribute('href', '/after-sales')
    expect(linkFor('客户列表')).toHaveAttribute('href', '/customers')
    expect(linkFor('财务对账')).toHaveAttribute('href', '/finance')
    expect(linkFor('生产看板')).toHaveAttribute('href', '/production')
    expect(linkFor('智能派单')).toHaveAttribute('href', '/production/pool')
    expect(linkFor('工艺配置')).toHaveAttribute('href', '/production/routings')
    expect(linkFor('计件工资')).toHaveAttribute('href', '/production/piecework')
    // issue #5271：面料进出与消耗移入新组「仓储与物料」（原生产管理组）
    expect(linkFor('入库单')).toHaveAttribute('href', '/inbound-orders')
    expect(linkFor('余料台账')).toHaveAttribute('href', '/production/remnants')
    expect(linkFor('省料看板')).toHaveAttribute('href', '/production/saving-board')
    expect(linkFor('员工管理')).toHaveAttribute('href', '/employees')
    expect(linkFor('岗位权限')).toHaveAttribute('href', '/roles')
    expect(linkFor('企业基础信息')).toHaveAttribute('href', '/settings')
    // #3094: 米宝 · 在线对话 菜单入口已移除（侧边栏不再渲染 /chat 链接）
    expect(screen.queryByText('米宝 · 在线对话')).not.toBeInTheDocument()
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
    expect(screen.queryByText('米高')).not.toBeInTheDocument()
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
    // /products 是「商品与加工项」组 ⇒ 该组默认展开（新交互 ①②）
    const link = linkFor('商品列表')
    expect(getActiveClass(link)).toContain('bg-primary-600')
  })

  it('should not highlight inactive menu items', () => {
    mockUsePathname.mockReturnValue('/dashboard')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    // 非当前组默认收起 ⇒ 先展开「商品与加工项」再断言它**不高亮**（断言强度不变）
    expandGroups('product-center')
    const link = linkFor('商品列表')
    expect(getActiveClass(link)).not.toContain('bg-primary-600')
  })

  it('should highlight nested route for /products/123', () => {
    mockUsePathname.mockReturnValue('/products/123')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const link = linkFor('商品列表')
    expect(getActiveClass(link)).toContain('bg-primary-600')
  })

  it('should highlight for root path as dashboard', () => {
    mockUsePathname.mockReturnValue('/')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const link = linkFor('经营看板')
    expect(getActiveClass(link)).toContain('bg-primary-600')
  })

  // ── 前缀嵌套路由互斥单高亮（#3094 米宝菜单已移除：/chat 无侧边栏入口，在线接待不重复高亮）──

  it('/chat 时无侧边栏菜单高亮（米宝入口已移除，对话经右下角 FAB）', () => {
    mockUsePathname.mockReturnValue('/chat')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expect(screen.queryByText('米宝 · 在线对话')).not.toBeInTheDocument()
    // /chat 不属于任何菜单项 ⇒ 无组可展开；展开智能客服后「在线接待」仍在 DOM 且不得高亮
    expandGroups('smart-customer-service')
    const humanLink = linkFor('在线接待')
    expect(getActiveClass(humanLink)).not.toContain('bg-primary-600')
  })

  it('/chat 时侧边栏无高亮菜单项（#3094 米宝入口已移除）', async () => {
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
    const ordersLink = linkFor('订单列表')
    const afterSalesLink = linkFor('售后工单')
    expect(getActiveClass(ordersLink)).toContain('bg-primary-600')
    expect(getActiveClass(afterSalesLink)).not.toContain('bg-primary-600')
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
    // /dashboard ⇒ 「商品与加工项」默认**收起**（新交互 ①），故先点开、再点收
    expect(screen.queryByText('商品列表')).not.toBeInTheDocument()
    expect(groupButton('product-center').getAttribute('aria-expanded')).toBe('false')

    await user.click(screen.getByText('商品与加工项'))
    expect(screen.getByText('商品列表')).toBeInTheDocument()
    expect(groupButton('product-center').getAttribute('aria-expanded')).toBe('true')

    await user.click(screen.getByText('商品与加工项'))
    expect(screen.queryByText('商品列表')).not.toBeInTheDocument()
    expect(groupButton('product-center').getAttribute('aria-expanded')).toBe('false')
  })

  // ── 独立菜单项 ──

  it('should render standalone items exactly once each', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    // #5271: 交易管理是**唯一**的合并组（原「订单管理」+「客户管理」组的客户列表/财务对账）
    expect(screen.getAllByText('交易管理').length).toBe(1)
    expect(screen.getAllByText('商品与加工项').length).toBe(1)
    // #3081: AI 客服配置已移除（合并进企业基础信息），不再渲染
    expect(screen.queryByText('AI 客服配置')).not.toBeInTheDocument()
    // #2969: 岗位权限归入组织管理组（唯一）—— 该组默认收起，先展开；通知中心仍为独立菜单（唯一）
    expandGroups('org-center')
    expect(screen.getAllByText('岗位权限').length).toBe(1)
    expect(screen.getAllByText('通知中心').length).toBe(1)
  })

  // ── UI-005: 智能客服大类分组与图标 ──

  it('「智能客服」大类位于「工作台」之后、「商品与加工项」之前', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const workspace = screen.getByText('工作台')
    const smartCs = screen.getByText('智能客服')
    const productCenter = screen.getByText('商品与加工项')
    const follows = (a: HTMLElement, b: HTMLElement) =>
      (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0
    expect(follows(workspace, smartCs)).toBe(true)
    expect(follows(smartCs, productCenter)).toBe(true)
  })

  it('「智能客服」下子菜单顺序：在线接待 在前、知识库次之（#2969/#3081/#3094 米宝·在线对话 入口已移除）', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expandGroups('smart-customer-service')
    const groupContainer = screen.getByText('智能客服').closest('[data-group-key]') as HTMLElement
    const links = groupContainer.querySelectorAll('a')
    expect(links.length).toBe(2)
    expect(links[0].textContent).toContain('在线接待')
    expect(links[1].textContent).toContain('知识库')
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
    // 在线接待整体仍存在（移入智能客服分组）
    expandGroups('smart-customer-service')
    expect(screen.getByText('在线接待')).toBeInTheDocument()
  })

  it('「在线接待」渲染 Headphones 图标，与「经营看板」BarChart3 图标明确区分', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expandGroups('smart-customer-service')
    const humanLink = linkFor('在线接待')
    expect(within(humanLink).getByTestId('icon-headphones')).toBeInTheDocument()
    expect(within(humanLink).queryByTestId('icon-bar-chart3')).not.toBeInTheDocument()
    const dashboardLink = linkFor('经营看板')
    expect(within(dashboardLink).getByTestId('icon-bar-chart3')).toBeInTheDocument()
  })

  it('「智能客服」大类渲染 MessageSquare 图标（#3081 AI 客服配置菜单已移除）', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const groupButtonEl = screen.getByText('智能客服').closest('button')!
    expect(within(groupButtonEl).getByTestId('icon-message-square')).toBeInTheDocument()
  })

  it('「米宝·在线对话」菜单入口已移除（#3094：智能体对话经右下角浮动按钮进入）', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expect(screen.queryByText('米宝 · 在线对话')).not.toBeInTheDocument()
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
      // UI-005/UI-011: admin 可见智能客服大类及其子菜单（#3094 米宝·在线对话 入口已移除）
      expect(screen.queryByText('米宝 · 在线对话')).not.toBeInTheDocument()
      expect(menuKeys()).toHaveLength(21)
    })

    it('should filter out items user has no permission for', () => {
      mockUseAuthStore.mockReturnValue({
        user: { id: '2', username: 'operator', name: '运营', permissions: ['dashboard:view', 'order:list', 'product:list'], roles: ['operator'] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      // 有权限的（组头恒在；项要先展开该组）
      expect(screen.getByText('工作台')).toBeInTheDocument()
      expect(screen.getByText('商品与加工项')).toBeInTheDocument()
      expect(screen.getByText('交易管理')).toBeInTheDocument()
      expandGroups('product-center', 'trade-center')
      expect(screen.getByText('商品列表')).toBeInTheDocument()
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
      // #5271: 生产管理 / 仓储与物料整组隐藏（无 processing:manage / inbound:view）
      expect(screen.queryByText('生产管理')).not.toBeInTheDocument()
      expect(screen.queryByText('仓储与物料')).not.toBeInTheDocument()
      expect(screen.queryByText('入库单')).not.toBeInTheDocument()
      expect(screen.queryByText('余料台账')).not.toBeInTheDocument()
      // 无 knowledge:view（知识库节点码，issue #5246 起为**读**码）→ 入口隐藏；通知中心全员可见
      expect(screen.queryByText('知识库')).not.toBeInTheDocument()
      expect(screen.getByText('通知中心')).toBeInTheDocument()
      // 可见项**精确**清单：经营看板（无码）+ 商品列表 + 订单列表 + 通知中心
      expect(menuKeys()).toEqual(['dashboard', 'products', 'orders', 'notifications'])
      // UI-005/UI-011: 无 agent:session / knowledge:view → 智能客服整组隐藏（#3081 已移除 AI 客服配置菜单）
      expect(screen.queryByText('智能客服')).not.toBeInTheDocument()
      expect(screen.queryByText('米宝 · 在线对话')).not.toBeInTheDocument()
      expect(screen.queryByText('在线接待')).not.toBeInTheDocument()
    })

    it('should show only dashboard when user has no permissions', () => {
      mockUseAuthStore.mockReturnValue({
        user: { id: '3', username: 'newbie', name: '新人', permissions: [], roles: [] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      expect(screen.getByText('工作台')).toBeInTheDocument()
      expect(screen.getByText('经营看板')).toBeInTheDocument()
      // 分组标题应该都不在（除工作台外六组全空 ⇒ 整组剔除）
      for (const name of ['商品与加工项', '交易管理', '订单管理', '智能客服', '生产管理', '仓储与物料', '组织管理', '客户管理']) {
        expect(screen.queryByText(name)).not.toBeInTheDocument()
      }
      expect(screen.queryByText('员工管理')).not.toBeInTheDocument()
      // 零权限也可见：通知中心（无权限码，全员）；经营看板同理
      expect(screen.getByText('通知中心')).toBeInTheDocument()
      expect(menuKeys()).toEqual(['dashboard', 'notifications'])
      // 零权限不可见：知识库（需 knowledge:view —— issue #5246 起节点用读码）、每日简报（需 dashboard:view + 开关）
      expect(screen.queryByText('知识库')).not.toBeInTheDocument()
      expect(screen.queryByText('每日简报')).not.toBeInTheDocument()
    })

    it('有 agent:session → 保留「在线接待」（#3094 米宝·在线对话 菜单已移除不渲染；#3081 无 AI 客服配置菜单）', () => {
      mockUseAuthStore.mockReturnValue({
        user: { id: '5', username: 'cs', name: '客服', permissions: ['agent:session'], roles: [] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      expect(screen.getByText('智能客服')).toBeInTheDocument()
      expandGroups('smart-customer-service')
      expect(screen.queryByText('米宝 · 在线对话')).not.toBeInTheDocument()
      expect(screen.getByText('在线接待')).toBeInTheDocument()
      expect(screen.queryByText('AI 客服配置')).not.toBeInTheDocument()
      // 组内**只有**在线接待（知识库要 knowledge:view —— issue #5246 起节点用读码）
      expect(menuKeys()).toEqual(['dashboard', 'human-sessions', 'notifications'])
    })

    it('仅 knowledge:view → 隐藏「在线接待」，保留「知识库」（#3094 米宝入口已移除）', () => {
      // issue #5246（已合入 main）：『知识库』节点码从写码 `knowledge:manage` 换成**读码**
      // `knowledge:view`（拆读写：只想看知识卡片的岗位不该被授予增删改发布权）⇒ 入口可见性按读码判。
      mockUseAuthStore.mockReturnValue({
        user: { id: '6', username: 'kb', name: '知识管理员', permissions: ['knowledge:view'], roles: [] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      expect(screen.getByText('智能客服')).toBeInTheDocument()
      expandGroups('smart-customer-service')
      expect(screen.getByText('知识库')).toBeInTheDocument()
      expect(screen.queryByText('米宝 · 在线对话')).not.toBeInTheDocument()
      expect(screen.queryByText('在线接待')).not.toBeInTheDocument()
      expect(menuKeys()).toEqual(['dashboard', 'knowledge', 'notifications'])
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
      expect(screen.queryByText('智能客服')).not.toBeInTheDocument()
      // 组内两项都不可见 ⇒ 智能客服**整组剔除**（空组不渲染）
      expect(menuKeys()).toEqual(['dashboard', 'notifications'])
    })

    it('售后工单走**读**码 after_sales:view；只持写码 order:refund ⇒ 入口隐藏（issue #5246）', () => {
      // 同族反面钉法在交易管理组上取一次：『售后工单』节点码 = `after_sales:view`（读码），
      // `order:refund` 是不挂在菜单节点上的**写**码 ⇒ 它不进可见性判定（否则「能退款」被当成「该看到入口」）。
      mockUseAuthStore.mockReturnValue({
        user: { id: '8', username: 'as', name: '售后', permissions: ['after_sales:view'], roles: [] },
      })
      const { unmount } = render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      expandGroups('trade-center')
      expect(screen.getByText('售后工单')).toBeInTheDocument()
      expect(screen.queryByText('订单列表')).not.toBeInTheDocument()
      expect(menuKeys()).toEqual(['dashboard', 'after-sales', 'notifications'])
      unmount()

      mockUseAuthStore.mockReturnValue({
        user: { id: '9', username: 'asw', name: '售后写', permissions: ['order:refund'], roles: [] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      expect(screen.queryByText('售后工单')).not.toBeInTheDocument()
      // 组内无可见项 ⇒ 交易管理整组剔除
      expect(screen.queryByText('交易管理')).not.toBeInTheDocument()
      expect(menuKeys()).toEqual(['dashboard', 'notifications'])
    })

    it('两个子菜单均不可见时「智能客服」大类整组隐藏（#3094）', () => {
      mockUseAuthStore.mockReturnValue({
        user: { id: '7', username: 'nocs', name: '无客服权限', permissions: ['dashboard:view'], roles: [] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      expect(screen.queryByText('智能客服')).not.toBeInTheDocument()
      expect(screen.queryByText('米宝 · 在线对话')).not.toBeInTheDocument()
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
      expect(menuKeys()).toEqual(['dashboard', 'inbound-orders', 'notifications'])
      unmount()

      // ② 只有 processing:manage ⇒ 入库单**不在**（独立门禁，不因同组而放行），余料台账/省料看板在
      mockUseAuthStore.mockReturnValue({
        user: { id: '9', username: 'op', name: '生产', permissions: ['processing:manage'], roles: [] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      expandGroups('inventory-center', 'production-center')
      expect(screen.getByText('余料台账')).toBeInTheDocument()
      expect(screen.getByText('省料看板')).toBeInTheDocument()
      expect(screen.queryByText('入库单')).not.toBeInTheDocument()
      // issue #5291：生产看板/工艺配置/计件工资 改挂读码 production:view ⇒
      // 只持 processing:manage 时它们**不在**（生产组只剩智能派单），生产组与仓储组仍各自成立。
      expect(menuKeys()).toEqual([
        'dashboard',
        'production-pool',
        'production-remnants',
        'production-saving-board',
        'notifications',
      ])
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

    const items: [string, string][] = [...GROUPS.flatMap((g) => g.items), ['notifications', '通知中心']]
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

    expect(items, '面非空自证：21 项（20 组内项 + 通知中心）').toHaveLength(21)
    expect(
      collisions,
      `以下菜单项在侧边栏里渲染出**同一个图标**（紧挨着出现 = 没有区分度，issue #5582）：\n${collisions.join('\n')}\n`
        + '出口：给后出现的那一项换一个语义相近的 lucide 图标（menu.ts + menu-icons.ts + tests/setup.ts 白名单三处同批）。',
    ).toEqual([])
    expect(byIcon.size).toBe(items.length)
  })
})