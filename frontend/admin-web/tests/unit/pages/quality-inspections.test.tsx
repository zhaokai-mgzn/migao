// case_ids: UI-118, PG-087, PG-099
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

/**
 * 质检记录页（`/quality-inspections`，issue #7140 = #5652 的**商家面**）—— 大菜单「生产管理 ▸ 质检记录」。
 *
 * ## 2026-10-27 改判（issue #7945，用户逐字「质检单的这个区域都可以移除了，应该从手机端去判定」）
 *
 * 判定入口**只在手机端**（质检员扫码 → 做工判定）。本页只剩两个读面：指标 + 质检流水。
 * PC 的「待检成品帘 / 录入判定」区整体移除 —— 同一件判定两个录入口 = 第二份口径。
 *
 * ## 本文件钉住的事（每条能单独变红）
 *
 * ① **PC 不再读待检清单**：`qualityInspectionApi.targets` 零调用；页面没有 `quality-targets-card`、
 *    没有「录入判定」按钮、没有「待检」摘要行；
 * ② 指标面板：默认「本月」拉一次，首检合格率与样本量同屏；
 * ③ **读失败 ≠ 没有数据**：流水读失败 ⇒ 失败锚常驻、不画空态；空态只在真的 0 条时出现；
 * ④ 流水客户端分页：25 条 ⇒ 第 1 页 10 条，翻页看第 2 页（issue #7217）；
 * ⑤ 页面如实说明入口在手机端（用户改判的可见面）；
 * ⑥ **加载中不是白卡片**（issue #8041）：读流水期间卡片体渲染既有 `Loading` 原语
 *    （「加载中…」+ 转圈），既不是空白、也不提前画空态；读完 ⇒ 占位消失、换成真数据。
 */

const mockTargets = vi.fn()
const mockList = vi.fn()
const mockCreate = vi.fn()
const mockStats = vi.fn()

vi.mock('@/lib/api', () => ({
  qualityInspectionApi: {
    targets: (...args: unknown[]) => mockTargets(...args),
    list: (...args: unknown[]) => mockList(...args),
    create: (...args: unknown[]) => mockCreate(...args),
    stats: (...args: unknown[]) => mockStats(...args),
  },
}))

vi.mock('@/lib/permission', () => ({
  usePermission: () => ({
    has: () => true,
    permissions: ['production:inspect'],
    isAdmin: false,
  }),
}))

import QualityInspectionsPage from '@/app/(dashboard)/quality-inspections/page'

const passRecord = {
  id: 'qi-2',
  order_item_id: 'item-2',
  processing_order_id: 'po-1',
  position_name: '布艺遮光帘B 米白',
  result: 'pass',
  result_label: '合格',
  reason: null,
  inspector_name: '质检员小李',
  inspected_at: '2026-10-17T10:30:00+08:00',
}

/** 流水 N 条（issue #7217 客户端分页判据） */
function mockRecords(n: number) {
  const records = Array.from({ length: n }, (_, i) => ({
    ...passRecord,
    id: `qi-${i + 1}`,
    position_name: `成品帘 ${i + 1}`,
    inspected_at: `2026-10-17T10:${String(i).padStart(2, '0')}:00+08:00`,
  }))
  mockList.mockResolvedValue({ data: { data: records } })
  return records
}

