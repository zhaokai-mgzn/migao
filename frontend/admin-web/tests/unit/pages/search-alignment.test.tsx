/**
 * L2 单元测试 — 搜索区域左对齐验证
 *
 * 业务真值 D1：所有表单页搜索/筛选区左侧对齐（与订单页一致）
 * 验证各列表页搜索容器 className 不含水平居中类
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

// ============ 公共 Mocks ============

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}))

const mockReplace = vi.fn()
const mockPush = vi.fn()

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush, replace: mockReplace, back: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => '/',
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
  redirect: vi.fn(),
  notFound: vi.fn(),
}))

vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

// 通用 UI Mock
vi.mock('@/components/ui', () => ({
  Button: ({ children, onClick, ...props }: any) => (
    <button onClick={onClick} {...props}>{children}</button>
  ),
  Input: ({ label, ...props }: any) => (
    <div>
      {label && <label>{label}</label>}
      <input {...props} />
    </div>
  ),
  Select: ({ label, options, value, onChange, ...props }: any) => (
    <div>
      {label && <label>{label}</label>}
      <select value={value} onChange={onChange} {...props}>
        {(options || []).map((o: any) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  ),
  Modal: ({ open, title, children, footer }: any) =>
    open ? <div data-testid="modal" role="dialog"><h2>{title}</h2>{children}<div>{footer}</div></div> : null,
  Pagination: () => <div data-testid="pagination" />,
  Table: ({ columns, dataSource, loading, rowKey, onRowClick }: any) => (
    <div data-testid="data-table">
      {loading && <div data-testid="table-loading">加载中...</div>}
      {(dataSource || []).map((row: any) => (
        <div key={row[rowKey || 'id']} data-testid={`row-${row[rowKey || 'id']}`}>{row.name || row.id}</div>
      ))}
    </div>
  ),
  Badge: ({ children, ...props }: any) => <span {...props}>{children}</span>,
  SearchBar: ({ fields, onSearch, onReset, loading, className }: any) => (
    <div data-testid="search-area" className={className} role="search">
      {(fields || []).map((f: any) => (
        <div key={f.key}>
          <label>{f.label}</label>
          <input placeholder={f.placeholder} />
        </div>
      ))}
      <button onClick={onSearch} disabled={loading}>搜索</button>
      <button onClick={onReset} disabled={loading}>重置</button>
    </div>
  ),
}))

vi.mock('@/components/ui/TreeCheckbox', () => ({
  TreeCheckbox: () => <div data-testid="tree-checkbox" />,
}))

// ============ 辅助函数 ============

const CENTER_CLASSES = ['mx-auto', 'justify-center', 'text-center']

function assertNoCenterClasses(className: string | null) {
  for (const cls of CENTER_CLASSES) {
    const regex = new RegExp(`\\b${cls.replace('-', '\\-')}\\b`)
    expect(className).not.toMatch(regex)
  }
}

const SEARCH_SELECTORS: Record<string, string> = {
  orders: '.bg-white.rounded-lg.border',
  products: '.bg-white.rounded-lg.border',
  'after-sales': '.border-x',
  customers: '[data-testid="search-area"]',
  employees: '.bg-gray-50.p-4.rounded-lg',
}

async function waitForSearchContainer(pageKey: string, container?: HTMLElement) {
  const selector = SEARCH_SELECTORS[pageKey]
  return await waitFor(() => {
    const el = (container || document).querySelector(selector)
    expect(el).toBeTruthy()
    return el as HTMLElement
  })
}

// ============ 测试 ============

describe('搜索区域左对齐 — 无居中 CSS 类', () => {
  describe('[orders] 订单页', () => {
    beforeEach(() => {
      vi.clearAllMocks()
      vi.doMock('@/lib/api', () => ({
        orderApi: {
          getOrders: vi.fn().mockResolvedValue({ data: { data: { items: [], total: 0 } } }),
          createOrder: vi.fn(),
          getOrder: vi.fn(),
        },
        productApi: { getProducts: vi.fn().mockResolvedValue({ data: { data: { items: [], total: 0 } } }) },
        customerApi: { getCustomers: vi.fn().mockResolvedValue({ data: { data: { items: [], total: 0 } } }) },
      }))
    })

    it('搜索容器 className 不含 mx-auto / justify-center / text-center', async () => {
      const { default: OrdersPage } = await import('@/app/(dashboard)/orders/page')
      const { container } = render(<OrdersPage />)
      const el = await waitForSearchContainer('orders', container)
      assertNoCenterClasses(el.className)
    })
  })

  describe('[products] 商品页（参照组）', () => {
    beforeEach(() => {
      vi.clearAllMocks()
      vi.doMock('@/lib/api', () => ({
        productApi: {
          getProducts: vi.fn().mockResolvedValue({ data: { data: { items: [], total: 0 } } }),
          deleteProduct: vi.fn(),
          updateProductStatus: vi.fn(),
        },
        categoryApi: { getCategories: vi.fn().mockResolvedValue({ data: { data: [] } }) },
      }))
      vi.doMock('@/components/products/ProductTable', () => ({
        default: () => <div data-testid="product-table" />,
      }))
    })

    it('搜索容器 className 不含 mx-auto / justify-center / text-center', async () => {
      const { default: ProductsPage } = await import('@/app/(dashboard)/products/page')
      const { container } = render(<ProductsPage />)
      const el = await waitForSearchContainer('products', container)
      assertNoCenterClasses(el.className)
    })
  })

  describe('[after-sales] 售后页', () => {
    beforeEach(() => {
      vi.clearAllMocks()
      vi.doMock('@/lib/api', () => ({
        afterSalesApi: {
          getTickets: vi.fn().mockResolvedValue({ data: { data: { items: [], total: 0 } } }),
          createTicket: vi.fn(),
        },
        orderApi: { getOrders: vi.fn().mockResolvedValue({ data: { data: { items: [] } } }) },
      }))
    })

    it('flex 布局搜索容器 className 不含 mx-auto / justify-center / text-center', async () => {
      const { default: AfterSalesPage } = await import('@/app/(dashboard)/after-sales/page')
      const { container } = render(<AfterSalesPage />)
      const el = await waitForSearchContainer('after-sales', container)
      assertNoCenterClasses(el.className)
      const innerFlex = el.querySelector('.flex.flex-wrap.items-end')
      expect(innerFlex).toBeTruthy()
      assertNoCenterClasses(innerFlex!.className)
    })
  })

  describe('[customers] 客户页', () => {
    beforeEach(() => {
      vi.clearAllMocks()
      vi.doMock('@/lib/api', () => ({
        customerApi: {
          getCustomers: vi.fn().mockResolvedValue({ data: { data: { items: [], total: 0 } } }),
          getCustomerTags: vi.fn().mockResolvedValue({ data: { data: [] } }),
          createCustomerTag: vi.fn(),
          updateCustomerTag: vi.fn(),
          deleteCustomerTag: vi.fn(),
        },
      }))
    })

    it('SearchBar 外层容器 className 不含 mx-auto / justify-center / text-center', async () => {
      const { default: CustomersPage } = await import('@/app/(dashboard)/customers/page')
      render(<CustomersPage />)
      const el = await waitForSearchContainer('customers')
      assertNoCenterClasses(el.className)
    })
  })

  describe('[employees] 员工页', () => {
    beforeEach(() => {
      vi.clearAllMocks()
      vi.doMock('@/lib/api', () => ({
        employeeApi: {
          getEmployees: vi.fn().mockResolvedValue({ data: { data: { items: [], total: 0 } } }),
          createEmployee: vi.fn(),
          updateEmployee: vi.fn(),
          deleteEmployee: vi.fn(),
          toggleEmployeeStatus: vi.fn(),
        },
        roleApi: { getAllRoles: vi.fn().mockResolvedValue({ data: { data: [] } }) },
      }))
      vi.doMock('@/lib/request', () => ({
        default: { get: vi.fn().mockResolvedValue({ data: { data: [] } }) },
      }))
    })

    it('搜索容器 className 不含 mx-auto / justify-center / text-center', async () => {
      const { default: EmployeesPage } = await import('@/app/(dashboard)/employees/page')
      const { container } = render(<EmployeesPage />)
      const el = await waitForSearchContainer('employees', container)
      assertNoCenterClasses(el.className)
    })
  })

  describe('[processing] 加工页 — 无搜索区域', () => {
    beforeEach(() => {
      vi.clearAllMocks()
      vi.doMock('@/lib/api', () => ({
        processingItemApi: {
          getProcessingItems: vi.fn().mockResolvedValue({ data: { data: { items: [] } } }),
          createProcessingItem: vi.fn(),
          updateProcessingItem: vi.fn(),
          deleteProcessingItem: vi.fn(),
          calculatePrice: vi.fn(),
        },
        processingCategoryApi: { getProcessingCategories: vi.fn().mockResolvedValue({ data: { data: [] } }) },
        categoryApi: { getCategories: vi.fn().mockResolvedValue({ data: { data: [] } }) },
      }))
    })

    it('页面不含 search-area 元素（无搜索区域，不受影响）', async () => {
      const { default: ProcessingPage } = await import('@/app/(dashboard)/processing/page')
      render(<ProcessingPage />)
      await waitFor(() => {
        expect(screen.getByText('加工项配置')).toBeInTheDocument()
      })
      expect(screen.queryByTestId('search-area')).toBeNull()
    })
  })
})
