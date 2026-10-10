// case_ids: UI-011, UI-078, PR-010
/**
 * 「**读失败时共享表格不得印「暂无数据」**」——**页面实例判据**（issue #6728）。
 *
 * ## 病灶（修复后的真机重放抓出来的剩项）
 *
 * 修完 #6713/#6714（PR #6718）后按 §15.7 复放：注入 admin 读接口 500、每页等 6s，
 * `/employees` 与 `/products` 的同屏事实是 **失败面在 + 「暂无数据」也在** ——
 * 同一屏既说「读不到」又说「没有数据」。前一批判它 `OUT_OF_SCOPE` 的理由
 * （改共享默认值波及全站）对**默认值**成立，但**页面级覆盖**不需要动默认值。
 *
 * 根因（`git show origin/main:<path>` 核过）：两页都渲染共享
 * `frontend/admin-web/src/components/ui/Table.tsx` 而**没有传 `emptyText`** ⇒
 * 继承默认值 `'暂无数据'`（该默认值**不动** —— 全站几十张表都用它）。
 *
 * ## 每页钉住的三件事（各自红在**自己那条断言**上）
 *
 *   ① 读失败 ⇒ 屏上**不得**出现「暂无数据」（改前：**就是它红**）；
 *   ② 读失败 ⇒ 常驻失败面 + 重试出口仍在（#6714 的成果，不得为了 ① 把它删掉）；
 *   ③ **反向对照**：读**成功且真为空** ⇒ 「暂无数据」照旧显示
 *      （不许把真实空态判红 —— 那是把判据用成「删功能」）。
 *
 * ## 反假绿约束（`migao-acceptance`）
 *
 * - 失败一律来自 **mock 接口 reject**（不依赖真实服务不可达）；
 * - 断言对象是**常驻面**（DOM），不看 toast 的 4s 存活窗口；
 * - 「暂无数据」按**逐字文本**取（`queryByText('暂无数据')`），不用宽正则 ——
 *   失败面自己的文案里有「不是没有员工，是没读到」，宽正则会把**正确的**失败面也判红；
 * - 与 `/notifications`（`emptyText` 由 tab 派生）不同，本单**不动**它（它改前就已经显式传参）。
 *
 * ## 边界（照实登记，§19.1）
 *
 * - 只覆盖票据点名的这两页；`/notifications` `/shipments` `/chat` 在
 *   `tests/unit/pages/read-failure-empty-state-copy-instances.test.tsx` 与
 *   `tests/unit/components/chat-session-read-failure.test.tsx` 里；
 * - **不测真机**：屏上「失败面够不够显眼」是 §15.7 真机读图的面（本单环境纪律不允许占用 3001，
 *   真机读数交集成侧复跑）；
 * - 类级固化（「凡渲染共享 `ui/Table` 且带读失败面的页面必须显式传 `emptyText`」）在
 *   `frontend/admin-web/scripts/read-failure-empty-state-scan.mjs` +
 *   `tests/unit/read-failure-empty-state-guard.test.ts`，**不在本文件**。
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

// ── 读接口 mock（一页一个）─────────────────────────────────────────────────
const mockGetEmployees = vi.fn()
const mockLoadPositions = vi.fn()
const mockGetProducts = vi.fn()
const mockGetCategories = vi.fn()
// #6728 的同类第三例（由判据 ④ 的调用图普查发现）：`/customers` 早已有失败面（#6703），
// 唯独共享表继承默认「暂无数据」⇒ 本单一并收口
const mockGetCustomers = vi.fn()
const mockGetCustomerTags = vi.fn()

vi.mock('@/lib/api', () => ({
  employeeApi: {
    getEmployees: (...a: unknown[]) => mockGetEmployees(...a),
    loadPositions: (...a: unknown[]) => mockLoadPositions(...a),
  },
  productApi: { getProducts: (...a: unknown[]) => mockGetProducts(...a) },
  categoryApi: { getCategories: (...a: unknown[]) => mockGetCategories(...a) },
  customerApi: {
    getCustomers: (...a: unknown[]) => mockGetCustomers(...a),
    getCustomerTags: (...a: unknown[]) => mockGetCustomerTags(...a),
  },
}))

// 登录态：两页都按权限码决定写入口是否渲染（与既有测试同口径）
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
import ProductsPage from '@/app/(dashboard)/products/page'
import CustomersPage from '@/app/(dashboard)/customers/page'

const TEST_TIMEOUT = 20_000

/** 表的**默认**空态文案（`ui/Table` 的默认值 —— 本判据断言它在失败态下**不出现**） */
const DEFAULT_EMPTY = '暂无数据'

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  // 与页面接线一致的「配角」读数（不是本文件断言对象）
  mockLoadPositions.mockResolvedValue({ data: { data: [] } })
  mockGetCategories.mockResolvedValue({ data: { data: [] } })
  mockGetCustomerTags.mockResolvedValue({ data: { data: [] } })
})

