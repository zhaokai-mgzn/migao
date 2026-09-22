// case_ids: PR-081
//
// PR-081（issue #5177）：池看板的**纯前端薄助手** —— 池化派单请求体 + 服务端值的展示格式化。
//
// 本文件只钉两件**前端口径红线**（真值源 = `ProductionPoolViews.Preview` 的五个 BigDecimal 字段
// + `migao-dev-flow` §15）：
//   ① **不重算米数**：`formulaMeters` / `pooledPlannedMeters` / `savedMeters` /
//      `perOrderPlannedMeters` / `poolingGainMeters` —— **五个都是服务端聚合**，一律**原样渲染**
//      （要求是「口径必须与落账逐值相等」，在浏览器里再算一次 = 第二份会漂的口径）。
//      ⚠️ `perOrderPlannedMeters` 是**一个数**（逐单派的应领**合计**，对照读数），
//      **不是** orderId → 米数 的映射 ⇒ 预览区没有逐单明细表（API 不下发）。
//      红证两条：① 用**故意不自洽**的服务端数字（`formulaMeters − pooledPlannedMeters ≠ savedMeters`）
//      ⇒ 前端一旦自己相减就红；② 删掉「对照·逐单派应领」行（= 把它当 map 处理的后果）⇒ 红。
//   ② **不重排**：本模块**不导出**任何排序器；顺序由页面按接口数组顺序渲染（DOM 序判据在
//      `tests/unit/pages/production-pool-batch.test.tsx`，那里才是顺序的消费者）。
import { describe, it, expect } from 'vitest'
import {
  buildPoolRequest,
  formatDeliveryDaysLeft,
  formatMeters,
  formatRequiredDeliveryDate,
  formatWaitHours,
  previewSummaryRows,
} from '@/lib/pool-board'
import type { PoolPreview } from '@/types'

describe('buildPoolRequest（/preview 与 /dispatch 同体）', () => {
  it('成批池化：pooled=true，四个键齐全（batches/assignmentRule 显式给空值）', () => {
    expect(buildPoolRequest(['o1', 'o2'], true)).toEqual({
      orderIds: ['o1', 'o2'],
      batches: [],
      assignmentRule: null,
      pooled: true,
    })
  })

  it('加急插队：**同一个端点 + 单订单 + pooled=false**（一个动作，不批）', () => {
    const body = buildPoolRequest(['u1'], false)
    expect(body.pooled).toBe(false)
    expect(body.orderIds).toEqual(['u1'])
    // 加急插队是「一单一派」—— 批内混加急会被服务端整批拒绝（422），前端不制造那种请求
    expect(body.orderIds).toHaveLength(1)
  })
})

describe('等待时长 / 到货日 文案（入参 = 服务端值，不重算）', () => {
  it('等待时长 < 24 小时按小时显示，≥ 24 小时进位成「X 天 Y 小时」', () => {
    expect(formatWaitHours(3)).toBe('3 小时')
    expect(formatWaitHours(12.5)).toBe('12.5 小时')
    expect(formatWaitHours(24)).toBe('1 天')
    expect(formatWaitHours(50)).toBe('2 天 2 小时')
  })

  it('到货日剩余天数：null = 未指定、负数 = 已逾期、0 = 今天到期', () => {
    expect(formatDeliveryDaysLeft(null)).toBe('未指定')
    expect(formatDeliveryDaysLeft(-2)).toBe('已逾期 2 天')
    expect(formatDeliveryDaysLeft(0)).toBe('今天到期')
    expect(formatDeliveryDaysLeft(3)).toBe('剩 3 天')
  })

  it('到货日：null/空 = 未指定（不猜一个日期）', () => {
    expect(formatRequiredDeliveryDate(null)).toBe('未指定')
    expect(formatRequiredDeliveryDate(undefined)).toBe('未指定')
    expect(formatRequiredDeliveryDate('2026-09-30')).toBe('2026-09-30')
  })

  it('米数：缺失值显示 -（不是 0.00 —— 0 与「没有值」是两件事）', () => {
    expect(formatMeters(0)).toBe('0.00')
    expect(formatMeters(12.345)).toBe('12.35')
    expect(formatMeters(null)).toBe('-')
    expect(formatMeters(undefined)).toBe('-')
  })
})

describe('成批预览摘要：渲染服务端值，绝不自己相减', () => {
  // ⚠️ 真值源 = `ProductionPoolViews.Preview`：**五个米数字段全是 BigDecimal**（都是聚合）。
  // `perOrderPlannedMeters` 是**一个数**（逐单派的应领**合计**，对照读数），**不是** map ——
  // 当成 `Object.entries(...)` 会静默渲染出 0 行（本仓库明令禁止的「空转」形态）。
  const preview = {
    orderCount: 2,
    assignmentRule: 'best-fit',
    formulaMeters: 10,
    pooledPlannedMeters: 6.5,
    // 🔴 **故意不自洽**：真实服务端会给 3.5，这里给 99 —— 只要前端自己算
    // `formulaMeters − pooledPlannedMeters`，下面的断言立刻红（= 判据不会被自己的文案喂绿）
    savedMeters: 99,
    perOrderPlannedMeters: 8, // 对照读数（逐单派应领合计），**一个数**
    poolingGainMeters: 1.5, // = 8 − 6.5（服务端算）
  } as unknown as PoolPreview

  it('五行摘要逐字给出服务端的五个键（标签分开「预计节省」与「池化新增收益」）', () => {
    const rows = previewSummaryRows(preview)
    expect(rows.map((r) => r.label)).toEqual([
      '逐单公式米数（对照基线）',
      '预计领料米数（池化后）',
      '预计节省',
      '对照·逐单派应领',
      '池化新增收益',
    ])
    expect(rows.map((r) => r.value)).toEqual(['10.00', '6.50', '99.00', '8.00', '1.50'])
  })

  it('`perOrderPlannedMeters` 是**一个数**（对照读数）—— 不是 orderId→米数 的映射', () => {
    const rows = previewSummaryRows(preview)
    // 当 map 处理（`Object.entries(<number>)`）⇒ 该行会是 `-` 或整块消失 ⇒ 这两条红
    const compare = rows.find((r) => r.label === '对照·逐单派应领')!
    expect(compare).toBeTruthy()
    expect(compare.value).toBe('8.00')
  })

  it('「预计节省」与「池化新增收益」是两个独立的服务端键 —— 合成一句就是丢信息', () => {
    const rows = previewSummaryRows(preview)
    const saved = rows.find((r) => r.label === '预计节省')!
    const gain = rows.find((r) => r.label === '池化新增收益')!
    // saved = formula − pooled = 3.5（**真实**服务端值；本桩故意给 99 以钉「不自己算」）；
    // gain = perOrder − pooled = 1.5：两者是**不同**的数，混成一个就分不清「池化的功劳」与「旧收益」
    expect(saved.value).not.toBe(gain.value)
    expect(saved.value).toBe('99.00')
    expect(gain.value).toBe('1.50')
  })
})
