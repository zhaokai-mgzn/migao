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
 * ③ **①尺寸行徽标**：填尺寸时就看得见识别结果（与②读**同一份**判定结果 ——
 *    issue #4976 包 2b 起该判定来自**服务端**，本文件的服务端替身即「服务端会回什么」）；
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
 * （`窗宽 × 褶倍 > 门幅`，与算料引擎算分幅同源；页面的褶倍 = 页面钉死的
 * `craft_tier='standard'` ⇒ `STANDARD_FULLNESS`）—— 韩褶大窗改前**不报**、改后报；
 * ② 加工类型**几何矛盾**（商家选「定高买宽」而 `高 + 卷边 > 门幅`）⇒ ②系统识别块里
 * **显式提示**「系统实际会按定宽买高算」（与算料引擎的自动回落一致；**不改变**推算，
 * 提示**不进**加工费组合键）。
 *
 * 🔴 issue #5030（用户 2026-09-21 裁定，**本文件已按新真值改钉**）：订单宽高 = **窗户宽高**
 * （净窗宽 / 净窗高）⇒ 成品宽 = 净窗宽、成品高 = 净窗高；宽度用料 = `窗宽 × 褶倍`，
 * **不再另加「左右覆盖余量」**（常量 `SIDE_MARGIN` 与配置键 `side_margin` 一并退场）。
 * ⇒ 本文件的 fixture 删掉 `side_margin`、依据文案由 `成品宽 6.6 + 左右余量 0.3 = 6.9 米 × 褶倍 2
 * = 13.8 米` 改钉 `窗宽 6.6 × 褶倍 2 = 13.2 米`；标签由「宽/高 (米)」改钉「窗宽/窗高 (米)」。
 *
 * 🔴 **2026-09-22 改判（issue #5130，用户裁定 D1 / D2 / D3 / D7 / D10 / D11）**：
 * 判据由「与**门幅**比」换成「与**企业阈值参数**比」——
 * `净窗宽 > oversize_width_threshold`（默认 6）⇒ `超宽`；`净窗高 > oversize_height_threshold`
 * （默认 4）⇒ `超高`；`倒幅` **不变**（加工类型 = `定宽买高`）。三条旧判据**一并退役**（D10）：
 * ① **#4661 按加工类型分流**（`定高买宽` ⇒ 只判超高）—— 新判据与加工类型无关；
 * ② **#4662 超宽须含褶倍**（`窗宽 × 褶倍 > 门幅`）—— 新判据不含褶倍；
 * ③ **#4877 判定面**（缺门幅 ⇒ 都判不了）—— 新判据**不读门幅**（门幅仍是几何层输入）。
 * ⇒ 本文件逐条改钉（**不是放宽**，仍是 `getByText` / `toEqual` 精确形态 + 反向断言）：
 * 缺省档 6.6 × 2.6 现在推出的是 **`超宽`**（6.6 > 6）而**不是** `超高`（2.6 ≤ 4）；
 * 旧式中「窗宽 × 褶倍 = … 米 > 门幅 … 米」的依据文案**整条退场**，改钉「净窗宽 … 米 > 超宽阈值 … 米」。
 * 留档位置：引擎 `curtain_calc.detect_auto_features` 的 docstring / `lib/craft-calc-glossary.ts`
 * 的 `AUTO_FEATURE_TERMS` / `.github/cases/order.yml` 的「下单页系统识别」用例 merge_log。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { render, screen, fireEvent, waitFor, within, act } from '@testing-library/react'

const mockCreateOrder = vi.fn()
const mockGetProducts = vi.fn()
const mockGetProduct = vi.fn()
const mockGetProcessingItems = vi.fn()
const mockGetCustomers = vi.fn()

/** 判定端点入参（测试替身用；与 `lib/api.ts` 的 `AutoFeaturesParams` 同形） */
interface AutoFeaturesRequestForTest {
  width: number
  height: number
  fabric_width?: number
  cutting_mode?: string
  config?: { oversize_width_threshold?: number; oversize_height_threshold?: number }
}

/**
 * **服务端替身**（issue #4976 包 2b）：判定端点的返回值。
 *
 * 🔴 **2026-09-22 改判（issue #5130）**：逐值复刻引擎 `curtain_calc.detect_auto_features` 的**新**判据：
 * `净窗宽 > oversize_width_threshold` ⇒ `超宽`；`净窗高 > oversize_height_threshold` ⇒ `超高`
 * （阈值取**该租户配置**，缺省 = 引擎默认 `6 / 4`）；`加工类型 == 定宽买高` ⇒ `倒幅`。
 * **与门幅 / 褶倍 / 加工类型分流全无关**（#4661 / #4662 / #4877 三条判定面裁定已退役）。
 * 旧替身（「定高买宽 ⇒ 只判超高（高 + 卷边 > 门幅）」）是本文件过去钉的口径，已随裁定替换。
 */
/** 门幅规则请求（本文件用到的字段） */
interface DoorWidthPlanRequestForTest {
  width: number
  height: number
  door_widths: number[]
  cutting_mode?: string
  selected_door_width?: number
  fullness?: number
}

/**
 * **服务端替身**（issue #5043 包 2b）：门幅规则端点。
 *
 * 逐值复刻引擎的**规则面**（够本文件用）：定高买宽可行 ⇒ 取可行集**最小**门幅；
 * 否则 ⇒ 定宽买高（分幅最少、并列取较小门幅）；显式 `cutting_mode` ⇒ 人工覆盖。
 * ⚠️ 它是**服务端替身**（不是第二份实现）：代表「服务端会回什么」，页面只负责**展示**。
 */
const mockDoorWidthPlan = vi.fn((p: DoorWidthPlanRequestForTest) => {
  const hem = 0.3
  const side = 0.3
  const fullness = p.fullness ?? 2.0
  const candidates = [...new Set(p.door_widths)].sort((a, b) => a - b)
  const need = Math.round((p.height + hem) * 1000) / 1000
  const feasible = candidates.filter((g) => need <= g)
  const mode = p.cutting_mode ?? (feasible.length > 0 ? '定高买宽' : '定宽买高')
  let state: 'single_panel' | 'needs_splice' | 'undecidable' = 'single_panel'
  let door: number | null = null
  let panels: number | null = null
  if (mode === '定高买宽') {
    if (feasible.length > 0) door = feasible[0]
    else {
      state = 'needs_splice'
      door = candidates[candidates.length - 1]
    }
  } else {
    const ranked = candidates
      .map((g) => ({ g, panels: Math.max(1, Math.ceil(((p.width + side) * fullness) / g)) }))
      .sort((a, b) => a.panels - b.panels || a.g - b.g)
    door = ranked[0].g
    panels = ranked[0].panels
  }
  const selected = p.selected_door_width ?? null
  let verdict: 'optimal' | 'suboptimal' | 'infeasible' | 'unknown' = 'unknown'
  let suggestion: string | null = null
  if (selected !== null && door !== null) {
    if (state === 'needs_splice') {
      verdict = 'infeasible'
suggestion = `所选 ${selected} 米门幅单幅做不出成品高（缺口 ${Math.round((need - candidates[candidates.length - 1]) * 1000) / 1000} 米 ⇒ **需接高**）—— 本单**没有任何门幅**能单幅做成`
    } else if (selected === door) {
      verdict = 'optimal'
    } else if (mode === '定高买宽') {
      if (need > selected) {
        verdict = 'infeasible'
        suggestion = `所选 ${selected} 米门幅单幅做不出（成品高 ${p.height} + 上下卷边 ${hem} = ${need} 米 ⇒ **需接高**）；规则解 = ${door} 米门幅`
      } else {
        verdict = 'suboptimal'
        suggestion = `规则解是 ${door} 米门幅（可行集里最小）—— 换它可少占宽幅布`
      }
    } else {
      const sp = Math.max(1, Math.ceil(((p.width + side) * fullness) / selected))
      if (sp <= (panels ?? 1)) verdict = 'optimal'
      else {
        verdict = 'suboptimal'
        suggestion = `所选 ${selected} 米门幅要 ${sp} 幅；规则解 ${door} 米只要 ${panels} 幅`
      }
    }
  }
  return Promise.resolve({
    data: {
      data: {
        state,
        code: '',
        effective_cutting_mode: mode,
        door_width: door,
        panels,
        splice: state === 'needs_splice',
        verdict,
        suggestion,
        reason: '服务端替身给出的规则解',
      },
    },
  })
})

