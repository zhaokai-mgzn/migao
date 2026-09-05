// case_ids: CT-001, CT-002, CT-003
/**
 * CategoryTree 组件测试（issue #2905 — 分类排序重构）
 * 覆盖：扁平列表渲染、空状态、上移/下移按钮（边界禁用）、编辑/删除操作
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
  { id: 'c1', name: '窗帘', sort: 0 },
  { id: 'c2', name: '窗纱', sort: 1 },
  { id: 'c3', name: '遮光帘', sort: 2 },
]

describe('CategoryTree (#2905)', () => {
  it('空列表显示统一占位文案', () => {
    render(<CategoryTree categories={[]} />)
    expect(screen.getByText('管理商品分类，支持对分类进行新增、编辑、删除和排序')).toBeTruthy()
  })

  it('平铺渲染全部分类（无父子嵌套）', () => {
    render(<CategoryTree categories={mockCategories} />)
    expect(screen.getByText('窗帘')).toBeTruthy()
    expect(screen.getByText('窗纱')).toBeTruthy()
    expect(screen.getByText('遮光帘')).toBeTruthy()
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
    const editButtons = document.querySelectorAll('[data-testid="icon-pencil"]')
    expect(editButtons.length).toBe(3)
    fireEvent.click(editButtons[0])
    expect(onEdit).toHaveBeenCalledWith(mockCategories[0])
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
    expect(deleteButtons.length).toBe(3)
    fireEvent.click(deleteButtons[1])
    expect(onDelete).toHaveBeenCalledWith(mockCategories[1])
  })

  // ── 上下移动（issue #2905）──

  it('点击上移按钮触发 onMoveUp', () => {
    const onMoveUp = vi.fn()
    render(
      <CategoryTree
        categories={mockCategories}
        onMoveUp={onMoveUp}
      />
    )
    const upButtons = document.querySelectorAll('[data-testid="icon-chevron-up"]')
    expect(upButtons.length).toBe(3)
    fireEvent.click(upButtons[1])
    expect(onMoveUp).toHaveBeenCalledWith(mockCategories[1])
  })

  it('点击下移按钮触发 onMoveDown', () => {
    const onMoveDown = vi.fn()
    render(
      <CategoryTree
        categories={mockCategories}
        onMoveDown={onMoveDown}
      />
    )
    const downButtons = document.querySelectorAll('[data-testid="icon-chevron-down"]')
    expect(downButtons.length).toBe(3)
    fireEvent.click(downButtons[0])
    expect(onMoveDown).toHaveBeenCalledWith(mockCategories[0])
  })

  it('首行上移按钮被禁用', () => {
    render(
      <CategoryTree
        categories={mockCategories}
        onMoveUp={vi.fn()}
      />
    )
    const upButtons = document.querySelectorAll('[data-testid="icon-chevron-up"]')
    const firstBtn = upButtons[0].closest('button') as HTMLButtonElement
    const secondBtn = upButtons[1].closest('button') as HTMLButtonElement
    expect(firstBtn.disabled).toBe(true)
    expect(secondBtn.disabled).toBe(false)
  })

  it('末行下移按钮被禁用', () => {
    render(
      <CategoryTree
        categories={mockCategories}
        onMoveDown={vi.fn()}
      />
    )
    const downButtons = document.querySelectorAll('[data-testid="icon-chevron-down"]')
    const lastBtn = downButtons[2].closest('button') as HTMLButtonElement
    const middleBtn = downButtons[1].closest('button') as HTMLButtonElement
    expect(lastBtn.disabled).toBe(true)
    expect(middleBtn.disabled).toBe(false)
  })

  it('未提供 onMoveUp/onMoveDown 时不渲染移动按钮', () => {
    render(<CategoryTree categories={mockCategories} />)
    expect(document.querySelectorAll('[data-testid="icon-chevron-up"]').length).toBe(0)
    expect(document.querySelectorAll('[data-testid="icon-chevron-down"]').length).toBe(0)
  })
})