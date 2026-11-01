// case_ids: CT-001, CT-002, CT-003, UI-147
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { findEmptyDataAssertions } from '../../../scripts/read-failure-empty-state-scan.mjs'
import userEvent from '@testing-library/user-event'

// ===== Mock categoryApi =====
const mockGetCategories = vi.fn()
const mockCreateCategory = vi.fn()
const mockUpdateCategory = vi.fn()
const mockDeleteCategory = vi.fn()
const mockMoveCategory = vi.fn()

vi.mock('@/lib/api', () => ({
  categoryApi: {
    getCategories: (...args: any[]) => mockGetCategories(...args),
    createCategory: (...args: any[]) => mockCreateCategory(...args),
    updateCategory: (...args: any[]) => mockUpdateCategory(...args),
    deleteCategory: (...args: any[]) => mockDeleteCategory(...args),
    moveCategory: (...args: any[]) => mockMoveCategory(...args),
  },
}))

// ===== Mock CategoryTree（扁平列表 + 上移/下移，issue #2905）=====
const mockCategoryTreeProps = vi.fn()
vi.mock('@/components/products/CategoryTree', () => ({
  default: (props: any) => {
    mockCategoryTreeProps(props)
    return (
      <div data-testid="category-tree">
        {props.categories.map((c: any) => (
          <div key={c.id} data-testid={`tree-item-${c.id}`}>
            <span>{c.name}</span>
            <button data-testid={`edit-${c.id}`} onClick={() => props.onEdit(c)}>
              编辑
            </button>
            <button data-testid={`delete-${c.id}`} onClick={() => props.onDelete(c)}>
              删除
            </button>
            <button data-testid={`move-up-${c.id}`} onClick={() => props.onMoveUp(c)}>
              上移
            </button>
            <button data-testid={`move-down-${c.id}`} onClick={() => props.onMoveDown(c)}>
              下移
            </button>
          </div>
        ))}
      </div>
    )
  },
}))

// ===== Mock CategoryDialog =====
const mockCategoryDialogProps = vi.fn()
vi.mock('@/components/products/CategoryDialog', () => ({
  default: (props: any) => {
    mockCategoryDialogProps(props)
    if (!props.open) return null
    return (
      <div data-testid="category-dialog" role="dialog">
        <h2>{props.category ? '编辑分类' : '添加分类'}</h2>
        <button data-testid="dialog-submit" onClick={() => props.onSubmit({ name: '新分类' })}>
          提交
        </button>
        <button data-testid="dialog-close" onClick={props.onClose}>
          关闭
        </button>
      </div>
    )
  },
}))

// ===== Mock UI components =====
vi.mock('@/components/ui', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>()
  return {
    // issue #7007：**先摊开真原语，再覆盖**（`...actual` 在前 ⇒ 显式 mock 仍然赢）。
    // 此前这里是**整模块** mock 且不合并真值，只列被替身的几个原语 ⇒ 页面一旦用上
    // **当时不存在的原语**（本轮加了 PageHeader / PageCard / SearchPanel）就报
    // `No "PageHeader" export is defined on the "@/components/ui" mock` ——
    // 报错离病灶很远（本轮 144 条红的根因，与页面改动对错无关）。
    // 摊开真值后，新增原语不必再逐个补 mock。口径与同目录
    // `production-remnants-paging.test.tsx` 既有写法同源。
    ...actual,
  Button: ({ children, onClick, variant, loading, disabled, ...props }: any) => (
    <button
      onClick={onClick}
      data-variant={variant}
      data-loading={loading ? 'true' : 'false'}
      disabled={disabled || loading}
      {...props}
    >
      {children}
    </button>
  ),
  Modal: ({ open, onClose, title, children, footer }: any) =>
    open ? (
      <div data-testid="modal" role="dialog">
        <h2>{title}</h2>
        {children}
        <div data-testid="modal-footer">{footer}</div>
      </div>
    ) : null,
  Loading: ({ text, size }: any) => (
    <div data-testid="loading" data-size={size}>
      {text}
    </div>
  ),
  }
})

