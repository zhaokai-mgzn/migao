// case_ids: UI-054
/**
 * `/settings/params`（参数总览 · 一级菜单项）**页面**守卫（issue #6573）。
 *
 * 分工：面板自身（受控渲染、域级权限、三件套）在
 * `frontend/admin-web/tests/unit/components/TenantParamsPanel.test.tsx`；主线的**纯判据**在
 * `frontend/admin-web/tests/unit/lib/config-readiness.test.ts`；本文件只判**页面**做的那两件事：
 *
 * 1. 🔴 **第一屏取数面**：渲染时**恰好**发起 5 个生产域读面（`production:view` = 菜单节点码 =
 *    路由守卫码），且**不**请求 AI 客服读面（那是域级懒加载，切过去才发一次）。
 *    仓内口径 = 「页面源码里由 `useEffect` 驱动的可执行面 = 该页第一屏读端点」
 *    （`tests/unit_ci_workflows/test_agent_permission_parity.py` 的 `MENU_READ_ENDPOINT_ANCHORS` 那一跳）
 *    ⇒ 把取数藏进子组件，这一跳就**看不见它**；本文件的计数断言就是那条口径的**机器读数**。
 * 2. **配置主线**：三态如实（读失败 ⇒ `unknown` = 「读不到」，**绝不**画成「待配置」）、
 *    常驻面只有一行摘要、逐项明细**折叠态下 DOM 不渲染**（§31 P1）。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import TenantParamsPage from '@/app/(dashboard)/settings/params/page'
import { BASE_ROUTE_NAMES, MAINLINE_STEPS } from '@/lib/config-readiness'
import { CALC_SCALAR_KEYS } from '@/lib/craft-calc-glossary'

const getOperationPositions = vi.fn()
const getRoutings = vi.fn()
const getFeeCombinations = vi.fn()
const getFeeGaps = vi.fn()
const getCraftCalcConfig = vi.fn()
// 域级懒加载读面（**第一屏不该碰它**）与子组件各自的读面
const getAiConfig = vi.fn()
const previewAutoFeatures = vi.fn()
const getSmallItemSpecs = vi.fn()

vi.mock('@/lib/api', () => ({
  productionApi: {
    getOperationPositions: () => getOperationPositions(),
    getRoutings: () => getRoutings(),
    getFeeCombinations: () => getFeeCombinations(),
    getFeeGaps: () => getFeeGaps(),
    getCraftCalcConfig: (withDefaults?: boolean) => getCraftCalcConfig(withDefaults),
  },
  settingsApi: { getAiConfig: () => getAiConfig() },
  autoFeaturesApi: { preview: () => previewAutoFeatures() },
  remnantApi: {
    smallItemSpecs: () => getSmallItemSpecs(),
    putSmallItemSpecs: () => Promise.resolve({ data: { success: true, data: null } }),
  },
}))

/** 登录态：**按 zustand 选择器**返回（`usePermission()` 走 `useAuthStore(s => s.user)`） */
const authMock = vi.hoisted(() => ({
  state: {
    user: {
      id: '1',
      username: 'tester',
      name: '测试账号',
      // 三个域级读码都持 ⇒ AI 域**看得见**（于是「不请求」这件事才是判据，而不是「域根本没渲染」）
      permissions: ['production:view', 'system:manage', 'processing:manage'] as string[],
      roles: [] as string[],
    },
  },
}))
vi.mock('@/store/auth', () => ({
  useAuthStore: (selector?: (s: unknown) => unknown) =>
    typeof selector === 'function' ? selector(authMock.state) : authMock.state,
}))

/** `request.get` 的返回壳 */
const ok = (data: unknown) => ({ data: { success: true, data } })

/** 算料读面：`source` 三态（`stored` / `default` / 其余）+ 引擎键集的配置值 */
function calcResponse(source: string, value = 0.4) {
  return ok({ source, config: Object.fromEntries(CALC_SCALAR_KEYS.map((k) => [k, value])) })
}

/** 两条基础路线齐 + 恰好一条默认（第 ② ③ 步的「已完成」形态）——路线名取自 `BASE_ROUTE_NAMES`，不写第二份 */
const DONE_ROUTINGS = ok({
  routings: [
    { name: BASE_ROUTE_NAMES[0], is_default: true },
    { name: BASE_ROUTE_NAMES[1], is_default: false },
  ],
})

/** 五个读面**全部成功且都「已配置」**：主线应当判 5/5 完成 */
function allConfigured() {
  getOperationPositions.mockResolvedValue(ok([{ unit_price: 12 }, { unit_price: 8 }]))
  getRoutings.mockResolvedValue(DONE_ROUTINGS)
  getFeeCombinations.mockResolvedValue(ok({ total: 3, combinations: [] }))
  getFeeGaps.mockResolvedValue(ok({ unpriced_combination_total: 0 }))
  getCraftCalcConfig.mockResolvedValue(calcResponse('stored'))
}

