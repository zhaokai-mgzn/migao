// case_ids: PP-014
//
// 「护栏失败响应体**契约形状**」的回归守卫（issue #4307；契约见 #4308「冻结补遗 ②」/ #4386 判据 3）。
// 存在理由：本文件前身是一个**集成方探针** —— 当时的实现按**虚构形状**读理由
// （顶层 `error_messages` + 把 `error` 当字符串），于是交付测试全绿，
// 而对**真实**信封 2/2 红、商家只看到「Request failed with status code 422」。
// 探针现转正为回归守卫：形状一改回去，这里立刻红。
//
// 位置说明：本文件原在 `tests/unit/pages/production-routings-guard-envelope.test.ts`，
// 随被测函数一起迁到 `lib/`（route 文件不得导出非框架字段，issue #4412）。
//
// 用**后端真实信封**（ApiResponse{success:false, error:{code,message,details:[{field,message}]}}）
// 喂解析函数，断言「逐条护栏理由被读出」这一**性质**（不绑定具体措辞）。
//
// ⚠️ 覆盖口径如实登记：`routingGuardReasons` 对应 PP-014（工艺路线用户面）；
// `feeGuardReasons`（加工费**组合**定价面，issue #4386；#4490 合并后是 `/production/processing`
// 的第二个 tab「加工费组合」）**目前没有对应用例条目** ——
// 属已登记的用例库缺口（见台账 #4411 的 B7），本文件只保证其**行为**不退化，不冒充用例覆盖。
import { describe, expect, it } from 'vitest'
import { describeRoutingGuard, feeGuardReasons, routingGuardReasons } from '@/lib/production-guard-reasons'

const realEnvelope = (details: { field: string; message: string }[]) => ({
  response: {
    status: 422,
    data: {
      success: false,
      error: { code: 'VALIDATION_ERROR', message: `校验未通过：${details.length} 项`, details },
    },
    suggestion: '请修正后重试',
  },
  message: 'Request failed with status code 422',
})

describe('探针：真实后端信封（路线页口径）', () => {
  it('error.details 应被逐条读出（主口径）', () => {
    const got = routingGuardReasons(
      realEnvelope([
        { field: 'operations', message: '路线不能为空' },
        { field: 'operations', message: '主线中引用的工序「三边」在工序库里不存在' },
      ]),
    )
    expect(got).toHaveLength(2)
    expect(got[0]).toContain('路线不能为空')
    expect(got[1]).toContain('工序「三边」在工序库里不存在')
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

  it('路线护栏文案带领域前缀（重复 / 工序不存在 / 权限），识别不了的原样透出', () => {
    expect(describeRoutingGuard('工序重复')).toContain('工序重复')
    expect(describeRoutingGuard('主线中的工序「三边」不存在')).toContain('工序不存在')
    expect(describeRoutingGuard('没有权限')).toContain('没有工艺路线管理权限')
    expect(describeRoutingGuard('别的理由')).toBe('别的理由')
    expect(describeRoutingGuard('')).toBe('保存失败')
  })

  it('#4961-⑥（**改判**）「缺少必完工序」前缀**已删除**：后端护栏 4 退场 ⇒ 该分支不可达（死代码）', () => {
    // 本文件原先自述的**死亡条件** = 「后端护栏 4 与本文件同时被判据移除」，**已满足**（issue #4961）：
    // `ProductionRoutingCommandService.validateMainline` 删掉「至少 1 道必完工序」（五条 ⇒ 四条），
    // 后端测试已改判为「#4961 护栏 4 **退场**：一道必完工序都没有 ⇒ 照常保存成功」。
    // ⇒ 判据取「**前缀不再被套上** + 理由原文**一字不吞**」（移除类判据 = 改前存在、断言不存在）。
    const raw = '主线中至少要有 1 道必完工序：必完工序全绿是加工单完工判定的唯一依据，一道都没有 ⇒ 这张单永远完不了工'
    const got = describeRoutingGuard(raw)
    expect(got).not.toContain('缺少必完工序：')   // 前缀整条退场（改前这里是 `缺少必完工序：${raw}`）
    expect(got).toContain('必完工序')            // 反 placeholder：后端理由本身逐字透出，没被吞成通用文案
    expect(got).not.toBe('保存失败')
  })
})

describe('加工费页口径（feeGuardReasons）', () => {
  it('details 逐条读出，且**不套**路线专属前缀（字段是加工项与单价）', () => {
    const got = feeGuardReasons(
      realEnvelope([
        { field: 'items', message: '组合不能为空' },
        { field: 'unit_price', message: '单价必须为正' },
      ]),
    )
    expect(got).toEqual(['组合不能为空', '单价必须为正'])
    expect(got.join('|')).not.toContain('工序重复')
  })

  it('无 details 时退化成 error.message；连 message 都没有才用兜底文案', () => {
    expect(feeGuardReasons({ response: { data: { error: { message: '组合不能为空' } } } })).toEqual(['组合不能为空'])
    expect(feeGuardReasons(new Error('boom'))).toEqual(['boom'])
    expect(feeGuardReasons(undefined)).toEqual(['保存失败，请稍后重试'])
  })
})
