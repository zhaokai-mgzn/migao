// case_ids: UI-054, PR-098
/**
 * 「参数总览」面板（企业参数中心 · 增量 1）**渲染面**守卫（issue #5131）。
 *
 * 分工：静态清单与文案守卫在 `frontend/admin-web/tests/unit/lib/tenant-params.test.ts`；
 * 本文件只判**渲染**（域导航、三件套真的上屏、**默认值可见**、高级渐进披露、行式配置只给入口、
 * 读面失败给**可行动话术**）。
 *
 * 🔴 **服务端替身**：本组件**不判任何口径**，值一律来自读面 ⇒ 测试必须替身 `@/lib/api`
 * （否则会打真实网络）。替身给的是**服务端形状**（`{source, config}` / `AiConfig`），
 * 不是前端自造的默认值。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { TenantParamsPanel } from '@/components/settings/TenantParamsPanel'
import { AI_PARAM_COPY, PARAM_DOMAINS } from '@/lib/tenant-params'
import { CALC_SCALAR_KEYS } from '@/lib/craft-calc-glossary'

const getCraftCalcConfig = vi.fn()
const getAiConfig = vi.fn()
// issue #5146：余料域的内联参数（小件用料尺寸表）也要读面 ⇒ 替身必须给得出形状
const getRemnantSpecs = vi.fn()

vi.mock('@/lib/api', () => ({
  productionApi: { getCraftCalcConfig: () => getCraftCalcConfig() },
  settingsApi: { getAiConfig: () => getAiConfig() },
  // §22 P4 阈值试算（issue #5131）：算料域会挂载试算块 ⇒ 该读面必须可用
  autoFeaturesApi: {
    preview: () => Promise.resolve({ data: { success: true, data: { auto_features: [] } } }),
  },
  // §22 P1（issue #5146）：余料域的内联面板读面（默认「未配置」—— 也就是本参数的默认值）
  remnantApi: {
    smallItemSpecs: () => getRemnantSpecs(),
    putSmallItemSpecs: () => Promise.resolve({ data: { success: true, data: null } }),
  },
}))

/**
 * 服务端读面形状：`{success, data: {source, config}}` —— 配置值由**引擎键集**生成，不写死。
 *
 * @param defaults 第三参（issue #5131 增量 2）：`{value}` ⇒ 附 `defaults` + `defaults_source='engine'`；
 *   `'unavailable'` ⇒ 只附 `defaults_source='unavailable'`（**不带** `defaults` 键）；
 *   缺省 ⇒ 两个键都不附（= 既有调用方口径）。
 */
function calcResponse(
  source: string,
  value = 0.4,
  defaults?: { value: number } | 'unavailable'
) {
  const config = Object.fromEntries(CALC_SCALAR_KEYS.map((k) => [k, value]))
  const data: Record<string, unknown> = { source, config }
  if (defaults === 'unavailable') {
    data.defaults_source = 'unavailable'
  } else if (defaults) {
    data.defaults = Object.fromEntries(CALC_SCALAR_KEYS.map((k) => [k, defaults.value]))
    data.defaults_source = 'engine'
  }
  return { data: { success: true, data } }
}

const aiResponse = {
  data: { success: true, data: { botName: '小布', greetingTemplate: '您好' } },
}

beforeEach(() => {
  getCraftCalcConfig.mockReset()
  getAiConfig.mockReset()
  getRemnantSpecs.mockReset()
  getCraftCalcConfig.mockResolvedValue(calcResponse('default'))
  getAiConfig.mockResolvedValue(aiResponse)
  getRemnantSpecs.mockResolvedValue({
    data: {
      success: true,
      data: {
        configured: false,
        items: [],
        notice: '未配置小件用料尺寸 ⇒ 不产生匹配建议（本参数默认值为空 = 未启用）',
      },
    },
  })
})

describe('判据 1：一处入口 —— 按域分组渲染（§22 P1）', () => {
  it('四个域导航都在，且默认停在第一个域（算料）', async () => {
    render(<TenantParamsPanel />)
    for (const d of PARAM_DOMAINS) {
      expect(screen.getByTestId(`param-domain-${d.key}`)).toBeInTheDocument()
    }
    expect(screen.getByTestId('param-domain-calc')).toHaveAttribute('aria-selected', 'true')
    await waitFor(() => expect(screen.getByTestId('param-hem_margin')).toBeInTheDocument())
  })
})

