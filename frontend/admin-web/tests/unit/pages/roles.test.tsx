// case_ids: HR-004, HR-005, HR-006, UI-028, UI-117
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'

// Mock APIs
const mockGetRoles = vi.fn()
const mockGetPermissions = vi.fn()
const mockCreateRole = vi.fn()
// issue #7146：工人端页面目录（页键 + 人话名都取服务端；前端不维护第二份词表）
const mockGetWorkerPages = vi.fn()

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
  workerPageCatalogApi: {
    get: (...args: any[]) => mockGetWorkerPages(...args),
  },
}))

// Mock sonner toast
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// 手机端可见面标注（issue #6759/#6781）走 `GET /api/admin/menus` —— 本文件按测试给**真语料**
const mockRequestGet = vi.fn()
vi.mock('@/lib/request', () => ({
  default: { get: (...args: any[]) => mockRequestGet(...args) },
}))

// Mock UI components
vi.mock('@/components/ui', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>()
  return {
    // issue #7007：**先摊开真原语，再覆盖**（`...actual` 在前 ⇒ 显式 mock 仍然赢）。
    // 此前这里是**整模块** mock 且不合并真值，只列被替身的几个原语 ⇒ 页面一旦用上
    // **当时不存在的原语**（本轮加了 PageHeader / PageCard / SearchPanel）就报
    // `No "PageHeader" export is defined on the "@/components/ui" mock` ——
    // 报错离病灶很远（本轮 144 条红的根因，与页面改动对错无关）。
    // 摊开真值后，新增原语不必再逐个补 mock。口径与同目录
    // `production-remnants-paging.test.tsx` 既有写法同源。
    ...actual,
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
  }
})

// Mock dayjs
vi.mock('dayjs', () => ({
  default: (date?: string) => ({
    format: (fmt: string) => date || '2026-06-22',
  }),
}))

// Mock lucide-react
vi.mock('lucide-react', async (importOriginal) => {
  // ⚠️ 必须 spread `...actual`：本 mock 是**闭合集合**（只列页面直接用到的那几个图标），
  // 而模块一旦经 `@/components/ui` 桶加载真 `EmptyState`（它自己 import `Package`），
  // 闭集就漏了它 ⇒ 报 `No "Package" export is defined on the "lucide-react" mock`
  // （与「整模块 mock `@/components/ui`」同一种病，见 issue #7007）。
  // `...actual` 在前 ⇒ 显式桩的 testid 仍然赢。
  const actual = await importOriginal<Record<string, unknown>>()
  const stub = (name: string) => (props: any) => <span data-testid={`icon-${name}`} {...props} />
  return {
    ...actual,
    Plus: stub('plus'),
    Pencil: stub('pencil'),
    Trash2: stub('trash2'),
    Shield: stub('shield'),
    // issue #6663：失败态行用的图标
    AlertTriangle: stub('alert-triangle'),
  }
})

