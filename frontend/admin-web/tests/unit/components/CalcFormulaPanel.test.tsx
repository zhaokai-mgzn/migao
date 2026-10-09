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
import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

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
