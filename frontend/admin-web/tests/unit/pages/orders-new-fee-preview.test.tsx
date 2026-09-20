// case_ids: OR-009, OR-014, UI-038, OR-039
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
 *
 * 另含 issue #4590 的一组判据（未定价告警必须**点名具体加工项组合** + 行级标注 + 边界），
 * 见文件末尾 `describe('#4590 …')`。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

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

/** 展开向导**区块 2**「加工项 · 特殊选项」（issue #4874 两步化；#4489 判据 3：默认收起） */
const expandProcessing = () => {
  const btn = screen.getAllByRole('button', { name: /^\d+ 加工项/ })[0]
  if (btn.getAttribute('aria-expanded') === 'false') fireEvent.click(btn)
}

const inputOf = (label: string, idx = 0) =>
  screen
    .getAllByText(label)
    .map((el) => el.closest('div')!.querySelector('input') as HTMLInputElement)[idx]

/** 选商品 → 填宽高（触发算料试算 → 预填「用料米数」）→ 勾一个 per_meter 加工项 */
async function setupLine() {
  render(<NewOrderPage />)
  fireEvent.click(await screen.findByText('点击搜索并选择商品'))
  fireEvent.click(await screen.findByText('遮光窗帘'))
  await screen.findByText('宽 (米)')
  fireEvent.change(inputOf('宽 (米)'), { target: { value: '6.6' } })
  fireEvent.change(inputOf('高 (米)'), { target: { value: '2.6' } })
  // 帘行米数输入框（issue #4598 起 label = 「用料米数」，旧文案「数量」）—— 它就是加工费米数
  await waitFor(() => expect(inputOf('用料米数')).toHaveValue(13.3))
  expandProcessing()
  fireEvent.click(screen.getByRole('checkbox'))
}

const submit = async () => {
  fireEvent.change(screen.getByPlaceholderText('请输入收货人姓名'), { target: { value: '张三' } })
  fireEvent.change(screen.getByPlaceholderText('请输入 11 位手机号'), { target: { value: '13800138000' } })
  fireEvent.change(screen.getByPlaceholderText('请输入详细收货地址'), { target: { value: '杭州市' } })
  await waitFor(() => expect(screen.queryByText(/加工费计价中/)).toBeNull())
  fireEvent.click(screen.getByText('提交订单'))
}

/**
 * 每个用例的公共桩（两个 `describe` 都要用 —— 桩实现是**跨 describe 粘连**的，
 * 靠「另一个 describe 的 beforeEach 跑过」会让 `-t` 窄跑时静默拿到空目录）。
 */
const stubApis = () => {
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
}

