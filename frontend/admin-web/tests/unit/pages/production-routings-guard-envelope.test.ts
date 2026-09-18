// case_ids: PP-014
//
// 护栏失败响应体**契约形状**的回归守卫（issue #4307；契约见 #4308「冻结补遗 ②」）。
// 存在理由：本文件前身是一个**集成方探针** —— 当时的实现按**虚构形状**读理由
// （顶层 `error_messages` + 把 `error` 当字符串），于是交付测试全绿，
// 而对**真实**信封 2/2 红、商家只看到「Request failed with status code 422」。
// 探针现转正为回归守卫：形状一改回去，这里立刻红。
//
// 用**后端真实信封**（ApiResponse{success:false, error:{code,message,details:[{field,message}]}}）
// 喂 routingGuardReasons()，断言「逐条护栏理由被读出」这一**性质**（不绑定具体措辞）。
import { describe, expect, it } from 'vitest'
import { routingGuardReasons } from '@/app/(dashboard)/production/routings/page'

const realEnvelope = (details: { field: string; message: string }[]) => ({
  response: {
    status: 422,
    data: {
      success: false,
      error: { code: 'VALIDATION_ERROR', message: `工艺路线校验未通过：${details.length} 项`, details },
    },
    suggestion: '请修正后重试',
  },
  message: 'Request failed with status code 422',
})

describe('探针：真实后端信封', () => {
  it('error.details 应被逐条读出（主口径）', () => {
    const got = routingGuardReasons(
      realEnvelope([
        { field: 'operations', message: '路线不能为空' },
        { field: 'must_finish', message: '至少要有一道必完工序' },
      ]),
    )
    expect(got).toHaveLength(2)
    expect(got[0]).toContain('路线不能为空')
    expect(got[1]).toContain('至少要有一道必完工序')
    // 关键性质：不得退化成 axios 的通用文案（旧形状读不到理由时就是这个形态）
    expect(got.join('|')).not.toContain('Request failed with status code')
  })

  it('只有 error.message（无 details）时应退化成单条，而不是通用文案', () => {
    const got = routingGuardReasons({
      response: { status: 422, data: { success: false, error: { code: 'VALIDATION_ERROR', message: '路线不能为空' } } },
      message: 'Request failed with status code 422',
    })
    expect(got).toHaveLength(1)
    expect(got[0]).toContain('路线不能为空')
    expect(got.join('|')).not.toContain('Request failed with status code')
  })
})
