// case_ids: RPT-001
import { describe, expect, it, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import ReportsPage from '@/app/(dashboard)/reports/page'

/**
 * 报表中心页面（issue #7376 / #7377）—— 三条展示纪律的**前端**判据。
 *
 * 后端已经保证「空数据 totals 为 null」「未知分项不填 0」，但页面如果把 null 渲染成 ¥0.00，
 * 结论就完全反了（「本月毛利 0 元」vs「还没数据」）。所以这里逐个钉：
 * 空数据 ⇒ 「暂无数据」；未知 ⇒ 「未采集 / 未知」；合计不完整 ⇒ 明写缺哪几项。
 */
const reportApi = vi.hoisted(() => ({
  orderMargins: vi.fn(),
  inventoryAging: vi.fn(),
  staffPerformance: vi.fn(),
  qualityCost: vi.fn(),
}))

vi.mock('@/lib/api', () => ({ reportApi }))

const wrap = <T,>(data: T) => Promise.resolve({ data: { success: true, data } })

const emptyAll = () => {
  reportApi.orderMargins.mockImplementation(() =>
    wrap({ hasData: false, rows: [], totals: null, unknownCostOrders: 0 }),
  )
  reportApi.inventoryAging.mockImplementation(() =>
    wrap({ slowMovingDays: 90, hasData: false, rows: [], totals: null, undeterminedRows: 0 }),
  )
  reportApi.staffPerformance.mockImplementation(() =>
    wrap({ hasData: false, rows: [], totals: null, unattributedOrders: 0 }),
  )
  reportApi.qualityCost.mockImplementation(() =>
    wrap({ components: [], total: null, complete: true, unknownComponents: [] }),
  )
}

describe('报表中心页面', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('🔴 没有数据时显示「暂无数据」，**不显示 ¥0.00**（空数据 ≠ 0）', async () => {
    emptyAll()
    render(<ReportsPage />)

    await waitFor(() => expect(screen.getByTestId('reports-margin-empty')).toBeInTheDocument())
    expect(screen.getByTestId('reports-margin-empty').textContent).toContain('暂无数据')
    expect(screen.getByTestId('reports-inventory-empty')).toBeInTheDocument()
    expect(screen.getByTestId('reports-staff-empty')).toBeInTheDocument()
    // 空态下不该出现任何金额
    expect(screen.queryByTestId('reports-margin-revenue')).toBeNull()
    expect(document.body.textContent).not.toContain('¥0.00')
  })

  it('有数据时给出合计，并提示「成本未知的单未计入」', async () => {
    emptyAll()
    reportApi.orderMargins.mockImplementation(() =>
      wrap({
        hasData: true,
        rows: [],
        totals: { revenue: 1000, refunded: 100, fabricCost: 400, laborCost: 150, grossMargin: 350 },
        unknownCostOrders: 2,
      }),
    )
    render(<ReportsPage />)

    await waitFor(() => expect(screen.getByTestId('reports-margin-body')).toBeInTheDocument())
    expect(screen.getByTestId('reports-margin-gross').textContent).toContain('350.00')
    expect(screen.getByTestId('reports-margin-unknown').textContent).toContain('2 单成本未知')
  })

  it('🔴 质量成本未知分项显示「未采集 / 未知」，并标注合计不完整', async () => {
    emptyAll()
    reportApi.qualityCost.mockImplementation(() =>
      wrap({
        components: [
          { code: 'rework_labor', label: '返工工时', amount: 100, known: true, note: '', unknownItems: 0 },
          { code: 'scrap_material', label: '报废料', amount: null, known: false, note: '未采集', unknownItems: 0 },
        ],
        total: 100,
        complete: false,
        unknownComponents: ['scrap_material'],
      }),
    )
    render(<ReportsPage />)

    await waitFor(() => expect(screen.getByTestId('reports-quality-body')).toBeInTheDocument())
    expect(screen.getByTestId('reports-quality-body').textContent).toContain('未采集 / 未知')
    expect(screen.getByTestId('reports-quality-incomplete').textContent).toContain('不是完整质量成本')
    expect(screen.getByTestId('reports-quality-total').textContent).toContain('100.00')
  })

  it('加载失败 ⇒ 常驻失败态（不是空白页），且带可重试出口', async () => {
    reportApi.orderMargins.mockRejectedValue({ response: { status: 500, data: {} } })
    reportApi.inventoryAging.mockRejectedValue(new Error('x'))
    reportApi.staffPerformance.mockRejectedValue(new Error('x'))
    reportApi.qualityCost.mockRejectedValue(new Error('x'))
    render(<ReportsPage />)

    await waitFor(() => expect(screen.getByTestId('reports-load-error')).toBeInTheDocument())
    expect(screen.getByTestId('reports-load-error-retry')).toBeInTheDocument()
  })
})
