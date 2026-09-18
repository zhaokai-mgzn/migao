// case_ids: PG-005, PG-036
//
// PG-036（issue #4357）：加工单菜单并入生产管理组、与生产看板**合并为单一入口** ——
//   列表页 /processing-orders **不再渲染任何列表**，改为重定向到 /production；
//   旧深链（书签/外部链接）不得 404。⚠️ 子路由 /processing-orders/{id}/production（生产明细）
//   **不随菜单移除**，仍由看板行内「生产明细」按钮进入（见 production-board.test.tsx）。
//
// PG-005（issue #4305，用户裁定「从订单作为发加工的唯一入口」）：列表页**不再提供任何状态流转入口**
//   —— 发加工/开始加工/加工完成/取消 四个按钮都不渲染。本文件原先断言的「四个按钮不渲染 +
//   只留 查看/生产明细」随 PG-036 合并**改判到生产看板**（唯一入口 = /production，断言在
//   production-board.test.tsx 的「入口收敛不回归」一条）；本文件保留「旧入口已退场」这一条：
//   访问 /processing-orders 不再有可操作的列表页，而是直接落到唯一入口。
//   （状态机语义与订单联动改判见 ProcessingOrderServiceTest 的 PG-001/PG-005/PG-007 用例。）
import { describe, it, expect, vi } from 'vitest'

const mockRedirect = vi.fn()

vi.mock('next/navigation', () => ({
  redirect: (...args: unknown[]) => mockRedirect(...args),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => '/processing-orders',
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
}))

import ProcessingOrdersPage from '@/app/(dashboard)/processing-orders/page'

describe('旧加工单列表入口（PG-036 / issue #4357）', () => {
  it('访问 /processing-orders 重定向到 /production（旧深链不 404，不再渲染列表页）', () => {
    ProcessingOrdersPage()

    expect(mockRedirect).toHaveBeenCalledWith('/production')
  })
})
