// case_ids: OR-039, UI-076
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
import {
  buildFeeDetailDisplay,
  buildOrderFeeComposition,
  unpricedCombinationLabel,
} from '@/lib/order-fee-display'

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

/**
 * 订单级**费用构成**（issue #5843）：详情页原先「商品合计 / 金额」两列只算商品金额，
 * 而页脚「订单金额」是订单级总额（含加工费）⇒ 中间那笔加工费**一个渲染点都没有**，
 * 商家看到两个数对不上（用户 2026-10-01 报障：245.14 与 368.74 之间差 123.60）。
 *
 * 本组钉的是**构成**这一层（页面渲染由 tests/unit/pages/order-detail.test.tsx 判）：
 *   `商品合计 + 加工费 + 其它构成 === 订单金额`（差额非 0 ⇒ 显式「其它构成」解释行）
 * 三条硬口径：只读落库数不重算 · 未定价不渲染 `¥0.00` · 布料单不出现空行。
 */
describe('订单级费用构成（issue #5843）', () => {
  /** 用户报障那一单的落库形状（字段名与 `OrderItemResponse` 同源） */
  const reportedItem = {
    id: 'item-1',
    productName: '全遮光雪尼尔',
    quantity: 10.3,
    unitPrice: 23.8,
    amount: 245.14,
    subtotal: 245.14,
    processingFee: 123.6,
    processingInfo: {
      processingFeeDetail: {
        composition: '韩褶 + 定型',
        unit_price: 12,
        meters: 10.3,
        fee_source: 'matched',
        amount: 123.6,
      },
    },
  }

  it('报障单读数：加工费合计 = Σ items[].processingFee，且 商品合计 + 加工费 = 订单金额', () => {
    const composition = buildOrderFeeComposition([reportedItem], {
      goodsTotal: 245.14,
      orderTotal: 368.74,
    })

    expect(composition.processingFeeTotal).toBeCloseTo(123.6, 2)
    expect(composition.goodsTotal + composition.processingFeeTotal).toBeCloseTo(368.74, 2)
    expect(composition.remainder).toBeCloseTo(0, 2)
    expect(composition.showProcessingFee).toBe(true)
    expect(composition.showRemainder).toBe(false)
    expect(composition.visible).toBe(true)
  })

  it('行级算式沿用 OrderItemList 的实现（米数 × 单价/米 = 金额），缺值不编', () => {
    const composition = buildOrderFeeComposition([reportedItem], {
      goodsTotal: 245.14,
      orderTotal: 368.74,
    })

    expect(composition.lines).toHaveLength(1)
    expect(composition.lines[0].label).toBe('全遮光雪尼尔')
    expect(composition.lines[0].amount).toBeCloseTo(123.6, 2)
    expect(composition.lines[0].expr).toBe('10.3 米 × ¥12.00/米 = ¥123.60')
    expect(composition.lines[0].unpriced).toBe(false)

    // 缺单价 / 米数 ⇒ `expr` 为 null（宁可只显示金额，也不给对不上的算式）
    const noFormula = buildOrderFeeComposition(
      [{ ...reportedItem, processingInfo: { processingFeeDetail: { fee_source: 'matched', amount: 123.6 } } }],
      { goodsTotal: 245.14, orderTotal: 368.74 }
    )
    expect(noFormula.lines[0].expr).toBeNull()
    expect(noFormula.lines[0].amount).toBeCloseTo(123.6, 2)
  })

  it('只认落库值：单价 × 米数与行金额不一致时不重算（详情页 = 落库快照）', () => {
    const composition = buildOrderFeeComposition(
      [
        {
          ...reportedItem,
          processingInfo: {
            processingFeeDetail: {
              unit_price: 9.99,
              meters: 10.3,
              fee_source: 'manual',
              amount: 123.6,
            },
          },
        },
      ],
      { goodsTotal: 245.14, orderTotal: 368.74 }
    )

    expect(composition.processingFeeTotal).toBeCloseTo(123.6, 2) // 不是 9.99 × 10.3 = 102.90
    expect(composition.lines[0].manual).toBe(true)
  })

  it('布料单（无加工费 / 无未定价 / 无差额）⇒ 整块不渲染（没有加工是正常，不是缺失）', () => {
    const composition = buildOrderFeeComposition(
      [{ id: 'i1', productName: '素色亚麻', processingFee: 0 }],
      { goodsTotal: 1990, orderTotal: 1990 }
    )

    expect(composition.processingFeeTotal).toBe(0)
    expect(composition.lines).toEqual([])
    expect(composition.showProcessingFee).toBe(false)
    expect(composition.showRemainder).toBe(false)
    expect(composition.visible).toBe(false)
  })

  it('未定价行 ⇒ 本行标出 + 点名组合，金额按 0 计（不是「本来就不收」）', () => {
    const composition = buildOrderFeeComposition(
      [
        {
          ...reportedItem,
          processingFee: 0,
          processingInfo: {
            processingFeeDetail: {
              composition: '韩褶 + 定型',
              items: ['韩褶', '定型'],
              fee_source: 'unpriced',
              amount: 0,
            },
          },
        },
      ],
      { goodsTotal: 245.14, orderTotal: 245.14 }
    )

    expect(composition.unpricedCount).toBe(1)
    expect(composition.unpricedLabels).toEqual(['韩褶 + 定型'])
    expect(composition.lines[0].unpriced).toBe(true)
    expect(composition.lines[0].unpricedLabel).toBe('韩褶 + 定型')
    // 未定价 ⇒ 没有实收加工费 ⇒ 不渲染「加工费 ¥0.00」那一行，但整块**必须**可见（否则就是静默改钱的外观）
    expect(composition.showProcessingFee).toBe(false)
    expect(composition.visible).toBe(true)
  })

  it('未定价组合名口径 = 新增订单页 unpricedCombinationLabel（items → composition → 缺选配信息）', () => {
    expect(unpricedCombinationLabel({ items: ['韩褶', '定型'], composition: 'hanzhe+dingxing' })).toBe(
      '韩褶 + 定型'
    )
    expect(unpricedCombinationLabel({ composition: 'hanzhe+dingxing' })).toBe('hanzhe+dingxing')
    expect(unpricedCombinationLabel({ items: [], composition: '  ' })).toBe(
      '没有可匹配的组合（缺选配信息）'
    )
  })

  it('差额非 0 ⇒ 显式「其它构成」解释行（等式仍闭合）', () => {
    const composition = buildOrderFeeComposition([reportedItem], {
      goodsTotal: 245.14,
      orderTotal: 373.74,
    })

    expect(composition.remainder).toBeCloseTo(5, 2)
    expect(composition.showRemainder).toBe(true)
    expect(
      composition.goodsTotal + composition.processingFeeTotal + composition.remainder
    ).toBeCloseTo(373.74, 2)
  })

  it('订单金额未知（接口没给）⇒ 不编差额、不渲染解释行', () => {
    const composition = buildOrderFeeComposition([reportedItem], { goodsTotal: 245.14, orderTotal: null })

    expect(composition.orderTotal).toBeNull()
    expect(composition.showRemainder).toBe(false)
  })
})