describe('质检记录页（/quality-inspections）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockList.mockResolvedValue({ data: { data: [passRecord] } })
    mockStats.mockResolvedValue({
      data: {
        data: {
          window: { from: null, to: null, name: null },
          bucket: 'day',
          min_sample: 20,
          counts: { inspected: 2, first_pass: 1, current_pass: 1, rework: 1, scrap: 0 },
          rates: {
            first_pass_rate: 0.5,
            current_pass_rate: 0.5,
            rework_rate: 0.5,
            scrap_rate: 0,
          },
          trend: [],
          by_processing_order: [],
          by_product: [],
          by_inspector: [],
          backlog: { pending: 1, oldest_pending_hours: 2, approximate: true, approximate_from: 'processing_order.created_at' },
        },
      },
    })
  })

  it('① 🔴 PC 不再读待检清单：targets 零调用、无录入判定入口（2026-10-27 改判）', async () => {
    render(<QualityInspectionsPage />)

    await waitFor(() => expect(mockList).toHaveBeenCalled())
    expect(await screen.findByTestId('quality-records-card')).toBeInTheDocument()
    // 判定入口只在手机端 ⇒ PC 零调用待检读面、零录入按钮
    expect(mockTargets).not.toHaveBeenCalled()
    expect(screen.queryByTestId('quality-targets-card')).not.toBeInTheDocument()
    expect(screen.queryByTestId('quality-state-summary')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /录入判定|复检/ })).not.toBeInTheDocument()
  })

  it('② 指标面板：默认「本月」拉一次，首检合格率与样本量同屏（issue #7192）', async () => {
    render(<QualityInspectionsPage />)

    await waitFor(() => expect(mockStats).toHaveBeenCalledTimes(1))
    expect(mockStats.mock.calls[0][0]).toMatchObject({ bucket: 'day' })
    expect(await screen.findByTestId('quality-metric-first-pass')).toHaveTextContent('50.0%')
    expect(screen.getByTestId('quality-metric-sample')).toHaveTextContent('已检 2 件')
    expect(screen.getByTestId('quality-metrics-window-month')).toHaveAttribute('aria-pressed', 'true')
  })

  it('③ 流水读失败 ⇒ 失败锚常驻，不把「读不到」画成「还没有质检记录」', async () => {
    mockList.mockRejectedValue(new Error('500'))
    render(<QualityInspectionsPage />)

    await waitFor(() => expect(screen.getByTestId('quality-records-load-error')).toBeInTheDocument())
    expect(screen.getByTestId('quality-records-load-error')).toHaveAttribute('role', 'alert')
    expect(screen.queryByTestId('quality-records-empty')).not.toBeInTheDocument()
  })

  it('④ 真的没有流水 ⇒ 空态（与读失败是两句话）', async () => {
    mockList.mockResolvedValue({ data: { data: [] } })
    render(<QualityInspectionsPage />)

    await waitFor(() => expect(screen.getByTestId('quality-records-empty')).toBeInTheDocument())
    expect(screen.queryByTestId('quality-records-load-error')).not.toBeInTheDocument()
  })

  it('⑤ 流水客户端分页：25 条 ⇒ 第 1 页 10 条，翻页看第 2 页（issue #7217）', async () => {
    const user = userEvent.setup()
    mockRecords(25)
    render(<QualityInspectionsPage />)

    const card = await screen.findByTestId('quality-records-card')
    await waitFor(() => expect(within(card).getByTestId('quality-record-row-qi-1')).toBeInTheDocument())
    expect(within(card).queryByTestId('quality-record-row-qi-11')).not.toBeInTheDocument()
    expect(within(card).getByTestId('pagination-total')).toHaveTextContent('共 25 条记录')

    await user.click(within(card).getByRole('button', { name: '2' }))
    await waitFor(() => expect(within(card).getByTestId('quality-record-row-qi-11')).toBeInTheDocument())
    expect(within(card).queryByTestId('quality-record-row-qi-1')).not.toBeInTheDocument()
  })

  it('⑦ 读流水期间 ⇒ 卡片体有「加载中…」占位，不是白卡片（issue #8041）', async () => {
    // 手控 promise：把「加载中」这一帧钉住，不靠时序碰运气
    let resolveRecords: (value: unknown) => void = () => {}
    mockList.mockReturnValue(
      new Promise((resolve) => {
        resolveRecords = resolve
      }),
    )
    render(<QualityInspectionsPage />)

    const card = screen.getByTestId('quality-records-card')
    // ⚠️ 指标面板也有「加载中…」⇒ 必须限定在流水卡片内取，否则会取到两个
    const placeholder = within(card).getByTestId('quality-records-loading')
    expect(placeholder).toBeInTheDocument()
    expect(within(card).getByText('加载中…')).toBeInTheDocument()
    // 「卡片体不是空白」的机器读数：占位里既有转圈的图标、也有文案；且没有提前画空态 / 失败态
    // （⚠️ 图标在测试环境里由 lucide-react 的 mock 渲染成 `<span>`，故按 `.animate-spin` 取，不写死 `svg`）
    expect(placeholder.querySelector('.animate-spin')).not.toBeNull()
    expect(placeholder).toHaveTextContent('加载中…')
    expect(within(card).queryByTestId('quality-records-empty')).not.toBeInTheDocument()
    expect(within(card).queryByTestId('quality-records-load-error')).not.toBeInTheDocument()

    resolveRecords({ data: { data: [passRecord] } })
    await waitFor(() =>
      expect(within(card).getByTestId('quality-record-row-qi-2')).toBeInTheDocument(),
    )
    expect(within(card).queryByTestId('quality-records-loading')).not.toBeInTheDocument()
  })

  it('⑥ 页面如实说明判定入口在手机端（改判的可见面）', async () => {
    render(<QualityInspectionsPage />)

    expect(await screen.findByTestId('quality-inspections-page')).toHaveTextContent('手机端')
    expect(screen.getByTestId('quality-inspections-page')).toHaveTextContent('质检流水')
  })
})
