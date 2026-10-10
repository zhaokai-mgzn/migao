// case_ids: UI-011, UI-078, ST-004, CU-010, PP-010, UI-057
/**
 * 「**读面失败不得与空态同屏**」——**页面实例判据**（issue #6714，与 #6713 同一形态）。
 *
 * ## 病灶（集成侧真机类普查：注入 admin 读接口 500，**每页等 6s** 看持久面）
 *
 * | 页面 | 持久面 | 判定 |
 * |---|---|---|
 * | `/employees` | 「暂无数据」+「共 0 条」 | 失败被画成空态 + 零值断言同屏 |
 * | `/notifications` | 「暂无通知」 | 失败被画成空态 |
 * | `/products` | 「暂无数据」 | 失败被画成空态（源码里是「Error handled by API layer」的空 catch） |
 * | `/shipments` | 表头在、零行、无失败面 | 与「没有发货单」不可区分 |
 * | `/production/remnants` | 失败横幅在，底下**仍印**「还没有余料记录」 | 两种语义同屏 |
 *
 * ## 每页钉住的三件事（各自红在**自己那条断言**上）
 *
 *   ① 注入该页读面失败 ⇒ 屏上**不得**只剩空态断言（「暂无…」/「还没有余料记录」）；
 *   ② ⇒ 必须出现**常驻**失败面（`data-testid` + `role="alert"`）+ 重试出口；
 *   ③ 点重试 ⇒ **真重发**（调用次数 +1）且恢复真实数据；
 *   ④ **反向对照**：读成功且**真为空** ⇒ 空态照旧（不得把空态也判红）。
 *
 * ## 反假绿约束（`migao-acceptance`）
 *
 * - 失败一律来自 **mock 接口 reject**（不依赖真实服务不可达）；
 * - 断言的是**常驻面**（DOM），**不看** toast 的 4s 存活窗口；
 * - ③ 钉住**调用次数**与**恢复后的真值**（不是「锚点消失了」这类改前改后都绿的断言）；
 * - 与 #6713 的 chat 面**共用一把尺子**：类级元守卫 =
 *   `frontend/admin-web/tests/unit/read-failure-empty-state-guard.test.ts`。
 *
 * ## 边界（照实登记）
 *
 * - 只覆盖票据点名的这 5 页（chat 面在 `tests/unit/components/chat-session-read-failure.test.tsx`）；
 * - **不测真机**：屏上「失败面够不够显眼」是 §15.7 真机读图的面，见 PR 报告；
 * - `/stock-ledger`（#6707）与 `/dashboard`（#6715）**不在本文件射程**。
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

// ── 读接口 mock（一页一个）─────────────────────────────────────────────────
const mockGetEmployees = vi.fn()
const mockLoadPositions = vi.fn()
const mockGetNotifications = vi.fn()
const mockGetProducts = vi.fn()
const mockGetCategories = vi.fn()
const mockShipmentList = vi.fn()
const mockLedger = vi.fn()

vi.mock('@/lib/api', () => ({
  employeeApi: {
    getEmployees: (...a: unknown[]) => mockGetEmployees(...a),
    loadPositions: (...a: unknown[]) => mockLoadPositions(...a),
  },
  notificationApi: { getNotifications: (...a: unknown[]) => mockGetNotifications(...a) },
  productApi: { getProducts: (...a: unknown[]) => mockGetProducts(...a) },
  categoryApi: { getCategories: (...a: unknown[]) => mockGetCategories(...a) },
  shipmentApi: { list: (...a: unknown[]) => mockShipmentList(...a) },
  remnantApi: { ledger: (...a: unknown[]) => mockLedger(...a) },
}))

// 登录态：`/products` 的「新增商品」按 `product:create` 显隐（与既有测试同口径）
vi.mock('@/store/auth', () => {
  const state = { user: { id: '1', username: 'admin', name: '管理员', permissions: ['*'], roles: [] } }
  return {
    useAuthStore: Object.assign(
      (selector?: (s: unknown) => unknown) => (typeof selector === 'function' ? selector(state) : state),
      { getState: () => state },
    ),
  }
})

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), forward: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => '/',
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
  redirect: vi.fn(),
  notFound: vi.fn(),
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn(), loading: vi.fn(), dismiss: vi.fn() },
}))

import EmployeesPage from '@/app/(dashboard)/employees/page'
import NotificationsPage from '@/app/(dashboard)/notifications/page'
import ProductsPage from '@/app/(dashboard)/products/page'
import ShipmentsPage from '@/app/(dashboard)/shipments/page'
import RemnantsPage from '@/app/(dashboard)/production/remnants/page'

const TEST_TIMEOUT = 20_000

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  // 与页面接线一致的「配角」读数（不是本文件断言对象）
  mockLoadPositions.mockResolvedValue({ data: { data: [] } })
  mockGetCategories.mockResolvedValue({ data: { data: [] } })
})

describe('读面失败不得与空态同屏（issue #6714）', () => {
  it(
    '① /employees：读失败 ⇒ 常驻失败面 + 真重发；「共 0 条」不得作为持久面',
    async () => {
      mockGetEmployees.mockRejectedValueOnce(new Error('500'))
      render(<EmployeesPage />)
      await waitFor(() => expect(mockGetEmployees).toHaveBeenCalledTimes(1))

      const surface = await screen.findByTestId('employees-load-failed')
      expect(surface).toHaveAttribute('role', 'alert')
      // 🔴 改前：失败只 toast，屏上留着表格的「暂无数据」+ Pagination 的「共 0 条」
      expect(screen.queryByText(/共\s*0\s*条/)).not.toBeInTheDocument()

      mockGetEmployees.mockResolvedValueOnce({ data: { data: { items: [], total: 0 } } })
      fireEvent.click(screen.getByTestId('employees-load-failed-retry'))
      await waitFor(() => expect(mockGetEmployees).toHaveBeenCalledTimes(2))
      // 重试成功 ⇒ 失败面收起（挂载期的一次拉取 + 重试 = 2 次，钉住「真重发」）
      await waitFor(() => expect(screen.queryByTestId('employees-load-failed')).not.toBeInTheDocument())
    },
    TEST_TIMEOUT,
  )

  it(
    '② /notifications：读失败 ⇒ 「暂无通知」不得出现；失败面 + 真重发',
    async () => {
      mockGetNotifications.mockRejectedValueOnce(new Error('500'))
      render(<NotificationsPage />)
      await waitFor(() => expect(mockGetNotifications).toHaveBeenCalledTimes(1))

      const surface = await screen.findByTestId('notifications-load-failed')
      expect(surface).toHaveAttribute('role', 'alert')
      // 🔴 改前：屏上就是「暂无通知」
      expect(screen.queryByText('暂无通知')).not.toBeInTheDocument()

      mockGetNotifications.mockResolvedValueOnce({ data: { data: { items: [], total: 0 } } })
      fireEvent.click(screen.getByTestId('notifications-load-failed-retry'))
      await waitFor(() => expect(mockGetNotifications).toHaveBeenCalledTimes(2))
      // 反向对照：重试成功且**真为空** ⇒ 「暂无通知」照旧（空态没有被判红）
      expect(await screen.findByTestId('notifications-empty')).toBeInTheDocument()
      expect(screen.getByText('暂无通知')).toBeInTheDocument()
    },
    TEST_TIMEOUT,
  )

  it(
    '③ /products：读失败 ⇒ 失败面 + 真重发（修前是「Error handled by API layer」的空 catch）',
    async () => {
      mockGetProducts.mockRejectedValueOnce(new Error('500'))
      render(<ProductsPage />)
      await waitFor(() => expect(mockGetProducts).toHaveBeenCalledTimes(1))

      const surface = await screen.findByTestId('products-load-failed')
      expect(surface).toHaveAttribute('role', 'alert')

      // ⚠️ 本页的 `loadProducts` 依赖 `searchParams`（`syncUrl` 会换引用）⇒ 挂载期可能多跑几次，
      // 「调用次数 == 2」是**别的页**的口径；这里钉「重试**真的又发了一次**」：
      // 先把重试前的次数固定下来（此时必 ≥1 且已停在失败态），再断言 +1。
      await waitFor(() => expect(screen.getByTestId('products-load-failed')).toBeInTheDocument())
      const before = mockGetProducts.mock.calls.length
      mockGetProducts.mockResolvedValue({ data: { data: { items: [], total: 0 } } })
      fireEvent.click(screen.getByTestId('products-load-failed-retry'))
      await waitFor(() => expect(mockGetProducts.mock.calls.length).toBeGreaterThan(before))
      await waitFor(() => expect(screen.queryByTestId('products-load-failed')).not.toBeInTheDocument())
    },
    TEST_TIMEOUT,
  )

  it(
    '④ /shipments：读失败 ⇒ 零行那一格必须是失败面（不是「暂无发货单」）；失败面 + 真重发',
    async () => {
      mockShipmentList.mockRejectedValueOnce(new Error('500'))
      render(<ShipmentsPage />)
      await waitFor(() => expect(mockShipmentList).toHaveBeenCalledTimes(1))

      const surface = await screen.findByTestId('shipments-load-failed')
      expect(surface).toHaveAttribute('role', 'alert')
      // 🔴 改前：这一格印的是「暂无发货单」（与「没有发货单」不可区分）
      expect(screen.queryByTestId('shipments-empty')).not.toBeInTheDocument()

      mockShipmentList.mockResolvedValueOnce({ data: { data: [] } })
      fireEvent.click(screen.getByTestId('shipments-load-failed-retry'))
      await waitFor(() => expect(mockShipmentList).toHaveBeenCalledTimes(2))
      // 反向对照：重试成功且**真为空** ⇒ 「暂无发货单」照旧
      expect(await screen.findByTestId('shipments-empty')).toBeInTheDocument()
    },
    TEST_TIMEOUT,
  )

  it(
    '⑤ /production/remnants：失败横幅已在，但**底下不得**再印「还没有余料记录」（同屏两种语义）',
    async () => {
      mockLedger.mockRejectedValueOnce(new Error('500'))
      render(<RemnantsPage />)
      await waitFor(() => expect(mockLedger).toHaveBeenCalledTimes(1))

      // 失败横幅（#6702 已立）仍在
      expect(await screen.findByTestId('remnant-ledger-load-failed')).toBeInTheDocument()
      // 🔴 改前：横幅下面同一屏还印着「还没有余料记录（派工生成排料结果时会自动产生）」
      expect(screen.queryByTestId('remnant-empty')).not.toBeInTheDocument()

      // 反向对照：读成功且**真为空** ⇒ 空态照旧
      mockLedger.mockResolvedValueOnce({
        data: {
          data: {
            items: [],
            total: 0,
            page: 1,
            size: 20,
            availableCount: 0,
            availableMeters: 0,
            usedCount: 0,
            recoveredMetersTotal: 0,
          },
        },
      })
      fireEvent.click(screen.getByTestId('remnant-ledger-retry'))
      await waitFor(() => expect(mockLedger).toHaveBeenCalledTimes(2))
      expect(await screen.findByTestId('remnant-empty')).toBeInTheDocument()
    },
    TEST_TIMEOUT,
  )

  it(
    '⑥ 反向对照（独立成条）：读成功且**真为空** ⇒ 各页空态照旧渲染、失败面不出现',
    async () => {
      mockGetNotifications.mockResolvedValue({ data: { data: { items: [], total: 0 } } })
      const n = render(<NotificationsPage />)
      expect(await screen.findByTestId('notifications-empty')).toBeInTheDocument()
      expect(screen.queryByTestId('notifications-load-failed')).not.toBeInTheDocument()
      n.unmount()

      mockShipmentList.mockResolvedValue({ data: { data: [] } })
      render(<ShipmentsPage />)
      expect(await screen.findByTestId('shipments-empty')).toBeInTheDocument()
      expect(screen.queryByTestId('shipments-load-failed')).not.toBeInTheDocument()
    },
    TEST_TIMEOUT,
  )
})
