// case_ids: HR-004, HR-005, HR-006, UI-028
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'

// Mock APIs
const mockGetRoles = vi.fn()
const mockGetPermissions = vi.fn()
const mockCreateRole = vi.fn()

vi.mock('@/lib/api', () => ({
  roleApi: {
    getRoles: (...args: any[]) => mockGetRoles(...args),
    createRole: (...args: any[]) => mockCreateRole(...args),
    updateRole: vi.fn(),
    deleteRole: vi.fn(),
  },
  permissionApi: {
    getPermissions: (...args: any[]) => mockGetPermissions(...args),
  },
}))

// Mock sonner toast
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// Mock UI components
vi.mock('@/components/ui', () => ({
  Button: ({ children, onClick, ...props }: any) => (
    <button onClick={onClick} {...props}>{children}</button>
  ),
  Input: ({ label, value, onChange, disabled }: any) => (
    <div>
      <label>{label}</label>
      <input value={value} onChange={onChange} disabled={disabled} />
    </div>
  ),
  Modal: ({ open, title, children, footer }: any) =>
    open ? (
      <div data-testid="modal" role="dialog">
        <h2>{title}</h2>
        {children}
        <div data-testid="modal-footer">{footer}</div>
      </div>
    ) : null,
  StatusBadge: ({ label, color, dot, className, onClick }: any) => React.createElement('span', { onClick, className, title: label }, dot ? React.createElement('span', { className: 'w-1.5 h-1.5 rounded-full' }) : null, label),
  Badge: ({ children, variant }: any) => <span data-variant={variant}>{children}</span>,
}))

// Mock dayjs
vi.mock('dayjs', () => ({
  default: (date?: string) => ({
    format: (fmt: string) => date || '2026-06-22',
  }),
}))

// Mock lucide-react
vi.mock('lucide-react', () => {
  const stub = (name: string) => (props: any) => <span data-testid={`icon-${name}`} {...props} />
  return {
    Plus: stub('plus'),
    Pencil: stub('pencil'),
    Trash2: stub('trash2'),
    Shield: stub('shield'),
  }
})

// #3002：与后端权限目录一致的真实 catalog（resourceType = 旧分组码，仅操作权限节展示用）
const PERMISSION_CATALOG = [
  { id: 'p-dashboard', name: '仪表板查看', code: 'dashboard:view', resource: 'dashboard', action: 'view', description: '查看数据概览' },
  { id: 'p-product-manage', name: '商品管理', code: 'product:manage', resource: 'product', action: 'manage', description: '管理商品(旧大类码，兼容)' },
  { id: 'p-product-list', name: '商品列表', code: 'product:list', resource: 'product', action: 'list', description: '查看商品列表' },
  { id: 'p-product-create', name: '新增商品', code: 'product:create', resource: 'product', action: 'create', description: '新增/编辑/上下架商品' },
  { id: 'p-product-category', name: '商品分类', code: 'product:category', resource: 'product', action: 'category', description: '管理商品分类' },
  { id: 'p-processing', name: '加工管理', code: 'processing:manage', resource: 'processing', action: 'manage', description: '管理加工项' },
  { id: 'p-knowledge', name: '知识库管理', code: 'knowledge:manage', resource: 'knowledge', action: 'manage', description: '管理知识库' },
  // issue #5246（已合入 main）：知识库/售后拆出**读**码（菜单节点改用读码；写码仍在目录里，
  // 落「操作权限」节）
  { id: 'p-knowledge-view', name: '知识库查看', code: 'knowledge:view', resource: 'knowledge', action: 'view', description: '查看知识卡片' },
  { id: 'p-after-sales-view', name: '售后查看', code: 'after_sales:view', resource: 'after-sales', action: 'view', description: '查看售后工单' },
  { id: 'p-order-list', name: '订单列表', code: 'order:list', resource: 'order', action: 'list', description: '查看订单列表' },
  { id: 'p-order-detail', name: '订单详情', code: 'order:detail', resource: 'order', action: 'detail', description: '查看订单详情' },
  { id: 'p-order-refund', name: '订单退款', code: 'order:refund', resource: 'order', action: 'refund', description: '处理退款/售后工单' },
  { id: 'p-customer', name: '客户管理', code: 'customer:view', resource: 'customer', action: 'view', description: '查看客户' },
  { id: 'p-finance', name: '财务对账', code: 'finance:view', resource: 'finance', action: 'view', description: '查看财务流水/对账' },
  { id: 'p-agent-session', name: '会话监控', code: 'agent:session', resource: 'agent', action: 'session', description: '黄金策对话/会话监控/在线接待' },
  { id: 'p-employee-list', name: '员工列表', code: 'employee:list', resource: 'employee', action: 'list', description: '查看员工列表' },
  { id: 'p-employee-create', name: '新增员工', code: 'employee:create', resource: 'employee', action: 'create', description: '新增/编辑/删除员工' },
  { id: 'p-system', name: '系统管理', code: 'system:manage', resource: 'system', action: 'manage', description: '企业信息/角色管理/系统设置' },
]