describe('下单页加工费计价预览接线（#4450）', () => {
  beforeEach(stubApis)

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

  it('判据 6：未定价 ⇒ 显式提示「未定价」，且页面金额 = 服务端值（0），不是本地 Σ', async () => {    mockFeePreview.mockResolvedValue({
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

  // ══════════════════════════════════════════════════════════════════════════
  // issue #4874：加工项区块里的「加工费组合」明细块 + 未定价行**就地改单价**
  //
  // 用户 2026-09-21：「订单中加工费组合**未配置**的情况下，**允许更改该单价**，并且在
  // **加工项下面添加具体的组合名**」。改价必须：① 立刻以该价**重发 `feePreview`**（页面金额跟着变）；
  // ② 以 `processingInfo.processingFeeOverride` **随建单提交**（后端 #4872 采用后 = `manual`）。
  // ══════════════════════════════════════════════════════════════════════════

  it('#4874 未定价行出现「改单价」输入 ⇒ 改价后 **feePreview 请求体**带 processingFeeOverride', async () => {
    mockFeePreview.mockResolvedValue(
      feeUnpriced([{ composition: '布帘+韩褶', items: ['布帘', '韩褶'] }])
    )
    await setupLine()

    // 加工项区块里**列出具体组合名**（`items.join(' + ')`，与「加工费组合」页逐字同源）
    const block = await screen.findByTestId('processing-fee-combinations')
    expect(within(block).getByTestId('fee-combination-name')).toHaveTextContent('布帘 + 韩褶')
    // 未定价 ⇒ 来源列显式标「未定价」（不渲染 ¥0.00 —— 仓库硬纪律）
    expect(within(block).getByText(/未定价/)).toBeInTheDocument()

    const override = within(block).getByTestId('fee-unit-price-override') as HTMLInputElement
    fireEvent.change(override, { target: { value: '12.5' } })

    // ① 立刻以该价重发 feePreview（300ms 防抖后）——「试算与提交必须看到同一份选配」
    await waitFor(() => {
      const last = mockFeePreview.mock.calls.at(-1)![0]
      expect(last.items[0].processingInfo.processingFeeOverride).toBe(12.5)
    })
    // ② 随建单提交同一份（后端据此把该组合记成 manual 并同步进加工费组合配置）
    await submit()
    await waitFor(() => expect(mockCreateOrder).toHaveBeenCalled())
    expect(
      mockCreateOrder.mock.calls[0][0].items[0].processingInfo.processingFeeOverride
    ).toBe(12.5)
  })

  it('#4874 组合键为空（缺选配信息）⇒ **不给**改单价入口（没有 key 可同步），保持既有提示', async () => {
    mockFeePreview.mockResolvedValue(feeUnpriced([{ composition: '', items: [] }]))
    await setupLine()

    const block = await screen.findByTestId('processing-fee-combinations')
    // 组合名照旧点明「缺选配信息」（既有文案，一字不改）
    expect(within(block).getByTestId('fee-combination-name')).toHaveTextContent(
      '没有可匹配的组合（缺选配信息）'
    )
    // 红证：若实现无条件渲染改单价输入（不判组合键），下面两条必红
    expect(within(block).queryByTestId('fee-unit-price-override')).toBeNull()
    expect(within(block).getByTestId('fee-combination-no-composition')).toBeInTheDocument()
  })

  it('#4874 已定价行 ⇒ 单价**只读**（无改单价入口），且保留去「加工费组合」的定价入口', async () => {
    await setupLine() // stub = feeMatched()：fee_source=matched、unit_price=10
    const block = await screen.findByTestId('processing-fee-combinations')
    expect(within(block).getByTestId('fee-unit-price')).toHaveTextContent('¥10.00/米')
    expect(within(block).queryByTestId('fee-unit-price-override')).toBeNull()
    // 已定价 ⇒ 不再需要「去定价」入口（那正是「未定价」才要做的事）
    expect(within(block).queryByRole('link', { name: /加工费组合/ })).toBeNull()
  })

  it('#4874 没有选配任何加工项（也未触发自动识别）⇒ 整块不渲染（无组合可展示、也无价可改）', async () => {
    render(<NewOrderPage />)
    fireEvent.click(await screen.findByText('点击搜索并选择商品'))
    fireEvent.click(await screen.findByText('遮光窗帘'))
    await screen.findByText('宽 (米)')
    // 刻意**不填宽高**（自动识别特征以宽高为输入）也**不勾**加工项 ⇒ 组合键为空
    expandProcessing()
    await waitFor(() => expect(mockFeePreview).toHaveBeenCalled())
    expect(screen.queryByTestId('processing-fee-combinations')).toBeNull()
  })
})

// ═══════════════════════════════════════════════════════════════════════════════════════════
// issue #4590：未定价告警必须**点名具体加工项组合**
//
// 用户 2026-09-19（下单页实测）：「这里要把**具体的加工项组合**告知用户，不然用户不知道设置哪个
// 组合」—— 告警此前只说「有 N 行加工费未定价」，商家拿着这句话去「加工费组合」页，面对一长串组合
// 仍不知道该给哪一条定价。而数据**后端已经给了**：`ProcessingFeeCalculator.detail` 的 13 键里就有
// `composition`（归一化组合键）与 `items`（展示用加工项名，与「加工费组合」页同源）
// ⇒ 前端只数行数 = 把可行动信息丢掉。
// ═══════════════════════════════════════════════════════════════════════════════════════════

/**
 * 后端「加工费组合」定价入口（`ProcessingFeeCalculator.PRICING_ENTRY`）—— **真值取自源码**，
 * 不写死字符串：前端若自己另写一个定价路径，本断言必红（#4590 的「同源」判据）。
 */
const backendPricingEntry = (): string => {
  const src = readFileSync(
    join(
      process.cwd(),
      '../../backend/admin-api/src/main/java/com/migao/admin/service/ProcessingFeeCalculator.java'
    ),
    'utf8'
  )
  const m = /PRICING_ENTRY\s*=\s*"([^"]+)"/.exec(src)
  if (!m) throw new Error('后端 ProcessingFeeCalculator 里找不到 PRICING_ENTRY —— 判据前提失效')
  return m[1]
}

/** 服务端未定价取价行（`composition` = 归一化组合键；`items` = 展示用加工项名，键名冻结） */
const unpricedItem = (composition: string, items: string[]) => ({
  processingFee: 0,
  processingFeeDetail: {
    composition,
    items,
    unit_price: null,
    meters: 13.3,
    fee_source: 'unpriced',
    amount: 0,
    // issue #4594：未定价行也带选项那半（本 fixture 没选选项 ⇒ 0）
    special_options: [],
    special_options_total: 0,
    hint: '选配组合未定价 ⇒ 请去「加工费管理」为该组合定价',
  },
})

const feeUnpriced = (rows: Array<{ composition: string; items: string[] }>) => ({
  data: {
    data: {
      items: rows.map((r) => unpricedItem(r.composition, r.items)),
      processingFeeTotal: 0,
    },
  },
})

/**
 * 未定价告警块。⚠️ 显式压到 2s：`tests/setup.ts` 把 `asyncUtilTimeout` 提到了 5s（issue #4414），
 * 与 vitest 默认测试超时**相等** ⇒ 未命中时会报「Test timed out」而不是「找不到元素」，
 * 红证里读不出判据（本 issue 的红证正是「找不到告警里的组合名」）。
 */
const findUnpricedAlert = () => screen.findByTestId('unpriced-fee-alert', {}, { timeout: 2000 })

/** 费用明细卡片（issue #4874：录入控件与明细行会同名 ⇒ 明细断言一律限定在卡片内） */
const feeCard = (): HTMLElement =>
  screen.getByText('费用明细').closest('div')!.parentElement as HTMLElement

/** 再加一个商品组并选中商品（「添加商品」→ 新组的「点击搜索并选择商品」→ 弹窗里选） */
const addGroupWithProduct = async () => {
  fireEvent.click(screen.getByText('添加商品'))
  // 新组是**空组**（issue #4508）⇒ 只有它渲染「点击搜索并选择商品」（已选商品的组显示「重新选择」）
  fireEvent.click(await screen.findByText('点击搜索并选择商品', {}, { timeout: 2000 }))
  const dialog = await screen.findByRole('dialog', { name: '选择商品' }, { timeout: 2000 })
  fireEvent.click(await within(dialog).findByText('遮光窗帘', {}, { timeout: 2000 }))
}

describe('#4590 未定价告警点名具体加工项组合', () => {
  beforeEach(stubApis)

  it('告警区出现**具体组合名**（不再只有「有 N 行未定价」）+ 直达定价页链接（路径与后端同源）', async () => {
    mockFeePreview.mockResolvedValue(
      feeUnpriced([{ composition: '布帘+韩褶', items: ['布帘', '韩褶'] }])
    )
    await setupLine()

    const alert = await findUnpricedAlert()
    // 组合名逐字 = `items.join(' + ')`（与「加工费组合」页同一写法）
    expect(alert.textContent).toContain('布帘 + 韩褶')
    expect(alert.textContent).toContain('1 行')
    // 「未定价」不得渲染成 ¥0.00（仓库硬纪律）
    expect(alert.textContent).not.toContain('¥0.00')
    // 一键直达「加工费组合」定价面：href 必须等于**后端** `PRICING_ENTRY`（不另写一个路径）
    // ⚠️ issue #4874：加工项区块**新增**了同一入口（未定价行的操作列）⇒ 现在有多处，
    // 断言从 `getByRole`（唯一）改为「**每一处**都指向后端同源路径」（比原来更强，不是放宽）。
    const pricingLinks = screen.getAllByRole('link', { name: /加工费组合/ })
    expect(pricingLinks.length).toBeGreaterThanOrEqual(2)
    for (const link of pricingLinks) {
      expect(link).toHaveAttribute('href', backendPricingEntry())
    }
  })

  it('费用明细**行内**也标出是哪个组合未定价（行级可判，不必回看告警）', async () => {
    mockFeePreview.mockResolvedValue(
      feeUnpriced([{ composition: '布帘+韩褶', items: ['布帘', '韩褶'] }])
    )
    await setupLine()

    await findUnpricedAlert()
    const row = screen.getByText('加工').parentElement!.parentElement!
    expect(row.textContent).toContain('组合未定价')
    expect(row.textContent).toContain('布帘 + 韩褶')
  })

  it('`composition` 为空 ⇒ 区分成「没有可匹配的组合（缺选配信息）」，不渲染空组合名', async () => {
    mockFeePreview.mockResolvedValue(feeUnpriced([{ composition: '', items: [] }]))
    await setupLine()

    const alert = await findUnpricedAlert()
    expect(alert.textContent).toContain('没有可匹配的组合（缺选配信息）')
    // 不得出现空组合名（`「」` 形态）—— 那是「组合未定价」的写法，两者不许混同
    expect(alert.textContent).not.toMatch(/「\s*」/)
    // 行级同样区分（不是空名字）
    const row = screen.getByText('加工').parentElement!.parentElement!
    expect(row.textContent).toContain('没有可匹配的组合（缺选配信息）')
  })

  it('同一组合命中多行 ⇒ **合并计数**（「2 行」）；多个组合 ⇒ 逐条列', async () => {
    mockFeePreview.mockResolvedValue(
      feeUnpriced([
        { composition: '布帘+韩褶', items: ['布帘', '韩褶'] },
        { composition: '布帘+韩褶', items: ['布帘', '韩褶'] },
        { composition: '布帘+韩褶+定型', items: ['布帘', '韩褶', '定型'] },
      ])
    )
    await setupLine()
    // 再加两组（取价行与 `pricedLines` 同序 ⇒ 前两行同一组合、第三行另一个组合）
    await addGroupWithProduct()
    await addGroupWithProduct()

    const alert = await findUnpricedAlert()
    await waitFor(() => expect(alert.textContent).toContain('3 行加工费未定价'))
    // 同一组合命中 2 行 ⇒ 合并成**一条**（名字只出现一次，计数为 2）
    expect(alert.textContent!.split('布帘 + 韩褶（2 行').length - 1).toBe(1)
    // 另一个组合逐条列出（各自的行数）
    expect(alert.textContent).toContain('布帘 + 韩褶 + 定型（1 行')
  })

  it('布料行**仍不计入**未定价（#4493 既有裁定不变：不给每张布料单挂假警报）', async () => {
    mockFeePreview.mockResolvedValue(
      feeUnpriced([{ composition: '布帘+韩褶', items: ['布帘', '韩褶'] }])
    )
    await setupLine()
    await findUnpricedAlert()

    // 切到布料 ⇒ 告警消失（布料无加工，按 0 计是正常的）
    fireEvent.click(
      within(screen.getByRole('radiogroup', { name: '售卖形态' })).getByRole('radio', {
        name: '布料',
      })
    )
    await waitFor(() => expect(screen.queryByTestId('unpriced-fee-alert')).toBeNull())

    // 正向对照（防「整块没渲染 ⇒ 假绿」）：切回成品帘 ⇒ 告警与组合名都回来
    fireEvent.click(
      within(screen.getByRole('radiogroup', { name: '售卖形态' })).getByRole('radio', {
        name: '成品帘',
      })
    )
    const alert = await findUnpricedAlert()
    expect(alert.textContent).toContain('布帘 + 韩褶')
  })
})

// ═══════════════════════════════════════════════════════════════════════════════════════════
// issue #4594（用户裁定 2026-09-19）：组合未定价时，**已定价的特殊选项照常计入**
//
// 行加工费 = 组合那半（未定价 ⇒ 0） + Σ 已定价特殊选项；选项是**按套的独立一笔账**，
// 与组合是否定价、米数是否齐全无关。告警**保留**且仍点名组合（#4590 判据不退化），
// 但文案必须说清「哪半 0、哪半照计」—— 否则 `¥0.00` 与「未定价」又混成一团。
// ═══════════════════════════════════════════════════════════════════════════════════════════

/** 组合未定价 + 已定价特殊选项「扣环」¥1.50/套 × 2 套 = ¥3.00（服务端已算好那两半） */
const feeUnpricedWithPricedOption = () => ({
  data: {
    data: {
      items: [
        {
          processingFee: 3,
          processingFeeDetail: {
            composition: '布帘+韩褶',
            items: ['布帘', '韩褶'],
            unit_price: null,
            meters: 13.3,
            fee_source: 'unpriced',
            amount: 0,
            special_options: [
              { name: '扣环', unit_price: 1.5, sets: 2, amount: 3, priced: true },
            ],
            special_options_total: 3,
            hint: '选配组合未定价 ⇒ 请去「加工费管理」为该组合定价',
          },
        },
      ],
      processingFeeTotal: 3,
    },
  },
})

describe('#4594 组合未定价时已定价的特殊选项照常计入', () => {
  beforeEach(stubApis)

  it('告警保留 + 点名组合（#4590 不退化），并说清「组合那半按 0 计；特殊选项照常计入」', async () => {
    mockFeePreview.mockResolvedValue(feeUnpricedWithPricedOption())
    await setupLine()

    const alert = await findUnpricedAlert()
    expect(alert.textContent).toContain('布帘 + 韩褶') // #4590 判据不退化
    expect(alert.textContent).toContain('组合那半按 0 计')
    expect(alert.textContent).toContain('已定价的特殊选项照常计入')
    expect(alert.textContent).toContain('¥3.00')
    // ⚠️ issue #4874：加工项区块也加了同一入口 ⇒ 每一处都指向后端同源路径（比唯一断言更强）
    const links = screen.getAllByRole('link', { name: /加工费组合/ })
    expect(links.length).toBeGreaterThanOrEqual(2)
    for (const link of links) expect(link).toHaveAttribute('href', backendPricingEntry())
  })

  it('费用明细逐行之和 === 订单金额（选项那半真的进了总额，不再是 0）', async () => {
    mockFeePreview.mockResolvedValue(feeUnpricedWithPricedOption())
    await setupLine()
    await findUnpricedAlert()

    // 商品 13.3 米 × ¥100 = 1330 + 特殊选项 ¥3.00（组合那半 0）⇒ 订单金额 1333.00
    // ⚠️ 限定在费用明细卡片内：区块 2 的「特殊选项」选择器里也有「扣环」按钮（录入控件）
    const optionRow = within(feeCard()).getByText('扣环').parentElement!.parentElement!
    expect(optionRow.textContent).toContain('¥1.50/套 × 2 套')
    expect(screen.getByText('订单金额').parentElement!.textContent).toContain('¥1,333.00')
    // 未定价**不得**渲染成 ¥0.00（仓库硬纪律）—— 组合那半那格显示的是「组合未定价…」而不是金额
    const feeRow = within(feeCard()).getByText('加工').parentElement!.parentElement!
    expect(feeRow.textContent).toContain('组合未定价')
    expect(feeRow.textContent).not.toContain('¥0.00')
  })

  it('行内表达能区分「组合那半 0」与「选项照计」（不再是一句含糊的「按 0 计」）', async () => {
    mockFeePreview.mockResolvedValue(feeUnpricedWithPricedOption())
    await setupLine()
    await findUnpricedAlert()

    const row = within(feeCard()).getByText('加工').parentElement!.parentElement!
    expect(row.textContent).toContain('组合未定价（组合那半按 0 计）')
    expect(row.textContent).toContain('布帘 + 韩褶')
    expect(row.textContent).toContain('特殊选项照计 ¥3.00')
  })
})
