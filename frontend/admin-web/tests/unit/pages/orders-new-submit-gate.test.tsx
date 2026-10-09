// case_ids: OR-054
/**
 * 下单页提交闸门补全 + 「哪儿缺了」的可达性（issue #5840）
 *
 * 用户报障（2026-10-01 逐字）：「未输入加工费组合价格但是提交成功了，缺少了必要的校验」，
 * 并要求「涉及到关键信息，比如金额，工艺，物流等信息未填入时，或者推算的用料米数和实际填入的
 * 不匹配上，都要提示用户，另外要注意区域折叠状态下如何让用户知道具体是哪儿的信息缺失」。
 *
 * 本文件钉住的口径（用户 2026-10-01 逐条裁定，**不是**实现者自拟）：
 *  1. 加工费组合**未定价且组合键非空** ⇒ **阻断提交**（钱算不出来 ⇒ 不允许落一张错单）；
 *  2. **缺选配**（未勾任何加工项 ⇒ 组合键为空）⇒ **不阻断**，只显著提示
 *     （裁定「工艺缺失 ⇒ 允许提交，只显著提示」）；
 *  3. 收货信息三项 + **物流两项**（常用物流/快递 + 常用物流公司）**必填** ⇒ 阻断；
 *  4. 提交失败必须说清「哪儿缺」：吸底条出现**可点的错误汇总**（不再只有一句 toast）；
 *  5. 出错的**折叠区必须自动展开**（费用明细 / 物流 `<details>` / 商品组卡 / 向导步骤）——
 *     否则商家只看到 toast，屏幕上什么都没有（本文件的存在理由就是这个）。
 *  6. **折叠态下也要看得出「已经选了什么」**（issue #6589，用户 2026-10-09 逐字：「订单这里折叠
 *     情况下应该要展示隐藏的具体信息」）—— 物流 `<details>` 收起时 `<summary>` 直接摆出当前值，
 *     不再只有一句通用提示；两项都缺 ⇒ 退回通用提示（**不编造**默认值，#4419）。
 *
 * 🔴 红证（改前必红）：① 未定价仍会发请求；② 无 `submit-error-summary`；
 *    ③ `logistics-section` 不会自动展开；④ 收起组卡后提交失败不会自动展开；
 *    ⑤ 收起态 `logistics-summary` 只有通用提示（issue #6589 改前形态）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import path from 'node:path'

// ── API 替身（与 `orders-new.test.tsx` 同一套形状，只保留本文件用得到的）──
const mockCreateOrder = vi.fn()
const mockGetProducts = vi.fn()
const mockGetProduct = vi.fn()
const mockGetProcessingItems = vi.fn()
const mockAutoFeaturesPreview = vi.fn()
const mockGetCraftCalcConfig = vi.fn()
/** 加工费计价预览：每个用例自己决定「已定价 / 未定价（组合键非空）/ 缺选配（组合键为空）」 */
const mockFeePreview = vi.fn()

vi.mock('@/lib/api', () => ({
  orderApi: { createOrder: (...a: unknown[]) => mockCreateOrder(...a) },
  productApi: {
    getProducts: (...a: unknown[]) => mockGetProducts(...a),
    getProduct: (...a: unknown[]) => mockGetProduct(...a),
  },
  processingItemApi: {
    getProcessingItems: (...a: unknown[]) => mockGetProcessingItems(...a),
  },
  customerApi: { getCustomers: vi.fn().mockResolvedValue({ data: { data: { items: [] } } }) },
  // 算料试算：本文件与「用料公式」正交 ⇒ 停在「进行中」（永不 resolve），
  // 避免它改写数量污染判据（同 `orders-new.test.tsx`）。
  craftCalcApi: { preview: () => new Promise(() => {}) },
  autoFeaturesApi: { preview: (...a: unknown[]) => mockAutoFeaturesPreview(...a) },
  // 门幅规则：本文件不验门幅，给一个「无规则解」的良性响应即可
  doorWidthPlanApi: { preview: () => Promise.resolve({ data: { data: null } }) },
  feePreviewApi: { preview: (...a: unknown[]) => mockFeePreview(...a) },
  productionApi: { getCraftCalcConfig: (...a: unknown[]) => mockGetCraftCalcConfig(...a) },
}))

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }))

