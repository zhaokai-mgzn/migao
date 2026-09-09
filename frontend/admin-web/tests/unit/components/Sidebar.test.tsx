// case_ids: HR-001, DF-007, UI-005, UI-011, UI-028
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
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

import Sidebar from '@/components/layout/Sidebar'

describe('Sidebar', () => {
  const user = userEvent.setup()
  const mockOnToggle = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
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

  it('should render all menu items', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    // 分组标题（#2969 七大组）
    expect(screen.getByText('工作台')).toBeInTheDocument()
    expect(screen.getByText('智能客服')).toBeInTheDocument()
    expect(screen.getByText('商品管理')).toBeInTheDocument()
    expect(screen.getByText('订单管理')).toBeInTheDocument()
    expect(screen.getByText('客户管理')).toBeInTheDocument() // 客户管理组（客户列表+财务对账）
    expect(screen.getByText('组织管理')).toBeInTheDocument()  // 组织管理组（员工+岗位权限+企业信息）
    // 子菜单项
    expect(screen.getByText('经营看板')).toBeInTheDocument()
    // UI-005/UI-011: 智能客服分组下 人工客服 + 知识库（#3094 米宝·在线对话 菜单入口已移除，对话经右下角 FAB）；#2969 知识库并入本组；#3081 AI 客服配置已合并进企业基础信息
    expect(screen.queryByText('米宝 · 在线对话')).not.toBeInTheDocument()
    expect(screen.getByText('人工客服')).toBeInTheDocument()
    expect(screen.getByText('知识库')).toBeInTheDocument()
    expect(screen.getByText('商品列表')).toBeInTheDocument()
    // #1403: 商品分类管理已移出侧边栏，入口内嵌到新增商品页
    expect(screen.queryByText('商品分类管理')).not.toBeInTheDocument()
    expect(screen.getByText('加工项管理')).toBeInTheDocument()
    // #2969: 岗位权限（原角色权限）归入组织管理组，入口应显示（system:manage 权限，admin 全权限）
    expect(screen.getByText('岗位权限')).toBeInTheDocument()
    // 通知中心（全员）入口可见
    expect(screen.getByText('通知中心')).toBeInTheDocument()
    expect(screen.getByText('订单列表')).toBeInTheDocument()
    expect(screen.getByText('售后工单')).toBeInTheDocument()
    // 客户管理组子项（#2969：客户列表 + 财务对账）
    expect(screen.getByText('客户列表')).toBeInTheDocument()
    expect(screen.getByText('财务对账')).toBeInTheDocument()
    // 组织管理组子项
    expect(screen.getByText('员工管理')).toBeInTheDocument()
    expect(screen.getByText('企业基础信息')).toBeInTheDocument()
    // UI-005: 「机器人设置」已更名为「AI 客服配置」，不再出现旧名
    expect(screen.queryByText('机器人设置')).not.toBeInTheDocument()
    // #2969: 「角色权限」已改名「岗位权限」，旧名不再出现
    expect(screen.queryByText('角色权限')).not.toBeInTheDocument()
  })

  it('should render navigation links with correct paths', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expect(screen.getByText('经营看板').closest('a')).toHaveAttribute('href', '/dashboard')
    expect(screen.getByText('商品列表').closest('a')).toHaveAttribute('href', '/products')
    expect(screen.getByText('订单列表').closest('a')).toHaveAttribute('href', '/orders')
    // #3094: 米宝 · 在线对话 菜单入口已移除（侧边栏不再渲染 /chat 链接）
    expect(screen.queryByText('米宝 · 在线对话')).not.toBeInTheDocument()
    expect(screen.getByText('人工客服').closest('a')).toHaveAttribute('href', '/agent-workspace/human-sessions')
    expect(screen.getByText('知识库').closest('a')).toHaveAttribute('href', '/knowledge')
    expect(screen.getByText('通知中心').closest('a')).toHaveAttribute('href', '/notifications')
  })

  // ── 折叠状态 ──

  it('should hide text labels when collapsed', () => {
    render(<Sidebar collapsed={true} onToggle={mockOnToggle} />)
    expect(screen.queryByText('工作台')).not.toBeInTheDocument()
    expect(screen.queryByText('米高')).not.toBeInTheDocument()
    expect(screen.queryByText('商品管理')).not.toBeInTheDocument()
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
    const link = screen.getByText('经营看板').closest('a')!
    expect(getActiveClass(link)).toContain('bg-primary-600')
  })

  it('should highlight active menu item for /products', () => {
    mockUsePathname.mockReturnValue('/products')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const link = screen.getByText('商品列表').closest('a')!
    expect(getActiveClass(link)).toContain('bg-primary-600')
  })

  it('should not highlight inactive menu items', () => {
    mockUsePathname.mockReturnValue('/dashboard')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const link = screen.getByText('商品列表').closest('a')!
    expect(getActiveClass(link)).not.toContain('bg-primary-600')
  })

  it('should highlight nested route for /products/123', () => {
    mockUsePathname.mockReturnValue('/products/123')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const link = screen.getByText('商品列表').closest('a')!
    expect(getActiveClass(link)).toContain('bg-primary-600')
  })

  it('should highlight for root path as dashboard', () => {
    mockUsePathname.mockReturnValue('/')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const link = screen.getByText('经营看板').closest('a')!
    expect(getActiveClass(link)).toContain('bg-primary-600')
  })

  // ── 前缀嵌套路由互斥单高亮（#3094 米宝菜单已移除：/chat 无侧边栏入口，人工客服不重复高亮）──

  it('/chat 时无侧边栏菜单高亮（米宝入口已移除，对话经右下角 FAB）', () => {
    mockUsePathname.mockReturnValue('/chat')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expect(screen.queryByText('米宝 · 在线对话')).not.toBeInTheDocument()
    const humanLink = screen.getByText('人工客服').closest('a')!
    expect(getActiveClass(humanLink)).not.toContain('bg-primary-600')
  })

  it('/chat 时侧边栏无高亮菜单项（#3094 米宝入口已移除）', () => {
    mockUsePathname.mockReturnValue('/chat')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const links = Array.from(document.querySelectorAll('nav a'))
    const activeLinks = links.filter((a) => a.className.includes('bg-primary-600'))
    expect(activeLinks).toHaveLength(0)
  })

  it('/orders/new 时「订单列表」高亮（嵌套路由前缀匹配回归保护）', () => {
    mockUsePathname.mockReturnValue('/orders/new')
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const ordersLink = screen.getByText('订单列表').closest('a')!
    const afterSalesLink = screen.getByText('售后工单').closest('a')!
    expect(getActiveClass(ordersLink)).toContain('bg-primary-600')
    expect(getActiveClass(afterSalesLink)).not.toContain('bg-primary-600')
  })

  // ── 分组折叠/展开 ──

  it('should toggle group expansion when clicking group header', async () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expect(screen.getByText('商品列表')).toBeInTheDocument()

    await user.click(screen.getByText('商品管理'))
    expect(screen.queryByText('商品列表')).not.toBeInTheDocument()
  })

  // ── 独立菜单项 ──

  it('should render standalone items exactly once each', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    // #2969: 客户管理已从独立菜单改为客户管理组标题（仍唯一）
    expect(screen.getAllByText('客户管理').length).toBe(1)
    // #3081: AI 客服配置已移除（合并进企业基础信息），不再渲染
    expect(screen.queryByText('AI 客服配置')).not.toBeInTheDocument()
    // #2969: 岗位权限归入组织管理组（唯一），通知中心仍为独立菜单（唯一）
    expect(screen.getAllByText('岗位权限').length).toBe(1)
    expect(screen.getAllByText('通知中心').length).toBe(1)
  })

  // ── UI-005: 智能客服大类分组与图标 ──

  it('「智能客服」大类位于「工作台」之后、「商品管理」之前', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const workspace = screen.getByText('工作台')
    const smartCs = screen.getByText('智能客服')
    const productCenter = screen.getByText('商品管理')
    const follows = (a: HTMLElement, b: HTMLElement) =>
      (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0
    expect(follows(workspace, smartCs)).toBe(true)
    expect(follows(smartCs, productCenter)).toBe(true)
  })

  it('「智能客服」下子菜单顺序：人工客服 在前、知识库次之（#2969/#3081/#3094 米宝·在线对话 入口已移除）', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const groupContainer = screen.getByText('智能客服').closest('.mb-4') as HTMLElement
    const links = groupContainer.querySelectorAll('a')
    expect(links.length).toBe(2)
    expect(links[0].textContent).toContain('人工客服')
    expect(links[1].textContent).toContain('知识库')
  })

  it('「人工客服」已从「工作台」分组移除（工作台仅剩经营看板）', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const workspaceGroup = screen.getByText('工作台').closest('.mb-4') as HTMLElement
    expect(within(workspaceGroup).getByText('经营看板')).toBeInTheDocument()
    expect(within(workspaceGroup).queryByText('人工客服')).not.toBeInTheDocument()
    // 人工客服整体仍存在（移入智能客服分组）
    expect(screen.getByText('人工客服')).toBeInTheDocument()
  })

  it('「人工客服」渲染 Headphones 图标，与「经营看板」BarChart3 图标明确区分', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const humanLink = screen.getByText('人工客服').closest('a')!
    expect(within(humanLink).getByTestId('icon-headphones')).toBeInTheDocument()
    expect(within(humanLink).queryByTestId('icon-bar-chart3')).not.toBeInTheDocument()
    const dashboardLink = screen.getByText('经营看板').closest('a')!
    expect(within(dashboardLink).getByTestId('icon-bar-chart3')).toBeInTheDocument()
  })

  it('「智能客服」大类渲染 MessageSquare 图标（#3081 AI 客服配置菜单已移除）', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    const groupButton = screen.getByText('智能客服').closest('button')!
    expect(within(groupButton).getByTestId('icon-message-square')).toBeInTheDocument()
  })

  it('「米宝·在线对话」菜单入口已移除（#3094：智能体对话经右下角浮动按钮进入）', () => {
    render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
    expect(screen.queryByText('米宝 · 在线对话')).not.toBeInTheDocument()
  })

  // ── 权限过滤 ──

  describe('Permission-based menu filtering', () => {
    it('should show all menu items for admin user with * permission', () => {
      mockUseAuthStore.mockReturnValue({
        user: { id: '1', username: 'admin', name: '管理员', permissions: ['*'], roles: ['admin'] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      expect(screen.getByText('工作台')).toBeInTheDocument()
      expect(screen.getByText('商品列表')).toBeInTheDocument()
      // #1403: 商品分类管理已移出侧边栏
      expect(screen.queryByText('商品分类管理')).not.toBeInTheDocument()
      expect(screen.getByText('订单列表')).toBeInTheDocument()
      // #2969: 客户管理组子项与组织管理组子项均可见
      expect(screen.getByText('客户管理')).toBeInTheDocument()
      expect(screen.getByText('客户列表')).toBeInTheDocument()
      expect(screen.getByText('财务对账')).toBeInTheDocument()
      expect(screen.getByText('组织管理')).toBeInTheDocument()
      expect(screen.getByText('员工管理')).toBeInTheDocument()
      expect(screen.getByText('岗位权限')).toBeInTheDocument()
      expect(screen.getByText('企业基础信息')).toBeInTheDocument()
      expect(screen.getByText('知识库')).toBeInTheDocument()
      expect(screen.getByText('通知中心')).toBeInTheDocument()
      // UI-005/UI-011: admin 可见智能客服大类及其子菜单（#3094 米宝·在线对话 入口已移除）
      expect(screen.getByText('智能客服')).toBeInTheDocument()
      expect(screen.queryByText('米宝 · 在线对话')).not.toBeInTheDocument()
      expect(screen.getByText('人工客服')).toBeInTheDocument()
    })

    it('should filter out items user has no permission for', () => {
      mockUseAuthStore.mockReturnValue({
        user: { id: '2', username: 'operator', name: '运营', permissions: ['dashboard:view', 'order:list', 'product:list'], roles: ['operator'] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      // 有权限的
      expect(screen.getByText('工作台')).toBeInTheDocument()
      expect(screen.getByText('商品列表')).toBeInTheDocument()
      expect(screen.getByText('订单列表')).toBeInTheDocument()
      // 无权限的
      expect(screen.queryByText('商品分类管理')).not.toBeInTheDocument()
      expect(screen.queryByText('加工项管理')).not.toBeInTheDocument()
      expect(screen.queryByText('售后工单')).not.toBeInTheDocument()
      // #2969: 客户管理组（客户列表+财务对账）整组隐藏
      expect(screen.queryByText('客户管理')).not.toBeInTheDocument()
      expect(screen.queryByText('客户列表')).not.toBeInTheDocument()
      expect(screen.queryByText('财务对账')).not.toBeInTheDocument()
      // #2969: 组织管理组（员工+岗位权限+企业信息）整组隐藏
      expect(screen.queryByText('组织管理')).not.toBeInTheDocument()
      expect(screen.queryByText('员工管理')).not.toBeInTheDocument()
      expect(screen.queryByText('岗位权限')).not.toBeInTheDocument()
      expect(screen.queryByText('企业基础信息')).not.toBeInTheDocument()
      // 无 knowledge:manage → 知识库入口隐藏；通知中心全员可见
      expect(screen.queryByText('知识库')).not.toBeInTheDocument()
      expect(screen.getByText('通知中心')).toBeInTheDocument()
      // UI-005/UI-011: 无 agent:session / knowledge:manage → 智能客服整组隐藏（#3081 已移除 AI 客服配置菜单）
      expect(screen.queryByText('智能客服')).not.toBeInTheDocument()
      expect(screen.queryByText('米宝 · 在线对话')).not.toBeInTheDocument()
      expect(screen.queryByText('人工客服')).not.toBeInTheDocument()
    })

    it('should show only dashboard when user has no permissions', () => {
      mockUseAuthStore.mockReturnValue({
        user: { id: '3', username: 'newbie', name: '新人', permissions: [], roles: [] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      expect(screen.getByText('工作台')).toBeInTheDocument()
      // 分组标题应该都不在
      expect(screen.queryByText('商品管理')).not.toBeInTheDocument()
      expect(screen.queryByText('订单管理')).not.toBeInTheDocument()
      expect(screen.queryByText('智能客服')).not.toBeInTheDocument()
      // #2969: 客户管理组/组织管理组也不在（整组权限过滤）
      expect(screen.queryByText('客户管理')).not.toBeInTheDocument()
      expect(screen.queryByText('组织管理')).not.toBeInTheDocument()
      expect(screen.queryByText('员工管理')).not.toBeInTheDocument()
      // 零权限也可见：通知中心（无权限码，全员）
      expect(screen.getByText('通知中心')).toBeInTheDocument()
      // 零权限不可见：知识库（需 knowledge:manage）
      expect(screen.queryByText('知识库')).not.toBeInTheDocument()
    })

    it('有 agent:session → 保留「人工客服」（#3094 米宝·在线对话 菜单已移除不渲染；#3081 无 AI 客服配置菜单）', () => {
      mockUseAuthStore.mockReturnValue({
        user: { id: '5', username: 'cs', name: '客服', permissions: ['agent:session'], roles: [] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      expect(screen.getByText('智能客服')).toBeInTheDocument()
      expect(screen.queryByText('米宝 · 在线对话')).not.toBeInTheDocument()
      expect(screen.getByText('人工客服')).toBeInTheDocument()
      expect(screen.queryByText('AI 客服配置')).not.toBeInTheDocument()
    })

    it('仅 knowledge:manage → 隐藏「人工客服」，保留「知识库」（#3094 米宝入口已移除）', () => {
      mockUseAuthStore.mockReturnValue({
        user: { id: '6', username: 'kb', name: '知识管理员', permissions: ['knowledge:manage'], roles: [] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      expect(screen.getByText('智能客服')).toBeInTheDocument()
      expect(screen.getByText('知识库')).toBeInTheDocument()
      expect(screen.queryByText('米宝 · 在线对话')).not.toBeInTheDocument()
      expect(screen.queryByText('人工客服')).not.toBeInTheDocument()
    })

    it('两个子菜单均不可见时「智能客服」大类整组隐藏（#3094）', () => {
      mockUseAuthStore.mockReturnValue({
        user: { id: '7', username: 'nocs', name: '无客服权限', permissions: ['dashboard:view'], roles: [] },
      })
      render(<Sidebar collapsed={false} onToggle={mockOnToggle} />)
      expect(screen.queryByText('智能客服')).not.toBeInTheDocument()
      expect(screen.queryByText('米宝 · 在线对话')).not.toBeInTheDocument()
      expect(screen.queryByText('人工客服')).not.toBeInTheDocument()
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
      // 订单管理 group should show (has order:list)
      expect(screen.getByText('订单管理')).toBeInTheDocument()
      expect(screen.getByText('订单列表')).toBeInTheDocument()
      // 但售后工单不应该出现
      expect(screen.queryByText('售后工单')).not.toBeInTheDocument()
      // 商品管理 group should be completely hidden
      expect(screen.queryByText('商品管理')).not.toBeInTheDocument()
    })
  })
})
