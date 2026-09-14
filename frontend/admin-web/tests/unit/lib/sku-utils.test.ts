import { describe, it, expect } from 'vitest'
// case_ids: PR-010
import {
  rebuildSkus,
  normalizeDoorWidth,
  sameDoorWidth,
  formatDoorWidth,
  doorWidthSelectOptions,
} from '@/lib/sku-utils'
import type { ProductColor, ProductSku, SellingMethod } from '@/types'

// ========== 辅助工厂函数 ==========

function color(id: string, name: string): ProductColor {
  return { id, colorName: name, sortOrder: Number(id) }
}

function sku(overrides: Partial<ProductSku> & { id: string }): ProductSku {
  return {
    colorId: '1',
    colorName: '红色',
    sellingMethod: 'bulk_cut' as SellingMethod,
    doorWidth: '2.8米',
    price: 100,
    stock: 10,
    status: 'active',
    ...overrides,
  }
}

const SM_BULK = 'bulk_cut' as SellingMethod
const SM_ROLL = 'full_roll' as SellingMethod

// ========== 测试用例 ==========

describe('rebuildSkus', () => {
  // ─── 1. 基础矩阵生成 ───

  it('generates 1 SKU from 1 color × 1 method × 1 width', () => {
    const result = rebuildSkus(
      [color('1', '红色')],
      [SM_BULK],
      ['2.8米'],
      [],
    )

    expect(result).toHaveLength(1)
    expect(result[0]).toMatchObject({
      colorId: '1',
      colorName: '红色',
      sellingMethod: 'bulk_cut',
      doorWidth: '2.8米',
      price: 0,
      stock: 0,
      status: 'active',
    })
    // 新生成的 SKU id 是负数时间戳（字符串形态）
    expect(Number(result[0].id)).toBeLessThan(0)
  })

  it('generates temp SKU ids as integers, not floats (P0-1: Long deserialization contract)', () => {
    // 回归：#P0-1 — 此前 id = String(-(Date.now() + Math.random())) 产出
    // "-1788388811825.4893" 这类浮点字符串，后端 ProductSkuInput.id(Long)
    // Jackson 反序列化失败 → POST /api/admin/products 400「请求体格式错误」。
    const result = rebuildSkus(
      [color('1', '红色'), color('2', '蓝色')],
      [SM_BULK, SM_ROLL],
      ['2.8米'],
      [],
    )
    expect(result).toHaveLength(4)
    for (const sku of result) {
      // 必须可被 Long 解析：纯整数字符串（可选负号 + 数字），不得含小数点
      expect(sku.id).toMatch(/^-?\d+$/)
      expect(Number.isInteger(Number(sku.id))).toBe(true)
    }
    // 唯一性：同一批次生成的临时 id 不允许重复（浮点方案依赖随机数，整数方案需自增保证）
    const ids = new Set(result.map((s) => s.id))
    expect(ids.size).toBe(result.length)
  })

  it('generates full matrix: 2 colors × 2 methods × 2 widths = 8 SKUs', () => {
    const result = rebuildSkus(
      [color('1', '红色'), color('2', '蓝色')],
      [SM_BULK, SM_ROLL],
      ['2.8米', '3.2米'],
      [],
    )

    expect(result).toHaveLength(8)

    // 验证每种组合都存在
    const combos = result.map((s) => ({
      colorId: s.colorId,
      colorName: s.colorName,
      sellingMethod: s.sellingMethod,
      doorWidth: s.doorWidth,
    }))

    expect(combos).toEqual(
      expect.arrayContaining([
        { colorId: '1', colorName: '红色', sellingMethod: 'bulk_cut', doorWidth: '2.8米' },
        { colorId: '1', colorName: '红色', sellingMethod: 'bulk_cut', doorWidth: '3.2米' },
        { colorId: '1', colorName: '红色', sellingMethod: 'full_roll', doorWidth: '2.8米' },
        { colorId: '1', colorName: '红色', sellingMethod: 'full_roll', doorWidth: '3.2米' },
        { colorId: '2', colorName: '蓝色', sellingMethod: 'bulk_cut', doorWidth: '2.8米' },
        { colorId: '2', colorName: '蓝色', sellingMethod: 'bulk_cut', doorWidth: '3.2米' },
        { colorId: '2', colorName: '蓝色', sellingMethod: 'full_roll', doorWidth: '2.8米' },
        { colorId: '2', colorName: '蓝色', sellingMethod: 'full_roll', doorWidth: '3.2米' },
      ]),
    )
  })

  // ─── 2. 空值过滤 ───

  it('filters out empty selling methods', () => {
    const result = rebuildSkus(
      [color('1', '红色')],
      [SM_BULK, '' as SellingMethod, SM_ROLL],
      ['2.8米'],
      [],
    )

    expect(result).toHaveLength(2)
    const methods = result.map((s) => s.sellingMethod)
    expect(methods).toEqual(['bulk_cut', 'full_roll'])
  })

  it('filters out empty door widths', () => {
    const result = rebuildSkus(
      [color('1', '红色')],
      [SM_BULK],
      ['2.8米', '', '3.2米'],
      [],
    )

    expect(result).toHaveLength(2)
    const widths = result.map((s) => s.doorWidth)
    expect(widths).toEqual(['2.8米', '3.2米'])
  })

  it('returns empty array when all selling methods are empty', () => {
    const result = rebuildSkus(
      [color('1', '红色')],
      ['' as SellingMethod, '' as SellingMethod],
      ['2.8米'],
      [],
    )

    expect(result).toHaveLength(0)
  })

  it('returns empty array when all door widths are empty', () => {
    const result = rebuildSkus(
      [color('1', '红色')],
      [SM_BULK],
      ['', ''],
      [],
    )

    expect(result).toHaveLength(0)
  })

  // ─── 3. 已有 SKU 匹配（colorId 优先）───

  it('preserves existing SKU data when matched by colorId', () => {
    const existing = [
      sku({ id: '100', colorId: '1', colorName: '红色-old', sellingMethod: SM_BULK, doorWidth: '2.8米', price: 99, stock: 5, skuCode: 'SKU001' }),
    ]

    const result = rebuildSkus(
      [color('1', '红色')],
      [SM_BULK],
      ['2.8米'],
      existing,
    )

    expect(result).toHaveLength(1)
    // 保留了已有数据
    expect(result[0].id).toBe('100')
    expect(result[0].price).toBe(99)
    expect(result[0].stock).toBe(5)
    expect(result[0].skuCode).toBe('SKU001')
    // 但 colorName 更新为当前的
    expect(result[0].colorName).toBe('红色')
  })

  // ─── 4. 已有 SKU 匹配（colorName 兜底，colorId 为 null）───

  it('falls back to colorName match when colorId is null', () => {
    const existing = [
      sku({ id: '200', colorId: '0' as unknown as string, colorName: '红色', sellingMethod: SM_BULK, doorWidth: '2.8米', price: 88 }),
    ]
    // 把 colorId 设为 null（模拟旧数据）
    existing[0].colorId = null as unknown as string

    const result = rebuildSkus(
      [color('1', '红色')],
      [SM_BULK],
      ['2.8米'],
      existing,
    )

    expect(result).toHaveLength(1)
    expect(result[0].id).toBe('200')
    expect(result[0].price).toBe(88)
  })

  // ─── 5. 部分已有 + 部分新增 ───

  it('preserves matching SKUs and creates new ones for missing combos', () => {
    const existing = [
      sku({ id: '10', colorId: '1', colorName: '红', sellingMethod: SM_BULK, doorWidth: '2.8米', price: 50 }),
    ]

    const result = rebuildSkus(
      [color('1', '红色')],
      [SM_BULK, SM_ROLL],
      ['2.8米'],
      existing,
    )

    expect(result).toHaveLength(2)

    const preserved = result.find((s) => s.id === '10')
    const newOne = result.find((s) => s.id !== '10')

    expect(preserved).toBeDefined()
    expect(preserved!.price).toBe(50)
    expect(preserved!.colorName).toBe('红色') // 更新了 colorName

    expect(newOne).toBeDefined()
    expect(Number(newOne!.id)).toBeLessThan(0) // 新生成的
    expect(newOne!.sellingMethod).toBe('full_roll')
    expect(newOne!.price).toBe(0)
    expect(newOne!.stock).toBe(0)
  })

  // ─── 6. 门幅 "门幅" 前缀兼容 ───

  it('matches "门幅2.8米" with "2.8米" (legacy format)', () => {
    const existing = [
      sku({ id: '300', colorId: '1', colorName: '红色', sellingMethod: SM_BULK, doorWidth: '门幅2.8米', price: 77 }),
    ]

    const result = rebuildSkus(
      [color('1', '红色')],
      [SM_BULK],
      ['2.8米'],
      existing,
    )

    expect(result).toHaveLength(1)
    expect(result[0].id).toBe('300')
    expect(result[0].doorWidth).toBe('门幅2.8米')
  })

  it('matches "2.8米" with "门幅2.8米" (reverse compatibility, issue #3621)', () => {
    // issue #3621：原 matchWidth 只从 db（已有数据）侧去「门幅」前缀，选项侧不去 →
    // 已有 2.8米 + 选项 门幅2.8米 判为不同组合，生成新 SKU。现改为双侧归一化。
    const existing = [
      sku({ id: '400', colorId: '1', colorName: '红色', sellingMethod: SM_BULK, doorWidth: '2.8米', price: 66 }),
    ]

    const result = rebuildSkus(
      [color('1', '红色')],
      [SM_BULK],
      ['门幅2.8米'],
      existing,
    )

    // 同一物理门幅 → 保留既有行（不新增）
    expect(result).toHaveLength(1)
    expect(result[0].id).toBe('400')
    expect(result[0].price).toBe(66)
  })

  // ─── 7. 边界情况 ───

  it('handles multiple colors with some existing SKUs', () => {
    const existing = [
      sku({ id: '1', colorId: '10', colorName: '白色', sellingMethod: SM_BULK, doorWidth: '2.8米', price: 10 }),
    ]

    const result = rebuildSkus(
      [color('10', '白色'), color('20', '黑色')],
      [SM_BULK],
      ['2.8米'],
      existing,
    )

    expect(result).toHaveLength(2)
    expect(result.find((s) => s.id === '1')).toBeDefined()
    expect(result.find((s) => s.id !== '1')!.price).toBe(0)
  })

  it('produces stable ordering: outer=colors, middle=methods, inner=widths', () => {
    const result = rebuildSkus(
      [color('1', '红'), color('2', '蓝')],
      [SM_BULK, SM_ROLL],
      ['2.8米', '3.2米'],
      [],
    )

    // 顺序：红-bulk-2.8, 红-bulk-3.2, 红-roll-2.8, 红-roll-3.2, 蓝-bulk-2.8, ...
    expect(result[0]).toMatchObject({ colorName: '红', sellingMethod: 'bulk_cut', doorWidth: '2.8米' })
    expect(result[1]).toMatchObject({ colorName: '红', sellingMethod: 'bulk_cut', doorWidth: '3.2米' })
    expect(result[2]).toMatchObject({ colorName: '红', sellingMethod: 'full_roll', doorWidth: '2.8米' })
    expect(result[3]).toMatchObject({ colorName: '红', sellingMethod: 'full_roll', doorWidth: '3.2米' })
    expect(result[4]).toMatchObject({ colorName: '蓝', sellingMethod: 'bulk_cut', doorWidth: '2.8米' })
    expect(result[7]).toMatchObject({ colorName: '蓝', sellingMethod: 'full_roll', doorWidth: '3.2米' })
  })
})

