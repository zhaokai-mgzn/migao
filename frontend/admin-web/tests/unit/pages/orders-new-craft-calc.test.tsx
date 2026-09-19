// case_ids: OR-036
// 原声明 `OR-009, OR-014, UI-038` 是**借用式**（issue #4431 B7 核实并替换）：OR-009 是下单全流程、
// OR-014 是下单加工项数量规则、UI-038 是「选择已有客户回填收货信息」—— 三条都不覆盖本文件被测行为
// （下单页算料试算接线：折数法自动算 + 公式串 + 四条 fail-closed）。
// 改用 **OR-036**（本 PR 新增，判据即本文件 + craft-calc-request.test.ts）。
// @vitest-environment jsdom
/**
 * 下单页「算料试算」接线（issue #4434 · 前置 #4421）。
 *
 * 判据聚焦用户裁定的「用料米数按折数法自动算 + 把计算公式体现出来」，以及三条 fail-closed：
 * ① 宽高齐全 ⇒ 试算并**预填数量** + 展示**后端产出的公式串**；
 * ② 手改数量 ⇒ 标记「人工指定」，**试算不得静默改回**（只能显式「恢复按公式计算」）；
 * ③ 试算失败 ⇒ 行内显式提示，数量保持原样（**不退回任何估算值**）；
 * ④ 参数不全 ⇒ **不发请求**（不得用默认窗宽猜一个米数）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const mockCreateOrder = vi.fn()
const mockGetProducts = vi.fn()
const mockGetProduct = vi.fn()
const mockGetProcessingItems = vi.fn()
const mockGetCustomers = vi.fn()
const mockCraftCalcPreview = vi.fn()

vi.mock('@/lib/api', () => ({
  orderApi: { createOrder: (...a: unknown[]) => mockCreateOrder(...a) },
  productApi: {
    getProducts: (...a: unknown[]) => mockGetProducts(...a),
    getProduct: (...a: unknown[]) => mockGetProduct(...a),
  },
  processingItemApi: { getProcessingItems: (...a: unknown[]) => mockGetProcessingItems(...a) },
  customerApi: { getCustomers: (...a: unknown[]) => mockGetCustomers(...a) },
  craftCalcApi: { preview: (...a: unknown[]) => mockCraftCalcPreview(...a) },
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

/** 52 折双开 / 标准档 2.0 的算料结果（真值源 §8 算例口径） */
const CALC_OK = {
  data: {
    data: {
      fabric_meters: 13.3,
      pleat_count: 52,
      per_panel_pleats: 26,
      per_fold: 0.25,
      fullness: 2,
      fullness_actual: 1.86,
      formula_used: 'fixed_height_pleats',
      formula_text: '(6.6+0.3)×2.0 → 52折 → 0.25×52+0.3 = 13.3米',
      source: '公式计算',
      craft_tier: 'standard',
    },
  },
}

/** 按 label 文本定位其所在容器里的 input（`Label` 无 htmlFor 关联） */
const inputOf = (label: string, idx = 0) =>
  screen
    .getAllByText(label)
    .map((el) => el.closest('div')!.querySelector('input') as HTMLInputElement)[idx]

const qtyInput = (idx = 0) => inputOf('数量', idx)

const pickProduct = async () => {
  fireEvent.click(await screen.findByText('点击搜索并选择商品'))
  fireEvent.click(await screen.findByText('遮光窗帘'))
  await screen.findByText('宽 (米)')
}

