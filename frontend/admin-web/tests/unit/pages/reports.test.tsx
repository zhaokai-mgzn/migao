// case_ids: RPT-001
import { describe, expect, it, beforeEach, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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
  receivableAging: vi.fn(),
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
  // 账龄报表（issue #7376 段 5）：空态 = hasData=false + totals=null（与其余四张同口径）
  reportApi.receivableAging.mockImplementation(() =>
    wrap({ asOf: '2026-10-23', hasData: false, customerCount: 0, buckets: [], customers: [], totals: null }),
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
    expect(screen.getByTestId('reports-aging-empty').textContent).toContain('暂无数据')
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
    const notice = screen.getByTestId('reports-quality-incomplete').textContent || ''
    expect(notice).toContain('不是完整质量成本')
    // 🔴 不摆内部码（`scrap_material` 这种商家读不懂）：未知项用中文名
    expect(notice).toContain('报废料')
    expect(notice).not.toContain('scrap_material')
    expect(screen.getByTestId('reports-quality-total').textContent).toContain('100.00')
  })

  it('🔴 账龄：有欠款时给合计与客户行，逾期单独标出', async () => {
    emptyAll()
    reportApi.receivableAging.mockImplementation(() =>
      wrap({
        asOf: '2026-10-23',
        hasData: true,
        customerCount: 2,
        buckets: [
          { bucket: 'NOT_DUE', label: '未到期', amount: 1800, orderCount: 3 },
          { bucket: 'DAYS_1_30', label: '逾期 1-30 天', amount: 200, orderCount: 1 },
        ],
        customers: [
          {
            customerName: '张记布艺', customerPhone: '13800000001', paymentTermsDays: 30,
            total: 1200, overdue: 200,
            buckets: [
              { bucket: 'NOT_DUE', label: '未到期', amount: 1000, orderCount: 1 },
              { bucket: 'DAYS_1_30', label: '逾期 1-30 天', amount: 200, orderCount: 1 },
            ],
          },
          {
            customerName: '李家窗帘', customerPhone: '13800000002', paymentTermsDays: 30,
            total: 800, overdue: 0,
            buckets: [{ bucket: 'NOT_DUE', label: '未到期', amount: 800, orderCount: 2 }],
          },
        ],
        totals: { outstanding: 2000, overdue: 200, orderCount: 4 },
      }),
    )
    render(<ReportsPage />)

    await waitFor(() => expect(screen.getByTestId('reports-aging-body')).toBeInTheDocument())
    expect(screen.getByTestId('reports-aging-outstanding').textContent).toContain('2,000.00')
    expect(screen.getByTestId('reports-aging-overdue').textContent).toContain('200.00')
    expect(screen.getByTestId('reports-aging-counts').textContent).toContain('2 家客户')
    expect(screen.getByTestId('reports-aging-counts').textContent).toContain('4 张单')
    // 五档是这张表的正文（合计只回答「欠多少」，分档才回答「欠了多久」）
    expect(screen.getByTestId('reports-aging-bucket-NOT_DUE').textContent).toContain('未到期')
    expect(screen.getByTestId('reports-aging-bucket-NOT_DUE').textContent).toContain('1,800.00')
    expect(screen.getByTestId('reports-aging-bucket-DAYS_1_30').textContent).toContain('逾期 1-30 天')
    expect(screen.getByTestId('reports-aging-bucket-DAYS_1_30').textContent).toContain('200.00')
    const rows = screen.getAllByTestId('reports-aging-customer')
    expect(rows).toHaveLength(2)
    expect(rows[0].textContent).toContain('张记布艺')
    // 逾期的客户行必须标出来（总额里读不出「谁欠得久」）
    expect(rows[0].textContent).toContain('逾期')
    expect(rows[1].textContent).not.toContain('逾期')
  })

  it('导出 CSV：把**已加载**的账龄读数写进文件（不额外请求，缺值留空）', async () => {
    emptyAll()
    reportApi.receivableAging.mockImplementation(() =>
      wrap({
        asOf: '2026-10-23',
        hasData: true,
        customerCount: 1,
        buckets: [{ bucket: 'NOT_DUE', label: '未到期', amount: 1200, orderCount: 1 }],
        customers: [
          {
            customerName: '张记布艺', customerPhone: '13800000001', paymentTermsDays: 30,
            total: 1200, overdue: null,
            buckets: [
              { bucket: 'NOT_DUE', label: '未到期', amount: 1200, orderCount: 1 },
              { bucket: 'DAYS_1_30', label: '逾期 1-30 天', amount: 0, orderCount: 0 },
            ],
          },
        ],
        totals: { outstanding: 1200, overdue: 0, orderCount: 1 },
      }),
    )
    const blobs: Blob[] = []
    const createObjectURL = vi.fn((blob: Blob) => {
      blobs.push(blob)
      return 'blob:mock'
    })
    const revokeObjectURL = vi.fn()
    Object.assign(URL, { createObjectURL, revokeObjectURL })
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    render(<ReportsPage />)
    await waitFor(() => expect(screen.getByTestId('reports-aging-body')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('reports-aging-export'))

    expect(createObjectURL).toHaveBeenCalledTimes(1)
    const text = await blobs[0].text()
    // ⚠️ jsdom 的 `Blob.text()` 会吃掉 UTF-8 BOM ⇒ BOM 由 `csv.test.ts` 直接对 `toCsv()` 断言
    expect(text).toContain('客户,账期(天),应收,逾期,未到期,逾期1-30')
    expect(text).toContain('张记布艺,30,1200,,1200,0')      // 逾期缺值留空（不是 0）
    expect(clickSpy).toHaveBeenCalled()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock')
    clickSpy.mockRestore()
  })

  it('加载失败 ⇒ 常驻失败态（不是空白页），且带可重试出口', async () => {
    reportApi.orderMargins.mockRejectedValue({ response: { status: 500, data: {} } })
    reportApi.inventoryAging.mockRejectedValue(new Error('x'))
    reportApi.staffPerformance.mockRejectedValue(new Error('x'))
    reportApi.qualityCost.mockRejectedValue(new Error('x'))
    reportApi.receivableAging.mockRejectedValue(new Error('x'))
    render(<ReportsPage />)

    await waitFor(() => expect(screen.getByTestId('reports-load-error')).toBeInTheDocument())
    expect(screen.getByTestId('reports-load-error-retry')).toBeInTheDocument()
  })
})