const mockAutoFeatures = vi.fn((params: AutoFeaturesRequestForTest) =>
  autoFeaturesServerDouble(params)
)

/** 服务端替身的**原始实现**（闸门用例会临时替换它，用完必须还原 —— `clearAllMocks` 不还原实现） */
async function autoFeaturesServerDouble(params: AutoFeaturesRequestForTest) {
  const hem = 0.3
  // 阈值取**该租户配置**（页面必须下发，见 `autoFeatureParamsOf`）；缺省 = 引擎默认 6 / 4
  const wide = params.config?.oversize_width_threshold ?? 6
  const high = params.config?.oversize_height_threshold ?? 4
  const round = (v: number) => Number(v.toFixed(3))
  const features: Array<{ name: string; source: string; reason: string }> = []
  // 提示（issue #5036）：由**服务端**给 —— 本替身复刻引擎 `detect_auto_feature_notices` 的输出。
  // 🔴 issue #5130 改判：只剩「几何矛盾」一条（缺门幅 / 缺褶倍两条已退役 ⇒ 不再产出它们）。
  const notices: Array<{ kind: string; reason: string }> = []
  // 判据 = 与**企业阈值**比（严格大于）—— 与门幅、褶倍、加工类型**全无关**
  if (params.width > wide) {
    features.push({
      name: '超宽',
      source: '推算',
      reason: `净窗宽 ${params.width} 米 > 超宽阈值 ${round(wide)} 米`,
    })
  }
  if (params.height > high) {
    features.push({
      name: '超高',
      source: '推算',
      reason: `净窗高 ${params.height} 米 > 超高阈值 ${round(high)} 米`,
    })
  }
  if (params.cutting_mode === '定宽买高') {
    features.push({ name: '倒幅', source: '推算', reason: '加工类型 = 定宽买高' })
  }
  // 几何矛盾提示（#4662 / #5036，issue #5130 **保留**）：引擎按「高 + 卷边 vs 门幅」唯一决定实际档位。
  // ⚠️ 缺门幅 ⇒ 没有几何依据 ⇒ 不提示（**不**回落到任何默认门幅 —— #4877 在几何层仍有效）。
  if (params.fabric_width != null) {
    const door = params.fabric_width
    const overHeight = params.height + hem > door
    const actualMode = overHeight ? '定宽买高' : '定高买宽'
    if (actualMode !== params.cutting_mode) {
      notices.push({
        kind: 'cutting-mode-conflict',
        reason:
          `加工类型选了「${params.cutting_mode}」，但成品高 ${params.height} + 上下卷边 ${hem} = ` +
          `${round(params.height + hem)} 米 ${overHeight ? '超过' : '未超过'}本 SKU 门幅 ${door} 米` +
          '（判据 = 算料引擎的几何分支「高 + 卷边 vs 门幅」，不读商家选的加工类型）' +
          `⇒ 按本 SKU 门幅口径，系统实际会按${actualMode}算` +
          '（⚠️ 引擎试算门幅尚未按本 SKU 门幅接线 —— #4746 / 待 #4652 ⇒ 引擎实际结果可能不同）',
      })
    }
  }
  return {
    data: { data: { auto_features: features, notices, door_width: params.fabric_width ?? null } },
  }
}

vi.mock('@/lib/api', () => ({
  orderApi: { createOrder: (...a: unknown[]) => mockCreateOrder(...a) },
  productApi: {
    getProducts: (...a: unknown[]) => mockGetProducts(...a),
    getProduct: (...a: unknown[]) => mockGetProduct(...a),
  },
  processingItemApi: { getProcessingItems: (...a: unknown[]) => mockGetProcessingItems(...a) },
  customerApi: { getCustomers: (...a: unknown[]) => mockGetCustomers(...a) },
  craftCalcApi: { preview: () => new Promise(() => {}) },
  // **自动特征判定端点**（issue #4976 包 2b）：判定已移到**服务端** ⇒ 本替身逐值复刻引擎判据
  // （issue #5130 改判后 = 净窗宽/净窗高 与**企业阈值**比 + `倒幅` 只看加工类型）。
  // ⚠️ 这是**服务端替身**（不是第二份实现）：它代表「服务端会回什么」，页面只负责**展示**。
  autoFeaturesApi: { preview: (p: unknown) => mockAutoFeatures(p as AutoFeaturesRequestForTest) },
  doorWidthPlanApi: { preview: (p: unknown) => mockDoorWidthPlan(p as DoorWidthPlanRequestForTest) },
  // **算料配置读面**（issue #4874）：公式缺省 + 档位 chips 的值域/文案都来自它 ⇒ 挂载即请求。
  // 🔴 issue #5130：两个**企业阈值**也在这里 —— 页面会把整份配置随判定请求下发（否则阈值静默不生效）。
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
              oversize_width_threshold: 6,
              oversize_height_threshold: 4,
            },
          },
        },
      }),
  },
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
/**
 * 等一次**服务端判定往返**（issue #4976 包 2b）。
 *
 * 判定已移到服务端 ⇒ 特征**不再同步可得**：本页 effect 防抖 400ms
 * （`orders/new/page.tsx` 的 `CRAFT_CALC_DEBOUNCE_MS`）后发请求、响应回来才写回行状态。
 *
 * 🔴 **不固定 sleep**：固定等 500ms 在慢机器上会假红（**本 PR 实测：CI 上就是这么红的**，
 * 本地全绿）。⇒ 轮询到「请求真的发出」为止，再让响应写回；宽高没齐（本就没有判定请求）⇒ 直接返回。
 */
async function settleAutoFeatures(): Promise<void> {
  try {
    // 2000ms 足够覆盖防抖 + 一次本地替身往返（比 vitest 的 5000ms 用例超时留足余量）
    await waitFor(() => expect(mockAutoFeatures).toHaveBeenCalled(), { timeout: 2000 })
  } catch {
    // 宽高没齐 ⇒ 本就没有判定请求（提交校验会拦），不必等
    return
  }
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0))
  })
}

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
          },
        ],
      },
    },
  })

  render(<NewOrderPage />)
  fireEvent.click(await screen.findByText('点击搜索并选择商品'))
  fireEvent.click(await screen.findByText('遮光窗帘'))
  await screen.findByText('窗宽 (米)')
  // 有 SKU 时必须先选颜色 + 门幅（都是 chips 按钮），宽高输入才跟着该 SKU 走
  if (doorWidth) {
    fireEvent.click(await screen.findByRole('button', { name: '米白' }))
    fireEvent.click(await screen.findByText(doorWidth))
  }
  openStep('尺寸与数量')
  fireEvent.change(inputOf('窗宽 (米)'), { target: { value: width } })
  fireEvent.change(inputOf('窗高 (米)'), { target: { value: height } })

  await settleAutoFeatures()
}

/**
 * 选商品（**同一颜色下有多个门幅 SKU**）→ 选颜色（**不点门幅**，交给门幅规则）→ 填宽高。
 *
 * issue #4877 裁定 C：多门幅时页面应按规则**自动选中**最省的那个门幅（可行集里最小门幅 /
 * 定宽买高取分幅最少）；客服仍可改（改了只提示、不覆盖）。
 */
async function setupLineMultiDoorWidth(opts: {
  widths: string[]
  width?: string
  height?: string
}): Promise<void> {
  const { widths, width = '3.0', height = '2.75' } = opts
  mockGetProducts.mockResolvedValue({
    data: { data: { items: [{ id: 'p1', name: '遮光窗帘', price: 100 }], total: 1 } },
  })
  mockGetProduct.mockResolvedValue({
    data: {
      data: {
        id: 'p1',
        name: '遮光窗帘',
        price: 100,
        skus: widths.map((w, i) => ({
          id: `sku${i}`,
          colorId: 'c1',
          colorName: '米白',
          doorWidth: w,
          price: 100,
        })),
      },
    },
  })
  render(<NewOrderPage />)
  fireEvent.click(await screen.findByText('点击搜索并选择商品'))
  fireEvent.click(await screen.findByText('遮光窗帘'))
  await screen.findByText('窗宽 (米)')
  // **只选颜色**：门幅留给规则自动选（issue #4877 裁定 C）
  fireEvent.click(await screen.findByRole('button', { name: '米白' }))
  openStep('尺寸与数量')
  fireEvent.change(inputOf('窗宽 (米)'), { target: { value: width } })
  fireEvent.change(inputOf('窗高 (米)'), { target: { value: height } })

  await settleAutoFeatures()
}

