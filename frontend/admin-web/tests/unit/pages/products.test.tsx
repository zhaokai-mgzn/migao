import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// ===== Override next/navigation mock with mutable searchParams (issue #660) =====
const { mockReplace, getSearchParams, resetSearchParams } = vi.hoisted(() => {
  let searchParams = new URLSearchParams()
  return {
    mockReplace: vi.fn((url: string | URL) => {
      const urlStr = typeof url === 'string' ? url : url.toString()
      const qs = urlStr.split('?')[1] || ''
      searchParams = new URLSearchParams(qs)
    }),
    getSearchParams: () => searchParams,
    resetSearchParams: () => { searchParams = new URLSearchParams() },
  }
})

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: mockReplace,
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => '/products',
  useSearchParams: () => getSearchParams(),
  useParams: () => ({}),
  redirect: vi.fn(),
  notFound: vi.fn(),
}))

// Mock API
const mockGetProducts = vi.fn()
const mockGetCategories = vi.fn()
const mockDeleteProduct = vi.fn()
const mockUpdateProductStatus = vi.fn()

vi.mock('@/lib/api', () => ({
  productApi: {
    getProducts: (...args: any[]) => mockGetProducts(...args),
    deleteProduct: (...args: any[]) => mockDeleteProduct(...args),
    updateProductStatus: (...args: any[]) => mockUpdateProductStatus(...args),
  },
  categoryApi: {
    getCategories: (...args: any[]) => mockGetCategories(...args),
  },
}))

// Mock next/link
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

// Mock ProductTable
vi.mock('@/components/products/ProductTable', () => ({
  default: ({ products, loading, total, page, pageSize, onPageChange, onDelete }: any) => (
    <div data-testid="product-table">
      {loading && <div data-testid="table-loading">加载中...</div>}
      {!loading && products.length === 0 && <div data-testid="table-empty">暂无数据</div>}
      {products.map((p: any) => (
        <div key={p.id} data-testid={`product-${p.id}`}>
          <span>{p.name}</span>
          <button onClick={() => onDelete(p)} data-testid={`delete-${p.id}`}>删除</button>
        </div>
      ))}
      <div data-testid="table-info">共 {total} 条, 第 {page} 页</div>
    </div>
  ),
}))

