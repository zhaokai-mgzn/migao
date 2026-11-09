// case_ids: OR-001, OR-002, OR-003, OR-004, OR-005, UI-057, UI-058, UI-130
/**
 * 销售订单列表 · 整行点击进详情 + 操作按钮平铺（2026-11-07 用户裁定）。
 *
 * ## 改动来源（用户逐字）
 *
 * 「一、需要支持订单非操作区域整行可点击，点击跳转至对应订单的订单详情页；
 *  二、操作一列：把订单对应的可操作按钮直接展示出来，不要收在『...』里面」。
 *
 * ⇒ 本页**推翻** issue #8011 在本页落的「1 主行动 + ⋯ 菜单」形态：操作列改成平铺
 * （主行动仍是 `Button variant="ghost"`，其余动作 = `RowActionLink`），并给非操作区域加整行点击。
 * 其它列表页的「⋯」菜单形态（`RowActions`）不受影响。
 *
 * ## 本文件的判据（会红，不是"看起来像"）
 *
 * ① 「不加急」全表**零出现**（非加急行 `textContent === ''`，不是灰字、不是 CSS 隐藏）；
 * ② 操作列**没有「⋯」入口**：每行 `queryByRole('menu')` / 「更多操作」均为空；所有可做动作
 *    同屏可见，按钮数 = 主行动 + 平铺动作数（逐状态可证伪）；
 * ③ 主行动**按状态派生**：待付款→`收款`、待发货→`发货`、已发货→`确认收货`、其它→无；
 * ④ 加急行渲染**醒目徽标**（彩色 Badge，不是同字号灰字），非加急行空单元格；
 * ⑤ 订单号单元格有复制按钮（`aria-label="复制订单号"`），点击**真写剪贴板**并 toast 提示；
 * ⑥ **整行点击**：点非操作区域（收货人 / 状态 / 金额…）⇒ `router.push('/orders/{id}')`；
 *    点操作按钮 / 操作格内边距 / 复制按钮 / 备注预览 ⇒ **不跳转**，各自动作照旧执行。
 *
 * **注入式红证**（复核用，非本文件运行时执行）：
 * - 把 `renderActions` 改回 `RowActions`（1 主行动 + ⋯ 菜单）⇒ ② 的「无更多操作」与逐状态按钮数当场红；
 * - 去掉 `<tr onClick>` ⇒ ⑥ 的第一条（非操作区域跳详情）红；
 * - 去掉操作 `<td>` 的 `stopPropagation` ⇒ ⑥ 的「点操作格不跳转」红；
 * - 去掉复制按钮 / 备注预览的 `stopPropagation` ⇒ ⑥ 的对应负控红；
 * - 把非加急分支写回 `{urgentBadgeText(order)}` ⇒ ① 当场红（全表出现「不加急」）；
 * - 把主行动映射改错（待付款 ⇒ `发货`）⇒ ③ 当场红。
 *
 * ## 为什么渲染**整页**而不是只渲染 OrderTable
 *
 * 判据是**页面级**形态（整行点击的落点 = 页面路由、操作列的逐状态按钮集合）。页面测试才覆盖
 * 「表格 + 分页 + 筛选」同屏的真实组合；`@/components/orders` 与 `@/components/ui` **都不替身**
 * （替身会让判据测到自己写的 mock）。
 *
 * 相邻判据（不重复）：
 * - 加急**取值口径**（服务端 `isUrgent` 缺省 = 不加急）⇒ `tests/unit/components/OrderTableUrgency.test.tsx`；
 * - 确认动作走自研 Modal（不是 `window.confirm`）⇒ `tests/unit/pages/orders-confirm-modal.test.tsx`；
 * - 「操作」列右缘冻结几何 ⇒ `tests/unit/wide-table-action-column-guard.test.ts`；
 * - 行内快捷发货 / 焦点归位 ⇒ `tests/unit/pages/orders-inline-ship.test.tsx`。
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'

// 页面按 `order:create` 显隐「新增订单」（issue #5983）⇒ 渲染必须带登录态（与 orders.test.tsx 同口径）
const authMock = vi.hoisted(() => ({
  state: { user: { id: '1', username: 'admin', name: '管理员', permissions: ['*'], roles: [] } },
}))
vi.mock('@/store/auth', () => ({
  useAuthStore: (selector?: (s: unknown) => unknown) =>
    typeof selector === 'function' ? selector(authMock.state) : authMock.state,
}))

const routerMock = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  back: vi.fn(),
  prefetch: vi.fn(),
}))
vi.mock('next/navigation', () => ({
  useRouter: () => routerMock,
  useSearchParams: () => new URLSearchParams(),
}))
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

const api = vi.hoisted(() => ({
  getOrders: vi.fn(),
  confirmPayment: vi.fn(),
  updateOrderStatus: vi.fn(),
  deleteOrder: vi.fn(),
  refundOrder: vi.fn(),
  addRemark: vi.fn(),
  closeOrder: vi.fn(),
}))
vi.mock('@/lib/api', () => ({ orderApi: api }))

// 惰性代理 mock：不逐个列图标名（闭集 mock 会在任一新图标 import 时假红）
vi.mock('lucide-react', async (importOriginal) =>
  (await import('../helpers/lucide-mock')).lucideMock((await importOriginal()) as Record<string, unknown>))

// toast 要断言「点了复制有反馈」⇒ 用本文件的桩（setup.ts 的全局 mock 无断言接口）
const toastMock = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  info: vi.fn(),
  warning: vi.fn(),
  loading: vi.fn(() => 'toast-1'),
  dismiss: vi.fn(),
}))
vi.mock('sonner', () => ({ toast: toastMock }))

import OrdersPage from '@/app/(dashboard)/orders/page'

/** 四种状态各一行（覆盖主行动派生的全部四档）+ 加急只在待发货那行 */
const ROWS = [
  {
    id: 'pay',
    orderNo: 'MG-PAY-0001',
    status: 'pending_payment',
    totalAmount: 1000,
    actualAmount: 0,
    customerName: '张先生',
    customerPhone: '13800000001',
    customerAddress: '浙江省杭州市西湖区文三路 100 号',
    hasProcessing: false,
    createdAt: '2026-11-06T10:00:00Z',
    items: [],
    isUrgent: false,
    remark: '[2026-11-06 09:00] 客户催单',
  },
  {
    id: 'ship',
    orderNo: 'MG-SHIP-0002',
    status: 'pending_shipment',
    totalAmount: 2000,
    actualAmount: 2000,
    customerName: '李女士',
    customerPhone: '13800000002',
    customerAddress: '江苏省南京市玄武区中山路 200 号',
    hasProcessing: false,
    createdAt: '2026-11-05T10:00:00Z',
    items: [],
    // 唯一的加急行 ⇒ 「加急徽标只出现在这一行」可逐单证伪
    isUrgent: true,
    requiredDeliveryDate: '2026-11-12',
    refundAmount: 0,
  },
  {
    id: 'recv',
    orderNo: 'MG-RECV-0003',
    status: 'shipped',
    totalAmount: 3000,
    actualAmount: 3000,
    customerName: '王先生',
    customerPhone: '13800000003',
    customerAddress: '上海市浦东新区陆家嘴金融中心',
    hasProcessing: false,
    createdAt: '2026-11-04T10:00:00Z',
    items: [],
    isUrgent: false,
    refundAmount: 0,
  },
  {
    id: 'done',
    orderNo: 'MG-DONE-0004',
    status: 'completed',
    totalAmount: 4000,
    actualAmount: 4000,
    customerName: '赵女士',
    customerPhone: '13800000004',
    customerAddress: '北京市朝阳区建国路 88 号',
    hasProcessing: false,
    createdAt: '2026-11-03T10:00:00Z',
    items: [],
    isUrgent: false,
    refundAmount: 0,
  },
]

