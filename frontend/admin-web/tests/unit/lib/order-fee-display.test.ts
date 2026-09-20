// case_ids: OR-039
/**
 * 费用明细**同一真值**（issue #4526 包 B · 设计文档 §4.3 / §9 判据 5）。
 *
 * 病根：`processingFeeDetail` 新增 `special_options[]` 后，「加工」行若仍显示整个
 * `processingFee`（= 组合那半 + 特殊选项），再单列特殊选项行 ⇒ **双算**，
 * 费用明细逐行之和 ≠ 订单金额 ⇒ 判据 5 红。
 *
 * 本模块是该拆分的**唯一实现**（页面只渲染它给出的行）：
 *   `加工` 行金额 = `processingFeeDetail.amount`（组合那半）
 *   `特殊选项` 行   = 逐项 `单价/套 × 套数`，合计 = `special_options_total`
 *   ⇒ 两半相加 === 行金额 `processingFee` === 订单金额里的那个数。
 *
 * 回退面（新增键只加不改）：服务端未返回 `special_options`（键缺席）⇒ 特殊选项块不出现，
 * 「加工」行金额回落为整个 `processingFee` —— 显示口径逐字等于改造前，不引入第三个口径。
 *
 * 红证（实现前）：`@/lib/order-fee-display` 不存在 ⇒ import 即红。
 */
import { describe, it, expect } from 'vitest'
import { buildFeeDetailDisplay } from '@/lib/order-fee-display'

