// case_ids: MC-243
/**
 * `lib/order-create/calc.ts` —— 下单页切片的**算料联动**（issue #8725 第一档）。
 *
 * 单一职责：把「商家录入的一行」推导成引擎入参 / 加工信息 / 加工项数量（全纯）。
 * 本文件钉的是**取整与 fail-closed** 这两类最容易被「看起来一样」骗过去的点：
 * 加工项数量恒等于面料米数（下限 1）、越界输入一律 `null`（绝不猜一个默认值）。
 */
import { describe, it, expect } from 'vitest'
import {
  calcInputOf,
  createEmptyLineItem,
  cuttingModeOf,
  defaultRollLengthOf,
  deriveProcessingQty,
  edgeMetersOf,
  edgeUnitPriceOf,
  heightFromDoorWidth,
  nonNegativeOrNull,
  positiveOrNull,
  rollFieldsOf,
} from '@/lib/order-create/calc'

describe('calc — 加工项数量（#4882 口径：恒等于面料米数，下限 1）', () => {
  it('按米数取，不清零、不取整', () => {
    expect(deriveProcessingQty(13.8)).toBe(13.8)
    expect(deriveProcessingQty(0.5)).toBe(1)
    expect(deriveProcessingQty(0)).toBe(1)
    expect(deriveProcessingQty(120.25)).toBe(120.25)
  })
})

describe('calc — 空行初始态', () => {
  it('数量 1 / 成品帘 / 布帘 / 宽高未填（`null` 而不是 0）/ 卷数留空', () => {
    const line = createEmptyLineItem('g1')
    expect(line.groupId).toBe('g1')
    expect(line.quantity).toBe(1)
    expect(line.saleForm).toBe('成品帘')
    expect(line.curtainBody).toBe('布帘')
    expect(line.width).toBe(null)
    expect(line.height).toBe(null)
    expect(line.rollCount).toBe(null)
    expect(line.rollLengthM).toBe(null)
    expect(line.selectedProcessing).toEqual({})
    expect(line.cuttingModeTouched).toBe(false)
  })

  it('每行 id 唯一（同一组内多行不许撞 id）', () => {
    const a = createEmptyLineItem('g1')
    const b = createEmptyLineItem('g1')
    expect(a.id).not.toBe(b.id)
    expect(a.groupId).toBe(b.groupId)
  })
})

describe('calc — 越界输入 fail-closed（不猜默认值）', () => {
  it('positiveOrNull：非正 / 非有限 / null 一律 null', () => {
    expect(positiveOrNull(2.6)).toBe(2.6)
    expect(positiveOrNull(0)).toBe(null)
    expect(positiveOrNull(-1)).toBe(null)
    expect(positiveOrNull(Number.NaN)).toBe(null)
    expect(positiveOrNull(null)).toBe(null)
  })

  it('nonNegativeOrNull：0 合法、负数不合法', () => {
    expect(nonNegativeOrNull(0)).toBe(0)
    expect(nonNegativeOrNull(3)).toBe(3)
    expect(nonNegativeOrNull(-0.1)).toBe(null)
    expect(nonNegativeOrNull(null)).toBe(null)
  })

  it('heightFromDoorWidth：从门幅串里取数，取不到 ⇒ null（不回落默认门幅）', () => {
    expect(heightFromDoorWidth('2.8')).toBe(2.8)
    expect(heightFromDoorWidth('门幅 3.2 米')).toBe(3.2)
    expect(heightFromDoorWidth('')).toBe(null)
    expect(heightFromDoorWidth(undefined)).toBe(null)
    expect(heightFromDoorWidth('无')).toBe(null)
  })
})

