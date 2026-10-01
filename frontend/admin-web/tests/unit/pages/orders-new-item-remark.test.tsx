// case_ids: OR-035, OR-033
// @vitest-environment jsdom
/**
 * 下单页**部位备注**写侧（issue #5685）。
 *
 * 客户现行系统（加工单 / 工人扫码端）有一行「部位备注: 公式--48个折」—— 它装的是
 * 「**这个数字是怎么来的**」（算料依据的人工说明）。我们此前**没有任何部位级备注载体**
 * （`order_items` 连 remark 列都没有）⇒ 本单把它挂到**订单行 `processingInfo.remark`**
 * （JSONB 顶层字符串，与 `craft` / `formula` 同层；**不开新列、不开新端点**）。
 *
 * 判据（口径已冻结）：
 * ① 填了 ⇒ 提交 payload 的 `processingInfo.remark` **逐字**等于输入（试算与提交**同一构造点**，
 *    两处同值 —— 这正是 `buildLineProcessingInfo` 存在的理由）；
 * ② 空 / 纯空白 ⇒ **payload 里没有 `remark` 键**（不是 `""`：写空串会被下游读成「填过」，
 *    详情页会多出一行空值）；
 * ③ 上限 **200 字符**：`maxLength` 挡住超长输入 + 字数提示可见（服务端不截断 ⇒ 前端必须挡）；
 * ④ **逐行**：两个订单行各存各的备注，不串行（备注挂在行状态上）。
 *
 * 红证（删实现那行 ⇒ 必红，实测见 PR body）：
 * - 删 `buildLineProcessingInfo` 里的 `if (remark) info.remark = remark` ⇒ 判据 ①②④ 红；
 * - 删录入控件的 `maxLength={REMARK_MAX_LENGTH}` ⇒ 判据 ③ 红。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

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
  // **自动特征判定端点**（issue #4976 包 2b）：页面挂载即请求；本文件与该面正交
  // ⇒ 服务端替身返回**不判**（`missing-door-width`），否则提交闸门会拦住无关断言。
  autoFeaturesApi: {
    preview: () =>
      Promise.resolve({
        data: {
          data: {
            auto_features: [],
            door_width: null,
            fullness_used: 2.0,
            notice: 'missing-door-width',
          },
        },
      }),
  },
  feePreviewApi: { preview: (...a: unknown[]) => mockFeePreview(...a) },
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

/**
 * 展开向导**区块 2**「加工项」（issue #4874 两步化；#4489 判据 3：默认收起）。
 * ⚠️ 手风琴是**互斥**的（`setOpenStep(openStep === n ? 0 : n)`）⇒ 展开区块 2 会**卸载**区块 1
 * （`用料米数` / `单价` 的只读读数）与区块 3（部位备注）的子内容 —— 商家实际也是这样：翻到
 * 区块 2 就看不到另两步的内容。
 */
const expandProcessing = () => {
  const btn = screen.getAllByRole('button', { name: /^\d+\s*加工项/ })[0]
  if (btn.getAttribute('aria-expanded') === 'false') fireEvent.click(btn)
}

/**
 * 把每个商品行的**「特殊选项 / 部位备注」**展开回来。
 * ⚠️ **2026-09-29 改判**（用户逐字：「其他的这块选择区域归属到加工项区域中，不要单独搞个折叠块了，
 * 用户打开加工项区域时一同打开，另外不要命名叫『其他』，改成**特殊选项**」）：部位备注与特殊选项
 * 都住在 **②加工项**（原 ③ 其他 的折叠壳已删除）；净窗宽 / 窗高仍常显在**组级**。
 */
const openOtherSteps = () => {
  screen.getAllByRole('button', { name: /^\d+\s*加工项/ }).forEach((btn) => {
    if (btn.getAttribute('aria-expanded') === 'false') fireEvent.click(btn)
  })
}

/**
 * 把每个商品行的**步骤 1「用料与规格（系统推导）」**展开回来（`用料米数` 读数在它里面）。
 * ⚠️ 2026-09-28 布局重排前这是 `openSizeSteps`（标题「尺寸与数量 · 工艺规格」已退场，
 * 净窗宽 / 净窗高提到**组级**常显）；步骤之间**互斥** ⇒ 展开步骤 3 会把它卸载。
 */
const openSpecSteps = () => {
  screen.getAllByRole('button', { name: /^\d+\s*用料与规格/ }).forEach((btn) => {
    if (btn.getAttribute('aria-expanded') === 'false') fireEvent.click(btn)
  })
}

const inputOf = (label: string, idx = 0) =>
  screen
    .getAllByText(label)
    .map((el) => el.closest('div')!.querySelector('input') as HTMLInputElement)[idx]

const remarkInput = (idx = 0): HTMLInputElement =>
  screen.getAllByTestId('line-item-remark')[idx] as HTMLInputElement

