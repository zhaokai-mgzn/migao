// case_ids: OR-036, OR-038
// 原声明 `OR-009, UI-038` 是**借用式**（issue #4431 B7 核实并替换）：OR-009 是下单全流程、
// UI-038 是「新增订单表单选择已有客户回填收货信息」—— 两条都不覆盖本文件被测行为（算料试算纯函数）。
// 改用 **OR-036**（本 PR 新增，判据即本文件 + orders-new-craft-calc.test.tsx）。
// OR-038（issue #4521 新增）：**纱帘不算料**（「买多少就是多少」）这条 fail-closed。
/**
 * 下单页算料试算的**纯函数半边**（issue #4434 · 前置 #4421）。
 *
 * 判据聚焦四条 fail-closed：**参数不全不发请求** / **纱帘不算料** / **非韩褶不发请求** /
 * **失败不给估算值**。
 * 红证（实现前）：`@/lib/craft-calc-request` 不存在 ⇒ import 即红。
 */
import { describe, expect, it } from 'vitest'
import {
  CRAFT_CALC_FORMULA_FULLNESS,
  CRAFT_CALC_FORMULA_PLEAT,
  CRAFT_CALC_MOUNTING,
  CRAFT_CALC_TIER,
  METERS_SOURCE_FORMULA,
  METERS_SOURCE_MANUAL,
  craftCalcErrorText,
  craftCalcParamsOf,
  craftCalcSignature,
  isAutoCalcUnavailable,
} from '@/lib/craft-calc-request'
import { CURTAIN_TYPE_SHEER } from '@/lib/order-craft-fields'

const line = (over: Partial<Parameters<typeof craftCalcParamsOf>[0]> = {}) => ({
  width: 6.6,
  height: 2.6,
  craft: {} as Record<string, unknown>,
  ...over,
})

describe('craftCalcParamsOf — 凑齐入参才发请求（fail-closed）', () => {
  it('宽高齐全 ⇒ 入参带标准档 + 韩褶 + 开数（开数缺省按 1）+ 默认公式（韩折）', () => {
    expect(craftCalcParamsOf(line())).toEqual({
      width: 6.6,
      height: 2.6,
      open_count: 1,
      mounting: CRAFT_CALC_MOUNTING,
      craft_tier: CRAFT_CALC_TIER,
      formula: CRAFT_CALC_FORMULA_PLEAT,
    })
  })

  it('#4527 公式选择：缺省 ⇒ 韩折公式（pleat）；显式指定 ⇒ 原样带出（不认的取值也不静默改写）', () => {
    // 缺省 = 韩折（用户裁定「默认用韩折的」）
    expect(craftCalcParamsOf(line())?.formula).toBe('pleat')
    expect(CRAFT_CALC_FORMULA_PLEAT).toBe('pleat')
    expect(CRAFT_CALC_FORMULA_FULLNESS).toBe('fullness')
    // 显式指定褶倍数公式 ⇒ 原样带出（前端不做映射、不做校验 —— 合法性由算料引擎判）
    expect(craftCalcParamsOf(line({ formula: CRAFT_CALC_FORMULA_FULLNESS }))?.formula).toBe(
      'fullness'
    )
    expect(craftCalcParamsOf(line({ formula: '褶倍数' }))?.formula).toBe('褶倍数')
  })

  it('#4527 公式进触发签名：换公式 ⇒ 签名变化（否则切了公式不会重算）', () => {
    const pleat = craftCalcSignature(craftCalcParamsOf(line()))
    const fullness = craftCalcSignature(
      craftCalcParamsOf(line({ formula: CRAFT_CALC_FORMULA_FULLNESS }))
    )
    expect(pleat).not.toBe(fullness)
  })

  // ── 用户 2026-09-19 追加裁定：「韩折用韩折公式算布料，打孔按倍数法算布料，默认选择 2 倍」──
  it('#4527 韩褶 ⇒ 折数法（pleat）+ s_hook', () => {
    const params = craftCalcParamsOf(line({ craft: { craft: '韩褶' } }))
    expect(params).toMatchObject({
      craft: '韩褶',
      mounting: 's_hook',
      formula: CRAFT_CALC_FORMULA_PLEAT,
    })
  })

  it('#4527 打孔 ⇒ **必须发请求**且走倍数法（fullness）+ eyelet（旧口径下打孔返回 null ⇒ 永不发请求 ⇒ 红）', () => {
    const params = craftCalcParamsOf(line({ craft: { craft: '打孔' } }))
    expect(params).not.toBeNull()
    expect(params).toMatchObject({
      craft: '打孔',
      mounting: 'eyelet',
      formula: CRAFT_CALC_FORMULA_FULLNESS,
    })
    // 打孔不是韩褶 ⇒ 不得仍硬编码 s_hook（后端会按韩褶口径算）
    expect(params?.mounting).not.toBe(CRAFT_CALC_MOUNTING)
  })

  it('开数/款式/拼次随工艺规格带出（拼色用料系数靠 special_options）', () => {
    const params = craftCalcParamsOf(
      line({
        craft: { openCount: 2, style: '拼色', specialOptions: ['拼1次'] },
      })
    )
    expect(params).toMatchObject({
      open_count: 2,
      style: '拼色',
      special_options: ['拼1次'],
    })
  })

  it('缺宽 ⇒ null（**不得**用默认窗宽猜一个米数）', () => {
    expect(craftCalcParamsOf(line({ width: null }))).toBeNull()
  })

  it('缺高 ⇒ null', () => {
    expect(craftCalcParamsOf(line({ height: null }))).toBeNull()
  })

  it('宽/高非正数 ⇒ null（0 与负数都不是「没填」以外的合法值）', () => {
    expect(craftCalcParamsOf(line({ width: 0 }))).toBeNull()
    expect(craftCalcParamsOf(line({ width: -1 }))).toBeNull()
    expect(craftCalcParamsOf(line({ height: 0 }))).toBeNull()
  })

  it('非韩褶工艺（四爪钩/穿杆/平幔）⇒ null（无自动算料口径，后端答不出）', () => {
    for (const craft of ['四爪钩', '穿杆', '平幔']) {
      expect(craftCalcParamsOf(line({ craft: { craft } }))).toBeNull()
    }
  })

  it('韩褶 / 未指定工艺 ⇒ 可试算（未指定按默认韩褶档）', () => {
    expect(craftCalcParamsOf(line({ craft: { craft: '韩褶' } }))).not.toBeNull()
    expect(craftCalcParamsOf(line({ craft: {} }))).not.toBeNull()
  })

  // issue #4521（用户裁定「**纱帘不需要算用料米数，买多少就是多少**」）：
  // 纱帘发了试算请求 ⇒ 商家手填的米数会被公式值**静默改回**（错单且无人知道）。
  it('#4521 纱帘 ⇒ null（买多少就是多少，**不得**发试算请求）', () => {
    expect(
      craftCalcParamsOf(line({ curtainType: CURTAIN_TYPE_SHEER, craft: { craft: '韩褶' } }))
    ).toBeNull()
  })

  it('#4521 主帘（部位缺省 / 布帘）⇒ 照常试算（红证：不得把「不写部位」也一起挡掉）', () => {
    expect(craftCalcParamsOf(line({ craft: { craft: '韩褶' } }))).not.toBeNull()
  })

  it('#4521 isAutoCalcUnavailable：纱帘恒为「无自动算料」（页面据此提示手填米数）', () => {
    expect(isAutoCalcUnavailable(line({ curtainType: CURTAIN_TYPE_SHEER }))).toBe(true)
    expect(isAutoCalcUnavailable(line({ craft: { craft: '韩褶' } }))).toBe(false)
    // issue #4527 追加裁定后：**打孔有自动算料口径**（倍数法）⇒ 不再是「无自动算料」
    expect(isAutoCalcUnavailable(line({ craft: { craft: '打孔' } }))).toBe(false)
    expect(isAutoCalcUnavailable(line({ craft: { craft: '四爪钩' } }))).toBe(true)
  })
})