import NewOrderPage from '@/app/(dashboard)/orders/new/page'

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
        tiers: { standard: { fullness: 2.0, label: '标准档（2.0倍）' } },
        default_formula: 'pleat',
        meters_rounding_step: 0.1,
      },
    },
  },
}

/** 服务端取价替身：`detail` 由用例给定（三态可控） */
function feePreviewReturning(detail: Record<string, unknown>, processingFee = 0) {
  mockFeePreview.mockImplementation(() =>
    Promise.resolve({
      data: {
        data: {
          items: [{ processingFee, processingFeeDetail: detail }],
          processingFeeTotal: processingFee,
        },
      },
    })
  )
}

/** 「已定价」基线：组合命中价目 ⇒ 不触发任何未定价闸门 */
const MATCHED_DETAIL = {
  fee_source: 'matched',
  composition: '韩褶 + 定型',
  items: ['韩褶', '定型'],
  unit_price: 12,
  meters: 3,
  special_options_total: 0,
}

/** 「未定价」：有组合键（商家确实选了加工项）但价目里没有这一档 —— **本次报障的形态** */
const UNPRICED_WITH_KEY = {
  fee_source: 'unpriced',
  composition: '韩褶 + 定型',
  items: ['韩褶', '定型'],
  unit_price: null,
  meters: 3,
  special_options_total: 0,
}

/** 「缺选配」：组合键为空（没勾任何加工项）—— 按裁定**不阻断** */
const UNPRICED_NO_KEY = {
  fee_source: 'unpriced',
  composition: '',
  items: [],
  unit_price: null,
  meters: 3,
  special_options_total: 0,
}

