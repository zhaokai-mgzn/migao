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
      // 推导方案（形状同 `CraftCalcPlan`）——**必须给**，否则页面按「推导服务未就绪」降级，
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
        reason:
          '自动推导（候选按「拼接最少 → 用料最少 → 接高接宽最少 → 表序」选优）：定高买宽单幅可做，用料 13.3 米',
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
  within(screen.getByRole('radiogroup', { name: label }))
    .getAllByRole('radio')
    .filter((r) => r.getAttribute('aria-checked') === 'true')
    .map((r) => r.textContent)

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

  it('判据 4（2026-09-29 改判）：门幅 chips **常态可选**；来源文案说人话（按窗宽挑最省料的那支）', async () => {
    await setupLine()
    // ① chips 常态就在（旧「只读摘要 + 点『改』展开」已删除）—— 选中态在无障碍树上可读（`aria-pressed`）
    // 红证方向：把 chips 藏回「改」后面 / 删掉 `aria-pressed` ⇒ 下面两条红
    expect(screen.getByRole('button', { name: /2\.8米/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.queryByTestId('sku-picker-toggle')).toBeNull()
    // ② 「为什么是这一支」= **可理解的原因**（含窗宽数），不再是那句没头没尾的「系统按门幅规则自动选中」
    const reason = screen.getByTestId('sku-choice-reason')
    expect(reason.textContent).toContain('窗宽 6.6 米')
    expect(reason.textContent).toContain('最省料')
    expect(reason.textContent).not.toContain('门幅规则')
  })

  it('判据 4b：商家点一下 chips ⇒ 选中态仍钉在同一支，来源翻「你手动选的规格」', async () => {
    await setupLine()
    fireEvent.click(screen.getByRole('button', { name: /2\.8米/ }))
    await waitFor(() =>
      expect(screen.getByTestId('sku-choice-reason').textContent).toContain('你手动选的规格')
    )
    expect(screen.getByRole('button', { name: /2\.8米/ })).toHaveAttribute('aria-pressed', 'true')
  })

  it('判据 5：推荐组合**默认预选**（韩褶 + 布帘定型），推荐条逐字给出这组名字', async () => {
    await setupLine()
    openStep(/^\d+ 加工项/)
    expect(checkedItems()).toEqual(['韩褶', '定型'])
    expect(screen.getByTestId('processing-recommended-names').textContent).toBe('韩褶 + 定型')
  })

  it('判据 5b：「全不采纳」⇒ 两项都取消，且落库不再含它们', async () => {
    await setupLine()
    openStep(/^\d+ 加工项/)
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
    openStep(/^\d+ 加工项/)
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
    openStep(/^\d+ 加工项/)
    fireEvent.click(screen.getByTestId('processing-recommended-reject'))
    expect(checkedItems()).toEqual([])

    fireEvent.click(screen.getByRole('radio', { name: '纱帘' }))
    fireEvent.click(screen.getByRole('radio', { name: '布帘' }))
    openStep(/^\d+ 加工项/)
    // 红证方向：删掉 `craftItemTouched` / `shapedItemTouched` 的留痕 ⇒ 换帘体时被勾回 ⇒ 红
    expect(checkedItems()).toEqual([])
  })

  it('判据 7（2026-09-29 改判）：「特殊选项」并入②加工项 —— 没有独立的「其他」步骤，打开加工项两块一起可见', async () => {
    await setupLine()
    // ① 结构面：下单页**只有两步**（旧 ③「其他」的折叠壳与 `stepProps(3)` 已删除）
    expect(screen.getByRole('button', { name: /^\d+ 加工项/ })).toHaveAttribute(
      'aria-expanded',
      'false'
    )
    expect(screen.queryByRole('button', { name: /^\d+ 其他/ })).toBeNull()
    // ② ②加工项收起时，加工项与「特殊选项 / 部位备注」都不在首屏
    expect(screen.queryByTestId('line-item-remark')).toBeNull()
    expect(screen.queryByRole('button', { name: '加铅块' })).toBeNull()
    // ③ 打开②加工项 ⇒ 三块**一同可见**（不再需要第二个折叠块）
    openStep(/^\d+ 加工项/)
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

  it('判据 10（2026-09-29 新增）：推导依据 / 候选**默认收起**，结论仍常显', async () => {
    await setupLine()
    const details = screen.getByTestId('craft-plan-details') as HTMLDetailsElement
    expect(details.open).toBe(false)
    // 结论（加工类型 / 用料）不随折叠消失 —— 收的只是「太多太细」的那半
    expect(screen.getByTestId('craft-plan-mode')).toBeTruthy()
    expect(screen.getByTestId('craft-plan-meters')).toBeTruthy()
    // 依据与候选**仍在 DOM**（既有判据照旧读得到），只是默认不展开
    expect(screen.getByTestId('craft-plan-reason')).toBeTruthy()
    expect(screen.getByTestId('craft-plan-candidates')).toBeTruthy()
    fireEvent.click(within(details).getByText(/推导依据/))
    expect(details.open).toBe(true)
  })

  it('判据 11（2026-09-29 新增）：系统识别 + 人工加 / 改**常态可见**（不依赖「改工艺参数」展开）', async () => {
    await setupLine()
    // 收起「改工艺参数」（推导方案就绪时它默认收起；本判据先确保它在收起态）
    const toggle = screen.getAllByTestId('craft-plan-edit')[0]
    if (toggle.getAttribute('aria-expanded') === 'true') fireEvent.click(toggle)
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    // 用户裁定：「这两部分应该合并到用料与规格那里」⇒ 收起态下两块依然在（不再藏在按钮后面）
    expect(screen.getByTestId('auto-detected-features')).toBeTruthy()
    expect(screen.getByTestId('craft-plan-manual')).toBeTruthy()
    // 反向自证：工艺参数 chips 确实**随它收起**（它们仍归「改工艺参数」这一层）
    expect(screen.queryByRole('radiogroup', { name: '加工类型' })).toBeNull()
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
    openStep(/^\d+ 加工项/)
    expect(checkedItems()).toEqual(['韩褶', '定型'])
    openStep(/^\d+ 用料与规格/)

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
    openStep(/^\d+ 加工项/)
    expect(checkedItems()).toEqual(['定型', '打孔'])
  })
})
