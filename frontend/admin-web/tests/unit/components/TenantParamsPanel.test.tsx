// case_ids: UI-054, PR-098
/**
 * 「参数总览」面板（企业参数中心）**渲染面**守卫（issue #5131 / #6573）。
 *
 * 分工：静态清单与文案守卫在 `frontend/admin-web/tests/unit/lib/tenant-params.test.ts`；
 * 配置主线的**纯判据**在 `frontend/admin-web/tests/unit/lib/config-readiness.test.ts`；
 * **页面**的第一屏取数与配置主线在 `frontend/admin-web/tests/unit/pages/settings-params.test.tsx`。
 * 本文件只判**渲染**（域导航、三件套真的上屏、**默认值可见**、高级渐进披露、行式配置只给入口、
 * 读面失败给**可行动话术**、**域级权限**、readiness 槽位位置）。
 *
 * 🔴 **issue #6573 起本组件是受控组件**：算料读数由**页面**取、以 props 传进来
 * （`calc` / `calcError` / `loading`），本组件**不再自己调** `productionApi.getCraftCalcConfig`
 * —— 仓内口径是「页面源码里由 `useEffect` 驱动的可执行面 = 该页第一屏读端点」
 * （`tests/unit_ci_workflows/test_agent_permission_parity.py` 的 `MENU_READ_ENDPOINT_ANCHORS` 那一跳）。
 * ⇒ 本文件按 props 直接给**服务端形状**（`{source, config, defaults?, defaults_source?}`），
 * 不再走「mock 读面 + 等异步落地」的写法（那会让断言依赖竞态，而不是依赖契约）。
 *
 * AI 客服域仍是**懒加载**（切到该域 + 持 `system:manage` 才发一次），故那一组用例仍替身 `@/lib/api`。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import {
  TenantParamsPanel,
  type TenantParamsPanelProps,
} from '@/components/settings/TenantParamsPanel'
import { AI_PARAM_COPY, PARAM_DOMAINS } from '@/lib/tenant-params'
import { CALC_SCALAR_KEYS } from '@/lib/craft-calc-glossary'
import type { CraftCalcConfig, CraftCalcConfigResponse } from '@/types'

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
 * 登录态（按用例改写 `permissions`）—— 必须**按 zustand 选择器**返回：
 * `usePermission()` 走 `useAuthStore(s => s.user)`，无视入参的整份 state mock 会让 `user` 恒 undefined
 * ⇒ `has()` 恒 false ⇒ 域可见性判据（issue #6573）无从成立。
 */
const authMock = vi.hoisted(() => ({
  state: {
    user: {
      id: '1',
      username: 'tester',
      name: '测试账号',
      permissions: ['production:view', 'system:manage', 'processing:manage'] as string[],
      roles: [] as string[],
    },
  },
}))
vi.mock('@/store/auth', () => ({
  useAuthStore: (selector?: (s: unknown) => unknown) =>
    typeof selector === 'function' ? selector(authMock.state) : authMock.state,
}))

/** 三个域级读码（issue #6573）：算料 / AI 客服 / 余料回收 各管各的域 */
const CALC_CODE = 'production:view'
const AI_CODE = 'system:manage'
const REMNANT_CODE = 'processing:manage'

function setPerms(codes: readonly string[]) {
  authMock.state.user = { ...authMock.state.user, permissions: [...codes], roles: [] }
}

/**
 * 服务端读面形状（**页面取到后传给面板的那一份**，issue #6573）：`{source, config, ...}`。
 * 配置值由**引擎键集**生成，不写死。
 *
 * @param defaults 第三参（issue #5131 增量 2）：`{value}` ⇒ 附 `defaults` + `defaults_source='engine'`；
 *   `'unavailable'` ⇒ 只附 `defaults_source='unavailable'`（**不带** `defaults` 键）；
 *   缺省 ⇒ 两个键都不附（= 既有调用方口径）。
 */
