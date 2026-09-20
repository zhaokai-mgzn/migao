// case_ids: OR-040
// @vitest-environment jsdom
/**
 * 下单页「**系统识别**」（自动识别）—— 放置位置（#4658）+ 可采纳/不采纳（#4657）。
 *
 * 用户 2026-09-20：「这里**推算的结果放在工艺规格选择那是不是更好**，他们两才是有联动的，
 * **加工项没有联动效果**，另外超宽是如何推算的？」+「**推算的结果应该允许用户采纳或者不采纳吧**，
 * 避免可能会推算错的情况」。
 *
 * 判据：
 * ① **位置**：块渲染在**②工艺规格**（`auto-detected-features`），**③加工项区只保留可勾的东西**
 *    （该区不得再出现「自动识别/推算」块 —— 它不可手选、与勾选无联动）；
 * ② **紧挨依据**：**逐条**显示 `reason` 文案（商家要能核对「为什么判它超宽」），不只是名字；
 * ③ **①尺寸行徽标**：填尺寸时就看得见识别结果（与②读**同一份** `detectAutoFeatures` 推导）；
 * ④ **可裁决**（#4657）：每条可 采纳/不采纳，系统漏判可**强制加**；**生效值**
 *    = `推算 ∪ 强制加 − 不采纳` ⇒ **唯一**进加工费组合键（`processingInfo.processingItems[].name`）；
 * ⑤ **留痕**：行上看得见「已忽略系统推算（依据：…）」/「手动加（系统未推算）」；
 * ⑥ **门幅取默认值时界面看得出来**（那是「推算可能错」的最大来源）；
 * ⑦ **判据 8 不放宽**：推导项**仍不得**出现在手选控件里（覆盖控件是**独立**的按钮，不是勾选框）。
 *
 * 红证（实现前）：
 * - ③加工项区**有**该块（`stepSection('加工项')` 内能查到 `auto-detected-features`）⇒ ①必红；
 * - ②工艺规格区**无**该块、`reason` 只在 `title` 属性里（正文无依据文案）⇒ ②必红；
 * - 无 `size-auto-badge-*` / `auto-feature-reject-*` / `auto-feature-add-*` ⇒ ③④必红。
 *
 * 🔴 issue #4661（**本文件已按新真值改钉**）：**超宽/超高按加工类型分流** ——
 * 页面默认档 `cuttingMode` = `定高买宽`（`DEFAULT_CUTTING_MODE`）⇒ **只判超高**（宽按米买、无上限），
 * `定宽买高` ⇒ 只判超宽（+ 倒幅）。本文件原先有 5 条断言把「定高买宽 ⇒ 推超宽（+ 超高）」钉成期望值
 * （= 同一个 bug 的页面层镜像：多推的「超宽」会进加工费组合键 ⇒ 价算错）⇒ 逐条**改钉新真值**
 * （**不是放宽**：断言仍是 `getByText`/`toEqual` 精确形态，另加反向断言）。
 *
 * 🔴 issue #4662（**本文件已按新真值改钉 + 新增**）：①「超宽」判据**含褶倍**
 * （`(宽 + SIDE_MARGIN) × 褶倍 > 门幅`，与算料引擎算分幅同源；页面的褶倍 = 页面钉死的
 * `craft_tier='standard'` ⇒ `STANDARD_FULLNESS`）—— 韩褶大窗改前**不报**、改后报；
 * ② 加工类型**几何矛盾**（商家选「定高买宽」而 `高 + 卷边 > 门幅`）⇒ ②系统识别块里
 * **显式提示**「系统实际会按定宽买高算」（与算料引擎的自动回落一致；**不改变**推算，
 * 提示**不进**加工费组合键）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'

const mockCreateOrder = vi.fn()
const mockGetProducts = vi.fn()
const mockGetProduct = vi.fn()
const mockGetProcessingItems = vi.fn()
const mockGetCustomers = vi.fn()

vi.mock('@/lib/api', () => ({
  orderApi: { createOrder: (...a: unknown[]) => mockCreateOrder(...a) },
  productApi: {
    getProducts: (...a: unknown[]) => mockGetProducts(...a),
    getProduct: (...a: unknown[]) => mockGetProduct(...a),
  },
  processingItemApi: { getProcessingItems: (...a: unknown[]) => mockGetProcessingItems(...a) },
  customerApi: { getCustomers: (...a: unknown[]) => mockGetCustomers(...a) },
  craftCalcApi: { preview: () => new Promise(() => {}) },
  feePreviewApi: {
    preview: () =>
      Promise.resolve({
        data: {
          data: {
            items: [
              {
                processingFee: 0,
                processingFeeDetail: { fee_source: 'unpriced', amount: 0, hint: '去定价' },
              },
            ],
            processingFeeTotal: 0,
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

const openStep = (title: string) => {
  const btn = screen.getAllByRole('button', { name: new RegExp(`^\\d+ ${title}`) })[0]
  if (btn.getAttribute('aria-expanded') === 'false') fireEvent.click(btn)
}

/**
 * 某一步骤的**整段 DOM**（`WizardStep` 根 div = 标题按钮的父元素）——
 * 这样才能断言「某块**在不在**这一步里」：手风琴会把未展开步骤的内容**卸载**，
 * 只查 `screen.queryByTestId` 无法区分「不在这区」与「这区没展开」（会变成空断言）。
 */
