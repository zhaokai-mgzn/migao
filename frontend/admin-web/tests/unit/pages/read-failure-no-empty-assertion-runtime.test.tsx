// case_ids: UI-057, UI-058, OR-001, OR-046, UI-087
/**
 * 「**读失败后屏上不得出现任何『没有数据』断言**」——**运行期判据**（issue #6733）。
 *
 * ## 为什么必须有一条**运行期**判据（这是本单最值得固化的点）
 *
 * #6728 的类普查是**调用图**普查（沿本地组件闭包找「渲染共享 `ui/Table`」的调用点）⇒ 它只覆盖
 * **用共享表**的页面。而 `/orders` 用的是**自定义表**
 * （`frontend/admin-web/src/components/orders/OrderTable.tsx` 手写 `<tbody>` 空态行）
 * ⇒ **调用图看不见这种形态**。这不是判据写错，是**手段的射程盲区**。
 * ⇒ 覆盖它只能靠**渲染后读屏**：注入读面失败 → 渲染页面 → 断言屏上**不出现任何「没有数据」断言**，
 *   **不管那张表是不是共享组件**。
 *
 * ## 本文件钉住的三件事（各自红在**自己那条断言**上）
 *
 *   ① 读失败 ⇒ 屏上**不得**有「没有数据」断言（`findEmptyDataAssertions`，**单一源口径**在
 *      `frontend/admin-web/scripts/read-failure-empty-state-scan.mjs`，本文件不抄第二份正则）；
 *   ② 读失败 ⇒ 失败面（`orders-load-error` + 重试）与「**共 — 条**」**保持**（#6703 的成果，
 *      不得为了 ① 把它们删掉 —— 那样就从"三种说法打架"变成"一句话都不说"）；
 *   ③ **反向对照**：读成功且**确实为空** ⇒ 「暂无数据」照旧、计数「共 0 条」照旧
 *      （真 0 不许被判红 —— 那是把判据用成「删功能」）。
 *
 * ## 判别力自证（本文件的第四组用例，**运行期**口径）
 *
 * 「把 `/orders` 的空态行改回无条件渲染 ⇒ 必红」这件事在**运行期**的等价形态 = 直接渲染
 * `OrderTable`（**不传** `emptyText`，即页面回退成"不接失败读数"的形态）⇒ 同一个
 * `findEmptyDataAssertions` 在同一个组件上**当场命中**。⇒ 证明这条断言**不是恒绿**：
 * 它之所以在页面级用例里为空，只因为页面把失败读数接进去了。
 *
 * ## 边界（照实登记，§19.1）
 *
 * - 只判**文本**：判不了「失败面够不够显眼」（那是 §15.7 真机读图的面）；
 * - **列表级与行内占位在纯文本上不可分**（`OrderTable` 在"有行但该行无明细"时也印「暂无数据」）
 *   ⇒ 本文件钉的是**首屏读失败**（列表必为空、不会有行）这一态；存量行场景由静态判据各自承担；
 * - **不测真机**：本文件是 jsdom + mock 读接口失败；真机读数由集成侧复跑（本单不占 3001）。
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

import { findEmptyDataAssertions } from '../../../scripts/read-failure-empty-state-scan.mjs'

const TEST_TIMEOUT = 20_000

/** 读接口 mock（`/orders` 挂载只拉 `orderApi.getOrders`） */
const mockGetOrders = vi.fn()
vi.mock('@/lib/api', () => ({
  orderApi: {
    getOrders: (...a: unknown[]) => mockGetOrders(...a),
    confirmPayment: vi.fn(),
    updateOrderStatus: vi.fn(),
    closeOrder: vi.fn(),
    addRemark: vi.fn(),
    refundOrder: vi.fn(),
  },
}))

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
  usePathname: () => '/orders',
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
  redirect: vi.fn(),
  notFound: vi.fn(),
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn(), loading: vi.fn(), dismiss: vi.fn() },
}))

import OrdersPage from '@/app/(dashboard)/orders/page'
import OrderTable from '@/components/orders/OrderTable'

/** 屏上文本（运行期口径的输入：整页 body 文本，不是一个 testid） */
const screenText = () => document.body.textContent || ''

