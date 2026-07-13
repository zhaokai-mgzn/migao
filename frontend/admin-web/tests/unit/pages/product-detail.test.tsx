import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

// Mock API
const mockGetProduct = vi.fn()
const mockUpdateProductStatus = vi.fn()

vi.mock('@/lib/api', () => ({
  productApi: {
    getProduct: (...args: any[]) => mockGetProduct(...args),
    updateProductStatus: (...args: any[]) => mockUpdateProductStatus(...args),
  },
}))

// Mock useRouteId
vi.mock('@/lib/use-route-id', () => ({
  useRouteId: () => 'test-product-1',
}))

// Mock resolveImageUrl
vi.mock('@/lib/utils', () => ({
  resolveImageUrl: (url: string) => url,
  cn: (...args: any[]) => args.filter(Boolean).join(' '),
}))

// Mock next/link
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

// Mock next/image
vi.mock('next/image', () => ({
  default: (props: any) => <img {...props} />,
}))

// Mock sonner
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// Mock UI components
vi.mock('@/components/ui', () => ({
  Button: ({ children, onClick, ...props }: any) => (
    <button onClick={onClick} {...props}>{children}</button>
  ),
  Badge: ({ children, variant }: any) => (
    <span data-testid="badge" data-variant={variant}>{children}</span>
  ),
  Loading: ({ text }: any) => <div>{text}</div>,
}))

// Mock types
vi.mock('@/types', () => ({
  ProductStatusLabels: {
    on_sale: '在售',
    off_sale: '下架',
    under_review: '审核中',
    draft: '草稿',
  },
  PricingTypeLabels: {
    per_meter: '按米计价',
    per_piece: '按件计价',
    per_area: '按面积计价',
  },
  SellingMethodLabels: {
    bulk_cut: '散剪',
    full_roll: '整卷',
    per_meter: '按米',
    per_piece: '按件',
  },
}))

import ProductDetailPage from '@/app/(dashboard)/products/[id]/ProductDetail'

const mockProduct = {
  id: 'test-product-1',
  name: '2699色卡',
  status: 'on_sale' as const,
  sku: 'SKU-2699',
  skuCode: 'SKU-2699-001',
  categoryName: '窗帘布',
  brand: '米高',
  pricingType: 'per_meter' as const,
  pricingUnit: '米',
  price: 99.5,
  costPrice: 55,
  totalStock: 500,
  stockDeductionMode: 'on_order',
  stockWarningThreshold: 100,
  colorCount: 6,
  salesCount: 1200,
  salesAmount: 119400,
  images: ['https://example.com/img1.jpg'],
  detailImages: ['https://example.com/detail1.jpg'],
  specifications: { weight: '500g', material: '涤纶' },
  colors: [
    { id: 1, colorName: '米白', mainColorHex: '#F5F5DC' },
    { id: 2, colorName: '深灰', mainColorHex: '#404040' },
  ],
  skus: [
    { id: 1, colorId: 1, colorName: '米白', doorWidth: '2.8米', sellingMethod: 'bulk_cut', skuCode: 'SKU-MB', stock: 200, price: 99.5 },
    { id: 2, colorId: 2, colorName: '深灰', doorWidth: '2.8米', sellingMethod: 'bulk_cut', skuCode: 'SKU-SG', stock: 300, price: 99.5 },
  ],
  processingItemConfigs: [
    { processingItemName: '打孔加工', customPrice: 5 },
  ],
  description: '高品质窗帘布',
  createdAt: '2026-01-15 10:00',
  updatedAt: '2026-06-20 15:00',
  editedBy: '管理员',
  editedAt: '2026-06-20 15:00:00',
}

describe('ProductDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetProduct.mockResolvedValue({
      data: { data: mockProduct },
    })
  })

  it('should show loading state initially', () => {
    render(<ProductDetailPage />)
    expect(screen.getByText('加载中...')).toBeInTheDocument()
  })

  it('should render product name after loading', async () => {
    render(<ProductDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('2699色卡')).toBeInTheDocument()
    })
  })

  it('should render status badge', async () => {
    render(<ProductDetailPage />)
    await waitFor(() => {
      const badges = screen.getAllByTestId('badge')
      expect(badges.length).toBeGreaterThanOrEqual(1)
      expect(badges[0]).toHaveTextContent('在售')
    })
  })

  it('should render edit button', async () => {
    render(<ProductDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('编辑')).toBeInTheDocument()
    })
  })

  it('should render down-shelf button for on_sale product', async () => {
    render(<ProductDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('下架')).toBeInTheDocument()
    })
  })

  it('should render up-shelf button for off_sale product', async () => {
    mockGetProduct.mockResolvedValue({
      data: { data: { ...mockProduct, status: 'off_sale' } },
    })
    render(<ProductDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('上架')).toBeInTheDocument()
    })
  })

  it('should render basic info section', async () => {
    render(<ProductDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('基本信息')).toBeInTheDocument()
      expect(screen.getByText('窗帘布')).toBeInTheDocument()
    })
  })

  it('should render product attributes section', async () => {
    render(<ProductDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('商品属性')).toBeInTheDocument()
      expect(screen.getByText('克重')).toBeInTheDocument()
      expect(screen.getByText('材质')).toBeInTheDocument()
    })
  })

  it('should render SKU table with 销售信息 title', async () => {
    render(<ProductDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('销售信息')).toBeInTheDocument()
    })
  })

  it('should render 货号 in basic info', async () => {
    render(<ProductDetailPage />)
    await waitFor(() => {
      const all = screen.getAllByText('货号')
      expect(all.length).toBeGreaterThanOrEqual(1)
      expect(screen.getByText('SKU-2699-001')).toBeInTheDocument()
    })
  })

  it('should have description above images', async () => {
    render(<ProductDetailPage />)
    await waitFor(() => {
      const d = screen.getByText('商品描述')
      const i = screen.getByText('商品图片')
      expect(d.compareDocumentPosition(i) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    })
  })

  it('should render processing items section', async () => {
    render(<ProductDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('加工项')).toBeInTheDocument()
      expect(screen.getByText('打孔加工')).toBeInTheDocument()
    })
  })

  it('should render description section', async () => {
    render(<ProductDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('商品描述')).toBeInTheDocument()
    })
  })
})
