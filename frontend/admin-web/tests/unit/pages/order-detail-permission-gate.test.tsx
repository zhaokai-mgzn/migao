// case_ids: UI-127
//
// issue #7276（RBAC）：「订单详情」这个权限码**从死码变成真码** —— 页面侧的三条读数。
//
// ## 病（用户 2026-10-18 现场原话）
//
// 「虽然页面上提示我没权限操作，但是我仍然能访问，RBAC权限没控制住？」
// 拆开是两件事：
//   ① `order:detail` 在岗位权限页里**能勾**，却**没有端点、没有页面守卫**在消费它
//      （admin-api 零 `@RequirePermission("order:detail")`、前端零 `has('order:detail')`）
//      ⇒ 取消勾选它，详情页照开、数据照出。
//   ② 详情页**无条件**请求加工单块（端点码 `production:view`）⇒ 客服/销售/财务这类
//      「持 `order:detail`、不持 `production:view`」的岗位一进页就吃一条 403
//      「没有权限执行此操作」，而同一屏的订单数据照常渲染 —— 看起来就是「说没权限却让我看全了」。
//
// ## 判据（三条，缺一即空断言）
//
// ① 无 `order:detail` ⇒ 渲染拒绝态，且**一个读请求都不发**（不是先请求再吃 403）；
// ② 有 `order:detail`、无 `production:view` ⇒ 页正常渲染，但加工单块**不渲染**（= 不发那条请求）；
// ③ 两码都在 ⇒ 加工单块渲染（②的对照组：否则「永远不渲染」也是绿的恒真断言）。
//
// ⚠️ 本文件只裁**前端体验层**；真正的关口是 admin-api 的 `@RequirePermission("order:detail")`
// （Java 侧判据 = `AdminOrderShipmentReadTest`，服务端 403 不可被前端绕过）。
import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'

// 登录态：按用例改写 permissions。必须**按 zustand 选择器**返回 ——
// `usePermission()` 走 `useAuthStore(s => s.user)`，整份 state mock 无视入参会让 `user` 恒 undefined
// ⇒ `has()` 恒 false ⇒ 判据 ③（有码 ⇒ 渲染）恒假、①恒真（同 `list-write-button-permission.test.tsx` 的注释）。
const authMock = vi.hoisted(() => ({
  state: {
    user: {
      id: '1',
      username: 'tester',
      name: '测试账号',
      permissions: ['*'] as string[],
      roles: [] as string[],
    },
  },
}))

vi.mock('@/store/auth', () => ({
  useAuthStore: (selector?: (s: unknown) => unknown) =>
    typeof selector === 'function' ? selector(authMock.state) : authMock.state,
}))

const setPerms = (permissions: string[]) => {
  authMock.state.user = { ...authMock.state.user, permissions, roles: [] }
}

const mockGetOrder = vi.fn()
const mockGetOrderShipments = vi.fn()
const mockGetOrderOperations = vi.fn()

vi.mock('@/lib/api', () => ({
  orderApi: {
    getOrder: (...a: unknown[]) => mockGetOrder(...a),
    getOrderShipments: (...a: unknown[]) => mockGetOrderShipments(...a),
    closeOrder: vi.fn(),
    confirmPayment: vi.fn(),
    updateOrderStatus: vi.fn(),
    updateLogistics: vi.fn(),
    refundOrder: vi.fn(),
  },
  productionApi: {
    getOrderOperations: (...a: unknown[]) => mockGetOrderOperations(...a),
  },
}))