const stepSection = (title: string) => {
  const btn = screen.getAllByRole('button', { name: new RegExp(`^\\d+ ${title}`) })[0]
  return btn.closest('div') as HTMLElement
}

const inputOf = (label: string, idx = 0) =>
  screen
    .getAllByText(label)
    .map((el) => el.closest('div')!.querySelector('input') as HTMLInputElement)[idx]

/**
 * 选商品（SKU 可带门幅）→ 填宽高。
 * ⚠️ issue #4661：缺省 `cuttingMode` = `定高买宽` ⇒ 6.6×2.6 对 2.8 门幅只识别出**超高**
 * （`2.6 + 0.3 = 2.9 > 2.8`）；「超宽」要 `定宽买高`（或强制加）才会出现。
 */
async function setupLine(opts: { doorWidth?: string; width?: string; height?: string } = {}) {
  const { doorWidth, width = '6.6', height = '2.6' } = opts
  mockGetProducts.mockResolvedValue({
    data: { data: { items: [{ id: 'p1', name: '遮光窗帘', price: 100 }], total: 1 } },
  })
  mockGetProduct.mockResolvedValue({
    data: {
      data: {
        id: 'p1',
        name: '遮光窗帘',
        price: 100,
        skus: [
          {
            id: 'sku1',
            colorId: 'c1',
            colorName: '米白',
            doorWidth,
            price: 100,
            sellingMethod: 'bulk_cut',
          },
        ],
      },
    },
  })

  render(<NewOrderPage />)
  fireEvent.click(await screen.findByText('点击搜索并选择商品'))
  fireEvent.click(await screen.findByText('遮光窗帘'))
  await screen.findByText('宽 (米)')
  // 有 SKU 时必须先选颜色 + 门幅（都是 chips 按钮），宽高输入才跟着该 SKU 走
  if (doorWidth) {
    fireEvent.click(await screen.findByRole('button', { name: '米白' }))
    fireEvent.click(await screen.findByText(doorWidth))
  }
  openStep('尺寸与数量')
  fireEvent.change(inputOf('宽 (米)'), { target: { value: width } })
  fireEvent.change(inputOf('高 (米)'), { target: { value: height } })
}

/** 填客户信息 → 提交 → 取**落库**的组合键加项（`processingInfo.processingItems[].name`） */
async function submitAndGetProcessingNames(): Promise<string[]> {
  fireEvent.change(screen.getByPlaceholderText('请输入收货人姓名'), { target: { value: '张三' } })
  fireEvent.change(screen.getByPlaceholderText('请输入 11 位手机号'), {
    target: { value: '13800138000' },
  })
  fireEvent.change(screen.getByPlaceholderText('请输入详细收货地址'), {
    target: { value: '杭州市' },
  })
  // 加工费计价闸门（#4450）：未就绪时提交会被拦 ⇒ 先等计价落地（真实商家也是看到金额才提交）
  await waitFor(() => expect(screen.queryByText(/加工费计价中/)).toBeNull())
  fireEvent.click(screen.getByText('提交订单'))
  await waitFor(() => expect(mockCreateOrder).toHaveBeenCalled())

  const info = mockCreateOrder.mock.calls[0][0].items[0].processingInfo as {
    processingItems: Array<{ name: string }>
  }
  return info.processingItems.map((i) => i.name)
}