import CategoriesPage from '@/app/(dashboard)/categories/page'

const mockCategories = [
  { id: '1', name: '窗帘', sort: 0 },
  { id: '3', name: '卷帘', sort: 1 },
]

describe('CategoriesPage', () => {
  const user = userEvent.setup()

  beforeEach(() => {
    vi.clearAllMocks()
    mockGetCategories.mockResolvedValue({
      data: { data: mockCategories },
    })
  })

  // ── Header ──

  it('should render page title and subtitle', async () => {
    render(<CategoriesPage />)
    await waitFor(() => {
      expect(screen.getByText('分类管理')).toBeInTheDocument()
    })
    expect(screen.getByText('管理商品分类：新增、编辑、删除和排序')).toBeInTheDocument()
  })

  it('should render add category button', async () => {
    render(<CategoriesPage />)
    await waitFor(() => {
      expect(screen.getByText('添加分类')).toBeInTheDocument()
    })
  })

  // ── Loading state ──

  it('should show loading state initially', () => {
    mockGetCategories.mockImplementation(() => new Promise(() => {}))
    render(<CategoriesPage />)
    expect(screen.getByTestId('loading')).toBeInTheDocument()
    expect(screen.getByText('加载中…')).toBeInTheDocument()
  })

  // ── Empty state ──

  it('should show empty state when no categories', async () => {
    mockGetCategories.mockResolvedValue({ data: { data: [] } })
    render(<CategoriesPage />)
    await waitFor(() => {
      // 🔴 2026-10-16（issue #7007）改判：空态**不再复读副标题**。
      // 旧判据数的是「同一句副标题出现 2 次」（header + 空态）—— 那正是 §31 P2 要治的
      // 「信息不重复」，而它把重复**钉成了契约**（改对反而红）。
      // 新判据强度不变、且不依赖重复：空态**在**（专属锚点）+ 树**不在**（真值分支）。
      expect(screen.getByTestId('categories-empty')).toBeInTheDocument()
      expect(screen.queryByTestId('category-tree')).not.toBeInTheDocument()
    })
  })

  // ── Categories loaded ──

  it('should load categories on mount', async () => {
    render(<CategoriesPage />)
    await waitFor(() => {
      expect(mockGetCategories).toHaveBeenCalledTimes(1)
    })
  })

  it('should render category list with loaded data', async () => {
    render(<CategoriesPage />)
    await waitFor(() => {
      expect(screen.getByTestId('category-tree')).toBeInTheDocument()
    })
    await waitFor(() => {
      expect(screen.getByTestId('tree-item-1')).toBeInTheDocument()
      expect(screen.getByTestId('tree-item-3')).toBeInTheDocument()
    })
  })

  it('should pass categories to CategoryTree', async () => {
    render(<CategoriesPage />)
    await waitFor(() => {
      expect(mockCategoryTreeProps).toHaveBeenCalledWith(
        expect.objectContaining({ categories: mockCategories })
      )
    })
  })

  it('should pass move handlers to CategoryTree', async () => {
    render(<CategoriesPage />)
    await waitFor(() => {
      expect(mockCategoryTreeProps).toHaveBeenCalledWith(
        expect.objectContaining({
          onMoveUp: expect.any(Function),
          onMoveDown: expect.any(Function),
        })
      )
    })
  })

  // ── Add category dialog ──

  it('should open add dialog when clicking add button', async () => {
    render(<CategoriesPage />)
    await waitFor(() => {
      expect(screen.getByText('添加分类')).toBeInTheDocument()
    })
    const addBtn = screen.getByRole('button', { name: /添加分类/ })
    await user.click(addBtn)
    await waitFor(() => {
      expect(screen.getByTestId('category-dialog')).toBeInTheDocument()
      expect(screen.getByRole('heading', { name: '添加分类' })).toBeInTheDocument()
    })
  })

  it('should close dialog when onClose is called', async () => {
    render(<CategoriesPage />)
    await waitFor(() => {
      expect(screen.getByText('添加分类')).toBeInTheDocument()
    })
    await user.click(screen.getByText('添加分类'))
    await waitFor(() => {
      expect(screen.getByTestId('category-dialog')).toBeInTheDocument()
    })
    await user.click(screen.getByTestId('dialog-close'))
    await waitFor(() => {
      expect(screen.queryByTestId('category-dialog')).not.toBeInTheDocument()
    })
  })

  // ── Edit category dialog ──

  it('should open edit dialog when clicking edit on a category', async () => {
    render(<CategoriesPage />)
    await waitFor(() => {
      expect(screen.getByTestId('edit-1')).toBeInTheDocument()
    })
    await user.click(screen.getByTestId('edit-1'))
    await waitFor(() => {
      expect(screen.getByTestId('category-dialog')).toBeInTheDocument()
      expect(screen.getByText('编辑分类')).toBeInTheDocument()
    })
  })

  it('should pass editingCategory to dialog', async () => {
    render(<CategoriesPage />)
    await waitFor(() => {
      expect(screen.getByTestId('edit-1')).toBeInTheDocument()
    })
    await user.click(screen.getByTestId('edit-1'))
    await waitFor(() => {
      expect(mockCategoryDialogProps).toHaveBeenCalledWith(
        expect.objectContaining({ category: mockCategories[0] })
      )
    })
  })

  // ── CRUD operations ──

  it('should call createCategory on dialog submit when adding', async () => {
    mockCreateCategory.mockResolvedValue({ data: { data: { id: '4', name: '新分类' } } })
    render(<CategoriesPage />)
    await waitFor(() => {
      expect(screen.getByText('添加分类')).toBeInTheDocument()
    })
    await user.click(screen.getByText('添加分类'))
    await waitFor(() => {
      expect(screen.getByTestId('dialog-submit')).toBeInTheDocument()
    })
    await user.click(screen.getByTestId('dialog-submit'))
    await waitFor(() => {
      expect(mockCreateCategory).toHaveBeenCalledWith(
        expect.objectContaining({ name: '新分类' })
      )
    })
  })

  it('should call updateCategory on dialog submit when editing', async () => {
    mockUpdateCategory.mockResolvedValue({ data: { data: mockCategories[0] } })
    render(<CategoriesPage />)
    await waitFor(() => {
      expect(screen.getByTestId('edit-1')).toBeInTheDocument()
    })
    await user.click(screen.getByTestId('edit-1'))
    await waitFor(() => {
      expect(screen.getByTestId('dialog-submit')).toBeInTheDocument()
    })
    await user.click(screen.getByTestId('dialog-submit'))
    await waitFor(() => {
      expect(mockUpdateCategory).toHaveBeenCalledWith('1', expect.objectContaining({ name: '新分类' }))
    })
  })

  // ── Move handlers（issue #2905）──

  it('should call moveCategory("up") and reload when moving up', async () => {
    mockMoveCategory.mockResolvedValue({ data: {} })
    render(<CategoriesPage />)
    await waitFor(() => {
      expect(screen.getByTestId('move-up-1')).toBeInTheDocument()
    })
    await user.click(screen.getByTestId('move-up-1'))
    await waitFor(() => {
      expect(mockMoveCategory).toHaveBeenCalledWith('1', 'up')
    })
    // 移动后重新拉取列表
    await waitFor(() => {
      expect(mockGetCategories).toHaveBeenCalledTimes(2)
    })
  })

  it('should call moveCategory("down") and reload when moving down', async () => {
    mockMoveCategory.mockResolvedValue({ data: {} })
    render(<CategoriesPage />)
    await waitFor(() => {
      expect(screen.getByTestId('move-down-3')).toBeInTheDocument()
    })
    await user.click(screen.getByTestId('move-down-3'))
    await waitFor(() => {
      expect(mockMoveCategory).toHaveBeenCalledWith('3', 'down')
    })
    await waitFor(() => {
      expect(mockGetCategories).toHaveBeenCalledTimes(2)
    })
  })

  // ── Delete confirmation modal ──

  it('should show delete modal when onDelete is triggered', async () => {
    render(<CategoriesPage />)
    await waitFor(() => {
      expect(screen.getByTestId('delete-1')).toBeInTheDocument()
    })
    await user.click(screen.getByTestId('delete-1'))
    await waitFor(() => {
      expect(screen.getByTestId('modal')).toBeInTheDocument()
      expect(screen.getByRole('heading', { name: '确认删除' })).toBeInTheDocument()
    })
  })

  it('should display category name in delete confirmation', async () => {
    render(<CategoriesPage />)
    await waitFor(() => {
      expect(screen.getByTestId('delete-1')).toBeInTheDocument()
    })
    await user.click(screen.getByTestId('delete-1'))
    await waitFor(() => {
      const modal = screen.getByTestId('modal')
      expect(modal).toBeInTheDocument()
      // The modal body contains the category name in a span with class "font-medium"
      const nameSpans = modal.querySelectorAll('span.font-medium')
      expect(nameSpans.length).toBeGreaterThan(0)
    })
  })

  it('should not show children warning in delete modal (父子概念移除)', async () => {
    render(<CategoriesPage />)
    await waitFor(() => {
      expect(screen.getByTestId('delete-1')).toBeInTheDocument()
    })
    await user.click(screen.getByTestId('delete-1'))
    await waitFor(() => {
      expect(screen.getByTestId('modal')).toBeInTheDocument()
    })
    // 删除确认不再有「子分类」提示（issue #2905）
    expect(screen.queryByText(/该分类下还有/)).not.toBeInTheDocument()
  })

  it('should close delete modal when cancel is clicked', async () => {
    render(<CategoriesPage />)
    await waitFor(() => {
      expect(screen.getByTestId('delete-1')).toBeInTheDocument()
    })
    await user.click(screen.getByTestId('delete-1'))
    await waitFor(() => {
      expect(screen.getByTestId('modal')).toBeInTheDocument()
    })
    await user.click(screen.getByText('取消'))
    await waitFor(() => {
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument()
    })
  })

  it('should call deleteCategory when confirm delete is clicked', async () => {
    mockDeleteCategory.mockResolvedValue({ data: {} })
    render(<CategoriesPage />)
    await waitFor(() => {
      expect(screen.getByTestId('delete-1')).toBeInTheDocument()
    })
    await user.click(screen.getByTestId('delete-1'))
    await waitFor(() => {
      expect(screen.getByTestId('modal')).toBeInTheDocument()
    })
    const confirmBtn = screen.getByRole('button', { name: '确认删除' })
    await user.click(confirmBtn)
    await waitFor(() => {
      expect(mockDeleteCategory).toHaveBeenCalledWith('1')
    })
  })

  it('should reload categories after successful delete', async () => {
    mockDeleteCategory.mockResolvedValue({ data: {} })
    render(<CategoriesPage />)
    await waitFor(() => {
      expect(screen.getByTestId('delete-1')).toBeInTheDocument()
    })
    // First load
    await waitFor(() => {
      expect(mockGetCategories).toHaveBeenCalledTimes(1)
    })
    await user.click(screen.getByTestId('delete-1'))
    await waitFor(() => {
      expect(screen.getByTestId('modal')).toBeInTheDocument()
    })
    const confirmBtn = screen.getByRole('button', { name: '确认删除' })
    await user.click(confirmBtn)
    // Should call getCategories again after delete
    await waitFor(() => {
      expect(mockGetCategories).toHaveBeenCalledTimes(2)
    })
  })

  it('should show confirm button disabled while deleting', async () => {
    mockDeleteCategory.mockImplementation(() => new Promise(() => {}))
    render(<CategoriesPage />)
    await waitFor(() => {
      expect(screen.getByTestId('delete-1')).toBeInTheDocument()
    })
    await user.click(screen.getByTestId('delete-1'))
    await waitFor(() => {
      expect(screen.getByTestId('modal')).toBeInTheDocument()
    })
    // Click the confirm button to trigger delete (which never resolves)
    await user.click(screen.getByRole('button', { name: '确认删除' }))
    // After clicking, deleting state becomes true, and loading prop disables the button
    await waitFor(() => {
      const btn = screen.getByRole('button', { name: '确认删除' })
      expect(btn).toBeDisabled()
    })
  })
})