function calcData(
  source: string,
  value = 0.4,
  defaults?: { value: number } | 'unavailable'
): CraftCalcConfigResponse {
  // 引擎键集 → 配置值（测试只用到这几个键 ⇒ 显式收窄成服务端形状，不在断言里放 `unknown`）
  const engineBag = (v: number) =>
    Object.fromEntries(CALC_SCALAR_KEYS.map((k) => [k, v])) as unknown as CraftCalcConfig
  const data: CraftCalcConfigResponse = { source, config: engineBag(value) }
  if (defaults === 'unavailable') {
    data.defaults_source = 'unavailable'
  } else if (defaults) {
    data.defaults = engineBag(defaults.value)
    data.defaults_source = 'engine'
  }
  return data
}

const aiResponse = {
  data: { success: true, data: { botName: '元元', greetingTemplate: '您好' } },
}

/** 页面在算料读面失败时下发的**可行动话术**（`/settings/params` 的 `setCalcError`，逐字） */
const PAGE_CALC_ERROR =
  '算料口径读取失败（可能是当前岗位没有「工艺配置」权限）—— 请联系管理员开权限后重试'

/** 受控渲染：默认 = 服务端说「没保存过算料口径」（`source='default'`）且读面已落地 */
function renderPanel(overrides: Partial<TenantParamsPanelProps> = {}) {
  return render(
    <TenantParamsPanel
      calc={calcData('default')}
      calcError=""
      loading={false}
      {...overrides}
    />
  )
}

beforeEach(() => {
  getCraftCalcConfig.mockReset()
  getAiConfig.mockReset()
  getRemnantSpecs.mockReset()
  setPerms([CALC_CODE, AI_CODE, REMNANT_CODE])
  getCraftCalcConfig.mockResolvedValue({ data: { success: true, data: calcData('default') } })
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
  it('五个域导航都在，且默认停在第一个域（算料）', () => {
    renderPanel()
    for (const d of PARAM_DOMAINS) {
      expect(screen.getByTestId(`param-domain-${d.key}`)).toBeInTheDocument()
    }
    expect(screen.getByTestId('param-domain-calc')).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByTestId('param-hem_margin')).toBeInTheDocument()
  })
})

describe('判据 2：每参数三件套上屏（§22 P2）', () => {
  it('常用参数的 label / hint / impact 都渲染，且**值来自 props（服务端读面）**', () => {
    renderPanel({ calc: calcData('stored', 0.4) })
    const row = screen.getByTestId('param-hem_margin')
    expect(row).toHaveTextContent('改它会怎样：')
    // #6573 起值由 props 直接注入 ⇒ **同步**断言即可（旧写法要 `waitFor` 等读面落地，那是竞态来源：
    // `param-hem_margin` 在 loading 期就已渲染、值是占位「…」，见本文件判据 10）
    expect(screen.getByTestId('param-value-hem_margin')).toHaveTextContent('0.4')
  })

  it('切到「加工费」域 ⇒ 行式配置**只给入口**（含「钱在哪」），不做列表编辑', () => {
    renderPanel()
    fireEvent.click(screen.getByTestId('param-domain-fee'))
    const row = screen.getByTestId('param-row-/production/processing-fees')
    expect(row).toHaveTextContent('钱在哪：')
    expect(row).toHaveAttribute('href', '/production/processing-fees')
    // 本页不得出现列表编辑控件（行式配置与标量表单不是一类）
    expect(screen.queryByTestId('param-hem_margin')).not.toBeInTheDocument()
  })
})

describe('判据 3：默认值可见（§22 P3，租户级）', () => {
  it("source='default' ⇒ 每个常用键都标「未配置（正在用引擎默认值）」", () => {
    renderPanel({ calc: calcData('default') })
    expect(screen.getByTestId('param-calc-using-default')).toBeInTheDocument()
    for (const p of PARAM_DOMAINS[0].common ?? []) {
      expect(screen.getByTestId(`param-unset-${p.key}`)).toBeInTheDocument()
    }
  })

  it("source='stored' ⇒ **不**标「未配置」（谎报已配置 = 让商家以为没生效）", () => {
    renderPanel({ calc: calcData('stored') })
    // 读数由 props 给定 ⇒ 两态**同步可辨**（旧写法必须等「值位由占位变配置值」才敢下否定断言，
    // 因为 `isUsingEngineDefault(undefined)` 也判 true ⇒ 读面未落地时徽标已在文档里；本写法没有这个窗口）
    expect(screen.getByTestId('param-value-hem_margin')).toHaveTextContent('0.4')
    expect(screen.queryByTestId('param-calc-using-default')).not.toBeInTheDocument()
    expect(screen.queryByTestId('param-unset-hem_margin')).not.toBeInTheDocument()
  })
})