describe('calc — 整卷售卖的落键口径（#5846）', () => {
  it('卷数为 null ⇒ 两个键都不进 payload（不是写 0）', () => {
    const line = createEmptyLineItem('g1')
    expect(rollFieldsOf(line)).toEqual({})
  })

  it('卷数填了 ⇒ 卷数一定进；卷长只在「填了」时进（与商品缺省相同也算填了）', () => {
    const line = createEmptyLineItem('g1')
    line.product = { id: 'p1', name: '布', rollLengthM: 50 } as never
    line.rollCount = 2
    expect(rollFieldsOf(line)).toEqual({ rollCount: 2 })

    line.rollLengthM = 50
    expect(rollFieldsOf(line)).toEqual({ rollCount: 2, rollLengthM: 50 })

    line.rollLengthM = 58.5
    expect(rollFieldsOf(line)).toEqual({ rollCount: 2, rollLengthM: 58.5 })
  })

  it('卷数留空但卷长被人工改过 ⇒ 只进卷长（两个键的准入条件不同）', () => {
    const line = createEmptyLineItem('g1')
    line.product = { id: 'p1', name: '布', rollLengthM: 50 } as never
    line.rollLengthM = 58.5
    expect(rollFieldsOf(line)).toEqual({ rollLengthM: 58.5 })

    line.rollLengthM = 50 // 等于商品缺省 ⇒ 不算「人工填过」
    expect(rollFieldsOf(line)).toEqual({})
  })

  it('defaultRollLengthOf：商品没有卷长 ⇒ null', () => {
    expect(defaultRollLengthOf(null)).toBe(null)
    expect(defaultRollLengthOf({ id: 'p', name: 'x' } as never)).toBe(null)
    expect(defaultRollLengthOf({ id: 'p', name: 'x', rollLengthM: 50 } as never)).toBe(50)
  })
})

describe('calc — 加工类型与配布边', () => {
  it('还没算（无规则结果 / 无试算）⇒ 回到默认档，不猜朝向', () => {
    const line = createEmptyLineItem('g1')
    expect(cuttingModeOf(line)).toBe(line.craft.cuttingMode)
  })

  it('商家人工选过 ⇒ 人工覆盖优先', () => {
    const line = createEmptyLineItem('g1')
    line.cuttingModeTouched = true
    line.craft = { ...line.craft, cuttingMode: '定宽买高' }
    expect(cuttingModeOf(line)).toBe('定宽买高')
  })

  it('配布边只对**拼色**有意义：非拼色 ⇒ 单价 null（不出这一行）', () => {
    const line = createEmptyLineItem('g1')
    line.edgeUnitPrice = 118
    expect(edgeUnitPriceOf(line)).toBe(null)
  })

  it('拼色且填了人工单价 ⇒ 用人工价；米数未填回落行米数（不是 0）', () => {
    const line = createEmptyLineItem('g1')
    line.craft = { ...line.craft, style: '拼色' }
    expect(edgeUnitPriceOf(line)).toBe(null)
    line.edgeUnitPrice = 118
    expect(edgeUnitPriceOf(line)).toBe(118)

    line.quantity = 13.8
    expect(edgeMetersOf(line)).toBe(13.8)
    line.edgeMeters = 0.6
    expect(edgeMetersOf(line)).toBe(0.6)
  })
})

describe('calc — 试算入参装配（算料联动的出口）', () => {
  it('宽高未填 ⇒ 入参里就是 null（由下游 fail-closed 拒发，前端不补默认值）', () => {
    const line = createEmptyLineItem('g1')
    const input = calcInputOf(line, null)
    expect(input.width).toBe(null)
    expect(input.height).toBe(null)
    expect(input.fabricWidth).toBe(null)
  })

  it('门幅来自所选 SKU（唯一解析点），加工类型只在人工点过时才算覆盖', () => {
    const line = createEmptyLineItem('g1')
    line.width = 6.6
    line.height = 2.6
    line.selectedSku = { id: 's1', colorId: 'c1', price: 118, doorWidth: '2.8' }
    expect(calcInputOf(line, null).fabricWidth).toBe(2.8)
    expect(calcInputOf(line, null).cuttingModeOverride).toBe(undefined)

    line.cuttingModeTouched = true
    line.craft = { ...line.craft, cuttingMode: '定宽买高' }
    expect(calcInputOf(line, null).cuttingModeOverride).toBe('定宽买高')
  })
})
