// case_ids: OR-052
// @vitest-environment jsdom
/**
 * 下单页**版面重排**（2026-09-28 用户裁定，逐字见 `.github/cases/order.yml` 的 OR-052）。
 *
 * 用户口径（**原话**）：「订单这里的布局得优化，正常用户提供净窗高/窗宽，然后再确认是否要韩折/打孔
 * 定型等信息即可，其他信息尽量推导，加工项组合可以让用户确认是否采纳」+「这个拍照/上传识别
 * 功能应该放到商品信息那」。
 *
 * 落地形态（**只动版面与默认预选，不动任何推导链路**）：
 * ① **净尺寸**（窗宽 / 窗高）提到**组级**：紧跟在「选择商品 / 颜色」之后、**门幅之前**
 *    —— 门幅规则要等尺寸填齐才能自动选最省门幅（#4877 裁定 C / #4899），改前是「先撞上选门幅」；
 * ② ~~门幅、用料米数、单价**常态只读**（「其他信息尽量推导」），各自一个「改」入口就地变输入框~~
 *    —— **2026-09-29 改判**（用户逐字「**移除这种设计**，当前编辑态就是允许用户直接更改的」）：
 *    三个「改」入口**整条退场**，门幅 chips 与用料米数 / 单价**常态直接可用**；
 * ③ 加工项区顶部是**系统推荐组合**（韩褶 + 布帘「定型」）并**预选**，商家一键**采纳 / 全不采纳**；
 * ④ ~~特殊选项 / 部位备注收进第三步「其他」（默认收起）~~ —— **2026-09-29 改判**：两块并入
 *    **②加工项**（并改名「特殊选项」），下单页只剩**两步**；
 * ⑤ 「拍照 / 上传识别」从「收货信息」卡移到**「商品信息」卡标题行**（它一次产出明细 + 收货信息 + 备注）。
 * ⑥ **2026-09-30 第四批**（用户逐字，附 3 张截图）：「净尺寸能否和售卖形态放一行？」+「门幅放进用料与规格中，
 *    和用料米数、单价放一行？」+「人工加 / 改先隐藏，本期不需要该功能」+「这里的 fixed_height，用中文术语，
 *    不要用英文」+「这个用料米数输入框无法自由更改数值，修，改这个输入框不需要对其他参数进行联动」
 *    ⇒ 判据 11 **改判**（人工加 / 改 ⇒ 常态不可见）、**新增判据 16~18**（组级输入行 / 规格三格行 / 中文术语 /
 *    用料米数可自由录入）。**顺序口径（判据 1）一字未动**：净尺寸 → 门幅 / 规格 → 用料米数。
 *
 * ⚠️ 本文件钉的是**版面与默认值**，不复制任何算料 / 判定口径（那些各有单一真值源与自己的判据）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'

const mockCreateOrder = vi.fn()
const mockGetProducts = vi.fn()
const mockGetProduct = vi.fn()
const mockGetProcessingItems = vi.fn()
const mockCraftCalcPreview = vi.fn()
const mockFeePreview = vi.fn()
// 图片识别（issue #5794）：页面快通道的上传 + 识别两个端点（判据 12 驱动它们）
const mockImageRecognize = vi.fn()

vi.mock('@/lib/api', () => ({
  orderApi: { createOrder: (...a: unknown[]) => mockCreateOrder(...a) },
  productApi: {
    getProducts: (...a: unknown[]) => mockGetProducts(...a),
    getProduct: (...a: unknown[]) => mockGetProduct(...a),
  },
  processingItemApi: { getProcessingItems: (...a: unknown[]) => mockGetProcessingItems(...a) },
  customerApi: {
    getCustomers: () => Promise.resolve({ data: { data: { items: [], total: 0 } } }),
  },
  craftCalcApi: { preview: (...a: unknown[]) => mockCraftCalcPreview(...a) },
  // 图片识别（issue #5794 判据 12）：上传拿 URL → 识别端点回字段表
  uploadApi: {
    uploadImage: () => Promise.resolve({ data: { data: { url: 'https://cdn.test/order.png' } } }),
  },
  imageRecognizeApi: { recognize: (...a: unknown[]) => mockImageRecognize(...a) },
  // 自动特征判定面（issue #4976 包 2b）：本文件与它正交 ⇒ 服务端替身返回「不判」，
  // 免得提交闸门拦住无关断言（同 `orders-new-item-remark.test.tsx` 的口径）。
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
  // 门幅规则面（issue #5043 包 2b）：本文件用**单 SKU 颜色**（规则面无从发挥），
  // 仍给一个确定替身 —— 页面尺寸一变就会问它，缺桩会走异常分支（噪声，但不是本文件的口径）。
  doorWidthPlanApi: {
    preview: () =>
      Promise.resolve({
        data: {
          data: {
            state: 'single_panel',
            code: '',
            effective_cutting_mode: '定高买宽',
            door_width: 2.8,
            panels: null,
            splice: false,
            verdict: 'optimal',
            suggestion: null,
            reason: '替身：单幅可做',
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

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))

import { toast } from 'sonner'
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
      // 推导方案（形状同 `CraftCalcPlan`）——**必须给**，否则页面按「推导方案暂不可用」降级，
      // 「用料方案（系统推导）」块（`craft-plan-*`）整块不出（判定折叠 / 结论常显的判据就无从断言）。
      plan: {
        cutting_mode: '定高买宽',
        door_width: 2.8,
        panels: null as number | null,
        splice_option: null as string | null,
        splice_times: 0,
        join_height_m: null as number | null,
        join_width_m: null as number | null,
        meters: 13.3,
        auto: true,
        // ⚠️ reason 是**具体算例的事实陈述**（不得复述「选优顺序」——那份口径的单一真值源在
        // `docs/design/order-auto-derivation.md`，在别处复述会被 C1/C2 守卫判红）。
        reason: '自动推导：定高买宽单幅可做，用料 13.3 米',
        candidates: [
          { key: 'fixed_height', feasible: true, meters: 13.3, splice_times: 0, reason: null },
          {
            key: 'reversed',
            feasible: false,
            meters: null,
            splice_times: 3,
            reason: '倒幅 + 接宽不可行',
          },
        ],
      },
    },
  },
}

const feeMatched = () => ({
  data: {
    data: {
      items: [
        {
          processingFee: 133,
          processingFeeDetail: {
            composition: '韩褶+定型',
            unit_price: 10,
            meters: 13.3,
            meters_source: 'processingMeters',
            fee_source: 'matched',
            amount: 133,
            hint: null,
          },
        },
      ],
      processingFeeTotal: 133,
    },
  },
})

const inputOf = (label: string, idx = 0) =>
  screen
    .getAllByText(label)
    .map((el) => el.closest('div')!.querySelector('input') as HTMLInputElement)[idx]

/** a 是否排在 b **之前**（DOM 顺序 —— 版面重排的判据就是它，别用「存在性」代替） */
const appearsBefore = (a: HTMLElement, b: HTMLElement) =>
  Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING)

