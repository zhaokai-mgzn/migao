// case_ids: MC-182
/**
 * 缺料风险接口的**形状判据**（issue #6282 / 后端 #6280）。
 *
 * 为什么单独一个模块：`src/lib/api.ts` 在 `tests/unit_ci_workflows/loc_freeze_ledger.json`
 * 的冻结面里（只许缩短），接口面下沉到 `api-material-shortage.ts` —— 判据跟着模块走。
 *
 * 三条口径（对应页面赖以成立的前提）：
 * ① 打的是 `GET /api/admin/materials/shortage`，不走别的路径；
 * ② 参数**原样透传**（`limit` 非法值由服务端显式 400 拒绝，前端**不夹取**、不吞错）；
 * ③ 返回形状 = `{ success, data: { bands, rows, … } }`，页面只读不重排。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'

const mockGet = vi.fn()
vi.mock('@/lib/request', () => ({ default: { get: (...a: unknown[]) => mockGet(...a) } }))

describe('用具缺口与耗尽风险接口（issue #6282）', () => {
  beforeEach(() => mockGet.mockReset())

  it('① 端点路径是缺料视图的唯一入口', async () => {
    mockGet.mockResolvedValue({ data: { success: true, data: { view: 'material_shortage', rows: [], count: 0 } } })
    const { materialShortageApi } = await import('@/lib/api-material-shortage')
    await materialShortageApi.shortage({ limit: 50 })
    expect(mockGet).toHaveBeenCalledTimes(1)
    expect(mockGet.mock.calls[0][0]).toBe('/api/admin/materials/shortage')
  })

  it('② 参数原样透传（不夹取、不替服务端做判定）', async () => {
    mockGet.mockResolvedValue({ data: { success: true, data: { view: 'material_shortage', rows: [], count: 0 } } })
    const { materialShortageApi } = await import('@/lib/api-material-shortage')
    await materialShortageApi.shortage({ limit: 0, statuses: 'blocked,critical' })
    expect(mockGet.mock.calls[0][1]).toEqual({ params: { limit: 0, statuses: 'blocked,critical' } })
  })

  it('③ 行序照服务端（页面不重排）：返回什么顺序就读成什么顺序', async () => {
    const rows = [{ productId: 'p2' }, { productId: 'p1' }]
    const payload = { data: { success: true, data: { view: 'material_shortage', rows, count: 2 } } }
    mockGet.mockResolvedValue(payload)
    const { materialShortageApi } = await import('@/lib/api-material-shortage')
    const res = await materialShortageApi.shortage({ limit: 50 })
    // 接口层**不排序、不过滤**：拿到的就是服务端给的那一段
    expect(res).toBe(payload)
    // axios 风格外壳：`res.data` = ApiResponse，`res.data.data` = 视图本体
    expect(res.data.data.rows).toEqual(rows)
  })
})
