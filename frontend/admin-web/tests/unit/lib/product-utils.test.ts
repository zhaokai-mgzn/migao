import { describe, it, expect } from 'vitest'
// case_ids: PR-010, PR-042, PR-043, PR-044, OR-046
import { validateProductForm, derivePrice } from '@/lib/product-utils'
import type { ProductFormData, ProductColor, SellingMethod } from '@/types'

// ========== 辅助工厂函数 ==========

function baseForm(overrides?: Partial<ProductFormData>): ProductFormData {
  return {
    name: '测试商品',
    skuCode: 'SKU001',
    unit: '米',
    categoryId: 'cat-1',
    images: ['https://example.com/img.jpg'],
    price: 50,
    colors: [{ id: '1', colorName: '红色', sortOrder: 0 }],
    sellingMethods: ['bulk_cut' as SellingMethod],
    doorWidths: ['2.8米'],
    skus: [
      {
        id: '1',
        colorId: '1',
        colorName: '红色',
        doorWidth: '2.8米',
        price: 100,
        stock: 50,
        status: 'active' as const,
      },
    ],
    status: 'draft',
    ...overrides,
  }
}

// ========== validateProductForm ==========

describe('validateProductForm', () => {
  // ─── 基础：name 校验（所有状态都必填）───

  it('requires name', () => {
    const errs = validateProductForm(baseForm({ name: '' }), 'draft')
    expect(errs.name).toBe('请输入商品标题')
  })

  it('rejects name > 60 chars', () => {
    const errs = validateProductForm(
      baseForm({ name: '测'.repeat(61) }),
      'draft',
    )
    expect(errs.name).toBe('标题不超过 60 字')
  })

  it('accepts name exactly 60 chars', () => {
    const errs = validateProductForm(
      baseForm({ name: '测'.repeat(60) }),
      'draft',
    )
    expect(errs.name).toBeUndefined()
  })

  // ─── draft 模式：只校验 name ───

  it('skips all other fields in draft mode', () => {
    const errs = validateProductForm(
      baseForm({
        name: '草稿',
        skuCode: '',
        unit: '',
        categoryId: '',
        images: [],
        colors: [],
        sellingMethods: [],
        doorWidths: [],
      }),
      'draft',
    )
    // draft 模式下只有 name 是必填的
    expect(Object.keys(errs)).toEqual([])
  })

  // ─── 非 draft：必填字段 ───

  it('requires skuCode when not draft', () => {
    const errs = validateProductForm(
      baseForm({ skuCode: '' }),
      'on_sale',
    )
    expect(errs.skuCode).toBe('请输入货号')
  })

  it('requires unit when not draft', () => {
    const errs = validateProductForm(
      baseForm({ unit: '' }),
      'on_sale',
    )
    expect(errs.unit).toBe('请选择计价单位')
  })

  it('requires categoryId when not draft', () => {
    const errs = validateProductForm(
      baseForm({ categoryId: '' }),
      'on_sale',
    )
    expect(errs.categoryId).toBe('请选择商品分类')
  })

  it('requires at least 1 image when not draft', () => {
    const errs = validateProductForm(
      baseForm({ images: [] }),
      'on_sale',
    )
    expect(errs.images).toBe('请至少上传 1 张商品主图')
  })

  // ─── 颜色校验 ───

  it('requires at least 1 color when not draft', () => {
    const errs = validateProductForm(
      baseForm({ colors: [], skus: [] }),
      'on_sale',
    )
    expect(errs.colors).toBe('请至少添加 1 种颜色')
  })

  it('requires all colors to have a name', () => {
    const errs = validateProductForm(
      baseForm({
        colors: [
          { id: '1', colorName: '红色', sortOrder: 0 },
          { id: '2', colorName: '', sortOrder: 1 },
        ],
      }),
      'on_sale',
    )
    expect(errs.colors).toBe('颜色必须填写名称')
  })

  it('rejects colors with whitespace-only names', () => {
    const errs = validateProductForm(
      baseForm({
        colors: [{ id: '1', colorName: '   ', sortOrder: 0 }],
      }),
      'on_sale',
    )
    expect(errs.colors).toBe('颜色必须填写名称')
  })

  // ─── 售卖方式 / 门幅校验 ───

  it('requires at least 1 non-empty selling method when not draft', () => {
    const errs = validateProductForm(
      baseForm({ sellingMethods: ['' as SellingMethod] }),
      'on_sale',
    )
    expect(errs.sellingMethods).toBe('请至少添加 1 种售卖方式')
  })

  it('requires at least 1 non-empty door width when not draft', () => {
    const errs = validateProductForm(
      baseForm({ doorWidths: [''] }),
      'on_sale',
    )
    expect(errs.doorWidths).toBe('请至少添加 1 种规格尺寸')
  })

  // ─── SKU 校验 ───

  it('requires all SKUs to have price > 0 and stock >= 0', () => {
    const errs = validateProductForm(
      baseForm({
        skus: [
          {
            id: '1',
        colorId: '1',
            colorName: '红色',
            doorWidth: '2.8米',
            price: 0, // 价格为 0
            stock: 50,
            status: 'active' as const,
          },
        ],
      }),
      'on_sale',
    )
    expect(errs.skus).toBe('请完整填写所有 SKU 的价格与库存')
  })

  it('rejects when SKU count < expected cells', () => {
    // 2 colors × 1 width = 2 cells（组合只有 颜色 × 门幅）, but only 1 SKU
    const errs = validateProductForm(
      baseForm({
        colors: [
          { id: '1', colorName: '红色', sortOrder: 0 },
          { id: '2', colorName: '蓝色', sortOrder: 1 },
        ],
        sellingMethods: ['bulk_cut' as SellingMethod],
        doorWidths: ['2.8米'],
        skus: [
          {
            id: '1',
        colorId: '1',
            colorName: '红色',
            doorWidth: '2.8米',
            price: 100,
            stock: 50,
            status: 'active' as const,
          },
          // 缺少蓝色的 SKU
        ],
      }),
      'on_sale',
    )
    expect(errs.skus).toBe('请完整填写所有 SKU 的价格与库存')
  })

  it('passes when all SKUs are valid', () => {
    const errs = validateProductForm(
      baseForm({
        colors: [
          { id: '1', colorName: '红色', sortOrder: 0 },
          { id: '2', colorName: '蓝色', sortOrder: 1 },
        ],
        sellingMethods: ['bulk_cut' as SellingMethod],
        doorWidths: ['2.8米'],
        skus: [
          { id: '1', colorId: '1', colorName: '红色', doorWidth: '2.8米', price: 100, stock: 50, status: 'active' as const },
          { id: '2',
        colorId: '2', colorName: '蓝色', doorWidth: '2.8米', price: 80, stock: 30, status: 'active' as const },
        ],
      }),
      'on_sale',
    )
    expect(Object.keys(errs)).toEqual([])
  })

  // ─── 1 卷 = 多少米（商品货号级基础参数；PR-043）───

  it('PR-043: 卷长留空（null / undefined）**不报错** —— 未配置是合法状态', () => {
    expect(
      Object.keys(validateProductForm(baseForm({ rollLengthM: null }), 'on_sale')),
    ).toEqual([])
    expect(
      Object.keys(
        validateProductForm(baseForm({ rollLengthM: undefined }), 'on_sale'),
      ),
    ).toEqual([])
  })

  it('PR-043: 卷长填了必须 > 0（0 / 负数 / NaN 都拒绝）', () => {
    expect(
      validateProductForm(baseForm({ rollLengthM: 0 }), 'on_sale').rollLengthM,
    ).toBe('卷长必须大于 0 米')
    expect(
      validateProductForm(baseForm({ rollLengthM: -60 }), 'on_sale').rollLengthM,
    ).toBe('卷长必须大于 0 米')
    expect(
      validateProductForm(
        baseForm({ rollLengthM: Number.NaN }),
        'on_sale',
      ).rollLengthM,
    ).toBe('卷长必须大于 0 米')
  })

  it('PR-043: 卷长 > 0 通过校验', () => {
    expect(
      Object.keys(
        validateProductForm(baseForm({ rollLengthM: 60 }), 'on_sale'),
      ),
    ).toEqual([])
  })

  it('PR-043: 草稿态不校验卷长（只校验标题）', () => {
    const errs = validateProductForm(baseForm({ rollLengthM: 0 }), 'draft')
    expect(errs.rollLengthM).toBeUndefined()
  })

  // ─── 综合：全部合法 → 无错误 ───

  it('returns no errors for fully valid form (on_sale)', () => {
    const errs = validateProductForm(
      baseForm({ status: 'on_sale' }),
      'on_sale',
    )
    expect(Object.keys(errs)).toEqual([])
  })

  // ─── 边界情况 ───

  it('rejects skuCode > 30 chars', () => {
    const errs = validateProductForm(
      baseForm({ skuCode: 'A'.repeat(31) }),
      'on_sale',
    )
    expect(errs.skuCode).toBe('货号不超过 30 字')
  })

  it('handles missing colors array (undefined)', () => {
    const errs = validateProductForm(
      baseForm({ colors: undefined as unknown as ProductColor[] }),
      'on_sale',
    )
    expect(errs.colors).toBe('请至少添加 1 种颜色')
  })

  it('handles missing sellingMethods array (undefined)', () => {
    const errs = validateProductForm(
      baseForm({ sellingMethods: undefined as unknown as SellingMethod[] }),
      'on_sale',
    )
    expect(errs.sellingMethods).toBe('请至少添加 1 种售卖方式')
  })
})