describe('#4877 门幅规则接线（裁定 C：规则驱动默认选中 + 非最优提示 + 需接高告警）', () => {
  it('多门幅 {2.8, 3.2} + 成品高 2.75 ⇒ 自动选中 **3.2**（否则 2.8 会判「需接高」/ 没选则「未维护」）', async () => {
    await setupLineMultiDoorWidth({ widths: ['2.8米', '3.2米'], width: '3.0', height: '2.75' })
    openStep('尺寸与数量')
    // 3.2 才做得下单幅（2.75 + 0.3 = 3.05 ≤ 3.2）⇒ 既不该报「需接高」，也不该是「门幅未维护」
    expect(screen.queryByTestId('door-width-needs-splice')).toBeNull()
    expect(screen.queryByTestId('door-width-missing')).toBeNull()
    expect(screen.queryByTestId('size-door-width-missing')).toBeNull()
  })

  it('客服选了**非最省**门幅（可行但更宽）⇒ 提示可换最优（**不改**客服的选择）', async () => {
    // 成品高 2.4 ⇒ 2.8 可行且是最小可行门幅 = 规则解 ⇒ 自动选中 2.8、**无**提示
    await setupLineMultiDoorWidth({ widths: ['2.8米', '3.2米'], width: '3.0', height: '2.4' })
    openStep('尺寸与数量')
    expect(screen.queryByTestId('door-width-suboptimal')).toBeNull()

    // 客服改成 3.2（仍可行，但不是规则解）⇒ 提示可选 2.8；选择**不被自动改回**
    fireEvent.click(await screen.findByText('3.2米'))
    const tip = await screen.findByTestId('door-width-suboptimal')
    expect(tip.textContent).toContain('2.8 米门幅')
    expect(screen.queryByTestId('door-width-needs-splice')).toBeNull()
  })

  it('所选门幅**单幅做不出**（成品高 2.75 对 2.8 门幅）⇒ 显式「需接高」强告警（缺口 0.25 米）', async () => {
    await setupLineMultiDoorWidth({ widths: ['2.8米'], width: '3.0', height: '2.75' })
    openStep('尺寸与数量')
    const warn = await screen.findByTestId('door-width-needs-splice')
    expect(warn.textContent).toContain('需接高')
    expect(warn.textContent).toContain('0.25')
  })
})

/**
 * 选商品（**给定 SKU 明细**：可含「同门幅多售卖方式」与库存）→ 选颜色（不点门幅，交给规则）→
 * 填宽高（传 `null` ⇒ **不填**，用于「尺寸未填」形态）。
 */
async function setupLineWithSkus(opts: {
  skus: Array<{ doorWidth: string; stock?: number; price?: number }>
  width?: string | null
  height?: string | null
}): Promise<void> {
  const { skus, width = '3.0', height = '2.4' } = opts
  mockGetProducts.mockResolvedValue({
    data: { data: { items: [{ id: 'p1', name: '遮光窗帘', price: 100 }], total: 1 } },
  })
  mockGetProduct.mockResolvedValue({
    data: {
      data: {
        id: 'p1',
        name: '遮光窗帘',
        price: 100,
        skus: skus.map((s, i) => ({
          id: `sku${i}`,
          colorId: 'c1',
          colorName: '米白',
          doorWidth: s.doorWidth,
          price: s.price ?? 100,
          stock: s.stock ?? 10,
        })),
      },
    },
  })
  render(<NewOrderPage />)
  fireEvent.click(await screen.findByText('点击搜索并选择商品'))
  fireEvent.click(await screen.findByText('遮光窗帘'))
  await screen.findByText('窗宽 (米)')
  fireEvent.click(await screen.findByRole('button', { name: '米白' }))
  openStep('尺寸与数量')
  if (width !== null) fireEvent.change(inputOf('窗宽 (米)'), { target: { value: width } })
  if (height !== null) fireEvent.change(inputOf('窗高 (米)'), { target: { value: height } })

  // 尺寸齐 ⇒ 会有判定请求 ⇒ 等它落地（本文件多处 `selectedInfo()` 会**提交订单**，
  // 判定未就绪会被提交闸门拦住 ⇒ 断言拿不到 payload）；
  // 🔴 尺寸未填（`null`）⇒ **本就没有判定请求** ⇒ **不要等**（白等会把用例拖过 5s 用例超时 —— CI 实测踩过）
  if (width !== null && height !== null) await settleAutoFeatures()
}

describe('#4899 反选门幅：**自动选中会被规则重算**、手选不被覆盖、判不了要显式说明', () => {
  // 红证（改前实测）：`autoSelectSkuByRuleForGroup` 里 `if (sample.selectedSku) return` ——
  // **自动选中的 SKU 也算「已选」** ⇒ 尺寸再变、规则解变了也不重算 ⇒ 页面停在旧门幅上
  // （用户 2026-09-21 人工验证：「无法通过工艺&加工项选配反选最优的门幅SKU」）。
  it('自动选中后改尺寸 ⇒ **自动改选**新的最优门幅（改前停在旧门幅 ⇒ 红）', async () => {
    await setupLineWithSkus({ skus: [{ doorWidth: '2.8米' }, { doorWidth: '3.2米' }], height: '2.4' })
    // 2.4 + 0.3 = 2.7 ≤ 2.8 ⇒ 规则解 = 2.8（自动选中）⇒ 无告警
    expect(screen.queryByTestId('door-width-needs-splice')).toBeNull()

    // 改成 2.75 ⇒ 2.8 不可行、3.2 可行 ⇒ **应自动改选 3.2**（停在 2.8 会报「需接高」⇒ 红）
    fireEvent.change(inputOf('窗高 (米)'), { target: { value: '2.75' } })
    await waitFor(() => expect(screen.queryByTestId('door-width-needs-splice')).toBeNull())
    // 🔴 **#5130 改判**：旧旁证（「3.2 生效 ⇒ 超高消失」）已不成立 —— 「超高」现在只看净窗高与
    // 企业阈值（2.75 ≤ 4），与门幅**无关**。⇒ 改为断言两个阈值特征都不出现
    //（3.0 宽 ≤ 6、2.75 高 ≤ 4），并留档「旧旁证为何退场」。
    expect(screen.queryByTestId('size-auto-badge-超高')).toBeNull()
    expect(screen.queryByTestId('size-auto-badge-超宽')).toBeNull()
  })

  // 回归护栏（**不是**红证条）：客服手选过 ⇒ 规则**不覆盖**，只提示可换最优。
  it('客服**手选**过 ⇒ 规则不覆盖（改尺寸后仍保持手选 + 只给提示）', async () => {
    await setupLineWithSkus({ skus: [{ doorWidth: '2.8米' }, { doorWidth: '3.2米' }], height: '2.4' })
    fireEvent.click(await screen.findByText('3.2米')) // 手选（非规则解）
    openStep('尺寸与数量')
    expect(await screen.findByTestId('door-width-suboptimal')).toBeInTheDocument()

    fireEvent.change(inputOf('窗高 (米)'), { target: { value: '2.5' } }) // 规则解仍是 2.8
    await waitFor(() => expect(screen.getByTestId('door-width-suboptimal')).toBeInTheDocument())
  })

  // 红证（改前实测）：最优门幅下有**多个 SKU**（散剪/整卷）时 `pickAutoSkuForColor` 返回 null
  // ⇒ 什么都不选 ⇒ 界面显示「门幅未维护」（**误导**：不是没维护，是没选到）。
  it('同一最优门幅下有多个 SKU（散剪/整卷）⇒ 也要选出一个默认（有库存优先）', async () => {
    await setupLineWithSkus({
      skus: [
        { doorWidth: '2.8米', stock: 5 },
        { doorWidth: '2.8米', stock: 0 },
      ],
      height: '2.4',
    })
    openStep('尺寸与数量')
    // 已经选中了一个 SKU ⇒ 不该出现「未维护门幅」的误导徽标
    expect(screen.queryByTestId('size-door-width-missing')).toBeNull()
  })

  // 红证（改前实测）：尺寸未填 ⇒ 规则 `undecidable`，页面**静默什么都不做**（用户看到「选不了门幅」）。
  it('尺寸未填 ⇒ **显式说明**「填完窗宽窗高后自动选最优门幅」（静默 ⇒ 红）', async () => {
    await setupLineWithSkus({ skus: [{ doorWidth: '2.8米' }, { doorWidth: '3.2米' }], width: null, height: null })
    openStep('尺寸与数量')
    const hint = await screen.findByTestId('door-width-need-size')
    expect(hint.textContent).toContain('自动选最优门幅')
    // 🔴 #5030 改判：文案由「填完成品宽高后…」改为「填完窗宽窗高后…」（口径变了 ⇒ 文案跟着变）
    expect(hint.textContent).toContain('填完窗宽窗高后')
    expect(hint.textContent).not.toContain('成品宽高')
  })
})

