// case_ids: OR-009, UI-038
/**
 * 下单页工艺规格**写侧**（issue #4375 包 4b · 设计文档 §4.2/§4.5/§4.8）。
 *
 * 两条硬约束的判据：
 * 1. **缺值不写**：用户没填 ⇒ 该键**不出现**（不写空串 / 0 / false —— 下游会当成真值）；
 * 2. **键名 camelCase**（§4.5）：订单/快照层与 Java 侧一致。
 */
import { describe, it, expect } from 'vitest'
import {
  CRAFT_OPTIONS,
  CURTAIN_TYPE_OPTIONS,
  CUTTING_MODE_OPTIONS,
  METERS_SOURCE_FOLLOW,
  METERS_SOURCE_MANUAL,
  OPEN_COUNT_OPTIONS,
  SPECIAL_OPTIONS,
  STYLE_OPTIONS,
  buildCraftSpec,
  buildEdgeLineCraftSpec,
  buildMainLineGroupKeys,
} from '@/lib/order-craft-fields'

describe('枚举清单（与库侧逐字一致）', () => {
  it('部位 = 布帘/纱帘/帘头', () => {
    expect(CURTAIN_TYPE_OPTIONS).toEqual(['布帘', '纱帘', '帘头'])
  })

  it('工艺 = 韩褶/打孔/四爪钩/穿杆/平幔（错值会让加工单取到错误工序路线）', () => {
    expect(CRAFT_OPTIONS).toEqual(['韩褶', '打孔', '四爪钩', '穿杆', '平幔'])
  })

  it('加工类型 = 定高买宽/定宽买高', () => {
    expect(CUTTING_MODE_OPTIONS).toEqual(['定高买宽', '定宽买高'])
  })

  // issue #4387 判据 1：`open_count` 是**开数（正整数）**，不是固定枚举 ——
  // 用户口径明确含**三开**，而 V63 列注释与下拉此前只有 1/2/4（三开选不出来 ⇒ 红）。
  it('打开方式 = 单开(1)/双开(2)/三开(3)/四开(4)（#4387 判据 1：候选必须含 3）', () => {
    expect(OPEN_COUNT_OPTIONS.map((o) => [o.value, o.label])).toEqual([
      [1, '单开'],
      [2, '双开'],
      [3, '三开'],
      [4, '四开'],
    ])
  })

  it('款式 = 单色/拼色', () => {
    expect(STYLE_OPTIONS).toEqual(['单色', '拼色'])
  })

  it('特殊选项 19 项，逐字等于真值源 §1 清单（选项名 = ERP 名，issue #4389）', () => {
    expect(SPECIAL_OPTIONS).toEqual([
      '余料带回-布', '余料带回-纱', '布绑带', '纱绑带', '加logo条', '加立边',
      '加花边', '拼1次', '拼2次', '拼3次', '加铅块', '接高', '双眼皮接高',
      '扣环', '抱枕', '防翘扣', '一分为二', '余料做绑带', '余料做帘头',
    ])
    expect(new Set(SPECIAL_OPTIONS).size).toBe(19)
  })

  it('特殊选项名是 join key：不得残留旧写法（与库侧差一个字 ⇒ 静默失效）', () => {
    // issue #4389：`一分二` / `余料带回(布)` / `余料带回(纱)` 是 ERP 名对齐**之前**的写法，
    // 服务端按 option_name 逐字匹配 ⇒ 写侧残留旧名 = 条件工序不加、系数静默退回 1.0。
    for (const stale of ['一分二', '余料带回(布)', '余料带回(纱)']) {
      expect(SPECIAL_OPTIONS as readonly string[]).not.toContain(stale)
    }
  })
})