describe('判据 4：高级参数默认收起（渐进披露）', () => {
  it('初始不渲染高级参数；点开后渲染', () => {
    renderPanel()
    const toggle = screen.getByTestId('param-advanced-toggle-calc')
    expect(screen.queryByTestId('param-advanced-calc')).not.toBeInTheDocument()
    expect(screen.queryByTestId('param-min_fullness')).not.toBeInTheDocument()
    fireEvent.click(toggle)
    expect(screen.getByTestId('param-advanced-calc')).toBeInTheDocument()
    expect(screen.getByTestId('param-min_fullness')).toBeInTheDocument()
  })
})

describe('判据 5：读面失败给**可行动话术**（不是静默空白）', () => {
  it('算料读面失败 ⇒ 渲染「请联系管理员」话术，且值位不谎报成配置值（是「—」）', () => {
    renderPanel({ calc: null, calcError: PAGE_CALC_ERROR })
    const err = screen.getByTestId('param-calc-error')
    expect(err).toHaveTextContent('请联系管理员')
    expect(err).toHaveTextContent(PAGE_CALC_ERROR)
    // 读不到 ⇒ 值位是「—」（不是 0.4 这类配置值，也不是空字符串）
    expect(screen.getByTestId('param-value-hem_margin')).toHaveTextContent('—')
  })

  it('AI 客服读面失败**不影响**算料区（两读面相互独立）', async () => {
    getAiConfig.mockRejectedValue(new Error('500'))
    renderPanel({ calc: calcData('stored') })
    fireEvent.click(screen.getByTestId('param-domain-ai'))
    await waitFor(() => expect(screen.getByTestId('param-botName')).toBeInTheDocument())
    expect(screen.queryByTestId('param-calc-error')).not.toBeInTheDocument()
    // 失败 ⇒ 该域**不谎报值**（值一律来自读面）
    expect(screen.getByTestId('param-value-botName')).toHaveTextContent('—')
  })
})

describe('判据 6：AI 客服域的清单与文案一致', () => {
  it('切到 AI 客服域 ⇒ 渲染 AI_PARAM_COPY 的全部键，且值来自读面', async () => {
    renderPanel()
    fireEvent.click(screen.getByTestId('param-domain-ai'))
    for (const key of Object.keys(AI_PARAM_COPY)) {
      expect(screen.getByTestId(`param-${key}`)).toBeInTheDocument()
    }
    // 行在 loading 期就已渲染，真正来自读面的是**值位** ⇒ 等被断言的这件事本身成立
    await waitFor(() =>
      expect(screen.getByTestId('param-value-botName')).toHaveTextContent('元元')
    )
  })
})