/** 填客户信息 → 提交 → 取**落库**的第一行（`processingInfo` 里带「哪一支 SKU 被选中」的证据） */
async function submitAndGetItemInfo(): Promise<{
  processingInfo: {
    doorWidth?: string
    skuId?: string
    processingItems: Array<{ name: string }>
    /** 索引签名：断言**某个键不存在**（如 V111 退场的 `sellingMethod`）时需要读它 */
    [key: string]: unknown
  }
}> {
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
  return mockCreateOrder.mock.calls[0][0].items[0]
}

/** 填客户信息 → 提交 → 取**落库**的组合键加项（`processingInfo.processingItems[].name`） */
async function submitAndGetProcessingNames(): Promise<string[]> {
  const { processingInfo } = await submitAndGetItemInfo()
  return processingInfo.processingItems.map((i) => i.name)
}

/**
 * issue #5014（用户 2026-09-21 逐字）：「同步改一下现在新增订单的自动推算功能，之前因为每个门幅
 * 有多个销售属性 散剪/整卷，反推出门幅高度后，就选择门幅 + **散剪**的 SKU 即可」。
 *
 * ⚠️ **2026-09-21 改判（V111，用户裁定）**：平局口径的**首位**「售卖方式 = 散剪优先」**已退场** ——
 * 它的前提「每个门幅有散剪/整卷两个销售属性」被用户推翻：售卖方式是**商品级基础属性**，
 * SKU 组合只有 **颜色 × 门幅** ⇒ 同一 (颜色, 门幅) 只有**一行** SKU，「按售卖方式选哪一支」
 * 这个问题不存在了（页面里的比较也已是死代码，已删）。
 * ⇒ 本 describe 现在只钉**仍然成立**的三级平局口径：**有库存优先 → 单价低者优先 → 按 id 稳定**。
 * 观测点 = **提交落库的** `doorWidth` / `skuId`（= 被选中 SKU 的证据），不是 DOM class。
 */
describe('#5014 自动选 SKU：有库存优先 → 单价低者优先 → 按 id 稳定（售卖方式首位已随 V111 退场）', () => {
  const selectedInfo = async () => (await submitAndGetItemInfo()).processingInfo

  // 判据 1（V111 改判）：同门幅多个 SKU ⇒ 必须选出一支，且按「有库存优先 → 单价低 → id」。
  // 红证方向：把排序改回「按售卖方式优先」（已退场的口径）或干脆不排 ⇒ 选中 sku0（无库存/高价）⇒ 本断言红。
  it('判据 1：同门幅两个 SKU ⇒ 选有库存且单价更低的那一支（不空选、不按已退场的售卖方式排）', async () => {
    await setupLineWithSkus({
      skus: [
        { doorWidth: '2.8米', stock: 1, price: 300 },
        { doorWidth: '2.8米', stock: 99, price: 50 },
      ],
      height: '2.4',
    })
    const info = await selectedInfo()
    expect(info.doorWidth).toBe('2.8米')
    expect(info.skuId).toBe('sku1')
  })

  // 判据 5（V111 改判）：两支都没库存 ⇒ 退到「单价低者优先」；仍要选出一支（不空选）。
  // 红证方向：去掉「单价」这一级 ⇒ 选中 sku0（价高）⇒ 本断言红。
  it('判据 5：两支都无库存 ⇒ 按单价低者优先（仍选出一支，不空选）', async () => {
    await setupLineWithSkus({
      skus: [
        { doorWidth: '2.8米', stock: 0, price: 300 },
        { doorWidth: '2.8米', stock: 0, price: 50 },
      ],
      height: '2.4',
    })
    expect((await selectedInfo()).skuId).toBe('sku1')
  })

  // 回归护栏（非红证条）：没有散剪可选时**仍要选出一支** ——
  // 空选会让界面谎报「门幅未维护」（#4899 的病根），且客服无从下手。
  it('判据 2：同门幅只有整卷 ⇒ 选整卷（不空选、不报「门幅未维护」）', async () => {
    await setupLineWithSkus({
      skus: [
        { doorWidth: '2.8米', stock: 5 },
        { doorWidth: '2.8米', stock: 0 },
        { doorWidth: '3.2米', stock: 5 },
      ],
      height: '2.4',
    })
    openStep('尺寸与数量')
    expect(screen.queryByTestId('size-door-width-missing')).toBeNull()
    const info = await selectedInfo()
    expect(info.doorWidth).toBe('2.8米')
    // 2.8 门幅下有两支（一支有库存 5、一支无库存 0）⇒ 选有库存那支
    expect(info.skuId).toBe('sku0')
  })

  // 回归护栏（非红证条）：**同一售卖方式**下多个 SKU ⇒ 沿用既有平局口径（库存 → 单价 → id）。
  // ⚠️ 3a/3b/3c 同时是「不许只按售卖方式排序」的守卫：只排售卖方式 ⇒ 这三条全红。
  it('判据 3a：同为散剪 ⇒ 有库存优先（无库存者单价再低也不选）', async () => {
    await setupLineWithSkus({
      skus: [
        { doorWidth: '2.8米', stock: 0, price: 10 },
        { doorWidth: '2.8米', stock: 5, price: 100 },
      ],
      height: '2.4',
    })
    expect((await selectedInfo()).skuId).toBe('sku1')
  })

  it('判据 3b：同为散剪且都有库存 ⇒ 单价低者优先', async () => {
    await setupLineWithSkus({
      skus: [
        { doorWidth: '2.8米', stock: 5, price: 300 },
        { doorWidth: '2.8米', stock: 5, price: 100 },
      ],
      height: '2.4',
    })
    expect((await selectedInfo()).skuId).toBe('sku1')
  })

  it('判据 3c：同为散剪且库存/单价相同 ⇒ 按 id 稳定（取 sku0）', async () => {
    await setupLineWithSkus({
      skus: [
        { doorWidth: '2.8米', stock: 5, price: 100 },
        { doorWidth: '2.8米', stock: 5, price: 100 },
      ],
      height: '2.4',
    })
    expect((await selectedInfo()).skuId).toBe('sku0')
  })

  // 回归护栏（非红证条）：该颜色只有一个 SKU ⇒ 直接选它（与门幅规则无关，既有行为不变）。
  it('判据 4：单 SKU 颜色 ⇒ 直接选它（与门幅规则无关）', async () => {
    await setupLineWithSkus({
      skus: [{ doorWidth: '2.8米', stock: 3 }],
      height: '2.4',
    })
    const info = await selectedInfo()
    expect(info.skuId).toBe('sku0')
    // V111：行级售卖方式不再由 SKU 派生（SKU 组合只有 颜色 × 门幅）⇒ 不落该键
    expect(info.sellingMethod).toBeUndefined()
  })
})

/**
 * issue #5020：**加工类型未指定 ⇒ 自动推导 + 自动选中；客服一点即改，且不被规则覆盖**。
 *
 * 口径（用户 2026-09-21 改判，见 issue #5020）：定高买宽可行（`成品高 + HEM_MARGIN ≤ 门幅有效值`）
 * ⇒ 取可行集里最小门幅 + `定高买宽`；否则 ⇒ 倒幅（分幅最少，并列取较小门幅）+ `定宽买高`；
 * 接高**不参与自动比较**（`needs_splice` 不得自动出现）；显式选择优先（人工覆盖保留）。
 *
 * 观测点 = 加工类型 chips 的 `aria-checked`（界面选中态）+ `door-width-*` 提示（规则解副作用）+
 * 落库 `processingInfo.cuttingMode`（= 真正下单的那个值，不只是「看起来选中」）。
 *
 * 红证（改前实测）：未指定加工类型 ⇒ `resolveCutPlan` 一律 `undecidable` ⇒ 自动解**不存在**
 * ⇒ 8a/8b 的 `checkedChips('加工类型')` 恒为 `['未指定']`、8d 落库 `cuttingMode` 为 `undefined`。
 */
