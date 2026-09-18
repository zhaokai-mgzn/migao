// case_ids: PG-020
// 复用既有用例 PG-020（工序库读/写面）。本文件钉的是 #4363 新增的**契约消费点**：
// 页面测试整模块 mock 了 '@/lib/api' ⇒ 端点 URL/动词不在其覆盖内（同 production-api.test.ts 的口径）。
// 契约由 #4361 冻结，前端**只消费、不许改名**：
//   GET  /api/admin/production/seed-templates
//   POST /api/admin/production/seed-templates/{templateId}/apply
import { describe, it, expect, vi, beforeEach } from 'vitest'

const mockPost = vi.fn()
const mockGet = vi.fn()
vi.mock('@/lib/request', () => ({
  default: {
    post: (...args: unknown[]) => mockPost(...args),
    get: (...args: unknown[]) => mockGet(...args),
  },
}))

import { productionApi } from '@/lib/api'

describe('productionApi 行业模板端点（issue #4361 冻结契约，前端半边 #4363）', () => {
  beforeEach(() => {
    mockGet.mockReset().mockResolvedValue({ data: { success: true, data: [] } })
    mockPost.mockReset().mockResolvedValue({
      data: { success: true, data: { created_operations: 30, created_routings: 9, skipped: 4 } },
    })
  })

  it('getSeedTemplates 打 GET /api/admin/production/seed-templates', async () => {
    await productionApi.getSeedTemplates()
    expect(mockGet.mock.calls.map((c) => c[0])).toEqual(['/api/admin/production/seed-templates'])
  })

  it('applySeedTemplate 打 POST /api/admin/production/seed-templates/{templateId}/apply（body 为空）', async () => {
    const res = await productionApi.applySeedTemplate('curtain')

    expect(mockPost).toHaveBeenCalledTimes(1)
    expect(mockPost.mock.calls[0][0]).toBe('/api/admin/production/seed-templates/curtain/apply')
    // 响应三键透传（toast 的「新增/跳过」数字就取自这里，页面不得自己编）
    expect(res.data.data).toEqual({ created_operations: 30, created_routings: 9, skipped: 4 })
  })
})
