// case_ids: OR-001, OR-002, OR-003, OR-004, OR-005, OR-058, UI-057, UI-058, UI-130
/**
 * 销售订单列表 · **行内快捷发货**（issue #8013，B 端体验打磨 P1：列表即队列）。
 *
 * ## 改前（真机读数）
 *
 * 看板「待发货 49 单」，而每单发货都要「点行内『发货』→ 跳到 `/orders/{id}/ship` 整页 → 填表 →
 * 提交 → 回列表」= **49 次页面往返**，每次都要重新定位上一单在哪。商家实际是「连着录运单号」，
 * 不是「一单一趟出远门」。
 *
 * ## 本文件的判据（会红，不是"看起来像"）
 *
 * ① 点「发货」**不发生路由跳转**（`router.push` 调用 0 次），在该行下方展开录入区
 *    （`data-testid="ship-inline-form"`，且它所在的 `<tr>` 就是这一行自己的展开行）；再次点击
 *    或 `Escape` 收起（收起态**不进 DOM**，不是 CSS 隐藏）；
 * ② 提交 ⇒ **只调用一次**发货写面，请求体含 `logisticsCompany` / `trackingNo` / `shippingMethod`，
 *    幂等键 `X-Client-Request-Id` 随请求带上；成功后录入区收起、列表刷新一次、**不跳页**，
 *    行状态随服务端刷新结果从「发货」变成「确认收货」；
 * ③ 前端预校验与**服务端同口径**：仅当**显式** `shippingMethod=logistics` 且运单号为空时拦
 *    （不提交 + 行内报错）；`shippingMethod=none`（无需物流）**空运单号也直接提交**；
 * ④ 失败（4xx）⇒ 录入区保留、输入**原样保留**、行内错误文案可见（服务端原文优先），
 *    行不消失、**不弹 toast 独占**、不跳页；
 * ⑤ 兜底路径仍在：⋯ 菜单里的「去发货页」跳既有 `/orders/{id}/ship`。
 *
 * **注入式红证**（复核用，非本文件运行时执行）：
 * - 把 `handleShip` 改回 `router.push(...)` ⇒ ① 的 `push` 0 次与 ② 的「不跳页」当场红；
 * - 提交改走「PUT /logistics」或两步老路（先 updateLogistics 再 updateStatus）⇒ ② 的「只调用一次
 *   原子发货端点」与「行变已发货」当场红（后者在 #6983 已实证：老路不建发货单、不确定状态）；
 * - 去掉前端空单号预校验 ⇒ ③ 红；把 `none` 也拦下 ⇒ ③ 的负控（无需物流直接提交）红；
 * - 把失败分支改成 `toast.error` + 清空输入 ⇒ ④ 的红；
 * - 把「去发货页」从菜单里删掉 ⇒ ⑤ 红。
 *
 * ## 与相邻判据的分工（不重复）
 *
 * - 行内操作收敛（1 主行动 + ⋯ 菜单）⇒ `tests/unit/pages/orders-list-row-actions.test.tsx`；
 * - 组件级渲染（表头 / 明细列 / 空态）⇒ `tests/unit/components/OrderTable.test.tsx`；
 * - 发货页整页表单（含原子端点 / 幂等键 / 加工单守卫）⇒ `tests/unit/pages/ship-order.test.tsx`。
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'

// 页面按 `order:create` 显隐「新增订单」（issue #5983）⇒ 渲染必须带登录态（与 orders.test.tsx 同口径）
const authMock = vi.hoisted(() => ({
  state: {
    // 发货人默认值 = 当前登录人（不是「管理员」这种角色名，也不是空）
    user: { id: '1', username: 'admin', name: '王师傅', permissions: ['*'], roles: [] },
  },
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
  default: ({ children, href, ...props }: any) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))

const api = vi.hoisted(() => ({
  getOrders: vi.fn(),
  confirmPayment: vi.fn(),
  updateOrderStatus: vi.fn(),
  deleteOrder: vi.fn(),
  refundOrder: vi.fn(),
  addRemark: vi.fn(),
  closeOrder: vi.fn(),
  updateLogistics: vi.fn(),
}))
/** 发货写面（既有原子端点 `POST /api/admin/production/orders/{id}/ship`，issue #6983） */
const shipApi = vi.hoisted(() => ({ shipOrder: vi.fn() }))
vi.mock('@/lib/api', () => ({ orderApi: api, productionApi: shipApi }))