// ========== 门幅口径统一（issue #3621）==========
//
// 门幅在库内是裸数值（2.8），但系统里同时存在「2.8米」「门幅2.8米」写法。
// 各处匹配口径不一致 → 同一物理门幅被当成不同组合 → 前端生成 tempId 新条目 →
// 后端字面键不认 → insert 新行，同一门幅两行（uq_product_skus_combination 是字面键）。
// 核心断言：**同一物理门幅在前端只对应一个组合**；真正不同的门幅/售卖方式仍须不匹配。

describe('门幅口径统一 (#3621)', () => {
  it('库内裸数值 2.8 + 选项带单位 2.8米 → 判为同一组合（保留既有行，不新增）', () => {
    const existing = [
      sku({ id: '100', colorId: '1', colorName: '红色', sellingMethod: SM_BULK, doorWidth: '2.8', price: 99, stock: 7 }),
    ]

    const result = rebuildSkus([color('1', '红色')], [SM_BULK], ['2.8米'], existing)

    expect(result).toHaveLength(1)
    // 关键：命中的是既有行（id=100），不是新生成的 tempId 负数 id
    expect(result[0].id).toBe('100')
    expect(result[0].price).toBe(99)
    expect(result[0].stock).toBe(7)
  })

  it('库内带单位 2.8米 + 选项裸数值 2.8 → 判为同一组合（反向同样归一化）', () => {
    const existing = [
      sku({ id: '101', colorId: '1', colorName: '红色', sellingMethod: SM_BULK, doorWidth: '2.8米', price: 88 }),
    ]

    const result = rebuildSkus([color('1', '红色')], [SM_BULK], ['2.8'], existing)

    expect(result).toHaveLength(1)
    expect(result[0].id).toBe('101')
    expect(result[0].price).toBe(88)
  })

  it('反向断言：真正不同的门幅（2.8 vs 3.2）仍判为不匹配（防归一化过宽）', () => {
    const existing = [
      sku({ id: '200', colorId: '1', colorName: '红色', sellingMethod: SM_BULK, doorWidth: '3.2', price: 55 }),
    ]

    const result = rebuildSkus([color('1', '红色')], [SM_BULK], ['2.8米'], existing)

    expect(result).toHaveLength(1)
    // 不同门幅 → 必须新建（负 tempId），且不能复用 3.2 行的价格
    expect(result[0].id).not.toBe('200')
    expect(Number(result[0].id)).toBeLessThan(0)
    expect(result[0].doorWidth).toBe('2.8米')
    expect(result[0].price).toBe(0)
  })

  it('反向断言：不同售卖方式仍判为不匹配（门幅相同也不行）', () => {
    const existing = [
      sku({ id: '300', colorId: '1', colorName: '红色', sellingMethod: SM_BULK, doorWidth: '2.8', price: 66 }),
    ]

    const result = rebuildSkus([color('1', '红色')], [SM_ROLL], ['2.8米'], existing)

    expect(result).toHaveLength(1)
    expect(result[0].sellingMethod).toBe('full_roll')
    expect(result[0].id).not.toBe('300')
    expect(result[0].price).toBe(0)
  })

  it('正常化口径：只去「门幅」前缀与「米/m」后缀（不改语义、不做数值换算）', () => {
    expect(normalizeDoorWidth('2.8')).toBe('2.8')
    expect(normalizeDoorWidth('2.8米')).toBe('2.8')
    expect(normalizeDoorWidth('门幅2.8米')).toBe('2.8')
    expect(normalizeDoorWidth('2.8m')).toBe('2.8')
    expect(normalizeDoorWidth(' 2.8 M ')).toBe('2.8')
    // 反向断言：不做数值换算，2.80 与 2.8 仍是不同字符串（当前数据里两种写法不存在）
    expect(sameDoorWidth('2.8', '2.8米')).toBe(true)
    expect(sameDoorWidth('2.8', '3.2米')).toBe(false)
    expect(sameDoorWidth('', '')).toBe(false)
  })

  it('下拉选项：值用 canonical 裸数值、显示带单位，同一物理门幅只产出一个 entry', () => {
    // 表单里同时出现裸数值与带单位（存量数据 + 历史写法）时，不得产出两个选项/两种写法
    const options = doorWidthSelectOptions(['2.8', '2.8米', '门幅2.8米'])

    expect(options).toEqual([
      { value: '2.8', label: '2.8米' },
      { value: '3.2', label: '3.2米' },
      { value: '3.4', label: '3.4米' },
    ])
    // 每个物理门幅只有一个 entry
    expect(new Set(options.map((o) => o.value)).size).toBe(options.length)

    // 非预设门幅（历史数据）也要能回显，且仍是「值 canonical + 显示带单位」
    expect(doorWidthSelectOptions(['3.6'])).toContainEqual({ value: '3.6', label: '3.6米' })
  })

  it('展示文案：裸数值补「米」，带单位原样返回', () => {
    expect(formatDoorWidth('2.8')).toBe('2.8米')
    expect(formatDoorWidth('2.8米')).toBe('2.8米')
    expect(formatDoorWidth('门幅2.8米')).toBe('门幅2.8米')
  })
})
