// case_ids: STK-002, APV-002
import { describe, expect, it, beforeEach, vi } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import StocktakesPage from '@/app/(dashboard)/stocktakes/page'

/**
 * 盘点单页面（issue #7373，P1-1 段 2 的商家面）—— 三条纪律的前端判据。
 *
 * 后端已保证「有差异必须有已通过的盘点差异审批」「差异由服务端算」，
 * 前端要守住的是**别把「还没数」画成 0**：账面/实盘/差异三列里，
 * 一个假的 0 会让商家以为账实相符。
 */
const stocktakeApi = vi.hoisted(() => ({
  list: vi.fn(),
  detail: vi.fn(),
  open: vi.fn(),
  count: vi.fn(),
  complete: vi.fn(),
  cancel: vi.fn(),
}))
const warehouseApi = vi.hoisted(() => ({ list: vi.fn() }))

const approvalApi = vi.hoisted(() => ({ submit: vi.fn() }))
vi.mock('@/lib/api', () => ({ stocktakeApi, warehouseApi, approvalApi }))
vi.mock('@/lib/permission', () => ({
  usePermission: () => ({ has: () => true, permissions: [], isAdmin: true }),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const wrap = <T,>(data: T) => Promise.resolve({ data: { success: true, data } })

const WAREHOUSES = [
  { id: 7, code: 'WH01', name: '主仓' },
  { id: 9, code: 'WH02', name: '加工仓' },
]

const HEAD = {
  id: 'st1',
  stocktakeNo: 'PD202610220001',
  warehouseId: 7,
  warehouseCode: null,
  status: 'counting' as const,
  note: null,
  completedAt: null,
  items: [],
}

/** 两个批次：一个已数（账面 10 → 实盘 8），一个**还没数**。 */
const PARTIAL = {
  ...HEAD,
  items: [
    { batchId: 11, batchNo: 'PC-20261022-0001', skuCode: 'SKU-A', bookQty: 10, countedQty: 8, diffQty: -2 },
    { batchId: 12, batchNo: 'PC-20261022-0002', skuCode: 'SKU-B', bookQty: 5, countedQty: null, diffQty: null },
  ],
}

/** 全部数完：差异 +1 + (−2) = −1。 */
const COUNTED = {
  ...HEAD,
  items: [
    { batchId: 11, batchNo: 'PC-20261022-0001', skuCode: 'SKU-A', bookQty: 10, countedQty: 9, diffQty: -1 },
    { batchId: 12, batchNo: 'PC-20261022-0002', skuCode: 'SKU-B', bookQty: 5, countedQty: 6, diffQty: 1 },
  ],
}

async function openDetail(row = 'st1') {
  render(<StocktakesPage />)
  await screen.findByTestId('stocktakes-table')
  fireEvent.click(screen.getByTestId(`stocktake-open-detail-${row}`))
  await screen.findByTestId('stocktake-lines')
}

describe('盘点单页面', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    warehouseApi.list.mockImplementation(() => wrap(WAREHOUSES))
    stocktakeApi.list.mockImplementation(() => wrap([HEAD]))
    stocktakeApi.detail.mockImplementation(() => wrap(PARTIAL))
    stocktakeApi.open.mockImplementation(() => wrap(HEAD))
    stocktakeApi.count.mockImplementation(() => wrap(PARTIAL))
    stocktakeApi.complete.mockImplementation(() => wrap({ ...COUNTED, status: 'completed' }))
    stocktakeApi.cancel.mockImplementation(() => wrap({ ...COUNTED, status: 'cancelled' }))
  })

  it('没有盘点单时给空态（不是空白表格）', async () => {
    stocktakeApi.list.mockImplementation(() => wrap([]))
    render(<StocktakesPage />)

    await waitFor(() => expect(screen.getByTestId('stocktakes-empty')).toBeInTheDocument())
    expect(screen.queryByTestId('stocktakes-table')).toBeNull()
    expect(screen.getByTestId('stocktakes-empty').textContent).toContain('还没有盘点单')
  })

  // issue #8056：加载态 = 通用表格骨架（#8036 / #8048 已验收口径），不再是裸「加载中…」+ 空白表体。
  it('加载中：渲染 table-skeleton，且不出现裸「加载中…」文案（#8056）', async () => {
    stocktakeApi.list.mockReturnValue(new Promise(() => {}))
    render(<StocktakesPage />)
    expect(await screen.findByTestId('table-skeleton')).toBeInTheDocument()
    // 红证：把加载分支改回裸文案 ⇒ 本条红
    expect(screen.queryByText(/加载中/)).not.toBeInTheDocument()
  })

  it('列表逐列照服务端值：单号 / 仓库名 / 状态（仓名按 id 查，不信 null 的 warehouseCode）', async () => {
    render(<StocktakesPage />)

    await screen.findByTestId('stocktakes-table')
    const row = screen.getByTestId('stocktake-row-st1')
    expect(row.textContent).toContain('PD202610220001')
    // 只显示仓名（issue #7616）：编码是内部键，不许拼在商家面前（「主仓（WH01）」那种形态）
    expect(row.textContent).toContain('主仓')
    expect(row.textContent).not.toContain('WH01')
    expect(screen.getByTestId('stocktake-status-st1').textContent).toBe('盘点中')
  })

  it('🔴 明细：账面 / 实盘 / 差异逐格；**没数的行写「未数」，不写 0**', async () => {
    await openDetail()

    // 列名说清口径（#7618：账面量曾经是"原始入库量"，改后是"剩余米数"）
    expect(screen.getByText('账面剩余')).toBeInTheDocument()
    expect(screen.getByTestId('stocktake-book-basis').textContent).toContain('入库米数 − 已派工消耗')

    const counted = screen.getByTestId('stocktake-line-11')
    expect(counted.textContent).toContain('PC-20261022-0001')
    expect(counted.textContent).toContain('SKU-A')
    expect(counted.textContent).toContain('10')
    expect(screen.getByTestId('stocktake-diff-11').textContent).toBe('-2')

    const uncounted = screen.getByTestId('stocktake-line-12')
    expect(uncounted.textContent).toContain('未数')
    expect(screen.getByTestId('stocktake-diff-12').textContent).toBe('未数')
    // 输入框留空（不是预填 0 —— 预填 0 等于替商家做了「数出来是 0」的结论）
    expect((screen.getByTestId('stocktake-count-input-12') as HTMLInputElement).value).toBe('')
  })

  it('🔴 差异合计：还有批次没数 ⇒ 「待录入」，**不给一个看起来已对账的合计**', async () => {
    await openDetail()

    const total = screen.getByTestId('stocktake-total-diff')
    expect(total.textContent).toContain('待录入')
    expect(total.textContent).toContain('还有 1 个批次没数')
    expect(total.textContent).not.toContain('差异合计')
  })

  it('差异合计：全部数完才给数（+1 与 −1 相抵 = 0 也要照实显示，不隐藏）', async () => {
    stocktakeApi.detail.mockImplementation(() => wrap(COUNTED))
    await openDetail()

    expect(screen.getByTestId('stocktake-total-diff').textContent).toContain('差异合计')
    expect(screen.getByTestId('stocktake-total-diff').textContent).toContain('0')
  })

  it('出盘点任务：不选仓 ⇒ 拦住且不打接口；选了仓 ⇒ 带上 warehouseId', async () => {
    render(<StocktakesPage />)
    await screen.findByTestId('stocktakes-table')

    // 先打开「出盘点任务」弹窗，再点提交（未选仓 ⇒ 页面自己拦住，不打接口）
    fireEvent.click(screen.getByTestId('stocktake-open'))
    fireEvent.click(screen.getByTestId('stocktake-open-submit'))
    await waitFor(() => expect(screen.getByTestId('stocktake-open-error')).toBeInTheDocument())
    expect(screen.getByTestId('stocktake-open-error').textContent).toContain('先选一个仓')
    expect(stocktakeApi.open).not.toHaveBeenCalled()

    fireEvent.change(screen.getByTestId('stocktake-form-warehouse'), { target: { value: '9' } })
    fireEvent.click(screen.getByTestId('stocktake-open-submit'))
    await waitFor(() => expect(stocktakeApi.open).toHaveBeenCalledWith(9, undefined))
  })

  it('出任务下拉：仓库只显示仓名，不拼编码（issue #7616，用户：「直接叫主仓即可，不要带括号和 main」）', async () => {
    render(<StocktakesPage />)
    await screen.findByTestId('stocktakes-table')
    fireEvent.click(screen.getByTestId('stocktake-open'))

    expect((await screen.findByRole('option', { name: '主仓' })).textContent).toBe('主仓')
    expect(screen.getByRole('option', { name: '加工仓' }).textContent).toBe('加工仓')
    // 变异即红：把编码拼回去（「主仓（WH01）」）⇒ 这两条查询都命中不到纯仓名
    expect(screen.queryByRole('option', { name: /WH\d/ })).toBeNull()
  })

  it('🔴 录实盘：0 可以提交（盘空是真实结果）；两位小数/负数在前端拦下且不打接口', async () => {
    await openDetail()

    const input = screen.getByTestId('stocktake-count-input-12') as HTMLInputElement
    fireEvent.change(input, { target: { value: '8.55' } })
    fireEvent.click(screen.getByTestId('stocktake-save-counts'))
    await waitFor(() => expect(screen.getByTestId('stocktake-form-error')).toBeInTheDocument())
    expect(screen.getByTestId('stocktake-form-error').textContent).toContain('最多 1 位小数')
    expect(stocktakeApi.count).not.toHaveBeenCalled()

    fireEvent.change(input, { target: { value: '0' } })
    fireEvent.click(screen.getByTestId('stocktake-save-counts'))
    await waitFor(() => expect(stocktakeApi.count).toHaveBeenCalled())
    // 只提交**这一行**（已数的 11 号行没改，但它的输入框有值 ⇒ 一起提交，这是「保存当前录入」的口径）
    expect(stocktakeApi.count.mock.calls[0][1]).toMatchObject({ 12: 0 })
  })

  it('🔴 完成被服务端拒绝（有差异但没审批）⇒ 原文显示，不吞成「操作失败」', async () => {
    stocktakeApi.complete.mockImplementation(() =>
      Promise.reject({
        response: {
          status: 400,
          data: { error: { message: '盘点有差异（合计 -1），必须先有已通过的「盘点差异」审批' } },
        },
      }),
    )
    await openDetail()

    fireEvent.click(screen.getByTestId('stocktake-complete'))
    await waitFor(() => expect(screen.getByTestId('stocktake-confirm-submit')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('stocktake-confirm-submit'))

    await waitFor(() => expect(screen.getByTestId('stocktake-form-error')).toBeInTheDocument())
    expect(screen.getByTestId('stocktake-form-error').textContent).toContain('「盘点差异」审批')
  })

  it('🔴 完成被拒（缺盘点差异审批）⇒ 就地预填申请：ref = 盘点单号、金额 = 差异合计', async () => {
    stocktakeApi.list.mockImplementation(() => wrap([HEAD]))
    // 全部数完（差异合计 = -2）：没数完时金额不预填、提示「先补齐实盘」——那是另一条口径
    stocktakeApi.detail.mockImplementation(() =>
      wrap({
        ...HEAD,
        items: [
          { batchId: 11, batchNo: 'PC-A', skuCode: 'SKU-A', bookQty: 10, countedQty: 8, diffQty: -2 },
          { batchId: 12, batchNo: 'PC-B', skuCode: 'SKU-B', bookQty: 5, countedQty: 5, diffQty: 0 },
        ],
      }),
    )
    stocktakeApi.complete.mockRejectedValue({
      response: {
        status: 400,
        data: { message: '盘点有差异（合计 2），必须先有已通过的「盘点差异」审批：objectType=stocktake_diff，objectRef=PD202610220001' },
      },
    })
    approvalApi.submit.mockResolvedValue({ data: { success: true, data: { id: 'ap-1' } } })
    render(<StocktakesPage />)

    fireEvent.click(await screen.findByTestId('stocktake-open-detail-st1'))
    fireEvent.click(await screen.findByTestId('stocktake-complete'))
    fireEvent.click(await screen.findByTestId('stocktake-confirm-submit'))

    // 服务端原话照旧上屏（不吞成「完成盘点失败」）
    await waitFor(() =>
      expect(screen.getByTestId('stocktake-form-error').textContent).toContain('盘点差异'),
    )
    // 申请入口自动摆出来：对象 = 盘点单号，金额预填差异合计（这里 -2 的绝对值）
    const target = await screen.findByTestId('approval-request-target')
    expect(target.textContent).toContain('PD202610220001')
    expect((screen.getByTestId('approval-request-amount') as HTMLInputElement).value).toBe('2')

    fireEvent.change(screen.getByTestId('approval-request-reason'), { target: { value: '帘头受潮报废' } })
    fireEvent.click(screen.getByTestId('approval-request-submit'))
    await waitFor(() =>
      expect(approvalApi.submit).toHaveBeenCalledWith(
        expect.objectContaining({
          objectType: 'stocktake_diff',
          objectRef: 'PD202610220001',
          amount: 2,
          reason: '帘头受潮报废',
        }),
      ),
    )
  })
})