vi.mock('@/lib/use-route-id', () => ({
  useRouteId: () => 'test-order-123',
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// `@/components/orders` 桶 mock：必须覆盖**页面真的 import 了**的那些键
// （缺键 ⇒ 渲染期 `No "<X>" export is defined` 直接崩；守卫 = tests/unit_ci_workflows/test_orders_barrel_mock_guard.py）。
// 这里全部替身成「可观测的壳」——本判据只裁**有没有渲染**，不裁这些块内部行为。
vi.mock('@/components/orders', () => ({
  OrderProgressSteps: () => <div data-testid="progress-steps" />,
  CloseOrderModal: () => null,
  LogisticsForm: () => null,
  RefundOrderModal: () => null,
  // 加工单块（issue #7276 的判据 ②/③ 就钉在它身上）
  ProcessingOrderBlock: () => <div data-testid="processing-block" />,
  ShipmentDoc: () => null,
  QuotationDoc: () => null,
  ProcessingDoc: () => null,
  SalesDoc: () => null,
  OrderUrgencyPanel: () => null,
  EditOrderContentModal: () => null,
  PrintDocPreview: () => null,
  ProcessingQrMissingNotice: () => null,
}))

// 页面用 `DateTimeCell` 渲染时间列；替身掉以免把 dayjs 的 mock 面拖进来（本判据不裁时间格式）。
vi.mock('@/components/common/DateTimeCell', () => ({
  default: ({ value }: { value?: string }) => <span>{value}</span>,
}))

import OrderDetailPage from '@/app/(dashboard)/orders/[id]/OrderDetail'

const mockOrder = {
  id: 'test-order-123',
  orderNo: 'MG202606001',
  status: 'completed',
  customerName: '张三',
  customerPhone: '13800138000',
  customerAddress: '北京市朝阳区xx小区',
  totalAmount: 1999,
  discountAmount: 0,
  actualAmount: 1949,
  refundAmount: 50,
  refundAt: '2026-10-18T07:09:00Z',
  items: [],
  processingItems: [],
}

beforeEach(() => {
  vi.clearAllMocks()
  setPerms(['*'])
  mockGetOrder.mockResolvedValue({ data: { data: mockOrder } })
  mockGetOrderShipments.mockResolvedValue({
    data: { data: { order_id: 'test-order-123', status: 'completed', shipments: [] } },
  })
  mockGetOrderOperations.mockResolvedValue({ data: { data: { positions: [] } } })
})

afterEach(() => {
  cleanup()
})

describe('#7276 订单详情页：页面码 = order:detail（死码转真码）', () => {
  it('判据 ①：无 order:detail ⇒ 渲染拒绝态，且一个读请求都不发', async () => {
    // 有列表码、有加工单码，**唯独**没有订单详情码 —— 正是「只勾订单列表不勾订单详情」的自定义岗位
    setPerms(['dashboard:view', 'order:list', 'production:view'])

    render(<OrderDetailPage />)

    expect(await screen.findByText('无权访问该页面')).toBeInTheDocument()
    expect(mockGetOrder).not.toHaveBeenCalled()
    expect(mockGetOrderShipments).not.toHaveBeenCalled()
    expect(mockGetOrderOperations).not.toHaveBeenCalled()
    expect(screen.queryByTestId('progress-steps')).not.toBeInTheDocument()
  })

  it('判据 ②：有 order:detail、无 production:view（客服/销售/财务形态）⇒ 页面可看，加工单块不渲染', async () => {
    setPerms(['dashboard:view', 'order:list', 'order:detail', 'processing:view'])

    render(<OrderDetailPage />)

    expect(await screen.findByTestId('progress-steps')).toBeInTheDocument()
    expect(screen.queryByText('无权访问该页面')).not.toBeInTheDocument()
    // 端点码 production:view 不在手 ⇒ 整块不渲染（= 不发那条必然 403 的请求）
    expect(screen.queryByTestId('processing-block')).not.toBeInTheDocument()
    expect(mockGetOrder).toHaveBeenCalledTimes(1)
  })

  it('判据 ③（②的对照组）：两码都在 ⇒ 加工单块渲染（否则「永远不渲染」也是绿的）', async () => {
    setPerms(['dashboard:view', 'order:list', 'order:detail', 'production:view'])

    render(<OrderDetailPage />)

    expect(await screen.findByTestId('progress-steps')).toBeInTheDocument()
    expect(screen.getByTestId('processing-block')).toBeInTheDocument()
  })
})