// ========== derivePrice ==========

describe('derivePrice', () => {
  it('returns form.price when SKU list is empty', () => {
    expect(derivePrice([], 99)).toBe(99)
  })

  it('returns min positive SKU price', () => {
    const skus = [
      { id: '1', colorId: '1', colorName: '红', doorWidth: '2.8米', price: 100, stock: 10, status: 'active' as const },
      { id: '2',
        colorId: '1', colorName: '红', doorWidth: '3.2米', price: 80, stock: 10, status: 'active' as const },
    ]
    expect(derivePrice(skus, 0)).toBe(80)
  })

  it('filters out zero-price SKUs and returns min positive', () => {
    const skus = [
      { id: '1', colorId: '1', colorName: '红', doorWidth: '2.8米', price: 0, stock: 10, status: 'active' as const },
      { id: '2',
        colorId: '1', colorName: '红', doorWidth: '3.2米', price: 120, stock: 10, status: 'active' as const },
    ]
    expect(derivePrice(skus, 0)).toBe(120)
  })

  it('returns form.price when all SKU prices are 0', () => {
    const skus = [
      { id: '1', colorId: '1', colorName: '红', doorWidth: '2.8米', price: 0, stock: 10, status: 'active' as const },
    ]
    expect(derivePrice(skus, 50)).toBe(50)
  })
})
