// case_ids: PP-014
// PP-014（issue #4307 交付物 2 / 契约所有者 = 后端 4308）：route_source → 用户提示的**单点映射**。
// 四态穷举（derived / partial / missing_route / default）+ 未知/缺失值不得提示，
// 以及两个键的分工：route_key = 实际使用，route_requested_key = 识别到的（missing_route 才有话可说）。
// 红证（实现前）：本模块不存在 ⇒ import 即红；三态静默 ⇒ 每条断言红。
import { describe, expect, it } from 'vitest'
import { routeSourceNotice } from '@/lib/route-source'

describe('routeSourceNotice — 加工单路线来源提示（四态）', () => {
  it('derived：正常派生不提示（避免噪音）', () => {
    expect(routeSourceNotice('derived', '布帘×韩褶')).toBeNull()
  })

  it('unknown / 缺失：不提示，且不得回落成「已派生」的正面结论', () => {
    expect(routeSourceNotice(undefined, '布帘×韩褶')).toBeNull()
    expect(routeSourceNotice(null, null)).toBeNull()
    expect(routeSourceNotice('', '布帘×韩褶')).toBeNull()
    // 未来新增态（如 derived_from_cache）在未登记前一律静默，不得猜成语义
    expect(routeSourceNotice('derived_from_cache', '布帘×韩褶')).toBeNull()
  })

  it('default：两维全不命中 ⇒ 高亮警示 + 要求核对工序与计件单价 + 引导把部位/做法填进订单', () => {
    const n = routeSourceNotice('default', '布帘×韩褶')
    expect(n?.key).toBe('default')
    expect(n?.tone).toBe('warning')
    expect(n?.title).toContain('没有填部位/做法')
    expect(n?.title).toContain('请核对工序与计件单价')
    expect(n?.detail).toContain('本单实际使用：布帘×韩褶')
    expect(n?.detail).toContain('填进订单')
  })

  it('partial：只命中一维 ⇒ 提示另一半取默认值（notice 档，非高亮）', () => {
    const n = routeSourceNotice('partial', '纱帘×韩褶')
    expect(n?.key).toBe('partial')
    expect(n?.tone).toBe('notice')
    expect(n?.title).toContain('只填了一半')
    expect(n?.detail).toContain('本单实际使用：纱帘×韩褶')
  })

  it('missing_route：两维都命中但库里没路线 ⇒ 报 route_requested_key + 去工艺配置页建', () => {
    const n = routeSourceNotice('missing_route', '布帘×韩褶', '罗马帘×韩褶')
    expect(n?.key).toBe('missing_route')
    expect(n?.tone).toBe('warning')
    expect(n?.title).toContain('没有对应路线')
    expect(n?.detail).toContain('本单识别的是 罗马帘×韩褶')
    expect(n?.detail).toContain('本单实际使用：布帘×韩褶')
    expect(n?.detail).toContain('工艺配置')
  })

  it('missing_route 但缺 route_requested_key：不编造识别键，其余文案照给', () => {
    const n = routeSourceNotice('missing_route', '布帘×韩褶', null)
    expect(n?.key).toBe('missing_route')
    expect(n?.detail).not.toContain('本单识别的是')
    expect(n?.detail).toContain('本单实际使用：布帘×韩褶')
  })

  it('键缺失时不编造路线名（route_key 为空 ⇒ 只给处置建议）', () => {
    const n = routeSourceNotice('default', null)
    expect(n?.detail).not.toContain('本单实际使用')
    expect(n?.detail).toContain('填进订单')
  })
})