describe('下单页算料试算接线（#4434）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetProducts.mockResolvedValue({
      data: { data: { items: [{ id: 'p1', name: '遮光窗帘', price: 100 }], total: 1 } },
    })
    mockGetProduct.mockResolvedValue({
      data: { data: { id: 'p1', name: '遮光窗帘', skus: [], price: 100 } },
    })
    mockGetProcessingItems.mockResolvedValue({ data: { data: { items: [] } } })
    mockCraftCalcPreview.mockResolvedValue(CALC_OK)
  })

  it('判据 1（红证）：宽高齐全 ⇒ 试算并预填数量 + 展示后端公式串（修复前数量恒为手填 1）', async () => {
    render(<NewOrderPage />)
    await pickProduct()

    fireEvent.change(inputOf('宽 (米)'), { target: { value: '6.6' } })
    fireEvent.change(inputOf('高 (米)'), { target: { value: '2.6' } })

    await waitFor(() => expect(mockCraftCalcPreview).toHaveBeenCalledTimes(1))
    // 入参 = 标准档 + 韩褶 + 开数（缺省 1）；**前端不补默认值、不重算**
    expect(mockCraftCalcPreview.mock.calls[0][0]).toMatchObject({
      width: 6.6,
      height: 2.6,
      open_count: 1,
      mounting: 's_hook',
      craft_tier: 'standard',
    })

    await waitFor(() => expect(qtyInput()).toHaveValue(13.3))
    // 公式串**原样渲染后端产出**（前端不得自拼）
    expect(screen.getByText(/0\.25×52\+0\.3 = 13\.3米/)).toBeInTheDocument()
  })

  it('判据 2：改宽 ⇒ 重新试算并更新数量（防抖后）', async () => {
    render(<NewOrderPage />)
    await pickProduct()
    fireEvent.change(inputOf('宽 (米)'), { target: { value: '6.6' } })
    fireEvent.change(inputOf('高 (米)'), { target: { value: '2.6' } })
    await waitFor(() => expect(qtyInput()).toHaveValue(13.3))

    mockCraftCalcPreview.mockResolvedValue({
      data: {
        data: {
          ...CALC_OK.data.data,
          fabric_meters: 9.8,
          pleat_count: 38,
          formula_text: '(5+0.3)×2.0 → 38折 → 0.25×38+0.3 = 9.8米',
        },
      },
    })
    fireEvent.change(inputOf('宽 (米)'), { target: { value: '5' } })

    await waitFor(() => expect(qtyInput()).toHaveValue(9.8))
    expect(screen.getByText(/= 9\.8米/)).toBeInTheDocument()
  })

  it('判据 3（红证）：手改数量 ⇒ 标记「人工指定」，且**不被试算静默改回**', async () => {
    render(<NewOrderPage />)
    await pickProduct()
    fireEvent.change(inputOf('宽 (米)'), { target: { value: '6.6' } })
    fireEvent.change(inputOf('高 (米)'), { target: { value: '2.6' } })
    await waitFor(() => expect(qtyInput()).toHaveValue(13.3))

    // 商家手改（真值源 §8：用料必须带来源）
    fireEvent.change(qtyInput(), { target: { value: '20' } })
    expect(qtyInput()).toHaveValue(20)
    expect(screen.getByText('人工指定')).toBeInTheDocument()

    // 再改宽：**不得**触发试算覆盖手工值
    fireEvent.change(inputOf('宽 (米)'), { target: { value: '5' } })
    // 负向断言没有可等的元素 ⇒ 等一个短窗口后确认请求数没涨、值没被改
    await new Promise((r) => setTimeout(r, 600))
    expect(mockCraftCalcPreview).toHaveBeenCalledTimes(1)
    expect(qtyInput()).toHaveValue(20)
  })

  it('判据 4：点「恢复按公式计算」⇒ 显式切回并重新预填（唯一的回切通道）', async () => {
    render(<NewOrderPage />)
    await pickProduct()
    fireEvent.change(inputOf('宽 (米)'), { target: { value: '6.6' } })
    fireEvent.change(inputOf('高 (米)'), { target: { value: '2.6' } })
    await waitFor(() => expect(qtyInput()).toHaveValue(13.3))

    fireEvent.change(qtyInput(), { target: { value: '20' } })
    fireEvent.click(screen.getByRole('button', { name: '恢复按公式计算' }))

    await waitFor(() => expect(mockCraftCalcPreview).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(qtyInput()).toHaveValue(13.3))
  })

  it('判据 5（红证）：试算失败 ⇒ 行内显式提示，数量保持原样（不退回估算值）', async () => {
    mockCraftCalcPreview.mockRejectedValue({
      response: {
        data: { error: { message: '特殊选项「拼3次」的拼色用料系数纸表未登记' } },
      },
    })
    render(<NewOrderPage />)
    await pickProduct()
    fireEvent.change(inputOf('宽 (米)'), { target: { value: '6.6' } })
    fireEvent.change(inputOf('高 (米)'), { target: { value: '2.6' } })

    await waitFor(() =>
      expect(screen.getByText(/算料试算失败.*拼3次/)).toBeInTheDocument()
    )
    // 数量保持原样（默认 1）—— **绝不**静默估一个米数
    expect(qtyInput()).toHaveValue(1)
  })

  it('判据 6：参数不全（只有宽没有高）⇒ **不发请求**（不得用默认窗宽猜米数）', async () => {
    render(<NewOrderPage />)
    await pickProduct()
    fireEvent.change(inputOf('宽 (米)'), { target: { value: '6.6' } })
    // 负向断言：等过防抖窗口后确认一次请求都没发
    await new Promise((r) => setTimeout(r, 600))
    expect(mockCraftCalcPreview).not.toHaveBeenCalled()
    expect(qtyInput()).toHaveValue(1)
  })

  it('判据 7：非韩褶工艺（打孔）⇒ 不发请求（折数法不适用，后端会 400）', async () => {
    render(<NewOrderPage />)
    await pickProduct()
    fireEvent.change(inputOf('宽 (米)'), { target: { value: '6.6' } })
    fireEvent.change(inputOf('高 (米)'), { target: { value: '2.6' } })
    await waitFor(() => expect(mockCraftCalcPreview).toHaveBeenCalledTimes(1))

    mockCraftCalcPreview.mockClear()
    fireEvent.change(screen.getByLabelText('工艺'), { target: { value: '打孔' } })
    await new Promise((r) => setTimeout(r, 600))
    expect(mockCraftCalcPreview).not.toHaveBeenCalled()
  })
})
