// case_ids: OR-034
// 原声明 `OR-001, UI-020` 是**借用式**（issue #4431 B7 核实并替换）：OR-001 是订单列表查询、
// UI-020 是订单列表「采购明细」的**加工费**展示 —— 两条都不覆盖本文件被测行为（工艺规格展示映射）。
// 改用 **OR-034**（本 PR 新增，判据即本文件 + OrderDetailCraftSpec.test.tsx）。
/**
 * 工艺规格展示映射（设计文档 §4.9「一份 spec，三处渲染」）——
 * 这份定义被 ① 报价单 ② 订单 ③ 加工单 三处共用，故它的判据也必须覆盖三处的两种键名口径。
 *
 * 硬约束（§4.9）：缺值不渲染（键缺席 / null / 空串 / 空数组 / 非有限数 ⇒ 该行不出现），
 * 绝不出现 undefined/null/NaN，也不补默认值。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import {
  FORMULA_LABELS,
  TIER_LABELS,
  craftSpecLine,
  craftSpecRows,
  isCraftSpecKey,
} from '@/lib/craft-display'
import { CRAFT_CALC_FORMULA_LABELS } from '@/lib/craft-calc-request'

/** 订单/快照层口径（camelCase，§4.5）：order_items.processing_info / items_snapshot */
const orderCraftSpec = {
  curtainType: '布帘',
  craft: '韩褶',
  cuttingMode: '定高买宽',
  openCount: 2,
  isShaped: true,
  style: '拼色',
  // issue #4876：下单页表单字段同键同源（`processingInfo.formula` / `craftTier`）⇒ 展示面也读它
  formula: 'pleat',
  craftTier: 'standard',
  specialOptions: ['加铅线', '双褶'],
  pleatSpacing: 0.1,
  hasPattern: true,
  patternRepeat: 0.32,
  processingMeters: 13.3,
  fabric_meters: 13.3,
  formulaText: '韩折公式：(6.6+0.3)×2 → 52折 → 0.25×52+0.3 = 13.3米',
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
  craft_tier: 'economy',
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
  it('按 §4.9 表渲染全部 19 个字段（#4876 起「用料公式」「档位」两行随表单字段同步新增；#4880 已删「褶距」行）', () => {
    const rows = craftSpecRows(orderCraftSpec)
    expect(rows.map((row) => row.label)).toEqual([
      '部位',
      '工艺',
      '加工类型',
      '打开方式',
      '是否定型',
      '款式',
      '用料公式',
      '档位',
      '特殊选项',
      '总褶数',
      '折数（每片）',
      '幅数',
      '理论褶倍',
      '实际褶倍',
      '面料米数',
      '加工费米数',
      '算料公式',
      '是否对花',
      '花距',
    ])
  })

  it('#4876 判据：用料公式 / 档位两行**与下单页表单字段同键同源**（含 snake_case 别名）', () => {
    // ① 键 = 下单页写进 `processingInfo` 的那两个（`formula` / `craftTier`）⇒ 订单详情直读即显示
    expect(rowValue(craftSpecRows({ formula: 'fullness' }), '用料公式')).toBe('褶倍数公式（倍数法）')
    expect(rowValue(craftSpecRows({ craftTier: 'economy' }), '档位')).toBe('经济工艺')
    // ② 快照/报价单口径的 snake_case 别名同样吃（`craft_tier`）—— 一份定义吃两种键名口径
    expect(rowValue(craftSpecRows({ craft_tier: 'standard' }), '档位')).toBe('标准工艺')
    // ③ 缺值不渲染（本文件硬约束）：键缺席 ⇒ 这两行不出现
    expect(craftSpecRows({ curtainType: '布帘' }).map((r) => r.label)).toEqual(['部位'])
  })

  it('#4876 判据：未登记的键**如实回显**（不编中文名、也不静默吞掉 —— 与 cuttingMode 的 fail-closed 刻意不同）', () => {
    // 档位是**商家可增删**的配置键（`craft-calc-config.tiers`）⇒ 恒有可能出现我们没登记过的键。
    // 回显原键至少可核对；若按 `cuttingMode` 那样 fail-closed，商家会以为"这单没设过档位"。
    expect(rowValue(craftSpecRows({ craftTier: 'luxury' }), '档位')).toBe('luxury')
    expect(rowValue(craftSpecRows({ formula: 'custom_formula' }), '用料公式')).toBe('custom_formula')
  })

  it('#4876 守卫：用料公式的文案**只有一份**（craft-calc-request 的 chips 文案 = 本表）', () => {
    // 下单页 chips 与详情页展示行必须是同一个字面量来源，否则同一个字段会有两份会漂移的文案。
    expect(CRAFT_CALC_FORMULA_LABELS).toEqual(FORMULA_LABELS)
    // 且键集与算料引擎登记的公式名逐字一致（值域守卫另有 craft-calc-formula-sync.test.ts）
    expect(Object.keys(FORMULA_LABELS).sort()).toEqual(['fullness', 'pleat'])
  })

  it('#4876 守卫：档位兜底文案的**键集 = 引擎 DEFAULT_CRAFT_TIERS 的键集**（逐值读 Python 源）', () => {
    // 引擎源 = 真值源（租户配置的缺省值来自它）；本表只是**兜底文案**，但键集漂移就意味着
    // 「引擎新增一档、详情页显示裸键」，所以键集必须逐值比对（不抄现值、读源）。
    const src = readFileSync(
      resolve(__dirname, '../../../../../backend/ai-agent-service/app/tools/curtain_calc.py'),
      'utf8'
    )
    const block = src.match(/DEFAULT_CRAFT_TIERS[^=]*=\s*\{([\s\S]*?)\n\}/)
    expect(block, 'curtain_calc.py 里找不到 DEFAULT_CRAFT_TIERS（结构变了，请同步本守卫）').not.toBeNull()
    // ⚠️ 只取**顶层**键（4 空格缩进 + 紧跟 `{`）：内层的 `fullness` / `label` 是档位**属性**，不是档位键
    // （首版守卫把内层键也捞进来 ⇒ 恒红；判据必须只认它要认的那一层）。
    const keys = [...block![1].matchAll(/^\s{4}"([a-z_]+)"\s*:\s*\{/gm)].map((m) => m[1]).sort()
    expect(keys, 'DEFAULT_CRAFT_TIERS 的顶层键解析为空 —— 结构变了，请同步本守卫').not.toHaveLength(0)
    expect(Object.keys(TIER_LABELS).sort()).toEqual(keys)
  })

  it('#4876 判据：「褶距」行**整体退场**（用户 2026-09-21：「应该直接删除这个字段，要做就做干净」）', () => {
    // 前因：写侧早在 #4874 就不产出该键，展示面当时**有意保留**（缺值不渲染 ⇒ 存量单仍能看到）。
    // 用户随后裁定「做干净」⇒ 连展示行一起删：**存量单也不再显示褶距**（口子彻底关上，
    // 不再留一条只对历史数据生效的渲染分支）。
    // 🔴 红证：把 `{ label: '褶距', keys: ['pleatSpacing', 'pleat_spacing'], format: meters }`
    // 那一行加回 `CRAFT_SPEC_FIELDS`（三份都加）⇒ 本断言红。
    expect(rowValue(craftSpecRows({ pleatSpacing: 0.1 }), '褶距')).toBeUndefined()
    expect(rowValue(craftSpecRows({ pleat_spacing: 0.12 }), '褶距')).toBeUndefined()
    expect(craftSpecRows(orderCraftSpec).map((row) => row.label)).not.toContain('褶距')
  })

  it('#4546 判据：算料公式**两个别名都登记** ⇒ C 端（snake_case 数据）也渲染该行', () => {
    // 用户 2026-09-19 追加裁定「**C端也要能看到**」⇒ C 端报价卡吃 `curtain_calc` 原始输出
    // （snake_case `formula_text`）必须能取到值；订单侧吃 camelCase `formulaText`。
    // 🔴 红证：删掉 snake_case 别名 ⇒ C 端取不到值 ⇒ 本断言红。
    const formula = '韩折公式：(6.6+0.3)×2 → 52折 → 0.25×52+0.3 = 13.3米'
    expect(rowValue(craftSpecRows({ formula_text: formula }), '算料公式')).toBe(formula)
    expect(rowValue(craftSpecRows({ formulaText: formula }), '算料公式')).toBe(formula)
  })

  it('格式化：布尔 → 是/否、米数带单位、倍数带单位、选项数组顿号连接', () => {
    const rows = craftSpecRows(orderCraftSpec)
    expect(rowValue(rows, '是否定型')).toBe('是')
    expect(rowValue(rows, '是否对花')).toBe('是')
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
    // ⚠️ #4876：原来用 `pleatSpacing` 举例，该行已整体删除 ⇒ 换成同为「米数」口径的 `patternRepeat`
    // （判据本身不变：字符串承载的数字仍按数字格式化）。
    expect(rowValue(craftSpecRows({ patternRepeat: '0.32' }), '花距')).toBe('0.32米')
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
    // 算料公式是工艺键 ⇒ 不会重复落进「其它字段」原始键值兜底行（issue #4546）
    expect(isCraftSpecKey('formulaText')).toBe(true)
    expect(isCraftSpecKey('colorName')).toBe(false)
    expect(isCraftSpecKey('sellingMethod')).toBe(false)
  })

  it('纯文本行形如「工艺：韩褶」（复制/打印用）', () => {
    expect(craftSpecLine({ label: '工艺', value: '韩褶' })).toBe('工艺：韩褶')
  })
})