beforeEach(() => {
  vi.clearAllMocks()
  mockGetProcessingItems.mockResolvedValue({
    data: {
      data: {
        items: [
          { id: 'pi1', name: '打孔加工', pricingMethod: 'per_meter', unitPrice: 5, unit: '米' },
        ],
      },
    },
  })
  mockGetCustomers.mockResolvedValue({ data: { data: { items: [], total: 0 } } })
})

describe('#4658：系统识别块在②工艺规格（不在③加工项）+ 逐条依据 + 尺寸行徽标', () => {
  it('#4658 ②工艺规格里出现「系统识别」，且**逐条**显示判定依据（reason 文案，不是只有名字）', async () => {
    await setupLine()
    openStep('工艺规格')

    const block = within(stepSection('工艺规格')).getByTestId('auto-detected-features')
    // 🔴 #4661 改钉：缺省档 = 定高买宽 ⇒ **只**出「超高」（改前这里断言「超宽 + 超高」两条都在）
    expect(within(block).getByText('超高')).toBeInTheDocument()
    expect(within(block).queryByText('超宽')).toBeNull()
    // 照实标注：推理非实证（设计 §5.2）—— **每条**特征都带来源标注
    const chips = block.querySelectorAll('span[title]')
    expect(chips.length).toBeGreaterThanOrEqual(1)
    for (const chip of Array.from(chips)) {
      expect(chip.textContent).toContain('（推算）')
      expect(chip.getAttribute('title')).toBeTruthy()
    }
    // 🔴 #4658 的核心：**正文里**逐条给依据（旧实现只在 `title` 属性里 ⇒ 商家看不见判定过程）
    // 🔴 #4661 改钉：余量按方向分开命名（宽 = 左右余量 / 高 = 上下卷边）—— 改前两条都写「卷边」
    expect(
      within(block).getByText(/成品高 2\.6 \+ 上下卷边 0\.3 = 2\.9 米 > 门幅 2\.8 米/)
    ).toBeInTheDocument()
    // 「超宽」在定高买宽下**不推算** ⇒ 它没有 reason 行；它只能被**强制加**（见 #4657 组）
    // ⚠️ 用**完整依据文案**做否定断言（不能只写 `/成品宽/` —— 那是 `+ 超宽` 强制加按钮的子串）
    expect(within(block).queryByText(/成品宽 6\.6 \+ 左右余量 0\.3/)).toBeNull()
    // 覆盖控件是**按钮**，不是勾选框（判据 8 不放宽）
    expect(block.querySelectorAll('input')).toHaveLength(0)
  })

  it('#4658 ③加工项区**只保留可勾的东西** —— 该区不得再出现「自动识别/推算」块', async () => {
    await setupLine()
    openStep('加工项')

    const section = stepSection('加工项')
    // 先自证「取到的确实是③加工项那一段」（否则下面的 null 断言会空跑）
    expect(within(section).getAllByRole('checkbox').length).toBeGreaterThan(0)
    expect(within(section).queryByTestId('auto-detected-features')).toBeNull()
    expect(within(section).queryByText(/自动识别/)).toBeNull()
    expect(within(section).queryByText(/推算/)).toBeNull()
  })

  // 🔴 #4661 改钉：缺省档（定高买宽）**不推超宽** ⇒ 徽标只有「超高」；
  // 改前这条断言「超宽 + 超高 两个徽标都在」（= 错口径在徽标面的镜像）。
  it('#4658 ①尺寸行旁的就地徽标：有识别结果时出现，不超时消失', async () => {
    await setupLine()
    expect(await screen.findByTestId('size-auto-badge-超高')).toBeInTheDocument()
    expect(screen.queryByTestId('size-auto-badge-超宽')).toBeNull()

    openStep('尺寸与数量')
    fireEvent.change(inputOf('宽 (米)'), { target: { value: '1.5' } })
    fireEvent.change(inputOf('高 (米)'), { target: { value: '1.5' } })

    await waitFor(() => expect(screen.queryByTestId('size-auto-badge-超高')).toBeNull())
    expect(screen.queryByTestId('size-auto-badge-超宽')).toBeNull()
  })

  it('#4657 门幅走了**默认值** ⇒ 界面看得出来（②标出 + ①徽标提示）', async () => {
    await setupLine() // 无 doorWidth ⇒ 默认 2.8
    expect(screen.getByTestId('size-door-width-fallback')).toBeInTheDocument()
    openStep('工艺规格')
    expect(screen.getByTestId('door-width-fallback')).toBeInTheDocument()
  })

  it('#4657 SKU 真的给了门幅 ⇒ **不谎报**成默认值（反向护栏）', async () => {
    await setupLine({ doorWidth: '2.8米' })
    expect(screen.queryByTestId('size-door-width-fallback')).toBeNull()
    openStep('工艺规格')
    expect(screen.queryByTestId('door-width-fallback')).toBeNull()
  })
})

