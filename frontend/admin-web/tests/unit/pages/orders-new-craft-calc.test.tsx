// case_ids: OR-036
// 原声明 `OR-009, OR-014, UI-038` 是**借用式**（issue #4431 B7 核实并替换）：OR-009 是下单全流程、
// OR-014 是下单加工项数量规则、UI-038 是「选择已有客户回填收货信息」—— 三条都不覆盖本文件被测行为
// （下单页算料试算接线：褶数法自动算 + 公式串 + 四条 fail-closed）。
// 改用 **OR-036**（本 PR 新增，判据即本文件 + craft-calc-request.test.ts）。
// @vitest-environment jsdom
/**
 * 下单页「算料试算」接线（issue #4434 · 前置 #4421）。
 *
 * 判据聚焦用户裁定的「用料米数按褶数法自动算 + 把计算公式体现出来」，以及三条 fail-closed：
 * ① 宽高齐全 ⇒ 试算并**预填数量** + 展示**后端产出的公式串**；
 * ② 手改数量 ⇒ 标记「人工指定」，**试算不得静默改回**（只能显式「恢复按公式计算」）；
 * ③ 试算失败 ⇒ 行内显式提示，数量保持原样（**不退回任何估算值**）；
 * ④ 参数不全 ⇒ **不发请求**（不得用默认窗宽猜一个米数）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'

const mockCreateOrder = vi.fn()
const mockGetProducts = vi.fn()
const mockGetProduct = vi.fn()
const mockGetProcessingItems = vi.fn()
const mockGetCustomers = vi.fn()
const mockCraftCalcPreview = vi.fn()
/** 算料配置读面（issue #4874）——「配置读不到 ⇒ 显式提示」那条判据要能把它切成失败 */
const mockGetCraftCalcConfig = vi.fn()