/**
 * 读失败 vs 真空态（issue #8200 · P1-06）—— `/categories` 是审计 P1-06 里**唯一**复核成立的那一处：
 * 改前读接口失败走**空 catch**，屏上照印 `<EmptyState title="还没有商品分类">` + 「先建一个分类」，
 * 与「这个店真的没有分类」逐字相同（DQ-1：空态不得冒充读不到）。
 *
 * 钉住三件事（各自红在自己那条断言上）：
 *   ① 失败 ⇒ **常驻**失败面（`role="alert"`）+ 重试出口在屏上；
 *   ② 失败 ⇒ 空态锚与空态文案**都不在**（`findEmptyDataAssertions` 是仓内**单一源**口径，不抄第二份正则）；
 *   ③ 点重试 ⇒ **真的重发**（调用次数 +1）且成功后失败面退场、树回来；
 * 对照读数：读**成功且真为空** ⇒ 空态照旧，失败面**不在**（不许把真 0 判红）。
 */
/** 整例预算（失败态等到底会走 RTL 的 5s `asyncUtilTimeout`；不拉长会以 `Test timed out` 出现 = 没跑到断言） */
const TEST_TIMEOUT = 20_000

describe('读失败 vs 真空态（issue #8200 · P1-06）', () => {
  it('读失败：常驻失败面 + 重试出口；空态锚与「没有分类」断言都不在屏上', async () => {
    mockGetCategories.mockRejectedValue(new Error('boom'))
    render(<CategoriesPage />)

    const anchor = await screen.findByTestId('categories-load-error')
    expect(anchor).toHaveAttribute('role', 'alert')
    expect(anchor).toHaveTextContent('分类没读到')
    expect(screen.getByTestId('categories-load-error-retry')).toBeInTheDocument()

    // ② 不冒充空态：锚与文案都要「不在」，且整屏没有「没有数据」式断言
    expect(screen.queryByTestId('categories-empty')).toBeNull()
    expect(screen.queryByText('还没有商品分类')).toBeNull()
    expect(findEmptyDataAssertions(document.body.textContent ?? '')).toEqual([])
  }, TEST_TIMEOUT)

  it('重试真的重发（不是只把失败面藏起来）：成功后失败面退场、分类树回来', async () => {
    mockGetCategories.mockRejectedValueOnce(new Error('boom'))
    mockGetCategories.mockResolvedValueOnce({ data: { data: mockCategories } })
    render(<CategoriesPage />)

    await screen.findByTestId('categories-load-error')
    // 基线取「点之前」的调用次数（**相对增量**：不受本文件其它用例遗留的自动重拉影响，
    // 判的仍是「这一次点击真的发了一次新请求」，不是「总次数恰好等于某个数」）
    const beforeRetry = mockGetCategories.mock.calls.length
    fireEvent.click(screen.getByTestId('categories-load-error-retry'))

    await waitFor(() => expect(mockGetCategories.mock.calls.length).toBeGreaterThan(beforeRetry))
    // 新请求的结果**真的被采用**（不是只把失败面藏起来）
    await waitFor(() => expect(screen.getByTestId('category-tree')).toBeInTheDocument())
    expect(screen.queryByTestId('categories-load-error')).toBeNull()
  }, TEST_TIMEOUT)

  it('对照读数：读成功且真为空 ⇒ 仍是空态（失败面没有把真空态吃掉）', async () => {
    mockGetCategories.mockResolvedValue({ data: { data: [] } })
    render(<CategoriesPage />)

    await waitFor(() => expect(screen.getByTestId('categories-empty')).toBeInTheDocument())
    expect(screen.queryByTestId('categories-load-error')).toBeNull()
  }, TEST_TIMEOUT)
})