const ALL_IDS = ROWS.map((r) => r.id)

/**
 * 逐状态「同屏可点的操作按钮」集合（2026-11-07 平铺形态）。
 * 主行动 + 平铺动作，按现有条件派生；顺序与 `renderActions` 一致。
 */
const EXPECTED_ACTION_LABELS: Record<string, string[]> = {
  pay: ['收款', '查看详情', '备注', '关闭订单'],
  ship: ['发货', '查看详情', '备注', '处理退款', '去发货页'],
  recv: ['确认收货', '查看详情', '备注', '处理退款'],
  done: ['查看详情', '备注', '处理退款'],
}

function renderPage() {
  return render(<OrdersPage />)
}

/**
 * jsdom 不提供 `navigator.clipboard` ⇒ 装一个可断言的桩（**每个用例新装**，避免跨用例串读数）。
 * 返回 `writeText` 桩：复制按钮必须**真写**它一次，才算「能复制」。
 */
function stubClipboard() {
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText },
    configurable: true,
  })
  return writeText
}

/** 等首屏列表落地（否则后面量的都是「空表」） */
async function waitForRows() {
  await waitFor(() => expect(api.getOrders).toHaveBeenCalled())
  await waitFor(() => expect(screen.getByTestId('order-actions-pay')).toBeInTheDocument())
}

