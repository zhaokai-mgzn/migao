// case_ids: UI-154
//
// 商品详情两区与层级（issue #8934）—— DOM 层判据（浏览器几何由
// `tests/e2e/specs/products/product-detail-regions.spec.ts` 承担）。
//
// 缺陷形态：批次账整块插在「商品属性」与「销售信息」之间 ⇒ 商品信息被切成两段、两个整体互相穿插；
// 库存读数在「基本信息」与「销售信息」表头各出现一次，批次区四块各带一段说明。
// 判据：两个区域卡（h2）+ 区域内子块（h3）；所有商品信息子块都在商品信息区、
// 批次/库存子块都在批次与库存区；商品级库存总量只出现一次。
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'

const mockGetProduct = vi.fn()

vi.mock('@/lib/api', () => ({
  productApi: {
    getProduct: (...args: any[]) => mockGetProduct(...args),
    updateProductStatus: vi.fn(),
  },
  batchStockApi: {
    batches: vi.fn().mockResolvedValue({
      data: {
        data: [
          {
            batchId: 1,
            batchNo: 'PC-20261101-0001',
            productId: 'test-product-1',
            skuId: 1,
            skuCode: 'SKU-MB',
            receivedDate: '2026-11-01',
            inboundMeters: '120',
            consumedMeters: '20',
            remainingMeters: '100',
          },
        ],
      },
    }),
    distribution: vi.fn().mockResolvedValue({
      data: {
        data: {
          totalBatches: 1,
          buckets: [
            { key: 'le_0_2', label: '≤0.2 米', batchCount: 0, share: '0' },
            { key: 'b0_2_0_5', label: '0.2~0.5 米', batchCount: 0, share: '0' },
            { key: 'b0_5_1', label: '0.5~1 米', batchCount: 0, share: '0' },
            { key: 'gt_1', label: '>1 米', batchCount: 1, share: '100' },
          ],
        },
      },
    }),
    reconcile: vi.fn().mockResolvedValue({
      data: {
        data: {
          totalDiff: '0',
          unreconciledCount: 0,
          rows: [
            {
              skuId: 1,
              skuCode: 'SKU-MB',
              productId: 'test-product-1',
              skuStock: '100',
              batchRemaining: '100',
              inboundMeters: '120',
              dispatchedMeters: '20',
              soldDeductedMeters: '0',
              otherLedgerDeltaMeters: '0',
              unbatchedMeters: '0',
              diff: '0',
              explainedDiff: '0',
              reconciled: true,
            },
          ],
        },
      },
    }),
  },
}))

vi.mock('@/lib/request', () => ({ default: { patch: vi.fn() } }))

vi.mock('next/navigation', () => {
  const router = { push: vi.fn(), replace: vi.fn(), back: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }
  return { useRouter: () => router, usePathname: () => '/', useSearchParams: () => new URLSearchParams(), useParams: () => ({}) }
})

