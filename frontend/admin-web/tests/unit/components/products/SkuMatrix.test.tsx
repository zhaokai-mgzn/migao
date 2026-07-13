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

  // ========== #1286: z-index / 层级修复 ==========

  it('#1286 L2-01: 颜色删除按钮 z-index (z-40) 高于色板 popover (z-30)', () => {
    const color: ProductColor = {
      id: -1,
      colorName: '黑色',
      remark: '',
      sortOrder: 0,
    }
    render(
      <SkuMatrix
        value={{ ...createDefaultValue(), colors: [color] }}
        onChange={vi.fn()}
      />
    )
    const deleteBtn = screen.getByTitle('删除')
    expect(deleteBtn.className).toContain('z-40')
    expect(deleteBtn.className).toContain('relative')
  })

  it('#1286 L2-01: 售卖方式与规格尺寸删除按钮也有 z-40', () => {
    const color: ProductColor = {
      id: -1,
      colorName: '黑色',
      remark: '',
      sortOrder: 0,
    }
    render(
      <SkuMatrix
        value={{
          ...createDefaultValue(),
          colors: [color],
          sellingMethods: ['bulk_cut' as SellingMethod],
          doorWidths: ['2.8米'],
          skus: [{
            id: -100,
            colorId: -1,
            colorName: '黑色',
            sellingMethod: 'bulk_cut' as SellingMethod,
            doorWidth: '2.8米',
            price: 100,
            stock: 50,
            status: 'active',
          }],
        }}
        onChange={vi.fn()}
      />
    )
    const deleteBtns = screen.getAllByTitle('删除')
    // 颜色 + 售卖方式 + 规格尺寸 = 3 个删除按钮
    expect(deleteBtns).toHaveLength(3)
    deleteBtns.forEach((btn) => {
      expect(btn.className).toContain('z-40')
    })
  })

  it('#1286 L2-03: 删除按钮 DOM 不在色板 popover overlay 容器内', () => {
    const color: ProductColor = {
      id: -1,
      colorName: '黑色',
      remark: '',
      sortOrder: 0,
    }
    render(
      <SkuMatrix
        value={{ ...createDefaultValue(), colors: [color] }}
        onChange={vi.fn()}
      />
    )
    const deleteBtn = screen.getByTitle('删除')
    const dialog = deleteBtn.closest('[role="dialog"]')
    expect(dialog).toBeNull()
  })

  it('#1286 L2-02: 色板 popover 默认不渲染（关闭状态）', () => {
    const color: ProductColor = {
      id: -1,
      colorName: '黑色',
      remark: '',
      sortOrder: 0,
    }
    render(
      <SkuMatrix
        value={{ ...createDefaultValue(), colors: [color] }}
        onChange={vi.fn()}
      />
    )
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('#1286 L3-01: 添加颜色 → 立即删除 → 该行被移除', () => {
    const onChange = vi.fn()
    render(
      <SkuMatrix
        value={createDefaultValue()}
        onChange={onChange}
      />
    )
    fireEvent.click(screen.getByText('添加颜色分类'))
    expect(onChange).toHaveBeenCalledTimes(1)
    const afterAdd = onChange.mock.calls[0][0]
    expect(afterAdd.colors).toHaveLength(1)

    onChange.mockClear()
    render(
      <SkuMatrix
        value={{ ...createDefaultValue(), colors: afterAdd.colors }}
        onChange={onChange}
      />
    )
    const deleteBtn = screen.getByTitle('删除')
    fireEvent.click(deleteBtn)
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange.mock.calls[0][0].colors).toHaveLength(0)
  })

  it('#1286 L3-02: 添加 3 行 → 删除中间行 → 其余行保留', () => {
    const colors: ProductColor[] = [
      { id: -1, colorName: '黑色', remark: '', sortOrder: 0 },
      { id: -2, colorName: '红色', remark: '', sortOrder: 1 },
      { id: -3, colorName: '蓝色', remark: '', sortOrder: 2 },
    ]
    const onChange = vi.fn()
    render(
      <SkuMatrix
        value={{ ...createDefaultValue(), colors }}
        onChange={onChange}
      />
    )
    const deleteBtns = screen.getAllByTitle('删除')
    expect(deleteBtns).toHaveLength(3)

    fireEvent.click(deleteBtns[1])
    expect(onChange).toHaveBeenCalledTimes(1)
    const afterDelete = onChange.mock.calls[0][0]
    expect(afterDelete.colors).toHaveLength(2)
    expect(afterDelete.colors[0].colorName).toBe('黑色')
    expect(afterDelete.colors[1].colorName).toBe('蓝色')
  })

  it('#1286 L3-03: 色板展开状态下删除其他行不受影响', () => {
    const colors: ProductColor[] = [
      { id: -1, colorName: '黑色', remark: '', sortOrder: 0 },
      { id: -2, colorName: '白色', remark: '', sortOrder: 1 },
    ]
    const onChange = vi.fn()
    render(
      <SkuMatrix
        value={{ ...createDefaultValue(), colors }}
        onChange={onChange}
      />
    )
    const swatchBtns = screen.getAllByTitle('选择主色')
    fireEvent.click(swatchBtns[0])
    expect(screen.getByRole('dialog')).toBeTruthy()

    const deleteBtns = screen.getAllByTitle('删除')
    fireEvent.click(deleteBtns[1])
    expect(onChange).toHaveBeenCalledTimes(1)
    const afterDelete = onChange.mock.calls[0][0]
    expect(afterDelete.colors).toHaveLength(1)
    expect(afterDelete.colors[0].colorName).toBe('黑色')
  })

  it('#1286 L3-04: 仅剩 1 行时删除按钮可见且可点击', () => {
    const colors: ProductColor[] = [
      { id: -1, colorName: '黑色', remark: '', sortOrder: 0 },
    ]
    const onChange = vi.fn()
    render(
      <SkuMatrix
        value={{ ...createDefaultValue(), colors }}
        onChange={onChange}
      />
    )
    const deleteBtn = screen.getByTitle('删除')
    expect(deleteBtn).toBeTruthy()
    expect(deleteBtn.className).toContain('z-40')

    fireEvent.click(deleteBtn)
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange.mock.calls[0][0].colors).toHaveLength(0)
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
