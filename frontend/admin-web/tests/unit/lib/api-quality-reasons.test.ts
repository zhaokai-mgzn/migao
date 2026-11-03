// case_ids: MC-181
/**
 * `qualityReasonApi.list()` 的接口形态判据（issue #7197 ①）。
 *
 * 为什么单独一个模块：`src/lib/api.ts` 在 LOC 冻结面里（`tests/unit_ci_workflows/loc_freeze_ledger.json`，
 * 只许缩短），所以原因字典的接口面下沉到本文件 —— 判据跟着模块走。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'

const get = vi.fn()
vi.mock('@/lib/request', () => ({ default: { get: (...a: unknown[]) => get(...a) } }))

describe('不合格原因字典接口（issue #7197 ①）', () => {
  beforeEach(() => get.mockReset())

  it('打到服务端唯一真值源的路径', async () => {
    get.mockResolvedValue({ success: true, data: { items: [] } })
    const { qualityReasonApi } = await import('@/lib/api-quality-reasons')
    await qualityReasonApi.list()
    expect(get).toHaveBeenCalledTimes(1)
    expect(get.mock.calls[0][0]).toBe('/api/admin/quality-inspections/reasons')
  })

  it('返回形状 = `{ items: [{ code, label }] }`（不在前端另造一份会漂的表）', async () => {
    const payload = {
      success: true,
      data: { items: [{ code: 'fabric_stain', label: '布面污渍' }] },
    }
    get.mockResolvedValue(payload)
    const { qualityReasonApi } = await import('@/lib/api-quality-reasons')
    const response = await qualityReasonApi.list()
    expect(response.data).toEqual({ items: [{ code: 'fabric_stain', label: '布面污渍' }] })
  })
})