vi.mock('@/lib/use-route-id', () => ({ useRouteId: () => 'test-product-1' }))
vi.mock('next/image', () => ({ default: (props: any) => <img {...props} /> }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import ProductDetailPage from '@/app/(dashboard)/products/[id]/ProductDetail'

const mockProduct = {
  id: 'test-product-1',
  name: '两区探针窗帘',
  status: 'on_sale' as const,
  price: 168,
  pricingUnit: '米',
  pricingType: 'per_meter' as const,
  totalStock: 100,
  stockDeductionMode: 'on_order',
  stockWarningThreshold: 20,
  categoryName: '窗帘布',
  brand: '观星台',
  specifications: { weight: '500g' },
  colors: [{ id: 1, colorName: '米白', mainColorHex: '#F5F5DC' }],
  skus: [{ id: 1, colorId: 1, colorName: '米白', doorWidth: '2.8米', skuCode: 'SKU-MB', stock: 100, price: 168 }],
  description: '高品质窗帘布',
  images: ['data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>'],
  detailImages: [],
  createdAt: '2026-10-15 10:00:00',
  updatedAt: '2026-11-18 15:00:00',
}

describe('商品详情两区与层级（issue #8934）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetProduct.mockResolvedValue({ data: { data: mockProduct } })
  })

  async function renderLoaded() {
    render(<ProductDetailPage />)
    await waitFor(() => expect(screen.getByText('两区探针窗帘')).toBeInTheDocument())
    // 批次账三个读面都到齐后再判版式（不是加载中 / 空态）
    await screen.findByTestId('batch-remaining-table')
    await screen.findByTestId('reconcile-table')
    return {
      info: screen.getByTestId('product-info-region'),
      stock: screen.getByTestId('product-stock-region'),
    }
  }

  it('两个区域卡上下排列：商品信息在前、批次与库存在后（不穿插）', async () => {
    const { info, stock } = await renderLoaded()
    expect(
      info.compareDocumentPosition(stock) & Node.DOCUMENT_POSITION_FOLLOWING,
      '批次与库存区必须排在商品信息区之后（两个整体不穿插）',
    ).toBeTruthy()
    expect(within(info).getByRole('heading', { level: 2, name: '商品信息' })).toBeInTheDocument()
    expect(within(stock).getByRole('heading', { level: 2, name: '批次与库存' })).toBeInTheDocument()
    // 两级层级：区域 h2、子块 h3
    expect(within(info).getByRole('heading', { level: 3, name: '基本信息' })).toBeInTheDocument()
    expect(within(stock).getByRole('heading', { level: 3, name: '批次余量' })).toBeInTheDocument()
  })

  it('商品信息一个整体：六个子块全在商品信息区，批次账一块都不在', async () => {
    const { info, stock } = await renderLoaded()
    for (const id of [
      'product-basic-info',
      'product-attributes',
      'product-sales-info',
      'product-colors',
      'product-description',
      'product-images',
    ]) {
      expect(within(info).getByTestId(id), `${id} 应在商品信息区内`).toBeInTheDocument()
      expect(within(stock).queryByTestId(id), `${id} 不应出现在批次与库存区`).toBeNull()
    }
    // 旧版把批次账插在「商品属性」和「销售信息」之间 ⇒ 商品信息区内不得再出现批次账
    for (const id of ['batch-stock-panel', 'batch-remaining-table', 'batch-stocktake', 'batch-distribution', 'reconcile-table']) {
      expect(within(info).queryByTestId(id), `${id} 不应穿插进商品信息区`).toBeNull()
    }
  })

  it('批次与库存一个整体：批次余量 / 按批次盘点 / 剩余量分布 / 库存对账全在该区', async () => {
    const { info, stock } = await renderLoaded()
    expect(within(stock).getByTestId('batch-remaining-table')).toBeInTheDocument()
    expect(within(stock).getByTestId('batch-stocktake')).toBeInTheDocument()
    expect(within(stock).getByTestId('batch-distribution')).toBeInTheDocument()
    expect(within(stock).getByTestId('reconcile-table')).toBeInTheDocument()
    for (const name of ['批次余量', '按批次盘点', '剩余量分布', '库存对账']) {
      expect(within(stock).getByRole('heading', { level: 3, name })).toBeInTheDocument()
    }
    expect(within(info).queryByTestId('reconcile-table')).toBeNull()
  })

  it('库存口径只在库存区出现一次：总量 / 扣减方式 / 预警阈值不重复进商品信息区', async () => {
    const { info, stock } = await renderLoaded()
    expect(within(stock).getByTestId('stock-total')).toHaveTextContent('100')
    expect(within(info).queryByTestId('stock-total')).toBeNull()
    expect(within(info).queryByText('库存扣减方式')).toBeNull()
    expect(within(info).queryByText('库存预警阈值')).toBeNull()
    expect(within(stock).getByText('库存扣减方式')).toBeInTheDocument()
    expect(within(stock).getByText('库存预警阈值')).toBeInTheDocument()
  })

  it('无重复标题：批次余量 / 剩余量分布 / 库存对账 / 商品图片在整页各只有一处', async () => {
    await renderLoaded()
    for (const name of ['批次余量', '按批次盘点', '剩余量分布', '库存对账', '商品图片']) {
      expect(screen.getAllByRole('heading', { level: 3, name })).toHaveLength(1)
    }
  })
})
