// case_ids: PR-011, PR-019, PR-042, PR-043, PR-044, OR-046, UI-055
// #4371：加工项与商品解耦 —— 商品详情页不再展示商品维度的「加工项」块
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

// Mock API
const mockGetProduct = vi.fn()
const mockUpdateProductStatus = vi.fn()

vi.mock('@/lib/api', () => ({
  productApi: {
    getProduct: (...args: any[]) => mockGetProduct(...args),
    updateProductStatus: (...args: any[]) => mockUpdateProductStatus(...args),
  },
}))

// Mock request（行内改价走 `request.patch`，见 SkuPriceCell.save）
const mockPatch = vi.fn()
vi.mock('@/lib/request', () => ({
  default: { patch: (...args: any[]) => mockPatch(...args) },
}))

// **稳定** router：`tests/setup.ts` 的 `useRouter()` 每次调用返回**新对象**，而详情页的
// `loadProduct` 以 router 为依赖 ⇒ effect 反复重跑、loading 态周期性回来（见下方既有注释）。
// 只读断言可以躲在 `waitFor` 里，**交互型**断言（点开行内改价框 → 键入 → 提交）会被这个抖动
// 打断（子组件随 loading 卸载、state 丢失）⇒ 本文件改用稳定 router，从根上消掉抖动。
vi.mock('next/navigation', () => {
  const router = {
    push: vi.fn(), replace: vi.fn(), back: vi.fn(), forward: vi.fn(),
    refresh: vi.fn(), prefetch: vi.fn(),
  }
  return {
    useRouter: () => router,
    usePathname: () => '/',
    useSearchParams: () => new URLSearchParams(),
    useParams: () => ({}),
    redirect: vi.fn(),
    notFound: vi.fn(),
  }
})

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
  StatusBadge: ({ label, color, dot, className, onClick }: any) => React.createElement('span', { onClick, className, title: label }, dot ? React.createElement('span', { className: 'w-1.5 h-1.5 rounded-full' }) : null, label),
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

  it('should render description section', async () => {
    render(<ProductDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('商品描述')).toBeInTheDocument()
    })
  })

  // ========== 售卖方式 / 卷长 = 商品级基础属性（PR-042 / PR-043）==========
  //
  // ⚠️ 断言必须留在 `waitFor` 内：`tests/setup.ts` 的 `useRouter()` 每次调用返回**新对象**
  // ⇒ 详情页 effect（deps 含 router）反复重跑、loading 态会周期性回来，
  // 在 waitFor 之后做同步查询会偶发撞上 loading 帧（实测）。
  it('PR-042: SKU 表**没有**「售卖方式」列（它已上移为商品级基础属性）', async () => {
    render(<ProductDetailPage />)
    await waitFor(() => {
      const table = screen.getByText('颜色').closest('table') as HTMLTableElement
      const headers = Array.from(table.querySelectorAll('th')).map((th) => th.textContent || '')
      expect(headers.some((h) => h.includes('售卖方式'))).toBe(false)
      expect(headers.some((h) => h.includes('门幅'))).toBe(true)
    })
  })

  it('PR-043: 未配置卷长时显示「未配置」（不编数字）', async () => {
    render(<ProductDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('1 卷 = 多少米')).toBeInTheDocument()
      expect(screen.getByText('未配置')).toBeInTheDocument()
    })
  })
})

// ========== 行内改价（SkuPriceCell）的数值语义（issue #5228 缺口 2）==========
//
// ⚠️ 判据**不建在「`0.` 中间态」上**：jsdom 把 `type="number"` 的 `"0."` 归一成 `""`，
// 真 Chromium 归一成 `"0"`（#5228 主会话真浏览器实测，两套读数**相反**）⇒ 谁在 jsdom 里拿它
// 当判据，谁就是在拿与环境相反的读数下结论（必然假红或假绿）。
// 这里钉的是**与引擎无关**的三条语义：完整串 ⇒ 提交原值；`0` ⇒ **不被当空**；空 ⇒ 显式拒绝（不是 0）。
describe('ProductDetailPage — 行内改价 SkuPriceCell 的数值语义（issue #5228 缺口 2）', () => {
  // ⚠️ 本 describe 与外层 `describe('ProductDetailPage')` 是**兄弟** ⇒ 不继承它的 `beforeEach`
  // ⇒ 必须自己复位（否则 `mockPatch` 的调用次数跨用例累积，`toHaveBeenCalledTimes(1)` 会永远等不到）。
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetProduct.mockResolvedValue({ data: { data: mockProduct } })
    mockPatch.mockResolvedValue({ data: { data: {} } })
  })

  /** 打开第 1 个 SKU 的价格行内编辑框（夹具价 99.5），返回那个 input */
  async function openPriceEditor() {
    render(<ProductDetailPage />)
    const cells = await screen.findAllByTitle('点击编辑价格')
    fireEvent.click(cells[0])
    return screen.getByDisplayValue('99.5') as HTMLInputElement
  }

  it('完整串 `0.5` ⇒ 提交的就是 0.5（原值：不取整、不被当空）', async () => {
    const input = await openPriceEditor()
    fireEvent.change(input, { target: { value: '0.5' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => expect(mockPatch).toHaveBeenCalledTimes(1))
    expect(mockPatch).toHaveBeenCalledWith('/api/admin/agent/products/test-product-1/skus/1', {
      price: 0.5,
    })
  })

  it('`0` 不被当空（#5198 那族的病根本体）：输入 0 ⇒ 提交 price: 0，且不报「请输入有效价格」', async () => {
    const input = await openPriceEditor()
    fireEvent.change(input, { target: { value: '0' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => expect(mockPatch).toHaveBeenCalledTimes(1))
    expect(mockPatch.mock.calls[0][1]).toEqual({ price: 0 })
    const { toast } = await import('sonner')
    expect(toast.error).not.toHaveBeenCalled()
  })

  it('清空 ⇒ **不是 0**：提交被显式拒绝（可行动文案），且一个请求都不发', async () => {
    const input = await openPriceEditor()
    fireEvent.change(input, { target: { value: '' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    const { toast } = await import('sonner')
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('请输入有效价格'))
    expect(mockPatch).not.toHaveBeenCalled()
  })
})
