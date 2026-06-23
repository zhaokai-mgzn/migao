/**
 * SkuMatrix 组件测试
 * 覆盖：#563 — 销售属性矩阵渲染、颜色管理、SKU 表格
 */
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import SkuMatrix from '@/components/products/SkuMatrix'
import type { ProductColor, ProductSku, SellingMethod } from '@/types'

// Mock @/lib/utils (cn + resolveImageUrl)
vi.mock('@/lib/utils', () => ({
  cn: (...args: any[]) => args.filter(Boolean).join(' '),
  resolveImageUrl: (url: string) => url,
}))

const createDefaultValue = () => ({
  colors: [] as ProductColor[],
  sellingMethods: [] as SellingMethod[],
  doorWidths: [] as string[],
  skus: [] as ProductSku[],
})

describe('SkuMatrix (#563)', () => {
  it('渲染销售属性标题', () => {
    render(
      <SkuMatrix
        value={createDefaultValue()}
        onChange={vi.fn()}
      />
    )
    expect(screen.getByText('销售属性')).toBeTruthy()
  })

  it('空值状态下显示占位提示', () => {
    render(
      <SkuMatrix
        value={createDefaultValue()}
        onChange={vi.fn()}
      />
    )
    expect(
      screen.getByText('请先完善颜色分类、售卖方式、规格尺寸')
    ).toBeTruthy()
  })

  it('渲染颜色分类区块并显示"添加颜色分类"按钮', () => {
    render(
      <SkuMatrix
        value={createDefaultValue()}
        onChange={vi.fn()}
      />
    )
    expect(screen.getByText('颜色分类')).toBeTruthy()
    expect(screen.getByText('添加颜色分类')).toBeTruthy()
  })

  it('渲染售卖方式区块', () => {
    render(
      <SkuMatrix
        value={createDefaultValue()}
        onChange={vi.fn()}
      />
    )
    expect(screen.getByText('售卖方式')).toBeTruthy()
  })

  it('渲染规格尺寸区块', () => {
    render(
      <SkuMatrix
        value={createDefaultValue()}
        onChange={vi.fn()}
      />
    )
    expect(screen.getByText('规格尺寸')).toBeTruthy()
  })

  it('渲染销售规格表头', () => {
    render(
      <SkuMatrix
        value={createDefaultValue()}
        onChange={vi.fn()}
      />
    )
    expect(screen.getByText('销售规格')).toBeTruthy()
  })

  it('渲染批量填写工具栏', () => {
    render(
      <SkuMatrix
        value={createDefaultValue()}
        onChange={vi.fn()}
      />
    )
    expect(screen.getByText('批量填写')).toBeTruthy()
  })

  it('渲染预设颜色展开按钮', () => {
    render(
      <SkuMatrix
        value={createDefaultValue()}
        onChange={vi.fn()}
      />
    )
    expect(screen.getByText('▸ 展开预设颜色')).toBeTruthy()
  })

  it('渲染批量输入颜色按钮', () => {
    render(
      <SkuMatrix
        value={createDefaultValue()}
        onChange={vi.fn()}
      />
    )
    expect(screen.getByText('▸ 批量输入颜色')).toBeTruthy()
  })

  it('点击添加颜色分类触发 onChange 并增加颜色', () => {
    const onChange = vi.fn()
    render(
      <SkuMatrix
        value={createDefaultValue()}
        onChange={onChange}
      />
    )
    fireEvent.click(screen.getByText('添加颜色分类'))
    expect(onChange).toHaveBeenCalledTimes(1)
    const nextValue = onChange.mock.calls[0][0]
    expect(nextValue.colors).toHaveLength(1)
    expect(nextValue.colors[0].colorName).toBe('')
  })

  it('有颜色数据时在颜色计数中显示数量', () => {
    const color: ProductColor = {
      id: -1,
      colorName: '红色',
      remark: '',
      sortOrder: 0,
    }
    render(
      <SkuMatrix
        value={{ ...createDefaultValue(), colors: [color] }}
        onChange={vi.fn()}
      />
    )
    // 颜色分类标题旁显示 (1)
    expect(screen.getByText('(1)')).toBeTruthy()
  })

  it('展开预设颜色面板', () => {
    render(
      <SkuMatrix
        value={createDefaultValue()}
        onChange={vi.fn()}
      />
    )
    fireEvent.click(screen.getByText('▸ 展开预设颜色'))
    // 点击后按钮文本变为收起
    expect(screen.getByText('▾ 收起预设颜色')).toBeTruthy()
  })

  it('展开批量输入颜色面板', () => {
    render(
      <SkuMatrix
        value={createDefaultValue()}
        onChange={vi.fn()}
      />
    )
    fireEvent.click(screen.getByText('▸ 批量输入颜色'))
    expect(screen.getByText('▾ 收起批量输入')).toBeTruthy()
    // textarea 和添加按钮出现
    expect(screen.getByPlaceholderText(/每行一个颜色名称/)).toBeTruthy()
    expect(screen.getByText('添加颜色')).toBeTruthy()
  })

  it('颜色名称不为空时不显示错误', () => {
    const color: ProductColor = {
      id: -1,
      colorName: '蓝色',
      remark: '',
      sortOrder: 0,
    }
    render(
      <SkuMatrix
        value={{ ...createDefaultValue(), colors: [color] }}
        onChange={vi.fn()}
      />
    )
    // 有颜色名时输入框应有值
    const input = screen.getByDisplayValue('蓝色')
    expect(input).toBeTruthy()
  })

  it('排序按钮可切换排序模式', () => {
    render(
      <SkuMatrix
        value={createDefaultValue()}
        onChange={vi.fn()}
      />
    )
    // "排序"文本出现在多处（颜色排序按钮 + RowSelectorSection 占位），取第一个
    const sortBtns = screen.getAllByText('排序')
    fireEvent.click(sortBtns[0])
    expect(screen.getByText('完成排序')).toBeTruthy()
  })

  it('有完整 SKU 数据时渲染 SKU 表格', () => {
    const color: ProductColor = {
      id: -1,
      colorName: '红色',
      remark: '',
      sortOrder: 0,
    }
    const sku: ProductSku = {
      id: -100,
      colorId: -1,
      colorName: '红色',
      sellingMethod: 'bulk_cut' as SellingMethod,
      doorWidth: '2.8米',
      price: 100,
      stock: 50,
      status: 'active',
    }
    render(
      <SkuMatrix
        value={{
          colors: [color],
          sellingMethods: ['bulk_cut' as SellingMethod],
          doorWidths: ['2.8米'],
          skus: [sku],
        }}
        onChange={vi.fn()}
      />
    )
    // SKU 表格应渲染（不再显示占位提示）
    expect(
      screen.queryByText('请先完善颜色分类、售卖方式、规格尺寸')
    ).toBeNull()
    // 表格中显示颜色名称
    expect(screen.getByText('红色')).toBeTruthy()
  })
})