beforeEach(() => {
  for (const fn of [
    getOperationPositions,
    getRoutings,
    getFeeCombinations,
    getFeeGaps,
    getCraftCalcConfig,
    getAiConfig,
    previewAutoFeatures,
    getSmallItemSpecs,
  ]) {
    fn.mockReset()
  }
  allConfigured()
  getAiConfig.mockResolvedValue(ok({ botName: '元元', greetingTemplate: '您好' }))
  previewAutoFeatures.mockResolvedValue(ok({ auto_features: [] }))
  getSmallItemSpecs.mockResolvedValue(ok({ configured: true, items: [], notice: '' }))
})

describe('判据 1：第一屏取数面（#6573 —— 恰好 5 个生产域读面，且不碰 AI 域）', () => {
  it('渲染 ⇒ 恰好发起 5 个生产域读面（逐个 1 次），且**不**请求 AI 客服读面', async () => {
    render(<TenantParamsPage />)
    // 正向前置：读数真的落到了界面上（否则「一个都没调」也能让下面的计数断言「通过」一部分）
    await waitFor(() =>
      expect(screen.getByTestId('config-readiness-headline')).toHaveTextContent('配置已完成 5/5')
    )

    expect(getOperationPositions).toHaveBeenCalledTimes(1)
    expect(getRoutings).toHaveBeenCalledTimes(1)
    expect(getFeeCombinations).toHaveBeenCalledTimes(1)
    expect(getFeeGaps).toHaveBeenCalledTimes(1)
    expect(getCraftCalcConfig).toHaveBeenCalledTimes(1)
    // 算料读面必须**要**引擎默认值（`with_defaults=true` ⇒ 逐键「我改过没有」才可比）
    expect(getCraftCalcConfig).toHaveBeenCalledWith(true)

    // 「恰好」：五路之和 = 5 —— 多一个第一屏读面（未登记的码）会当场红
    const total =
      getOperationPositions.mock.calls.length +
      getRoutings.mock.calls.length +
      getFeeCombinations.mock.calls.length +
      getFeeGaps.mock.calls.length +
      getCraftCalcConfig.mock.calls.length
    expect(total).toBe(5)

    // AI 客服域读面是**域级懒加载**：持码、看得见，但第一屏**不**请求
    expect(screen.getByTestId('param-domain-ai')).toBeInTheDocument()
    expect(getAiConfig).not.toHaveBeenCalled()
  })

  it('切到 AI 客服域才发 AI 读面（且只发一次）—— 懒加载不是「第一屏码」', async () => {
    render(<TenantParamsPage />)
    await waitFor(() =>
      expect(screen.getByTestId('config-readiness-headline')).toHaveTextContent('配置已完成 5/5')
    )
    expect(getAiConfig).not.toHaveBeenCalled()

    fireEvent.click(screen.getByTestId('param-domain-ai'))
    await waitFor(() => expect(getAiConfig).toHaveBeenCalledTimes(1))
    fireEvent.click(screen.getByTestId('param-domain-calc'))
    fireEvent.click(screen.getByTestId('param-domain-ai'))
    await waitFor(() =>
      expect(screen.getByTestId('param-value-botName')).toHaveTextContent('元元')
    )
    expect(getAiConfig).toHaveBeenCalledTimes(1)
  })
})

describe('判据 2：配置主线 —— 全配置完成（§31 P1 常驻一行摘要）', () => {
  it('5 个读面都成功且都「已配置」⇒ 常驻摘要显示 5/5 已完成（加载中说的是「读取中…」）', async () => {
    render(<TenantParamsPage />)
    const headline = screen.getByTestId('config-readiness-headline')
    // 加载期**不谎报**：既不说完成，也不说缺什么
    expect(headline).toHaveTextContent('配置主线读取中…')

    await waitFor(() => expect(headline).toHaveTextContent('配置已完成 5/5'))
    // 全完成 ⇒ 摘要里没有「下一步」也没有「未配置」
    expect(headline.textContent ?? '').not.toContain('下一步')
    expect(headline.textContent ?? '').not.toContain('未配置')
  })

  it("算料读面 source='stored' ⇒ 面板**不**显示「未配置（正在用引擎默认值）」徽标（读面真值一路传到渲染）", async () => {
    render(<TenantParamsPage />)
    await waitFor(() =>
      expect(screen.getByTestId('config-readiness-headline')).toHaveTextContent('配置已完成 5/5')
    )
    expect(screen.queryByTestId('param-calc-using-default')).not.toBeInTheDocument()
    expect(screen.queryByTestId('param-unset-hem_margin')).not.toBeInTheDocument()
    expect(screen.queryByTestId('param-calc-error')).not.toBeInTheDocument()
    // 正控：同一个值位真的拿到了读面的配置值（否则「徽标不在」可能是面板根本没渲染）
    expect(screen.getByTestId('param-value-hem_margin')).toHaveTextContent('0.4')
  })
})