/** 展开某一步手风琴（互斥：展开一步会收起同级其它步） */
const openStep = (title: RegExp) => {
  const btn = screen.getAllByRole('button', { name: title })[0]
  if (btn.getAttribute('aria-expanded') === 'false') fireEvent.click(btn)
}

/** 已勾选的加工项名（按目录顺序） */
const checkedItems = () =>
  screen
    .getAllByRole('checkbox')
    .filter((c) => (c as HTMLInputElement).checked)
    .map((c) => c.getAttribute('aria-label'))

/** 某个单选 chips 组里**当前选中**的档（用于打开方式 / 加工类型这类 `radiogroup`） */
const checkedChips = (label: string) =>
  // 2026-09-29 第三次裁定：下拉**恒有一档选中**（含「未指定」档）⇒ 读数 = 当前选中项
  [ (screen.getByRole('combobox', { name: label }) as HTMLSelectElement).selectedOptions[0]?.textContent ?? '' ]

/**
 * 展开**唯一那一块**「推导细节」折叠区（🔴 2026-09-30 第六批起：① 门幅 / ② 用料公式 / ③ 用料方案
 * 三块都收在它里面，用它这一个标题行统一切换 —— 改前是三条各自折叠）。
 */
const openDerivationPanel = () => {
  const panel = screen.getByTestId('derivation-panel') as HTMLDetailsElement
  if (!panel.open) fireEvent.click(within(panel).getByText(/推导细节/))
  return panel
}

/** 展开「改工艺参数」区（推导方案就绪时它默认收起；展开才能看加工类型 / 打开方式 / 用料公式 chips） */
const openCraftParams = () => {
  const btn = screen.getAllByTestId('craft-plan-edit')[0]
  if (btn.getAttribute('aria-expanded') === 'false') fireEvent.click(btn)
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

const submittedLine = async (idx = 0) => {
  await submit()
  await waitFor(() => expect(mockCreateOrder).toHaveBeenCalled())
  return mockCreateOrder.mock.calls[0][0].items[idx]
}

/**
 * 选商品 → 选颜色（**单 SKU 颜色** ⇒ 规格自动选中）→ 填净尺寸（触发算料写回用料米数）。
 * 目录里给「韩褶 / 定型 / 打孔」三项（V83 种子形状的名字，见 `orders-new.test.tsx` 的同类注释）。
 */
async function setupLine() {
  render(<NewOrderPage />)
  fireEvent.click(await screen.findByText('点击搜索并选择商品'))
  fireEvent.click(await screen.findByText('遮光窗帘'))
  await screen.findByText('窗宽 (米)')
  fireEvent.click(await screen.findByRole('button', { name: '米白' }))
  fireEvent.change(inputOf('窗宽 (米)'), { target: { value: '6.6' } })
  fireEvent.change(inputOf('窗高 (米)'), { target: { value: '2.6' } })
  await waitFor(() => expect(inputOf('用料米数')).toHaveValue('13.3'))
}

const stubApis = () => {
  vi.clearAllMocks()
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
          { id: 'sku-28', colorId: 'c1', colorName: '米白', doorWidth: '2.8米', price: 100, stock: 73 },
        ],
      },
    },
  })
  mockGetProcessingItems.mockResolvedValue({
    data: {
      data: {
        items: [
          { id: 'pi-hz', name: '韩褶', craftHint: '韩褶', unit: '米' },
          { id: 'pi-dx', name: '定型', unit: '米' },
          { id: 'pi-dk', name: '打孔', craftHint: '打孔', unit: '米' },
        ],
      },
    },
  })
  mockCraftCalcPreview.mockResolvedValue(CALC_OK)
  mockFeePreview.mockResolvedValue(feeMatched())
  // 缺省：识别端点回「零可用字段」（degraded）—— 只有判据 12 会真的驱动它
  mockImageRecognize.mockResolvedValue({ data: { data: { degraded: true, fields: [] } } })
}

