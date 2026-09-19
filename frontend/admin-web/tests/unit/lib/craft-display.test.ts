// case_ids: OR-033
// 原声明 `OR-001, UI-020` 是**借用式**（issue #4431 B7 核实并替换）：OR-001 是订单列表查询、
// UI-020 是订单列表「采购明细」的**加工费**展示 —— 两条都不覆盖本文件被测行为（工艺规格展示映射）。
// 改用 **OR-033**（本 PR 新增，判据即本文件 + OrderDetailCraftSpec.test.tsx）。
/**
 * 工艺规格展示映射（设计文档 §4.9「一份 spec，三处渲染」）——
 * 这份定义被 ① 报价单 ② 订单 ③ 加工单 三处共用，故它的判据也必须覆盖三处的两种键名口径。
 *
 * 硬约束（§4.9）：缺值不渲染（键缺席 / null / 空串 / 空数组 / 非有限数 ⇒ 该行不出现），
 * 绝不出现 undefined/null/NaN，也不补默认值。
 */
import { describe, expect, it } from 'vitest'
import { craftSpecLine, craftSpecRows, isCraftSpecKey } from '@/lib/craft-display'

/** 订单/快照层口径（camelCase，§4.5）：order_items.processing_info / items_snapshot */
const orderCraftSpec = {
  curtainType: '布帘',
  craft: '韩褶',
  cuttingMode: '定高买宽',
  openCount: 2,
  isShaped: true,
  style: '拼色',
  specialOptions: ['加铅线', '双褶'],
  pleatSpacing: 0.1,
  hasPattern: true,
  patternRepeat: 0.32,
  processingMeters: 13.3,
  fabric_meters: 13.3,
  pleat_count: 52,
  per_panel_pleats: 26,
  panels: 4,
  fullness: 2,
  fullness_actual: 1.86,
}

/** 报价单口径（curtain_calc 输出，snake_case，§4.5） */
const quoteCraftSpec = {
  curtain_type: '纱帘',
  craft: '打孔',
  formula_used: 'fixed_width_pleats',
  open_count: 4,
  is_shaped: false,
  style: '单色',
  special_options: ['罗马圈'],
  pleat_spacing: 0.12,
  has_pattern: false,
  pattern_repeat: 0.4,
  processing_meters: 8.5,
  fabric_meters: 8.5,
  pleat_count: 40,
  per_panel_pleats: 10,
  panels: 3,
  fullness: 1.8,
  fullness_actual: 1.7,
}

const rowValue = (rows: ReturnType<typeof craftSpecRows>, label: string) =>
  rows.find((row) => row.label === label)?.value

describe('craftSpecRows — 订单/快照层（camelCase）', () => {
  it('按 §4.9 表渲染全部 17 个字段', () => {
    const rows = craftSpecRows(orderCraftSpec)
    expect(rows.map((row) => row.label)).toEqual([
      '部位',
      '工艺',
      '加工类型',
      '打开方式',
      '是否定型',
      '款式',
      '特殊选项',
      '总褶数',
      '折数（每片）',
      '褶距',
      '幅数',
      '理论褶倍',
      '实际褶倍',
      '面料米数',
      '加工费米数',
      '是否对花',
      '花距',
    ])
  })

  it('格式化：布尔 → 是/否、米数带单位、倍数带单位、选项数组顿号连接', () => {
    const rows = craftSpecRows(orderCraftSpec)
    expect(rowValue(rows, '是否定型')).toBe('是')
    expect(rowValue(rows, '是否对花')).toBe('是')
    expect(rowValue(rows, '褶距')).toBe('0.1米')
    expect(rowValue(rows, '花距')).toBe('0.32米')
    expect(rowValue(rows, '面料米数')).toBe('13.3米')
    expect(rowValue(rows, '加工费米数')).toBe('13.3米')
    expect(rowValue(rows, '理论褶倍')).toBe('2 倍')
    expect(rowValue(rows, '实际褶倍')).toBe('1.86 倍')
    expect(rowValue(rows, '特殊选项')).toBe('加铅线、双褶')
    expect(rowValue(rows, '加工类型')).toBe('定高买宽')
  })

  it('打开方式：1/2/3/4 → 单开/双开/三开/四开（§4.2 字段表 A；三开 = issue #4387 判据 1）', () => {
    expect(rowValue(craftSpecRows({ openCount: 1 }), '打开方式')).toBe('单开')
    expect(rowValue(craftSpecRows({ openCount: 2 }), '打开方式')).toBe('双开')
    expect(rowValue(craftSpecRows({ openCount: 3 }), '打开方式')).toBe('三开')
    expect(rowValue(craftSpecRows({ openCount: 4 }), '打开方式')).toBe('四开')
  })

  it('打开方式：未知开数如实标 N 开（不猜、不落默认值）', () => {
    expect(rowValue(craftSpecRows({ openCount: 6 }), '打开方式')).toBe('6 开')
  })
})

