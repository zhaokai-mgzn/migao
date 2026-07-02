import { describe, it, expect } from 'vitest'
import { rebuildSkus } from '@/lib/sku-utils'
import type { ProductColor, ProductSku, SellingMethod } from '@/types'

// ========== 辅助工厂函数 ==========

function color(id: number, name: string): ProductColor {
  return { id, colorName: name, sortOrder: id }
}

function sku(overrides: Partial<ProductSku> & { id: number }): ProductSku {
  return {
    colorId: 1,
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
      [color(1, '红色')],
      [SM_BULK],
      ['2.8米'],
      [],
    )

    expect(result).toHaveLength(1)
    expect(result[0]).toMatchObject({
      colorId: 1,
      colorName: '红色',
      sellingMethod: 'bulk_cut',
      doorWidth: '2.8米',
      price: 0,
      stock: 0,
      status: 'active',
    })
    // 新生成的 SKU id 是负数时间戳
    expect(result[0].id).toBeLessThan(0)
  })

  it('generates full matrix: 2 colors × 2 methods × 2 widths = 8 SKUs', () => {
    const result = rebuildSkus(
      [color(1, '红色'), color(2, '蓝色')],
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
        { colorId: 1, colorName: '红色', sellingMethod: 'bulk_cut', doorWidth: '2.8米' },
        { colorId: 1, colorName: '红色', sellingMethod: 'bulk_cut', doorWidth: '3.2米' },
        { colorId: 1, colorName: '红色', sellingMethod: 'full_roll', doorWidth: '2.8米' },
        { colorId: 1, colorName: '红色', sellingMethod: 'full_roll', doorWidth: '3.2米' },
        { colorId: 2, colorName: '蓝色', sellingMethod: 'bulk_cut', doorWidth: '2.8米' },
        { colorId: 2, colorName: '蓝色', sellingMethod: 'bulk_cut', doorWidth: '3.2米' },
        { colorId: 2, colorName: '蓝色', sellingMethod: 'full_roll', doorWidth: '2.8米' },
        { colorId: 2, colorName: '蓝色', sellingMethod: 'full_roll', doorWidth: '3.2米' },
      ]),
    )
  })

  // ─── 2. 空值过滤 ───

  it('filters out empty selling methods', () => {
    const result = rebuildSkus(
      [color(1, '红色')],
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
      [color(1, '红色')],
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
      [color(1, '红色')],
      ['' as SellingMethod, '' as SellingMethod],
      ['2.8米'],
      [],
    )

    expect(result).toHaveLength(0)
  })

  it('returns empty array when all door widths are empty', () => {
    const result = rebuildSkus(
      [color(1, '红色')],
      [SM_BULK],
      ['', ''],
      [],
    )

    expect(result).toHaveLength(0)
  })

  // ─── 3. 已有 SKU 匹配（colorId 优先）───

  it('preserves existing SKU data when matched by colorId', () => {
    const existing = [
      sku({ id: 100, colorId: 1, colorName: '红色-old', sellingMethod: SM_BULK, doorWidth: '2.8米', price: 99, stock: 5, skuCode: 'SKU001' }),
    ]

    const result = rebuildSkus(
      [color(1, '红色')],
      [SM_BULK],
      ['2.8米'],
      existing,
    )

    expect(result).toHaveLength(1)
    // 保留了已有数据
    expect(result[0].id).toBe(100)
    expect(result[0].price).toBe(99)
    expect(result[0].stock).toBe(5)
    expect(result[0].skuCode).toBe('SKU001')
    // 但 colorName 更新为当前的
    expect(result[0].colorName).toBe('红色')
  })

  // ─── 4. 已有 SKU 匹配（colorName 兜底，colorId 为 null）───

  it('falls back to colorName match when colorId is null', () => {
    const existing = [
      sku({ id: 200, colorId: 0 as unknown as number, colorName: '红色', sellingMethod: SM_BULK, doorWidth: '2.8米', price: 88 }),
    ]
    // 把 colorId 设为 null（模拟旧数据）
    existing[0].colorId = null as unknown as number

    const result = rebuildSkus(
      [color(1, '红色')],
      [SM_BULK],
      ['2.8米'],
      existing,
    )

    expect(result).toHaveLength(1)
    expect(result[0].id).toBe(200)
    expect(result[0].price).toBe(88)
  })

  // ─── 5. 部分已有 + 部分新增 ───

  it('preserves matching SKUs and creates new ones for missing combos', () => {
    const existing = [
      sku({ id: 10, colorId: 1, colorName: '红', sellingMethod: SM_BULK, doorWidth: '2.8米', price: 50 }),
    ]

    const result = rebuildSkus(
      [color(1, '红色')],
      [SM_BULK, SM_ROLL],
      ['2.8米'],
      existing,
    )

    expect(result).toHaveLength(2)

    const preserved = result.find((s) => s.id === 10)
    const newOne = result.find((s) => s.id !== 10)

    expect(preserved).toBeDefined()
    expect(preserved!.price).toBe(50)
    expect(preserved!.colorName).toBe('红色') // 更新了 colorName

    expect(newOne).toBeDefined()
    expect(newOne!.id).toBeLessThan(0) // 新生成的
    expect(newOne!.sellingMethod).toBe('full_roll')
    expect(newOne!.price).toBe(0)
    expect(newOne!.stock).toBe(0)
  })

  // ─── 6. 门幅 "门幅" 前缀兼容 ───

  it('matches "门幅2.8米" with "2.8米" (legacy format)', () => {
    const existing = [
      sku({ id: 300, colorId: 1, colorName: '红色', sellingMethod: SM_BULK, doorWidth: '门幅2.8米', price: 77 }),
    ]

    const result = rebuildSkus(
      [color(1, '红色')],
      [SM_BULK],
      ['2.8米'],
      existing,
    )

    expect(result).toHaveLength(1)
    expect(result[0].id).toBe(300)
    expect(result[0].doorWidth).toBe('门幅2.8米')
  })

  it('matches "2.8米" with "门幅2.8米" (reverse compatibility)', () => {
    // 注意：matchWidth 仅从 db（已有数据）侧去"门幅"前缀，不从 opt（选项）侧去。
    // 因此 已有 2.8米 + 选项 门幅2.8米 → 不匹配，会生成新 SKU
    const existing = [
      sku({ id: 400, colorId: 1, colorName: '红色', sellingMethod: SM_BULK, doorWidth: '2.8米', price: 66 }),
    ]

    const result = rebuildSkus(
      [color(1, '红色')],
      [SM_BULK],
      ['门幅2.8米'],
      existing,
    )

    // 当前行为：反向不匹配，生成新 SKU（保留旧数据的 doorWidth）
    expect(result).toHaveLength(1)
    // 不保留旧 id — 因为没匹配上，会生成新的
    expect(result[0].doorWidth).toBe('门幅2.8米')
  })

  // ─── 7. 边界情况 ───

  it('handles multiple colors with some existing SKUs', () => {
    const existing = [
      sku({ id: 1, colorId: 10, colorName: '白色', sellingMethod: SM_BULK, doorWidth: '2.8米', price: 10 }),
    ]

    const result = rebuildSkus(
      [color(10, '白色'), color(20, '黑色')],
      [SM_BULK],
      ['2.8米'],
      existing,
    )

    expect(result).toHaveLength(2)
    expect(result.find((s) => s.id === 1)).toBeDefined()
    expect(result.find((s) => s.id !== 1)!.price).toBe(0)
  })

  it('produces stable ordering: outer=colors, middle=methods, inner=widths', () => {
    const result = rebuildSkus(
      [color(1, '红'), color(2, '蓝')],
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
