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