describe('D6：自动识别结果只读可见（判据 8）', () => {
  it('改宽高 ⇒ 识别结果跟着变（不是写死的展示文案）', async () => {
    await setupLine()
    openStep('工艺规格')
    const block = screen.getByTestId('auto-detected-features')
    // 🔴 #4661 改钉：缺省档（定高买宽）推的是「超高」，不是「超宽」
    expect(within(block).getByText('超高')).toBeInTheDocument()

    openStep('尺寸与数量')
    fireEvent.change(inputOf('宽 (米)'), { target: { value: '1.5' } })
    fireEvent.change(inputOf('高 (米)'), { target: { value: '1.5' } })
    openStep('工艺规格')

    await waitFor(() => {
      expect(screen.queryByTestId('auto-feature-超宽')).toBeNull()
      expect(screen.queryByTestId('auto-feature-超高')).toBeNull()
    })
    // 缺省 cuttingMode = 定高买宽（= 正幅）⇒ #4592 起**不推导任何特征**。
    // 红证（修复前必红）：修复前这里恒有「正幅」，而「正幅」不在加工项目录里 ⇒
    // 默认订单的组合键永远匹配不到价 ⇒ 加工费恒 ¥0.00。
    expect(screen.queryByText('正幅')).toBeNull()
    // 块**仍在**（#4657 要能「强制加」+ 门幅默认值要可见）—— 但一条识别行都没有
    const blockAfter = screen.getByTestId('auto-detected-features')
    expect(within(blockAfter).queryByText('超宽')).toBeNull()
    expect(within(blockAfter).queryByText('超高')).toBeNull()
    expect(within(blockAfter).getByText(/系统未识别出特征/)).toBeInTheDocument()
  })

  it('门幅 = SKU.doorWidth：1.5 高 × 1.0 宽 对 2.8 门幅不超，对 1.4 窄幅门幅判超高', async () => {
    await setupLine({ doorWidth: '1.4米', width: '1.0', height: '1.5' })
    openStep('工艺规格')

    const block = screen.getByTestId('auto-detected-features')
    expect(within(block).getByText('超高')).toBeInTheDocument()
    expect(within(block).queryByText('超宽')).toBeNull()
  })

  it('自动识别结果**不是**可勾选项（没有它的 checkbox），也不计入「已选 N 项」', async () => {
    await setupLine()
    openStep('工艺规格')

    const block = screen.getByTestId('auto-detected-features')
    expect(block.querySelectorAll('input')).toHaveLength(0)
    // 一个手选加工项都没勾 ⇒ 摘要必须是「未选」（自动特征不算手选）
    // ⚠️ 用 `stepSection` 限定在③加工项那一段：④特殊选项的摘要也是「未选」（全局查会命中 2 处）
    expect(within(stepSection('加工项')).getByText('未选')).toBeInTheDocument()
  })

  // issue #4566（用户 2026-09-19 裁定「工艺规格中的**工艺，定型**……直接通过加工项来勾选」）：
  // 加工项目录里的**自动推导特征**（超高/超宽/倒幅）**必须存在**（商家配「加工费组合」时要能选到
  // `韩折+超高+定型` 这种名字），但**下单页的手选控件必须没有它们**（判据 8：手选项 ⇒ 红）。
  // 单一真值 = `lib/craft-auto-features.ts` 的 `AUTO_FEATURE_NAMES`（页面不抄第二份名字数组）。
  it('#4566 目录里的「超高/超宽/倒幅」**不出手选控件**（只出现在②只读的系统识别块里）', async () => {
    mockGetProcessingItems.mockResolvedValue({
      data: {
        data: {
          items: [
            { id: 'pi-02', name: '韩折', craftHint: '韩褶', pricingMethod: 'per_meter', unitPrice: 0, unit: '米' },
            { id: 'pi-06', name: '定型', pricingMethod: 'per_meter', unitPrice: 0, unit: '米' },
            { id: 'pi-14', name: '超高', pricingMethod: 'per_meter', unitPrice: 0, unit: '米' },
            { id: 'pi-15', name: '超宽', pricingMethod: 'per_meter', unitPrice: 0, unit: '米' },
            { id: 'pi-16', name: '倒幅', pricingMethod: 'per_meter', unitPrice: 0, unit: '米' },
          ],
        },
      },
    })
    await setupLine()

    // ③加工项：手选列表 = 目录 − 自动推导特征（红证：修复前这里会出现 5 个 checkbox）
    openStep('加工项')
    expect(screen.getAllByRole('checkbox').map((b) => b.getAttribute('aria-label'))).toEqual([
      '韩折',
      '定型',
    ])
    for (const auto of ['超高', '超宽', '倒幅']) {
      expect(screen.queryByRole('checkbox', { name: auto })).toBeNull()
    }
    // 推导结果照旧**只读可见**；🔴 #4661 改钉：缺省档（定高买宽）只出「超高」
    // （改前这里断言「超宽 + 超高」两条都在 = 错口径的页面层镜像），块内无任何输入控件
    openStep('工艺规格')
    const block = screen.getByTestId('auto-detected-features')
    expect(within(block).getByText('超高')).toBeInTheDocument()
    expect(within(block).queryByText('超宽')).toBeNull()
    expect(block.querySelectorAll('input')).toHaveLength(0)
  })
})