describe('craftSpecRows — 报价单（curtain_calc 输出，snake_case）', () => {
  it('同一份定义吃 snake_case 键（不是第二套定义）', () => {
    const rows = craftSpecRows(quoteCraftSpec)
    expect(rowValue(rows, '部位')).toBe('纱帘')
    expect(rowValue(rows, '工艺')).toBe('打孔')
    expect(rowValue(rows, '打开方式')).toBe('四开')
    expect(rowValue(rows, '是否定型')).toBe('否')
    expect(rowValue(rows, '特殊选项')).toBe('罗马圈')
    expect(rowValue(rows, '褶距')).toBe('0.12米')
    expect(rowValue(rows, '实际褶倍')).toBe('1.7 倍')
  })

  it('加工类型取 §4.2 的真值来源 formula_used：fixed_height* → 定高买宽', () => {
    expect(rowValue(craftSpecRows({ formula_used: 'fixed_height' }), '加工类型')).toBe('定高买宽')
    expect(rowValue(craftSpecRows({ formula_used: 'fixed_height_pleats' }), '加工类型')).toBe('定高买宽')
  })

  it('加工类型：fixed_width* / roman_panel → 定宽买高', () => {
    expect(rowValue(craftSpecRows({ formula_used: 'fixed_width' }), '加工类型')).toBe('定宽买高')
    expect(rowValue(craftSpecRows({ formula_used: 'fixed_width_pleats' }), '加工类型')).toBe('定宽买高')
    expect(rowValue(craftSpecRows({ formula_used: 'roman_panel' }), '加工类型')).toBe('定宽买高')
  })

  it('加工类型：未知 formula 取值 fail-closed（宁少一行，不漏内部代号给顾客）', () => {
    expect(rowValue(craftSpecRows({ formula_used: 'unknown_formula' }), '加工类型')).toBeUndefined()
    expect(craftSpecRows({ formula_used: 'unknown_formula' })).toEqual([])
  })

  it('cuttingMode 直存中文时优先于 formula_used（订单层口径）', () => {
    const rows = craftSpecRows({ cuttingMode: '定宽买高', formula_used: 'fixed_height' })
    expect(rowValue(rows, '加工类型')).toBe('定宽买高')
  })
})

describe('craftSpecRows — 缺值不渲染（§4.9 硬约束 2）', () => {
  it('键缺席 / null / 空串 / 空数组 / 非有限数 ⇒ 该行不出现', () => {
    const rows = craftSpecRows({
      curtainType: null,
      craft: '',
      cuttingMode: undefined,
      openCount: null,
      isShaped: null,
      style: '   ',
      specialOptions: [],
      pleatSpacing: Number.NaN,
      panels: Number.POSITIVE_INFINITY,
      hasPattern: undefined,
      patternRepeat: null,
    })
    expect(rows).toEqual([])
  })

  it('部分缺值 ⇒ 只渲染有值的行（存量单形态：完全没有工艺键）', () => {
    const rows = craftSpecRows({ curtainType: '布帘', colorName: '米白', sellingMethod: 'bulk_cut' })
    expect(rows).toEqual([{ label: '部位', value: '布帘' }])
  })

  it('空载荷 / 非对象 ⇒ 空数组（渲染方据此整块不出现）', () => {
    expect(craftSpecRows(null)).toEqual([])
    expect(craftSpecRows(undefined)).toEqual([])
    expect(craftSpecRows('布帘')).toEqual([])
    expect(craftSpecRows(['布帘'])).toEqual([])
    expect(craftSpecRows({})).toEqual([])
  })

  it('任何取值组合下都不会渲染出 undefined / null / NaN 字面量', () => {
    const payloads: unknown[] = [
      orderCraftSpec,
      quoteCraftSpec,
      { curtainType: undefined, craft: null, specialOptions: [null, 1, '', '  '], fullness: Number.NaN },
      { isShaped: 'maybe', hasPattern: 3, panels: {} },
      {},
    ]
    for (const payload of payloads) {
      for (const row of craftSpecRows(payload)) {
        expect(row.value).not.toMatch(/undefined|null|NaN/)
        expect(row.value.trim()).not.toBe('')
      }
    }
  })

  it('特殊选项里的非字符串项被丢弃（不渲染 [object Object] / null）', () => {
    expect(rowValue(craftSpecRows({ specialOptions: ['加铅线', null, 1, '双褶'] }), '特殊选项')).toBe('加铅线、双褶')
  })

  it('数字以字符串承载时仍按数字口径格式化（JSON 边界容错）', () => {
    expect(rowValue(craftSpecRows({ pleatSpacing: '0.1' }), '褶距')).toBe('0.1米')
    expect(rowValue(craftSpecRows({ openCount: '2' }), '打开方式')).toBe('双开')
  })
})

describe('isCraftSpecKey / craftSpecLine', () => {
  it('认两种键名口径（订单明细据此避免同一真值被重复展示）', () => {
    expect(isCraftSpecKey('craft')).toBe(true)
    expect(isCraftSpecKey('curtainType')).toBe(true)
    expect(isCraftSpecKey('curtain_type')).toBe(true)
    expect(isCraftSpecKey('processing_meters')).toBe(true)
    expect(isCraftSpecKey('processingMeters')).toBe(true)
    expect(isCraftSpecKey('colorName')).toBe(false)
    expect(isCraftSpecKey('sellingMethod')).toBe(false)
  })

  it('纯文本行形如「工艺：韩褶」（复制/打印用）', () => {
    expect(craftSpecLine({ label: '工艺', value: '韩褶' })).toBe('工艺：韩褶')
  })
})