describe('判据 2：每参数三件套上屏（§22 P2）', () => {
  it('常用参数的 label / hint / impact 都渲染，且**值来自读面**', async () => {
    getCraftCalcConfig.mockResolvedValue(calcResponse('stored', 0.4))
    render(<TenantParamsPanel />)
    await waitFor(() => expect(screen.getByTestId('param-hem_margin')).toBeInTheDocument())
    const row = screen.getByTestId('param-hem_margin')
    expect(row).toHaveTextContent('改它会怎样：')
    // ⚠️ 值断言必须**等**读面回来：`param-hem_margin` 在 loading 期就已渲染（值是占位「…」）
    // ⇒ 上面那条 waitFor 会立刻返回，紧接着断言值就是**竞态**（全量跑时实测偶发红，issue #5146 复现）。
    // 这不是放宽断言：断言的**内容一字未改**，只是等到它成立。
    await waitFor(() =>
      expect(screen.getByTestId('param-value-hem_margin')).toHaveTextContent('0.4')
    )
  })

  it('切到「加工费」域 ⇒ 行式配置**只给入口**（含「钱在哪」），不做列表编辑', async () => {
    render(<TenantParamsPanel />)
    fireEvent.click(screen.getByTestId('param-domain-fee'))
    const row = await screen.findByTestId('param-row-/production/processing-fees')
    expect(row).toHaveTextContent('钱在哪：')
    expect(row).toHaveAttribute('href', '/production/processing-fees')
    // 本页不得出现列表编辑控件（行式配置与标量表单不是一类）
    expect(screen.queryByTestId('param-hem_margin')).not.toBeInTheDocument()
  })
})

describe('判据 3：默认值可见（§22 P3，租户级）', () => {
  it("source='default' ⇒ 每个常用键都标「未配置（正在用引擎默认值）」", async () => {
    render(<TenantParamsPanel />)
    await waitFor(() => expect(screen.getByTestId('param-calc-using-default')).toBeInTheDocument())
    for (const p of PARAM_DOMAINS[0].common ?? []) {
      expect(screen.getByTestId(`param-unset-${p.key}`)).toBeInTheDocument()
    }
  })

  it("source='stored' ⇒ **不**标「未配置」（谎报已配置 = 让商家以为没生效）", async () => {
    getCraftCalcConfig.mockResolvedValue(calcResponse('stored'))
    render(<TenantParamsPanel />)
    await waitFor(() => expect(screen.getByTestId('param-hem_margin')).toBeInTheDocument())
    expect(screen.queryByTestId('param-calc-using-default')).not.toBeInTheDocument()
    expect(screen.queryByTestId('param-unset-hem_margin')).not.toBeInTheDocument()
  })
})

describe('判据 4：高级参数默认收起（渐进披露）', () => {
  it('初始不渲染高级参数；点开后渲染', async () => {
    render(<TenantParamsPanel />)
    const toggle = await screen.findByTestId('param-advanced-toggle-calc')
    expect(screen.queryByTestId('param-advanced-calc')).not.toBeInTheDocument()
    expect(screen.queryByTestId('param-min_fullness')).not.toBeInTheDocument()
    fireEvent.click(toggle)
    expect(screen.getByTestId('param-advanced-calc')).toBeInTheDocument()
    expect(screen.getByTestId('param-min_fullness')).toBeInTheDocument()
  })
})

describe('判据 5：读面失败给**可行动话术**（不是静默空白）', () => {
  it('算料读面 rejected ⇒ 渲染含「请联系管理员」的终态提示（权限拒绝不是参数问题）', async () => {
    getCraftCalcConfig.mockRejectedValue(new Error('403'))
    render(<TenantParamsPanel />)
    const err = await screen.findByTestId('param-calc-error')
    expect(err).toHaveTextContent('请联系管理员')
  })

  it('AI 客服读面失败**不影响**算料区（两读面相互独立）', async () => {
    getAiConfig.mockRejectedValue(new Error('500'))
    render(<TenantParamsPanel />)
    await waitFor(() => expect(screen.getByTestId('param-hem_margin')).toBeInTheDocument())
    expect(screen.queryByTestId('param-calc-error')).not.toBeInTheDocument()
  })
})

describe('判据 6：AI 客服域的清单与文案一致', () => {
  it('切到 AI 客服域 ⇒ 渲染 AI_PARAM_COPY 的全部键', async () => {
    render(<TenantParamsPanel />)
    fireEvent.click(screen.getByTestId('param-domain-ai'))
    for (const key of Object.keys(AI_PARAM_COPY)) {
      expect(await screen.findByTestId(`param-${key}`)).toBeInTheDocument()
    }
    expect(screen.getByTestId('param-value-botName')).toHaveTextContent('小布')
  })
})