describe('craftCalcSignature — 入参不变就不重发', () => {
  it('同一入参 ⇒ 同一签名（写回 quantity 不会再次触发试算）', () => {
    expect(craftCalcSignature(craftCalcParamsOf(line()))).toBe(
      craftCalcSignature(craftCalcParamsOf(line()))
    )
  })

  it('改宽 / 改开数 / 改拼次 ⇒ 签名变化（该重算的必须重算）', () => {
    const base = craftCalcSignature(craftCalcParamsOf(line()))
    expect(craftCalcSignature(craftCalcParamsOf(line({ width: 5 })))).not.toBe(base)
    expect(
      craftCalcSignature(craftCalcParamsOf(line({ craft: { openCount: 2 } })))
    ).not.toBe(base)
    expect(
      craftCalcSignature(
        craftCalcParamsOf(line({ craft: { style: '拼色', specialOptions: ['拼2次'] } }))
      )
    ).not.toBe(base)
  })

  it('null 入参 ⇒ 空签名（不触发请求）', () => {
    expect(craftCalcSignature(null)).toBe('')
  })
})

describe('craftCalcErrorText — 失败给可行动提示，**不给估算值**', () => {
  it('优先取后端 error.message（如「拼3次纸表未登记」）', () => {
    const text = craftCalcErrorText({
      response: { data: { error: { message: '特殊选项「拼3次」的拼色用料系数纸表未登记' } } },
    })
    expect(text).toContain('算料试算失败')
    expect(text).toContain('拼3次')
  })

  it('无任何 message ⇒ 兜底文案（不得空串，也不得悄悄算一个数）', () => {
    expect(craftCalcErrorText({})).toContain('算料试算失败')
    expect(craftCalcErrorText(undefined)).toContain('请核对宽高与工艺')
  })
})

describe('用料来源两态（真值源 §8：用料必须带来源）', () => {
  it('「公式计算」与「人工指定」是两个不同真值（手改后不得被静默改回）', () => {
    expect(METERS_SOURCE_FORMULA).toBe('公式计算')
    expect(METERS_SOURCE_MANUAL).toBe('人工指定')
    expect(METERS_SOURCE_FORMULA).not.toBe(METERS_SOURCE_MANUAL)
  })
})