describe('#5020 加工类型自动推导：未指定 ⇒ 自动选中；客服改后不被规则覆盖', () => {
  /** 某个 radiogroup 里 `aria-checked=true` 的 chip 文案（界面选中态的唯一证据） */
  const checkedChips = (label: string): string[] =>
    within(screen.getByRole('radiogroup', { name: label }))
      .getAllByRole('radio')
      .filter((el) => el.getAttribute('aria-checked') === 'true')
      .map((el) => el.textContent ?? '')

  /** 点某个 chip（客服手选 / 点「未指定」交还给规则） */
  const pickChip = (label: string, text: string) => {
    fireEvent.click(within(screen.getByRole('radiogroup', { name: label })).getByText(text))
  }

  it('判据 8a：未指定加工类型 ⇒ 按规则**自动选中**（成品高 2.75 ⇒ 定高买宽）', async () => {
    // 尺寸留空建单（`setupLineWithSkus` 的 `null` 档）⇒ 展开步骤后先点「未指定」，再填尺寸
    await setupLineWithSkus({ skus: [{ doorWidth: '2.8米' }, { doorWidth: '3.2米' }], width: null, height: null })
    openStep('尺寸与数量')
    pickChip('加工类型', '未指定')
    fireEvent.change(inputOf('窗宽 (米)'), { target: { value: '3.0' } })
    fireEvent.change(inputOf('窗高 (米)'), { target: { value: '2.75' } })
    // 2.75 + 0.3 = 3.05 ⇒ 2.8 判需接高、3.2 可行 ⇒ 自动解 = 3.2 + 定高买宽
    await waitFor(() => expect(checkedChips('加工类型')).toEqual(['定高买宽']))
    // 「看得见是自动的」：标出「自动」标记（否则客服会以为自己选过）
    expect(screen.getByTestId('cutting-mode-auto')).toBeInTheDocument()
    expect(screen.queryByTestId('door-width-needs-splice')).toBeNull()
  })

  it('判据 8b：未指定 + 可行集为空（成品高 3.0）⇒ 自动选中**定宽买高**（倒幅，不自动走接高）', async () => {
    await setupLineWithSkus({ skus: [{ doorWidth: '2.8米' }, { doorWidth: '3.2米' }], width: null, height: null })
    openStep('尺寸与数量')
    pickChip('加工类型', '未指定')
    fireEvent.change(inputOf('窗宽 (米)'), { target: { value: '3.0' } })
    fireEvent.change(inputOf('窗高 (米)'), { target: { value: '3.0' } })
    await waitFor(() => expect(checkedChips('加工类型')).toEqual(['定宽买高']))
    // **接高不得自动出现**（`needs_splice` 只在显式「定高买宽」+ 高度超限时才有）
    expect(screen.queryByTestId('door-width-needs-splice')).toBeNull()
  })

  it('判据 8c：客服**一点即改** ⇒ 按所选走；规则解变化**不得覆盖**手选值', async () => {
    await setupLineWithSkus({ skus: [{ doorWidth: '2.8米' }, { doorWidth: '3.2米' }], width: null, height: null })
    openStep('尺寸与数量')
    pickChip('加工类型', '未指定')
    fireEvent.change(inputOf('窗宽 (米)'), { target: { value: '3.0' } })
    fireEvent.change(inputOf('窗高 (米)'), { target: { value: '3.0' } })
    // 自动解 = 定宽买高（3.0 + 0.3 = 3.3 > 3.2）
    await waitFor(() => expect(checkedChips('加工类型')).toEqual(['定宽买高']))

    // 客服改成「定高买宽」（高度超限 ⇒ 按所选口径走 ⇒ 需接高告警）
    pickChip('加工类型', '定高买宽')
    const warn = await screen.findByTestId('door-width-needs-splice')
    expect(warn.textContent).toContain('需接高')
    // 手选之后**不再**标「自动」（这一档是客服自己点的）
    await waitFor(() => expect(screen.queryByTestId('cutting-mode-auto')).toBeNull())

    // 规则解再变（改高）也**不得**把手选值改回自动解
    fireEvent.change(inputOf('窗高 (米)'), { target: { value: '3.05' } })
    await waitFor(() => expect(checkedChips('加工类型')).toEqual(['定高买宽']))
    expect(screen.getByTestId('door-width-needs-splice')).toBeInTheDocument()
  })

  it('判据 8d：落库的 `cuttingMode` = 自动推导值（不只是「看起来选中」）', async () => {
    await setupLineWithSkus({ skus: [{ doorWidth: '2.8米' }, { doorWidth: '3.2米' }], width: null, height: null })
    openStep('尺寸与数量')
    pickChip('加工类型', '未指定')
    fireEvent.change(inputOf('窗宽 (米)'), { target: { value: '3.0' } })
    fireEvent.change(inputOf('窗高 (米)'), { target: { value: '3.0' } })
    await waitFor(() => expect(checkedChips('加工类型')).toEqual(['定宽买高']))
    // issue #4976 包 2b：判定已移到**服务端** ⇒ 本用例在 setup 之后才填尺寸 ⇒ 提交前必须等判定落地
    //（否则会被提交闸门拦住 ⇒ `submitAndGetItemInfo` 拿不到 payload ⇒ 用例超时）
    await settleAutoFeatures()
    const info = (await submitAndGetItemInfo()) as unknown as {
      processingInfo: Record<string, unknown>
    }
    expect(info.processingInfo.cuttingMode).toBe('定宽买高')
  })
})

beforeEach(() => {
  vi.clearAllMocks()
  mockGetProcessingItems.mockResolvedValue({
    data: {
      data: {
        items: [
          { id: 'pi1', name: '打孔加工', unit: '米' },
        ],
      },
    },
  })
  mockGetCustomers.mockResolvedValue({ data: { data: { items: [], total: 0 } } })
})

