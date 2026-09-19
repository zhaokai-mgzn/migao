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
  // 加工费计价预览（issue #4450）：本文件验的是**算料试算**接线，与加工费取价正交
  // ⇒ 桩成「无加工项 ⇒ 加工费 0」的服务端（本文件各用例都没选加工项）。
  // **必须 resolve**：预览未就绪时页面会拦住提交。
  feePreviewApi: {
    preview: (payload: { items?: Array<{ processingInfo?: { processingItems?: unknown[] } }> }) => {
      const items = (payload?.items ?? []).map(() => ({
        processingFee: 0,
        processingFeeDetail: { fee_source: 'unpriced', amount: 0 },
      }))
      return Promise.resolve({ data: { data: { items, processingFeeTotal: 0 } } })
    },
  },
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

/** 填收货信息 → 等计价就绪 → 提交（落库 payload 的判据用；与 fee-preview 测试同一套流程） */
const submitOrder = async () => {
  fireEvent.change(screen.getByPlaceholderText('请输入收货人姓名'), { target: { value: '张三' } })
  fireEvent.change(screen.getByPlaceholderText('请输入 11 位手机号'), {
    target: { value: '13800138000' },
  })
  fireEvent.change(screen.getByPlaceholderText('请输入详细收货地址'), {
    target: { value: '杭州市' },
  })
  await waitFor(() => expect(screen.queryByText(/加工费计价中/)).toBeNull())
  fireEvent.click(screen.getByText('提交订单'))
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
    // issue #4493：宽 → 打开方式联动（真值源 §10：>5m 四开）⇒ 入参带 open_count=4
    expect(mockCraftCalcPreview.mock.calls[0][0]).toMatchObject({
      width: 6.6,
      height: 2.6,
      open_count: 4,
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

  it('#4527 打孔 ⇒ **照常发请求**且走倍数法（eyelet + fullness）——「打孔按倍数法算布料」必须在页面上真的发生', async () => {
    // ⚠️ #4566（用户 2026-09-19 裁定「工艺…直接通过加工项来勾选」）：工艺不再是「工艺规格」里的
    // 选择器 ⇒ 从**加工项**勾选（目录形状 = V83 种子：名字「打孔」+ `craftHint='打孔'`）。
    mockGetProcessingItems.mockResolvedValue({
      data: {
        data: {
          items: [
            {
              id: 'pi-punch',
              name: '打孔',
              craftHint: '打孔',
              pricingMethod: 'per_meter',
              unitPrice: 0,
              unit: '米',
            },
          ],
        },
      },
    })
    render(<NewOrderPage />)
    await pickProduct()
    fireEvent.change(inputOf('宽 (米)'), { target: { value: '6.6' } })
    fireEvent.change(inputOf('高 (米)'), { target: { value: '2.6' } })
    await waitFor(() => expect(mockCraftCalcPreview).toHaveBeenCalledTimes(1))

    mockCraftCalcPreview.mockClear()
    // issue #4511 手风琴：加工项是向导③ ⇒ 先展开该步，再勾选（勾选即改入参签名 ⇒ 重发试算）
    const processingStep = screen.getAllByRole('button', { name: /^\d+ 加工项/ })[0]
    if (processingStep.getAttribute('aria-expanded') === 'false') fireEvent.click(processingStep)
    fireEvent.click(await screen.findByRole('checkbox', { name: '打孔' }))
    // 旧口径下打孔返回 null ⇒ 永不发请求 ⇒ 本断言红（这正是本条要防的形态）
    await waitFor(() => expect(mockCraftCalcPreview).toHaveBeenCalledTimes(1))
    expect(mockCraftCalcPreview.mock.calls[0][0]).toMatchObject({
      craft: '打孔',
      mounting: 'eyelet',
      formula: 'fullness',
    })
  })

  it('判据 7：无自动算料口径的工艺（穿杆）⇒ 不发请求（后端答不出）', async () => {
    // ⚠️ #4566：工艺从加工项派生 ⇒ 本判据改用 V83 目录里的「穿杆」（`craftHint='穿杆'`，
    // `curtain_calc` 无该工艺的自动算料口径）。
    // 原判据用「四爪钩」——它**不在** V83 加工项目录里（是配件，不是打褶方式；归属 #4365 阶段 2）
    // ⇒ 下单页已不可达（已知取舍）。`isAutoCalcUnavailable('四爪钩')` 的**纯函数**判据仍保留在
    // `craft-calc-request.test.ts`（口径本身没丢，只是页面入口随裁定退场）。
    mockGetProcessingItems.mockResolvedValue({
      data: {
        data: {
          items: [
            {
              id: 'pi-rod',
              name: '穿杆',
              craftHint: '穿杆',
              pricingMethod: 'per_meter',
              unitPrice: 0,
              unit: '米',
            },
          ],
        },
      },
    })
    render(<NewOrderPage />)
    await pickProduct()
    fireEvent.change(inputOf('宽 (米)'), { target: { value: '6.6' } })
    fireEvent.change(inputOf('高 (米)'), { target: { value: '2.6' } })
    await waitFor(() => expect(mockCraftCalcPreview).toHaveBeenCalledTimes(1))

    mockCraftCalcPreview.mockClear()
    const processingStep = screen.getAllByRole('button', { name: /^\d+ 加工项/ })[0]
    if (processingStep.getAttribute('aria-expanded') === 'false') fireEvent.click(processingStep)
    fireEvent.click(await screen.findByRole('checkbox', { name: '穿杆' }))
    await new Promise((r) => setTimeout(r, 600))
    expect(mockCraftCalcPreview).not.toHaveBeenCalled()
  })

  // issue #4546：算料公式串**落库**（详情页要能告知商家「用料是怎么算出来的」）。
  // 真值源仍是算料试算响应 —— 前端只**透传**，不拼串（拼串 = 第二份算料逻辑）。
  describe('算料公式串落库（#4546）', () => {
    it('判据 1/3（红证）：提交 payload 的 formulaText **逐字** = 试算响应的 formula_text（前端不得自拼）', async () => {
      // 注入法：刻意让后端串里的数值与 `fabric_meters`（13.3）**不一致**（这里写 7.7米）——
      // 前端若按数字自拼，产出必然 ≠ 本串 ⇒ 本断言红。正解 = 只从试算响应取。
      const backendFormula = '韩折公式（商家自定义档）：(6.6+0.3)×2 → 52折 → 0.25×52+0.3 = 7.7米'
      mockCraftCalcPreview.mockResolvedValue({
        data: { data: { ...CALC_OK.data.data, formula_text: backendFormula } },
      })

      render(<NewOrderPage />)
      await pickProduct()
      fireEvent.change(inputOf('宽 (米)'), { target: { value: '6.6' } })
      fireEvent.change(inputOf('高 (米)'), { target: { value: '2.6' } })
      await waitFor(() => expect(qtyInput()).toHaveValue(13.3))
      await submitOrder()
      await waitFor(() => expect(mockCreateOrder).toHaveBeenCalled())

      const info = mockCreateOrder.mock.calls[0][0].items[0].processingInfo
      expect(info.formulaText).toBe(backendFormula)
    })

    it('判据 5（红证）：无试算结果 ⇒ **不写该键**（写空串 / 写 undefined 都算红）', async () => {
      mockCraftCalcPreview.mockRejectedValue({
        response: { data: { error: { message: '算料服务不可用' } } },
      })

      render(<NewOrderPage />)
      await pickProduct()
      fireEvent.change(inputOf('宽 (米)'), { target: { value: '6.6' } })
      fireEvent.change(inputOf('高 (米)'), { target: { value: '2.6' } })
      await waitFor(() => expect(screen.getByText(/算料试算失败/)).toBeInTheDocument())
      await submitOrder()
      await waitFor(() => expect(mockCreateOrder).toHaveBeenCalled())

      const info = mockCreateOrder.mock.calls[0][0].items[0].processingInfo
      // 键**整个缺席**（不是空串、也不是值为 undefined 的键）⇒ 详情页不会多出一行空值
      expect(Object.keys(info)).not.toContain('formulaText')
    })
  })
})