describe('判据 7：§22 P3 逐键「我改过没有」（issue #5131 增量 2）', () => {
  it('引擎默认值可用 ⇒ 被改过的键标「已改（默认 X）」、未改的标「默认」', () => {
    const calc = calcData('stored', 0.4, { value: 0.25 })
    ;(calc.config as unknown as Record<string, unknown>).hem_margin = 0.25 // 与默认值相同 ⇒ 该键应标「默认」

    renderPanel({ calc })

    expect(screen.getByTestId('param-changed-per_fold_single')).toHaveTextContent(
      '已改（默认 0.25）'
    )
    expect(screen.getByTestId('param-is-default-hem_margin')).toHaveTextContent('默认')
  })

  it('引擎默认值**取不到** ⇒ 显式说要「判不了」，且**一个徽标都不标**（拿不到 ≠ 就是默认值）', () => {
    renderPanel({ calc: calcData('stored', 0.4, 'unavailable') })

    expect(screen.getByTestId('param-defaults-unavailable')).toBeInTheDocument()
    expect(screen.queryByTestId('param-changed-per_fold_single')).not.toBeInTheDocument()
    expect(screen.queryByTestId('param-is-default-per_fold_single')).not.toBeInTheDocument()
  })

  it('读面**没带** defaults（既有调用方口径）⇒ 一个徽标都不标、也不显示「取不到」', () => {
    renderPanel({ calc: calcData('stored', 0.4) })

    expect(screen.getByTestId('param-per_fold_single')).toBeInTheDocument()
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
    renderPanel()
    fireEvent.click(screen.getByTestId('param-domain-remnant'))
    // ⚠️ 容器在 loading 期就已渲染（`param-remnant-specs` 不受 `!loading` 约束），而
    // `remnant-specs-unset` 只在 `!loading && !configured` 时才上屏（`RemnantItemSizesPanel.tsx`）
    // ⇒ 那是**面板自己的异步读面**，等**目标本身**出现（不是放宽断言）
    expect(screen.getByTestId('param-remnant-specs')).toBeInTheDocument()
    const unset = await screen.findByTestId('remnant-specs-unset')
    expect(unset).toBeInTheDocument()
    expect(screen.getByTestId('remnant-specs-notice').textContent).toContain('不产生匹配建议')
    // 同一个域里的行式入口（余料台账）也还在
    expect(screen.getByTestId('param-row-/production/remnants')).toBeInTheDocument()
  })

  it('域摘要与余料术语的 markdown 强调**渲染成元素**、裸标记不上屏（issue #5194 改判）', async () => {
    renderPanel()
    // 算料域摘要（`本域**每一项都直接改米数 = 改钱**`）+ 参数三件套里的 `` `上下卷边` ``
    // 🔴 issue #6488：代码片里只放**商家看得懂的名字**（旧文的 `` `HEM_MARGIN` `` 键名已去掉）——
    //    正控随之改钉中文名，仍要求代码片真的以元素呈现（不是把标记删掉）。
    const calcText = screen.getByTestId('tenant-params-panel').textContent ?? ''
    expect(calcText).not.toContain('**')
    expect(calcText).not.toContain('`')
    // 正控：强调必须以元素形态呈现（把标记删掉也能让「不含 **」变绿 ⇒ 必须另有这条）
    expect(
      Array.from(document.querySelectorAll('strong')).map((el) => el.textContent)
    ).toContain('每一项都直接改米数 = 改钱')
    expect(
      Array.from(document.querySelectorAll('code')).map((el) => el.textContent)
    ).toContain('上下卷边')

    // 余料回收域：术语表（`但还**能再用**的布`）
    fireEvent.click(screen.getByTestId('param-domain-remnant'))
    await waitFor(() => expect(screen.getByTestId('param-remnant-specs')).toBeInTheDocument())
    const remnant = screen.getByTestId('param-remnant-specs')
    expect(remnant.textContent ?? '').not.toContain('**')
    expect(
      Array.from(remnant.querySelectorAll('strong')).map((el) => el.textContent)
    ).toContain('能再用')
  })

  it('红证：内联面板**不出现**在别的域里（防止把面板挂到算料域 = 入口分裂）', () => {
    renderPanel()
    expect(screen.getByTestId('param-hem_margin')).toBeInTheDocument()
    expect(screen.queryByTestId('param-remnant-specs')).not.toBeInTheDocument()
    fireEvent.click(screen.getByTestId('param-domain-remnant'))
    expect(screen.getByTestId('param-remnant-specs')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('param-domain-calc'))
    expect(screen.queryByTestId('param-remnant-specs')).not.toBeInTheDocument()
  })
})

/**
 * 判据 9（issue #6573 · 域级权限）：**不持该码的域既不渲染也不请求**。
 *
 * 红证形态：把 `visibleDomains` 的过滤条件删掉（或改成恒真）⇒ ①② 必红；
 * 把 AI 懒加载的 `aiVisible` 条件删掉 ⇒ ③ 的「不请求」必红。
 */
