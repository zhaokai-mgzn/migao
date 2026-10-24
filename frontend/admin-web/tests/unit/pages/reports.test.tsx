// case_ids: RPT-001, RPT-004, RPT-007, RPT-008
import { describe, expect, it, beforeEach, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import ReportsPage, { presetRange } from '@/app/(dashboard)/reports/page'

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
  qualityCostBreakdown: vi.fn(),
}))

const warehouseApi = vi.hoisted(() => ({ list: vi.fn() }))
vi.mock('@/lib/api', () => ({ reportApi, warehouseApi }))

const wrap = <T,>(data: T) => Promise.resolve({ data: { success: true, data } })
// 仓库下拉的默认桩：两个仓（用例可覆盖）
warehouseApi.list.mockImplementation(() =>
  Promise.resolve({ data: { success: true, data: [
    { id: 1, code: 'WH01', name: '主仓' },
    { id: 2, code: 'WH02', name: '次仓' },
  ] } }),
)

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
  // 质量成本维度汇总（issue #7377 段 5）：空态 = hasData=false + totals=null
  reportApi.qualityCostBreakdown.mockImplementation((dim: string) =>
    wrap({
      dimension: dim, scope: dim === 'customer' ? 'rework_and_compensation_by_customer' : 'rework_by_processing_operation',
      startDate: null, endDate: null, hasData: false, rows: [], totals: null,
      unattributed: { rework: 0, reworkLines: 0, compensation: 0, compensationCount: 0, total: 0, reason: '' },
      notes: [],
    }),
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

  it('🔴 一张表慢不拖累其余四张：毛利未返回时，账龄已有读数（issue #7582）', async () => {
    emptyAll()
    // 订单毛利「永不返回」= 最慢的那张卡（改了 N+1 之后它也不该再锁住整页）
    reportApi.orderMargins.mockImplementation(() => new Promise(() => {}))
    reportApi.receivableAging.mockImplementation(() =>
      wrap({
        asOf: '2026-10-23',
        hasData: true,
        customerCount: 1,
        buckets: [{ bucket: 'NOT_DUE', label: '未到期', amount: 1200, orderCount: 1 }],
        customers: [],
        totals: { outstanding: 1200, overdue: 0, orderCount: 1 },
      }),
    )
    render(<ReportsPage />)

    // 断言的是「同时」：毛利仍显示加载中，账龄那张已经出了读数
    await waitFor(() => expect(screen.getByTestId('reports-aging-outstanding')).toBeInTheDocument())
    expect(screen.getByTestId('reports-margin-loading')).toBeInTheDocument()
    expect(screen.getByTestId('reports-aging-outstanding').textContent).toContain('1,200.00')
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

  it('🔴 维度汇总：默认按客户，切到按工序只重取这一块（不重打整页）', async () => {
    emptyAll()
    const calls: string[] = []
    reportApi.qualityCostBreakdown.mockImplementation((dim: string) => {
      calls.push(dim)
      return wrap({
        dimension: dim, scope: 'x', startDate: null, endDate: null, hasData: false, rows: [], totals: null,
        unattributed: { rework: 0, reworkLines: 0, compensation: 0, compensationCount: 0, total: 0, reason: '' },
        notes: [],
      })
    })
    render(<ReportsPage />)

    await waitFor(() => expect(calls).toEqual(['customer']))
    fireEvent.click(screen.getByTestId('reports-quality-dim-process'))
    await waitFor(() => expect(calls).toEqual(['customer', 'process']))
    // 商品维度（issue #7377 段 6，用户 2026-10-23 裁定「按比例」）
    fireEvent.click(screen.getByTestId('reports-quality-dim-product'))
    await waitFor(() => expect(calls).toEqual(['customer', 'process', 'product']))
    // 整页的五个端点**没有**被重取（只有维度这一块重取）
    expect(reportApi.orderMargins).toHaveBeenCalledTimes(1)
  })

  it('🔴 无法归属的金额必须露出来（恒等式：合计 = Σ行 + 无法归属）', async () => {
    emptyAll()
    reportApi.qualityCost.mockImplementation(() =>
      wrap({ components: [], total: null, complete: true, unknownComponents: [] }),
    )
    reportApi.qualityCostBreakdown.mockImplementation((dim: string) =>
      wrap({
        dimension: dim, scope: 'x', startDate: null, endDate: null, hasData: true,
        rows: [
          { key: 'cus:138', label: '张记布艺', rework: 60, reworkLines: 2, scrap: 40, scrapLines: 1,
            compensation: 120, compensationCount: 1, total: 220 },
        ],
        totals: { rework: 110, reworkLines: 3, scrap: 60, scrapLines: 2,
          compensation: 200, compensationCount: 2, total: 370 },
        unattributed: {
          rework: 50, reworkLines: 1, scrap: 20, scrapLines: 1, compensation: 80, compensationCount: 1, total: 150,
          reason: '这些返工报工关联不到加工单/订单，或退款流水关联不到订单',
        },
        notes: ['报废料不在本视图：本仓未采集'],
      }),
    )
    render(<ReportsPage />)

    await waitFor(() => expect(screen.getAllByTestId('reports-quality-breakdown-row')).toHaveLength(1))
    const row = screen.getAllByTestId('reports-quality-breakdown-row')[0]
    expect(row.textContent).toContain('张记布艺')
    expect(row.textContent).toContain('220.00')
    // 报废工时与返工**分列**展示（两个成因两种处置）
    expect(row.textContent).toContain('报废')
    expect(row.textContent).toContain('40.00')
    // 🔴 未归属单独一行、带原因、金额不许被并进任何行
    const unattributed = screen.getByTestId('reports-quality-breakdown-unattributed')
    expect(unattributed.textContent).toContain('150.00')
    expect(unattributed.textContent).toContain('无法归属')
    // note 现在把「工时已采集 / 料未采集」说清楚（issue #7377 段 8）
    expect(screen.getByTestId('reports-quality-breakdown-notes').textContent).toContain('报废')
    expect(screen.getByTestId('reports-quality-breakdown-notes').textContent).toContain('未采集')
  })

  it('维度汇总空态：写「暂无数据」，不画 ¥0.00', async () => {
    emptyAll()
    render(<ReportsPage />)
    await waitFor(() => expect(screen.getByTestId('reports-quality-breakdown-empty')).toBeInTheDocument())
    expect(screen.getByTestId('reports-quality-breakdown-empty').textContent).toContain('暂无数据')
    expect(document.body.textContent).not.toContain('¥0.00')
  })

  // ── 时间区间（issue #7376 段 6，case RPT-007）────────────────────────────────

  it('区间预设四档的日期都是「当天算出来」的（上月 31 天/30 天/闰年 2 月不许差一天）', () => {
    // 注入 today ⇒ 判据能钉死（不靠跑测那一天是哪天）
    expect(presetRange('thisMonth', new Date(2026, 9, 23))).toEqual({ from: '2026-10-01', to: '2026-10-23' })
    expect(presetRange('lastMonth', new Date(2026, 9, 23))).toEqual({ from: '2026-09-01', to: '2026-09-30' })
    // 跨年：1 月的「上月」是去年 12 月
    expect(presetRange('lastMonth', new Date(2026, 0, 5))).toEqual({ from: '2025-12-01', to: '2025-12-31' })
    // 闰年 2 月
    expect(presetRange('lastMonth', new Date(2024, 2, 10))).toEqual({ from: '2024-02-01', to: '2024-02-29' })
    expect(presetRange('last90', new Date(2026, 9, 23))).toEqual({ from: '2026-07-26', to: '2026-10-23' })
    expect(presetRange('all', new Date(2026, 9, 23))).toEqual({ from: '', to: '' })
  })

  it('🔴 只有「按下单日/报工日」统计的三张表吃区间——库存与账龄是此刻读数，不重取', async () => {
    emptyAll()
    render(<ReportsPage />)
    await waitFor(() => expect(reportApi.orderMargins).toHaveBeenCalledTimes(1))
    expect(reportApi.inventoryAging).toHaveBeenCalledTimes(1)
    expect(reportApi.receivableAging).toHaveBeenCalledTimes(1)

    fireEvent.change(screen.getByTestId('reports-filter-from'), { target: { value: '2026-10-01' } })
    fireEvent.change(screen.getByTestId('reports-filter-to'), { target: { value: '2026-10-31' } })

    await waitFor(() =>
      expect(reportApi.orderMargins).toHaveBeenLastCalledWith({ startDate: '2026-10-01', endDate: '2026-10-31' }),
    )
    expect(reportApi.staffPerformance).toHaveBeenLastCalledWith({ startDate: '2026-10-01', endDate: '2026-10-31' })
    expect(reportApi.qualityCost).toHaveBeenLastCalledWith({ startDate: '2026-10-01', endDate: '2026-10-31' })
    // 维度汇总也用同一区间（否则「贵在哪」和上面的合计对不上）
    expect(reportApi.qualityCostBreakdown).toHaveBeenLastCalledWith('customer', {
      startDate: '2026-10-01',
      endDate: '2026-10-31',
    })
    // 🔴 此刻读数两张表**没有**被重取（传日期给它们只会是「传了但没用」的假筛选）
    expect(reportApi.inventoryAging).toHaveBeenCalledTimes(1)
    expect(reportApi.receivableAging).toHaveBeenCalledTimes(1)
  })

  it('点「本月」⇒ 输入框被填成当月 1 号 ~ 今天，并按该区间重取', async () => {
    emptyAll()
    render(<ReportsPage />)
    await waitFor(() => expect(reportApi.orderMargins).toHaveBeenCalledTimes(1))

    fireEvent.click(screen.getByTestId('reports-filter-this-month'))
    const expected = presetRange('thisMonth')

    await waitFor(() =>
      expect(reportApi.orderMargins).toHaveBeenLastCalledWith({
        startDate: expected.from,
        endDate: expected.to,
      }),
    )
    expect((screen.getByTestId('reports-filter-from') as HTMLInputElement).value).toBe(expected.from)
    expect((screen.getByTestId('reports-filter-to') as HTMLInputElement).value).toBe(expected.to)
  })

  it('点「全部」⇒ 清空区间，请求不带日期参数（不是传两个空串）', async () => {
    emptyAll()
    render(<ReportsPage />)
    await waitFor(() => expect(reportApi.orderMargins).toHaveBeenCalledTimes(1))

    fireEvent.change(screen.getByTestId('reports-filter-from'), { target: { value: '2026-10-01' } })
    await waitFor(() => expect(reportApi.orderMargins).toHaveBeenLastCalledWith({ startDate: '2026-10-01' }))

    fireEvent.click(screen.getByTestId('reports-filter-all'))
    await waitFor(() => expect(reportApi.orderMargins).toHaveBeenLastCalledWith({}))
  })

  it('🔴 页面上写明「哪些表吃区间」——不写就会出现「我筛了 10 月，滞销怎么没变」', async () => {
    emptyAll()
    render(<ReportsPage />)
    await waitFor(() => expect(screen.getByTestId('reports-filter-note')).toBeInTheDocument())
    const note = screen.getByTestId('reports-filter-note').textContent || ''
    expect(note).toContain('订单毛利')
    expect(note).toContain('返工报工日')
    expect(note).toContain('不受区间影响')
    // 文案不许留字面 markdown 星号（会逐字上屏）
    expect(note).not.toContain('**')
  })

  it('🔴 库存滞销按仓库筛：换仓只重取这一张，且带 warehouseCode（其余表不动）', async () => {
    reportApi.inventoryAging.mockImplementation((params?: { warehouseCode?: string }) =>
      wrap({ slowMovingDays: 90, hasData: true,
        totals: { onHand: 10, slowMovingOnHand: params?.warehouseCode === 'WH02' ? 4 : 10, slowMovingBatches: 1 },
        undeterminedRows: 0,
        rows: [{ batchNo: 'PC-' + (params?.warehouseCode || 'ALL'), skuCode: 'SKU-A', warehouse: '主仓',
          onHand: 10, lastMovementDate: '2026-06-01', daysSince: 120, slowMoving: true }] }))

    render(<ReportsPage />)
    await waitFor(() => expect(screen.getByTestId('reports-inventory-warehouse')).toBeInTheDocument())

    const marginsBefore = reportApi.orderMargins.mock.calls.length
    fireEvent.change(screen.getByTestId('reports-inventory-warehouse'), { target: { value: 'WH02' } })

    // 只重打滞销这一张：带 warehouseCode，而且**不动**毛利那张
    await waitFor(() =>
      expect(reportApi.inventoryAging).toHaveBeenLastCalledWith({ warehouseCode: 'WH02' }),
    )
    expect(reportApi.orderMargins.mock.calls.length).toBe(marginsBefore)
    // 下拉的选项来自仓库列表（全部仓库 + 两个仓）
    expect(screen.getByTestId('reports-inventory-warehouse').textContent).toContain('全部仓库')
    expect(screen.getByTestId('reports-inventory-warehouse').textContent).toContain('主仓')
  })
})
