// case_ids: UI-054
/**
 * `CalcFormulaPanel` 的**两种挂载形态**判据（issue #6585 P1）。
 *
 * ## 这个面板为什么是「算料口径域的一块」而不是独立域
 *
 * v2 把板子 calc tab 里 `CalcCaliberPanel` **没有**的两块搬进「算料口径」域：
 * **公式编辑**（`craft-calc-config-default_formula`）与**读数原因**（`craft-calc-config-reasons`）。
 * 标量参数已在 `CalcCaliberPanel` 里 ⇒ 本面板**不重复搬**（那会造出第二份口径）。
 * 它会与 `CalcCaliberPanel` **同屏**（同一域）⇒ `embedded` 形态下**不渲染自己的区块标题**
 * 尤其重要（否则与域标题 / 算料面板标题重复）。
 *
 * 判据：① 自包含（单独挂载即自读 `craft-calc-config`）② embedded 不渲染本层标题、公式控件与
 * 理由块仍在（**用 testid 判**）。
 *
 * ⚠️ mock 一律**显式具名导出**（不用 Proxy 兜底）。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import { toast } from 'sonner'

vi.mock('@/lib/api', () => ({
  productionApi: {
    getCraftCalcConfig: vi.fn(() =>
      Promise.resolve({
        data: {
          success: true,
          data: {
            source: 'stored',
            config: { default_formula: 'pleat', per_fold_single: 0.25 },
          },
        },
      }),
    ),
    updateCraftCalcConfig: vi.fn(() => Promise.resolve({ data: { success: true, data: {} } })),
  },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import { CalcFormulaPanel } from '@/components/production-config/CalcFormulaPanel'
import { productionApi } from '@/lib/api'
import { markErrorToastShown } from '@/lib/api-error'

describe('CalcFormulaPanel（算料口径域的一块，issue #6585）', () => {
  it('① 自包含：单独挂载即自读算料配置，并渲染公式编辑面', async () => {
    render(<CalcFormulaPanel />)
    await waitFor(() => expect(productionApi.getCraftCalcConfig).toHaveBeenCalled())
    // 关键功能面在（用 testid 判）：公式编辑 + 保存
    const formula = await screen.findByTestId('craft-calc-config-default_formula')
    expect(formula).toHaveValue('pleat')
    expect(screen.getByTestId('craft-calc-config-save')).toBeInTheDocument()
  })

  it('② embedded：本层区块标题不渲染，但公式编辑面仍在', async () => {
    render(<CalcFormulaPanel embedded />)
    await waitFor(() => expect(screen.getByTestId('craft-calc-config-default_formula')).toBeInTheDocument())
    expect(screen.queryByText('算料公式')).toBeNull()
    expect(screen.getByTestId('craft-calc-config-default_formula')).toBeInTheDocument()
    expect(screen.getByTestId('craft-calc-config-save')).toBeInTheDocument()
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// 判据 ③：读失败 ⇒ 面板内**恰好一处**失败信号（issue #6669 未完成 1 / §31 P1 常驻面克制 · P2 信息不重复）
//
// 病灶（真机读图实测，2026-10-10）：`/settings` 的算料域读失败时，同一故障在**一屏之内**渲染了
// **四处**信号 —— ① `CalcCaliberPanel` 顶部红条；② 域徽标「读不到」；③ 参数数值位一排 `—`；
// ④ 本面板底部「算料配置加载失败，请稍后重试 [重试]」。
// #6663 撤掉 ① 以外的本域三处（不再画参数卡、数值位不再用 `—`、去掉重复文案），
// **本文件族的第 ④ 处由本包收口**。
//
// ## 判的是「几处」，不是「哪句话」
//
// 统计**失败文案节点的数量**与**可点重试入口的数量**，断言 `=== 1`（不锚具体文案 ——
// 文案会随话术迭代漂移，而「一处」是本条纪律本身）。
//
// ## 本面板为什么**不再**自己弹 toast（实测依据）
//
// `frontend/admin-web/src/lib/request.ts` 的响应拦截器对**所有**失败分支
// （`success:false` 业务错 / 各种 HTTP 状态 / 网络错 / 非 axios 错）都已 `toast.error(...)`
// 且 `markErrorToastShown(error)` ⇒ 真 API 失败时本面板那句 `if (!isErrorToastShown(e)) toast.error(...)`
// 是**不执行**的死分支；它只在「错误不是经拦截器抛出的」时执行 —— 那种情形下面板内联那行**同屏也在**，
// 等于同一个故障报两遍（toast + 内联）。⇒ 撤掉本面板自己的播报，**保留**内联摘要 + 「重试」出口
// （硬约束：撤的是**重复**，不是**可见性**）。同族守卫见 `tests/unit/read-failure-empty-state-guard.test.ts`。
// ══════════════════════════════════════════════════════════════════════════════
describe('判据 ③：读失败只留一处失败信号（issue #6669 · 收敛自 #6663/§31）', () => {
  beforeEach(() => {
    vi.mocked(toast.error).mockClear()
    vi.mocked(toast.success).mockClear()
    vi.mocked(productionApi.getCraftCalcConfig).mockReset()
    vi.mocked(productionApi.getCraftCalcConfig).mockRejectedValue(new Error('500'))
  })

  it('读接口失败（mock 抛错）⇒ 面板内**恰好一处**失败摘要 + **恰好一个**「重试」出口，且本面板零 toast 播报', async () => {
    render(<CalcFormulaPanel />)
    await waitFor(() => expect(screen.getByTestId('craft-calc-config-error')).toBeInTheDocument())

    // 在屏上看得见（硬约束：不许把失败变静默）
    const failure = screen.getAllByTestId('craft-calc-config-error')
    expect(failure, '同一次读失败的面板内联失败信号必须恰好一处').toHaveLength(1)
    expect(failure[0]).toHaveTextContent('算料配置加载失败')

    // 有出口（硬约束：失败态必须给下一步）
    const retry = within(failure[0]).getByTestId('craft-calc-config-retry')
    expect(retry).toHaveTextContent('重试')

    // 重复信号：本面板自己的 toast 播报（拦截器已统一播报，面板再播一遍 = 同屏两处）
    expect(toast.error, '面板已内联播报失败 ⇒ 不得再弹一次 toast（重复信号）').not.toHaveBeenCalled()

    // 失败态不伪装成读数：公式控件与保存按钮都不渲染
    expect(screen.queryByTestId('craft-calc-config-default_formula')).toBeNull()
    expect(screen.queryByTestId('craft-calc-config-save')).toBeNull()
  })

  it('对照读数：读成功 ⇒ 失败信号与 toast 都不出现（不是恒显失败）', async () => {
    vi.mocked(productionApi.getCraftCalcConfig).mockResolvedValue({
      data: { success: true, data: { source: 'stored', config: { default_formula: 'pleat' } } },
    } as never)
    render(<CalcFormulaPanel />)
    await waitFor(() => expect(screen.getByTestId('craft-calc-config-default_formula')).toBeInTheDocument())
    expect(screen.queryByTestId('craft-calc-config-error')).toBeNull()
    expect(toast.error).not.toHaveBeenCalled()
  })

  /**
   * 🔴 **两种失败形态的实测读数**（集成侧 2026-10-10 真机注入式验收的观察项：全局 api-error 层
   * 的泛化 toast「服务器内部错误」与页面内联横幅**同屏**）。
   *
   * 本条的射程**只有面板侧**（全局层不属本文件面 —— 见 PR body「未收口的一半」）：
   * 面板要回答的问题 = 「全局 toast 必然播时，面板还要不要再播一次」。
   *
   * | 失败形态 | 全局拦截器（`lib/request.ts`） | 本面板改前 | 本面板改后 |
   * |---|---|---|---|
   * | 真 API 失败（`success:false` / 4xx / 5xx / 网络错） | **播**泛化 toast + `markErrorToastShown` | 那句 `if (!isErrorToastShown(e)) toast.error(…)` 是**死分支**（不播） | 不播（代码已删） |
   * | 错误不经拦截器（本文件这类替身抛的裸 `Error`） | **不播** | **播**「算料配置加载失败」（与内联摘要同屏两处） | 不播（内联摘要即那一处） |
   *
   * ⇒ 命名形态（= 真 API 失败）下**必然同时出现**的是「全局泛化 toast + 面板内联摘要」，
   * 面板自己那次播报两种形态下都**不该**存在 —— 处置 = **不重复播报**（内联摘要 + 「重试」是面板侧那一处）。
   */
  it('读数：真 API 失败的命名形态（拦截器已播 + 已打标）⇒ 面板**不重复播报**，但失败仍可见且有出口', async () => {
    const err = new Error('服务器内部错误')
    markErrorToastShown(err) // 模拟 `lib/request.ts` 拦截器：已 toast + 已打标
    vi.mocked(productionApi.getCraftCalcConfig).mockRejectedValue(err)
    render(<CalcFormulaPanel />)

    const failure = await screen.findByTestId('craft-calc-config-error')
    expect(failure).toHaveTextContent('算料配置加载失败')
    expect(within(failure).getByTestId('craft-calc-config-retry')).toBeInTheDocument()
    // 🟢 **不重复播报**（而不是「保留一处兜底」）：本面板 0 次 toast —— 全局层那次是它自己的
    expect(toast.error, '拦截器已播泛化 toast ⇒ 面板不得再播一次（同屏两处）').not.toHaveBeenCalled()
  })
})