describe('读失败时共享表格不得印「暂无数据」（issue #6728）', () => {
  it(
    '① /employees：读失败 ⇒ 屏上无「暂无数据」，失败面 + 重试仍在',
    async () => {
      mockGetEmployees.mockRejectedValueOnce(new Error('500'))
      render(<EmployeesPage />)
      await waitFor(() => expect(mockGetEmployees).toHaveBeenCalledTimes(1))

      // ② 常驻失败面（#6714 的成果）必须先立住，否则下面那条可能是「整页没渲染」造成的假绿
      const surface = await screen.findByTestId('employees-load-failed')
      expect(surface).toHaveAttribute('role', 'alert')
      expect(screen.getByTestId('employees-load-failed-retry')).toBeInTheDocument()

      // 🔴 ① 改前**就是这条红**：表格继承共享默认值 ⇒ 屏上印「暂无数据」
      expect(screen.queryByText(DEFAULT_EMPTY)).not.toBeInTheDocument()
    },
    TEST_TIMEOUT,
  )

  it(
    '② /products：读失败 ⇒ 屏上无「暂无数据」，失败面 + 重试仍在',
    async () => {
      mockGetProducts.mockRejectedValueOnce(new Error('500'))
      render(<ProductsPage />)
      await waitFor(() => expect(mockGetProducts).toHaveBeenCalled())

      const surface = await screen.findByTestId('products-load-failed')
      expect(surface).toHaveAttribute('role', 'alert')
      expect(screen.getByTestId('products-load-failed-retry')).toBeInTheDocument()

      // 🔴 ① 改前**就是这条红**：`ProductTable` 没传 `emptyText` ⇒ 共享默认值上屏
      expect(screen.queryByText(DEFAULT_EMPTY)).not.toBeInTheDocument()
    },
    TEST_TIMEOUT,
  )

  it(
    '③ 反向对照：读**成功且真为空** ⇒ 「暂无数据」照旧显示（空态不许被判红）',
    async () => {
      mockGetEmployees.mockResolvedValueOnce({ data: { data: { items: [], total: 0 } } })
      const e = render(<EmployeesPage />)
      // 读成功且零条 ⇒ 空态文案照旧（这是**真**「没有员工」）
      expect(await screen.findByText(DEFAULT_EMPTY)).toBeInTheDocument()
      expect(screen.queryByTestId('employees-load-failed')).not.toBeInTheDocument()
      e.unmount()

      mockGetProducts.mockResolvedValue({ data: { data: { items: [], total: 0 } } })
      render(<ProductsPage />)
      expect(await screen.findByText(DEFAULT_EMPTY)).toBeInTheDocument()
      expect(screen.queryByTestId('products-load-failed')).not.toBeInTheDocument()
    },
    TEST_TIMEOUT,
  )

  it(
    '④ 对照读数：读成功且**非空** ⇒ 行渲染、也没有「暂无数据」',
    async () => {
      mockGetEmployees.mockResolvedValueOnce({
        data: {
          data: {
            items: [{ id: 7, name: '张三', phone: '13800000000', role: 'staff', status: 'active', permissions: [] }],
            total: 1,
          },
        },
      })
      render(<EmployeesPage />)
      expect(await screen.findByText('张三')).toBeInTheDocument()
      expect(screen.queryByText(DEFAULT_EMPTY)).not.toBeInTheDocument()
    },
    TEST_TIMEOUT,
  )

  it(
    '⑤ /customers（#6728 用调用图普查发现的同类第三例）：读失败无「暂无数据」，真为空照旧印',
    async () => {
      mockGetCustomers.mockRejectedValueOnce(new Error('500'))
      const c = render(<CustomersPage />)
      await waitFor(() => expect(mockGetCustomers).toHaveBeenCalled())

      const surface = await screen.findByTestId('customers-load-error')
      expect(surface).toHaveAttribute('role', 'alert')
      expect(screen.getByTestId('customers-load-error-retry')).toBeInTheDocument()
      // 🔴 改前：失败面在、共享表仍继承默认「暂无数据」⇒ 同屏「没读到」+「没有客户」
      expect(screen.queryByText(DEFAULT_EMPTY)).not.toBeInTheDocument()
      c.unmount()

      // 反向对照：读成功且真为空 ⇒ 「暂无数据」照旧
      mockGetCustomers.mockResolvedValue({ data: { data: { items: [], total: 0 } } })
      render(<CustomersPage />)
      expect(await screen.findByText(DEFAULT_EMPTY)).toBeInTheDocument()
      expect(screen.queryByTestId('customers-load-error')).not.toBeInTheDocument()
    },
    TEST_TIMEOUT,
  )
})
