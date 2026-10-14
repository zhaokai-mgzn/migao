// case_ids: UI-061, UI-063
/**
 * 工序清单的**读面口径**唯一实现（issue #6901）—— 实例判据 + 红证。
 *
 * 为什么必须有这一层：加工单**纸面**（`ProcessingDoc`，A4）与商家端**加工单块**
 * （`ProcessingOrderBlock`：屏幕明细块 + 「复制全部」纯文本）三处都要印「这一单要做哪几道工序」，
 * 而它们各自的取数/格式化若各写一份，必然漂移（复制出去的文本与纸面给车间的清单不一致，
 * 且**没有任何东西会红**）⇒ 索引与状态文案收敛到本模块，由本文件钉住口径。
 *
 * 两条口径的边界（文件头已声明、这里逐条钉住）：
 * ① `operationsByItem()`：键 = `position.order_item_id`（与洗水码 / 批号**同一把钥匙**）；
 *    缺键 / 空工序 **不入表**（挂不上具体一套 ⇒ 不许上纸面）；同一 id 多组 ⇒ **取第一组**
 *    （宁可少印，也不许把两组缝成一份假清单）；
 * ② `operationStatusText()`：读面 `status` 是**机器键**（`pending` / `done`）⇒ 一律折成中文，
 *    未知值的形态也要如实钉住（**绝不让内部键上纸面/上屏**）。
 */
import { describe, expect, it } from 'vitest'
import { operationsByItem, operationStatusText } from '@/lib/operation-list'
import type { ProductionOperation, ProductionPosition } from '@/types'

/** 一道工序（读面形状：`logical_name` 是展示真值，`operation` 是工人端快照名，**不得**渲染） */
function buildOperation(overrides: Partial<ProductionOperation> = {}): ProductionOperation {
  return {
    id: 'op-1',
    operation: '精裁-布',
    logical_name: '精裁',
    position: '布帘',
    unit: '米',
    qty: 12.5,
    status: 'pending',
    ...overrides,
  }
}

/** 一个部位分组（读面 `positions[]` 的一项） */
function buildPosition(overrides: Partial<ProductionPosition> = {}): ProductionPosition {
  return {
    order_item_id: 'item-1',
    position_name: '布帘',
    operations: [buildOperation()],
    ...overrides,
  }
}

describe('operationsByItem — 工序清单按订单行索引（issue #6901）', () => {
  it('按 `position.order_item_id` 建索引（与洗水码 / 批号同一把钥匙）', () => {
    const index = operationsByItem([
      buildPosition({ order_item_id: 'item-1' }),
      buildPosition({
        order_item_id: 'item-2',
        operations: [buildOperation({ id: 'op-2', logical_name: '韩褶', unit: '折', qty: 52 })],
      }),
    ])
    expect([...index.keys()]).toEqual(['item-1', 'item-2'])
    expect(index.get('item-2')?.operations?.[0]?.logical_name).toBe('韩褶')
  })

  it('🔴 缺 `order_item_id` 的分组**不入表**（挂不上具体一套 ⇒ 不上纸面，不猜）', () => {
    expect(operationsByItem([buildPosition({ order_item_id: null })]).size).toBe(0)
    expect(operationsByItem([buildPosition({ order_item_id: undefined })]).size).toBe(0)
    expect(operationsByItem([buildPosition({ order_item_id: '' })]).size).toBe(0)
  })

  it('🔴 空工序 / 缺 `operations` 键的分组**不入表**（= 消费方「整块不出现」，不印空表）', () => {
    expect(operationsByItem([buildPosition({ operations: [] })]).size).toBe(0)
    expect(operationsByItem([buildPosition({ operations: undefined })]).size).toBe(0)
  })

  it('🔴 同一 `order_item_id` 多组 ⇒ **取第一组**（宁可少印，也不缝成假清单）', () => {
    const index = operationsByItem([
      buildPosition({
        order_item_id: 'item-1',
        operations: [buildOperation({ id: 'first', logical_name: '打孔' })],
      }),
      buildPosition({
        order_item_id: 'item-1',
        operations: [buildOperation({ id: 'second', logical_name: '韩褶' })],
      }),
    ])
    expect(index.size).toBe(1)
    expect(index.get('item-1')?.operations?.map((op) => op.id)).toEqual(['first'])
  })

  it('🔴 缺值入参（undefined / null / 空数组）⇒ 空表（纸面与屏幕块都走「整块不出现」）', () => {
    expect(operationsByItem(undefined).size).toBe(0)
    expect(operationsByItem(null).size).toBe(0)
    expect(operationsByItem([]).size).toBe(0)
  })

  it('🔴 红证（注入式自证）：去掉「跳过缺键 / 空工序」的守卫 ⇒ 上面两条必红', () => {
    // 修前形态 = 照单全收（旧实现若省掉守卫，缺键分组会以 `''` / `'null'` 为键入表，
    // 而消费方按 `item.id` 取 —— 取不到只是恰好不显示，遇 `order_item_id` 为空串的行
    // 却会与「订单行 id 为空」的行撞键 ⇒ 印出**挂不上任何一套**的假清单）。
    const buggy = (positions: ProductionPosition[]): Map<string, ProductionPosition> => {
      const index = new Map<string, ProductionPosition>()
      for (const position of positions) {
        // ⛔ 守卫被去掉的形态（本用例的反面对照）
        index.set(String(position.order_item_id), position)
      }
      return index
    }
    // ① 缺键分组：坏形态入表（键 `'null'` / `''`），真实现不入表 ⇒ 「不入表」那条**会红**
    expect(buggy([buildPosition({ order_item_id: null })]).size).toBe(1)
    expect(operationsByItem([buildPosition({ order_item_id: null })]).size).toBe(0)
    // ② 空工序分组：坏形态入表，真实现不入表 ⇒ 「空工序不入表」那条**会红**
    expect(buggy([buildPosition({ operations: [] })]).size).toBe(1)
    expect(operationsByItem([buildPosition({ operations: [] })]).size).toBe(0)
  })
})

describe('operationStatusText — 工序状态文案（issue #6901）', () => {
  it('读面 `done` ⇒ 「已完成」；其余（`pending` 等）⇒ 「待做」', () => {
    expect(operationStatusText('done')).toBe('已完成')
    expect(operationStatusText('pending')).toBe('待做')
  })

  it('🔴 未知取值 / 缺值：一律折「待做」，**绝不把内部键原样印出来**', () => {
    for (const unknown of ['in_progress', 'PARTIAL', 'x', '', null, undefined]) {
      const text = operationStatusText(unknown)
      expect(text).toBe('待做')
      // 反面：把机器键原样渲染 ⇒ 纸面/屏幕会出现 `in_progress` 这种工人看不懂的串
      expect(text).not.toBe(unknown)
    }
  })

  it('🔴 红证：状态文案是**封闭二态**（没有第三个出口）', () => {
    // 读面只有 `done` / 其余两种形态 ⇒ 文案集恒为这两条；将来读面新增状态时，
    // 消费方（纸面 / 加工单块）会一起落到「待做」——本断言把「封闭二态」钉住
    const texts = new Set(
      ['done', 'pending', 'in_progress', null, undefined].map((s) => operationStatusText(s))
    )
    expect(texts.size).toBe(2)
    expect(texts.has('待做')).toBe(true)
    expect(texts.has('已完成')).toBe(true)
  })
})
