// case_ids: OR-036, OR-038
// 原声明 `OR-009, UI-038` 是**借用式**（issue #4431 B7 核实并替换）：OR-009 是下单全流程、
// UI-038 是「新增订单表单选择已有客户回填收货信息」—— 两条都不覆盖本文件被测行为（算料试算纯函数）。
// 改用 **OR-036**（本 PR 新增，判据即本文件 + orders-new-craft-calc.test.tsx）。
// OR-038（issue #4521 新增；**2026-09-21 口径反转**）：纱帘用料 —— 原「纱帘不算料（买多少
// 就是多少）」这条 fail-closed 已**作废并删除**；现行真值 = **纱帘与布帘用料算法完全一致**
// （同一公式 / 同一档位 / 同一次试算链路），判据见本文件的 `口径反转` 组。
/**
 * 下单页算料试算的**纯函数半边**（issue #4434 · 前置 #4421）。
 *
 * 判据聚焦三条 fail-closed：**参数不全不发请求** / **无自动算料口径的工艺不发请求** /
 * **失败不给估算值**；外加 **2026-09-21 口径反转**：纱帘与布帘**同参同算**。
 * 红证（实现前）：`@/lib/craft-calc-request` 不存在 ⇒ import 即红。
 */
import { describe, expect, it } from 'vitest'
import {
  CRAFT_CALC_FORMULA_FULLNESS,
  CRAFT_CALC_FORMULA_PLEAT,
  CRAFT_CALC_MOUNTING,
  CRAFT_CALC_MOUNTING_BY_CRAFT,
  CRAFT_CALC_TIER,
  CRAFT_PLAN_CANDIDATE_LABELS,
  DEFAULT_CRAFT_NAME,
  JOIN_GAP_MAX_METERS,
  METERS_SOURCE_FORMULA,
  METERS_SOURCE_MANUAL,
  craftCalcErrorText,
  craftCalcParamsOf,
  craftCalcSignature,
  craftPlanCandidateLabel,
  craftPlanHasSplice,
  craftPlanSpliceText,
  isAutoCalcUnavailable,
  joinGapOf,
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

  it('#4527 公式选择：缺省 ⇒ 韩褶公式（pleat）；显式指定 ⇒ 原样带出（不认的取值也不静默改写）', () => {
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

  // ── 用户 2026-09-19 追加裁定：「韩褶用韩褶公式算布料，打孔按倍数法算布料，默认选择 2 倍」──
  it('#4527 韩褶 ⇒ 褶数法（pleat）+ s_hook', () => {
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

  // ── ⚠️ 2026-09-21 用户裁定（**口径反转**）────────────────────────────────────
  // 用户原话：「订单中选择纱帘时，**用料算法和布帘的用料算法完全一致**，之前给的信息是错误的」
  // ⇒ 原 #4521「纱帘不需要算用料米数，买多少就是多少 / 纱帘不算料」**作废**。
  // 下面三条判据是原判据的**反向改判**（**不是删断言**）：
  // ① 纱帘 ⇒ 与布帘**同一入参**（照常试算）；② 纱帘 ≠「无自动算料」；
  // ③ 部位键**仍带**（它是工序路线的索引键）但**不再**影响算不算料。
  // 注入式红证：把 `craftCalcParamsOf` / `isAutoCalcUnavailable` 里的
  // `if (line.curtainType === CURTAIN_TYPE_SHEER) …` 两行加回去 ⇒ 本组必红。
  it('2026-09-21 反转：纱帘 ⇒ **照常试算**，且入参与布帘**逐值一致**（只是部位不同）', () => {
    const sheer = craftCalcParamsOf(
      line({ curtainType: CURTAIN_TYPE_SHEER, craft: { craft: '韩褶' } })
    )
    const cloth = craftCalcParamsOf(line({ craft: { craft: '韩褶' } }))
    expect(sheer).not.toBeNull()
    expect(cloth).not.toBeNull()
    // 部位不进算料入参（`CraftCalcParams` 无该键）⇒ 两者的算料入参必须**完全相同**
    expect(sheer).toEqual(cloth)
  })

  it('2026-09-21 反转：`isAutoCalcUnavailable(纱帘)` = false（纱帘不再被当成「无自动算料」）', () => {
    expect(isAutoCalcUnavailable(line({ curtainType: CURTAIN_TYPE_SHEER }))).toBe(false)
    expect(
      isAutoCalcUnavailable(line({ curtainType: CURTAIN_TYPE_SHEER, craft: { craft: '韩褶' } }))
    ).toBe(false)
    // 真正的「无自动算料」判据不变：工艺无算料口径 ⇒ true（与部位无关）
    expect(isAutoCalcUnavailable(line({ craft: { craft: '韩褶' } }))).toBe(false)
    // issue #4527 追加裁定后：**打孔有自动算料口径**（倍数法）⇒ 不再是「无自动算料」
    expect(isAutoCalcUnavailable(line({ craft: { craft: '打孔' } }))).toBe(false)
    expect(isAutoCalcUnavailable(line({ craft: { craft: '四爪钩' } }))).toBe(true)
    // 纱帘 + 无算料口径的工艺 ⇒ 仍按**工艺**判 true（部位不再是开关）
    expect(
      isAutoCalcUnavailable(line({ curtainType: CURTAIN_TYPE_SHEER, craft: { craft: '四爪钩' } }))
    ).toBe(true)
  })

  it('2026-09-21 反转：参数不全时纱帘与布帘**同样**不发请求（fail-closed 与部位无关）', () => {
    for (const curtainType of [undefined, CURTAIN_TYPE_SHEER]) {
      expect(craftCalcParamsOf(line({ curtainType, craft: {}, width: null }))).toBeNull()
      expect(craftCalcParamsOf(line({ curtainType, craft: {}, height: null }))).toBeNull()
    }
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

describe('对花 / 花距进算料入参（issue #4572）', () => {
  it('「对花 = 是」⇒ 带 has_pattern + pattern_repeat（定宽买高时每幅 +1 花距）', () => {
    const params = craftCalcParamsOf(line({ craft: { hasPattern: true, patternRepeat: 0.45 } }))
    expect(params?.has_pattern).toBe(true)
    expect(params?.pattern_repeat).toBe(0.45)
  })

  it('「对花 = 否」/「未指定」⇒ 两个键都**不带**（对花为否时留着花距是自相矛盾的输入）', () => {
    expect(
      craftCalcParamsOf(line({ craft: { hasPattern: false, patternRepeat: 0.45 } }))?.has_pattern
    ).toBeUndefined()
    expect(craftCalcParamsOf(line({ craft: {} }))?.has_pattern).toBeUndefined()
    expect(craftCalcParamsOf(line({ craft: {} }))?.pattern_repeat).toBeUndefined()
  })

  it('对花 = 是但花距缺失 / 非正数 ⇒ 只带 has_pattern（**不发明花距**）', () => {
    const missing = craftCalcParamsOf(line({ craft: { hasPattern: true } }))
    expect(missing?.has_pattern).toBe(true)
    expect(missing?.pattern_repeat).toBeUndefined()
    expect(
      craftCalcParamsOf(line({ craft: { hasPattern: true, patternRepeat: 0 } }))?.pattern_repeat
    ).toBeUndefined()
    expect(
      craftCalcParamsOf(line({ craft: { hasPattern: true, patternRepeat: -1 } }))?.pattern_repeat
    ).toBeUndefined()
  })

  it('花距 / 对花开关进触发签名：改任一项 ⇒ 签名变化（否则页面留着旧口径的米数）', () => {
    const base = craftCalcSignature(
      craftCalcParamsOf(line({ craft: { hasPattern: true, patternRepeat: 0.3 } }))
    )
    const other = craftCalcSignature(
      craftCalcParamsOf(line({ craft: { hasPattern: true, patternRepeat: 0.5 } }))
    )
    const off = craftCalcSignature(craftCalcParamsOf(line({ craft: {} })))
    expect(base).not.toBe(other)
    expect(base).not.toBe(off)
  })
})

// ══════════════════════════════════════════════════════════════════════════
// issue #5202（母单 #5200 子单 C）：门幅 / 人工覆盖 / 人工加（拼次·接高·接宽）与推导方案展示
// ══════════════════════════════════════════════════════════════════════════
describe('#5202 门幅进试算入参（根因 1：签名漏项 ⇒ effect 不触发 ⇒ 静默停在旧数）', () => {
  it('带 `fabricWidth` ⇒ 请求带 `fabric_width`（引擎按 SKU 门幅算分幅与定高可行性）', () => {
    expect(craftCalcParamsOf(line({ fabricWidth: 2.8 }))?.fabric_width).toBe(2.8)
  })

  it('门幅解析不到（`null`）/ 非正数 ⇒ **不发该键**（#4877 没有缺省门幅，不猜）', () => {
    expect(craftCalcParamsOf(line({ fabricWidth: null }))?.fabric_width).toBeUndefined()
    expect(craftCalcParamsOf(line({ fabricWidth: 0 }))?.fabric_width).toBeUndefined()
    expect(craftCalcParamsOf(line({ fabricWidth: Number.NaN }))?.fabric_width).toBeUndefined()
  })

  it('改门幅 / 改加工类型 ⇒ **签名必须变**（否则改了它不重算 —— 这就是用户报的「联动死板」）', () => {
    const base = craftCalcSignature(craftCalcParamsOf(line({ fabricWidth: 2.8 })))
    const wider = craftCalcSignature(craftCalcParamsOf(line({ fabricWidth: 3.2 })))
    const mode = craftCalcSignature(
      craftCalcParamsOf(line({ fabricWidth: 2.8, cuttingModeOverride: '定宽买高' }))
    )
    expect(base).not.toBe(wider)
    expect(base).not.toBe(mode)
  })

  it('加工类型是**人工覆盖**语义：只在显式传入时才带（自动档不带 ⇒ 服务端才能给 `auto=true` 的推导）', () => {
    expect(craftCalcParamsOf(line())?.cutting_mode).toBeUndefined()
    expect(craftCalcParamsOf(line({ cuttingModeOverride: '定宽买高' }))?.cutting_mode).toBe(
      '定宽买高'
    )
    // 空串 / 纯空白 = 未指定（不落一个空键）
    expect(craftCalcParamsOf(line({ cuttingModeOverride: '  ' }))?.cutting_mode).toBeUndefined()
  })
})

describe('#5202 人工加接高 / 接宽：0 < x ≤ 0.1（契约 #5200 §三 R1），越界一律不发', () => {
  it('上限内 ⇒ 发对应键；等于上限（0.1）⇒ 也算合法（「最多 0.1 米」含 0.1）', () => {
    const params = craftCalcParamsOf(
      line({ planOverrides: { joinHeightM: 0.1, joinWidthM: 0.05 } })
    )
    expect(params?.join_height_m).toBe(0.1)
    expect(params?.join_width_m).toBe(0.05)
  })

  it('超限 / 0 / 负数 / 非数 ⇒ **不发该键**（fail-closed：不发必然 422 的值，也**不静默截断成上限**）', () => {
    expect(joinGapOf(0.2)).toBeNull()
    expect(joinGapOf(JOIN_GAP_MAX_METERS + 0.0001)).toBeNull()
    expect(joinGapOf(0)).toBeNull()
    expect(joinGapOf(-0.05)).toBeNull()
    expect(joinGapOf('')).toBeNull()
    expect(joinGapOf(undefined)).toBeNull()
    const params = craftCalcParamsOf(
      line({ planOverrides: { joinHeightM: 0.2, joinWidthM: -1 } })
    )
    expect(params?.join_height_m).toBeUndefined()
    expect(params?.join_width_m).toBeUndefined()
  })

  it('拼次人工覆盖：0~3 才发（R5：≥4 **不发明**「拼4次」，超范围一律不发）', () => {
    expect(craftCalcParamsOf(line({ planOverrides: { spliceTimes: 2 } }))?.splice_times).toBe(2)
    expect(craftCalcParamsOf(line({ planOverrides: { spliceTimes: 0 } }))?.splice_times).toBe(0)
    expect(
      craftCalcParamsOf(line({ planOverrides: { spliceTimes: 4 } }))?.splice_times
    ).toBeUndefined()
    expect(
      craftCalcParamsOf(line({ planOverrides: { spliceTimes: -1 } }))?.splice_times
    ).toBeUndefined()
  })

  it('人工加也进签名（改了它必须重算，否则页面停在旧米数）', () => {
    const base = craftCalcSignature(craftCalcParamsOf(line()))
    const spliced = craftCalcSignature(
      craftCalcParamsOf(line({ planOverrides: { spliceTimes: 1 } }))
    )
    const joined = craftCalcSignature(
      craftCalcParamsOf(line({ planOverrides: { joinHeightM: 0.1 } }))
    )
    expect(base).not.toBe(spliced)
    expect(base).not.toBe(joined)
  })
})

describe('#5202 推导方案（`data.plan`）的**展示**口径 —— 前端只渲染，不推导', () => {
  it('拼次文案：1/2/3 ⇒ 服务端选项名；0 ⇒ 不拼接；≥4 ⇒ 数字 + 需人工处理（**不发明「拼4次」**）', () => {
    expect(craftPlanSpliceText({ splice_times: 2, splice_option: '拼2次' })).toBe('拼2次')
    expect(craftPlanSpliceText({ splice_times: 0, splice_option: null })).toBe('不拼接')
    expect(craftPlanSpliceText({ splice_times: 3, splice_option: null })).toBe('拼3次')
    const many = craftPlanSpliceText({ splice_times: 4, splice_option: null })
    expect(many).toContain('4')
    expect(many).toContain('人工处理')
    expect(many).not.toContain('拼4次')
    // 缺 plan ⇒ 不拼（不是「未知」）
    expect(craftPlanSpliceText(null)).toBe('不拼接')
  })

  it('R4 判据（有没有拼接）：`≥1` ⇒ true（款式冲突由页面按 `STYLE_MIXED` 判定，本函数不碰款式真值）', () => {
    expect(craftPlanHasSplice({ splice_times: 1 })).toBe(true)
    expect(craftPlanHasSplice({ splice_times: 0 })).toBe(false)
    expect(craftPlanHasSplice(null)).toBe(false)
  })

  it('候选方案名：**键名冻结于契约 #5200 §三**；未登记的键原样显示键名（不编中文名）', () => {
    expect(craftPlanCandidateLabel('fixed_width_join_width')).toBe('倒幅 + 接宽')
    expect(craftPlanCandidateLabel('fixed_width_join_height')).toBe('倒幅 + 接高')
    expect(craftPlanCandidateLabel('brand_new_key')).toBe('brand_new_key')
    expect(Object.keys(CRAFT_PLAN_CANDIDATE_LABELS)).toHaveLength(5)
  })

  it('工艺默认名与映射表同源（工艺**不在** `plan` 里，页面只能标「系统默认 · 可改」）', () => {
    expect(CRAFT_CALC_MOUNTING_BY_CRAFT[DEFAULT_CRAFT_NAME]).toBe(CRAFT_CALC_MOUNTING)
  })
})
