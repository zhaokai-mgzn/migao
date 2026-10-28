// case_ids: OR-001, OR-002, OR-003, OR-004, OR-005, UI-057, UI-058, UI-130
/**
 * 销售订单列表 · 行内操作收敛 + 噪声清理（issue #8011，B 端体验打磨 P0-1）。
 *
 * ## 改前（真机读数，2026-10-24 截图 `14-orders-list.png`）
 *
 * ① 每行 **4 个同级文字链**：`查看 · 备注 · 发货 · 处理退款` —— 20 行/页 ⇒ 单屏 **80** 个可点文本，
 *    没有层级、没有主行动；
 * ② 普通行的「加急」列把**「不加急」**印在每一行（同屏零信息量重复，`migao-dev-flow` §31 P2）；
 * ③ 订单号是 17 位纯数字，**没有复制入口**；
 * ④ 加急与不加急同样字号 ⇒ 扫视读不出来。
 *
 * ## 本文件的判据（会红，不是"看起来像"）
 *
 * ① 「不加急」全表**零出现**（非加急行 `textContent === ''`，不是灰字、不是 CSS 隐藏）；
 * ② 每行操作区**可点元素 ≤ 2**（1 主行动 + 1 菜单触发器），且旧的四文字链形态**不再同屏**；
 * ③ 主行动**按状态派生**：待付款→`收款`、待发货→`发货`、已发货→`确认收货`、其它→无；
 * ④ 加急行渲染**醒目徽标**（彩色 Badge，不是同字号灰字），非加急行空单元格；
 * ⑤ 订单号单元格有复制按钮（`aria-label="复制订单号"`），点击**真写剪贴板**并 toast 提示。
 *
 * **注入式红证**（复核用，非本文件运行时执行）：
 * - 把 `renderActions` 恢复成旧的 4 个 `RowActionLink` ⇒ ② 的「≤ 2」与负控当场红；
 * - 把非加急分支写回 `{urgentBadgeText(order)}` ⇒ ① 当场红（全表出现「不加急」）；
 * - 把主行动映射改错（待付款 ⇒ `发货`）⇒ ③ 当场红；
 * - 把复制按钮的 `aria-label` 改掉 / 去掉 clipboard 调用 ⇒ ⑤ 当场红。
 *
 * ## 为什么渲染**整页**而不是只渲染 OrderTable
 *
 * issue 的判据是**页面级**形态（单屏 80 个可点文本、一屏至多一个 primary）。页面测试才覆盖
 * 「表格 + 分页 + 筛选」同屏的真实组合；`@/components/orders` 与 `@/components/ui` **都不替身**
 * （替身会让判据测到自己写的 mock）。
 *
 * 相邻判据（不重复）：
 * - 加急**取值口径**（服务端 `isUrgent` 缺省 = 不加急）⇒ `tests/unit/components/OrderTableUrgency.test.tsx`；
 * - 确认动作走自研 Modal（不是 `window.confirm`）⇒ `tests/unit/pages/orders-confirm-modal.test.tsx`；
 * - 「操作」列右缘冻结几何 ⇒ `tests/unit/wide-table-action-column-guard.test.ts`。
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
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
    hasProcessing: false,
    createdAt: '2026-10-20T10:00:00Z',
    items: [],
    isUrgent: false,
  },
  {
    id: 'ship',
    orderNo: 'MG-SHIP-0002',
    status: 'pending_shipment',
    totalAmount: 2000,
    actualAmount: 2000,
    customerName: '李女士',
    hasProcessing: false,
    createdAt: '2026-10-21T10:00:00Z',
    items: [],
    // 唯一的加急行 ⇒ 「加急徽标只出现在这一行」可逐单证伪
    isUrgent: true,
    requiredDeliveryDate: '2026-10-30',
    refundAmount: 0,
  },
  {
    id: 'recv',
    orderNo: 'MG-RECV-0003',
    status: 'shipped',
    totalAmount: 3000,
    actualAmount: 3000,
    customerName: '王先生',
    hasProcessing: false,
    createdAt: '2026-10-22T10:00:00Z',
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
    hasProcessing: false,
    createdAt: '2026-10-23T10:00:00Z',
    items: [],
    isUrgent: false,
    refundAmount: 0,
  },
]

const ALL_IDS = ROWS.map((r) => r.id)

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

describe('销售订单列表 · 行内操作收敛 + 噪声清理（issue #8011）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.getOrders.mockResolvedValue({ data: { data: { items: ROWS, total: ROWS.length } } })
  })

  // ================= ① 加急列的零噪声 =================

  it('① 全表「不加急」出现次数 = 0（非加急行不渲染任何文字，空单元格）', async () => {
    renderPage()
    await waitForRows()

    // 靶心：改用例前这里是灰字「不加急」× 3 行（noise = 同屏零信息量重复）
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

  // ================= ② 每行 ≤ 2 个可点元素 + 旧形态负控 =================

  it('② 每行操作区可点元素 ≤ 2（1 主行动 + 1 菜单触发器）', async () => {
    renderPage()
    await waitForRows()

    for (const id of ALL_IDS) {
      const buttons = within(actionsCell(id)).getAllByRole('button')
      expect(
        buttons.length,
        `订单 ${id} 的操作区有 ${buttons.length} 个可点元素（>2 ⇐ 又回到了平铺文字链的形态）`,
      ).toBeLessThanOrEqual(2)
    }
    // 页面级同一读数：单屏可点元素不再是 4 × 行数
    const total = ALL_IDS.reduce((n, id) => n + within(actionsCell(id)).getAllByRole('button').length, 0)
    expect(total).toBeLessThanOrEqual(2 * ROWS.length)
  })

  it('② 负控：旧的「查看 / 备注 / 发货 / 处理退款」四文字链同屏形态不再出现', async () => {
    renderPage()
    await waitForRows()

    for (const id of ALL_IDS) {
      const cell = actionsCell(id)
      // 收起态：菜单项**不进 DOM**（折叠不是 CSS 隐藏，§31 P1 的机器读数）
      expect(within(cell).queryByRole('menu')).toBeNull()
      // 旧形态的同级文字链 —— 现在都收进菜单（有待发货行做正控：主行动「发货」仍在）
      expect(cell.textContent).not.toMatch(/查看/)
      expect(cell.textContent).not.toMatch(/备注/)
      expect(cell.textContent).not.toMatch(/处理退款/)
    }
    // 正控（防止上面三条因「整列压根没渲染」而空跑通过）
    expect(actionsCell('ship').textContent).toContain('发货')
  })

  // ================= ③ 主行动按状态派生 =================

  it('③ 待付款行主行动 = 收款；待发货行 = 发货', async () => {
    renderPage()
    await waitForRows()

    expect(within(screen.getByTestId('order-primary-pay')).getByRole('button').textContent).toBe('收款')
    expect(within(screen.getByTestId('order-primary-ship')).getByRole('button').textContent).toBe('发货')
  })

  it('③ 已发货行主行动 = 确认收货；已完成行无主行动（只剩「⋯」菜单）', async () => {
    renderPage()
    await waitForRows()

    expect(within(screen.getByTestId('order-primary-recv')).getByRole('button').textContent).toBe('确认收货')
    // completed 没有派生主行动 ⇒ 主行动位不渲染（不是渲染一个禁用按钮占位）
    expect(screen.queryByTestId('order-primary-done')).toBeNull()
    // 而菜单触发器仍在（每行都能操作，只是没有「主」行动）
    expect(within(actionsCell('done')).getByRole('button', { name: '更多操作' })).toBeInTheDocument()
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

  // ================= 「保持原有行为」= 收敛不改语义 =================

  it('菜单里的动作保持原行为：查看详情跳详情页、备注仍打开备注弹框', async () => {
    renderPage()
    await waitForRows()

    // 待发货行：查看详情 → 详情页（改前是行内文字链，容器变了、回调没变）
    fireEvent.click(within(actionsCell('ship')).getByRole('button', { name: '更多操作' }))
    fireEvent.click(screen.getByRole('menuitem', { name: '查看详情' }))
    expect(routerMock.push).toHaveBeenCalledWith('/orders/ship')
    // 点了就收起（菜单不留在屏上）
    expect(screen.queryByRole('menu')).toBeNull()

    // 备注 → 备注弹框（`RemarkModal` 自带标题「添加备注」，没有 role="dialog"）
    fireEvent.click(within(actionsCell('ship')).getByRole('button', { name: '更多操作' }))
    fireEvent.click(screen.getByRole('menuitem', { name: '备注' }))
    expect(await screen.findByText('添加备注')).toBeInTheDocument()
  })

  it('主行动仍是原行为：待发货行「发货」跳发货页；待付款行「收款」开确认弹框（不直接改状态）', async () => {
    renderPage()
    await waitForRows()

    fireEvent.click(within(screen.getByTestId('order-primary-ship')).getByRole('button'))
    expect(routerMock.push).toHaveBeenCalledWith('/orders/ship/ship')

    // 收款 = 旧「确认付款」的同一个弹框闸门（弹框里点确认才发请求）
    fireEvent.click(within(screen.getByTestId('order-primary-pay')).getByRole('button'))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/已收到客户付款|确认付款/)).toBeInTheDocument()
    expect(api.confirmPayment).not.toHaveBeenCalled()
  })

  it('处理退款仍在菜单里且仍受「可退状态 + 未退过款」约束（权限判断不变）', async () => {
    renderPage()
    await waitForRows()

    // 待付款行不可退 ⇒ 菜单里没有该项（旧实现同样不渲染）
    fireEvent.click(within(actionsCell('pay')).getByRole('button', { name: '更多操作' }))
    expect(screen.queryByRole('menuitem', { name: '处理退款' })).toBeNull()
    expect(screen.getByRole('menuitem', { name: '关闭订单' })).toBeInTheDocument()

    // 已发货行可退 ⇒ 有该项，点击仍弹退款弹框
    fireEvent.click(within(actionsCell('recv')).getByRole('button', { name: '更多操作' }))
    fireEvent.click(screen.getByRole('menuitem', { name: '处理退款' }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })
})

describe('行内菜单的键盘可达性（收敛不得把动作藏成不可达）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.getOrders.mockResolvedValue({ data: { data: { items: ROWS, total: ROWS.length } } })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('Escape 收起菜单；触发器 aria-expanded 随开合变化', async () => {
    renderPage()
    await waitForRows()

    const trigger = within(actionsCell('ship')).getByRole('button', { name: '更多操作' })
    expect(trigger.getAttribute('aria-expanded')).toBe('false')

    fireEvent.click(trigger)
    expect(trigger.getAttribute('aria-expanded')).toBe('true')
    expect(screen.getByRole('menu')).toBeInTheDocument()

    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('menu')).toBeNull())
  })
})
