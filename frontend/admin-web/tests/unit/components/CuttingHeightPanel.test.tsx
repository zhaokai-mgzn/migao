// case_ids: UI-054
/**
 * `CuttingHeightPanel` 的**两种挂载形态**判据（issue #6585 P1）。
 *
 * ① **自包含**：单独 `render(<CuttingHeightPanel />)` 即发起它自己的读面
 *    （`cuttingHeightApi.get()` —— 本层为了「配没配」的 `source` 自己读一次；
 *    内层 `CuttingHeightConfigPanel` 按既有实现再读一次，与搬运前的板子**逐字相同**）。
 * ② **embedded 形态**：本层区块标题不渲染，但裁高配置面板本体（**用 testid 判**）仍在。
 *
 * ⚠️ mock 一律**显式具名导出**（不用 Proxy 兜底）。
 */
import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

vi.mock('@/lib/api', () => ({
  cuttingHeightApi: {
    get: vi.fn(() =>
      Promise.resolve({
        data: {
          success: true,
          data: {
            source: 'default',
            config: { items: [], rounding: { mode: 'none', step: null } },
          },
        },
      }),
    ),
    update: vi.fn(() => Promise.resolve({ data: { success: true, data: {} } })),
    preview: vi.fn(() => Promise.resolve({ data: { success: true, data: {} } })),
  },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import { CuttingHeightPanel } from '@/components/production-config/CuttingHeightPanel'
import { cuttingHeightApi } from '@/lib/api'

describe('CuttingHeightPanel（裁高配置域，issue #6585）', () => {
  it('① 自包含：单独挂载即发起自己的裁高读面', async () => {
    render(<CuttingHeightPanel />)
    await waitFor(() => expect(cuttingHeightApi.get).toHaveBeenCalled())
    // 关键功能面在（用 testid 判）
    expect(await screen.findByTestId('cutting-height-config-panel')).toBeInTheDocument()
  })

  it('② embedded：区块标题不渲染，但裁高配置面板本体仍在', async () => {
    render(<CuttingHeightPanel embedded />)
    await waitFor(() => expect(screen.getByTestId('cutting-height-config-panel')).toBeInTheDocument())
    expect(screen.queryByText('裁高配置')).toBeNull()
    // 容器 testid（就绪度第 ⑤ 步的「去处理」要滚到它）仍在
    expect(screen.getByTestId('cutting-height-panel')).toBeInTheDocument()
  })
})