describe('判据 9：域级权限 —— 看得见取决于持码（issue #6573）', () => {
  it('不持 system:manage ⇒ AI 客服域**不渲染**，也不发该域读面', () => {
    setPerms([CALC_CODE, REMNANT_CODE])
    renderPanel()
    expect(screen.queryByTestId('param-domain-ai')).not.toBeInTheDocument()
    expect(getAiConfig).not.toHaveBeenCalled()
  })

  it('不持 processing:manage ⇒ 余料回收域**不渲染**（内联面板随之不挂载、不发读面）', () => {
    setPerms([CALC_CODE, AI_CODE])
    renderPanel()
    expect(screen.queryByTestId('param-domain-remnant')).not.toBeInTheDocument()
    expect(getRemnantSpecs).not.toHaveBeenCalled()
  })

  it('持 system:manage 但**不切到**该域 ⇒ 一个请求都不发（懒加载只在「看得见 ∧ 切过去」时发一次）', () => {
    renderPanel()
    expect(screen.getByTestId('param-domain-ai')).toBeInTheDocument()
    expect(getAiConfig).not.toHaveBeenCalled()
  })

  it('切到 AI 客服域 ⇒ 恰好发一次；来回切换不重复发（`aiRequested` 一次性闸门）', async () => {
    renderPanel()
    fireEvent.click(screen.getByTestId('param-domain-ai'))
    await waitFor(() => expect(getAiConfig).toHaveBeenCalledTimes(1))
    fireEvent.click(screen.getByTestId('param-domain-calc'))
    fireEvent.click(screen.getByTestId('param-domain-ai'))
    await waitFor(() => expect(screen.getByTestId('param-value-botName')).toHaveTextContent('元元'))
    expect(getAiConfig).toHaveBeenCalledTimes(1)
  })
})

/**
 * 判据 10（issue #6573 · 受控组件契约）：值由 props 决定，**第一屏取数不藏在本组件里**。
 *
 * 红证形态：把 `productionApi.getCraftCalcConfig` 重新写回本组件 ⇒ ② 必红；
 * 把 `loading ? '…' : valueOf(...)` 的 `loading` 分支删掉 ⇒ ① 必红（加载中会显示「—」= 谎报「没配」）。
 */
describe('判据 10：受控组件（#6573）—— 值来自 props、取数不在本组件', () => {
  it('loading ⇒ 值位是占位「…」（加载中不把值画成「—」= 不谎报「没配」）', () => {
    renderPanel({ loading: true, calc: null })
    expect(screen.getByTestId('param-value-hem_margin')).toHaveTextContent('…')
  })

  it('🔴 loading 中 / 读失败 ⇒ **不许**说「未配置（正在用引擎默认值）」（#6573 收口：`isUsingEngineDefault(undefined) === true` 的谎报形态）', () => {
    // 首屏那一瞬 `calc === null` ⇒ `source === undefined` 会被 `isUsingEngineDefault` 读成
    // 「在用引擎默认值」⇒ 不设栏就把「还不知道」说成「你没配」。读失败同理：那时该说的是
    // **可行动话术**（页面下发 `calcError`），而不是一条「未配置」的事实断言。
    const first = renderPanel({ loading: true, calc: null })
    expect(screen.queryByTestId('param-calc-using-default')).not.toBeInTheDocument()
    expect(screen.queryByTestId('param-unset-hem_margin')).not.toBeInTheDocument()
    first.unmount()

    renderPanel({ calc: null, calcError: PAGE_CALC_ERROR })
    expect(screen.getByTestId('param-calc-error')).toBeInTheDocument()
    expect(screen.queryByTestId('param-calc-using-default')).not.toBeInTheDocument()
    expect(screen.queryByTestId('param-unset-hem_margin')).not.toBeInTheDocument()
  })

  it('面板**不发**算料读面（第一屏取数由页面发起，页面守卫见 settings-params.test.tsx）', () => {
    renderPanel()
    expect(getCraftCalcConfig).not.toHaveBeenCalled()
  })

  it('readiness 槽位渲染在标题卡之后、域导航之前（进页第一眼是「还缺什么 / 下一步去哪」）', () => {
    renderPanel({ readiness: <div data-testid="readiness-slot">配置主线（替身）</div> })
    const slot = screen.getByTestId('readiness-slot')
    const title = screen.getByRole('heading', { level: 2, name: '参数总览' })
    const nav = screen.getByTestId('param-domain-calc')
    expect(title.compareDocumentPosition(slot) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(slot.compareDocumentPosition(nav) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('未传 readiness ⇒ 槽位为空，面板其余部分照常渲染（槽位是可选入参）', () => {
    renderPanel()
    expect(screen.queryByTestId('config-readiness')).not.toBeInTheDocument()
    expect(screen.getByTestId('param-domain-calc')).toBeInTheDocument()
  })
})