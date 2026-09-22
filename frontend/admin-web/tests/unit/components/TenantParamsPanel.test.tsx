// case_ids: UI-054
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

vi.mock('@/lib/api', () => ({
  productionApi: { getCraftCalcConfig: () => getCraftCalcConfig() },
  settingsApi: { getAiConfig: () => getAiConfig() },
  // §22 P4 阈值试算（issue #5131）：算料域会挂载试算块 ⇒ 该读面必须可用
  autoFeaturesApi: {
    preview: () => Promise.resolve({ data: { success: true, data: { auto_features: [] } } }),
  },
}))

/** 服务端读面形状：`{success, data: {source, config}}` —— 配置值由**引擎键集**生成，不写死 */
function calcResponse(source: string, value = 0.4) {
  const config = Object.fromEntries(CALC_SCALAR_KEYS.map((k) => [k, value]))
  return { data: { success: true, data: { source, config } } }
}

const aiResponse = {
  data: { success: true, data: { botName: '小布', greetingTemplate: '您好' } },
}

beforeEach(() => {
  getCraftCalcConfig.mockReset()
  getAiConfig.mockReset()
  getCraftCalcConfig.mockResolvedValue(calcResponse('default'))
  getAiConfig.mockResolvedValue(aiResponse)
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
    expect(screen.getByTestId('param-value-hem_margin')).toHaveTextContent('0.4')
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