describe('buildCraftSpec：缺值不写', () => {
  it('未填任何工艺 ⇒ 空对象（不写空串 / 0 / false 占位）', () => {
    expect(buildCraftSpec({})).toEqual({})
  })

  it('全填 ⇒ 逐键 camelCase 落库', () => {
    expect(
      buildCraftSpec({
        curtainType: '纱帘',
        craft: '打孔',
        cuttingMode: '定高买宽',
        openCount: 2,
        isShaped: false,
        pleatSpacing: 0.1,
        hasPattern: true,
        patternRepeat: 0.6,
        style: '拼色',
        specialOptions: ['加铅块', '拼2次'],
      })
    ).toEqual({
      curtainType: '纱帘',
      craft: '打孔',
      cuttingMode: '定高买宽',
      openCount: 2,
      isShaped: false,
      pleatSpacing: 0.1,
      hasPattern: true,
      patternRepeat: 0.6,
      style: '拼色',
      specialOptions: ['加铅块', '拼2次'],
    })
  })

  it('显式「否」是真值 ⇒ 必须写（isShaped=false / hasPattern=false 不得当成未填丢弃）', () => {
    expect(buildCraftSpec({ isShaped: false, hasPattern: false })).toEqual({
      isShaped: false,
      hasPattern: false,
    })
  })

  it('空串 / 纯空白字符串 ⇒ 不写该键', () => {
    expect(buildCraftSpec({ curtainType: '', craft: '   ', style: '' })).toEqual({})
  })

  it('数值占位 0 / NaN / 非数值 ⇒ 不写该键（0 会被下游当成真值）', () => {
    expect(
      buildCraftSpec({
        openCount: 0,
        pleatSpacing: 0,
        patternRepeat: 0,
      })
    ).toEqual({})
    expect(
      buildCraftSpec({
        openCount: Number.NaN,
        pleatSpacing: Number.POSITIVE_INFINITY,
      })
    ).toEqual({})
  })

  it('特殊选项：空数组 ⇒ 不写；空串项被丢弃', () => {
    expect(buildCraftSpec({ specialOptions: [] })).toEqual({})
    expect(buildCraftSpec({ specialOptions: ['  ', '加铅块', ''] })).toEqual({
      specialOptions: ['加铅块'],
    })
  })

  it('是否对花 = 否 ⇒ 花距无意义，不写 patternRepeat（不留自相矛盾的真值）', () => {
    expect(buildCraftSpec({ hasPattern: false, patternRepeat: 0.6 })).toEqual({
      hasPattern: false,
    })
  })

  it('是否对花 = 是但花距未填 ⇒ 只写 hasPattern（不补默认花距）', () => {
    expect(buildCraftSpec({ hasPattern: true })).toEqual({ hasPattern: true })
  })

  it('未知键不进 payload（只落白名单工艺键）', () => {
    const built = buildCraftSpec({ craft: '韩褶' } as never)
    expect(Object.keys(built)).toEqual(['craft'])
  })
})

describe('双拼（§4.8）：主布行 / 配布边行的绑组键', () => {
  it('主布行绑组键 = componentRole=主布 + craftLineId（自指）', () => {
    expect(buildMainLineGroupKeys('item-1')).toEqual({
      componentRole: '主布',
      craftLineId: 'item-1',
    })
  })

  it('配布边行 = componentRole=配布边 + craftLineId（指向主布行）+ metersSource', () => {
    expect(buildEdgeLineCraftSpec('item-1', METERS_SOURCE_FOLLOW)).toEqual({
      componentRole: '配布边',
      craftLineId: 'item-1',
      metersSource: '跟随主布',
    })
    expect(buildEdgeLineCraftSpec('item-1', METERS_SOURCE_MANUAL)).toEqual({
      componentRole: '配布边',
      craftLineId: 'item-1',
      metersSource: '人工指定',
    })
  })

  it('配布边行不携带工艺规格键（折数/开数/幅数是一扇窗的属性，不是每块布的）', () => {
    const edge = buildEdgeLineCraftSpec('item-1', METERS_SOURCE_FOLLOW)
    for (const key of ['curtainType', 'craft', 'openCount', 'isShaped', 'specialOptions']) {
      expect(edge).not.toHaveProperty(key)
    }
  })

  it('metersSource 取值逐字 = 跟随主布 / 人工指定', () => {
    expect(METERS_SOURCE_FOLLOW).toBe('跟随主布')
    expect(METERS_SOURCE_MANUAL).toBe('人工指定')
  })
})