describe('#4658：系统识别块在②工艺规格（不在③加工项）+ 逐条依据 + 尺寸行徽标', () => {
  it('#4658 ②工艺规格里出现「系统识别」，且**逐条**显示判定依据（reason 文案，不是只有名字）', async () => {
    // 🔴 issue #4877：门幅**必须显式**（已无缺省门幅）—— 不传门幅 = 不判，断言无据可依
    await setupLine({ doorWidth: '2.8米' })
    // #4878（origin/main）：系统识别块位置 = ①尺寸与数量
    openStep('尺寸与数量')

    const block = within(stepSection('尺寸与数量')).getByTestId('auto-detected-features')
    // 🔴 #5130 改钉：判据 = 与**企业阈值**比 ⇒ 6.6 宽 > 6 ⇒ 出「超宽」；2.6 高 ≤ 4 ⇒ 不出「超高」
    //（#4661 的「按加工类型分流」已退役 —— 特征与加工类型无关，两者可同时为真）
    expect(within(block).getByText('超宽')).toBeInTheDocument()
    expect(within(block).queryByText('超高')).toBeNull()
    // 照实标注：推理非实证（设计 §5.2）—— **每条**特征都带来源标注
    const chips = block.querySelectorAll('span[title]')
    expect(chips.length).toBeGreaterThanOrEqual(1)
    for (const chip of Array.from(chips)) {
      expect(chip.textContent).toContain('（推算）')
      expect(chip.getAttribute('title')).toBeTruthy()
    }
    // 🔴 #4658 的核心：**正文里**逐条给依据（旧实现只在 `title` 属性里 ⇒ 商家看不见判定过程）
    // 🔴 #5130 改钉：依据文案 = 「净窗宽 … 米 > 超宽阈值 … 米」（旧式「窗宽 × 褶倍 = … 米 > 门幅 … 米」整条退场）
    expect(
      within(block).getByText(/净窗宽 6\.6 米 > 超宽阈值 6(?:\.0)? 米/)
    ).toBeInTheDocument()
    // 「超高」在 2.6 高下**不判**（未超阈值）⇒ 它没有 reason 行；它只能被**强制加**（见 #4657 组）
    // ⚠️ 用**完整依据文案**做否定断言（不能只写 `/窗宽/` —— 那是别的块/别的行的子串）
    // 🔴 #5030 / #5130 反向守卫：旧式余量与旧式门幅依据**整块不得再上屏**
    expect(within(block).queryByText(/左右余量/)).toBeNull()
    expect(within(block).queryByText(/> 门幅/)).toBeNull()
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

  // 🔴 #5130 改钉：判据 = 净窗宽 > 阈值 ⇒ 缺省档（6.6 宽）出「超宽」；
  // 改前（#4661）这条断言「超高」——那是「按门幅分流」的错口径在徽标面的镜像。
  it('#4658 ①尺寸行旁的就地徽标：有识别结果时出现，不超时消失', async () => {
    await setupLine({ doorWidth: '2.8米' })
    expect(await screen.findByTestId('size-auto-badge-超宽')).toBeInTheDocument()
    expect(screen.queryByTestId('size-auto-badge-超高')).toBeNull()

    openStep('尺寸与数量')
    fireEvent.change(inputOf('窗宽 (米)'), { target: { value: '1.5' } })
    fireEvent.change(inputOf('窗高 (米)'), { target: { value: '1.5' } })

    // 1.5 × 1.5 两个方向都**没超**企业阈值 ⇒ 徽标全部消失（不是「超时消失」）
    await waitFor(() => expect(screen.queryByTestId('size-auto-badge-超宽')).toBeNull())
    expect(screen.queryByTestId('size-auto-badge-超高')).toBeNull()
  })

  // 🔴 issue #4877 改判：**缺省门幅已删除** —— 未维护门幅不再「按 2.8 推算」，而是**几何层判不了** + 显式告知。
  // 🔴 **issue #5130 再改判**：**判定面**已与门幅**彻底脱钩**（净窗宽/净窗高 vs 企业阈值）
  // ⇒ 缺门幅时超高/超宽**照样判**；「未维护门幅」的告知只覆盖**几何层**（分幅 / 加工类型）。
  // 红证：若文案又写「超高/超宽都判不了」、或缺门幅时判定面短路成 `[]` ⇒ 本用例红。
  it('#4877/#5130 SKU 未维护门幅 ⇒ **几何层**判不了（显式告知 + 徽标），判定面**照判**', async () => {
    // issue #4899 更正：`setupLine()` **不点颜色** ⇒ 根本没有选中的 SKU —— 那是「未选规格」，
    // **不是**「门幅未维护」（旧断言把两者混成同一个徽标 = 误导）。门幅不可解析要走「已选中但解析不到」。
    await setupLine({ doorWidth: '加宽' })
    expect(screen.getByTestId('size-door-width-missing')).toBeInTheDocument()
    openStep('尺寸与数量')
    const missing = screen.getByTestId('door-width-missing')
    expect(missing).toBeInTheDocument()
    expect(screen.queryByTestId('door-width-fallback')).toBeNull()
    // 文案改判：只说**几何层**判不了（旧的「超高 / 超宽都判不了」在新判据下是假话）
    expect(missing.textContent).toContain('分幅与加工类型判不了')
    expect(missing.textContent).not.toContain('超高 / 超宽都判不了')
    // 🔴 判定面照判：6.6 宽 > 6 ⇒ 「超宽」（旧行为「缺门幅 ⇒ 不判」已随 #4877 判定面退役）
    expect(within(screen.getByTestId('auto-detected-features')).getByText('超宽')).toBeInTheDocument()
  })

  // 红证（issue #4899，改前实测）：改前 `doorWidthMissing = selectedDoorWidth === null` ⇒
  // **没选 SKU** 也会被标成「门幅未维护」并给「该 SKU 未维护门幅」的告知 ⇒ 本次必红。
  it('#4899 未选规格 ⇒ **不谎报**「门幅未维护」（那是「未选规格」，另有提交闸门）', async () => {
    await setupLine() // 不点颜色 ⇒ 没有选中的 SKU
    expect(screen.queryByTestId('size-door-width-missing')).toBeNull()
    openStep('尺寸与数量')
    expect(screen.queryByTestId('door-width-missing')).toBeNull()
    expect(screen.queryByTestId('auto-feature-notice-missing-door-width')).toBeNull()
  })

  it('#4877 SKU 真的给了门幅 ⇒ **不谎报**成「未维护」（反向护栏）', async () => {
    await setupLine({ doorWidth: '2.8米' })
    expect(screen.queryByTestId('size-door-width-missing')).toBeNull()
    openStep('尺寸与数量')
    expect(screen.queryByTestId('door-width-missing')).toBeNull()
  })
})

describe('D6：自动识别结果只读可见（判据 8）', () => {
  it('改宽高 ⇒ 识别结果跟着变（不是写死的展示文案）', async () => {
    // 🔴 issue #4877：门幅必须显式（无缺省门幅）—— 缺门幅时一条都不判，本用例将失去对照物
    await setupLine({ doorWidth: '2.8米' })
    openStep('尺寸与数量')
    const block = screen.getByTestId('auto-detected-features')
    // 🔴 #5130 改钉：缺省 6.6 宽 > 6 ⇒ 「超宽」；改前（#4661）这条断言的是「超高」
    expect(within(block).getByText('超宽')).toBeInTheDocument()

    openStep('尺寸与数量')
    fireEvent.change(inputOf('窗宽 (米)'), { target: { value: '1.5' } })
    fireEvent.change(inputOf('窗高 (米)'), { target: { value: '1.5' } })
    openStep('尺寸与数量')

    await waitFor(() => {
      expect(screen.queryByTestId('auto-feature-超宽')).toBeNull()
      expect(screen.queryByTestId('auto-feature-超高')).toBeNull()
    })
    // 缺省 cuttingMode = 定高买宽（= 正幅）⇒ #4592 起**不推导任何特征**。
    // 红证（修复前必红）：修复前这里恒有「正幅」，而「正幅」不在加工项目录里 ⇒
    // 默认订单的组合键永远匹配不到价 ⇒ 加工费恒 ¥0.00。
    expect(screen.queryByText('正幅')).toBeNull()
    // 块**仍在**（要能「强制加」+ 门幅未维护时要能看见）—— 但一条识别行都没有
    const blockAfter = screen.getByTestId('auto-detected-features')
    expect(within(blockAfter).queryByText('超宽')).toBeNull()
    expect(within(blockAfter).queryByText('超高')).toBeNull()
    expect(within(blockAfter).getByText(/系统未识别出特征/)).toBeInTheDocument()
  })

  // 🔴 **#5130 改判**：旧用例（「1.5 高 × 1.0 宽 对 1.4 窄幅门幅判超高」）的**前提已被裁定掉** ——
  // 判定面不再读门幅（#4877 判定面退役）；1.5 高 ≤ 默认阈值 4 ⇒ 不判超高。
  // ⇒ 改判为**反向守卫**（同强度）：同一几何换成任何门幅，判定结果**逐值相同**；
  // 且把窗高抬过阈值时**真的**判得出来（证明不是「判定面整体失效」的假绿）。
  it('#5130 门幅**不再**决定判定：同一几何换门幅判定不变；抬过阈值才判', async () => {
    await setupLine({ doorWidth: '1.4米', width: '1.0', height: '1.5' })
    openStep('尺寸与数量')

    const block = screen.getByTestId('auto-detected-features')
    // 旧判据会因 `1.5 + 0.3 = 1.8 > 1.4` 判「超高」；新判据不读门幅 ⇒ 不判
    expect(within(block).queryByText('超高')).toBeNull()
    expect(within(block).queryByText('超宽')).toBeNull()

    // 反向自证（不是空断言）：窗高抬到 4.5 > 4 ⇒ 「超高」真的判得出来
    fireEvent.change(inputOf('窗高 (米)'), { target: { value: '4.5' } })
    await waitFor(() =>
      expect(
        within(screen.getByTestId('auto-detected-features')).getByText('超高')
      ).toBeInTheDocument()
    )
  })

  it('自动识别结果**不是**可勾选项（没有它的 checkbox），也不计入「已选 N 项」', async () => {
    await setupLine()
    openStep('尺寸与数量')

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
            { id: 'pi-02', name: '韩折', craftHint: '韩褶', unit: '米' },
            { id: 'pi-06', name: '定型', unit: '米' },
            { id: 'pi-14', name: '超高', unit: '米' },
            { id: 'pi-15', name: '超宽', unit: '米' },
            { id: 'pi-16', name: '倒幅', unit: '米' },
          ],
        },
      },
    })
    await setupLine({ doorWidth: '2.8米' })

    // ③加工项：手选列表 = 目录 − 自动推导特征（红证：修复前这里会出现 5 个 checkbox）
    openStep('加工项')
    expect(screen.getAllByRole('checkbox').map((b) => b.getAttribute('aria-label'))).toEqual([
      '韩折',
      '定型',
    ])
    for (const auto of ['超高', '超宽', '倒幅']) {
      expect(screen.queryByRole('checkbox', { name: auto })).toBeNull()
    }
    // 推导结果照旧**只读可见**；🔴 #5130 改钉：缺省档（6.6 宽）出「超宽」（改前 #4661 断言「超高」）
    openStep('尺寸与数量')
    const block = screen.getByTestId('auto-detected-features')
    expect(within(block).getByText('超宽')).toBeInTheDocument()
    expect(within(block).queryByText('超高')).toBeNull()
    expect(block.querySelectorAll('input')).toHaveLength(0)
  })
})