// 惰性代理 mock：不逐个列图标名（闭集 mock 会在任一新图标 import 时假红）
vi.mock('lucide-react', async (importOriginal) =>
  (await import('../helpers/lucide-mock')).lucideMock((await importOriginal()) as Record<string, unknown>))

// ④ 的负控要断言「失败不弹 toast 独占」⇒ 用本文件的桩（setup.ts 的全局 mock 没有可断言的实现）
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
// 🔴 真实的生产映射（不替身）：`productionApi.shipOrder` 只经它把表单数据拼成 HTTP body ——
// 断言「body 含 logisticsCompany / trackingNo / shippingMethod」必须落在**真值**上，不是我自己写的期望。
import { buildLogisticsPayload } from '@/lib/data-adapter'

/** 两行待发货（可逐单证伪「展开的是我点的那一行」）+ 一行已发货（对照） */
const ROWS = [
  {
    id: 'ship1',
    orderNo: 'MG-SHIP-0001',
    status: 'pending_shipment',
    totalAmount: 2000,
    actualAmount: 2000,
    customerName: '李女士',
    hasProcessing: false,
    createdAt: '2026-10-21T10:00:00Z',
    items: [],
    isUrgent: false,
    refundAmount: 0,
  },
  {
    id: 'ship2',
    orderNo: 'MG-SHIP-0002',
    status: 'pending_shipment',
    totalAmount: 2600,
    actualAmount: 2600,
    customerName: '赵先生',
    hasProcessing: false,
    createdAt: '2026-10-22T10:00:00Z',
    items: [],
    isUrgent: false,
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
    createdAt: '2026-10-20T10:00:00Z',
    items: [],
    isUrgent: false,
    refundAmount: 0,
  },
]

function pageOf(rows: unknown[]) {
  return { data: { data: { items: rows, total: rows.length } } }
}

const actionsCell = (id: string) => screen.getByTestId(`order-actions-${id}`)
const primaryButton = (id: string) => within(screen.getByTestId(`order-primary-${id}`)).getByRole('button')

/** 等首屏列表落地（否则后面量的都是「空表」） */
async function waitForRows() {
  await waitFor(() => expect(api.getOrders).toHaveBeenCalled())
  await waitFor(() => expect(screen.getByTestId('order-actions-ship1')).toBeInTheDocument())
}

/** 点某行的主行动「发货」展开录入区 */
async function expandShip(id: string) {
  fireEvent.click(primaryButton(id))
  return screen.findByTestId('ship-inline-form')
}

/** 填运单号（单号输入框按标签定位 —— 与商家看到的是同一个字段） */
function typeTracking(no: string) {
  fireEvent.change(screen.getByLabelText('运单号'), { target: { value: no } })
}

function selectCompany(company: string) {
  fireEvent.change(screen.getByLabelText('物流公司'), { target: { value: company } })
}

function selectMethod(method: 'logistics' | 'none') {
  fireEvent.change(screen.getByLabelText('物流方式'), { target: { value: method } })
}

