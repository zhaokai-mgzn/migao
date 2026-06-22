import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// ===== Mock categoryApi =====
const mockGetCategories = vi.fn()
const mockCreateCategory = vi.fn()
const mockUpdateCategory = vi.fn()
const mockDeleteCategory = vi.fn()

vi.mock('@/lib/api', () => ({
  categoryApi: {
    getCategories: (...args: any[]) => mockGetCategories(...args),
    createCategory: (...args: any[]) => mockCreateCategory(...args),
    updateCategory: (...args: any[]) => mockUpdateCategory(...args),
    deleteCategory: (...args: any[]) => mockDeleteCategory(...args),
  },
}))

// ===== Mock CategoryTree =====
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
            <button data-testid={`add-child-${c.id}`} onClick={() => props.onAddChild(c)}>
              添加子分类
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
        {props.presetParentId && (
          <span data-testid="preset-parent-id">{props.presetParentId}</span>
        )}
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
vi.mock('@/components/ui', () => ({
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
}))

import CategoriesPage from '@/app/(dashboard)/categories/page'

const mockCategories = [
  { id: '1', name: '窗帘', children: [{ id: '2', name: '布艺窗帘' }] },
  { id: '3', name: '卷帘', children: [] },
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
    expect(screen.getByText('管理商品分类，最多支持二级分类')).toBeInTheDocument()
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
    expect(screen.getByText('加载中...')).toBeInTheDocument()
  })

  // ── Empty state ──

  it('should show empty state when no categories', async () => {
    mockGetCategories.mockResolvedValue({ data: { data: [] } })
    render(<CategoriesPage />)
    await waitFor(() => {
      expect(screen.getByText(/暂无分类/)).toBeInTheDocument()
    })
  })

  // ── Categories loaded ──

  it('should load categories on mount', async () => {
    render(<CategoriesPage />)
    await waitFor(() => {
      expect(mockGetCategories).toHaveBeenCalledTimes(1)
    })
  })

  it('should render category tree with loaded data', async () => {
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

  // ── Add child category ──

  it('should open dialog with presetParent when adding child', async () => {
    render(<CategoriesPage />)
    await waitFor(() => {
      expect(screen.getByTestId('add-child-1')).toBeInTheDocument()
    })
    await user.click(screen.getByTestId('add-child-1'))
    await waitFor(() => {
      expect(screen.getByTestId('category-dialog')).toBeInTheDocument()
      expect(screen.getByRole('heading', { name: '添加分类' })).toBeInTheDocument()
      expect(screen.getByTestId('preset-parent-id')).toHaveTextContent('1')
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

  it('should show children warning when category has sub-categories', async () => {
    render(<CategoriesPage />)
    await waitFor(() => {
      expect(screen.getByTestId('delete-1')).toBeInTheDocument()
    })
    await user.click(screen.getByTestId('delete-1'))
    await waitFor(() => {
      expect(screen.getByText(/该分类下还有 1 个子分类/)).toBeInTheDocument()
    })
  })

  it('should not show children warning when category has no sub-categories', async () => {
    render(<CategoriesPage />)
    await waitFor(() => {
      expect(screen.getByTestId('delete-3')).toBeInTheDocument()
    })
    await user.click(screen.getByTestId('delete-3'))
    await waitFor(() => {
      expect(screen.getByTestId('modal')).toBeInTheDocument()
      expect(screen.getByRole('heading', { name: '确认删除' })).toBeInTheDocument()
    })
    // Category "卷帘" has no children, so warning should not appear
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