describe('特殊选项行（R2：选了特殊选项 ⇒ 进费用明细）', () => {
  it('逐项 `名称 / 单价/套 × 套数`，且行金额之和 = special_options_total', () => {
    const display = buildFeeDetailDisplay({
      processingFee: 112.4,
      processingFeeDetail: {
        amount: 106.4,
        special_options: [
          { name: '加铅块', unit_price: 6, sets: 1, amount: 6, priced: true },
        ],
        special_options_total: 6,
      },
    })

    expect(display.baseAmount).toBe(106.4)
    expect(display.specialOptionsTotal).toBe(6)
    expect(display.specialOptionRows).toEqual([
      { key: '加铅块', label: '加铅块', expr: '¥6.00/套 × 1 套', amount: 6, billing: 'per_set' },
    ])
    // 同一真值：组合那半 + 特殊选项 = 行金额（订单金额里的那个数）
    expect(display.baseAmount + display.specialOptionsTotal).toBe(112.4)
  })

  it('多项 ⇒ 逐项一行（顺序 = 服务端给的 Unicode 码点升序，前端不重排、不合并）', () => {
    const display = buildFeeDetailDisplay({
      processingFee: 21,
      processingFeeDetail: {
        amount: 9,
        special_options: [
          { name: '加logo条', unit_price: 5, sets: 1, amount: 5, priced: true },
          { name: '加铅块', unit_price: 6, sets: 1, amount: 6, priced: true },
          { name: '接高', unit_price: 1, sets: 1, amount: 1, priced: true },
        ],
        special_options_total: 12,
      },
    })

    expect(display.specialOptionRows.map((r) => r.label)).toEqual(['加logo条', '加铅块', '接高'])
    expect(display.specialOptionRows.map((r) => r.amount)).toEqual([5, 6, 1])
    expect(display.specialOptionsTotal).toBe(12)
  })

  it('未定价选项 ⇒ 显式标「未定价（按 0 计）」（判据 3：不许静默按 0 收）', () => {
    const display = buildFeeDetailDisplay({
      processingFee: 106.4,
      processingFeeDetail: {
        amount: 106.4,
        special_options: [
          { name: '加铅块', unit_price: null, sets: 1, amount: 0, priced: false },
        ],
        special_options_total: 0,
      },
    })

    expect(display.specialOptionRows).toEqual([
      { key: '加铅块', label: '加铅块', expr: '未定价（按 0 计）', amount: 0, billing: 'per_set' },
    ])
    // 未定价 = 按 0 计，所以合计仍与订单金额一致（不静默改数）
    expect(display.baseAmount + display.specialOptionsTotal).toBe(106.4)
  })

  it('空数组 = 没选 ⇒ 不出现该块（缺值不渲染）', () => {
    const display = buildFeeDetailDisplay({
      processingFee: 106.4,
      processingFeeDetail: { amount: 106.4, special_options: [], special_options_total: 0 },
    })

    expect(display.specialOptionRows).toEqual([])
    expect(display.specialOptionsTotal).toBe(0)
  })

  it('回退面：服务端未返回 special_options（键缺席）⇒ 不出现该块，加工行金额 = 整个 processingFee', () => {
    const display = buildFeeDetailDisplay({
      processingFee: 106.4,
      processingFeeDetail: { amount: 106.4, unit_price: 8, meters: 13.3 },
    })

    expect(display.specialOptionRows).toEqual([])
    expect(display.baseAmount).toBe(106.4)
    expect(display.baseAmount + display.specialOptionsTotal).toBe(106.4)
  })

  it('detail 整个缺席（计价未就绪 / 旧服务端）⇒ 加工行金额 = processingFee（不抛异常）', () => {
    const display = buildFeeDetailDisplay({ processingFee: 50 })

    expect(display.specialOptionRows).toEqual([])
    expect(display.baseAmount).toBe(50)
    expect(display.specialOptionsTotal).toBe(0)
  })

  it('detail 里 amount 缺失 ⇒ 用 special_options_total 反推组合那半（仍不双算）', () => {
    const display = buildFeeDetailDisplay({
      processingFee: 112.4,
      processingFeeDetail: {
        special_options: [{ name: '加铅块', unit_price: 6, sets: 1, amount: 6, priced: true }],
        special_options_total: 6,
      },
    })

    expect(display.baseAmount).toBe(106.4)
    expect(display.baseAmount + display.specialOptionsTotal).toBe(112.4)
  })

  it('特殊选项键在但 total 键缺席 ⇒ 逐项求和当合计（不把特殊选项那半算进加工行）', () => {
    const display = buildFeeDetailDisplay({
      processingFee: 112.4,
      processingFeeDetail: {
        amount: 106.4,
        special_options: [
          { name: '加铅块', unit_price: 6, sets: 1, amount: 6, priced: true },
          { name: '接高', unit_price: 1, sets: 1, amount: 1, priced: true },
        ],
      },
    })

    expect(display.specialOptionsTotal).toBe(7)
    expect(display.baseAmount + display.specialOptionsTotal).toBe(113.4)
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// 拼色加价（#4855，用户 2026-09-21 裁定「拼色计价 = 拼色款另加 2.4 元/米」「两处都按 2.4 元/米」）
//
// 行金额自此有**三个分量**：组合那半 + 特殊选项（元/套）+ 拼色加价（元/米 × 面料米数）。
// 判据：① 三段相加 === processingFee（少算一段 = 页面显示 ≠ 落库 ⇒ 红）；
//      ② `拼1次`/`拼2次` 改按元/米计（`billing=per_meter`）⇒ **不得**读成「未定价」，也不得再显示一个元/套价；
//      ③ 键缺席（存量单 / 旧服务端）⇒ 显示口径逐字等于改造前（不引入第三个口径）。
// ══════════════════════════════════════════════════════════════════════════════

describe('拼色加价（#4855：拼色款另加 2.4 元/米）', () => {
  it('拼色款：三段相加 === 行金额；`拼1次` 显示「已并入拼色加价」且金额 0（不再显示元/套价）', () => {
    const display = buildFeeDetailDisplay({
      // 真值源 §10 算例：52 折双开 拼1次 ⇒ 组合那半 341.00 + 拼色加价 81.84 = 422.84
      processingFee: 422.84,
      processingFeeDetail: {
        amount: 341,
        special_options: [
          // 库里那笔元/套价（V82 种子 3.00）仍在，但**不再被取价使用**（改按元/米）
          { name: '拼1次', unit_price: 3, sets: 1, amount: 0, priced: true, billing: 'per_meter' },
        ],
        special_options_total: 0,
        mixed_color_surcharge: 81.84,
        mixed_color_surcharge_per_meter: 2.4,
        mixed_color_meters: 34.1,
        mixed_color_options: ['拼1次'],
      },
    })

    expect(display.mixedColorSurcharge).toBe(81.84)
    expect(display.mixedColorSurchargeExpr).toBe('34.1 米 × ¥2.40/米')
    expect(display.specialOptionRows).toEqual([
      {
        key: '拼1次',
        label: '拼1次',
        expr: '按 ¥2.40/米 计（已并入拼色加价）',
        amount: 0,
        billing: 'per_meter',
      },
    ])
    // 🔴 三段相加 === 行金额（订单金额里的那个数）
    expect(display.baseAmount + display.specialOptionsTotal + display.mixedColorSurcharge)
      .toBeCloseTo(422.84, 2)
  })

  it('单色款 / 键缺席（存量单）⇒ 加价 0、加工行 = 整个 processingFee（显示口径逐字不变）', () => {
    const legacy = buildFeeDetailDisplay({
      processingFee: 106.4,
      processingFeeDetail: { amount: 106.4, unit_price: 8, meters: 13.3 },
    })
    expect(legacy.mixedColorSurcharge).toBe(0)
    expect(legacy.baseAmount).toBe(106.4)

    const single = buildFeeDetailDisplay({
      processingFee: 133,
      processingFeeDetail: {
        amount: 133,
        special_options: [],
        special_options_total: 0,
        mixed_color_surcharge: 0,
        mixed_color_surcharge_per_meter: 2.4,
        mixed_color_meters: null,
      },
    })
    expect(single.mixedColorSurcharge).toBe(0)
    expect(single.baseAmount).toBe(133)
  })

  it('amount 缺失 ⇒ 用「行金额 − 选项合计 − 拼色加价」反推组合那半（仍不双算）', () => {
    const display = buildFeeDetailDisplay({
      processingFee: 428.84,
      processingFeeDetail: {
        special_options: [{ name: '加铅块', unit_price: 6, sets: 1, amount: 6, priced: true }],
        special_options_total: 6,
        mixed_color_surcharge: 81.84,
        mixed_color_surcharge_per_meter: 2.4,
        mixed_color_meters: 34.1,
      },
    })

    expect(display.baseAmount).toBe(341)
    expect(display.baseAmount + display.specialOptionsTotal + display.mixedColorSurcharge)
      .toBeCloseTo(428.84, 2)
  })
})
