// case_ids: KF-030
import { describe, it, expect, vi, beforeEach } from 'vitest'

const get = vi.fn()
const post = vi.fn()
vi.mock('@/lib/request', () => ({ default: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a) } }))

import { kfApi } from '@/lib/kf-api'

describe('kfApi（微信客服自助接入 API 契约）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    get.mockResolvedValue({ data: { data: [] } })
    post.mockResolvedValue({ data: { data: {} } })
  })

  it('列表 GET /api/admin/kf/channels', async () => {
    await kfApi.listChannels()
    expect(get).toHaveBeenCalledWith('/api/admin/kf/channels')
  })

  it('接入 POST：请求体用 snake_case，secret 只在请求体里', async () => {
    await kfApi.createChannel({ corpId: 'corp', openKfid: 'wk-1', secret: 'sec' })
    expect(post).toHaveBeenCalledWith('/api/admin/kf/channels', {
      corp_id: 'corp', open_kfid: 'wk-1', secret: 'sec',
    })
  })

  it('自检 / 停用 / 生成链接的路径与方法', async () => {
    await kfApi.verifyChannel('ch-1')
    await kfApi.disableChannel('ch-1')
    await kfApi.createLink('ch-1', 'tenant:1')
    expect(post).toHaveBeenNthCalledWith(1, '/api/admin/kf/channels/ch-1/verify')
    expect(post).toHaveBeenNthCalledWith(2, '/api/admin/kf/channels/ch-1/disable')
    expect(post).toHaveBeenNthCalledWith(3, '/api/admin/kf/channels/ch-1/link', { scene_param: 'tenant:1' })
  })
})
