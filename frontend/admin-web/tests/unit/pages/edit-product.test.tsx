import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

// ===== Mock useRouteId =====
const mockProductId = 'prod-123'
vi.mock('@/lib/use-route-id', () => ({
  useRouteId: () => mockProductId,
}))

// ===== Mock productApi =====
const mockGetProduct = vi.fn()
const mockUpdateProduct = vi.fn()

vi.mock('@/lib/api', () => ({
  productApi: {
    getProduct: (...args: any[]) => mockGetProduct(...args),
    updateProduct: (...args: any[]) => mockUpdateProduct(...args),
  },
}))

// ===== Mock next/navigation =====
// Use vi.hoisted to create a STABLE router object — prevents useEffect re-runs
const { mockPush, stableRouter } = vi.hoisted(() => {
  const mockPush = vi.fn()
  const stableRouter = {
    push: mockPush,
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }
  return { mockPush, stableRouter }
})

vi.mock('next/navigation', () => ({
  useRouter: () => stableRouter,
  usePathname: () => '/products/prod-123/edit',
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({ id: 'prod-123' }),
  redirect: vi.fn(),
  notFound: vi.fn(),
}))

// ===== Mock ProductForm =====
const mockProductFormProps = vi.fn()
vi.mock('@/components/products/ProductForm', () => ({
  default: (props: any) => {
    mockProductFormProps(props)
    return (
      <div data-testid="product-form">
        <h3>编辑商品</h3>
        <span data-testid="submit-text">{props.submitText}</span>
        {props.initialData && (
          <div data-testid="initial-data">
            <span data-testid="product-name">{props.initialData.name}</span>
            <span data-testid="product-sku">{props.initialData.sku}</span>
            <span data-testid="product-price">{props.initialData.price}</span>
            <span data-testid="product-stock-deduction">{props.initialData.stockDeductionMode}</span>
            <span data-testid="product-supports-processing">{String(props.initialData.supportsProcessing)}</span>
          </div>
        )}
        <button
          data-testid="form-submit"
          onClick={() => props.onSubmit(props.initialData)}
        >
          提交
        </button>
      </div>
    )
  },
}))

// ===== Mock UI components =====
vi.mock('@/components/ui', () => ({
  Loading: ({ text, size }: any) => (
    <div data-testid="loading" data-size={size}>
      {text}
    </div>
  ),
}))

import EditProductPage from '@/app/(dashboard)/products/[id]/edit/EditProduct'

const mockProduct = {
  id: 'prod-123',
  name: '遮光窗帘A',
  sku: 'SKU001',
  skuCode: 'SC001',
  brand: '米高',
  categoryId: 'cat-1',
  description: '高品质遮光窗帘',
  pricingType: 'fixed',
  price: 199,
  costPrice: 100,
  unit: '米',
  status: 'on_sale' as const,
  images: ['https://example.com/img1.jpg'],
  detailImages: [],
  specifications: { color: '灰色' },
  processingItems: ['item-1'],
  processingItemConfigs: [{ itemId: 'item-1', price: 50 }],
  stockDeductionMode: 'on_order' as const,
  colors: [],
  sellingMethods: [],
  doorWidths: [],
  skus: [],
}

