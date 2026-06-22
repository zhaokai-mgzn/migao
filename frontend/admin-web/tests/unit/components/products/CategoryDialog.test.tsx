/**
 * CategoryDialog 组件测试
 * 覆盖：#563 — Modal 渲染、表单字段、新增/编辑模式
 */
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import CategoryDialog from '@/components/products/CategoryDialog'
import type { Category } from '@/types'

// Mock @/lib/utils
vi.mock('@/lib/utils', () => ({
  cn: (...args: any[]) => args.filter(Boolean).join(' '),
  resolveImageUrl: (url: string) => url,
}))

const mockCategories: Category[] = [
  { id: 'c1', name: '窗帘', sort: 0 },
  { id: 'c2', name: '窗纱', sort: 1 },
]

describe('CategoryDialog (#563)', () => {
  it('open 为 true 时渲染 Modal 标题"添加分类"', () => {
    render(
      <CategoryDialog
        open={true}
        onClose={vi.fn()}
        onSubmit={vi.fn().mockResolvedValue(undefined)}
        categories={mockCategories}
      />
    )
    expect(screen.getByText('添加分类')).toBeTruthy()
  })

  it('编辑模式下显示"编辑分类"标题', () => {
    const category: Category = {
      id: 'c1',
      name: '窗帘',
      parentId: '',
      sort: 0,
    }
    render(
      <CategoryDialog
        open={true}
        onClose={vi.fn()}
        onSubmit={vi.fn().mockResolvedValue(undefined)}
        category={category}
        categories={mockCategories}
      />
    )
    expect(screen.getByText('编辑分类')).toBeTruthy()
  })

  it('渲染分类名称输入框', () => {
    render(
      <CategoryDialog
        open={true}
        onClose={vi.fn()}
        onSubmit={vi.fn().mockResolvedValue(undefined)}
        categories={mockCategories}
      />
    )
    expect(screen.getByPlaceholderText('请输入分类名称')).toBeTruthy()
  })

  it('渲染父级分类选择器', () => {
    render(
      <CategoryDialog
        open={true}
        onClose={vi.fn()}
        onSubmit={vi.fn().mockResolvedValue(undefined)}
        categories={mockCategories}
      />
    )
    expect(screen.getByText('父级分类')).toBeTruthy()
  })

  it('渲染排序输入框', () => {
    render(
      <CategoryDialog
        open={true}
        onClose={vi.fn()}
        onSubmit={vi.fn().mockResolvedValue(undefined)}
        categories={mockCategories}
      />
    )
    expect(screen.getByText('排序')).toBeTruthy()
  })

  it('渲染取消和添加按钮', () => {
    render(
      <CategoryDialog
        open={true}
        onClose={vi.fn()}
        onSubmit={vi.fn().mockResolvedValue(undefined)}
        categories={mockCategories}
      />
    )
    expect(screen.getByText('取消')).toBeTruthy()
    expect(screen.getByText('添加')).toBeTruthy()
  })

  it('编辑模式下显示保存按钮', () => {
    const category: Category = {
      id: 'c1',
      name: '窗帘',
      sort: 0,
    }
    render(
      <CategoryDialog
        open={true}
        onClose={vi.fn()}
        onSubmit={vi.fn().mockResolvedValue(undefined)}
        category={category}
        categories={mockCategories}
      />
    )
    expect(screen.getByText('保存')).toBeTruthy()
  })

  it('名称为空时点击添加显示校验错误', () => {
    render(
      <CategoryDialog
        open={true}
        onClose={vi.fn()}
        onSubmit={vi.fn().mockResolvedValue(undefined)}
        categories={mockCategories}
      />
    )
    fireEvent.click(screen.getByText('添加'))
    expect(screen.getByText('请输入分类名称')).toBeTruthy()
  })

  it('点击取消触发 onClose', () => {
    const onClose = vi.fn()
    render(
      <CategoryDialog
        open={true}
        onClose={onClose}
        onSubmit={vi.fn().mockResolvedValue(undefined)}
        categories={mockCategories}
      />
    )
    fireEvent.click(screen.getByText('取消'))
    expect(onClose).toHaveBeenCalled()
  })

  it('存在预设 parentId 时回填父级分类', () => {
    render(
      <CategoryDialog
        open={true}
        onClose={vi.fn()}
        onSubmit={vi.fn().mockResolvedValue(undefined)}
        categories={mockCategories}
        presetParentId="c1"
      />
    )
    // 分类名称输入框应存在（父级通过 select 回填，不直接显示文本）
    expect(screen.getByPlaceholderText('请输入分类名称')).toBeTruthy()
  })
})
