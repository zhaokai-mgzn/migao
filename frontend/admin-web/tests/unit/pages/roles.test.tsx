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
  { id: 'p-order-list', name: '订单列表', code: 'order:list', resource: 'order', action: 'list', description: '查看订单列表' },
  { id: 'p-order-detail', name: '订单详情', code: 'order:detail', resource: 'order', action: 'detail', description: '查看订单详情' },
  { id: 'p-order-refund', name: '订单退款', code: 'order:refund', resource: 'order', action: 'refund', description: '处理退款/售后工单' },
  { id: 'p-customer', name: '客户管理', code: 'customer:view', resource: 'customer', action: 'view', description: '查看客户' },
  { id: 'p-finance', name: '财务对账', code: 'finance:view', resource: 'finance', action: 'view', description: '查看财务流水/对账' },
  { id: 'p-agent-session', name: '会话监控', code: 'agent:session', resource: 'agent', action: 'session', description: '米宝对话/会话监控/在线接待' },
  { id: 'p-employee-list', name: '员工列表', code: 'employee:list', resource: 'employee', action: 'list', description: '查看员工列表' },
  { id: 'p-employee-create', name: '新增员工', code: 'employee:create', resource: 'employee', action: 'create', description: '新增/编辑/删除员工' },
  { id: 'p-system', name: '系统管理', code: 'system:manage', resource: 'system', action: 'manage', description: '企业信息/角色管理/系统设置' },
]

import RolesPage from '@/app/(dashboard)/roles/page'

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
    // 菜单组头 = 侧边栏菜单组名
    expect(tree.getByText('智能客服')).toBeInTheDocument()
    expect(tree.getAllByText('商品管理').length).toBeGreaterThanOrEqual(1) // 组头；操作权限节另有同名项
    expect(tree.getByText('订单管理')).toBeInTheDocument()
    expect(tree.getByText('客户管理')).toBeInTheDocument()
    expect(tree.getByText('组织管理')).toBeInTheDocument()
    // 菜单项 = 侧边栏菜单项名
    // #3094: 米宝 · 在线对话 菜单入口已移除，权限树不再渲染该菜单项
    expect(tree.queryByText('米宝 · 在线对话')).not.toBeInTheDocument()
    expect(tree.getByText('在线接待')).toBeInTheDocument()
    expect(tree.getByText('知识库')).toBeInTheDocument()
    expect(tree.getByText('商品列表')).toBeInTheDocument()
    expect(tree.getByText('加工项管理')).toBeInTheDocument()
    expect(tree.getByText('订单列表')).toBeInTheDocument()
    expect(tree.getByText('售后工单')).toBeInTheDocument()
    expect(tree.getByText('客户列表')).toBeInTheDocument()
    expect(tree.getByText('财务对账')).toBeInTheDocument()
    expect(tree.getByText('员工管理')).toBeInTheDocument()
    expect(tree.getByText('岗位权限')).toBeInTheDocument()
    expect(tree.getByText('企业基础信息')).toBeInTheDocument()
    // 旧口径不出现：旧权限名 + 英文 resourceType 组头
    expect(tree.queryByText('会话监控')).not.toBeInTheDocument()
    expect(tree.queryByText('快捷回复')).not.toBeInTheDocument()
    expect(tree.queryByText('AI 客服配置')).not.toBeInTheDocument()
    expect(tree.queryByText('订单退款')).not.toBeInTheDocument()
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

  it('勾选菜单项「在线接待」→ 创建岗位时 permissionIds 含 agent:session 权限ID（代码映射，#3094 米宝菜单已移除）', async () => {
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

  it('菜单组全选：勾选「智能客服」组头 → 组内权限码全部授予并随提交落库', async () => {
    mockGetRoles.mockResolvedValue({ data: { data: { items: [], total: 0 } } })
    render(<RolesPage />)
    fireEvent.click(await screen.findByText('新增岗位'))
    // 智能客服组含 agent:session（2 个菜单项）+ knowledge:manage（#3081 已移除 agent:quickreply）
    const groupHeader = (await screen.findByText('智能客服')).closest('div')!
    fireEvent.click(groupHeader.querySelector('input')!)
    const textboxes = screen.getAllByRole('textbox')
    fireEvent.change(textboxes[0], { target: { value: '智能客服岗' } })
    fireEvent.change(textboxes[1], { target: { value: 'cs' } })
    fireEvent.click(screen.getByRole('button', { name: '创建' }))
    await waitFor(() => {
      expect(mockCreateRole).toHaveBeenCalledWith(expect.objectContaining({
        permissionIds: expect.arrayContaining(['p-agent-session', 'p-knowledge']),
      }))
    })
    // #3081: agent:quickreply 权限已随快捷回复功能下线，不再授予
    expect(mockCreateRole.mock.calls[0][0].permissionIds).not.toContain('p-agent-quickreply')
  })
})