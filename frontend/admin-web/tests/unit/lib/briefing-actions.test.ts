// case_ids: DA-032
import { describe, it, expect, vi, beforeEach } from 'vitest'

const post = vi.fn()
vi.mock('@/lib/request', () => ({ default: { post: (url: string, data: any) => post(url, data) } }))

import { briefingActionApi } from '@/lib/briefing-actions'

/**
 * 决策采纳上报（issue #8260）。
 *
 * 这个模块本身很小，但它承接了两条**会坏事**的约束：
 *
 * 1. **端点与路径**：打错一个字母就是「点了但没记上」，而用户毫无感知 —— 只能靠判据钉。
 * 2. **它是 `lib/api.ts` 的暂存区**：`api.ts` 是 2362 行冻结文件，新增接口必须落在这里。
 *    这条由 `tests/unit_ci_workflows/test_loc_ratchet.py` 反向保证，本文件只钉行为。
 */
describe('briefingActionApi.record（issue #8260）', () => {
  beforeEach(() => {
    post.mockReset()
    post.mockResolvedValue({ data: { data: { recorded: true } } })
  })

  it('打的是 /api/admin/briefing/actions，方法 POST', async () => {
    await briefingActionApi.record({
      bizDate: '2026-10-31',
      itemKind: 'suggestion',
      title: '补充知识库',
      action: 'opened_agent',
    })

    expect(post).toHaveBeenCalledTimes(1)
    expect(post.mock.calls[0][0]).toBe('/api/admin/briefing/actions')
    expect(post.mock.calls[0][1]).toEqual({
      bizDate: '2026-10-31',
      itemKind: 'suggestion',
      title: '补充知识库',
      action: 'opened_agent',
    })
  })

  it('原样透传四种 itemKind（todo / risk / suggestion 都是简报里真实存在的区块）', async () => {
    for (const kind of ['todo', 'risk', 'suggestion'] as const) {
      await briefingActionApi.record({
        bizDate: '2026-10-31', itemKind: kind, title: 't', action: 'opened_agent',
      })
      expect(post.mock.calls.at(-1)![1].itemKind).toBe(kind)
    }
  })
})
