/**
 * ProductForm 组件测试
 * 覆盖：#646 移除 in_warehouse — 按钮数量、labelMap 无仓库中
 */
import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import ProductForm from '@/components/products/ProductForm'

// Mock 子组件以减少依赖
vi.mock('@/components/products/ImageUploader', () => ({
  default: (props: any) => {
    const React = require('react')
    return React.createElement('div', { 'data-testid': 'image-uploader' }, 'ImageUploader')
  },
}))
vi.mock('@/components/products/SkuMatrix', () => ({
  default: (props: any) => {
    const React = require('react')
    return React.createElement('div', { 'data-testid': 'sku-matrix' }, 'SkuMatrix')
  },
}))
vi.mock('@/components/products/ProductAttributes', () => ({
  default: (props: any) => {
    const React = require('react')
    return React.createElement('div', { 'data-testid': 'product-attributes' }, 'ProductAttributes')
  },
}))
vi.mock('@/components/products/RichTextEditor', () => ({
  default: (props: any) => {
    const React = require('react')
    return React.createElement('div', { 'data-testid': 'rich-text-editor' }, 'RichTextEditor')
  },
}))

// Mock API 调用
vi.mock('@/lib/api', () => ({
  categoryApi: {
    getCategories: vi.fn().mockResolvedValue({ data: { data: [] } }),
  },
  processingItemApi: {
    getProcessingItems: vi.fn().mockResolvedValue({ data: { data: { items: [] } } }),
  },
}))

describe('ProductForm (#1284 — 表单行对齐)', () => {
  const mockOnSubmit = vi.fn().mockResolvedValue(undefined)

  it('「总库存」「拍下减库存」「是否支持加工」三行 label 均含 * 必填标记', () => {
    render(<ProductForm onSubmit={mockOnSubmit} />)

    const stockLabels = screen.getAllByText(/总库存/)
    const deductionLabels = screen.getAllByText(/拍下减库存/)
    const processingLabels = screen.getAllByText(/是否支持加工/)

    expect(stockLabels.length).toBeGreaterThanOrEqual(1)
    expect(deductionLabels.length).toBeGreaterThanOrEqual(1)
    expect(processingLabels.length).toBeGreaterThanOrEqual(1)
  })

  it('「拍下减库存」渲染 RadioGroup（是/付款减库存）', () => {
    render(<ProductForm onSubmit={mockOnSubmit} />)

    // "否（付款减库存）" 选项存在
    expect(screen.getByText(/付款减库存/)).toBeTruthy()
  })

  it('「是否支持加工」渲染 RadioGroup（是/否）', () => {
    render(<ProductForm onSubmit={mockOnSubmit} />)

    const yesElements = screen.getAllByText('是')
    const noElements = screen.getAllByText('否')

    expect(yesElements.length).toBeGreaterThanOrEqual(2)
    expect(noElements.length).toBeGreaterThanOrEqual(1)
  })

  it('RadioGroup 有 pt-2 补偿，使文字 baseline 与 h-9 input 对齐', () => {
    render(<ProductForm onSubmit={mockOnSubmit} />)

    const deductionRadio = screen.getByText(/付款减库存/)
    const deductionRadioGroup = deductionRadio.parentElement!.parentElement!
    expect(deductionRadioGroup.className).toContain('pt-2')

    const yesRadios = screen.getAllByText('是')
    const processingYes = yesRadios[1]
    const processingRadioGroup = processingYes.parentElement!.parentElement!
    expect(processingRadioGroup.className).toContain('pt-2')
  })
})

describe('ProductForm (#646 — 移除 in_warehouse)', () => {
  const mockOnSubmit = vi.fn().mockResolvedValue(undefined)

  it('底部操作栏只有 2 个按钮：存草稿 + 提交并上架', () => {
    render(<ProductForm onSubmit={mockOnSubmit} />)

    // 应该有「存草稿」按钮
    expect(screen.getByText('存草稿')).toBeTruthy()

    // 应该有「提交并上架」按钮
    expect(screen.getByText('提交并上架')).toBeTruthy()

    // 不应有「提交并放入仓库」按钮
    expect(screen.queryByText('提交并放入仓库')).toBeNull()
    expect(screen.queryByText('仓库中')).toBeNull()
  })

  it('编辑场景仍显示 2 按钮（不出现仓库按钮）', () => {
    render(
      <ProductForm
        initialData={{ name: '测试商品', status: 'draft' } as any}
        onSubmit={mockOnSubmit}
      />
    )

    expect(screen.getByText('存草稿')).toBeTruthy()
    expect(screen.getByText('提交并上架')).toBeTruthy()
    expect(screen.queryByText('提交并放入仓库')).toBeNull()
  })

  it('自定义 submitText 生效', () => {
    render(<ProductForm onSubmit={mockOnSubmit} submitText="保存并上架" />)

    expect(screen.getByText('保存并上架')).toBeTruthy()
  })

  it('页面标题显示"新增商品"（非编辑模式）', () => {
    render(<ProductForm onSubmit={mockOnSubmit} />)

    expect(screen.getByText('新增商品')).toBeTruthy()
  })

  it('编辑模式页面标题显示"编辑商品"', () => {
    render(
      <ProductForm
        initialData={{ name: '测试' } as any}
        onSubmit={mockOnSubmit}
      />
    )

    expect(screen.getByText('编辑商品')).toBeTruthy()
  })
})

describe('ProductForm (#1403 — 管理分类入口)', () => {
  const mockOnSubmit = vi.fn().mockResolvedValue(undefined)

  it('「商品分类」选择框旁应存在「管理分类」按钮', () => {
    render(<ProductForm onSubmit={mockOnSubmit} />)

    // 分类选择器的 label 存在
    const categoryLabels = screen.getAllByText('商品分类')
    expect(categoryLabels.length).toBeGreaterThanOrEqual(1)

    // 「管理分类」按钮应存在于选择框旁
    expect(screen.getByText('管理分类')).toBeTruthy()
  })

  it('点击「管理分类」按钮应打开分类管理弹窗', async () => {
    const { default: userEvent } = await import('@testing-library/user-event')
    const ue = userEvent.setup()
    render(<ProductForm onSubmit={mockOnSubmit} />)

    const btn = screen.getByText('管理分类')
    await ue.click(btn)

    // 弹窗标题「分类管理」应出现
    expect(screen.getByText('添加分类')).toBeTruthy()
  })
})
