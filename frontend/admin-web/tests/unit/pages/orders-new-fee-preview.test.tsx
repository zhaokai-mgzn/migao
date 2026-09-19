// case_ids: OR-009, OR-014, UI-038
// @vitest-environment jsdom
/**
 * 下单页「加工费计价预览」接线（issue #4450 · 前置 #4406）。
 *
 * 这一组判据守的是**拒单**：本页此前本地自算（Σ 加工项），而服务端创建订单按**选配组合取价**
 * ⇒ 页面总额 ≠ 服务端总额 ⇒ 命中「实收金额与应收不一致」校验 ⇒ **带加工项的订单提交被拒**。
 *
 * 四条判据：
 * ① 页面加工费 = **服务端**取价结果（不是本地 Σ）；
 * ② `processingInfo` 必须带**加工费米数**（`processingMeters` / `fabric_meters`）——
 *    一个都不写 ⇒ 服务端判「缺米数」⇒ 加工费按 0 计（同一 P1 的第二处缺口）；
 * ③ **预览入参 === 提交入参**（同一个 `buildLineProcessingInfo`，两处各拼一份就会再次分叉）；
 * ④ 计价失败 / 未就绪 ⇒ **拦住提交**（宁可让商家等，也不发一个必被拒的单）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const mockCreateOrder = vi.fn()
const mockGetProducts = vi.fn()
const mockGetProduct = vi.fn()
const mockGetProcessingItems = vi.fn()
const mockGetCustomers = vi.fn()
const mockCraftCalcPreview = vi.fn()
const mockFeePreview = vi.fn()

vi.mock('@/lib/api', () => ({
  orderApi: { createOrder: (...a: unknown[]) => mockCreateOrder(...a) },
  productApi: {
    getProducts: (...a: unknown[]) => mockGetProducts(...a),
    getProduct: (...a: unknown[]) => mockGetProduct(...a),
  },
  processingItemApi: { getProcessingItems: (...a: unknown[]) => mockGetProcessingItems(...a) },
  customerApi: { getCustomers: (...a: unknown[]) => mockGetCustomers(...a) },
  craftCalcApi: { preview: (...a: unknown[]) => mockCraftCalcPreview(...a) },
  feePreviewApi: { preview: (...a: unknown[]) => mockFeePreview(...a) },
}))

vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import NewOrderPage from '@/app/(dashboard)/orders/new/page'

const CALC_OK = {
  data: {
    data: {
      fabric_meters: 13.3,
      pleat_count: 52,
      per_panel_pleats: 26,
      per_fold: 0.25,
      fullness: 2,
      fullness_actual: 1.86,
      formula_text: '(6.6+0.3)×2.0 → 52折 → 0.25×52+0.3 = 13.3米',
      source: '公式计算',
      craft_tier: 'standard',
    },
  },
}

/** 服务端取价：命中组合 ¥10/米 × 13.3 米 = ¥133 */
const feeMatched = (amount = 133) => ({
  data: {
    data: {
      items: [
        {
          processingFee: amount,
          processingFeeDetail: {
            composition: '韩式褶',
            unit_price: 10,
            meters: 13.3,
            meters_source: 'processingMeters',
            fee_source: 'matched',
            amount,
            hint: null,
          },
        },
      ],
      processingFeeTotal: amount,
    },
  },
})

const inputOf = (label: string, idx = 0) =>
  screen
    .getAllByText(label)
    .map((el) => el.closest('div')!.querySelector('input') as HTMLInputElement)[idx]

/** 选商品 → 填宽高（触发算料试算 → 预填数量）→ 勾一个 per_meter 加工项 */
async function setupLine() {
  render(<NewOrderPage />)
  fireEvent.click(await screen.findByText('点击搜索并选择商品'))
  fireEvent.click(await screen.findByText('遮光窗帘'))
  await screen.findByText('宽 (米)')
  fireEvent.change(inputOf('宽 (米)'), { target: { value: '6.6' } })
  fireEvent.change(inputOf('高 (米)'), { target: { value: '2.6' } })
  await waitFor(() => expect(inputOf('数量')).toHaveValue(13.3))
  fireEvent.click(screen.getByRole('checkbox'))
}

const submit = async () => {
  fireEvent.change(screen.getByPlaceholderText('请输入收货人姓名'), { target: { value: '张三' } })
  fireEvent.change(screen.getByPlaceholderText('请输入 11 位手机号'), { target: { value: '13800138000' } })
  fireEvent.change(screen.getByPlaceholderText('请输入详细收货地址'), { target: { value: '杭州市' } })
  await waitFor(() => expect(screen.queryByText(/加工费计价中/)).toBeNull())
  fireEvent.click(screen.getByText('提交订单'))
}

