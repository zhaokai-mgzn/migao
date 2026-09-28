// case_ids: OR-052
// @vitest-environment jsdom
/**
 * 下单页**版面重排**（2026-09-28 用户裁定，逐字见 `.github/cases/order.yml` 的 OR-052）。
 *
 * 用户口径：「订单这里的布局得优化，正常用户提供净窗高/窗宽，然后再确认是否要韩折/打孔
 * 定型等信息即可，其他信息尽量推导，加工项组合可以让用户确认是否采纳」+「这个拍照/上传识别
 * 功能应该放到商品信息那」。
 *
 * 落地形态（**只动版面与默认预选，不动任何推导链路**）：
 * ① **净尺寸**（窗宽 / 窗高）提到**组级**：紧跟在「选择商品 / 颜色」之后、**门幅之前**
 *    —— 门幅规则要等尺寸填齐才能自动选最省门幅（#4877 裁定 C / #4899），改前是「先撞上选门幅」；
 * ② 门幅、用料米数、单价**常态只读**（「其他信息尽量推导」），各自一个「改」入口就地变输入框；
 * ③ 加工项区顶部是**系统推荐组合**（韩折 + 布帘「定型」）并**预选**，商家一键**采纳 / 全不采纳**；
 * ④ 特殊选项 / 部位备注收进第三步「其他」（默认收起）；
 * ⑤ 「拍照 / 上传识别」从「收货信息」卡移到**「商品信息」卡标题行**（它一次产出明细 + 收货信息 + 备注）。
 *
 * ⚠️ 本文件钉的是**版面与默认值**，不复制任何算料 / 判定口径（那些各有单一真值源与自己的判据）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const mockCreateOrder = vi.fn()
const mockGetProducts = vi.fn()
const mockGetProduct = vi.fn()
const mockGetProcessingItems = vi.fn()
const mockCraftCalcPreview = vi.fn()
const mockFeePreview = vi.fn()

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
 * 目录里给「韩折 / 定型 / 打孔」三项（V83 种子形状的名字，见 `orders-new.test.tsx` 的同类注释）。
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
          { id: 'pi-hz', name: '韩折', craftHint: '韩褶', unit: '米' },
          { id: 'pi-dx', name: '定型', unit: '米' },
          { id: 'pi-dk', name: '打孔', craftHint: '打孔', unit: '米' },
        ],
      },
    },
  })
  mockCraftCalcPreview.mockResolvedValue(CALC_OK)
  mockFeePreview.mockResolvedValue(feeMatched())
}

describe('#OR-052 下单页版面重排（尺寸优先 / 推导只读可就地改 / 推荐组合 / 其他折叠）', () => {
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

  it('判据 3：用料米数 / 单价**默认只读**，点「改」才可输入；改完照旧落 payload', async () => {
    await setupLine()
    // 常态只读（「其他信息尽量推导」）——闸门断言在 `readOnly` 属性上：
    // ⚠️ 刻意**不**断言「只读态下 fireEvent.change 不生效」：jsdom 的 fireEvent 会绕过 readOnly
    // 直接写 DOM 值再派发事件（真实浏览器里用户敲不进去，这里却敲得进）⇒ 那种断言在 jsdom 里
    // 恒假、在真浏览器里又无从复现，属于**测不出被测行为**的假判据。真正的行为由下面三段落库证据承担。
    expect(inputOf('用料米数').readOnly).toBe(true)
    expect(inputOf('单价 (¥/米)').readOnly).toBe(true)

    fireEvent.click(screen.getByTestId('meters-edit'))
    fireEvent.click(screen.getByTestId('price-edit'))
    expect(inputOf('用料米数').readOnly).toBe(false)
    expect(inputOf('单价 (¥/米)').readOnly).toBe(false)
    fireEvent.change(inputOf('用料米数'), { target: { value: '9.5' } })
    fireEvent.change(inputOf('单价 (¥/米)'), { target: { value: '88' } })

    const line = await submittedLine()
    expect(line.processingInfo.processingMeters).toBe(9.5)
    expect(line.unitPrice).toBe(88)
  })

  it('判据 4：门幅常态只读（含来源）；点「改」才出 chips，换一支 ⇒ 来源翻「人工选定」', async () => {
    await setupLine()
    expect(screen.getByTestId('sku-summary').textContent).toContain('门幅 2.8米')
    expect(screen.getByTestId('sku-summary-source').textContent).toBe('系统按门幅规则自动选中')
    // 常态不出 chips（省点击）——红证方向：把摘要整块删掉换回 chips ⇒ 上面两条红
    expect(screen.queryByRole('button', { name: /2\.8米/ })).toBeNull()

    fireEvent.click(screen.getByTestId('sku-picker-toggle'))
    const chip = await screen.findByRole('button', { name: /2\.8米/ })
    fireEvent.click(chip)
    // chips 换完不自动收起 ⇒ 点「收起规格」回到只读摘要
    fireEvent.click(screen.getByTestId('sku-picker-toggle'))
    await waitFor(() =>
      expect(screen.getByTestId('sku-summary-source').textContent).toBe('人工选定')
    )
  })

  it('判据 5：推荐组合**默认预选**（韩折 + 布帘定型），推荐条逐字给出这组名字', async () => {
    await setupLine()
    openStep(/^\d+ 加工项/)
    expect(checkedItems()).toEqual(['韩折', '定型'])
    expect(screen.getByTestId('processing-recommended-names').textContent).toBe('韩折 + 定型')
  })

  it('判据 5b：「全不采纳」⇒ 两项都取消，且落库不再含它们', async () => {
    await setupLine()
    openStep(/^\d+ 加工项/)
    fireEvent.click(screen.getByTestId('processing-recommended-reject'))
    expect(checkedItems()).toEqual([])

    // 勾一个**非推荐**项，让本行仍有选配（否则「落库不含韩折/定型」缺少对照面）
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
    // 韩折（工艺项）顶掉打孔；定型（非工艺项）不受单值护栏影响
    expect(checkedItems()).toEqual(['韩折', '定型'])
    expect(toast.info).toHaveBeenCalledWith('一张单只能有一个工艺：已把「打孔」换成「韩折」')
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

  it('判据 7：「其他」默认收起（特殊选项 / 部位备注都不在首屏），展开后两块都在', async () => {
    await setupLine()
    expect(screen.getByRole('button', { name: /^\d+ 其他/ }).getAttribute('aria-expanded')).toBe(
      'false'
    )
    expect(screen.queryByTestId('line-item-remark')).toBeNull()
    // 特殊选项那块**没有标题**，用它的一个选项名当锚（`加铅块` 只出现在这里）
    expect(screen.queryByRole('button', { name: '加铅块' })).toBeNull()

    openStep(/^\d+ 其他/)
    expect(screen.getByTestId('line-item-remark')).toBeTruthy()
    expect(screen.getByRole('button', { name: '加铅块' })).toBeTruthy()
  })
})