// #3002：与后端权限目录一致的真实 catalog（resourceType = 旧分组码，仅操作权限节展示用）
const PERMISSION_CATALOG = [
  { id: 'p-dashboard', name: '仪表板查看', code: 'dashboard:view', resource: 'dashboard', action: 'view', description: '查看数据概览' },
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

/** 商家**可见**文本 = 元素树里「直属文本节点」的拼接（`sr-only` 元素整棵跳过 —— 它不上屏）。 */
const visibleText = (root: HTMLElement): string => {
  let out = ''
  const walk = (el: Element) => {
    el.childNodes.forEach(n => {
      if (n.nodeType === 3) out += n.textContent || ''
      else if (n.nodeType === 1 && !(n as Element).classList.contains('sr-only')) walk(n as Element)
    })
  }
  walk(root)
  return out
}

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
    // 缺省：菜单接口读不到 ⇒ 零手机端标注（本文件绝大多数用例与本单无关，不喂语料）
    mockRequestGet.mockRejectedValue(new Error('not mocked'))
    // 缺省：工人端页面目录可读（issue #7146；个别用例改成失败态 / 改名语料）
    mockGetWorkerPages.mockResolvedValue({
      data: {
        data: {
          pages: ['report', 'piecework', 'order', 'cut_calc', 'shipment'],
          labels: { report: '报工', piecework: '计件工资报表', order: '订单', cut_calc: '裁高计算器', shipment: '发货' },
        },
      },
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

  // issue #7146：描述只承载「职责」散文；「默认可用模块」改为派生区（后台 + 手机端同一张卡）
  // 长描述仍默认收起（§31 P1 常驻面克制）+ 逐卡「展开/收起」看全文；短描述不给按钮（对照读数：不制造噪音）
  it('#7111/#7146 长岗位描述默认收起，点「展开」看全文（短描述不给按钮）', async () => {
    const longDescription =
      '职责：' + '维护商品资料与分类，管理加工项与加工费口径。'.repeat(3)
    mockGetRoles.mockResolvedValue({
      data: {
        data: {
          items: [
            { id: 'r9', name: '商品管理员', code: 'product_manager', description: longDescription, permissions: [], createdAt: '2026-06-01' },
            { id: 'r8', name: '客服', code: 'customer_service', description: '客服人员', permissions: [], createdAt: '2026-06-02' },
          ],
        },
      },
    })
    render(<RolesPage />)
    const desc = await screen.findByTestId('role-description-product_manager')
    expect(desc).toHaveClass('line-clamp-2')
    expect(screen.queryByTestId('role-description-toggle-customer_service')).toBeNull()
    // 🔴 #7146：描述里**不得**再出现模块清单（清单必须派生 ⇒ 否则就是第二份会漂的真值）
    expect(desc).not.toHaveTextContent('默认可用模块')

    fireEvent.click(screen.getByTestId('role-description-toggle-product_manager'))
    expect(desc).not.toHaveClass('line-clamp-2')
    expect(desc).toHaveTextContent('维护商品资料与分类')
    expect(screen.getByTestId('role-description-toggle-product_manager')).toHaveAttribute('aria-expanded', 'true')

    fireEvent.click(screen.getByTestId('role-description-toggle-product_manager'))
    expect(desc).toHaveClass('line-clamp-2')
  })

  it('shows empty state when no positions', () => {
    mockGetRoles.mockResolvedValue({
      data: { data: { items: [], total: 0 } },
    })
    render(<RolesPage />)
    expect(screen.getByText('岗位权限')).toBeInTheDocument()
  })

  // ── #3002 权限分配与真实菜单一致（菜单同构渲染，groupedBy menuGroups 单源）──

  it('🔴 权限分配弹窗按真实侧边栏菜单分组渲染（菜单组名 + 菜单项名），旧英文分组与已撤销组名不出现', async () => {
    render(<RolesPage />)
    fireEvent.click(await screen.findByText('新增岗位'))
    const tree = within(await screen.findByTestId('perm-menu-sections'))
    // 🔴 菜单组头 = 侧边栏菜单组名（issue #7087 后**5 组**；「工作台」组**整组撤销**）
    expect(tree.getByText('客户服务')).toBeInTheDocument()
    expect(tree.getByText('交易管理')).toBeInTheDocument()
    expect(tree.getByText('生产管理')).toBeInTheDocument()
    expect(tree.getByText('仓储与物料')).toBeInTheDocument()
    expect(tree.getByText('组织管理')).toBeInTheDocument()
    // 🔴 已撤销的组名不得出现在权限树里 —— 商家可见面（含权限勾选树）不再有「工作台」（issue #7087）
    expect(tree.queryByText('工作台')).not.toBeInTheDocument()
    // 旧组名不再出现：issue #5271 / #5778 三处改判（商品与加工项**撤销**；智能客服 → 客户服务；
    // 订单管理 + 客户管理 → 交易管理）。
    // 🔴 #5895 纠错：旧断言 `tree.getAllByText('商品管理')).toHaveLength(1)` 是**假绿** ——
    // 它命中的是「操作权限」节里的旧大类码 `product:manage`（DB 名也叫「商品管理」，就渲染在本容器内），
    // 而**菜单项「商品管理」当时根本没渲染**（#5778 把它升为 `standaloneTopItems` 一级项时本页没跟）。
    // 真实判据 = 本文件 #5895 三条（一级项块 `perm-standalone-top` 的位置/名称/码 + 勾选落库）。
    expect(tree.queryByText('商品与加工项')).not.toBeInTheDocument()
    // 🔴 2026-10-29（issue #8086）：商品管理已降入「基础资料」组（不再是尾席位一级项）
    const basicSection = tree.getByText('基础资料').closest('div')!.parentElement as HTMLElement
    expect(within(basicSection).getByText('商品管理')).toBeInTheDocument()
    expect(within(basicSection).getByText('客户列表')).toBeInTheDocument()
    expect(within(basicSection).getByText('供应商')).toBeInTheDocument()
    expect(within(basicSection).getByText('价格本')).toBeInTheDocument()
    // 质量组（#8086）：质检记录 / 返工单（从生产管理拆出，权限码不变）
    const qualitySection = tree.getByText('质量').closest('div')!.parentElement as HTMLElement
    expect(within(qualitySection).getByText('质检记录')).toBeInTheDocument()
    expect(within(qualitySection).getByText('返工单')).toBeInTheDocument()
    expect(tree.queryByText('智能客服')).not.toBeInTheDocument()
    expect(tree.queryByText('订单管理')).not.toBeInTheDocument()
    expect(tree.queryByText('客户管理')).not.toBeInTheDocument()
    // 菜单项 = 侧边栏菜单项名
    // #3094: 黄金策 · 在线对话 菜单入口已移除，权限树不再渲染该菜单项
    expect(tree.queryByText('黄金策 · 在线对话')).not.toBeInTheDocument()
    expect(tree.getByText('在线接待')).toBeInTheDocument()
    expect(tree.getByText('知识库')).toBeInTheDocument()
    // 🔴 issue #7087：「经营看板」升为**最前席位**一级项 ⇒ 渲染在 `perm-standalone-head` 块里，
    // 它带的码 `dashboard:view` 因此仍**可授予**（否则「勾得动 / 看不到」漂移 —— 与 #5895 同一形态）；
    // 同批「每日简报」菜单项**已删除**（功能保留：企业开关仍驱动经营看板上的结论卡）。
    const head = within(tree.getByTestId('perm-standalone-head'))
    expect(head.getByText('经营看板')).toBeInTheDocument()
    // 报表中心（issue #7376）与经营看板**同码**（报表就是看板的下钻，零授权 delta）⇒
    // 权限树里两个节点都渲染同一个码 —— 与既有「入库单 / 供应商 / 采购单 同取 inbound:view」同款，
    // 勾任一个即授予该码（这是码粒度决定的，不是本页的 bug）。
    expect(head.getByText('报表中心')).toBeInTheDocument()
    expect(head.getAllByText('dashboard:view')).toHaveLength(2)
    expect(tree.queryByText('每日简报')).not.toBeInTheDocument()
    // #5778：「商品列表」改名「商品管理」（菜单项判据见本文件 #5895 三条：`perm-standalone-top`）
    // 🔴 #6580（2026-10-09 用户裁定）：菜单项「加工项管理」「工艺配置」**已移除**（功能体并入
    // `/settings` 企业基础设置页内的配置域）⇒ 权限树不再渲染它们；同批「企业基础设置」由
    // 组织管理组的组内项**升为一级项**（渲染在 `perm-standalone-top` 里，见下方断言）。
    expect(tree.queryByText('加工项管理')).not.toBeInTheDocument()
    expect(tree.queryByText('工艺配置')).not.toBeInTheDocument()
    expect(tree.getByText('销售订单')).toBeInTheDocument()
    expect(tree.getByText('售后工单')).toBeInTheDocument()
    expect(tree.getByText('客户列表')).toBeInTheDocument()
    expect(tree.getByText('财务对账')).toBeInTheDocument()
    // #5778：生产管理组 5 项（含移入的「加工项管理」）+「仓储与物料」3 项都要在权限树里
    //（否则「勾得动/看不到」漂移）
    expect(tree.getByText('作业看板')).toBeInTheDocument()
    expect(tree.getByText('智能派单')).toBeInTheDocument()
    expect(tree.getByText('计件工资')).toBeInTheDocument()
    expect(tree.getByText('入库单')).toBeInTheDocument()
    expect(tree.getByText('余料台账')).toBeInTheDocument()
    expect(tree.getByText('省料看板')).toBeInTheDocument()
    expect(tree.getByText('员工管理')).toBeInTheDocument()
    expect(tree.getByText('岗位权限')).toBeInTheDocument()
    // 🔴 #6580：「企业基础设置」（原名「企业基础信息」）现为**一级项**
    // ⇒ 渲染在 `perm-standalone-top` 块里（与「商品管理」同口径），不在分组树里重复出现。
    expect(within(tree.getByTestId('perm-standalone-top')).getByText('企业基础设置')).toBeInTheDocument()
    // 旧口径不出现：旧权限名 + 英文 resourceType 组头
    expect(tree.queryByText('会话监控')).not.toBeInTheDocument()
    expect(tree.queryByText('快捷回复')).not.toBeInTheDocument()
    expect(tree.queryByText('AI 客服配置')).not.toBeInTheDocument()
    // issue #5246 契约翻转：`order:refund` 不再是「售后工单」节点的码（节点改用读码
    // `after_sales:view`）⇒ 它成了**没有菜单节点的写码**，按既有规则落进「操作权限」节
    // （该节位于本容器内）。「不出现在菜单树」这半条仍成立 —— 见下一行的计数断言。
    expect(within(screen.getByTestId('perm-extra-section')).getByText('订单退款')).toBeInTheDocument()
    expect(tree.queryAllByText('订单退款')).toHaveLength(1)
    // 🔴 #6580（2026-10-09）：`system:manage`（权限目录里的显示名「系统管理」）**不再是任何
    // 菜单节点的码** —— 合并后 `/settings` 的节点码 = `production:view`，该码改为在那个节点下的
    // org-center 权限码节点（`企业基础设置（经营域）`）上保留可授予性。
    // ⇒ 它按既有规则落进「操作权限」节（该节在本容器内），口径与上面的 `order:refund` **完全一样**：
    // 出现一次、且不在菜单组里重复渲染（这条计数断言防的正是「同一权限两处渲染」）。
    expect(within(screen.getByTestId('perm-extra-section')).getByText('系统管理')).toBeInTheDocument()
    expect(tree.queryAllByText('系统管理')).toHaveLength(1)
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

  it('编辑岗位按菜单回显：角色已有 order:list → 「销售订单」勾选', async () => {
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
    const orderItem = (await screen.findByText('销售订单')).closest('label')!
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
    // 🔴 2026-10-17（issue #7087）：**最前席位**（`standaloneHeadItems`：经营看板 / `dashboard:view`）
    // —— 它与 #5895 的尾席位是**同一形态**的入口（新增梯队、权限树没跟），必须同款接线。
    standaloneHeadItems: 'perm-standalone-head',
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

  it('类级守卫：**四个梯队**里每个带码菜单节点都能在权限树里勾到（漏接即红）', async () => {
    render(<RolesPage />)
    fireEvent.click(await screen.findByText('新增岗位'))
    const container = await screen.findByTestId('perm-menu-sections')
    // 菜单行 = 「菜单名 + 权限码」的 label（码在 `sr-only` 文本里 —— 不上可见面，但仍在
    // accessible name / `label.textContent` 里 ⇒ 本条接线判据照旧可判）；
    // 「操作权限」节渲染的是「权限名(action)」、不含码 ⇒ 同名条目（如旧大类码 product:manage
    // 也叫「商品管理」）**不会**把漏接的菜单项伪装成已接线。
    const rows = Array.from(container.querySelectorAll('label')).map(l => l.textContent || '')
    const coded = [
      ...menuConfig.menuGroups.flatMap(g => g.children),
      // 🔴 issue #7087：最前席位必须一起枚举 —— 只列尾席位会让「经营看板」的漏接**判不出来**
      ...menuConfig.standaloneHeadItems,
      ...menuConfig.standaloneTopItems,
      ...menuConfig.standaloneItems,
    ].filter(item => item.permissionCode)
    expect(coded.length).toBeGreaterThan(0) // 反空跑：没有可判的对象时本判据不算通过
    // 点名最前席位（避免将来又把它漏掉时这条判据「恰好」还是绿的）
    expect(coded.map(i => i.name)).toContain('经营看板')
    for (const item of coded) {
      const hit = rows.some(text => text.includes(item.name) && text.includes(item.permissionCode!))
      expect(hit, `菜单节点「${item.name}」(${item.permissionCode}) 未出现在权限树 —— 梯队接线漏了`).toBe(true)
    }
  })

  it('🔴 权限树顺序与侧边栏同源：#7087 最前席位在最前，「商品管理」「企业基础设置」随其后，二者都在**所有分组之前**', async () => {
    render(<RolesPage />)
    fireEvent.click(await screen.findByText('新增岗位'))
    const container = await screen.findByTestId('perm-menu-sections')
    const head = within(container).getByTestId('perm-standalone-head')
    const top = within(container).getByTestId('perm-standalone-top')
    expect(within(head).getByText('经营看板')).toBeInTheDocument()
    // 报表中心（#7376）与经营看板同码（报表是看板的下钻）⇒ 同码两节点各自渲染，勾任一即授予该码
    expect(within(head).getByText('报表中心')).toBeInTheDocument()
    expect(within(head).getAllByText('dashboard:view')).toHaveLength(2)
    // 🔴 #8086：商品管理已进「基础资料」组 ⇒ 尾席位只剩「企业基础设置」
    expect(within(top).getByText('企业基础设置')).toBeInTheDocument()
    expect(within(top).queryByText('商品管理')).toBeNull()
    // 位置与侧边栏同序（一级项块 → 分组 → 尾部项）：**席位块是权限树的第一个子块**
    // （#7087 前这条判的是 `perm-standalone-top`；最前席位加入后它退到第二个 —— 断言强度不降：
    //  现在多钉了「最前席位在最前」且「两个席位块连续」）。
    expect(container.firstElementChild).toBe(head)
    expect(container.firstElementChild!.nextElementSibling).toBe(top)
    // 判别力：旧形态（席位块排在分组之后）会让上面两条红
    expect(container.firstElementChild!.hasAttribute('data-testid')).toBe(true)
  })

  // ══════════════════════════════════════════════════════════════════════════
  // issue #6781：权限树里的手机端标注「一个码只出现一处」+ 落点在树序首个承载节点
  //
  // 语料 = 真配置（`@/config/menu` 的梯队）+ **未修形态**的菜单接口下发（每个承载节点上
  // 各带一遍该码的 `mobileTitles`）。判据只数「可见面渲染了几处标注」—— 与后端
  // `annotateMobileTitles` 的「首承载节点」是同一个可观察口径（前端只渲染服务端给的）。
  // ══════════════════════════════════════════════════════════════════════════

  /**
   * 「码 → 手机端面名」**夹具**（= 服务端 `MobileSurfaces` 真值在这 6 个码上的读数，
   * 逐字取自 issue #6781 的实测读数）。⚠️ 它**只存在于测试夹具**（模拟服务端下发），
   * 不是前端的映射表 —— 生产源码里没有第二份真值（判据 =
   * tests/unit_ci_workflows/test_mobile_surface_annotation_single_source.py 判据 3）。
   */
  const MOBILE_SURFACES_FIXTURE: Record<string, string[]> = {
    'dashboard:view': ['数据'],
    'agent:session': ['坐席'],
    'after_sales:view': ['售后处理'],
    'production:view': ['计件工资报表', '生产待办'],
    'processing:view': ['智能派单'],
    'inbound:view': ['入库过账'],
  }

  /**
   * 菜单接口下发（真 `GET /api/admin/menus` 的形状）：`onlyFirstCarrier` = 本单修后形态
   * （同一个码只在**树序首个承载节点**上带 `mobileTitles`，其余同码节点为空）。
   *
   * ⚠️ 承载节点**不止在组内**：`standaloneHeadItems`（「经营看板」`dashboard:view`）与
   * `standaloneTopItems`（「商品管理」`product:list` / 「企业基础设置」`production:view`）都是顶层的
   * **叶子节点**，服务端树里同样是带着 `mobileTitles` 的顶层条目
   *（`production:view` 因此有 3 个承载节点 —— 本单「名实不符」的那一个就在其中）。
   *
   * 🔴 2026-10-17（issue #7087）：`dashboard:view` 的承载节点由**两个**（工作台组的经营看板 +
   * 每日简报）降为**一个**（最前席位「经营看板」）—— 组撤销 + 菜单项删除的直接后果；
   * 本文件据此把「重复标注」锚点从 `dashboard:view` 收敛到 `production:view`（它仍是 3 处）。
   */
  const menuPayload = (onlyFirstCarrier: boolean) => {
    const seen = new Set<string>()
    const node = (c: { key: string; name: string; permissionCode?: string }) => {
      const code = c.permissionCode || c.key
      const titles = MOBILE_SURFACES_FIXTURE[code] || []
      const firstOfCode = !seen.has(code)
      seen.add(code)
      return { code, label: c.name, mobileTitles: onlyFirstCarrier && !firstOfCode ? [] : titles }
    }
    return [
      // 最前席位（issue #7087）：真服务端树里它是**顶层首个**条目
      ...menuConfig.standaloneHeadItems.map(c => ({ code: c.key, label: c.name, children: [node(c)] })),
      ...menuConfig.menuGroups.map(g => ({
        code: g.key,
        label: g.name,
        children: g.children.map(node),
      })),
      ...menuConfig.standaloneTopItems.map(c => ({ code: c.key, label: c.name, children: [node(c)] })),
    ]
  }

  it('🔴 #6781：未修形态（一个码在每个承载节点上各标注一次）⇒ 同屏出现重复/名实不符标注 ⇒ 红', async () => {
    mockRequestGet.mockResolvedValue({ data: { data: menuPayload(false) } })
    render(<RolesPage />)
    fireEvent.click(await screen.findByText('新增岗位'))
    const container = await screen.findByTestId('perm-menu-sections')

    // 锚定：未修形态下「同一个码 = 同一串标注」在**多个**节点上被渲染（同屏重复 §31 P2）
    expect(container.querySelectorAll('[data-testid^="roles-mobile-production:view"]')).toHaveLength(3)
    // 🔴 issue #7087 + #7376：`dashboard:view` 现有**两个**承载节点（经营看板 + 报表中心，同码）
    // ⇒ 未修形态下它也变成「同屏重复」的实例之一（与 `production:view` 同族读数）
    expect(container.querySelectorAll('[data-testid="roles-mobile-dashboard:view"]')).toHaveLength(2)
  })

  it('🔴 #6781 修后形态：每个权限码**只**在树序首个承载节点上渲染一处手机端标注（同屏重复与名实不符都归零）', async () => {
    // 修后形态的语料 = 服务端只把标注放在**树序首个承载节点**上（其余同码节点 `mobileTitles` 为空）
    // 🔴 判别力自证（不读磁盘）：同一份真配置下，**未修形态**的语料必然在同屏渲染出**重复**标注
    //（`production:view` 三处；`dashboard:view` 自 issue #7087 起只剩一处承载节点）；修后形态收敛为每码一处。
    const legacyCodes = menuPayload(false).flatMap(g => g.children)
      .filter(c => (c.mobileTitles || []).length > 0).map((c: any) => c.code)
    expect(legacyCodes.filter(c => c === 'production:view')).toHaveLength(3)
    expect(legacyCodes.filter(c => c === 'dashboard:view')).toHaveLength(2)
    expect(new Set(legacyCodes).size).toBeLessThan(legacyCodes.length)
    const fixedCodes = menuPayload(true).flatMap(g => g.children)
      .filter(c => (c.mobileTitles || []).length > 0).map((c: any) => c.code)
    expect(fixedCodes).toHaveLength(6)
    expect(new Set(fixedCodes).size).toBe(fixedCodes.length)
    mockRequestGet.mockResolvedValue({ data: { data: menuPayload(true) } })
    render(<RolesPage />)
    fireEvent.click(await screen.findByText('新增岗位'))
    const container = await screen.findByTestId('perm-menu-sections')

    // ① 可见文本（元素直属文本节点）里**不得**出现 `模块:动作` 形态的内部码。
    //    ⚠️ 必须按文本节点数，不能用 `container.textContent` —— `sr-only` 文本在 textContent 里仍可见
    //    （那正是「不上屏但保留可及性」的落点，本判据有意放行）。
    const codes = Array.from(container.querySelectorAll('label[title]'))
      .map(l => l.getAttribute('title')!)
    expect(codes.length).toBeGreaterThan(0)  // 反空跑：真配置里确实有带码菜单项
    expect(visibleText(container)).not.toMatch(/[a-z_]+:[a-z_]+/)
    // 「操作权限」节同样不得回显码（该节在同一个容器内，原本渲染 `(view)` 这类内部动作名以外的码）
    for (const code of codes) {
      expect(visibleText(container), code).not.toContain(code)
    }
    // 负控：同一把尺子对**真的**权限码会命中（否则上面两条是空断言）
    expect(codes, '真配置里应有带码菜单项').not.toHaveLength(0)
    expect(codes[0]).toMatch(/[a-z_]+:[a-z_]+/)

    // ② 非可见面：每个带码节点的 label 上仍有 `title` + `sr-only` 文本（可及性 / hover 不降级）
    for (const code of ['product:list', 'production:view', 'inbound:view']) {
      const span = container.querySelector(`[data-testid="roles-code-${code}"]`) as HTMLElement | null
      expect(span?.className, code).toContain('sr-only')
      expect(span?.textContent, code).toBe(code)
      expect(span?.closest('label')?.getAttribute('title'), code).toBe(code)
    }
  })

  it('#6770 红证（判别力自证·真语料）：把可见的码 span 加回去 ⇒ ①当场红；只改 title/sr-only ⇒ 不红', async () => {
    mockRequestGet.mockResolvedValue({ data: { data: menuPayload(false) } })
    render(<RolesPage />)
    fireEvent.click(await screen.findByText('新增岗位'))
    const container = await screen.findByTestId('perm-menu-sections')

    // 逐字复刻未修形态的那一行（`<span className="text-xs text-neutral-400" title={code}>{code}</span>`）
    const row = container.querySelector('label[title="inbound:view"]')!
    const legacy = document.createElement('span')
    legacy.className = 'text-xs text-neutral-400'
    legacy.setAttribute('title', 'inbound:view')
    legacy.textContent = 'inbound:view'
    row.appendChild(legacy)

    expect(visibleText(container)).toMatch(/[a-z_]+:[a-z_]+/)   // 注入生效 ⇒ 判据①必红
    legacy.remove()
    expect(visibleText(container)).not.toMatch(/[a-z_]+:[a-z_]+/) // 撤掉注入 ⇒ 绿（判别力自证）
  })

  it('#5895 勾选「基础资料 → 商品管理」→ 创建岗位时 permissionIds 含 product:list 的权限ID（勾得动）', async () => {
    mockGetRoles.mockResolvedValue({ data: { data: { items: [], total: 0 } } })
    render(<RolesPage />)
    fireEvent.click(await screen.findByText('新增岗位'))
    // 🔴 #8086：商品管理已进「基础资料」组 ⇒ 在该组小节内取标签（「操作权限」节里另有一个
    // 同名的 `product:manage` 旧码，全容器取会撞名 —— 与 #5895 的原始坑同源）
    const sections = within(await screen.findByTestId('perm-menu-sections'))
    const basic = sections.getByText('基础资料').closest('div')!.parentElement as HTMLElement
    fireEvent.click(within(basic).getByText('商品管理').closest('label')!.querySelector('input')!)
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
// ══════════════════════════════════════════════════════════════════════════════
// issue #6663：读面失败 ≠ 空态（三维审计逐条复核）
//
// 改前 `loadRoles` 的 catch 只 `toast.error` 而 `roles` 保持 `[]` ⇒ 页面落到「暂无岗位」，
// **故障被画成业务事实**（商家以为这个企业没有岗位）。范式 = dashboard/page.tsx（#5792 ④）。
// 类级收口 = tests/unit/read-failure-empty-state-guard.test.ts（本文件是它的实例面）。
// ══════════════════════════════════════════════════════════════════════════════
describe('RolesPage 读面失败态（issue #6663）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetPermissions.mockResolvedValue({ data: { data: PERMISSION_CATALOG } })
  })

  it('岗位清单读失败 ⇒ 显示失败态（**不是**「暂无岗位」）+ 重试出口', async () => {
    mockGetRoles.mockRejectedValue(new Error('500'))
    render(<RolesPage />)

    const failure = await screen.findByTestId('roles-load-error')
    expect(failure).toHaveTextContent('岗位加载失败')
    // 🔴 核心：不得落到空态那句 —— 否则商家读成「这个企业没有岗位」
    expect(screen.queryByText('暂无岗位，点击上方按钮新增')).not.toBeInTheDocument()
    // 重试出口真可点（点了重新发请求；这次成功 ⇒ 失败态退场、清单出来）
    mockGetRoles.mockResolvedValue({
      data: { data: { items: [{ id: 'r9', name: '新岗位', code: 'new_role', permissions: [], createdAt: '2026-06-03' }] } },
    })
    fireEvent.click(within(failure).getByRole('button', { name: '重新加载' }))
    await waitFor(() => expect(mockGetRoles).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(screen.getByText('新岗位')).toBeInTheDocument())
    expect(screen.queryByTestId('roles-load-error')).not.toBeInTheDocument()
  })

  it('岗位清单读成功且为空 ⇒ 仍是空态那句（对照读数：失败态不吞掉真空态）', async () => {
    mockGetRoles.mockResolvedValue({ data: { data: { items: [], total: 0 } } })
    render(<RolesPage />)

    await waitFor(() => expect(screen.getByText('暂无岗位，点击上方按钮新增')).toBeInTheDocument())
    expect(screen.queryByTestId('roles-load-error')).not.toBeInTheDocument()
  })

  it('权限目录读失败 ⇒ 权限分配里显示失败态（**不是**「暂无权限数据」），且权限树不渲染', async () => {
    mockGetRoles.mockResolvedValue({
      data: { data: { items: [{ id: 'r1', name: '管理员', code: 'admin', permissions: [], createdAt: '2026-06-01' }] } },
    })
    mockGetPermissions.mockRejectedValue(new Error('500'))
    render(<RolesPage />)

    // 新增岗位 ⇒ 打开弹窗（权限分配是弹窗内容）
    await waitFor(() => expect(screen.getByText('新增岗位')).toBeInTheDocument())
    fireEvent.click(screen.getByText('新增岗位'))

    const failure = await screen.findByTestId('roles-permissions-error')
    expect(failure).toHaveTextContent('权限目录读取失败')
    expect(screen.queryByText('暂无权限数据')).not.toBeInTheDocument()
    expect(screen.queryByTestId('perm-menu-sections')).not.toBeInTheDocument()
  })
})

/**
 * issue #7146：**默认菜单 = 后台 + 手机端（一份菜单的两次投影）**。
 *
 * 用户 2026-10-17 逐字：「手机端可见面要不要作为『默认岗位默认菜单』的一部分，当然需要，
 * **把 PC 和手机端当一个整体**」。
 *
 * 判据的真值面：
 * - 后台菜单名 = `@/config/menu`（侧边栏真值源，三源同构）；
 * - 手机端面名 = 服务端 `GET /api/admin/menus` 的 `mobileTitles`（真值 = `MobileSurfaces`）；
 *   🔴 本文件的语料**必须**能证明「页面透传服务端、不自造表」——改名夹具 ⇒ 页面跟着改。
 */
describe('RolesPage 默认菜单 = 后台 + 手机端（issue #7146）', () => {
  // ⚠️ 本块是**独立的顶层 describe**：上面那个 `beforeEach` 不覆盖这里的用例
  //（曾因此让 `mockGetWorkerPages` 无实现 ⇒ 页面落到失败态、断言超时）——缺省语料在这里自带一份。
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetRoles.mockResolvedValue({
      data: {
        data: {
          items: [
            { id: 'r-cs', name: '客服', code: 'customer_service', description: '职责：在线接待客户咨询与投诉。', permissions: [], createdAt: '2026-06-02' },
          ],
        },
      },
    })
    mockGetPermissions.mockResolvedValue({ data: { data: PERMISSION_CATALOG } })
    mockRequestGet.mockRejectedValue(new Error('not mocked'))
    mockGetWorkerPages.mockResolvedValue({
      data: {
        data: {
          pages: ['report', 'piecework', 'order', 'cut_calc', 'shipment'],
          labels: { report: '报工', piecework: '计件工资报表', order: '订单', cut_calc: '裁高计算器', shipment: '发货' },
        },
      },
    })
  })

  const roleWithCodes = (codes: string[]) => ({
    data: {
      data: {
        items: [
          {
            id: 'r-cs',
            name: '客服',
            code: 'customer_service',
            description: '职责：在线接待客户咨询与投诉，跟进订单进度。',
            permissions: codes.map((code, i) => ({ id: `p-${i}`, code, name: code })),
            createdAt: '2026-06-02',
          },
        ],
      },
    },
  })

  const menusPayload = (titles: Record<string, string[]>) => ({
    data: {
      data: [
        {
          code: 'dashboard',
          label: '经营看板',
          children: [{ code: 'dashboard:view', label: '经营看板', mobileTitles: titles['dashboard:view'] || [] }],
        },
        {
          code: 'customer-service',
          label: '客户服务',
          children: [
            { code: 'agent:session', label: '在线接待', mobileTitles: titles['agent:session'] || [] },
            { code: 'order:list', label: '销售订单', mobileTitles: titles['order:list'] || [] },
          ],
        },
      ],
    },
  })

  it('同一张卡给「后台 N 项」与「手机端 M 个入口」：默认收起，展开看两份清单', async () => {
    mockGetRoles.mockResolvedValue(roleWithCodes(['dashboard:view', 'agent:session', 'order:list']))
    mockRequestGet.mockResolvedValue(
      menusPayload({ 'dashboard:view': ['数据'], 'agent:session': ['坐席'] }),
    )
    render(<RolesPage />)

    const card = await screen.findByTestId('role-default-menu-customer_service')
    await waitFor(() =>
      expect(within(card).getByTestId('role-default-menu-summary-customer_service')).toHaveTextContent(
        '默认菜单：后台 6 项 · 手机端 2 个入口',
      ),
    )
    // §31 P1 常驻面克制：折叠态下清单不渲染（不是 CSS 隐藏）
    expect(screen.queryByTestId('role-default-menu-backend-customer_service')).toBeNull()

    fireEvent.click(within(card).getByRole('button', { name: /默认菜单/ }))
    // 报表中心（#7376）与经营看板同码 ⇒ 勾了 dashboard:view 的岗位默认菜单里**两项都在**
    expect(await screen.findByTestId('role-default-menu-backend-customer_service')).toHaveTextContent(
      '经营看板、报表中心、在线接待、价格本、销售订单',
    )
    expect(screen.getByTestId('role-default-menu-mobile-customer_service')).toHaveTextContent('数据、坐席')
    expect(within(card).getByRole('button', { name: /默认菜单/ })).toHaveAttribute('aria-expanded', 'true')
  })

  it('手机端面名逐字取服务端下发：服务端改名 ⇒ 页面跟着改（前端没有第二张表）', async () => {
    mockGetRoles.mockResolvedValue(roleWithCodes(['dashboard:view']))
    mockRequestGet.mockResolvedValue(menusPayload({ 'dashboard:view': ['数据（服务端改名）'] }))
    render(<RolesPage />)

    const card = await screen.findByTestId('role-default-menu-customer_service')
    fireEvent.click(await within(card).findByRole('button', { name: /默认菜单/ }))
    expect(await screen.findByTestId('role-default-menu-mobile-customer_service')).toHaveTextContent(
      '数据（服务端改名）',
    )
  })

  it('没有手机端可见码的岗位 ⇒ 手机端 0 个入口（不是「全给」也不是「无权限报错」）', async () => {
    mockGetRoles.mockResolvedValue(roleWithCodes(['order:list']))
    mockRequestGet.mockResolvedValue(menusPayload({}))
    render(<RolesPage />)

    const card = await screen.findByTestId('role-default-menu-customer_service')
    await waitFor(() =>
      expect(within(card).getByTestId('role-default-menu-summary-customer_service')).toHaveTextContent(
        // #7375 段 3：`order:list` 现在覆盖三项（价格本 / 销售订单 / 发货单）⇒ 后台 2 项 → 3 项
        '默认菜单：后台 3 项 · 手机端 0 个入口',
      ),
    )
    fireEvent.click(within(card).getByRole('button', { name: /默认菜单/ }))
    expect(await screen.findByTestId('role-default-menu-mobile-customer_service')).toHaveTextContent('无')
  })

  it('工人只读卡（#7146 用户裁定）：页名逐字取服务端目录、无编辑/删除、链接到工人档案', async () => {
    render(<RolesPage />)

    const card = await screen.findByTestId('worker-menu-card')
    expect(card).toHaveTextContent('工人')
    expect(card).toHaveTextContent('只读')
    const pages = await screen.findByTestId('worker-menu-pages')
    for (const label of ['报工', '计件工资报表', '订单', '裁高计算器', '发货']) {
      expect(pages, label).toHaveTextContent(label)
    }
    // 只读：卡片里没有编辑 / 删除按钮（工人不是 roles 行，不能在这里改）
    expect(within(card).queryByTitle('编辑')).toBeNull()
    expect(within(card).queryByTitle('删除')).toBeNull()
    // 逐人配置的出口：员工管理（工人档案）
    expect(within(card).getByRole('link')).toHaveAttribute('href', '/employees')
  })

  it('工人端页面目录读失败 ⇒ 显式失败态 + 重试（不画成「没有页面」）', async () => {
    mockGetWorkerPages.mockRejectedValueOnce(new Error('403'))
    render(<RolesPage />)

    const failure = await screen.findByTestId('worker-menu-error')
    expect(failure).toHaveTextContent('工人端页面目录读取失败')
    expect(screen.queryByTestId('worker-menu-pages')).not.toBeInTheDocument()

    fireEvent.click(within(failure).getByRole('button', { name: '重试' }))
    await waitFor(() => expect(mockGetWorkerPages).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(screen.getByTestId('worker-menu-pages')).toHaveTextContent('报工'))
  })
})