describe('EditProductPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Ensure getProduct resolves with valid data for most tests
    mockGetProduct.mockImplementation(() =>
      Promise.resolve({ data: { data: mockProduct } })
    )
  })

  // ── Product loaded (run first before any mock-changing tests) ──

  it('should fetch product on mount using route id', async () => {
    render(<EditProductPage />)
    await waitFor(() => {
      expect(mockGetProduct).toHaveBeenCalledWith('prod-123')
    })
  })

  it('should render ProductForm after product loads', async () => {
    render(<EditProductPage />)
    await waitFor(() => {
      expect(screen.getByTestId('product-form')).toBeInTheDocument()
    })
  })

  // ── Form submission ──

  it('should call updateProduct when form is submitted', async () => {
    render(<EditProductPage />)
    // Wait for the form to render fully
    await screen.findByTestId('product-form')
    // Set up the update mock after form is loaded
    mockUpdateProduct.mockImplementation(() =>
      Promise.resolve({ data: { data: mockProduct } })
    )
    // Submit the form
    const btn = screen.getByTestId('form-submit')
    btn.click()
    // Verify updateProduct was called
    await waitFor(() => {
      expect(mockUpdateProduct).toHaveBeenCalledWith('prod-123', expect.any(Object))
    })
  })

  // ── Loading state ──

  it('should show loading state initially', () => {
    mockGetProduct.mockImplementation(() => new Promise(() => {}))
    render(<EditProductPage />)
    expect(screen.getByTestId('loading')).toBeInTheDocument()
    expect(screen.getByText('加载中...')).toBeInTheDocument()
  })

  it('should show large loading spinner', () => {
    mockGetProduct.mockImplementation(() => new Promise(() => {}))
    render(<EditProductPage />)
    expect(screen.getByTestId('loading')).toHaveAttribute('data-size', 'lg')
  })

  it('should pass correct submitText to ProductForm', async () => {
    render(<EditProductPage />)
    await waitFor(() => {
      expect(screen.getByTestId('product-form')).toBeInTheDocument()
    })
    await waitFor(() => {
      expect(screen.getByTestId('submit-text')).toHaveTextContent('保存修改')
    })
  })

  // ── Initial data mapping ──

  it('should pass name in initialData', async () => {
    render(<EditProductPage />)
    await waitFor(() => {
      expect(screen.getByTestId('product-name')).toHaveTextContent('遮光窗帘A')
    })
  })

  it('should pass sku in initialData', async () => {
    render(<EditProductPage />)
    await waitFor(() => {
      expect(screen.getByTestId('product-sku')).toHaveTextContent('SKU001')
    })
  })

  it('should pass price in initialData', async () => {
    render(<EditProductPage />)
    await waitFor(() => {
      expect(screen.getByTestId('product-price')).toHaveTextContent('199')
    })
  })

  it('should map stockDeductionMode on_order to on_place', async () => {
    render(<EditProductPage />)
    await waitFor(() => {
      expect(screen.getByTestId('product-stock-deduction')).toHaveTextContent('on_place')
    })
  })

  it('should map stockDeductionMode on_payment to on_pay', async () => {
    mockGetProduct.mockResolvedValue({
      data: {
        data: { ...mockProduct, stockDeductionMode: 'on_payment' },
      },
    })
    render(<EditProductPage />)
    await waitFor(() => {
      expect(screen.getByTestId('product-stock-deduction')).toHaveTextContent('on_pay')
    })
  })

  it('should default empty processingItemConfigs to empty array', async () => {
    mockGetProduct.mockResolvedValue({
      data: {
        data: { ...mockProduct, processingItemConfigs: undefined },
      },
    })
    render(<EditProductPage />)
    await waitFor(() => {
      expect(screen.getByTestId('product-form')).toBeInTheDocument()
    })
    // Verify the initialData passed to ProductForm has empty arrays
    const calls = mockProductFormProps.mock.calls
    const lastCall = calls[calls.length - 1]?.[0]
    expect(lastCall?.initialData?.processingItemConfigs).toEqual([])
  })

  it('should set supportsProcessing true when processingItemConfigs has items', async () => {
    render(<EditProductPage />)
    await waitFor(() => {
      expect(screen.getByTestId('product-supports-processing')).toHaveTextContent('true')
    })
  })

  it('should set supportsProcessing false when processingItemConfigs is empty', async () => {
    mockGetProduct.mockResolvedValue({
      data: {
        data: { ...mockProduct, processingItemConfigs: [] },
      },
    })
    render(<EditProductPage />)
    await waitFor(() => {
      expect(screen.getByTestId('product-supports-processing')).toHaveTextContent('false')
    })
  })

  // ── Error handling ──

  it('should redirect to /products on load error', async () => {
    mockGetProduct.mockRejectedValue(new Error('Network error'))
    render(<EditProductPage />)
    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith('/products')
    })
  })

  // ── Null product state ──

  it('should render nothing when product is null after loading', async () => {
    mockGetProduct.mockResolvedValue({
      data: { data: null },
    })
    const { container } = render(<EditProductPage />)
    await waitFor(() => {
      expect(container.innerHTML).toBe('')
    })
  })
})