describe('#4657：推算结果可**采纳 / 不采纳** + 强制加（生效值唯一 ⇒ 组合键）', () => {
  it('#4657 不采纳「超高」⇒ 留痕「已忽略系统推算（依据：…）」且组合键里**不再含**它', async () => {
    await setupLine({ doorWidth: '2.8米' })
    openStep('工艺规格')

    // 红证（实现前）：无 `auto-feature-reject-*` 控件 ⇒ 本条必红
    // 🔴 #4661 改钉：缺省档（定高买宽）推的是「超高」⇒ 裁决对象随之改为「超高」
    fireEvent.click(screen.getByTestId('auto-feature-reject-超高'))

    // 留痕：行上看得见「已忽略系统推算」+ **原推算依据**（谁改的、原判据是什么）
    const rejected = await screen.findByTestId('auto-feature-rejected-超高')
    expect(rejected.textContent).toContain('已忽略系统推算')
    // 🔴 #4661 改钉：高方向余量名 = 「上下卷边」（改前写「卷边」）
    expect(rejected.textContent).toContain('成品高 2.6 + 上下卷边 0.3 = 2.9 米 > 门幅 2.8 米')
    // ① 徽标 = **生效值** ⇒ 超高消失
    expect(screen.queryByTestId('size-auto-badge-超高')).toBeNull()
    // 落库的组合键 = 生效值（唯一口径：界面与 payload 不会各说各话）⇒ 一条都不剩
    expect(await submitAndGetProcessingNames()).toEqual([])
  })

  it('#4657 不采纳后「采纳」⇒ 生效值回来（裁决可逆，不是单向开关）', async () => {
    await setupLine({ doorWidth: '2.8米' })
    openStep('工艺规格')

    fireEvent.click(screen.getByTestId('auto-feature-reject-超高'))
    await screen.findByTestId('auto-feature-rejected-超高')
    fireEvent.click(screen.getByTestId('auto-feature-adopt-超高'))

    await waitFor(() => expect(screen.queryByTestId('auto-feature-rejected-超高')).toBeNull())
    expect(screen.getByTestId('size-auto-badge-超高')).toBeInTheDocument()
    expect(await submitAndGetProcessingNames()).toEqual(['超高'])
  })

  it('#4657 系统**没推**也能**强制加**（如门幅数据缺失漏判）⇒ 组合键含它 + 留痕「手动加」', async () => {
    await setupLine({ doorWidth: '2.8米' })
    openStep('工艺规格')

    // 🔴 #4661 改钉：缺省档（定高买宽）**不推超宽** ⇒ 「超宽」正是「系统没推也能强制加」的真实场景
    // （改前它是被推算出来的，本用例测不到「强制加」这条路径）
    fireEvent.click(screen.getByTestId('auto-feature-add-超宽'))

    const manual = await screen.findByTestId('auto-feature-manual-超宽')
    expect(manual.textContent).toContain('手动加（系统未推算）')
    expect(screen.getByTestId('size-auto-badge-超宽')).toBeInTheDocument()
    // 生效值 = 推算 ∪ 强制加（顺序 = 推算在前；组合键归一化另有唯一实现）
    expect(await submitAndGetProcessingNames()).toEqual(['超高', '超宽'])
  })

  // 🔴 #4661 新增：把「分流」本身钉在页面链路上 —— 加工类型选 `定宽买高` ⇒ 只判**超宽**（+ 倒幅）、
  // 且**不判超高**（改前页面不把 cuttingMode 分流当回事 ⇒ 这条必红）。
  it('#4661 加工类型选「定宽买高」⇒ 系统识别出「超宽 + 倒幅」，**不**出「超高」', async () => {
    await setupLine({ doorWidth: '2.8米' })
    openStep('工艺规格')
    fireEvent.click(screen.getByRole('radio', { name: '定宽买高' }))

    const block = screen.getByTestId('auto-detected-features')
    await waitFor(() => expect(within(block).getByText('超宽')).toBeInTheDocument())
    expect(within(block).getByText('倒幅')).toBeInTheDocument()
    expect(within(block).queryByText('超高')).toBeNull()
    // 落库组合键 = 生效值（超宽 + 倒幅；宽方向余量名 = 「左右余量」）
    // 🔴 #4662 改钉：判据含**褶倍**（与引擎算分幅同源）⇒ 依据里看得见「× 褶倍 2 = 13.8 米」
    expect(
      within(block).getByText(/成品宽 6\.6 \+ 左右余量 0\.3 = 6\.9 米 × 褶倍 2 = 13\.8 米 > 门幅 2\.8 米/)
    ).toBeInTheDocument()
    expect(await submitAndGetProcessingNames()).toEqual(['超宽', '倒幅'])
  })

  /**
   * 🔴 issue #4592（P0）的用户可见症状的**落库面**判据：默认「定高买宽」订单的组合键
   * （= `processingInfo.processingItems[].name`，服务端 `featureNames()` 的唯一来源）
   * **不得**含 `正幅` —— 它不在 `processing_items` 目录（V83）里 ⇒ 商家配不出含它的组合
   * ⇒ 组合价永远匹配不到 ⇒ 加工费恒 ¥0.00。
   *
   * 红证（修复前必红）：修复前这里得到 `['超宽','超高','正幅']`（默认档 = 定高买宽）。
   *
   * 🔴 issue #4661：默认档（定高买宽）只判**高**方向 ⇒ 落库加项 = `['超高']`
   * （改前是 `['超宽','超高']` —— 多出的「超宽」正是错口径进组合键 ⇒ 价算错）。
   * 判据改钉新真值（**不是放宽**）：`toEqual` 仍是**精确**断言（不是 `toContain`/`not.toContain` 兜底），
   * 且下面那条「不得含 `正幅`」（#4592 的 P0 护栏）**一字未动**。
   */
  it('#4592 默认「定高买宽」订单落库的组合加项 = {超高}，**不含「正幅」**', async () => {
    // 带门幅 ⇒ setupLine 会连颜色 + 规格一起选上（缺颜色会被页面校验拦在提交前）
    await setupLine({ doorWidth: '2.8米' })

    const names = await submitAndGetProcessingNames()
    expect(names).toEqual(['超高'])
    expect(names).not.toContain('正幅')
  })
})

