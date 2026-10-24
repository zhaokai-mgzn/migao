// case_ids: PG-087
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

/**
 * 质检**指标**面板（P0 + P1，issue #7192）—— `/quality-inspections` 页顶部。
 *
 * ## 本文件钉住的事（每条能单独变红）
 *
 * ① 🔴 **0 样本 ⇒ 「—」不是 0%**：服务端给 `null` ⇒ 界面必须显示「—」（两句语义不同）；
 * ② **首检合格率是主位**：有值 ⇒ `82.5%`，并给出已检件数；
 * ③ **样本偏少要标**：已检 < `min_sample` ⇒ 明说「样本偏少，率仅供参考」（不让人拿 1/1 当质量结论）；
 * ④ **待检时长是近似**：选项文案必须带「近似」并说明起算点（无「进入待检」时间戳，不做假精确）；
 * ⑤ **时间窗可切**：点「今日」⇒ 回调拿到 `today`（窗口换算由页面负责，本组件不重算）；
 * ⑥ **趋势/分组**：趋势画点、空态可辨；分组 tab 切换换数据源；
 * ⑦ **读失败 ≠ 没数据**：错误态给「加载失败」+ 重试回调。
 */

const mockStats = vi.fn()

vi.mock('@/lib/api', () => ({
  qualityInspectionApi: {
    stats: (...args: unknown[]) => mockStats(...args),
  },
}))

import QualityMetricsPanel from '@/components/production/QualityMetricsPanel'
import type { QualityStats } from '@/types'

function stats(overrides: Partial<QualityStats> = {}): QualityStats {
  return {
    window: { from: '2026-10-01', to: '2026-11-01', name: null },
    bucket: 'day',
    min_sample: 20,
    counts: { inspected: 40, first_pass: 33, current_pass: 36, rework: 3, scrap: 1 },
    rates: {
      first_pass_rate: 0.825,
      current_pass_rate: 0.9,
      rework_rate: 0.075,
      scrap_rate: 0.025,
    },
    trend: [
      { bucket: '2026-10-16', inspected: 20, first_pass: 17, first_pass_rate: 0.85 },
      { bucket: '2026-10-17', inspected: 20, first_pass: 16, first_pass_rate: 0.8 },
    ],
    by_processing_order: [
      { name: 'JG-20261017-0001', inspected: 12, first_pass: 10, first_pass_rate: 0.8333 },
    ],
    by_product: [
      { name: '布艺遮光帘A · 米白', inspected: 8, first_pass: 6, first_pass_rate: 0.75 },
    ],
    by_inspector: [{ name: '质检员小李', inspected: 15, first_pass: 13, first_pass_rate: 0.8667 }],
    backlog: {
      pending: 2,
      oldest_pending_hours: 6.5,
      approximate: true,
      approximate_from: 'processing_order.created_at',
    },
    ...overrides,
  }
}

function renderPanel(overrides: Partial<React.ComponentProps<typeof QualityMetricsPanel>> = {}) {
  const props = {
    stats: stats(),
    loading: false,
    error: '',
    window: 'month' as const,
    onWindowChange: vi.fn(),
    onRetry: vi.fn(),
    ...overrides,
  }
  render(<QualityMetricsPanel {...props} />)
  return props
}

describe('质检指标面板（issue #7192）', () => {
  it('① 0 样本 ⇒ 显示「—」（不是 0%）', () => {
    renderPanel({
      stats: stats({
        counts: { inspected: 0, first_pass: 0, current_pass: 0, rework: 0, scrap: 0 },
        rates: {
          first_pass_rate: null,
          current_pass_rate: null,
          rework_rate: null,
          scrap_rate: null,
        },
      }),
    })

    expect(screen.getByTestId('quality-metric-first-pass')).toHaveTextContent('—')
    expect(screen.getByTestId('quality-metric-first-pass')).not.toHaveTextContent('0.0%')
    expect(screen.getByTestId('quality-metric-current-pass')).toHaveTextContent('—')
  })

  it('② 有值 ⇒ 首检合格率 82.5% + 已检 40 件', () => {
    renderPanel()

    expect(screen.getByTestId('quality-metric-first-pass')).toHaveTextContent('82.5%')
    expect(screen.getByTestId('quality-metric-sample')).toHaveTextContent('已检 40 件')
    expect(screen.getByTestId('quality-metric-rework')).toHaveTextContent('7.5%')
    expect(screen.getByTestId('quality-metric-scrap')).toHaveTextContent('2.5%')
  })

  it('③ 样本偏少（已检 < min_sample）⇒ 明说「仅供参考」', () => {
    renderPanel({
      stats: stats({
        counts: { inspected: 3, first_pass: 2, current_pass: 2, rework: 1, scrap: 0 },
        rates: {
          first_pass_rate: 0.6667,
          current_pass_rate: 0.6667,
          rework_rate: 0.3333,
          scrap_rate: 0,
        },
      }),
    })

    expect(screen.getByTestId('quality-metric-sample')).toHaveTextContent('样本偏少')
  })

  it('④ 待检积压：件数 + 近似的最久待检（必须写「近似」）', () => {
    renderPanel()

    const backlog = screen.getByTestId('quality-backlog')
    expect(backlog).toHaveTextContent('待检积压 2 件')
    expect(backlog).toHaveTextContent('6.5 小时')
    expect(backlog).toHaveTextContent('近似')
  })

  it('⑤ 时间窗：点「今日」⇒ 回调 today（组件不自己换算窗口）', async () => {
    const user = userEvent.setup()
    const props = renderPanel()

    await user.click(screen.getByTestId('quality-metrics-window-today'))
    expect(props.onWindowChange).toHaveBeenCalledWith('today')
  })

  it('⑥ 趋势画点 + 分组 tab 切换数据源', async () => {
    const user = userEvent.setup()
    renderPanel()

    expect(screen.getAllByTestId('quality-trend-point')).toHaveLength(2)
    expect(screen.getByTestId('quality-groups')).toHaveTextContent('JG-20261017-0001')

    await user.click(screen.getByTestId('quality-group-tab-by_product'))
    expect(screen.getByTestId('quality-groups')).toHaveTextContent('布艺遮光帘A · 米白')

    await user.click(screen.getByTestId('quality-group-tab-by_inspector'))
    expect(screen.getByTestId('quality-groups')).toHaveTextContent('质检员小李')
  })

  it('⑦ 读失败 ⇒ 失败文案 + 重试（不是「没有数据」）', async () => {
    const user = userEvent.setup()
    const props = renderPanel({ stats: null, error: '指标加载失败 —— 这不是「没有数据」，是这次没读到。' })

    expect(screen.getByTestId('quality-metrics-error')).toHaveTextContent('加载失败')
    await user.click(screen.getByRole('button', { name: '重新加载' }))
    expect(props.onRetry).toHaveBeenCalled()
  })
})