const noop = () => {}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
})

describe('读失败后屏上不得有「没有数据」断言（运行期，issue #6733）', () => {
  it(
    '① /orders 读失败 ⇒ 屏上零「没有数据」断言（含自有表体空态行）',
    async () => {
      mockGetOrders.mockRejectedValueOnce(new Error('500'))
      render(<OrdersPage />)
      await waitFor(() => expect(mockGetOrders).toHaveBeenCalled())

      // ② 失败面与「共 — 条」必须先在位（否则 ① 可能是「整页没渲染」造成的假绿）
      const surface = await screen.findByTestId('orders-load-error')
      expect(surface).toHaveAttribute('role', 'alert')
      expect(screen.getByTestId('orders-load-error-retry')).toBeInTheDocument()
      expect(screenText()).toMatch(/共\s*—\s*条/)

      // 🔴 ① 改前**就是这条红**：自有表体空态行无条件渲染 ⇒ 屏上印「暂无数据」
      expect(findEmptyDataAssertions(screenText())).toEqual([])
      expect(screen.queryByText('暂无数据')).not.toBeInTheDocument()
      // 表体空态格仍在（只是空了）——不是把整块删掉掩人耳目
      expect(screen.getByTestId('orders-empty')).toBeInTheDocument()
    },
    TEST_TIMEOUT,
  )

  it(
    '③ 反向对照：读成功且**确实为空** ⇒ 「暂无数据」照旧、计数仍印「共 0 条」',
    async () => {
      mockGetOrders.mockResolvedValue({ data: { data: { items: [], total: 0 } } })
      render(<OrdersPage />)
      await waitFor(() => expect(mockGetOrders).toHaveBeenCalled())

      expect(await screen.findByText('暂无数据')).toBeInTheDocument()
      expect(screenText()).toMatch(/共\s*0\s*条/)
      expect(screen.queryByTestId('orders-load-error')).not.toBeInTheDocument()
    },
    TEST_TIMEOUT,
  )

  it(
    '④ 判别力自证（运行期）：同一个组件**不接失败读数**时，本判据当场命中 ⇒ 不是恒绿',
    async () => {
      // 页面把失败读数接进去（`emptyText={loadError ? '' : …}`）⇒ 不命中
      const ok = render(
        <OrderTable orders={[]} loading={false} selectedIds={[]} onSelectChange={noop} onView={noop}
          onRemark={noop} onClose={noop} onShip={noop} emptyText="" />,
      )
      expect(findEmptyDataAssertions(screenText())).toEqual([])
      ok.unmount()

      // 把「接失败读数」这一步摘掉（= 页面回退成改前形态：默认文案）⇒ **必红**
      render(
        <OrderTable orders={[]} loading={false} selectedIds={[]} onSelectChange={noop} onView={noop}
          onRemark={noop} onClose={noop} onShip={noop} />,
      )
      const hits = findEmptyDataAssertions(screenText())
      expect(hits.length).toBeGreaterThan(0)
      expect(hits[0].text).toContain('暂无')
    },
    TEST_TIMEOUT,
  )

  it(
    '⑤ 口径自证：「读不到」被**正确**说出来时不算空态断言（不误伤失败面）',
    async () => {
      // 失败面自己那句「没读到数据」不得被当成「没有数据」断言
      expect(findEmptyDataAssertions('订单加载失败 —— 没读到数据，下面的条数与列表都不可信。')).toEqual([])
      expect(findEmptyDataAssertions('列表读取失败 —— 请检查网络后重试')).toEqual([])
      // 行内字段占位（`暂无消息` 一族）不是列表体断言
      expect(findEmptyDataAssertions('暂无消息')).toEqual([])
      // 真的空态断言 ⇒ 必须命中（含**别的措辞**：本判据不绑死「暂无数据」四个字）
      expect(findEmptyDataAssertions('暂无数据').length).toBe(1)
      expect(findEmptyDataAssertions('暂无订单').length).toBe(1)
      expect(findEmptyDataAssertions('还没有订单记录').length).toBe(1)
    },
    TEST_TIMEOUT,
  )
})