describe('判据 7：§22 P3 逐键「我改过没有」（issue #5131 增量 2）', () => {
  it('引擎默认值可用 ⇒ 被改过的键标「已改（默认 X）」、未改的标「默认」', async () => {
    const res = calcResponse('stored', 0.4, { value: 0.25 })
    const cfg = (res.data.data as Record<string, unknown>).config as Record<string, unknown>
    cfg.hem_margin = 0.25 // 与默认值相同 ⇒ 该键应标「默认」
    getCraftCalcConfig.mockResolvedValue(res)

    render(<TenantParamsPanel />)

    expect(await screen.findByTestId('param-changed-per_fold_single')).toHaveTextContent(
      '已改（默认 0.25）'
    )
    expect(screen.getByTestId('param-is-default-hem_margin')).toHaveTextContent('默认')
  })

  it('引擎默认值**取不到** ⇒ 显式说要「判不了」，且**一个徽标都不标**（拿不到 ≠ 就是默认值）', async () => {
    getCraftCalcConfig.mockResolvedValue(calcResponse('stored', 0.4, 'unavailable'))

    render(<TenantParamsPanel />)

    expect(await screen.findByTestId('param-defaults-unavailable')).toBeInTheDocument()
    expect(screen.queryByTestId('param-changed-per_fold_single')).not.toBeInTheDocument()
    expect(screen.queryByTestId('param-is-default-per_fold_single')).not.toBeInTheDocument()
  })

  it('读面**没带** defaults（既有调用方口径）⇒ 一个徽标都不标、也不显示「取不到」', async () => {
    getCraftCalcConfig.mockResolvedValue(calcResponse('stored', 0.4))

    render(<TenantParamsPanel />)

    await waitFor(() => expect(screen.getByTestId('param-per_fold_single')).toBeInTheDocument())
    expect(screen.queryByTestId('param-changed-per_fold_single')).not.toBeInTheDocument()
    expect(screen.queryByTestId('param-is-default-per_fold_single')).not.toBeInTheDocument()
    expect(screen.queryByTestId('param-defaults-unavailable')).not.toBeInTheDocument()
  })
})

/**
 * 判据 8（issue #5146 / §22 P1+P3）：**余料域的参数就配在本页里**（不另开第二个配置入口）。
 *
 * 红证形态：把 `TenantParamsPanel` 里那段 `domain.inline?.panel === 'remnant-specs'` 的渲染分支
 * 删掉 ⇒ 本用例必红（参数**静默不显示**是配置页最坏的形态，且不会有别的检查发现它）。
 */
describe('判据 8：内联参数（余料回收域）在本页内渲染（issue #5146）', () => {
  it('切到「余料回收」域 ⇒ 小件用料尺寸表面板出现，且**默认值可见**（未配置徽标 + 服务端说明）', async () => {
    render(<TenantParamsPanel />)
    fireEvent.click(screen.getByTestId('param-domain-remnant'))
    await waitFor(() => expect(screen.getByTestId('param-remnant-specs')).toBeInTheDocument())
    expect(screen.getByTestId('remnant-specs-unset')).toBeInTheDocument()
    expect(screen.getByTestId('remnant-specs-notice').textContent).toContain('不产生匹配建议')
    // 同一个域里的行式入口（余料台账）也还在
    expect(screen.getByTestId('param-row-/production/remnants')).toBeInTheDocument()
  })

  it('域摘要与余料术语的 markdown 强调**渲染成元素**、裸标记不上屏（issue #5194 改判）', async () => {
    render(<TenantParamsPanel />)
    await waitFor(() => expect(screen.getByTestId('param-hem_margin')).toBeInTheDocument())
    // 算料域摘要（`本域**每一项都直接改米数 = 改钱**`）+ 参数三件套里的 `` `HEM_MARGIN` ``
    const calcText = screen.getByTestId('tenant-params-panel').textContent ?? ''
    expect(calcText).not.toContain('**')
    expect(calcText).not.toContain('`')
    // 正控：强调必须以元素形态呈现（把标记删掉也能让「不含 **」变绿 ⇒ 必须另有这条）
    expect(
      Array.from(document.querySelectorAll('strong')).map((el) => el.textContent)
    ).toContain('每一项都直接改米数 = 改钱')
    expect(
      Array.from(document.querySelectorAll('code')).map((el) => el.textContent)
    ).toContain('HEM_MARGIN')

    // 余料回收域：术语表（`但还**能再用**的布`）
    fireEvent.click(screen.getByTestId('param-domain-remnant'))
    await waitFor(() => expect(screen.getByTestId('param-remnant-specs')).toBeInTheDocument())
    const remnant = screen.getByTestId('param-remnant-specs')
    expect(remnant.textContent ?? '').not.toContain('**')
    expect(
      Array.from(remnant.querySelectorAll('strong')).map((el) => el.textContent)
    ).toContain('能再用')
  })

  it('红证：内联面板**不出现**在别的域里（防止把面板挂到算料域 = 入口分裂）', async () => {
    render(<TenantParamsPanel />)
    await waitFor(() => expect(screen.getByTestId('param-hem_margin')).toBeInTheDocument())
    expect(screen.queryByTestId('param-remnant-specs')).not.toBeInTheDocument()
    fireEvent.click(screen.getByTestId('param-domain-remnant'))
    await waitFor(() => expect(screen.getByTestId('param-remnant-specs')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('param-domain-calc'))
    await waitFor(() =>
      expect(screen.queryByTestId('param-remnant-specs')).not.toBeInTheDocument()
    )
  })
})
