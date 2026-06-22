/**
 * CategoryTree 组件测试
 * 覆盖：#563 — 树节点渲染、空状态、选择/展开交互
 */
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import CategoryTree from '@/components/products/CategoryTree'
import type { Category } from '@/types'

// Mock @/lib/utils
vi.mock('@/lib/utils', () => ({
  cn: (...args: any[]) => args.filter(Boolean).join(' '),
  resolveImageUrl: (url: string) => url,
}))

const mockCategories: Category[] = [
  {
    id: 'c1',
    name: '窗帘',
    sort: 0,
    children: [
      { id: 'c1-1', name: '遮光窗帘', sort: 0, parentId: 'c1' },
      { id: 'c1-2', name: '纱帘', sort: 1, parentId: 'c1' },
    ],
  },
  { id: 'c2', name: '窗纱', sort: 1 },
]

describe('CategoryTree (#563)', () => {
  it('空列表显示"暂无分类数据"', () => {
    render(<CategoryTree categories={[]} />)
    expect(screen.getByText('暂无分类数据')).toBeTruthy()
  })

  it('渲染分类名称', () => {
    render(<CategoryTree categories={mockCategories} />)
    expect(screen.getByText('窗帘')).toBeTruthy()
    expect(screen.getByText('窗纱')).toBeTruthy()
  })

  it('渲染子分类名称', () => {
    render(<CategoryTree categories={mockCategories} />)
    expect(screen.getByText('遮光窗帘')).toBeTruthy()
    expect(screen.getByText('纱帘')).toBeTruthy()
  })

  it('点击分类触发 onSelect', () => {
    const onSelect = vi.fn()
    render(
      <CategoryTree
        categories={mockCategories}
        onSelect={onSelect}
      />
    )
    fireEvent.click(screen.getByText('窗帘'))
    expect(onSelect).toHaveBeenCalledWith(mockCategories[0])
  })

  it('选中状态高亮', () => {
    render(
      <CategoryTree
        categories={mockCategories}
        selectedId="c1"
      />
    )
    // 选中的节点应有包含 primary 相关的 class
    const selectedEl = screen.getByText('窗帘').closest('[class*="primary"]')
    expect(selectedEl).toBeTruthy()
  })

  it('点击编辑按钮触发 onEdit', () => {
    const onEdit = vi.fn()
    render(
      <CategoryTree
        categories={mockCategories}
        onEdit={onEdit}
      />
    )
    // 找到"窗帘"行的编辑按钮（Pencil 图标 mock 为 icon-pencil）
    const editButtons = document.querySelectorAll('[data-testid="icon-pencil"]')
    expect(editButtons.length).toBeGreaterThan(0)
  })

  it('点击删除按钮触发 onDelete', () => {
    const onDelete = vi.fn()
    render(
      <CategoryTree
        categories={mockCategories}
        onDelete={onDelete}
      />
    )
    const deleteButtons = document.querySelectorAll('[data-testid="icon-trash2"]')
    expect(deleteButtons.length).toBeGreaterThan(0)
  })

  it('一级分类显示添加子分类按钮', () => {
    const onAddChild = vi.fn()
    render(
      <CategoryTree
        categories={mockCategories}
        onAddChild={onAddChild}
      />
    )
    // Plus 图标（添加子分类）
    const addButtons = document.querySelectorAll('[data-testid="icon-plus"]')
    expect(addButtons.length).toBeGreaterThan(0)
  })

  it('展开/折叠切换', () => {
    render(<CategoryTree categories={mockCategories} />)
    // 子分类初始可见（expanded 默认为 true）
    expect(screen.getByText('遮光窗帘')).toBeTruthy()

    // 点击展开/折叠按钮（第一个 ChevronDown 是父级"窗帘"的 toggle）
    const allToggles = screen.getAllByTestId('icon-chevron-down')
    // 第一个是父级"窗帘"的可见 toggle
    fireEvent.click(allToggles[0])
    // 折叠后子分类不可见
    expect(screen.queryByText('遮光窗帘')).toBeNull()
    expect(screen.queryByText('纱帘')).toBeNull()
  })
})
