// case_ids: PR-008
// PR-008（创建商品-完整流程）：商品不再持有加工项 —— 建品/下单链路都不再经过商品维度的加工项端点。
// ⚠️ 2026-09-19（#4371 商品↔加工项解耦）：本文件把解耦**钉死**（可红）——
// ① 选商品不得调用已被删除的 `productApi.getProductProcessingItems`（旧「按商品过滤」链路）；
// ② 加工项选择器的数据来自**店铺级目录** `processingItemApi.getProcessingItems`，且只加载一次
//    （不随商品选择重复请求）；
// ③ 商品 payload 完全没有加工项字段时，选择器照旧渲染（旧实现按 supportsProcessing/hasProcessing 门禁隐藏）。
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

// Mock API：两个加工项来源都 mock —— 目录端点必须被调用，商品维度端点必须**永不**被调用
const mockCreateOrder = vi.fn()
const mockGetProducts = vi.fn()
const mockGetProduct = vi.fn()
const mockGetProductProcessingItems = vi.fn()
const mockGetProcessingItems = vi.fn()
const mockGetCustomers = vi.fn()

vi.mock('@/lib/api', () => ({
  orderApi: {
    createOrder: (...args: any[]) => mockCreateOrder(...args),
  },
  productApi: {
    getProducts: (...args: any[]) => mockGetProducts(...args),
    getProduct: (...args: any[]) => mockGetProduct(...args),
    getProductProcessingItems: (...args: any[]) => mockGetProductProcessingItems(...args),
  },
  processingItemApi: {
    getProcessingItems: (...args: any[]) => mockGetProcessingItems(...args),
  },
  customerApi: {
    getCustomers: (...args: any[]) => mockGetCustomers(...args),
  },
  // 算料试算（#4434）：本文件验的是商品↔加工项解耦，与算料正交 ⇒ 停在「进行中」
  craftCalcApi: { preview: () => new Promise(() => {}) },
  // 加工费计价预览（#4450）：同样正交 ⇒ 桩成「组合价 == Σ 加工项」的服务端
  // （数值与旧口径一致 ⇒ 本文件断言不变）。**必须 resolve**：未就绪时页面会拦住提交。
  feePreviewApi: {
    preview: (payload: any) => {
      const items = (payload?.items ?? []).map((it: any) => {
        const details = it?.processingInfo?.processingItems ?? []
        const fee = details.reduce(
          (s: number, d: any) => s + (Number(d.unitPrice) || 0) * (Number(d.quantity) || 0),
          0
        )
        return { processingFee: fee, processingFeeDetail: { fee_source: 'matched', amount: fee } }
      })
      const processingFeeTotal = items.reduce((s: number, r: any) => s + r.processingFee, 0)
      return Promise.resolve({ data: { data: { items, processingFeeTotal } } })
    },
  },
}))

vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

import NewOrderPage from '@/app/(dashboard)/orders/new/page'

// 商品 payload 里**没有任何加工项字段**（解耦后的真实形态）
const productWithoutProcessing = {
  id: 'p1',
  name: '遮光窗帘',
  price: 100,
  skus: [],
}

// 店铺级加工项目录
const shopCatalog = [
  { id: 'pi1', name: '打孔加工', pricingMethod: 'per_meter', unitPrice: 5, unit: '米' },
  { id: 'pi2', name: '韩式定型', pricingMethod: 'per_set', unitPrice: 8, unit: '套' },
]

describe('NewOrderPage — 商品↔加工项解耦（#4371）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetProducts.mockResolvedValue({
      data: { data: { items: [productWithoutProcessing], total: 1 } },
    })
    mockGetProduct.mockResolvedValue({ data: { data: productWithoutProcessing } })
    mockGetProcessingItems.mockResolvedValue({ data: { data: { items: shopCatalog } } })
    // 旧端点若被调用即失败（断言「永不调用」）
    mockGetProductProcessingItems.mockRejectedValue(new Error('端点已删除，不应被调用'))
  })

  it('挂载时加载店铺级加工项目录（只加载一次）', async () => {
    render(<NewOrderPage />)
    await waitFor(() => {
      expect(mockGetProcessingItems).toHaveBeenCalledTimes(1)
    })
    expect(mockGetProcessingItems).toHaveBeenCalledWith({ page: 1, size: 100 })
  })

  it('选商品后仍不调用商品维度加工项端点，选择器来自店铺级目录', async () => {
    render(<NewOrderPage />)

    fireEvent.click(await screen.findByText('点击搜索并选择商品'))
    fireEvent.click(await screen.findByText('遮光窗帘'))

    // 商品 payload 无 supportsProcessing/hasProcessing，旧实现会把选择器整块隐藏
    await waitFor(() => {
      expect(screen.getByText('加工选项（可选）')).toBeInTheDocument()
    })
    // 目录里的加工项渲染为可选行
    expect(await screen.findByText('打孔加工')).toBeInTheDocument()
    expect(screen.getByText('韩式定型')).toBeInTheDocument()
    expect(screen.getAllByRole('checkbox')).toHaveLength(shopCatalog.length)

    // 旧链路（按商品过滤）从未被触发
    expect(mockGetProductProcessingItems).not.toHaveBeenCalled()
    // 目录不随商品选择重复请求
    expect(mockGetProcessingItems).toHaveBeenCalledTimes(1)
  })

  it('目录加载完成后选商品，加工项仍可选并计入加工费', async () => {
    render(<NewOrderPage />)
    // 先等目录就绪，再选商品（真实用户路径）
    await waitFor(() => {
      expect(mockGetProcessingItems).toHaveBeenCalledTimes(1)
    })

    fireEvent.click(await screen.findByText('点击搜索并选择商品'))
    fireEvent.click(await screen.findByText('遮光窗帘'))
    // 勾选目录第一项（打孔加工，按米 5 元）—— 等选择器渲染完再点
    const checkboxes = await screen.findAllByRole('checkbox')
    fireEvent.click(checkboxes[0])

    await waitFor(() => {
      expect(screen.getByText('加工费').closest('div')!.textContent).toContain('¥5.00')
    })
    expect(mockGetProductProcessingItems).not.toHaveBeenCalled()
  })
})