/** 选商品 → 填宽高（触发算料试算 → 预填「用料米数」）→ 勾一个 per_meter 加工项 */
async function setupLine() {
  render(<NewOrderPage />)
  fireEvent.click(await screen.findByText('点击搜索并选择商品'))
  fireEvent.click(await screen.findByText('遮光窗帘'))
  await screen.findByText('窗宽 (米)')
  fireEvent.change(inputOf('窗宽 (米)'), { target: { value: '6.6' } })
  fireEvent.change(inputOf('窗高 (米)'), { target: { value: '2.6' } })
  await waitFor(() => expect(inputOf('用料米数')).toHaveValue('13.3'))
  expandProcessing()
  fireEvent.click(screen.getByRole('checkbox'))
}

const submit = async () => {
  fireEvent.change(screen.getByPlaceholderText('请输入收货人姓名'), { target: { value: '张三' } })
  fireEvent.change(screen.getByPlaceholderText('请输入 11 位手机号'), {
    target: { value: '13800138000' },
  })
  fireEvent.change(screen.getByPlaceholderText('请输入详细收货地址'), { target: { value: '杭州市' } })
  // 物流两项（issue #5840 起**必填**）：只在**未带出**时补默认 —— 选客户已带出值时**不覆盖**
  // （否则会盖掉「客户档案带出的常用物流」那几条判据要验的值）；「缺物流被拦」有自己的用例。
  const lt = screen.getByTestId('order-logistics-type') as HTMLSelectElement
  if (!lt.value) fireEvent.change(lt, { target: { value: 'express' } })
  const lc = screen.getByTestId('order-logistics-company') as HTMLInputElement
  if (!lc.value) fireEvent.change(lc, { target: { value: '顺丰' } })
  await waitFor(() => expect(screen.queryByText(/加工费计价中/)).toBeNull())
  fireEvent.click(screen.getByText('提交订单'))
}

/** 提交后拿到的 `processingInfo`（建单唯一构造点 `buildLineProcessingInfo` 的产物） */
const submittedInfo = async (lineIdx = 0): Promise<Record<string, unknown>> => {
  await submit()
  await waitFor(() => expect(mockCreateOrder).toHaveBeenCalled())
  return mockCreateOrder.mock.calls[0][0].items[lineIdx].processingInfo
}

const stubApis = () => {
  vi.clearAllMocks()
  mockGetProducts.mockResolvedValue({
    data: { data: { items: [{ id: 'p1', name: '遮光窗帘', price: 100 }], total: 1 } },
  })
  mockGetProduct.mockResolvedValue({
    data: { data: { id: 'p1', name: '遮光窗帘', skus: [], price: 100 } },
  })
  mockGetProcessingItems.mockResolvedValue({
    data: { data: { items: [{ id: 'pi1', name: '韩式褶', unit: '米' }] } },
  })
  mockCraftCalcPreview.mockResolvedValue(CALC_OK)
  mockFeePreview.mockResolvedValue(feeMatched())
}