describe('下单页提交闸门（issue #5840）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetProducts.mockResolvedValue({
      data: { data: { items: [{ id: 'p1', name: '遮光窗帘', price: 100 }], total: 1 } },
    })
    mockGetProduct.mockResolvedValue({
      data: { data: { id: 'p1', name: '遮光窗帘', skus: [], price: 100 } },
    })
    mockGetProcessingItems.mockResolvedValue({ data: { data: { items: [] } } })
    mockGetCraftCalcConfig.mockResolvedValue(CALC_CONFIG_OK)
    mockAutoFeaturesPreview.mockResolvedValue({
      data: { data: { auto_features: [], door_width: null, fullness_used: 2.0, notice: 'missing-door-width' } },
    })
    feePreviewReturning(MATCHED_DETAIL, 36)
  })

  /** 选商品 + 填净尺寸（成品帘宽高必填，否则会被既有闸门先拦住，掩盖本文件要验的判据） */
  const pickCurtain = async ({ size = true } = {}) => {
    fireEvent.click(await screen.findByText('点击搜索并选择商品'))
    fireEvent.click(await screen.findByText('遮光窗帘'))
    await screen.findByText('净尺寸')
    if (size) {
      fireEvent.change(screen.getByLabelText('窗宽 (米)'), { target: { value: '3' } })
      fireEvent.change(screen.getByLabelText('窗高 (米)'), { target: { value: '2.5' } })
    }
  }

  const fillCustomer = () => {
    fireEvent.change(screen.getByPlaceholderText('请输入收货人姓名'), { target: { value: '张三' } })
    fireEvent.change(screen.getByPlaceholderText('请输入 11 位手机号'), { target: { value: '13800138000' } })
    fireEvent.change(screen.getByPlaceholderText('请输入详细收货地址'), { target: { value: '杭州市西湖区' } })
  }

  const fillLogistics = () => {
    fireEvent.change(screen.getByTestId('order-logistics-type'), { target: { value: 'express' } })
    fireEvent.change(screen.getByTestId('order-logistics-company'), { target: { value: '顺丰' } })
  }

  /**
   * 等「加工费计价」与「自动识别判定」两个既有闸门落地（它们是**异步**的；
   * 不等就会把「计价中」误判成本文件要验的那条闸门 —— 固定 sleep 在慢机器上会假红）。
   */
  const settleAsyncGates = async () => {
    await waitFor(() => expect(mockFeePreview).toHaveBeenCalled(), { timeout: 3000 })
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
    try {
      await waitFor(() => expect(mockAutoFeaturesPreview).toHaveBeenCalled(), { timeout: 3000 })
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 0))
      })
    } catch {
      // 该用例没有可判定的行 ⇒ 本就没有判定请求
    }
  }

  const submit = () => fireEvent.click(screen.getByText('提交订单'))

  // ─────────────────────────────────────────────────────────────
  // 判据 1（🔴 红证）：未定价（组合键非空）⇒ 阻断，且原因必须**看得见**
  // ─────────────────────────────────────────────────────────────
  it('未定价且组合键非空 ⇒ 不发请求；汇总点名组合；费用明细自动展开（红证）', async () => {
    feePreviewReturning(UNPRICED_WITH_KEY, 0)
    render(<NewOrderPage />)
    await pickCurtain()
    fillCustomer()
    fillLogistics()
    await settleAsyncGates()

    // 事前自证：费用明细**默认收起**（否则「自动展开」这条判据是空的）
    expect(screen.queryByTestId('fee-detail-panel')).toBeNull()

    submit()

    await waitFor(() => expect(screen.getByTestId('submit-error-summary')).toBeInTheDocument())
    expect(mockCreateOrder).not.toHaveBeenCalled()
    const summary = screen.getByTestId('submit-error-summary')
    expect(summary.textContent).toContain('加工费未定价')
    // 只报「有几行」不够 —— 必须点名是哪个组合（否则商家不知道该给哪一档定价）
    expect(summary.textContent).toContain('韩褶 + 定型')
    // 出错的折叠区自动展开（商家不必自己去点开「费用明细」）
    expect(screen.getByTestId('fee-detail-panel')).toBeInTheDocument()
  })

  // ─────────────────────────────────────────────────────────────
  // 判据 2：缺选配（组合键为空）⇒ **不阻断**（用户裁定：工艺缺失只显著提示）
  // ─────────────────────────────────────────────────────────────
  it('未勾任何加工项（组合键为空）⇒ 不阻断，只提示', async () => {
    feePreviewReturning(UNPRICED_NO_KEY, 0)
    render(<NewOrderPage />)
    await pickCurtain()
    fillCustomer()
    fillLogistics()
    await settleAsyncGates()

    submit()

    await waitFor(() => expect(mockCreateOrder).toHaveBeenCalledTimes(1))
  })

  // ─────────────────────────────────────────────────────────────
  // 判据 3：物流两项必填（用户裁定「两个物流字段也必填」）
  // ─────────────────────────────────────────────────────────────
  it('缺物流两项 ⇒ 阻断 + 物流折叠区自动展开；补齐后放行', async () => {
    render(<NewOrderPage />)
    await pickCurtain()
    fillCustomer()
    await settleAsyncGates()

    const logistics = screen.getByTestId('logistics-section') as HTMLDetailsElement
    // 事前自证：它**默认收起**（否则「自动展开」测的是空气）
    expect(logistics.open).toBe(false)

    submit()

    await waitFor(() => expect(screen.getByTestId('submit-error-summary')).toBeInTheDocument())
    expect(mockCreateOrder).not.toHaveBeenCalled()
    expect(screen.getByTestId('submit-error-summary').textContent).toContain('常用物流')
    expect((screen.getByTestId('logistics-section') as HTMLDetailsElement).open).toBe(true)

    // 补齐 ⇒ 不再被这一条拦（防「闸门把正常单挡在门外」）
    fillLogistics()
    submit()
    await waitFor(() => expect(mockCreateOrder).toHaveBeenCalledTimes(1))
  })

  // ─────────────────────────────────────────────────────────────
  // 判据 9（2026-10-09，issue #6589）：**折叠态**下 summary 要显示已带出的**具体物流**
  // ─────────────────────────────────────────────────────────────
  it('折叠态 summary 显示已带出的具体物流（不是只显示通用提示）', async () => {
    // 用户逐字：「订单这里折叠情况下应该要展示隐藏的具体信息」（红框 = 收起态的「常用物流」那一行；
    // 截图里姓名 / 手机号 / 地址都已填好，这一行却只有静态提示 ⇒ 看不出带出的是哪一家）。
    render(<NewOrderPage />)
    await pickCurtain()
    fillCustomer()
    await settleAsyncGates()

    // ① 未指定 ⇒ 退回通用提示（「未指定」是真值，不编造「快递」—— #4419 口径）
    const summary = screen.getByTestId('logistics-summary')
    expect(summary.textContent).toContain('常用物流（必填 · 选客户时自动带出）')

    fillLogistics()

    // ② **收起态**下两项当前值都看得见（改前：summary 与两个控件的值零绑定 ⇒ 只有通用提示）
    expect((screen.getByTestId('logistics-section') as HTMLDetailsElement).open).toBe(false)
    expect(summary.textContent).toContain('常用物流：快递 · 顺丰')
    // 值走 primary 色系（与周围中性灰的通用提示不同一档；同 #6399 收起态读数的形态）
    expect(summary.querySelector('span.text-primary-700')?.textContent).toBe('快递 · 顺丰')

    // ③ 读数是**跟着改的值走**的（不是一份写死的快照）
    fireEvent.change(screen.getByTestId('order-logistics-company'), {
      target: { value: '四季安物流' },
    })
    expect(summary.textContent).toContain('常用物流：快递 · 四季安物流')
  })

  // ─────────────────────────────────────────────────────────────
  // 判据 4：报错行必须**可点**，点了能到出错的那一块（折叠态下也找得到）
  // ─────────────────────────────────────────────────────────────
  it('错误汇总逐条可点 ⇒ 点「常用物流」那条能把物流折叠区展开', async () => {
    render(<NewOrderPage />)
    await pickCurtain()
    fillCustomer()
    await settleAsyncGates()
    submit()

    const items = await screen.findAllByTestId('submit-error-item')
    expect(items.length).toBeGreaterThan(0)
    // 先收起物流区，再点汇总里的那一条 —— 验证它是**真的**能定向展开
    const logistics = screen.getByTestId('logistics-section') as HTMLDetailsElement
    logistics.open = false
    const hit = items.find((el) => (el.textContent ?? '').includes('常用物流'))!
    expect(hit).toBeTruthy()
    fireEvent.click(hit)
    await waitFor(() =>
      expect((screen.getByTestId('logistics-section') as HTMLDetailsElement).open).toBe(true)
    )
  })

  // ─────────────────────────────────────────────────────────────
  // 判据 5（🔴 红证）：商品组卡**收起**时提交失败 ⇒ 自动展开到出错那一步
  // ─────────────────────────────────────────────────────────────
  it('组卡收起时提交失败 ⇒ 自动展开（折叠态下不再「只弹 toast、屏幕上什么都没有」）', async () => {
    render(<NewOrderPage />)
    // 净尺寸**不填** ⇒ 宽高报错（要验的正是「这一步里的错」在收起时可达）
    await pickCurtain({ size: false })
    fillCustomer()
    fillLogistics()

    // 收起整卡
    fireEvent.click(screen.getByRole('button', { name: /遮光窗帘/ }))
    await waitFor(() => expect(screen.queryByTestId('wizard-step-1')).toBeNull())

    await settleAsyncGates()
    submit()

    // 卡被自动展开 ⇒ 出错的那一步重新可见
    await waitFor(() => expect(screen.getByTestId('wizard-step-1')).toBeInTheDocument())
    expect(screen.getByTestId('submit-error-summary').textContent).toContain('未填宽')
  })

  // ─────────────────────────────────────────────────────────────
  // 判据 6：手填用料米数 ⇒ 组头摘要（**收起时也看得见**）必须标出来
  // ─────────────────────────────────────────────────────────────
  it('手填用料米数 ⇒ 组头摘要标「手填」（收起态可见，且不阻断提交）', async () => {
    render(<NewOrderPage />)
    await pickCurtain()
    fillCustomer()
    fillLogistics()
    await settleAsyncGates()

    const metersLabel = screen.getAllByText('用料米数')[0]
    const metersInput = metersLabel.closest('div')!.querySelector('input') as HTMLInputElement
    fireEvent.change(metersInput, { target: { value: '7.5' } })

    // 收起整卡 ⇒ 只剩组头摘要
    fireEvent.click(screen.getByRole('button', { name: /遮光窗帘/ }))
    await waitFor(() => expect(screen.queryByTestId('wizard-step-1')).toBeNull())

    const header = screen.getByRole('button', { name: /遮光窗帘/ })
    expect(header.textContent).toContain('手填')
  })

  // ─────────────────────────────────────────────────────────────
  // 判据 7（🔴 红证）：**死键**不再可能 —— 判定未就绪也要能在汇总里看见
  // ─────────────────────────────────────────────────────────────
  it('自动识别判定未就绪 ⇒ 汇总里看得见（`line_*_autoFeatures` 此前是死键）', async () => {
    // 判定永不返回 ⇒ `validate()` 会写 `line_<id>_autoFeatures`。
    // 改前这个键**全页没有任何渲染点**（`errors[...]` 只在别处读）⇒ 商家只看到「请完善订单信息」，
    // 屏幕上找不到原因，只能反复点提交。
    mockAutoFeaturesPreview.mockReturnValue(new Promise(() => {}))
    render(<NewOrderPage />)
    await pickCurtain()
    fillCustomer()
    fillLogistics()
    await waitFor(() => expect(mockAutoFeaturesPreview).toHaveBeenCalled(), { timeout: 3000 })
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })

    submit()

    await waitFor(() => expect(screen.getByTestId('submit-error-summary')).toBeInTheDocument())
    expect(screen.getByTestId('submit-error-summary').textContent).toContain('自动识别判定')
    expect(mockCreateOrder).not.toHaveBeenCalled()
  })

  // ─────────────────────────────────────────────────────────────
  // 判据 8（**类级元守卫**）：汇总必须**全量**派生自 `errors`
  //
  // 本单的病根形态是「写进错误映射、页面上没有渲染点」=**死键**（`line_*_autoFeatures`）。
  // 上面 7 条判据各自钉住一个**实例**；这一条钉住**类**：只要汇总仍由 `Object.keys(errors)`
  // 全量派生，**任何**新增的错误键都自动有落点，死键在结构上不再可能。
  // 回归时会怎么红：把派生改成挑着显示（白名单 / filter / 手写数组）⇒ 第一条断言红。
  // ─────────────────────────────────────────────────────────────
  it('类级元守卫：错误汇总由 `Object.keys(errors)` 全量派生（死键在结构上不可能）', () => {
    const src = readFileSync(
      path.resolve(process.cwd(), 'src/app/(dashboard)/orders/new/page.tsx'),
      'utf8'
    )
    // ① 全量派生（唯一允许的入参形态）
    expect(src.match(/sortErrorKeys\(Object\.keys\(errors\)\)/)?.[0]).toBe(
      'sortErrorKeys(Object.keys(errors))'
    )
    // ② 这个派生结果真的被汇总渲染了（不是算出来没人用）
    expect(src.match(/data-testid="submit-error-summary"/)?.[0]).toBe(
      'data-testid="submit-error-summary"'
    )
    expect(src.match(/\{errorEntries\.map\(/)?.[0]).toBe('{errorEntries.map(')
  })
})