describe('销售订单列表 · 行内快捷发货（issue #8013）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.getOrders.mockResolvedValue(pageOf(ROWS))
    shipApi.shipOrder.mockResolvedValue({ data: { data: { order_id: 'ship1', status: 'shipped' } } })
  })

  // ================= ① 不跳页 + 行内展开 =================

  it('① 点「发货」**不跳页**，在该行下方展开录入区（四个字段 + 发货人默认当前登录人）', async () => {
    render(<OrdersPage />)
    await waitForRows()

    const form = await expandShip('ship1')
    // 靶心：改前这一下是 `router.push('/orders/ship1/ship')`（整页往返）
    expect(routerMock.push).not.toHaveBeenCalled()

    // 「在该行下方」= 录入区住在本行自己的展开 `<tr>` 里（不是整页顶部、也不是遮罩模态）
    const row = form.closest('tr')
    expect(row).not.toBeNull()
    expect(row!.getAttribute('data-testid')).toBe('ship-inline-row-ship1')
    expect(screen.queryByRole('dialog')).toBeNull()

    // 四个字段齐 + 发货人默认当前登录人（不是空、也不是「管理员」这类角色名）
    expect(screen.getByLabelText('物流方式')).toBeInTheDocument()
    expect(screen.getByLabelText('物流公司')).toBeInTheDocument()
    expect(screen.getByLabelText('运单号')).toBeInTheDocument()
    expect((screen.getByTestId('ship-inline-shipper') as HTMLInputElement).value).toBe('王师傅')

    // 只展开被点的那一行（逐单可证伪：另一行没有录入区）
    expect(screen.queryByTestId('ship-inline-row-ship2')).toBeNull()
  })

  it('① 再次点击「发货」收起；`Escape` 也收起（收起态**不进 DOM**）', async () => {
    render(<OrdersPage />)
    await waitForRows()

    await expandShip('ship1')
    fireEvent.click(primaryButton('ship1'))
    await waitFor(() => expect(screen.queryByTestId('ship-inline-form')).toBeNull())

    // Escape 收起：录入区不是「只能靠再点一次才能关」的陷阱
    await expandShip('ship1')
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByTestId('ship-inline-form')).toBeNull())
    expect(routerMock.push).not.toHaveBeenCalled()

    // 切换行：点另一行的「发货」⇒ 只保留那一行（不是两行同时展开）
    await expandShip('ship1')
    await expandShip('ship2')
    expect(screen.queryByTestId('ship-inline-row-ship1')).toBeNull()
    expect(screen.getByTestId('ship-inline-row-ship2')).toBeInTheDocument()
  })

  // ================= ② 提交：只写一次、不跳页、刷新列表、行状态更新 =================

  it('② 提交 ⇒ 只调用一次发货写面（body 含三键 + 幂等键），成功后收起、刷新、不跳页', async () => {
    render(<OrdersPage />)
    await waitForRows()

    const form = await expandShip('ship1')
    typeTracking('SF1234567890')
    selectCompany('顺丰速运')
    fireEvent.click(within(form).getByRole('button', { name: '确认发货' }))

    await waitFor(() => expect(shipApi.shipOrder).toHaveBeenCalledTimes(1))
    const [orderId, payload, clientRequestId] = shipApi.shipOrder.mock.calls[0]
    expect(orderId).toBe('ship1')
    // 页面交给共享 API 的**表单数据**（唯一键名映射在 `buildLogisticsPayload`）
    expect(payload).toEqual(
      expect.objectContaining({
        company: '顺丰速运',
        trackingNo: 'SF1234567890',
        shippingMethod: 'logistics',
        shipperName: '王师傅',
      }),
    )
    // 真正发出去的 **HTTP body**（`productionApi.shipOrder` 内部只经 `buildLogisticsPayload`）
    expect(buildLogisticsPayload(payload)).toEqual(
      expect.objectContaining({
        logisticsCompany: '顺丰速运',
        trackingNo: 'SF1234567890',
        shippingMethod: 'logistics',
      }),
    )
    // 幂等键随请求带上（同键重试由服务端回放，不会把运单号覆盖成第二次的值）
    expect(typeof clientRequestId).toBe('string')
    expect((clientRequestId as string).length).toBeGreaterThan(0)

    // 录入区收起 + 列表按既有方式刷新（getOrders 第 2 次）+ 不跳页
    await waitFor(() => expect(screen.queryByTestId('ship-inline-form')).toBeNull())
    await waitFor(() => expect(api.getOrders).toHaveBeenCalledTimes(2))
    expect(routerMock.push).not.toHaveBeenCalled()
  })

  it('② 行状态即时更新：服务端刷新后该行不再是「发货」，而是「确认收货」', async () => {
    render(<OrdersPage />)
    await waitForRows()

    // 提交成功后服务端返回的那一单已是 shipped（真值来自服务端，不是前端乐观改写）
    api.getOrders.mockResolvedValueOnce(
      pageOf(ROWS.map((r) => (r.id === 'ship1' ? { ...r, status: 'shipped' } : r))),
    )

    const form = await expandShip('ship1')
    typeTracking('SF1234567890')
    fireEvent.click(within(form).getByRole('button', { name: '确认发货' }))

    await waitFor(() => expect(api.getOrders).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(primaryButton('ship1').textContent).toBe('确认收货'))
    // 对照行仍是待发货（没有整表被改写的副作用）
    expect(primaryButton('ship2').textContent).toBe('发货')
  })

  // ================= ③ 预校验与服务端同口径 =================

  it('③ 显式 logistics + 空运单号 ⇒ 行内拦下（不提交），错误文案可见', async () => {
    render(<OrdersPage />)
    await waitForRows()

    const form = await expandShip('ship1')
    // 默认就是「物流发货」，运单号为空 ⇒ 与服务端 422 同口径，前端先拦一次
    fireEvent.click(within(form).getByRole('button', { name: '确认发货' }))

    await waitFor(() => expect(within(form).getByTestId('ship-inline-error')).toBeInTheDocument())
    expect(within(form).getByTestId('ship-inline-error').textContent).toContain('快递单号')
    expect(shipApi.shipOrder).not.toHaveBeenCalled()
    // 拦下 ≠ 收起：录入区还在，商家接着填
    expect(screen.getByTestId('ship-inline-form')).toBeInTheDocument()
  })

  it('③ 负控：`shippingMethod=none`（无需物流）⇒ 空运单号**直接提交**，不被错拦', async () => {
    render(<OrdersPage />)
    await waitForRows()

    const form = await expandShip('ship1')
    selectMethod('none')
    fireEvent.click(within(form).getByRole('button', { name: '确认发货' }))

    await waitFor(() => expect(shipApi.shipOrder).toHaveBeenCalledTimes(1))
    const [, payload] = shipApi.shipOrder.mock.calls[0]
    expect(payload).toEqual(
      expect.objectContaining({ shippingMethod: 'none', trackingNo: '', company: '' }),
    )
    // 「无需物流」的空单号是**合法**形态：HTTP body 里运单号/承运商都是空串，且 shippingMethod=none
    expect(buildLogisticsPayload(payload)).toEqual(
      expect.objectContaining({ shippingMethod: 'none', trackingNo: '', logisticsCompany: '' }),
    )
  })

  // ================= ④ 失败态：保留输入 + 行内错误 =================

  it('④ 接口 4xx ⇒ 录入区保留、输入原样在、服务端原文可见、行不消失、不弹 toast、不跳页', async () => {
    shipApi.shipOrder.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        status: 422,
        data: { success: false, error: { code: 'BUSINESS_ERROR', message: '作业单未完成，不能发货' } },
      },
    })
    render(<OrdersPage />)
    await waitForRows()

    const form = await expandShip('ship1')
    typeTracking('SF-REJECT-001')
    fireEvent.click(within(form).getByRole('button', { name: '确认发货' }))

    await waitFor(() =>
      expect(within(screen.getByTestId('ship-inline-form')).getByTestId('ship-inline-error').textContent).toBe(
        '作业单未完成，不能发货',
      ),
    )
    // 输入原样保留（不整区重置，否则商家要重打一遍 17 位单号）
    expect((screen.getByLabelText('运单号') as HTMLInputElement).value).toBe('SF-REJECT-001')
    // 行不消失、录入区还开着
    expect(actionsCell('ship1')).toBeInTheDocument()
    expect(screen.getByTestId('ship-inline-form')).toBeInTheDocument()
    // 「不整页 toast 独占」：错误就在行内，不再叠一个全局 toast
    expect(toastMock.error).not.toHaveBeenCalled()
    expect(routerMock.push).not.toHaveBeenCalled()
    // 失败后没有刷新列表（写了 0 行，别假装成功）
    expect(api.getOrders).toHaveBeenCalledTimes(1)
  })

  // ================= ⑤ 兜底：既有发货页仍在 =================

  it('⑤ ⋯ 菜单保留「去发货页」入口，点击跳既有 /orders/{id}/ship', async () => {
    render(<OrdersPage />)
    await waitForRows()

    fireEvent.click(within(actionsCell('ship1')).getByRole('button', { name: '更多操作' }))
    fireEvent.click(screen.getByRole('menuitem', { name: '去发货页' }))

    expect(routerMock.push).toHaveBeenCalledWith('/orders/ship1/ship')
  })
})
