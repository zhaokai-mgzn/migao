// case_ids: UI-087
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * 库存明细端点（`GET /api/admin/stock-ledger`，issue #6404 新增前端消费面）。
 *
 * 本文件锚**请求层**（wire-level）：端点路径与三个筛选参数**原样透传** ——
 * 真值源 = `backend/admin-api/src/main/java/com/migao/admin/controller/StockLedgerController.java`
 * 的 `getLedger(skuId, productId, refNo, page, size)`（方法级 `product:list`）。
 *
 * 🔴 **不得传关键词**：该端点**没有**关键词参数（不是模糊搜索），
 * 传了会被服务端**静默丢弃** ⇒ 拿全量冒充过滤结果。商品侧必须先走既有商品搜索拿到 `productId`
 * （见 `frontend/admin-web/tests/unit/pages/stock-ledger.test.tsx` 判据 ⑤）。
 */

const mockGet = vi.fn()

vi.mock('@/lib/request', () => ({
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    post: vi.fn(),
    patch: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}))

import { stockLedgerApi } from '@/lib/api'

beforeEach(() => {
  mockGet.mockReset()
  mockGet.mockResolvedValue({
    data: { data: { items: [], total: 0, page: 1, size: 20 } },
  })
})

describe('库存明细端点（issue #6404 / UI-087）', () => {
  it('① 打到 StockLedgerController 的端点（路径逐字，不得自造第二个）', async () => {
    await stockLedgerApi.ledger()
    expect(mockGet).toHaveBeenCalledWith('/api/admin/stock-ledger', { params: undefined })
  })

  it('② 三个筛选参数原样透传（skuId / productId / refNo + 分页）', async () => {
    await stockLedgerApi.ledger({
      productId: 'prod-1',
      skuId: 12,
      refNo: 'RK-20261001-0001',
      page: 2,
      size: 50,
    })
    expect(mockGet).toHaveBeenCalledWith('/api/admin/stock-ledger', {
      params: { productId: 'prod-1', skuId: 12, refNo: 'RK-20261001-0001', page: 2, size: 50 },
    })
  })

  it('③ 负控：签名里没有关键词参数（端点没有该参数，传了 = 拿全量冒充过滤结果）', async () => {
    await stockLedgerApi.ledger({ productId: 'prod-1' })
    const params = mockGet.mock.calls[0][1].params as Record<string, unknown>
    for (const forbidden of ['keyword', 'name', 'skuCode', 'q']) {
      expect(Object.keys(params)).not.toContain(forbidden)
    }
  })
})
