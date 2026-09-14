/**
 * SkuMatrix 组件测试
 * 覆盖：#563 — 销售属性矩阵渲染、颜色管理、SKU 表格
 * case_ids: PR-010
 */
import { render, screen, fireEvent, within } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { toast } from 'sonner'
import SkuMatrix from '@/components/products/SkuMatrix'
import type { ProductColor, ProductSku, SellingMethod } from '@/types'

// issue #3621：门幅选项/匹配口径统一用例需要断言「拒绝重复门幅」的可见提示
vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  },
}))

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
    // P0-1 回归：颜色临时 id 必须是纯整数（后端 ProductColorInput.id 为 Long，
    // 浮点字符串会导致商品创建 400「请求体格式错误或缺失」）
    expect(nextValue.colors[0].id).toMatch(/^-?\d+$/)
    expect(Number.isInteger(Number(nextValue.colors[0].id))).toBe(true)
  })

  it('有颜色数据时在颜色计数中显示数量', () => {
    const color: ProductColor = {
      id: '-1',
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
      id: '-1',
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
      id: '-1',
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
      id: '-1',
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
            id: '-100',
            colorId: '-1',
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
      id: '-1',
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
      id: '-1',
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
      { id: '-1', colorName: '黑色', remark: '', sortOrder: 0 },
      { id: '-2', colorName: '红色', remark: '', sortOrder: 1 },
      { id: '-3', colorName: '蓝色', remark: '', sortOrder: 2 },
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
      { id: '-1', colorName: '黑色', remark: '', sortOrder: 0 },
      { id: '-2', colorName: '白色', remark: '', sortOrder: 1 },
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
      { id: '-1', colorName: '黑色', remark: '', sortOrder: 0 },
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
      id: '-1',
      colorName: '红色',
      remark: '',
      sortOrder: 0,
    }
    const sku: ProductSku = {
      id: '-100',
      colorId: '-1',
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

  // ========== #2908: 校验失败提示可见性 ==========

  const skuErrorValue = {
    colors: [
      { id: '-1', colorName: '红色', remark: '', sortOrder: 0 } as ProductColor,
    ],
    sellingMethods: ['bulk_cut' as SellingMethod],
    doorWidths: ['2.8米'],
    skus: [
      {
        id: '-100',
        colorId: '-1',
        colorName: '红色',
        sellingMethod: 'bulk_cut' as SellingMethod,
        doorWidth: '2.8米',
        price: 0,
        stock: 0,
        status: 'active',
      } as ProductSku,
    ],
  }
  const SKU_ERROR = '请完整填写所有 SKU 的价格与库存'

  it('#2908 L2-01: errors.skus 存在时渲染醒目警示横幅（含未填写计数）', () => {
    render(
      <SkuMatrix
        value={skuErrorValue}
        onChange={vi.fn()}
        errors={{ skus: SKU_ERROR }}
      />
    )
    const alert = screen.getByRole('alert')
    expect(alert.textContent).toContain(SKU_ERROR)
    // 价格=0 未填写 → 计数 1 处
    expect(alert.textContent).toContain('1 处')
  })

  it('#2908 L2-02: 无校验错误时不渲染警示横幅', () => {
    render(<SkuMatrix value={skuErrorValue} onChange={vi.fn()} />)
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('#2908 L2-03: 校验失败时高亮未填写的价格单元格，正常单元格不高亮', () => {
    const { container } = render(
      <SkuMatrix
        value={skuErrorValue}
        onChange={vi.fn()}
        errors={{ skus: SKU_ERROR }}
      />
    )
    const priceInput = container.querySelector(
      'td input[type="number"]'
    ) as HTMLInputElement
    expect(priceInput.className).toContain('border-red-400')
    // 库存为 0 视为有效，不标红
    const stockInput = container.querySelectorAll('td input[type="number"]')[1]
    expect((stockInput as HTMLInputElement).className).not.toContain(
      'border-red-400'
    )
    // aria-invalid 标记
    expect(priceInput.getAttribute('aria-invalid')).toBe('true')
  })

  it('#2908 L2-04: 未触发校验（无 errors）时不因价格=0 标红', () => {
    const { container } = render(
      <SkuMatrix value={skuErrorValue} onChange={vi.fn()} />
    )
    const priceInput = container.querySelector(
      'td input[type="number"]'
    ) as HTMLInputElement
    expect(priceInput.className).not.toContain('border-red-400')
  })

  it('#2908 L2-05: SKU 行缺失（矩阵未重建）时价格与库存单元格均标红', () => {
    const { container } = render(
      <SkuMatrix
        value={{
          colors: [
            { id: '-1', colorName: '红色', remark: '', sortOrder: 0 },
          ] as ProductColor[],
          sellingMethods: ['bulk_cut' as SellingMethod],
          doorWidths: ['2.8米'],
          skus: [],
        }}
        onChange={vi.fn()}
        errors={{ skus: SKU_ERROR }}
      />
    )
    const inputs = container.querySelectorAll('td input[type="number"]')
    expect(inputs.length).toBe(2)
    inputs.forEach((i) =>
      expect((i as HTMLInputElement).className).toContain('border-red-400')
    )
  })
})

// ========== 门幅口径统一（issue #3621）==========
//
// 门幅下拉的 value 原为带单位写法（'2.8米'），而库内是裸数值（'2.8'），
// matchWidth 只容 legacy「门幅」前缀 → 同一物理门幅被判成两个组合 → 重复 SKU 行。
// 现改为「值/显示分离」（value=裸数值，label 带单位）+ 双侧归一化匹配。
// 断言口径按 tdd-iron-law §7：断言**用户可见的结果**（回显文案/单元格数值/界面未变），
// 不止断言 onChange 被调用。

describe('门幅口径统一 (#3621)', () => {
  const color3621: ProductColor = {
    id: '1',
    colorName: '红色',
    remark: '',
    sortOrder: 0,
  }

  /** 库内既有 SKU：doorWidth 是裸数值（种子/历史数据的真实写法） */
  const existingSku = (over: Partial<ProductSku> = {}): ProductSku => ({
    id: '100',
    colorId: '1',
    colorName: '红色',
    sellingMethod: 'bulk_cut' as SellingMethod,
    doorWidth: '2.8',
    price: 168,
    stock: 500,
    status: 'active',
    ...over,
  })

  it('#3621 L2-01: 存量商品回显 — 下拉值为裸数值、显示「2.8米」，每个门幅只有一个选项', () => {
    render(
      <SkuMatrix
        value={{
          colors: [color3621],
          sellingMethods: ['bulk_cut' as SellingMethod],
          doorWidths: ['2.8'],
          skus: [existingSku()],
        }}
        onChange={vi.fn()}
      />
    )

    const widthSelect = screen.getByRole('combobox', {
      name: '规格尺寸',
    }) as HTMLSelectElement

    // 值 = canonical 裸数值（与库内一致）→ 匹配不需要容错
    expect(widthSelect.value).toBe('2.8')
    // 显示 = 带单位（商家看到的文案不回退）
    expect(widthSelect.selectedOptions[0].textContent).toBe('2.8米')
    // 同一 Select 不出现同一门幅两种写法：每个物理门幅只有一个 entry
    expect(Array.from(widthSelect.options).map((o) => o.textContent)).toEqual([
      '请选择',
      '2.8米',
      '3.2米',
      '3.4米',
    ])
  })

  it('#3621 L2-02: 历史带单位写法（2.8米）回显也不产生第二种写法', () => {
    render(
      <SkuMatrix
        value={{
          colors: [color3621],
          sellingMethods: ['bulk_cut' as SellingMethod],
          // 存量表单里的历史写法（后端由 SKU 派生，两种写法都真实存在）
          doorWidths: ['2.8米'],
          skus: [existingSku({ doorWidth: '2.8米' })],
        }}
        onChange={vi.fn()}
      />
    )

    const widthSelect = screen.getByRole('combobox', {
      name: '规格尺寸',
    }) as HTMLSelectElement
    expect(widthSelect.value).toBe('2.8')
    expect(widthSelect.selectedOptions[0].textContent).toBe('2.8米')
    // 不追加第二个「2.8米」entry
    expect(
      Array.from(widthSelect.options).filter((o) => o.textContent === '2.8米')
    ).toHaveLength(1)
  })

  it('#3621 L2-03: 同一物理门幅不能再加第二个组合（拒绝 + 提示可见）', () => {
    const onChange = vi.fn()
    render(
      <SkuMatrix
        value={{
          colors: [color3621],
          sellingMethods: ['bulk_cut' as SellingMethod],
          doorWidths: ['2.8', '3.2'],
          skus: [
            existingSku(),
            existingSku({ id: '200', doorWidth: '3.2', price: 188, stock: 300 }),
          ],
        }}
        onChange={onChange}
      />
    )

    const widthSelects = screen.getAllByRole('combobox', {
      name: '规格尺寸',
    }) as HTMLSelectElement[]
    expect(widthSelects).toHaveLength(2)

    // 商家把第二行改成与第一行同一物理门幅（下拉里选「2.8米」= value 2.8）
    fireEvent.change(widthSelects[1], { target: { value: '2.8' } })

    // 结果：被拒绝并给可见提示，第二行界面**没有变化**（仍是 3.2米）
    expect(toast.warning).toHaveBeenCalledWith('当前规格尺寸已经添加过了哦')
    expect(onChange).not.toHaveBeenCalled()
    expect(widthSelects[1].value).toBe('3.2')
    expect(widthSelects[1].selectedOptions[0].textContent).toBe('3.2米')
  })

  it('#3621 L2-04: 新增不同门幅（3.4）落到 canonical 值，且矩阵新行可见', () => {
    const onChange = vi.fn()
    const { rerender } = render(
      <SkuMatrix
        value={{
          colors: [color3621],
          sellingMethods: ['bulk_cut' as SellingMethod],
          doorWidths: ['2.8', '3.2'],
          skus: [
            existingSku(),
            existingSku({ id: '200', doorWidth: '3.2' }),
          ],
        }}
        onChange={onChange}
      />
    )

    const widthSelects = screen.getAllByRole('combobox', {
      name: '规格尺寸',
    }) as HTMLSelectElement[]
    fireEvent.change(widthSelects[1], { target: { value: '3.4' } })

    expect(onChange).toHaveBeenCalledTimes(1)
    const next = onChange.mock.calls[0][0]
    // 写入侧口径统一：落表单的是 canonical 裸数值（不是 '3.4米'）
    expect(next.doorWidths).toEqual(['2.8', '3.4'])
    // 新组合已重建出 SKU 行（成果物存在于提交数据里）
    expect(
      next.skus.some(
        (s: ProductSku) => s.doorWidth === '3.4' && s.sellingMethod === 'bulk_cut'
      )
    ).toBe(true)

    // 结果可见：以新值重渲染后，下拉显示 3.4米，且矩阵里出现 3.4 价格输入框
    rerender(
      <SkuMatrix
        value={{ ...next, colors: [color3621] }}
        onChange={onChange}
      />
    )
    const afterSelects = screen.getAllByRole('combobox', {
      name: '规格尺寸',
    }) as HTMLSelectElement[]
    expect(afterSelects[1].selectedOptions[0].textContent).toBe('3.4米')
    const table = document.querySelector('table') as HTMLTableElement
    expect(within(table).getByText('3.4米')).toBeTruthy()
  })

  it('#3621 L2-05: 库内裸数值 2.8 + 表单 2.8米 → 矩阵单元格显示既有价格/库存（结果可见）', () => {
    const { container } = render(
      <SkuMatrix
        value={{
          colors: [color3621],
          sellingMethods: ['bulk_cut' as SellingMethod],
          doorWidths: ['2.8米'],
          skus: [existingSku()],
        }}
        onChange={vi.fn()}
      />
    )

    const inputs = container.querySelectorAll('td input[type="number"]')
    expect(inputs).toHaveLength(2)
    expect((inputs[0] as HTMLInputElement).value).toBe('168')
    expect((inputs[1] as HTMLInputElement).value).toBe('500')
    // 门幅列显示带单位文案（canonical 值 2.8 → 显示 2.8米，视觉不回退）
    expect(within(document.querySelector('table') as HTMLTableElement).getByText('2.8米')).toBeTruthy()
  })
})
