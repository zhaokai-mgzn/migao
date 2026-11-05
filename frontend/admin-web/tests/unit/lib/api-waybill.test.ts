// case_ids: MC-220, MC-217
/**
 * 物流取号接口面（issue #8698 P0）—— `frontend/admin-web/src/lib/api-waybill.ts`。
 *
 * 判据（都能红）：
 * 1. **只调本系统端点**：三个方法分别打 `/api/admin/logistics/carriers`、
 *    `/api/admin/logistics/carrier-config`、`/api/admin/logistics/orders/{id}/waybill` ——
 *    出现任何承运商域名 ⇒ 判据 1 红（前端不直连承运商）；
 * 2. **取号 ≠ 发货**：本模块**没有**任何 ship / 状态流转调用（红证：往模块里加一条
 *    `/api/admin/production/orders/.../ship` ⇒ 判据 2 红）；
 * 3. **空配置 = 全 manual**：`saveCarrier(null)` 必须把 `carrierCode: null` 原样发出去
 *    （不是空串、不是省略键 —— 省略键在服务端与「没改」不可区分）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

const get = vi.fn()
const put = vi.fn()
const post = vi.fn()

vi.mock('@/lib/request', () => ({
  default: { get: (...a: any[]) => get(...a), put: (...a: any[]) => put(...a), post: (...a: any[]) => post(...a) },
}))

import { waybillApi } from '@/lib/api-waybill'

const LOGISTICS_PREFIX = '/api/admin/logistics/'

describe('waybillApi（issue #8698 P0）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    get.mockResolvedValue({ data: { data: {} } })
    put.mockResolvedValue({ data: { data: {} } })
    post.mockResolvedValue({ data: { data: {} } })
  })

  it('判据 1：三个方法只打本系统 logistics 端点', async () => {
    await waybillApi.getCapabilities()
    expect(get.mock.calls[0][0]).toBe('/api/admin/logistics/carriers')

    await waybillApi.saveCarrier('sf')
    expect(put.mock.calls[0][0]).toBe('/api/admin/logistics/carrier-config')

    await waybillApi.createWaybill('o-1', { receiverAddress: '杭州市西湖区文三路 1 号' })
    expect(post.mock.calls[0][0]).toBe('/api/admin/logistics/orders/o-1/waybill')

    const urls = [...get.mock.calls, ...put.mock.calls, ...post.mock.calls].map((c) => String(c[0]))
    expect(urls.filter((u) => !u.startsWith(LOGISTICS_PREFIX))).toEqual([])
  })

  it('判据 2：取号接口面不含发货调用（取号 ≠ 发货）', async () => {
    await waybillApi.createWaybill('o-1', {})
    const urls = [...get.mock.calls, ...put.mock.calls, ...post.mock.calls].map((c) => String(c[0]))
    expect(urls.filter((u) => u.includes('/ship'))).toEqual([])
  })

  it('判据 3：空配置发送 carrierCode: null（不是空串、不是省略键）', async () => {
    await waybillApi.saveCarrier(null)
    expect(put.mock.calls[0][1]).toEqual({ carrierCode: null })

    await waybillApi.saveCarrier('sja')
    expect(put.mock.calls[1][1]).toEqual({ carrierCode: 'sja' })
  })

  it('订单号做 URL 编码（订单号里出现斜杠也不会打到别的端点）', async () => {
    await waybillApi.createWaybill('o/1 2', {})
    expect(post.mock.calls[0][0]).toBe('/api/admin/logistics/orders/o%2F1%202/waybill')
  })
})