const actionsCell = (id: string) => screen.getByTestId(`order-actions-${id}`)
const actionButton = (id: string, label: string) =>
  within(actionsCell(id)).getByRole('button', { name: label })

describe('销售订单列表 · 整行点击 + 操作按钮平铺（2026-11-07 用户裁定）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.getOrders.mockResolvedValue({ data: { data: { items: ROWS, total: ROWS.length } } })
  })

  // ================= ① 加急列的零噪声 =================

  it('① 全表「不加急」出现次数 = 0（非加急行不渲染任何文字，空单元格）', async () => {
    renderPage()
    await waitForRows()

    expect(screen.queryAllByText(/不加急/)).toHaveLength(0)
    for (const id of ['pay', 'recv', 'done']) {
      // 空单元格 = **真的没内容**（`textContent === ''`，不是 CSS 隐藏 / sr-only）
      expect(screen.getByTestId(`order-urgent-${id}`).textContent).toBe('')
    }
  })

  // ================= ④ 加急行有视觉强度 =================

  it('④ 加急行渲染醒目徽标（彩色 Badge）；非加急行不渲染徽标', async () => {
    renderPage()
    await waitForRows()

    const urgentCell = screen.getByTestId('order-urgent-ship')
    const badge = within(urgentCell).getByText('加急')
    // 醒目 = 走了 `Badge variant="warning"`（描边 + 底色），不是同字号灰字
    expect(badge.className).toMatch(/bg-amber-50/)
    expect(badge.className).toMatch(/border-amber-200/)

    // 反向（非空断言的关键）：其余三行连「加急」字样都没有 —— 不许整表一个值
    for (const id of ['pay', 'recv', 'done']) {
      expect(within(screen.getByTestId(`order-urgent-${id}`)).queryByText('加急')).toBeNull()
    }
  })

  // ================= ② 操作按钮平铺、没有「⋯」 =================

  it('② 每行的可做动作**同屏平铺**：没有「更多操作」触发器、没有菜单，按钮集合逐状态可证伪', async () => {
    renderPage()
    await waitForRows()

    for (const id of ALL_IDS) {
      const cell = actionsCell(id)
      // 「平铺」的机器读数：没有 ⋯ 触发器、也没有菜单（收起态/展开态都不许有）
      expect(within(cell).queryByRole('button', { name: '更多操作' })).toBeNull()
      expect(within(cell).queryByRole('menu')).toBeNull()
      expect(within(cell).queryByRole('menuitem')).toBeNull()

      // 逐状态正控：该做的动作全在，且**没有**被漏掉/多出来
      const labels = within(cell)
        .getAllByRole('button')
        .map((b) => (b.textContent || '').trim())
      expect(labels, `订单 ${id} 的同屏动作集合漂移了`).toEqual(EXPECTED_ACTION_LABELS[id])
    }
  })

  it('② 负控：旧形态「1 主行动 + ⋯ 菜单」在本页不再出现（菜单项文案只以平铺按钮露出）', async () => {
    renderPage()
    await waitForRows()

    // 行内可点元素不再是「主行动 + 触发器」两枚；待发货行 = 主行动 1 + 平铺动作 4
    expect(within(actionsCell('ship')).getAllByRole('button')).toHaveLength(5)
    // 旧形态的「⋯」触发器不在了；而「去发货页」现在直接可见（不再是菜单项）
    expect(within(actionsCell('ship')).queryByLabelText('更多操作')).toBeNull()
    expect(actionButton('ship', '去发货页')).toBeInTheDocument()
  })

  // ================= ③ 主行动按状态派生 =================

  it('③ 待付款行主行动 = 收款；待发货行 = 发货', async () => {
    renderPage()
    await waitForRows()

    expect(within(screen.getByTestId('order-primary-pay')).getByRole('button').textContent).toBe('收款')
    expect(within(screen.getByTestId('order-primary-ship')).getByRole('button').textContent).toBe('发货')
  })

  it('③ 已发货行主行动 = 确认收货；已完成行无主行动（只剩平铺动作）', async () => {
    renderPage()
    await waitForRows()

    expect(within(screen.getByTestId('order-primary-recv')).getByRole('button').textContent).toBe('确认收货')
    // completed 没有派生主行动 ⇒ 主行动位不渲染（不是渲染一个禁用按钮占位）
    expect(screen.queryByTestId('order-primary-done')).toBeNull()
    // 而平铺动作仍在（每行都能操作，只是没有「主」行动）
    expect(actionButton('done', '查看详情')).toBeInTheDocument()
  })

  it('③ 一屏至多一个 primary（§32.2）：行内动作一律不走主色实心 variant', async () => {
    renderPage()
    await waitForRows()

    const solidPrimary = ALL_IDS.flatMap((id) =>
      within(actionsCell(id))
        .getAllByRole('button')
        // `Button variant="primary"` = 实心主色（一屏只许一个，那一个是「新增订单」）
        .filter((b) => /bg-primary-600/.test(b.className)),
    )
    expect(solidPrimary).toHaveLength(0)
  })

  // ================= ⑤ 订单号可复制 =================

  it('⑤ 订单号单元格有复制按钮（aria-label="复制订单号"）：点击写剪贴板并 toast', async () => {
    const writeText = stubClipboard()
    renderPage()
    await waitForRows()

    const copies = screen.getAllByRole('button', { name: '复制订单号' })
    // 每行一个（不是整表一个 —— 否则复制到的是「那一行」还是「第一行」就说不清）
    expect(copies).toHaveLength(ROWS.length)

    fireEvent.click(copies[0])
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('MG-PAY-0001'))
    await waitFor(() => expect(toastMock.success).toHaveBeenCalled())
  })

  it('⑤ 复制的是**该行**的订单号（逐单可证伪：点第 3 行拿到的不是第 1 行的号）', async () => {
    const writeText = stubClipboard()
    renderPage()
    await waitForRows()

    fireEvent.click(screen.getAllByRole('button', { name: '复制订单号' })[2])
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('MG-RECV-0003'))
    expect(writeText).not.toHaveBeenCalledWith('MG-PAY-0001')
  })

  // ================= ⑥ 整行点击（非操作区域） =================

  it('⑥ 点非操作区域（收货人 / 状态 / 金额）⇒ 跳该行订单详情', async () => {
    renderPage()
    await waitForRows()

    // 收货人单元格（非操作区域；第 9 格，0 起 = 8）
    fireEvent.click(screen.getByTestId('order-row-ship').querySelectorAll('td')[8])
    expect(routerMock.push).toHaveBeenCalledWith('/orders/ship')

    // 状态单元格（非操作区域）—— 再点另一行，证明不是「只对第一行生效」。
    // 用行内第 2 格（状态）定位，避免依赖状态文案在多处出现。
    const statusCell = screen.getByTestId('order-row-done').querySelectorAll('td')[1]
    fireEvent.click(statusCell)
    expect(routerMock.push).toHaveBeenCalledWith('/orders/done')
    expect(routerMock.push).toHaveBeenCalledTimes(2)
  })

  it('⑥ 点「操作」列（按钮 / 格内空白）⇒ 不跳详情，各自动作照旧执行', async () => {
    renderPage()
    await waitForRows()

    // 平铺动作按钮自己 stopPropagation
    fireEvent.click(actionButton('ship', '备注'))
    expect(routerMock.push).not.toHaveBeenCalled()
    expect(await screen.findByText('添加备注')).toBeInTheDocument()

    // 「操作」格的内边距 / 空白也不能触发跳转（整格拦截，不只靠按钮自己）
    fireEvent.click(actionsCell('pay'))
    expect(routerMock.push).not.toHaveBeenCalled()
  })

  it('⑥ 点复制订单号 / 备注预览 ⇒ 不跳详情（行内交互元素各自拦冒泡）', async () => {
    stubClipboard()
    renderPage()
    await waitForRows()

    // 复制按钮
    fireEvent.click(screen.getByTestId('order-copy-pay'))
    expect(routerMock.push).not.toHaveBeenCalled()

    // 备注预览（点开浮层，不进详情）
    fireEvent.click(screen.getByText(/客户催单/))
    expect(routerMock.push).not.toHaveBeenCalled()
    expect(await screen.findByRole('tooltip')).toBeInTheDocument()
  })

  it('⑥ 主行动点「发货」仍是就地展开（不跳页），展开后整行点击也不误触', async () => {
    renderPage()
    await waitForRows()

    fireEvent.click(within(screen.getByTestId('order-primary-ship')).getByRole('button'))
    expect(routerMock.push).not.toHaveBeenCalled()
    expect(screen.getByTestId('ship-inline-form')).toBeInTheDocument()

    // 展开行（录入区）不是可点击行；点它不应把页面带走
    fireEvent.click(screen.getByTestId('ship-inline-row-ship'))
    expect(routerMock.push).not.toHaveBeenCalled()
  })

  // ================= 「保持原有行为」= 只改形态，不改语义 =================

  it('平铺后的动作保持原行为：查看详情跳详情页、备注仍打开备注弹框', async () => {
    renderPage()
    await waitForRows()

    // 待发货行：查看详情 → 详情页（改前在 ⋯ 菜单里，容器变了、回调没变）
    fireEvent.click(actionButton('ship', '查看详情'))
    expect(routerMock.push).toHaveBeenCalledWith('/orders/ship')

    // 备注 → 备注弹框（`RemarkModal` 自带标题「添加备注」，没有 role="dialog"）
    fireEvent.click(actionButton('ship', '备注'))
    expect(await screen.findByText('添加备注')).toBeInTheDocument()
  })

  it('主行动仍是原行为：待付款行「收款」开确认弹框（不直接改状态）', async () => {
    renderPage()
    await waitForRows()

    fireEvent.click(within(screen.getByTestId('order-primary-pay')).getByRole('button'))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/已收到客户付款|确认付款/)).toBeInTheDocument()
    expect(api.confirmPayment).not.toHaveBeenCalled()
  })

  it('处理退款仍受「可退状态 + 未退过款」约束（权限判断不变，只是不再收在菜单里）', async () => {
    renderPage()
    await waitForRows()

    // 待付款行不可退 ⇒ 整行文本里没有这一项（旧实现同样不渲染）
    expect(within(actionsCell('pay')).queryByText('处理退款')).toBeNull()
    expect(actionButton('pay', '关闭订单')).toBeInTheDocument()

    // 已发货行可退 ⇒ 平铺可见，点击仍弹退款弹框
    fireEvent.click(actionButton('recv', '处理退款'))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })

  it('关闭订单只在待付款行平铺展示，点击仍走既有确认弹框', async () => {
    renderPage()
    await waitForRows()

    expect(actionButton('pay', '关闭订单')).toBeInTheDocument()
    for (const id of ['ship', 'recv', 'done']) {
      expect(within(actionsCell(id)).queryByText('关闭订单')).toBeNull()
    }

    fireEvent.click(actionButton('pay', '关闭订单'))
    // 本仓自研 `Modal` / `CloseOrderModal` 没有 role="dialog"（与 RemarkModal 同口径）⇒ 按标题正控
    expect(await screen.findByRole('heading', { name: '关闭订单' })).toBeInTheDocument()
    expect(api.closeOrder).not.toHaveBeenCalled()
  })
})