describe('下单页加工费计价预览接线（#4450）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetProducts.mockResolvedValue({
      data: { data: { items: [{ id: 'p1', name: '遮光窗帘', price: 100 }], total: 1 } },
    })
    mockGetProduct.mockResolvedValue({
      data: { data: { id: 'p1', name: '遮光窗帘', skus: [], price: 100 } },
    })
    mockGetProcessingItems.mockResolvedValue({
      data: {
        data: {
          items: [
            { id: 'pi1', name: '韩式褶', unitPrice: 5, unit: '米', pricingMethod: 'per_meter' },
          ],
        },
      },
    })
    mockCraftCalcPreview.mockResolvedValue(CALC_OK)
    mockFeePreview.mockResolvedValue(feeMatched())
  })

  it('判据 1（红证）：页面加工费 = **服务端**取价（本地 Σ 是 5×13.3=66.5，服务端给 133）', async () => {
    await setupLine()
    // 服务端计价落地后，页面出现 133（**不是**本地 Σ 66.50）；
    // 133 会同时出现在「行算式」与「加工费 / 订单金额」⇒ 用 getAllByText
    await waitFor(() => expect(screen.getAllByText('¥133.00').length).toBeGreaterThanOrEqual(1))
    expect(screen.queryByText('¥66.50')).toBeNull()
    // 行算式逐字 = 服务端构成（加工费米数 × 组合单价）
    expect(screen.getByText('13.3 米 × ¥10.00/米')).toBeInTheDocument()
  })

  it('判据 2（红证）：processingInfo 带加工费米数（缺它服务端判「缺米数」⇒ 加工费按 0）', async () => {
    await setupLine()
    await submit()
    await waitFor(() => expect(mockCreateOrder).toHaveBeenCalled())

    const info = mockCreateOrder.mock.calls[0][0].items[0].processingInfo
    // `ProcessingFeeCalculator.METER_KEYS = (processingMeters, fabric_meters)` —— 两个都要落
    expect(info.processingMeters).toBe(13.3)
    expect(info.fabric_meters).toBe(13.3)
  })

  it('判据 3：**预览入参 === 提交入参**（同一个 processingInfo 构造点）', async () => {
    await setupLine()
    await submit()
    await waitFor(() => expect(mockCreateOrder).toHaveBeenCalled())

    const previewInfo = mockFeePreview.mock.calls.at(-1)![0].items[0].processingInfo
    const submitInfo = mockCreateOrder.mock.calls[0][0].items[0].processingInfo
    // 选配与米数是组合键与金额的两个因子 —— 两处必须逐值一致
    expect(previewInfo.processingItems).toEqual(submitInfo.processingItems)
    expect(previewInfo.processingMeters).toBe(submitInfo.processingMeters)
    expect(previewInfo.fabric_meters).toBe(submitInfo.fabric_meters)
  })

  it('判据 4：提交 payload 的行小计用**服务端**加工费（商品 0 + 加工 133）', async () => {
    await setupLine()
    await submit()
    await waitFor(() => expect(mockCreateOrder).toHaveBeenCalled())
    expect(mockCreateOrder.mock.calls[0][0].items[0].subtotal).toBe(1463) // 商品 13.3×¥100 = 1330 + 服务端加工费 133
  })

  it('判据 5（红证）：计价失败 ⇒ **拦住提交** + 可见提示（不得用本地估算值提交）', async () => {
    mockFeePreview.mockRejectedValue({
      response: { data: { error: { message: '加工费组合服务不可用' } } },
    })
    await setupLine()
    await waitFor(() => expect(screen.getByText(/加工费计价失败/)).toBeInTheDocument())
    await submit()
    await waitFor(() => expect(screen.getAllByText(/加工费计价失败/).length).toBeGreaterThan(0))
    expect(mockCreateOrder).not.toHaveBeenCalled()
  })

  it('判据 6：未定价 ⇒ 显式提示「未定价」，且页面金额 = 服务端值（0），不是本地 Σ', async () => {
    mockFeePreview.mockResolvedValue({
      data: {
        data: {
          items: [
            {
              processingFee: 0,
              processingFeeDetail: {
                composition: '韩式褶',
                unit_price: null,
                meters: 13.3,
                fee_source: 'unpriced',
                amount: 0,
                hint: '该组合未定价，请到加工费组合里配置',
              },
            },
          ],
          processingFeeTotal: 0,
        },
      },
    })
    await setupLine()
    await waitFor(() => expect(screen.getByText(/有 1 行加工费未定价/)).toBeInTheDocument())
    // 页面不得显示本地 Σ（66.50）
    expect(screen.queryByText('¥66.50')).toBeNull()
  })
})
