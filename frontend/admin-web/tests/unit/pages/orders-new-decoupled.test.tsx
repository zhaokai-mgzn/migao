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
  // **算料配置读面**（issue #4874）：公式缺省 + 档位 chips 的值域/文案都来自它 ⇒ 挂载即请求
  productionApi: {
    getCraftCalcConfig: () =>
      Promise.resolve({
        data: {
          data: {
            source: 'default',
            config: {
              per_fold_single: 0.25,
              per_fold_mixed_times: {},
              margin_single: 0.3,
              margin_multi: 0.3,
              min_fullness: 1.5,
              tiers: { standard: { fullness: 2.0, label: '标准档' } },
              default_formula: 'pleat',
              side_margin: 0.15,
              meters_rounding_step: 0.1,
            },
          },
        },
      }),
  },
  // 算料试算（#4434）：本文件验的是商品↔加工项解耦，与算料正交 ⇒ 停在「进行中」
  craftCalcApi: { preview: () => new Promise(() => {}) },
  // 加工费计价预览（#4450）：同样正交 ⇒ 桩成「组合价 5 元/米 × 加工费米数」的服务端。
  // ⚠️ #4882：加工项**没有单价了** ⇒ 桩不能再按 `Σ 加工项单价 × 数量` 求和（会恒为 0，
  // 把下面的 ¥5.00 判据打成假红）；改为按加工项数量（= 加工费米数）乘组合单价。
  // **必须 resolve**：未就绪时页面会拦住提交。
  feePreviewApi: {
    preview: (payload: any) => {
      const COMBO_UNIT_PRICE = 5 // 组合价目（元/米）—— 本桩唯一的价格真值
      const items = (payload?.items ?? []).map((it: any) => {
        const details = it?.processingInfo?.processingItems ?? []
        const fee =
          details.reduce((s: number, d: any) => s + (Number(d.quantity) || 0), 0) * COMBO_UNIT_PRICE
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

// 店铺级加工项目录（#4882：无 `unitPrice` / `pricingMethod` —— 加工项只是可选服务目录）
const shopCatalog = [
  { id: 'pi1', name: '打孔加工', unit: '米' },
  { id: 'pi2', name: '韩式定型', unit: '米' },
]

/** 展开向导③「加工项」步骤（issue #4511 手风琴；#4489 判据 3：默认收起） */
const expandProcessing = () => {
  const btns = screen.getAllByRole('button', { name: /^\d+ 加工项/ })
  if (btns.length && btns[0].getAttribute('aria-expanded') === 'false') fireEvent.click(btns[0])
}

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

    // #4508：空态不渲染组壳 ⇒ 先等商品落地（组壳出现）才有「加工选项」
    await screen.findByText('帘体')
    // 商品 payload 无 supportsProcessing/hasProcessing，旧实现会把选择器整块隐藏
    // issue #4489 判据 3：加工选项**默认折叠** ⇒ 断言折叠头（不再是一段静态文案）
    expect(screen.getByRole('button', { name: /^\d+ 加工项/ })).toBeInTheDocument()
    expandProcessing()
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
    // #4508：先等商品落地（空态没有组壳 ⇒ 没有加工选项）
    await screen.findByText('帘体')
    // 勾选目录第一项（打孔加工，按米 5 元）—— 等选择器渲染完再点
    expandProcessing()
    const checkboxes = await screen.findAllByRole('checkbox')
    fireEvent.click(checkboxes[0])

    await waitFor(() => {
      expect(screen.getByText('加工费').closest('div')!.textContent).toContain('¥5.00')
    })
    expect(mockGetProductProcessingItems).not.toHaveBeenCalled()
  })
})