import RolesPage from '@/app/(dashboard)/roles/page'
// #5895：菜单梯队的**真值源**（判据直接遍历它，而不是抄一份清单 —— 抄的那份会漂移）
import * as menuConfig from '@/config/menu'

describe('RolesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetRoles.mockResolvedValue({
      data: {
        data: {
          items: [
            { id: 'r1', name: '管理员', code: 'admin', description: '系统管理员', permissions: [{ id: 'p-product-list', name: '商品列表', code: 'product:list', resource: 'product', action: 'list' }], createdAt: '2026-06-01' },
            { id: 'r2', name: '客服', code: 'customer_service', description: '客服人员', permissions: [], createdAt: '2026-06-02' },
          ],
        },
      },
    })
    mockGetPermissions.mockResolvedValue({
      data: { data: PERMISSION_CATALOG },
    })
  })

  it('renders page title', () => {
    render(<RolesPage />)
    expect(screen.getByText('岗位权限')).toBeInTheDocument()
  })

  it('renders add position button', () => {
    render(<RolesPage />)
    expect(screen.getByText('新增岗位')).toBeInTheDocument()
  })

  it('loads and displays position cards', async () => {
    render(<RolesPage />)
    await waitFor(() => {
      expect(mockGetRoles).toHaveBeenCalled()
    })
    await waitFor(() => {
      expect(screen.getByText('管理员')).toBeInTheDocument()
      expect(screen.getByText('客服')).toBeInTheDocument()
    })
  })

  it('displays position codes', async () => {
    render(<RolesPage />)
    await waitFor(() => {
      expect(screen.getByText('admin')).toBeInTheDocument()
      expect(screen.getByText('customer_service')).toBeInTheDocument()
    })
  })

  it('shows empty state when no positions', () => {
    mockGetRoles.mockResolvedValue({
      data: { data: { items: [], total: 0 } },
    })
    render(<RolesPage />)
    expect(screen.getByText('岗位权限')).toBeInTheDocument()
  })

  // ── #3002 权限分配与真实菜单一致（菜单同构渲染，groupedBy menuGroups 单源）──

  it('权限分配弹窗按真实侧边栏菜单分组渲染（菜单组名 + 菜单项名），旧英文分组不出现', async () => {
    render(<RolesPage />)
    fireEvent.click(await screen.findByText('新增岗位'))
    const tree = within(await screen.findByTestId('perm-menu-sections'))
    // 菜单组头 = 侧边栏菜单组名（#5778 新 IA：**6 组 + 1 个一级项**，逐组点名）
    expect(tree.getByText('工作台')).toBeInTheDocument()
    expect(tree.getByText('客户服务')).toBeInTheDocument()
    expect(tree.getByText('交易管理')).toBeInTheDocument()
    expect(tree.getByText('生产管理')).toBeInTheDocument()
    expect(tree.getByText('仓储与物料')).toBeInTheDocument()
    expect(tree.getByText('组织管理')).toBeInTheDocument()
    // 旧组名不再出现：issue #5271 / #5778 三处改判（商品与加工项**撤销**；智能客服 → 客户服务；
    // 订单管理 + 客户管理 → 交易管理）。
    // 🔴 #5895 纠错：旧断言 `tree.getAllByText('商品管理')).toHaveLength(1)` 是**假绿** ——
    // 它命中的是「操作权限」节里的旧大类码 `product:manage`（DB 名也叫「商品管理」，就渲染在本容器内），
    // 而**菜单项「商品管理」当时根本没渲染**（#5778 把它升为 `standaloneTopItems` 一级项时本页没跟）。
    // 真实判据 = 本文件 #5895 三条（一级项块 `perm-standalone-top` 的位置/名称/码 + 勾选落库）。
    expect(tree.queryByText('商品与加工项')).not.toBeInTheDocument()
    expect(within(tree.getByTestId('perm-standalone-top')).getByText('商品管理')).toBeInTheDocument()
    expect(tree.queryByText('智能客服')).not.toBeInTheDocument()
    expect(tree.queryByText('订单管理')).not.toBeInTheDocument()
    expect(tree.queryByText('客户管理')).not.toBeInTheDocument()
    // 菜单项 = 侧边栏菜单项名
    // #3094: 黄金策 · 在线对话 菜单入口已移除，权限树不再渲染该菜单项
    expect(tree.queryByText('黄金策 · 在线对话')).not.toBeInTheDocument()
    expect(tree.getByText('在线接待')).toBeInTheDocument()
    expect(tree.getByText('知识库')).toBeInTheDocument()
    // 工作台组两项**都**进权限树：每日简报要 dashboard:view；
    // 🔴 issue #5699（P4）：经营看板自本阶段起**有码**（dashboard:view）⇒ 从「无码不进树」变为可勾选
    //（否则「勾得动 / 看不到」会漂移：它现在确实决定一个菜单项与 5 个读端点的可见性）。
    expect(tree.getByText('每日简报')).toBeInTheDocument()
    expect(tree.getByText('经营看板')).toBeInTheDocument()
    // #5778：「商品列表」改名「商品管理」（菜单项判据见本文件 #5895 三条：`perm-standalone-top`）
    // issue #4490：「加工项管理」+「加工费管理」合并为单一入口；#4542 起菜单名 =「加工项管理」
    // （权限树与真实侧边栏同源）
    expect(tree.getByText('加工项管理')).toBeInTheDocument()
    expect(tree.getByText('订单列表')).toBeInTheDocument()
    expect(tree.getByText('售后工单')).toBeInTheDocument()
    expect(tree.getByText('客户列表')).toBeInTheDocument()
    expect(tree.getByText('财务对账')).toBeInTheDocument()
    // #5778：生产管理组 5 项（含移入的「加工项管理」）+「仓储与物料」3 项都要在权限树里
    //（否则「勾得动/看不到」漂移）
    expect(tree.getByText('生产看板')).toBeInTheDocument()
    expect(tree.getByText('智能派单')).toBeInTheDocument()
    expect(tree.getByText('工艺配置')).toBeInTheDocument()
    expect(tree.getByText('计件工资')).toBeInTheDocument()
    expect(tree.getByText('入库单')).toBeInTheDocument()
    expect(tree.getByText('余料台账')).toBeInTheDocument()
    expect(tree.getByText('省料看板')).toBeInTheDocument()
    expect(tree.getByText('员工管理')).toBeInTheDocument()
    expect(tree.getByText('岗位权限')).toBeInTheDocument()
    expect(tree.getByText('企业基础信息')).toBeInTheDocument()
    // 旧口径不出现：旧权限名 + 英文 resourceType 组头
    expect(tree.queryByText('会话监控')).not.toBeInTheDocument()
    expect(tree.queryByText('快捷回复')).not.toBeInTheDocument()
    expect(tree.queryByText('AI 客服配置')).not.toBeInTheDocument()
    // issue #5246 契约翻转：`order:refund` 不再是「售后工单」节点的码（节点改用读码
    // `after_sales:view`）⇒ 它成了**没有菜单节点的写码**，按既有规则落进「操作权限」节
    // （该节位于本容器内）。「不出现在菜单树」这半条仍成立 —— 见下一行的计数断言。
    expect(within(screen.getByTestId('perm-extra-section')).getByText('订单退款')).toBeInTheDocument()
    expect(tree.queryAllByText('订单退款')).toHaveLength(1)
    expect(tree.queryByText('系统管理')).not.toBeInTheDocument()
    expect(tree.queryByText('dashboard')).not.toBeInTheDocument()
    expect(tree.queryByText('order')).not.toBeInTheDocument()
  })

  it('非菜单操作权限单独一节展示（新增商品/订单详情/新增员工等），不混入菜单树', async () => {
    render(<RolesPage />)
    fireEvent.click(await screen.findByText('新增岗位'))
    const extras = within(await screen.findByTestId('perm-extra-section'))
    expect(extras.getByText('操作权限')).toBeInTheDocument()
    expect(extras.getByText('新增商品')).toBeInTheDocument()
    expect(extras.getByText('订单详情')).toBeInTheDocument()
    expect(extras.getByText('新增员工')).toBeInTheDocument()
    expect(extras.getByText('商品分类')).toBeInTheDocument()
    // 菜单码不进操作权限节
    expect(extras.queryByText('售后工单')).not.toBeInTheDocument()
    expect(extras.queryByText('加工项管理')).not.toBeInTheDocument()
  })

  it('勾选菜单项「在线接待」→ 创建岗位时 permissionIds 含 agent:session 权限ID（代码映射，#3094 黄金策菜单已移除）', async () => {
    mockGetRoles.mockResolvedValue({ data: { data: { items: [], total: 0 } } })
    render(<RolesPage />)
    fireEvent.click(await screen.findByText('新增岗位'))
    const item = (await screen.findByText('在线接待')).closest('label')!
    fireEvent.click(item.querySelector('input')!)
    const textboxes = screen.getAllByRole('textbox')
    fireEvent.change(textboxes[0], { target: { value: '客服人员' } })
    fireEvent.change(textboxes[1], { target: { value: 'customer_service' } })
    fireEvent.click(screen.getByRole('button', { name: '创建' }))
    await waitFor(() => {
      expect(mockCreateRole).toHaveBeenCalledWith(expect.objectContaining({
        permissionIds: expect.arrayContaining(['p-agent-session']),
      }))
    })
  })

  it('编辑岗位按菜单回显：角色已有 order:list → 「订单列表」勾选', async () => {
    mockGetRoles.mockResolvedValue({
      data: {
        data: {
          items: [
            { id: 'r1', name: '订单客服', code: 'order_service', description: '', permissions: [{ id: 'p-order-list', name: '订单列表', code: 'order:list', resource: 'order', action: 'list' }], createdAt: '2026-06-01' },
          ],
        },
      },
    })
    render(<RolesPage />)
    await screen.findByText('订单客服')
    fireEvent.click(screen.getByTitle('编辑'))
    await screen.findByText('编辑岗位')
    const orderItem = (await screen.findByText('订单列表')).closest('label')!
    expect(orderItem.querySelector('input')!.checked).toBe(true)
    // 未授予的菜单项不勾选
    const knowledgeItem = screen.getByText('知识库').closest('label')!
    expect(knowledgeItem.querySelector('input')!.checked).toBe(false)
  })

  it('菜单组全选：勾选「客户服务」组头 → 组内权限码全部授予并随提交落库', async () => {
    mockGetRoles.mockResolvedValue({ data: { data: { items: [], total: 0 } } })
    render(<RolesPage />)
    fireEvent.click(await screen.findByText('新增岗位'))
    // #5778：客户服务组（原「智能客服」组）含 agent:session（在线接待）+ **knowledge:view**
    //（知识库；issue #5246 起读码，写码 knowledge:manage 不再挂在菜单节点上）（#3081 已移除 agent:quickreply）
    const groupHeader = (await screen.findByText('客户服务')).closest('div')!
    fireEvent.click(groupHeader.querySelector('input')!)
    const textboxes = screen.getAllByRole('textbox')
    fireEvent.change(textboxes[0], { target: { value: '客户服务岗' } })
    fireEvent.change(textboxes[1], { target: { value: 'cs' } })
    fireEvent.click(screen.getByRole('button', { name: '创建' }))
    await waitFor(() => {
      expect(mockCreateRole).toHaveBeenCalledWith(expect.objectContaining({
        permissionIds: expect.arrayContaining(['p-agent-session', 'p-knowledge-view']),
      }))
    })
    // #3081: agent:quickreply 权限已随快捷回复功能下线，不再授予
    expect(mockCreateRole.mock.calls[0][0].permissionIds).not.toContain('p-agent-quickreply')
  })

  // ══ #5895：一级项（`standaloneTopItems`）必须并入权限树 ══
  // 缺陷的**类** = 「侧边栏的菜单梯队（或梯队里新增的带码项）在权限树里漏接」——
  // #5778 引入一级项 `standaloneTopItems`（「商品管理」）时，侧边栏与 ⌘K 都跟了，
  // 只有本弹窗仍只遍历 `menuGroups` ⇒ 该菜单在「权限分配」里**整项消失**（勾都勾不到）。

  // 登记表：菜单梯队 → 它在权限树里的专属容器（null = 散在整树里/无带码项）。
  // 🔴 新增一个菜单梯队必须在此登记并接线，否则下面第一条判据当场红（未登记即红）。
  const MENU_TIERS: Record<string, string | null> = {
    menuGroups: null,
    standaloneTopItems: 'perm-standalone-top',
    standaloneItems: null, // 尾部项「通知中心」：全员可见、**无码** ⇒ 不可授予
  }

  it('类级守卫：config/menu 的菜单梯队全部已并入权限树（新增梯队未接线即红）', () => {
    const tierArrays = Object.entries(menuConfig)
      .filter(([, v]) => Array.isArray(v))
      .map(([k]) => k)
      .sort()
    expect(tierArrays).toEqual(Object.keys(MENU_TIERS).sort())
  })

  it('类级守卫：三梯队里每个带码菜单节点都能在权限树里勾到（漏接即红）', async () => {
    render(<RolesPage />)
    fireEvent.click(await screen.findByText('新增岗位'))
    const container = await screen.findByTestId('perm-menu-sections')
    // 菜单行 = 「菜单名 + 权限码」的 label；「操作权限」节渲染的是「权限名(action)」、不含码
    // ⇒ 同名条目（如旧大类码 product:manage 也叫「商品管理」）**不会**把漏接的菜单项伪装成已接线。
    const rows = Array.from(container.querySelectorAll('label')).map(l => l.textContent || '')
    const coded = [
      ...menuConfig.menuGroups.flatMap(g => g.children),
      ...menuConfig.standaloneTopItems,
      ...menuConfig.standaloneItems,
    ].filter(item => item.permissionCode)
    expect(coded.length).toBeGreaterThan(0) // 反空跑：没有可判的对象时本判据不算通过
    for (const item of coded) {
      const hit = rows.some(text => text.includes(item.name) && text.includes(item.permissionCode!))
      expect(hit, `菜单节点「${item.name}」(${item.permissionCode}) 未出现在权限树 —— 梯队接线漏了`).toBe(true)
    }
  })

  it('#5895 一级项「商品管理」渲染在权限树**所有分组之前**（standaloneTopItems / product:list）', async () => {
    render(<RolesPage />)
    fireEvent.click(await screen.findByText('新增岗位'))
    const container = await screen.findByTestId('perm-menu-sections')
    const top = within(container).getByTestId('perm-standalone-top')
    expect(within(top).getByText('商品管理')).toBeInTheDocument()
    expect(within(top).getByText('product:list')).toBeInTheDocument()
    // 位置与侧边栏同序：一级项 → 分组 → 尾部项 ⇒ 一级项块是权限树的**第一个**子块
    expect(container.firstElementChild).toBe(top)
  })

  it('#5895 勾选一级项「商品管理」→ 创建岗位时 permissionIds 含 product:list 的权限ID（勾得动）', async () => {
    mockGetRoles.mockResolvedValue({ data: { data: { items: [], total: 0 } } })
    render(<RolesPage />)
    fireEvent.click(await screen.findByText('新增岗位'))
    const top = within(await screen.findByTestId('perm-menu-sections')).getByTestId('perm-standalone-top')
    fireEvent.click(within(top).getByText('商品管理').closest('label')!.querySelector('input')!)
    const textboxes = screen.getAllByRole('textbox')
    fireEvent.change(textboxes[0], { target: { value: '商品运营' } })
    fireEvent.change(textboxes[1], { target: { value: 'product_operator' } })
    fireEvent.click(screen.getByRole('button', { name: '创建' }))
    await waitFor(() => {
      expect(mockCreateRole).toHaveBeenCalledWith(expect.objectContaining({
        permissionIds: expect.arrayContaining(['p-product-list']),
      }))
    })
  })
})