describe('#OR-052 下单页版面重排（2026-09-29 两步化：尺寸优先 / 常态可编辑 / 推荐组合 / 特殊选项并入加工项）', () => {
  beforeEach(stubApis)

  it('判据 1：净尺寸排在**门幅与用料之前**（用户口径「用户先提供净窗宽 / 净窗高」）', async () => {
    await setupLine()
    const size = screen.getByText('窗宽 (米)')
    const spec = screen.getByText('门幅 / 规格')
    const meters = screen.getByText('用料米数')
    // 红证方向：把净尺寸块放回门幅之下（改前形态）⇒ 前两条断言红
    expect(appearsBefore(size, spec)).toBe(true)
    expect(appearsBefore(spec, meters)).toBe(true)
    // 与「商品 / 颜色」同段（尺寸是商家的输入面，不是推导读数）
    expect(appearsBefore(screen.getByText('颜色'), size)).toBe(true)
  })

  it('判据 2：识别入口挂在**商品信息**卡标题行（不再挂在收货信息卡里）', async () => {
    render(<NewOrderPage />)
    const button = await screen.findByTestId('image-recognize-button')
    const cardOf = (title: string) => screen.getByText(title).closest('.p-6') as HTMLElement
    // 前置自证：两张卡都在（否则「不在收货信息卡里」是空断言）
    expect(cardOf('商品信息')).toBeTruthy()
    expect(cardOf('收货信息')).toBeTruthy()
    expect(cardOf('商品信息').contains(button)).toBe(true)
    expect(cardOf('收货信息').contains(button)).toBe(false)
  })

  it('判据 3（2026-09-29 改判）：用料米数 / 单价**常态可编辑**（「改」这一步已删除）；改完照旧落 payload', async () => {
    await setupLine()
    // 用户 2026-09-29 逐字：「**移除这种设计**，当前编辑态就是允许用户直接更改的」
    // ⇒ 两个框常态 `readOnly === false`，且**不再存在** `meters-edit` / `price-edit` 开关。
    // ⚠️ 与旧判据同一纪律：刻意**不**断言「只读态下 fireEvent.change 不生效」—— jsdom 的 fireEvent
    // 会绕过 readOnly（真实浏览器里敲不进去、这里却敲得进）⇒ 那种断言测不到被测行为（假判据）。
    // 真正的行为由下面两段落库证据承担。
    expect(inputOf('用料米数').readOnly).toBe(false)
    expect(inputOf('单价 (¥/米)').readOnly).toBe(false)
    expect(screen.queryByTestId('meters-edit')).toBeNull()
    expect(screen.queryByTestId('price-edit')).toBeNull()

    fireEvent.change(inputOf('用料米数'), { target: { value: '9.5' } })
    fireEvent.change(inputOf('单价 (¥/米)'), { target: { value: '88' } })

    const line = await submittedLine()
    expect(line.processingInfo.processingMeters).toBe(9.5)
    expect(line.unitPrice).toBe(88)
  })

  it('判据 4（🔴 2026-09-30 第五批改判）：门幅常态可选；**两块重复文案已删**，「为什么是这一支」只在推导细节里', async () => {
    await setupLine()
    // ① 下拉仍在（用户实测原话：常显 chips 网格「比较浪费空间」⇒ 改一行摘要 + 下拉）
    const select = screen.getByTestId('sku-select') as HTMLSelectElement
    expect(select.selectedOptions[0]?.textContent).toContain('2.8米')
    expect(screen.queryByTestId('sku-picker-toggle')).toBeNull()
    // ② 🔴 第五批（用户逐字「这种文字我觉得没有添加的必要，可以移除掉吧」）：两块**必须不存在** ——
    //    `sku-summary` 与 `<select>` 里选中项是同一串字；`sku-choice-reason` 与下面的「规则解 + 系统依据」重复。
    //    红证：把任一块加回来 ⇒ 本断言红（反向断言，防回潮）。
    expect(screen.queryByTestId('sku-summary')).toBeNull()
    expect(screen.queryByTestId('sku-choice-reason')).toBeNull()
    // ③ 「为什么是这一支」的**唯一**落点 = 门幅推导细节：它在**唯一那一块**推导细节折叠区
    //    （`derivation-panel`；🔴 2026-09-30 第六批：三条各自折叠 → **一整块**）里面，默认收起；
    //    展开这一块后候选清单 / 规则解 / 服务端依据都读得到
    //    （旧口径「系统按门幅规则自动选中」的**可读替代**就在这里，判据强度未降）
    const panel = openDerivationPanel()
    expect(panel.contains(screen.getByTestId('door-width-details'))).toBe(true)
    expect(screen.getByTestId('door-width-candidates').textContent).toContain('2.8米')
    expect(screen.getByTestId('door-width-rule-solution').textContent).toContain('2.8 米')
    expect(screen.getByTestId('door-width-plan-reason').textContent).toContain('替身：单幅可做')
    // 自动挑中时**一个字都不多**：手选才出现的那条不在
    expect(screen.queryByTestId('door-width-manual-note')).toBeNull()
  })

  it('判据 4b（🔴 第五批改判）：改下拉 ⇒ 规格换掉；「你手动选的」只收进推导细节（不再常显一行）', async () => {
    await setupLine()
    const select = screen.getByTestId('sku-select') as HTMLSelectElement
    fireEvent.change(select, { target: { value: select.options[0].value } })
    await waitFor(() => expect(screen.getByTestId('door-width-manual-note')).toBeInTheDocument())
    expect(screen.getByTestId('door-width-manual-note').textContent).toContain('手动选的')
    expect(select.selectedOptions[0]?.textContent).toContain('2.8米')
    // 常显那一行仍然不存在（第五批口径：噪声不进常态面）
    expect(screen.queryByTestId('sku-choice-reason')).toBeNull()
  })

  it('判据 5：推荐组合**默认预选**（韩褶 + 布帘定型），推荐条逐字给出这组名字', async () => {
    await setupLine()
    openStep(/^\d+\s*加工项/)
    expect(checkedItems()).toEqual(['韩褶', '定型'])
    expect(screen.getByTestId('processing-recommended-names').textContent).toBe('韩褶 + 定型')
  })

  it('判据 5b：「全不采纳」⇒ 两项都取消，且落库不再含它们', async () => {
    await setupLine()
    openStep(/^\d+\s*加工项/)
    fireEvent.click(screen.getByTestId('processing-recommended-reject'))
    expect(checkedItems()).toEqual([])

    // 勾一个**非推荐**项，让本行仍有选配（否则「落库不含韩褶/定型」缺少对照面）
    fireEvent.click(screen.getByRole('checkbox', { name: '打孔' }))
    const line = await submittedLine()
    expect(line.processingInfo.processingItems.map((i: { name: string }) => i.name)).toEqual(['打孔'])
    expect(line.processingInfo.craft).toBe('打孔')
  })

  it('判据 5c：「采纳」把推荐组合勾回来，并按**工艺单值护栏**顶掉别的工艺项', async () => {
    await setupLine()
    openStep(/^\d+\s*加工项/)
    fireEvent.click(screen.getByTestId('processing-recommended-reject'))
    fireEvent.click(screen.getByRole('checkbox', { name: '打孔' }))
    expect(checkedItems()).toEqual(['打孔'])

    fireEvent.click(screen.getByTestId('processing-recommended-adopt'))
    // 韩褶（工艺项）顶掉打孔；定型（非工艺项）不受单值护栏影响
    expect(checkedItems()).toEqual(['韩褶', '定型'])
    expect(toast.info).toHaveBeenCalledWith('一张单只能有一个工艺：已把「打孔」换成「韩褶」')
  })

  it('判据 6：撤销过（手改留痕）⇒ 改帘体**不再**把推荐组合勾回来', async () => {
    await setupLine()
    openStep(/^\d+\s*加工项/)
    fireEvent.click(screen.getByTestId('processing-recommended-reject'))
    expect(checkedItems()).toEqual([])

    fireEvent.click(screen.getByRole('radio', { name: '纱帘' }))
    fireEvent.click(screen.getByRole('radio', { name: '布帘' }))
    openStep(/^\d+\s*加工项/)
    // 红证方向：删掉 `craftItemTouched` / `shapedItemTouched` 的留痕 ⇒ 换帘体时被勾回 ⇒ 红
    expect(checkedItems()).toEqual([])
  })

  it('判据 7（2026-09-29 改判）：「特殊选项」并入②加工项 —— 没有独立的「其他」步骤，打开加工项两块一起可见', async () => {
    await setupLine()
    // ① 结构面：下单页**只有两步**（旧 ③「其他」的折叠壳与 `stepProps(3)` 已删除）
    expect(screen.getByRole('button', { name: /^\d+\s*加工项/ })).toHaveAttribute(
      'aria-expanded',
      'false'
    )
    expect(screen.queryByRole('button', { name: /^\d+\s*其他/ })).toBeNull()
    // ② ②加工项收起时，加工项与「特殊选项 / 部位备注」都不在首屏
    expect(screen.queryByTestId('line-item-remark')).toBeNull()
    expect(screen.queryByRole('button', { name: '加铅块' })).toBeNull()
    // ③ 打开②加工项 ⇒ 三块**一同可见**（不再需要第二个折叠块）
    openStep(/^\d+\s*加工项/)
    expect(screen.getByTestId('processing-recommended')).toBeTruthy()
    expect(screen.getByRole('button', { name: '加铅块' })).toBeTruthy()
    expect(screen.getByText('特殊选项')).toBeTruthy()
    expect(screen.getByTestId('line-item-remark')).toBeTruthy()
  })

  it('判据 8（2026-09-29 新增）：打开方式缺省 = **双开**；改窗宽**不再**自动推算开数', async () => {
    await setupLine()
    openCraftParams()
    // 用户裁定逐字：「打开方式默认改成双开，**不要自动推算**」⇒ 新建行缺省就是双开
    // 红证方向：把 `deriveOpenCount` 的启发式装回来（6.6 > 2.2 ⇒ 2 会**巧合**相同）⇒ 见下面那次 8 米
    expect(checkedChips('打开方式')).toEqual(['双开'])
    // 旧启发式：> 5 米 ⇒ **四开**。新行为：改窗宽**不动**开数（只有商家手改才变）
    fireEvent.change(inputOf('窗宽 (米)'), { target: { value: '8' } })
    expect(checkedChips('打开方式')).toEqual(['双开'])
  })

  it('判据 9（2026-09-29 新增）：用料公式下给出**参数说明**（哪个数是哪个参数 + 去哪改）', async () => {
    await setupLine()
    // 数值取自**同一次算料响应 / 算料配置**（`CALC_OK` 的 52 折 / 0.25 / 褶倍 2 + 配置的余量 0.3）
    const legend = await screen.findByTestId('meters-formula-legend')
    expect(legend.textContent).toContain('6.6=净窗宽（米）')
    expect(legend.textContent).toContain('0.3=每片余量（米 · 算料配置）')
    expect(legend.textContent).toContain('2=褶倍（算料配置）')
    expect(legend.textContent).toContain('52=自动算出的褶数')
    expect(legend.textContent).toContain('0.25=每折吃布（米 · 算料配置）')
    // 「要改参数去哪改」——用户口径「如果用户要修改参数也知道去改什么」
    const where = screen.getByTestId('meters-formula-legend-where')
    expect(where.textContent).toContain('净尺寸')
    expect(where.textContent).toContain('工艺配置 → 算料配置')
  })

  it('判据 10（🔴 2026-09-30 第六批改判）：推导细节**收拢为一个折叠区**、默认收起、不折叠套折叠', async () => {
    await setupLine()
    // 用户逐字（第六批）：「推导细节都收拢到一个折叠区域，打开后展示全部细节，直接用一行展示这块的
    // 标题+推导细节，默认折叠，通过文案提示用户可以打开」
    const panel = screen.getByTestId('derivation-panel') as HTMLDetailsElement
    // 形态：**这一块自己就是那个折叠项**（`<details>`），默认收起；引导语就是它的标题行
    // （它在 ① 的标题右侧栏里 ⇒ 与标题**同一行**）
    expect(panel.tagName).toBe('DETAILS')
    expect(panel.open).toBe(false)
    expect(panel.textContent).toContain('推导细节（默认收起，点标题展开）')
    // ① 门幅 / ② 用料公式 / ③ 用料方案 三块**全都收在它里面**（编号即标题 —— 用户说的「1 2 3」），
    // 且**都不再是折叠项**：整块里除它自己外没有任何 `<details>`（改前 = 三条各自折叠 ⇒ 本断言必红）
    expect(panel.querySelectorAll('details')).toHaveLength(0)
    expect(panel.contains(screen.getByTestId('door-width-details'))).toBe(true)
    expect(panel.contains(screen.getByTestId('meters-formula-block'))).toBe(true)
    expect(panel.contains(screen.getByTestId('craft-plan'))).toBe(true)
    expect(panel.textContent).toContain('① 门幅')
    expect(panel.textContent).toContain('② 用料公式')
    expect(panel.textContent).toContain('③ 用料方案')
    // **一次展开 = 全部细节看得见**（用户逐字「打开后展示全部细节」）：结论、逐项、依据、候选都在这一块里
    openDerivationPanel()
    expect(panel.open).toBe(true)
    expect(screen.getByTestId('craft-plan-mode')).toBeTruthy()
    expect(screen.getByTestId('craft-plan-headline')).toBeTruthy()
    expect(screen.getByTestId('craft-plan-meters')).toBeTruthy()
    expect(screen.getByTestId('craft-plan-reason')).toBeTruthy()
    expect(screen.getByTestId('craft-plan-candidates')).toBeTruthy()
  })

  it('判据 11（🔴 2026-09-30 改判）：系统识别常态可见；**人工加 / 改本期隐藏**（用户逐字「先隐藏，本期不需要该功能」）', async () => {
    await setupLine()
    // 收起「改工艺参数」（推导方案就绪时它默认收起；本判据先确保它在收起态）
    const toggle = screen.getAllByTestId('craft-plan-edit')[0]
    if (toggle.getAttribute('aria-expanded') === 'true') fireEvent.click(toggle)
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    // 用户裁定：「这两部分应该合并到用料与规格那里」⇒ 收起态下**系统识别**依然在
    expect(screen.getByTestId('auto-detected-features')).toBeTruthy()
    // 🔴 2026-09-30（第四批）：`craft-plan-manual` 本期**隐藏** —— 形态 = `display:none`
    // （`hidden` 类 ⇒ 屏幕上与**无障碍树**上都不存在，不是「藏在折叠里还能展开」），
    // 而**节点仍在 DOM** ⇒ 11 条既有页面判据（接高上限 / 拼次落库 / 项级来源 / 引擎拒绝态）
    // **一条不降**（铁律 8「只简化实现代码、不降测试门禁」）。
    // 红证方向：① 去掉 `hidden`（入口重新露面）⇒ 第 1 条红；② 整块删掉（连根拔掉那 11 条）⇒ 第 2 条红。
    const manual = screen.getByTestId('craft-plan-manual')
    expect(manual).toHaveClass('hidden')
    expect(manual).toBeInTheDocument()
    // 反向自证：工艺参数 chips 确实**随它收起**（它们仍归「改工艺参数」这一层）
    expect(screen.queryByTestId('craft-select-cutting-mode')).toBeNull()
  })

  it('判据 12（2026-09-29 新增）：图片下单 ⇒ **按图中客户要求**选工艺规格与加工项（不按系统默认）', async () => {
    mockImageRecognize.mockResolvedValue({
      data: {
        data: {
          degraded: false,
          fields: [
            { key: 'open_count', label: '打开方式', value: '单开', source: '[图片识别]', reason: null },
            { key: 'style', label: '款式', value: '拼色', source: '[图片识别]', reason: null },
            {
              key: 'processing_items',
              label: '加工项',
              value: '打孔、定型',
              source: '[图片识别]',
              reason: null,
            },
          ],
        },
      },
    })
    await setupLine()
    // 前置自证：**系统默认**是「双开 + 韩褶 + 定型」（判据 5 / 8 钉的就是它们）
    openCraftParams()
    expect(checkedChips('打开方式')).toEqual(['双开'])
    openStep(/^\d+\s*加工项/)
    expect(checkedItems()).toEqual(['韩褶', '定型'])
    openStep(/^\d+\s*用料与规格/)

    const file = new File(['x'], 'order.png', { type: 'image/png' })
    fireEvent.change(screen.getByTestId('image-recognize-input'), { target: { files: [file] } })

    // ① 留痕可见（①用料与规格 里逐字说出「按图选了什么」）
    const note = await screen.findByTestId('recognized-craft-note')
    expect(note.textContent).toContain('打开方式 单开')
    expect(note.textContent).toContain('款式 拼色')
    expect(note.textContent).toContain('加工项 打孔、定型')
    // ② 打开方式 / 款式按图（**盖过**缺省双开、缺省单色）
    openCraftParams()
    expect(checkedChips('打开方式')).toEqual(['单开'])
    expect(checkedChips('款式')).toEqual(['拼色'])
    // ③ 加工项按图 = 打孔 + 定型；**默认的「韩褶」被取消**（客户没提它 ⇒ 不能选错）
    openStep(/^\d+\s*加工项/)
    expect(checkedItems()).toEqual(['定型', '打孔'])
  })

  it('判据 16（2026-09-30 第四批）：净尺寸与**售卖形态同一行**；门幅 / 用料米数 / 单价**同一网格行**且在①用料与规格内', async () => {
    await setupLine()
    // ① 组级「输入行」= 售卖形态 + 帘体 + 净尺寸（商家唯二要选/要填的组级输入）
    const inputRow = screen.getByTestId('group-input-row')
    expect(inputRow.contains(screen.getByText('售卖形态'))).toBe(true)
    expect(inputRow.contains(screen.getByText('帘体'))).toBe(true)
    expect(inputRow.contains(screen.getByTestId('size-row'))).toBe(true)
    expect(inputRow.contains(inputOf('窗宽 (米)'))).toBe(true)
    expect(inputRow.contains(inputOf('窗高 (米)'))).toBe(true)
    // ② 规格行 = 门幅 / 规格 + 用料米数 + 单价（三个**系统给**、商家可就地改的数）
    const specRow = screen.getByTestId('spec-input-row')
    expect(specRow.contains(screen.getByTestId('sku-select'))).toBe(true)
    expect(specRow.contains(inputOf('用料米数'))).toBe(true)
    expect(specRow.contains(inputOf('单价 (¥/米)'))).toBe(true)
    // ③ 它在 **①用料与规格** 里（不再是组级独立块）
    expect(screen.getByTestId('wizard-step-1').contains(specRow)).toBe(true)
    // ④ 判据 1 的顺序口径不倒退：净尺寸 → 门幅 / 规格 → 用料米数
    const sizeRow = screen.getByTestId('size-row')
    const specLabel = screen.getByText('门幅 / 规格')
    expect(appearsBefore(sizeRow, specLabel)).toBe(true)
    expect(appearsBefore(specLabel, screen.getByText('用料米数'))).toBe(true)
  })

  it('判据 17（2026-09-30 第四批）：推导依据**用中文术语**（引擎文案里的候选键不裸露英文）', async () => {
    // 引擎 `derive_plan()` 的原样文案（键名冻结于契约 #5200 §三，展示层换中文）。
    // ⚠️ **刻意不复述「选优顺序」那一句**（单一真值源在 `docs/design/order-auto-derivation.md`）——
    // 逐字复述会被 `tests/unit_ci_workflows/test_craft_calc_ranking_order_single_source.py` 判红。
    mockCraftCalcPreview.mockResolvedValue({
      data: {
        data: {
          ...CALC_OK.data.data,
          plan: {
            ...CALC_OK.data.data.plan,
            reason:
              '自动推导：选定 fixed_height —— 成品高 2.6 + 上下卷边 0.15 = 2.75 米 ≤ 门幅 2.8 米 ⇒ 定高买宽单幅可做',
          },
        },
      },
    })
    await setupLine()
    const reason = screen.getByTestId('craft-plan-reason')
    // 红证（单点变异，实测）：把页面那处 `craftPlanReasonText(plan.reason)` 换回 `plan.reason`
    // ⇒ 第 1 条断言红（商家读到的正是「选定 fixed_height」）。
    expect(reason.textContent).toContain('定高买宽')
    expect(reason.textContent).not.toContain('fixed_height')
    // 候选清单与依据**同一份**中文名（两处不得分叉）
    expect(screen.getByTestId('craft-plan-candidate-fixed_height').textContent).toContain('定高买宽')
  })

  it('判据 18（2026-09-30 第四批）：用料米数**可自由录入小数**（原值 13.3 ⇒ 全选改 6.5，逐键都留得住）', async () => {
    await setupLine()
    const meters = inputOf('用料米数')
    expect(meters.value).toBe('13.3')
    // 商家全选改写 ⇒ 逐键序列 "6" → "6." → "6.5"（中间态不得被回显洗成 "0"）
    fireEvent.change(meters, { target: { value: '6' } })
    expect(meters.value).toBe('6')
    fireEvent.change(meters, { target: { value: '6.' } })
    // 红证（单点变异，实测）：把 `NumberInput` 渲染期回显守卫换回 `draftNumber(draft)` 形态
    // ⇒ 本断言收到 `'0'`，再敲 "5" 得到 `"05"` —— 用户现场截图里的「06」同形。
    expect(meters.value).toBe('6.')
    fireEvent.change(meters, { target: { value: '6.5' } })
    expect(meters.value).toBe('6.5')
    // 落库证据：改完就是商家敲的那个数（不被推导改回）
    expect((await submittedLine()).processingInfo.processingMeters).toBe(6.5)
  })

  it('判据 25（2026-09-30 第五批）：勾选 / 反选「韩褶」⇒ 用料公式与用料米数**自动联动**', async () => {
    // 用户逐字：「如果加工项这里没有勾选韩折，用料公式默认得用倍数法，如果勾选了韩折，默认用韩褶公式。
    // 而且勾选/反选韩折要自动联动用料公式和用料米数」
    // 公式跟着工艺 ⇒ 试算入参的 `formula` 变 ⇒ 试算签名变 ⇒ 米数按新公式重算（无第二份状态）。
    mockCraftCalcPreview.mockImplementation((params: Record<string, unknown>) => {
      const pleat = params.formula === 'pleat'
      return Promise.resolve({
        data: {
          data: {
            ...CALC_OK.data.data,
            fabric_meters: pleat ? 13.3 : 12.0,
            formula_text: pleat ? '韩褶公式：… 13.3米' : '褶倍数公式：… 12.0米',
          },
        },
      })
    })
    await setupLine()
    openStep(/^\d+\s*加工项/)
    const lastFormula = () => mockCraftCalcPreview.mock.calls.at(-1)?.[0]?.formula
    // 缺省：推荐组合把「韩褶」勾上了 ⇒ 韩褶公式
    await waitFor(() => expect(lastFormula()).toBe('pleat'), { timeout: 5000 })
    // 反选韩褶 ⇒ 缺省翻**倍数法**，米数按倍数法重算
    fireEvent.click(screen.getByRole('checkbox', { name: '韩褶' }))
    await waitFor(() => expect(lastFormula()).toBe('fullness'), { timeout: 5000 })
    // ⚠️ 用料米数在 **①** 里，而手风琴是互斥的（打开 ② 时 ① 已收起）⇒ 读之前先把 ① 打开
    openStep(/用料与规格/)
    await waitFor(() => expect(inputOf('用料米数')).toHaveValue('12'), { timeout: 5000 })
    // 再勾回来 ⇒ 回到韩褶公式，米数跟着回来
    openStep(/^\d+\s*加工项/)
    fireEvent.click(screen.getByRole('checkbox', { name: '韩褶' }))
    await waitFor(() => expect(lastFormula()).toBe('pleat'), { timeout: 5000 })
    openStep(/用料与规格/)
    await waitFor(() => expect(inputOf('用料米数')).toHaveValue('13.3'), { timeout: 5000 })
  }, 30000)

  it('判据 22（2026-09-30 第五批）：推算细节搬进 ① 标题**右侧**（不再压在表单下方）', async () => {
    await setupLine()
    // 用户逐字：「这里的一整趴如何推算的细节，放到 用料与规格（系统推导）这个标题的**右侧空白区域**」
    const aside = screen.getByTestId('wizard-aside-1')
    // 三块推导细节都在右侧栏：门幅推导细节 / 公式 + 参数说明 / 用料方案（只读）
    expect(aside.contains(screen.getByTestId('door-width-details'))).toBe(true)
    expect(aside.contains(screen.getByTestId('meters-formula-block'))).toBe(true)
    expect(aside.contains(screen.getByTestId('craft-plan'))).toBe(true)
    // ⚠️ 右侧栏必须是**标题按钮的兄弟**、排在其后：栏里有 `<details>` / 深链 / 按钮，
    // 嵌进 `<button>` 就是非法嵌套（同 `CollapsibleHeader` 的既有约束）—— 判的是 DOM 结构，不是措辞。
    const toggle = screen.getAllByRole('button', { name: /用料与规格/ })[0]
    expect(toggle.contains(aside)).toBe(false)
    expect(appearsBefore(toggle, aside)).toBe(true)
    // 主体里只剩「表单 + 裁决」：三格行**不在**右侧栏里（在它下面的主体里）
    expect(aside.contains(screen.getByTestId('spec-input-row'))).toBe(false)
    expect(aside.contains(screen.getByTestId('auto-detected-features'))).toBe(false)
    // 红证方向：把三块放回三格行之后（改前形态）⇒ `wizard-step-1-aside` 不存在 ⇒ 第一条红。
  })

  it('判据 23（2026-09-30 第五批）：系统识别块新增「接高 / 拼接」推导行（裁决入口**收敛一处**）', async () => {
    mockCraftCalcPreview.mockResolvedValue({
      data: {
        data: {
          ...CALC_OK.data.data,
          plan: {
            ...CALC_OK.data.data.plan,
            cutting_mode: '定高买宽',
            splice_times: 2,
            splice_option: '拼2次',
            join_height_m: 0.05,
          },
        },
      },
    })
    await setupLine()
    // 用户逐字：「系统识别（…可采纳 / 不采纳）这里再加**接高和拼接**两项」
    const features = screen.getByTestId('auto-detected-features')
    const derived = screen.getByTestId('craft-plan-derived-options')
    expect(features.contains(derived)).toBe(true)
    expect(derived.contains(screen.getByTestId('craft-plan-derived-option-拼2次'))).toBe(true)
    expect(derived.contains(screen.getByTestId('craft-plan-derived-option-接高'))).toBe(true)
    // **裁决入口只此一处**（用料方案块里不再有第二份 —— 同一件事不许两个操作面）
    expect(screen.getAllByTestId('craft-plan-derived-options')).toHaveLength(1)
    // 采纳 / 不采纳走**既有**机制（`onDerivedOptionDecision` / `derivedOptionDecisions`，不新造状态）
    expect(screen.getByTestId('craft-plan-derived-option-接高')).toHaveTextContent('已并入')
    fireEvent.click(screen.getByTestId('craft-plan-derived-reject-接高'))
    await waitFor(() =>
      expect(screen.getByTestId('craft-plan-derived-option-接高')).toHaveTextContent('已忽略')
    )
    fireEvent.click(screen.getByTestId('craft-plan-derived-adopt-接高'))
    await waitFor(() =>
      expect(screen.getByTestId('craft-plan-derived-option-接高')).toHaveTextContent('已并入')
    )
  })

  it('判据 24（2026-09-30 第五批）：拼接**可选档**（由推导决定 / 不拼接 / 拼1~3次），选完照旧落库', async () => {
    await setupLine()
    // 用户逐字：「拼接…可以先不做自动推导，**能让用户选择即可**」——档位就是既有那一份
    // `SPLICE_OVERRIDE_OPTIONS`（唯一真值），落库走既有 `planOverrides.spliceTimes` 链路。
    const group = screen.getByRole('radiogroup', { name: '拼接（人工加）' })
    expect(within(group).getByText('由推导决定')).toBeTruthy()
    fireEvent.click(within(group).getByText('拼2次'))
    expect(within(group).getByText('拼2次').getAttribute('aria-checked')).toBe('true')
    // 落库证据：拼次进 `specialOptions`（⇒ 服务端插工序 + 计件）
    const line = await submittedLine()
    expect(line.processingInfo.specialOptions).toContain('拼2次')
  })

  it('判据 28（2026-10-06，issue #6399）：「改工艺参数」**收起态**也要把当前所选摆出来并高亮', async () => {
    // 用户逐字：「订单详情中，这里折叠的部分得把折叠的内容展示出来，不然用户不知道选择了什么，
    // 而且得**高亮展示**」（截图红框 = `craft-plan-edit` 按钮这一行）。
    // 改前形态：收起态只有一句静态按钮文案，加工类型 / 打开方式 / 款式 / 用料公式的**当前值**
    // 全在被折叠的 `OrderCraftFields` 里（收起时该子树根本不渲染）⇒ 要核对只能点开一次。
    await setupLine()
    const toggle = screen.getAllByTestId('craft-plan-edit')[0]
    if (toggle.getAttribute('aria-expanded') === 'true') fireEvent.click(toggle)
    expect(toggle.getAttribute('aria-expanded')).toBe('false')

    // ① 四项当前值逐项可读（标签 + 值）——取值 = 页面侧唯一派生点 `derivedCraftSpec`
    //    （与展开态控件 / 试算 / 落库同一份，不是另抄一份读数）
    const current = screen.getByTestId('craft-plan-current')
    expect(current).toHaveTextContent('加工类型')
    expect(current).toHaveTextContent('定高买宽')
    expect(current).toHaveTextContent('打开方式')
    expect(current).toHaveTextContent('双开')
    expect(current).toHaveTextContent('款式')
    expect(current).toHaveTextContent('单色')
    expect(current).toHaveTextContent('用料公式')
    expect(current).toHaveTextContent('韩褶公式')
    // ② 高亮：primary 色系（与周围那一圈中性灰不同一档）——条本身有底色 + 边框，**值**是高亮文字
    //    红证方向：把 `bg-primary-50` / `text-primary-700` 退回中性灰 ⇒ 这两条断言红。
    expect(current.className).toContain('bg-primary-50')
    expect(current.className).toContain('border-primary-200')
    expect(within(current).getByText('定高买宽').className).toContain('text-primary-700')

    // ③ 展开态**不重复渲染**：内容本来就在眼前（同屏两份同一真值也会让按文案取元素的判据歧义）
    fireEvent.click(toggle)
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    expect(screen.queryByTestId('craft-plan-current')).toBeNull()

    // ④ 读数是**跟着改的值走**的（不是一份写死的快照）：款式改「拼色」⇒ 收起后读到「拼色」
    fireEvent.change(screen.getByTestId('craft-select-style'), { target: { value: '拼色' } })
    fireEvent.click(toggle)
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    await waitFor(() => expect(screen.getByTestId('craft-plan-current')).toHaveTextContent('拼色'))
  })
})
