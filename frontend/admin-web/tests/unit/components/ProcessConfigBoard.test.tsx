// case_ids: UI-054
/**
 * 工艺配置功能体（issue #6580）—— `ProcessConfigBoard` 的**两种挂载形态**判据。
 *
 * ## 为什么这份测试只判「形态」不判数据面
 *
 * 数据面（工序/价目/路线/规则/矩阵）由 `tests/unit/pages/production-routings.test.tsx` 的 163 条覆盖
 * —— 本包把功能体从页面里**零逻辑改动**搬出来，那些判据就是搬运等价性的证据。本文件只判**新的那一件事**：
 * 被配置指挥台挂载时（`embedded`）**不许**再渲染页头与自带的「配置就绪度」卡 ——
 * 同屏两个就绪面、两个标题正是用户说的「散乱的配置乱放」（设计真值源 §2 判死线第 2 条）。
 */
import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

// 全部 api 命名空间/方法兜底成「成功但内容空」—— 本文件不判数据面（见文件头）；
// 需要具体形状的少数方法在下面逐个给。
vi.mock('@/lib/api', () => {
  // 逐方法**显式**给具名导出（vitest 的 ESM mock 不支持用 Proxy 兜 —— 兜不住会让板子
  // 在「一切报错」的状态下渲染，那样「页头在不在」就成了弱断言）。数据面为空是**故意**的：
  // 本文件只判形态，数据面由 `tests/unit/pages/production-routings.test.tsx` 的 163 条覆盖。
  const ok = () => Promise.resolve({ data: { success: true, data: [] } })
  const f = () => vi.fn(ok)
  return {
    productionApi: {
      getRoutings: f(), updateRouting: f(), createRouting: f(), deleteRouting: f(),
      getOperationsCatalog: f(), createOperation: f(), updateOperation: f(), deleteOperation: f(),
      getOperationPositions: f(), updateOperationPosition: f(), getOperationLayers: f(),
      getRouteRules: f(), getRouteRuleOptions: f(), deleteRouteRule: f(),
      updateRuleCustomerUnitPrice: f(), getRouteSignals: f(), createOptionRule: f(),
      getCraftCalcConfig: () =>
        Promise.resolve({
          data: { success: true, data: { config: { per_fold_single: 0.3 }, source: 'stored' } },
        }),
      updateCraftCalcConfig: f(),
    },
    cuttingHeightApi: { get: f(), update: f(), preview: f() },
    autoFeaturesApi: { preview: f() },
  }
})
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import ProcessConfigBoard from '@/components/production-config/ProcessConfigBoard'

describe('工艺配置功能体的挂载形态（issue #6580）', () => {
  it('独立形态（默认，旧路由 `/production/routings` 用）：页头「工艺配置」在', async () => {
    render(<ProcessConfigBoard />)
    expect(await screen.findByText('工艺配置')).toBeInTheDocument()
  })

  it('🔴 嵌入形态（配置指挥台用）：页头标题**不渲染**（域面板已给标题与一句话）', async () => {
    render(<ProcessConfigBoard embedded />)
    // 等一轮渲染（数据面到齐与否都要满足「标题不出现」）
    await waitFor(() => expect(screen.queryByText('工艺配置')).toBeNull())
    expect(screen.queryByText(/管理工序与计件单价、工艺路线和算料口径/)).toBeNull()
  })
})