vi.mock('@/lib/api', () => ({
  orderApi: { createOrder: (...a: unknown[]) => mockCreateOrder(...a) },
  productApi: {
    getProducts: (...a: unknown[]) => mockGetProducts(...a),
    getProduct: (...a: unknown[]) => mockGetProduct(...a),
  },
  processingItemApi: { getProcessingItems: (...a: unknown[]) => mockGetProcessingItems(...a) },
  customerApi: { getCustomers: (...a: unknown[]) => mockGetCustomers(...a) },
  craftCalcApi: { preview: (...a: unknown[]) => mockCraftCalcPreview(...a) },
  // **自动特征判定端点**（issue #4976 包 2b）：判定已移到服务端 ⇒ 页面挂载即请求。
  // 本文件与「自动特征」正交 ⇒ 服务端替身返回**不判**（`missing-door-width`）。
  // ⚠️ 必须**返回**：判定缺席会被提交闸门拦住 ⇒ 本文件无关的断言会连带红。
  autoFeaturesApi: {
    preview: () =>
      Promise.resolve({
        data: { data: { auto_features: [], door_width: null, fullness_used: 2.0, notice: 'missing-door-width' } },
      }),
  },
  // **算料配置读面**（issue #4874）：用料公式缺省 + 档位 chips 的值域/文案都来自它
  // （`GET /api/admin/production/craft-calc-config`）⇒ 页面挂载即请求。
  productionApi: {
    getCraftCalcConfig: (...a: unknown[]) => mockGetCraftCalcConfig(...a),
  },
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

/**
 * 算料配置读面桩（issue #4874）——档位**值域与文案都取自这里**（页面不写死档位真值）。
 * `label` 刻意与键名不同字，便于断言「chips 文案确实来自配置」。
 */
const CALC_CONFIG_OK = {
  data: {
    data: {
      source: 'stored',
      config: {
        per_fold_single: 0.25,
        per_fold_mixed_times: {},
        margin_single: 0.3,
        margin_multi: 0.3,
        min_fullness: 1.5,
        tiers: {
          standard: { fullness: 2.0, label: '标准档（2.0倍）' },
          economy: { fullness: 1.8, label: '经济档（1.8倍）' },
        },
        default_formula: 'pleat',
        side_margin: 0.15,
        meters_rounding_step: 0.1,
      },
    },
  },
}

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

// 帘（成品）行的米数输入框（issue #4598 起 label = 「用料米数」，旧文案「数量」）——
// 它就是**加工费米数**（`info.processingMeters = line.quantity`），也是试算写回的目标字段。
const qtyInput = (idx = 0) => inputOf('用料米数', idx)

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
    mockGetCraftCalcConfig.mockResolvedValue(CALC_CONFIG_OK)
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
      const backendFormula = '韩褶公式（商家自定义档）：(6.6+0.3)×2 → 52折 → 0.25×52+0.3 = 7.7米'
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

// ══════════════════════════════════════════════════════════════════════════
// issue #4874（用户 2026-09-21）：「**加上用料公式字段**，如果选择韩褶公式，那就自动算出褶数，
// 如果选择的是褶倍数公式，那就展示是经济档还是标准档，这里需要**和工艺配置的算料配置保持一致**」
//
// ⇒ 值域与文案**一律从算料配置读面取**（`GET /api/admin/production/craft-calc-config`），
// 档位进算料请求 `craft_tier` **并且**落库 `processingInfo.craftTier`（不再钉死 `standard`）。
// ══════════════════════════════════════════════════════════════════════════
describe('#4874 用料公式 / 档位（与「工艺配置 → 算料配置」同源）', () => {
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
    mockGetCraftCalcConfig.mockResolvedValue(CALC_CONFIG_OK)
  })

  /** 展开**区块 1**（尺寸与数量 · 工艺规格）—— issue #4874 两步化后的新锚点 */
  const openStep1 = () => {
    const btn = screen.getAllByRole('button', { name: /^\d+ 尺寸与数量/ })[0]
    if (btn.getAttribute('aria-expanded') === 'false') fireEvent.click(btn)
  }
  const formulaRadio = (name: string) =>
    within(screen.getByRole('radiogroup', { name: '用料公式' })).getByRole('radio', { name })

  it('判据 1（红证）：缺省公式 = 算料配置的 `default_formula`，且选韩褶公式 ⇒ 展示**自动算出的褶数**', async () => {
    render(<NewOrderPage />)
    await pickProduct()
    openStep1()
    // 红证（改前）：页面既没有「用料公式」控件，也没有褶数展示块 ⇒ 下面两行必红
    expect(formulaRadio('韩褶公式（褶数法）')).toHaveAttribute('aria-checked', 'true')
    // 试算还没发（宽高未填）⇒ 褶数是「—」：**不编数**
    expect(within(screen.getByTestId('craft-pleat-count')).getByText('—')).toBeInTheDocument()

    fireEvent.change(inputOf('宽 (米)'), { target: { value: '6.6' } })
    fireEvent.change(inputOf('高 (米)'), { target: { value: '2.6' } })
    // 试算回来（`pleat_count: 52`）⇒ 褶数展示**照抄响应**（页面不自己算褶数）
    await waitFor(() =>
      expect(
        within(screen.getByTestId('craft-pleat-count')).getByText('52')
      ).toBeInTheDocument()
    )
    expect(mockCraftCalcPreview.mock.calls[0][0]).toMatchObject({
      formula: 'pleat',
      // 缺省档 = 配置里**真实存在**的档位键（fixture 里 standard 在 ⇒ 用它）
      craft_tier: 'standard',
    })
  })

  it('判据 2（红证）：选褶倍数公式 ⇒ 出现档位 chips，文案逐字 = 算料配置 `tiers[*].label`', async () => {
    render(<NewOrderPage />)
    await pickProduct()
    openStep1()
    fireEvent.click(formulaRadio('褶倍数公式（倍数法）'))

    const tiers = await screen.findByTestId('craft-tier-options')
    // fixture label 与键名不同字（`标准档（2.0倍）` ≠ `standard`）⇒ 页面写死中文档位名必红
    expect(
      within(tiers)
        .getAllByRole('radio')
        .map((r) => r.textContent)
    ).toEqual(['标准档（2.0倍）', '经济档（1.8倍）'])
    // 褶数块只在韩褶公式下出现
    expect(screen.queryByTestId('craft-pleat-count')).toBeNull()
  })

  it('判据 3（红证）：改档位 ⇒ 算料请求 `craft_tier` 与落库 `processingInfo.craftTier` 都是所选档', async () => {
    render(<NewOrderPage />)
    await pickProduct()
    openStep1()
    fireEvent.change(inputOf('宽 (米)'), { target: { value: '6.6' } })
    fireEvent.change(inputOf('高 (米)'), { target: { value: '2.6' } })
    await waitFor(() => expect(mockCraftCalcPreview).toHaveBeenCalledTimes(1))

    fireEvent.click(formulaRadio('褶倍数公式（倍数法）'))
    fireEvent.click(
      within(await screen.findByTestId('craft-tier-options')).getByRole('radio', {
        name: '经济档（1.8倍）',
      })
    )
    // 签名变化（formula / craft_tier 都进了签名）⇒ 必须重发试算，且带上所选档
    await waitFor(() => {
      const params = mockCraftCalcPreview.mock.calls.map((c) => c[0])
      expect(params.some((p) => p.formula === 'fullness' && p.craft_tier === 'economy')).toBe(true)
    })

    await submitOrder()
    await waitFor(() => expect(mockCreateOrder).toHaveBeenCalled())
    // 落库同源（改前 `craft_tier` 钉死 standard、`craftTier` 键根本不存在）
    expect(mockCreateOrder.mock.calls[0][0].items[0].processingInfo.craftTier).toBe('economy')
  })

  it('判据 4（不静默·红证）：算料配置读不到 ⇒ 按缺省（pleat + standard）走 **且显式提示**', async () => {
    mockGetCraftCalcConfig.mockRejectedValue(new Error('boom'))
    render(<NewOrderPage />)
    await pickProduct()
    // 红证：改前没有这个提示元素（配置读不到时页面**静默**按钉死的档位算）
    expect(await screen.findByTestId('craft-calc-config-missing')).toBeInTheDocument()
    openStep1()
    // 公式值域与引擎常量同源（不依赖配置）⇒ chips 仍在；档位值域取不到 ⇒ 不渲染 chips
    expect(formulaRadio('韩褶公式（褶数法）')).toHaveAttribute('aria-checked', 'true')
    expect(screen.queryByTestId('craft-tier-options')).toBeNull()

    fireEvent.change(inputOf('宽 (米)'), { target: { value: '6.6' } })
    fireEvent.change(inputOf('高 (米)'), { target: { value: '2.6' } })
    await waitFor(() => expect(mockCraftCalcPreview).toHaveBeenCalled())
    // 不阻断录入：试算照发，缺省档 = 常量 `standard`
    expect(mockCraftCalcPreview.mock.calls.at(-1)![0]).toMatchObject({
      craft_tier: 'standard',
      formula: 'pleat',
    })
  })
})
