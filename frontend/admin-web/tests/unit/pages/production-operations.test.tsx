// case_ids: PG-020
// PG-020（issue #4203 / #4204，前端半边）在 issue #4416 合并后的**旧路径守卫**：
// 「工序库」菜单项已并入「工艺配置」/production/routings（工序库半边 = 该页左栏），
// /production/operations 不再渲染任何页面内容，改为 `redirect('/production/routings')`
// —— 旧书签 / 外部深链 / e2e 直链不得 404（照 #4357 的 /processing-orders → /production 先例）。
//
// 工序库自身的全部能力（分组目录 / 改单价 / 必完开关 / 作用域 / 行业模板补套）断言
// **已迁到** tests/unit/pages/production-routings.test.tsx（case_ids: PG-020, PP-014）——
// 本文件只钉「旧入口仍然可达」，不重复那批断言（避免第二份口径）。
import { describe, expect, it, vi, beforeEach } from 'vitest'

const mockRedirect = vi.fn()

vi.mock('next/navigation', () => ({
  redirect: (...args: unknown[]) => mockRedirect(...args),
}))

import OperationsRedirectPage from '@/app/(dashboard)/production/operations/page'

describe('旧「工序库」入口 /production/operations（issue #4416 合并后）', () => {
  beforeEach(() => {
    mockRedirect.mockReset()
  })

  it('重定向到唯一入口 /production/routings（旧深链不 404）', () => {
    OperationsRedirectPage()

    expect(mockRedirect).toHaveBeenCalledTimes(1)
    expect(mockRedirect).toHaveBeenCalledWith('/production/routings')
  })
})