/**
 * issue #4662（用户 2026-09-20 裁定 A + C）：
 * ①「超宽」判据**含褶倍**（`(宽 + SIDE_MARGIN) × 褶倍 > 门幅`，与算料引擎算分幅同源）；
 * ② 加工类型**几何矛盾** ⇒ 界面**显式提示**「系统实际会按哪种算」（与引擎的自动回落一致）。
 *
 * 红证（改前实测）：① 韩褶大窗（宽 1.5 × 褶倍 2.0 + 余量 0.3 = 3.6 > 门幅 2.8）—— 改前只比
 * `1.5 + 0.3 = 1.8 ≤ 2.8` ⇒ ②系统识别块里**没有**「超宽」、落库组合键 = `['倒幅']`（该报不报 ⇒ 价算错）；
 * ② 缺省档（定高买宽）+ 高 2.6 + 卷边 0.3 = 2.9 > 门幅 2.8 ⇒ 改前**零提示**（前端推算「超高」
 * 与算料引擎实际按定宽买高算**静默不一致**）。
 */
describe('#4662 「超宽」含褶倍 + 加工类型几何矛盾显式提示（页面链路）', () => {
  it('#4662 韩褶大窗：切「定宽买高」+ 宽 1.5 ⇒ 推「超宽」（依据里带褶倍）+ 落库组合键含它', async () => {
    await setupLine({ doorWidth: '2.8米', width: '1.5', height: '2.6' })
    openStep('工艺规格')
    fireEvent.click(screen.getByRole('radio', { name: '定宽买高' }))

    const block = screen.getByTestId('auto-detected-features')
    await waitFor(() => expect(within(block).getByText('超宽')).toBeInTheDocument())
    // 依据里看得见**褶倍与乘积**（改前文案只有「成品宽 + 左右余量」，看不出会不会分幅）
    expect(
      within(block).getByText(/成品宽 1\.5 \+ 左右余量 0\.3 = 1\.8 米 × 褶倍 2 = 3\.6 米 > 门幅 2\.8 米/)
    ).toBeInTheDocument()
    // 高 2.6 + 0.3 = 2.9 > 2.8 ⇒ 与商家选的档位**一致**（引擎也按定宽买高）⇒ 无矛盾提示
    expect(screen.queryByTestId('auto-feature-notice-cutting-mode-conflict')).toBeNull()
    expect(await submitAndGetProcessingNames()).toEqual(['超宽', '倒幅'])
  })

  it('#4662 几何矛盾：缺省「定高买宽」+ 高超门幅 ⇒ 显式提示「系统实际会按定宽买高算」', async () => {
    await setupLine({ doorWidth: '2.8米' }) // 6.6 × 2.6 对 2.8 门幅：2.6 + 0.3 = 2.9 > 2.8
    openStep('工艺规格')

    const notice = screen.getByTestId('auto-feature-notice-cutting-mode-conflict')
    expect(notice.textContent).toContain('系统实际会按定宽买高算')
    // 依据说清（哪两个数比出来的）+ 门幅前提可见 —— 前端**不编**口径
    expect(notice.textContent).toContain('成品高 2.6 + 上下卷边 0.3 = 2.9 米')
    expect(notice.textContent).toContain('门幅 2.8 米')
    // 推算仍**以商家选的为准**（裁定 C）：特征 = ['超高']，不冒出「超宽 / 倒幅」
    expect(screen.getByTestId('auto-feature-超高')).toBeInTheDocument()
    expect(screen.queryByTestId('auto-feature-超宽')).toBeNull()
    expect(screen.queryByTestId('auto-feature-倒幅')).toBeNull()
    // 提示**不进**加工费组合键（它不是特征；目录里没有的名字 = 加工费恒 ¥0.00 的 P0 教训）
    expect(await submitAndGetProcessingNames()).toEqual(['超高'])
  })

  it('#4662 反向：切「定宽买高」+ 高不超门幅 ⇒ 提示「系统实际会按定高买宽算」', async () => {
    await setupLine({ doorWidth: '2.8米', width: '1.5', height: '1.5' })
    openStep('工艺规格')
    fireEvent.click(screen.getByRole('radio', { name: '定宽买高' }))

    const notice = await screen.findByTestId('auto-feature-notice-cutting-mode-conflict')
    expect(notice.textContent).toContain('系统实际会按定高买宽算')
  })

  it('#4662 几何一致 ⇒ 无矛盾提示（不制造噪音）', async () => {
    await setupLine({ doorWidth: '2.8米', width: '1.5', height: '1.5' }) // 缺省定高买宽 + 1.8 ≤ 2.8
    openStep('工艺规格')
    expect(screen.queryByTestId('auto-feature-notice-cutting-mode-conflict')).toBeNull()
  })
})