describe('判据 3：三态纪律 —— 读失败是「读不到」，**绝不**画成「待配置」', () => {
  it('加工费缺口读面 rejected ⇒ 该步 unknown（徽标「读不到」），其余四步仍「已配置」，全表零「待配置」', async () => {
    getFeeGaps.mockRejectedValue(new Error('500'))
    render(<TenantParamsPage />)
    const headline = screen.getByTestId('config-readiness-headline')
    await waitFor(() => expect(headline).toHaveTextContent('配置完成 4/5'))
    expect(headline).toHaveTextContent('1 项读不到')
    expect(headline).toHaveTextContent('下一步「加工费组合」')

    fireEvent.click(screen.getByTestId('config-readiness-toggle'))
    expect(screen.getByTestId('readiness-state-fee-combinations')).toHaveTextContent('读不到')
    // 🔴 三态不互画：整个清单里**一个**「待配置」都不许有（读不到 ≠ 没配）
    expect(screen.queryAllByText('待配置')).toHaveLength(0)
    // 反向对照：不能靠「全都退化成 unknown」蒙混过关
    for (const key of ['operations', 'routings', 'default-route', 'calc']) {
      expect(screen.getByTestId(`readiness-state-${key}`)).toHaveTextContent('已配置')
    }
  })

  it('算料读面 rejected ⇒ 面板给可行动话术 + 该步 unknown（话术由**页面**产出，不在子组件里）', async () => {
    getCraftCalcConfig.mockRejectedValue(new Error('403'))
    render(<TenantParamsPage />)
    const err = await screen.findByTestId('param-calc-error')
    // 权限拒绝是**终态**，不是「参数有问题」——给可行动话术，不让商家反复重试
    expect(err).toHaveTextContent('请联系管理员')

    await waitFor(() =>
      expect(screen.getByTestId('config-readiness-headline')).toHaveTextContent('配置完成 4/5')
    )
    fireEvent.click(screen.getByTestId('config-readiness-toggle'))
    expect(screen.getByTestId('readiness-state-calc')).toHaveTextContent('读不到')
    expect(screen.queryAllByText('待配置')).toHaveLength(0)
  })

  it('工艺路线读面 rejected ⇒ **同源的**两步（工艺路线 / 默认路线）一起 unknown（一个读面喂两步）', async () => {
    getRoutings.mockRejectedValue(new Error('500'))
    render(<TenantParamsPage />)
    await waitFor(() =>
      expect(screen.getByTestId('config-readiness-headline')).toHaveTextContent('配置完成 3/5')
    )
    fireEvent.click(screen.getByTestId('config-readiness-toggle'))
    expect(screen.getByTestId('readiness-state-routings')).toHaveTextContent('读不到')
    expect(screen.getByTestId('readiness-state-default-route')).toHaveTextContent('读不到')
    expect(screen.getByTestId('readiness-state-operations')).toHaveTextContent('已配置')
    expect(screen.queryAllByText('待配置')).toHaveLength(0)
  })
})

describe('判据 4：§31 P1 —— 折叠态逐项 DOM 不渲染，展开才出现（CSS 隐藏不算）', () => {
  it('初始：常驻摘要 + 收起按钮（aria-expanded=false）、逐项取不到；展开：五步逐项 + 徽标 + 去处;收起：再消失', async () => {
    render(<TenantParamsPage />)
    await waitFor(() =>
      expect(screen.getByTestId('config-readiness-headline')).toHaveTextContent('配置已完成 5/5')
    )
    const toggle = screen.getByTestId('config-readiness-toggle')
    expect(toggle).toHaveAttribute('aria-expanded', 'false')

    // 🔴 红证形态：`queryByTestId` 必须**取不到**节点（把明细改成 CSS 隐藏 / `sr-only` ⇒ 本组必红）
    expect(screen.queryByTestId('config-readiness-list')).toBeNull()
    for (const s of MAINLINE_STEPS) {
      expect(screen.queryByTestId(`readiness-item-${s.key}`)).toBeNull()
    }

    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByTestId('config-readiness-list')).toBeInTheDocument()
    // 五步一条不少
    expect(screen.getAllByTestId(/^readiness-item-/)).toHaveLength(MAINLINE_STEPS.length)
    for (const s of MAINLINE_STEPS) {
      const item = screen.getByTestId(`readiness-item-${s.key}`)
      expect(item).toBeInTheDocument()
      // 每步给「状态 + 去处」（文案与影响说明由 ConfigReadinessBar 渲染，纯判据在 lib 侧）
      expect(screen.getByTestId(`readiness-state-${s.key}`)).toHaveTextContent('已配置')
      expect(screen.getByTestId(`readiness-goto-${s.key}`)).toHaveAttribute('href', s.href)
    }

    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByTestId('readiness-item-calc')).toBeNull()
  })
})