// ================= 选择列（假动作）已移除（issue #8052） =================
//
// 用户 2026-10-29 裁定：「先移除」—— 每行勾选框 / 表头全选框选完**没有任何批量动作消费它**
// （全仓无 `selectedIds` 消费者）⇒ 能点但没用的假动作（`migao-dev-flow` §31 P1）。
// 重启条件：真需要批量能力时**连动作一起设计**再放回选择列（见 issue #8052）。
//
// 本文件渲染的是**真页面 + 真 OrderTable**（两处组件都不替身）⇒ 列头 / 行内形态、
// 列数与 `colSpan` 的一致性都是真读数，不是测自己写的 mock。
describe('销售订单列表 · 选择列已移除（issue #8052）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.getOrders.mockResolvedValue({ data: { data: { items: ROWS, total: ROWS.length } } })
  })

  it('① 表头无全选 checkbox、行内无 checkbox 单元格（整页零 checkbox）', async () => {
    renderPage()
    await waitForRows()

    // 红证：把 `<th>` 里的全选勾选框（或每行 `<td>` 里的勾选框）注回去 ⇒ 下面两条当场红
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0)
    expect(document.querySelectorAll('table input[type="checkbox"]')).toHaveLength(0)

    // 正控（防止「整张表没渲染」让上面两条空跑通过）：表还在，且首个表头是「订单ID」而非空占位
    const headerCells = Array.from(document.querySelectorAll('table thead th'))
    expect(headerCells).toHaveLength(14)
    expect(headerCells[0].textContent?.trim()).toBe('订单ID')
    // 数据行格数 = 列数（移除一列后没有留下空 `<td>`）
    expect(document.querySelectorAll('table tbody tr:first-child td')).toHaveLength(14)
  })

  it('② 列数 = 14，加载态 / 空态的 colSpan 一并收敛（列数变了 colSpan 没跟上 = 表格错位）', async () => {
    // 加载态：issue #8048 起是**通用表格骨架**（页面级三元），此时根本没有 <table>
    // ⇒ 列数一致性改为在**骨架**上量：首行占位格必须同样 14 个，否则「骨架比真实列多」的错位又回来了
    api.getOrders.mockReturnValue(new Promise(() => {}))
    const loading = renderPage()
    const skeleton = await screen.findByTestId('table-skeleton')
    expect(document.querySelector('table')).toBeNull()
    const firstRow = skeleton.querySelectorAll('[data-testid="table-skeleton-row"]')[0]
    expect(firstRow.querySelectorAll('div')).toHaveLength(14)
    loading.unmount()

    // 空态：同样必须 14（改前这里是 15 —— 那正是「骨架/占位比真实列数多」的错位形态）
    api.getOrders.mockResolvedValue({ data: { data: { items: [], total: 0 } } })
    renderPage()
    await waitFor(() => expect(screen.getByTestId('orders-empty')).toBeInTheDocument())
    expect(document.querySelectorAll('table thead th')).toHaveLength(14)
    expect(screen.getByTestId('orders-empty').getAttribute('colspan')).toBe('14')
  })
})
