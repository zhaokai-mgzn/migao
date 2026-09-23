// case_ids: UI-054
/**
 * 阈值**试算**（§22 P4「改钱的参数给护栏 + 预览」）渲染面守卫（issue #5131）。
 *
 * 判据（每条都能单独变红）：
 * 1. 初值 = 该租户**当前**阈值（来自读面，不写死数字），且**同时**发起「当前口径」与「调整后」两次试算；
 * 2. 判定依据**逐字**来自服务端（本组件不拼、不判）；
 * 3. 改阈值 ⇒ 用**新值**重发试算（证明它真的在预演，而不是把初始结果一直摆着）；
 * 4. 服务端失败 ⇒ 给可行动话术，**不**静默显示「不判任何特征」（那是把它当成结论）；
 * 5. **本组件不保存** —— 只调判定读面，不调任何写面。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { OversizeThresholdPreview } from '@/components/settings/OversizeThresholdPreview'
import type { CraftCalcConfig } from '@/types'

const preview = vi.fn()
vi.mock('@/lib/api', () => ({
  autoFeaturesApi: { preview: (p: unknown) => preview(p) },
}))

/** 该租户当前配置（读面原文形状：阈值就在配置里，不是前端常量） */
const CONFIG = {
  oversize_width_threshold: 6,
  oversize_height_threshold: 4,
} as unknown as CraftCalcConfig

/** 服务端替身：阈值 > 5 判超宽，否则不判 —— 让「改阈值 ⇒ 结论变」可观测 */
function serveByThreshold(p: { config?: Record<string, unknown> }) {
  const w = Number(p.config?.oversize_width_threshold)
  return Promise.resolve({
    data: {
      success: true,
      data: {
        auto_features:
          w > 5
            ? [{ name: '超宽', source: '推算', reason: `净窗宽 5.5 米 > 超宽阈值 ${w} 米` }]
            : [],
      },
    },
  })
}

beforeEach(() => {
  preview.mockReset()
  preview.mockImplementation(serveByThreshold)
})

describe('判据 1：初值取自租户配置，且两个口径各试算一次', () => {
  it('阈值输入框的初值 = 读面原文；两个口径列都渲染', async () => {
    render(<OversizeThresholdPreview config={CONFIG} />)
    await waitFor(() => expect(preview).toHaveBeenCalledTimes(2))
    expect(screen.getByTestId('preview-threshold-width')).toHaveValue('6')
    expect(screen.getByTestId('preview-threshold-height')).toHaveValue('4')
    // 竞态修复（issue #5218 CI 红）：`findByTestId` 只等**元素出现**，而本组件在数据回来前
    // 就已渲染 `preview-current` 容器（占位符 `—`）⇒ 必须等**文本**，不能只等元素。
    await waitFor(() => expect(screen.getByTestId('preview-current')).toHaveTextContent('超宽'))
  })
})

// issue #5218 #5：四个框旧形态都是 `type="number"` + `Number()` 往返 ⇒ "0." 中间态被吃掉。
describe('阈值/试算窗逐键录入（issue #5218 #5 红证）', () => {
  it('超宽阈值逐键 3 → . → 5 打出 "3.5"（中间态不丢）', async () => {
    render(<OversizeThresholdPreview config={CONFIG} />)
    await waitFor(() => expect(preview).toHaveBeenCalledTimes(2))
    const el = screen.getByTestId('preview-threshold-width') as HTMLInputElement

    fireEvent.change(el, { target: { value: '3' } })
    expect(el.value).toBe('3')
    fireEvent.change(el, { target: { value: '3.' } })
    // 红证（单点变异）：把本框改回 `type="number"` + `Number(...)` ⇒ 本断言收到 ''
    expect(el.value).toBe('3.')
    fireEvent.change(el, { target: { value: '3.5' } })
    expect(el.value).toBe('3.5')
    fireEvent.blur(el)
    expect(el.value).toBe('3.5')
  })
})

describe('判据 2：判定依据逐字来自服务端', () => {
  it('reason 原文上屏（本组件不拼文案）', async () => {
    render(<OversizeThresholdPreview config={CONFIG} />)
    // 竞态修复（同上，本条是 CI 实测红的那条）：期望内容**一字未改**，只把「等元素」改成「等文本」。
    await waitFor(() =>
      expect(screen.getByTestId('preview-current')).toHaveTextContent(
        '净窗宽 5.5 米 > 超宽阈值 6 米'
      )
    )
  })
})

describe('判据 3：改阈值 ⇒ 用新值重发试算（真的在预演）', () => {
  it('把超宽阈值改成 3 ⇒ 新一次请求带 3，且「调整后」变为不判', async () => {
    render(<OversizeThresholdPreview config={CONFIG} />)
    await waitFor(() => expect(preview).toHaveBeenCalledTimes(2))
    fireEvent.change(screen.getByTestId('preview-threshold-width'), { target: { value: '3' } })
    await waitFor(() =>
      expect(
        preview.mock.calls.some(
          (c) => (c[0] as { config?: Record<string, unknown> }).config?.oversize_width_threshold === 3
        )
      ).toBe(true)
    )
    await waitFor(() =>
      expect(screen.getByTestId('preview-adjusted')).toHaveTextContent('不判任何特征')
    )
    // 「按当前口径」不受影响（对照列还在）
    expect(screen.getByTestId('preview-current')).toHaveTextContent('超宽')
  })
})

describe('判据 4：服务端失败 ⇒ 可行动话术（不得当成「不判」）', () => {
  it('两次试算都失败 ⇒ 渲染错误提示，两列都不给结论', async () => {
    preview.mockRejectedValue(new Error('503'))
    render(<OversizeThresholdPreview config={CONFIG} />)
    const err = await screen.findByTestId('preview-error')
    expect(err).toHaveTextContent('试算失败')
    expect(screen.getByTestId('preview-current')).not.toHaveTextContent('不判任何特征')
    expect(screen.getByTestId('preview-adjusted')).not.toHaveTextContent('不判任何特征')
  })
})

describe('判据 5：本组件不保存（只读预演）', () => {
  it('读面未就绪（config 为 null）⇒ 一次都不调；且全程只调判定读面', async () => {
    render(<OversizeThresholdPreview config={null} />)
    await waitFor(() => expect(screen.getByTestId('threshold-preview')).toBeInTheDocument())
    expect(preview).not.toHaveBeenCalled()
  })
})
