// case_ids: PR-010, PR-042, UI-055
//
// 库存口径三处一致（issue #6662 判据 ⑤）：商品详情 / 商品表单 / SKU 矩阵**同一个单位**。
// 缺陷形态：SkuMatrix 写「库存（米）」、ProductForm 总库存尾缀写「件」、详情表头只写「库存」
// —— 同一份 `product_skus.stock`（库列注释与 V115 精度都写明是**米**，
// `ProductService.getTotalStock()` 就是它的汇总）在三个面三种读法。
// 修法：单位取**单一源**（`STOCK_UNIT`），三处引用它 —— 下次改单位只改一处。
// 红证（注入式）：把 ProductForm 尾缀改回字面量「件」⇒ 本组第一条红。
import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { STOCK_UNIT } from '@/lib/product-roll-length'

const mockGetProduct = vi.fn()
vi.mock('@/lib/api', () => ({
  productApi: {
    getProduct: (...args: any[]) => mockGetProduct(...args),
    updateProductStatus: vi.fn(),
  },
  categoryApi: { getCategories: vi.fn().mockResolvedValue({ data: { data: [] } }) },
  processingItemApi: { getProcessingItems: vi.fn().mockResolvedValue({ data: { data: { items: [] } } }) },
}))
vi.mock('@/lib/request', () => ({ default: { patch: vi.fn() } }))
vi.mock('next/navigation', () => {
  const router = { push: vi.fn(), replace: vi.fn(), back: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }
  return { useRouter: () => router, usePathname: () => '/', useSearchParams: () => new URLSearchParams(), useParams: () => ({}) }
})
vi.mock('@/lib/use-route-id', () => ({ useRouteId: () => 'test-product-1' }))
vi.mock('next/image', () => ({ default: (props: any) => <img {...props} /> }))
vi.mock('@/components/products/ImageUploader', () => ({ default: () => <div data-testid="image-uploader" /> }))
vi.mock('@/components/products/ProductAttributes', () => ({ default: () => <div data-testid="product-attributes" /> }))
vi.mock('@/components/products/RichTextEditor', () => ({ default: () => <div data-testid="rich-text-editor" /> }))

import ProductDetailPage from '@/app/(dashboard)/products/[id]/ProductDetail'
import ProductForm from '@/components/products/ProductForm'

const mockProduct = {
  id: 'test-product-1',
  name: '库存单位探针',
  status: 'on_sale' as const,
  price: 10,
  pricingUnit: '米',
  totalStock: 12.5,
  specifications: {},
  skus: [{ id: 1, colorName: '米白', doorWidth: '2.8米', skuCode: 'S1', stock: 12.5, price: 10 }],
}

describe('库存单位单一源（issue #6662 判据 ⑤）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetProduct.mockResolvedValue({ data: { data: mockProduct } })
  })

  it('#6662 ProductForm 的「总库存」尾缀 = STOCK_UNIT（不是「件」）', () => {
    const { container } = render(<ProductForm onSubmit={vi.fn()} />)
    // 只读总库存框：`input[readonly]` 后面那个绝对定位的单位尾缀 span
    const input = container.querySelector('input[readonly]') as HTMLInputElement
    expect(input).toBeTruthy()
    const suffix = input.parentElement?.querySelector('span') as HTMLElement
    expect(suffix.textContent?.trim()).toBe(STOCK_UNIT)
    expect(suffix.textContent).not.toContain('件')
  })

  it('#6662 商品详情有库存读数处一律带单位（STOCK_UNIT），不出现「件」', async () => {
    render(<ProductDetailPage />)
    await waitFor(() => expect(screen.getByText('库存单位探针')).toBeInTheDocument())
    expect(screen.getAllByText(new RegExp(`库存（${STOCK_UNIT}）`)).length).toBeGreaterThanOrEqual(2)
    expect(screen.queryByText(/库存（件）/)).toBeNull()
  })
})