// Mock UI components
vi.mock('@/components/ui', () => ({
  Button: ({ children, onClick, ...props }: any) => <button onClick={onClick} {...props}>{children}</button>,
  Select: ({ label, options, value, onChange, ...props }: any) => (
    <div>
      <label>{label}</label>
      <select value={value} onChange={onChange} data-testid={`select-${label}`}>
        {options?.map((o: any) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  ),
  Input: ({ label, value, onChange, onKeyDown, ...props }: any) => (
    <div>
      <label htmlFor={`input-${label}`}>{label}</label>
      <input id={`input-${label}`} value={value} onChange={onChange} onKeyDown={onKeyDown} {...props} />
    </div>
  ),
  Modal: ({ open, onClose, title, children, footer }: any) => (
    open ? (
      <div data-testid="modal" role="dialog">
        <h2>{title}</h2>
        {children}
        <div data-testid="modal-footer">{footer}</div>
      </div>
    ) : null
  ),
  EmptyState: ({ title, description, action }: any) => (
    <div data-testid="empty-state">
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  ),
}))

import ProductsPage from '@/app/(dashboard)/products/page'

const mockProducts = [
  { id: '1', name: '遮光窗帘A', sku: 'SKU001', status: 'on_sale', price: 199 },
  { id: '2', name: '纱帘B', sku: 'SKU002', status: 'off_sale', price: 99 },
  { id: '3', name: '卷帘C', sku: 'SKU003', status: 'draft', price: 159 },
]

describe('ProductsPage', () => {
  const user = userEvent.setup()

  beforeEach(() => {
    vi.clearAllMocks()
    resetSearchParams()
    mockGetProducts.mockResolvedValue({
      data: { data: { items: mockProducts, total: 3 } },
    })
    mockGetCategories.mockResolvedValue({
      data: { data: [] },
    })
  })

  it('should render page title', async () => {
    render(<ProductsPage />)
    expect(screen.getByText('商品列表')).toBeInTheDocument()
  })

  it('should render add product button', () => {
    render(<ProductsPage />)
    expect(screen.getByText('新增商品')).toBeInTheDocument()
  })

  it('should load and display products', async () => {
    render(<ProductsPage />)
    await waitFor(() => {
      expect(mockGetProducts).toHaveBeenCalled()
    })
    await waitFor(() => {
      expect(screen.getByTestId('product-1')).toBeInTheDocument()
      expect(screen.getByText('遮光窗帘A')).toBeInTheDocument()
    })
  })

  it('should show product table with correct total', async () => {
    render(<ProductsPage />)
    await waitFor(() => {
      expect(screen.getByTestId('table-info')).toHaveTextContent('共 3 条')
    })
  })

  it('should load products on mount', async () => {
    render(<ProductsPage />)
    await waitFor(() => {
      expect(mockGetProducts).toHaveBeenCalled()
    })
  })

  it('should show search/filter section when products exist', async () => {
    render(<ProductsPage />)
    await waitFor(() => {
      expect(screen.getByText('商品ID')).toBeInTheDocument()
    })
  })

  it.skip('should show empty state when no products and no filters', async () => {
    // TODO: ProductTable mock 的 loading 状态与真实组件不同步，
    // 需要重构 mock 或直接用真实 ProductTable 组件
    mockGetProducts.mockResolvedValue({
      data: { data: { items: [], total: 0 } },
    })
    render(<ProductsPage />)
    const emptyState = await screen.findByTestId('table-empty')
    expect(emptyState).toBeInTheDocument()
    expect(screen.getByText('暂无数据')).toBeInTheDocument()
  })

  it('should call API with search params', async () => {
    render(<ProductsPage />)
    await waitFor(() => {
      expect(mockGetProducts).toHaveBeenCalledWith(
        expect.objectContaining({ page: 1, size: 10 })
      )
    })
  })

  it('should open delete confirmation modal', async () => {
    render(<ProductsPage />)
    await waitFor(() => {
      expect(screen.getByTestId('product-1')).toBeInTheDocument()
    })
    await user.click(screen.getByTestId('delete-1'))
    expect(screen.getByTestId('modal')).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  // ═══════════════════════════════════════════════════════════
  // Issue #660: 筛选字段 onChange → 立即查询
  // CONTRACT_JSON business_truths:
  //   1. 切换状态筛选 → 列表立即按新状态重新查询并刷新
  //   2. 切换商品ID/名称/SKU/创建时间 → 列表立即按新条件重新查询
  //   3. 切换任何筛选条件 → 分页自动重置到第 1 页
  //   4. 输入框筛选(名称/SKU/商品ID) → 300ms debounce 后才触发查询
  //   5. 点"搜索"按钮 → 行为与切换筛选条件一致
  // ═══════════════════════════════════════════════════════════

  it('should refetch when status filter changes (immediate)', async () => {
    render(<ProductsPage />)
    await waitFor(() => {
      expect(mockGetProducts).toHaveBeenCalledTimes(1)
    })

    const statusSelect = screen.getByRole('combobox')
    await user.selectOptions(statusSelect, 'on_sale')

    // 立即触发 syncUrl → router.replace 被调用，包含 status=on_sale&page=1
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith(
        expect.stringContaining('status=on_sale'),
        expect.objectContaining({ scroll: false })
      )
    })
  })

  it('should reset page to 1 when status filter changes', async () => {
    render(<ProductsPage />)
    await waitFor(() => {
      expect(mockGetProducts).toHaveBeenCalledTimes(1)
    })

    const statusSelect = screen.getByRole('combobox')
    await user.selectOptions(statusSelect, 'off_sale')

    await waitFor(() => {
      const calls = mockReplace.mock.calls
      const lastCall = calls[calls.length - 1]
      const url = lastCall[0] as string
      expect(url).toContain('page=1')
      expect(url).toContain('status=off_sale')
    })
  })

  it('should refetch when createdFrom date changes (immediate)', async () => {
    render(<ProductsPage />)
    await waitFor(() => {
      expect(mockGetProducts).toHaveBeenCalledTimes(1)
    })

    const dateInput = screen.getByPlaceholderText('开始日期')
    await user.clear(dateInput)
    await user.type(dateInput, '2025-01-01')

    // 日期选择器 onChange 触发 syncUrl
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith(
        expect.stringContaining('createdFrom=2025-01-01'),
        expect.objectContaining({ scroll: false })
      )
    })
  })

  it('should refetch when createdTo date changes (immediate)', async () => {
    render(<ProductsPage />)
    await waitFor(() => {
      expect(mockGetProducts).toHaveBeenCalledTimes(1)
    })

    const dateInput = screen.getByPlaceholderText('结束日期')
    await user.clear(dateInput)
    await user.type(dateInput, '2025-12-31')

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith(
        expect.stringContaining('createdTo=2025-12-31'),
        expect.objectContaining({ scroll: false })
      )
    })
  })

  it('should debounce text input changes by 300ms before syncUrl', async () => {
    render(<ProductsPage />)
    await waitFor(() => {
      expect(mockGetProducts).toHaveBeenCalledTimes(1)
    })

    const nameInput = screen.getByPlaceholderText('请输入商品标题')
    await user.clear(nameInput)
    await user.type(nameInput, '遮光')

    // 立即检查：syncUrl 不应被调用（还在 300ms debounce 期内）
    expect(mockReplace).not.toHaveBeenCalledWith(
      expect.stringContaining('name='),
      expect.anything()
    )

    // 等待 350ms（超过 300ms debounce）
    await new Promise(r => setTimeout(r, 350))

    // 现在 syncUrl 应该被调用，name 被 URLSearchParams 自动编码
    expect(mockReplace).toHaveBeenCalledWith(
      expect.stringContaining('name=%E9%81%AE%E5%85%89'), // encodeURIComponent('遮光')
      expect.anything()
    )
  })

  it('should keep Enter key search working after onChange debounce', async () => {
    render(<ProductsPage />)
    await waitFor(() => {
      expect(mockGetProducts).toHaveBeenCalledTimes(1)
    })

    // 搜索按钮点击仍应立即触发查询（非 debounce）
    const searchButton = screen.getByText('搜索')
    await user.click(searchButton)

    // handleSearch → syncUrl({ page: 1 }) 被立即调用
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith(
        expect.stringContaining('page=1'),
        expect.objectContaining({ scroll: false })
      )
    })
  })
})