describe('#4657：推算结果可**采纳 / 不采纳** + 强制加（生效值唯一 ⇒ 组合键）', () => {
  it('#4657 不采纳「超宽」⇒ 留痕「已忽略系统推算（依据：…）」且组合键里**不再含**它', async () => {
    await setupLine({ doorWidth: '2.8米' })
    openStep('尺寸与数量')

    // 红证（实现前）：无 `auto-feature-reject-*` 控件 ⇒ 本条必红
    // 🔴 #5130 改钉：缺省档（6.6 宽 / 2.6 高）推出的**唯一**特征是「超宽」（净窗宽 > 阈值）
    fireEvent.click(screen.getByTestId('auto-feature-reject-超宽'))

    // 留痕：行上看得见「已忽略系统推算」+ **原推算依据**（谁改的、原判据是什么）
    const rejected = await screen.findByTestId('auto-feature-rejected-超宽')
    expect(rejected.textContent).toContain('已忽略系统推算')
    expect(rejected.textContent).toContain('净窗宽 6.6 米')
    expect(rejected.textContent).toContain('超宽阈值')
    // ① 徽标 = **生效值** ⇒ 超宽消失
    expect(screen.queryByTestId('size-auto-badge-超宽')).toBeNull()
    // 落库的组合键 = 生效值（唯一口径：界面与 payload 不会各说各话）⇒ 一条都不剩
    expect(await submitAndGetProcessingNames()).toEqual([])
  })

  it('#4657 不采纳后「采纳」⇒ 生效值回来（裁决可逆，不是单向开关）', async () => {
    await setupLine({ doorWidth: '2.8米' })
    openStep('尺寸与数量')

    fireEvent.click(screen.getByTestId('auto-feature-reject-超宽'))
    await screen.findByTestId('auto-feature-rejected-超宽')
    fireEvent.click(screen.getByTestId('auto-feature-adopt-超宽'))

    await waitFor(() => expect(screen.queryByTestId('auto-feature-rejected-超宽')).toBeNull())
    expect(screen.getByTestId('size-auto-badge-超宽')).toBeInTheDocument()
    expect(await submitAndGetProcessingNames()).toEqual(['超宽'])
  })

  it('#4657 系统**没推**也能**强制加**（如净窗高未超阈值）⇒ 组合键含它 + 留痕「手动加」', async () => {
    await setupLine({ doorWidth: '2.8米' })
    openStep('尺寸与数量')

    // 🔴 #5130 改钉：缺省档（2.6 高 ≤ 4）**不推超高** ⇒ 「超高」正是「系统没推也能强制加」的真实场景
    //（改前 #4661 下它是被推算出来的，本用例测不到「强制加」这条路径）
    fireEvent.click(screen.getByTestId('auto-feature-add-超高'))

    const manual = await screen.findByTestId('auto-feature-manual-超高')
    expect(manual.textContent).toContain('手动加（系统未推算）')
    expect(screen.getByTestId('size-auto-badge-超高')).toBeInTheDocument()
    // 生效值 = 推算 ∪ 强制加（顺序 = 推算在前；组合键归一化另有唯一实现）
    expect(await submitAndGetProcessingNames()).toEqual(['超宽', '超高'])
  })

  // 🔴 **#5130 改判**：旧用例（「#4661 加工类型选定宽买高 ⇒ 只判超宽 + 倒幅、不判超高」）的
  // 分流前提已退役（特征与加工类型无关）；但「切定宽买高 ⇒ 多一个**倒幅**」这一半**仍然为真**
  // ⇒ 改判为：加工类型**只**决定 `倒幅`。
  it('#5130 加工类型只决定「倒幅」：切「定宽买高」⇒ 超宽 + 倒幅（依据文案 = 阈值式）', async () => {
    await setupLine({ doorWidth: '2.8米' })
    openStep('尺寸与数量')
    fireEvent.click(screen.getByRole('radio', { name: '定宽买高' }))

    const block = screen.getByTestId('auto-detected-features')
    await waitFor(() => expect(within(block).getByText('倒幅')).toBeInTheDocument())
    expect(within(block).getByText('超宽')).toBeInTheDocument()
    // 2.6 高 ≤ 4 ⇒ 不出「超高」（与加工类型无关，只是没超阈值）
    expect(within(block).queryByText('超高')).toBeNull()
    // 🔴 依据文案 = 与**企业阈值**比；旧式「窗宽 6.6 × 褶倍 2 = 13.2 米 > 门幅 2.8 米」整条退场
    expect(within(block).getByText(/净窗宽 6\.6 米 > 超宽阈值 6(?:\.0)? 米/)).toBeInTheDocument()
    expect(within(block).queryByText(/褶倍/)).toBeNull()
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
   *
   * 🔴 **issue #5130 再改判**：缺省档 6.6 × 2.6 ⇒ 唯一特征 = `超宽`（净窗宽 > 企业阈值）；
   * 「#4661 只判高方向」已退役（特征与加工类型无关）。`toEqual` 精确形态与「不得含正幅」护栏**不变**。
   */
  it('#4592 默认「定高买宽」订单落库的组合加项 = {超宽}，**不含「正幅」**', async () => {
    // 带门幅 ⇒ setupLine 会连颜色 + 规格一起选上（缺颜色会被页面校验拦在提交前）
    await setupLine({ doorWidth: '2.8米' })

    const names = await submitAndGetProcessingNames()
    expect(names).toEqual(['超宽'])
    expect(names).not.toContain('正幅')
  })
})

/**
 * issue #4662（用户 2026-09-20 裁定 A + C）：
 * ①「超宽」判据**含褶倍**（`窗宽 × 褶倍 > 门幅`，与算料引擎算分幅同源；#5030 起**不含左右余量**）；
 * ② 加工类型**几何矛盾** ⇒ 界面**显式提示**「系统实际会按哪种算」（与引擎的自动回落一致）。
 *
 * 🔴 **2026-09-22 改判（issue #5130）**：① 的**判据**已换成 `净窗宽 > oversize_width_threshold`
 * （企业阈值）⇒ 旧文「含褶倍 / 与门幅比」**整条退役**（#4662 裁定退役，D10）。
 * 本条改判为**反向守卫**：小窗（1.5 宽 × 褶倍 2 = 3 ≤ 门幅 2.8）在**旧**判据下会判超宽，
 * **新**判据（1.5 ≤ 6）**不判** ⇒ 并断言依据文案里**不再出现**「褶倍」。
 * ② 的「几何矛盾提示」**仍然为真**（几何层，与本裁定无关）⇒ 三条断言一字未放宽。
 */
describe('#4662 / #5130 「超宽」判据已换为企业阈值 + 加工类型几何矛盾显式提示（页面链路）', () => {
  it('#5130 小窗不再判「超宽」（旧「含褶倍」判据退役）⇒ 落库组合键只剩「倒幅」', async () => {
    await setupLine({ doorWidth: '2.8米', width: '1.5', height: '2.6' })
    openStep('尺寸与数量')
    fireEvent.click(screen.getByRole('radio', { name: '定宽买高' }))

    const block = screen.getByTestId('auto-detected-features')
    await waitFor(() => expect(within(block).getByText('倒幅')).toBeInTheDocument())
    // 🔴 红证：把 #4662 的旧判据（`1.5 × 2 = 3 > 门幅 2.8`）加回 ⇒ 「超宽」就会出现 ⇒ 本断言红
    expect(within(block).queryByText('超宽')).toBeNull()
    // 依据文案里**不再有**褶倍（判据已不含它）
    expect(within(block).queryByText(/褶倍/)).toBeNull()
    // 高 2.6 + 0.3 = 2.9 > 2.8 ⇒ 与商家选的档位**一致**（引擎也按定宽买高）⇒ 无矛盾提示
    expect(screen.queryByTestId('auto-feature-notice-cutting-mode-conflict')).toBeNull()
    expect(await submitAndGetProcessingNames()).toEqual(['倒幅'])
  })

  it('#4662 几何矛盾：缺省「定高买宽」+ 高超门幅 ⇒ 显式提示「系统实际会按定宽买高算」', async () => {
    await setupLine({ doorWidth: '2.8米' }) // 6.6 × 2.6 对 2.8 门幅：2.6 + 0.3 = 2.9 > 2.8
    openStep('尺寸与数量')

    const notice = screen.getByTestId('auto-feature-notice-cutting-mode-conflict')
    expect(notice.textContent).toContain('系统实际会按定宽买高算')
    // 依据说清（哪两个数比出来的）+ 门幅前提可见 —— 前端**不编**口径
    expect(notice.textContent).toContain('成品高 2.6 + 上下卷边 0.3 = 2.9 米')
    expect(notice.textContent).toContain('门幅 2.8 米')
    // 🔴 issue #4746：提示**不再**声称「算料引擎按此判几何」—— 引擎按 `internal.py::_FABRIC_WIDTH`
    // 硬编码 3.2 试算，那句是**无据断言**（商家按提示做的决定可能是错的）；改后只声明「按本 SKU
    // 门幅口径」并**显式登记**引擎试算门幅尚未接线（分叉 #4652）。红证：改前这两条必红。
    expect(notice.textContent).not.toContain('算料引擎按此判几何')
    expect(notice.textContent).toContain('引擎试算门幅尚未按本 SKU 门幅接线')
    expect(notice.textContent).toContain('#4746')
    // 推算仍**以商家选的为准**（裁定 C）：特征 = ['超宽']（6.6 > 6），不冒出「超高 / 倒幅」
    // 🔴 #5130 改钉：改前这里是 `['超高']`（门幅式判据）；现在缺省档推出的是「超宽」
    expect(screen.getByTestId('auto-feature-超宽')).toBeInTheDocument()
    expect(screen.queryByTestId('auto-feature-超高')).toBeNull()
    expect(screen.queryByTestId('auto-feature-倒幅')).toBeNull()
    // 提示**不进**加工费组合键（它不是特征；目录里没有的名字 = 加工费恒 ¥0.00 的 P0 教训）
    expect(await submitAndGetProcessingNames()).toEqual(['超宽'])
  })

  it('#4662 反向：切「定宽买高」+ 高不超门幅 ⇒ 提示「系统实际会按定高买宽算」', async () => {
    await setupLine({ doorWidth: '2.8米', width: '1.5', height: '1.5' })
    openStep('尺寸与数量')
    fireEvent.click(screen.getByRole('radio', { name: '定宽买高' }))

    const notice = await screen.findByTestId('auto-feature-notice-cutting-mode-conflict')
    expect(notice.textContent).toContain('系统实际会按定高买宽算')
  })

  it('#4662 几何一致 ⇒ 无矛盾提示（不制造噪音）', async () => {
    await setupLine({ doorWidth: '2.8米', width: '1.5', height: '1.5' }) // 缺省定高买宽 + 1.8 ≤ 2.8
    openStep('尺寸与数量')
    expect(screen.queryByTestId('auto-feature-notice-cutting-mode-conflict')).toBeNull()
  })
})

// ══════════════════ #4976 包 2b：判定移到**服务端** ══════════════════
//
// 用户 2026-09-21 裁定 B：「**判定移到服务端**」（前端只展示服务端结论）。
// 判据方向 = **迁移期等价性** + 「前端不得再本地判价」 + 「判定未就绪不许提交」。

describe('#4976 包 2b：判定移到服务端', () => {
  it('判据 1（静态）：下单页**不再本地判特征**（判据只在服务端）', () => {
    const src = readFileSync(
      resolve(__dirname, '../../../src/app/(dashboard)/orders/new/page.tsx'),
      'utf8'
    )
    // 注入：把 `detectAutoFeatures({…})` 调回页面（= 本地判价，会出现「前端一套、服务端一套」）⇒ 红
    // ⚠️ 钉**调用/导入形态**（注释里引用旧实现名做历史说明是允许的 —— 判据不得把解释性注释判成违规）
    expect(src).not.toContain('detectAutoFeatures({')
    expect(src).not.toMatch(/^\s*detectAutoFeatures,\s*$/m)
    // 判定必须来自服务端端点
    expect(src).toContain('autoFeaturesApi.preview')
  })

  it('判据 2：请求带**该 SKU 的门幅**、加工类型与**两个企业阈值**（判定入参就是它们）', async () => {
    await setupLine({ doorWidth: '2.8米' })
    const call = mockAutoFeatures.mock.calls.at(-1)?.[0] as AutoFeaturesRequestForTest
    // 注入：不发 fabric_width（几何矛盾提示失去依据）⇒ 红
    expect(call.fabric_width).toBe(2.8)
    expect(call.cutting_mode).toBe('定高买宽')
    expect(call.width).toBe(6.6)
    expect(call.height).toBe(2.6)
    // 🔴 issue #5130：两个**企业阈值**必须随请求下发 —— 不下发 ⇒ 引擎回落默认值
    // ⇒ 商家在「算料配置」改的阈值**静默不生效**（可配却不生效 = 本仓明令禁止的形态）⇒ 红
    expect(call.config?.oversize_width_threshold).toBe(6)
    expect(call.config?.oversize_height_threshold).toBe(4)
  })

  it('判据 3：拿不到门幅 ⇒ **不发 `fabric_width`**（不回落默认门幅，issue #4877）', async () => {
    await setupLine({})
    const call = mockAutoFeatures.mock.calls.at(-1)?.[0] as AutoFeaturesRequestForTest
    // 注入：补一个默认门幅（2.8 / 3.2）⇒ 红 —— 那是「拿一个不是这张单的值判价」
    expect(call).not.toHaveProperty('fabric_width')
  })

  it('判据 4：判定**未就绪** ⇒ 提交被闸门拦住（不发创建请求）', async () => {
    // 判定永不返回 ⇒ 行状态停在「没判」；组合键会少一项 ⇒ 必须拦住提交
    mockAutoFeatures.mockImplementation((() => new Promise(() => {})) as never)
    mockCreateOrder.mockClear()
    try {
      await setupLine({ doorWidth: '2.8米' })
      fireEvent.change(screen.getByPlaceholderText('请输入收货人姓名'), { target: { value: '张三' } })
      fireEvent.change(screen.getByPlaceholderText('请输入 11 位手机号'), {
        target: { value: '13800138000' },
      })
      fireEvent.change(screen.getByPlaceholderText('请输入详细收货地址'), {
        target: { value: '杭州市' },
      })
      await waitFor(() => expect(screen.queryByText(/加工费计价中/)).toBeNull())
      fireEvent.click(screen.getByText('提交订单'))
      // 注入：去掉闸门 ⇒ 会发出创建请求（组合键少一项 ⇒ 取价错）⇒ 红
      await waitFor(() => expect(mockCreateOrder).not.toHaveBeenCalled())
    } finally {
      // 还原服务端替身（`clearAllMocks` **不还原实现** ⇒ 不还原会污染后续用例）
      mockAutoFeatures.mockImplementation((params: AutoFeaturesRequestForTest) =>
        autoFeaturesServerDouble(params)
      )
    }
  })
})
