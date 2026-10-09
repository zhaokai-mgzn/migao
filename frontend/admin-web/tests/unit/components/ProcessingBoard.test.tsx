// case_ids: UI-054
/**
 * 加工项与加工费功能体（issue #6580）—— `ProcessingBoard` 的**两种挂载形态**判据。
 *
 * 数据面（加工项 CRUD、分类、加工费组合、未定价组合）由
 * `tests/unit/pages/production-board.test.tsx` 覆盖 —— 本包是**零逻辑改动**搬运。
 * 本文件只判新的那一件事：被配置指挥台挂载时（`embedded`）不许再渲染页头「加工项管理」
 * （域面板已给「加工项与加工费」标题与一句话；两层标题 = 用户说的「散乱」）。
 */
import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

vi.mock('@/lib/api', () => {
  // 具名导出（同 ProcessConfigBoard 测试的理由）；数据面为空是故意的：本文件只判形态。
  const ok = () => Promise.resolve({ data: { success: true, data: [] } })
  const f = () => vi.fn(ok)
  return {
    processingItemApi: {
      list: f(), create: f(), update: f(), remove: f(), getProcessingItems: f(),
      createProcessingItem: f(), updateProcessingItem: f(), deleteProcessingItem: f(),
    },
    processingCategoryApi: { getProcessingCategories: f(), createProcessingCategory: f() },
    productionApi: {
      getFeeCombinations: f(), getFeeGaps: f(), createFeeCombination: f(),
      updateFeeCombination: f(), disableFeeCombination: f(),
    },
  }
})
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import ProcessingBoard from '@/components/production-config/ProcessingBoard'

describe('加工费功能体的挂载形态（issue #6580）', () => {
  it('独立形态（默认，旧路由 `/production/processing` 用）：页头「加工项管理」在', async () => {
    render(<ProcessingBoard />)
    expect(await screen.findByText('加工项管理')).toBeInTheDocument()
  })

  it('🔴 嵌入形态（配置指挥台用）：页头标题**不渲染**，但功能面照旧', async () => {
    render(<ProcessingBoard embedded />)
    await waitFor(() => expect(screen.queryByText('加工项管理')).toBeNull())
    expect(screen.queryByText(/管理下单时客户可选的加工服务与加工费/)).toBeNull()
  })
})