describe('下单页部位备注写侧（#5685）', () => {
  beforeEach(stubApis)

  it('判据 1（红证）：填了备注 ⇒ 提交 payload 的 processingInfo.remark **逐字**等于输入，且试算同值', async () => {
    await setupLine()
    openOtherSteps() // 步骤 2 展开后其余步骤已收起 ⇒ 备注输入位（在**步骤 3「其他」**）要显式展开回来
    // 客户现行系统里的原话就是这个形态（`公式--48个折`）
    const typed = '公式--48个折'
    fireEvent.change(remarkInput(), { target: { value: typed } })

    // ① 试算入参（同一个 `buildLineProcessingInfo`）已经带上它 ⇒ 「页面显示 === 落库」的前提成立
    // ⚠️ 显式压到 2s：`tests/setup.ts` 把 `asyncUtilTimeout` 提到了 5s，与 vitest 默认单测超时
    // **相等** ⇒ 未命中时会报「Test timed out」而不是「值不相等」，红证里读不出判据。
    await waitFor(
      () => expect(mockFeePreview.mock.calls.at(-1)![0].items[0].processingInfo.remark).toBe(typed),
      { timeout: 2000 }
    )
    // ② 提交 payload 逐字同值
    const info = await submittedInfo()
    expect(info.remark).toBe(typed)
    // 与既有键**并存**（只加不改：备注不得挤掉加工费米数等既有落库键）
    expect(info.processingMeters).toBe(13.3)
  })

  it('判据 2（红证）：没填 ⇒ payload 里**没有** remark 键（不是空串）', async () => {
    await setupLine()
    // 前提自证：本态下 processingInfo 确实产出了（否则「没有 remark 键」是空断言）
    const untouched = await submittedInfo()
    expect(untouched.processingMeters).toBe(13.3)
    expect('remark' in untouched).toBe(false)
    expect(untouched.remark).toBeUndefined()
  })

  it('判据 2b（红证）：只打空格 ⇒ 同样**不落键**（纯空白 = 未填，不是真值）', async () => {
    await setupLine()
    openOtherSteps()
    fireEvent.change(remarkInput(), { target: { value: '   ' } })
    // 前提自证：空白确实进了输入框（否则这条判据会退化成上一条的重复）
    expect(remarkInput().value).toBe('   ')

    const info = await submittedInfo()
    expect(info.processingMeters).toBe(13.3)
    expect('remark' in info).toBe(false)
    expect(info.remark).not.toBe('')
  })

  it('判据 3（红证）：上限 200 —— maxLength 挡住超长输入 + 字数提示可见', async () => {
    await setupLine()
    openOtherSteps()
    const input = remarkInput()
    // ① 浏览器层上限：`maxLength=200`（服务端不截断 ⇒ 超长必须在录入处挡住）
    expect(input.maxLength).toBe(200)
    expect(input).toHaveAttribute('maxlength', '200')
    // ② 字数提示（商家看得见还剩多少）
    expect(screen.getByTestId('line-item-remark-counter')).toHaveTextContent('0/200')

    // ③ 连打 201 个字符 ⇒ 只进 200（**不是**静默截断已写内容：超出部分根本进不来）
    await userEvent.type(input, 'x'.repeat(201))
    expect(input.value).toBe('x'.repeat(200))
    expect(screen.getByTestId('line-item-remark-counter')).toHaveTextContent('200/200')

    // ④ 200 字照常**逐字**落库（上限之内不丢内容）
    const info = await submittedInfo()
    expect(info.remark).toBe('x'.repeat(200))
  }, 20000)

  it('判据 4（红证）：备注是**逐行**的 —— 第二行没填 ⇒ 第二行的 processingInfo 里没有该键', async () => {
    await setupLine()
    openOtherSteps()
    const typed = '公式--48个折'
    fireEvent.change(remarkInput(0), { target: { value: typed } })

    // 再加一组商品并选中（新组是空组 ⇒ 只有它渲染「点击搜索并选择商品」）
    fireEvent.click(screen.getByText('添加商品'))
    fireEvent.click(await screen.findByText('点击搜索并选择商品', {}, { timeout: 2000 }))
    const dialog = await screen.findByRole('dialog', { name: '选择商品' }, { timeout: 2000 })
    fireEvent.click(await within(dialog).findByText('遮光窗帘', {}, { timeout: 2000 }))
    // 第二行的宽高（必填）—— 净尺寸已提到**组级**（常显，不属于任何手风琴步骤）。
    // ⚠️ 第二行是**异步**出现的（商品详情接口回来后才建行）⇒ 先等两组的净尺寸都上屏。
    await waitFor(() => expect(screen.getAllByText('窗宽 (米)')).toHaveLength(2), { timeout: 2000 })
    fireEvent.change(inputOf('窗宽 (米)', 1), { target: { value: '3.3' } })
    fireEvent.change(inputOf('窗高 (米)', 1), { target: { value: '2.6' } })

    // 第二行也要**真的就绪**：算料试算落回米数后才过得了「数量须大于 0」的提交闸门
    // （不等它 ⇒ validate() 失败 ⇒ 一次 createOrder 都不会发生，而红证会读成"备注没落库"）。
    // 2026-09-28 布局重排：`用料米数` 读数在**步骤 1「用料与规格（系统推导）」**里 ⇒ 两行都展开
    // （步骤互斥：上一段把第 1 行停在步骤 3 ⇒ 它现在收起着），下标 1 = 第二行。
    await waitFor(
      () => {
        openSpecSteps()
        expect(inputOf('用料米数', 1)).toHaveValue('13.3')
      },
      { timeout: 2000 }
    )

    // 部位备注在**②加工项**（2026-09-29 起与特殊选项同一步；新行缺省停在步骤 1）⇒ 逐行展开；
    // ⚠️ 顺序要紧：②加工项一展开，该行的 `用料米数` 读数就随步骤 1 卸载 ⇒ 必须放在上面之后。
    // ⚠️ 显式压到 2s：`tests/setup.ts` 把 `asyncUtilTimeout` 提到了 5s，与 vitest 默认单测超时
    // **相等** ⇒ 未命中时会报「Test timed out」而不是「找不到元素」，红证里读不出判据。
    await waitFor(
      () => {
        openOtherSteps()
        expect(screen.getAllByTestId('line-item-remark')).toHaveLength(2)
      },
      { timeout: 2000 }
    )
    expect(remarkInput(1).value).toBe('')

    await submit()
    await waitFor(() => expect(mockCreateOrder).toHaveBeenCalled())
    const items = mockCreateOrder.mock.calls[0][0].items
    expect(items).toHaveLength(2)
    // 前提自证：两行都真的产出了 processingInfo 且逐值相同（否则下面的「没有 remark 键」是空断言）
    // ⚠️ 不用 `toBeDefined()`：它是 QA Growth Gate 的**弱断言**形态
    //（`.github/growth_gate.py` 的 `_TS_WEAK_PATTERNS`）⇒ 新增测试文件里一出现就判红。
    expect(items[0].processingInfo.processingMeters).toBe(13.3)
    expect(items[1].processingInfo.processingMeters).toBe(13.3)
    expect(items[0].processingInfo.remark).toBe(typed)
    // 红证：若备注存在页面级共享 state（或被写进每一行）⇒ 第二行会拿到同一串 ⇒ 本条红
    expect('remark' in items[1].processingInfo).toBe(false)
  }, 30000)
})
