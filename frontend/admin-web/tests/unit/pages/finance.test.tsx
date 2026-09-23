import React from 'react';
// case_ids: FN-001, FN-002, FN-003, FN-004, UI-055
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// Mock API
const mockGetSummary = vi.fn()
const mockGetTransactions = vi.fn()
const mockGetReconciliation = vi.fn()
const mockCreateTransaction = vi.fn()

vi.mock('@/lib/api', () => ({
  financeApi: {
    getSummary: (...args: any[]) => mockGetSummary(...args),
    getTransactions: (...args: any[]) => mockGetTransactions(...args),
    getReconciliation: (...args: any[]) => mockGetReconciliation(...args),
    createTransaction: (...args: any[]) => mockCreateTransaction(...args),
  },
}))

// Mock lucide-react
vi.mock('lucide-react', () => {
  const stub = (name: string) => (props: any) => <span data-testid={`icon-${name}`} {...props} />
  return {
    Plus: stub('plus'),
    Search: stub('search'),
    RotateCcw: stub('reset'),
    Wallet: stub('wallet'),
    ArrowDownCircle: stub('arrow-down'),
    ArrowUpCircle: stub('arrow-up'),
    TrendingUp: stub('trending'),
  }
})

// Mock types
vi.mock('@/types', () => ({
  FinanceTransactionTypeLabels: { income: '收款', refund: '退款' },
  FinancePaymentMethodLabels: {
    wechat: '微信',
    alipay: '支付宝',
    bank_transfer: '银行转账',
    cash: '现金',
    other: '其他',
  },
  FinanceTransactionStatusLabels: {
    pending: '待处理',
    success: '成功',
    failed: '失败',
  },
}))

// Mock UI components
vi.mock('@/components/ui', () => ({
  Pagination: ({ current, total }: any) => (
    <div data-testid="pagination">第 {current} 页, 共 {total} 条</div>
  ),
  Modal: ({ open, title, children, footer }: any) =>
    open ? (
      <div data-testid="modal" role="dialog">
        <h2>{title}</h2>
        {children}
        <div data-testid="modal-footer">{footer}</div>
      </div>
    ) : null,
  Button: ({ children, onClick, ...props }: any) => <button onClick={onClick} {...props}>{children}</button>,
  Input: ({ label, value, onChange, onKeyDown, ...props }: any) => (
    <div>
      <label htmlFor={label}>{label}</label>
      <input id={label} value={value} onChange={onChange} onKeyDown={onKeyDown} {...props} />
    </div>
  ),
  Select: ({ label, options, value, onChange }: any) => (
    <div>
      <label>{label}</label>
      <select value={value} onChange={onChange}>
        {options?.map((o: any) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  ),
  Badge: ({ children, variant }: any) => <span data-testid="badge" data-variant={variant}>{children}</span>,
}))

// ── 冻结墙钟（issue #4761 第 2 条：**模块级** `currentPeriod`）────────────────
// 病根（比 #1/#3 更隐蔽）：本文件的 `currentPeriod` 是**模块级求值** —— 它在
// `import FinancePage from ...` 的**那一刻**定格；而被测页面 `src/app/(dashboard)/finance/page.tsx`
// 也有一份**同形的模块级** `CURRENT_PERIOD = getCurrentPeriod()`。两者各自在「模块加载」与
// 「模块加载」取时钟（测试侧定格于加载期、页面侧在加载期定格后**沿用到用例执行**）⇒ 只要
// **模块加载 → 断言**之间跨过午夜（或跨月首），两者就分叉必红。
// 模块级求值还把两个时刻的间隔从「一次 render」放大到「整个文件加载 + 用例执行」。
//
// 修法（要处理「模块级求值在导入时定格」这一点，**不是只改断言**）：
//   ① 用**导入期夹具** `./helpers/frozen-clock` 在**被测页面之前**冻结系统时钟
//      ⇒ 页面的模块级 `CURRENT_PERIOD` 与本文件的 `currentPeriod` 都定格在**同一冻结时刻**；
//      ⚠️ 这一步**必须**走独立模块：`import` 声明会被提升，写在文件里「先冻结后导入」不成立
//      （实测：页面仍在真实墙钟上定格，`结束日期` 读回真实今天）；
//   ② 每条用例前 `setSystemTime(FROZEN_NOW)` 复位 ⇒ 用例之间不累积漂移。
import { FROZEN_NOW } from '../helpers/frozen-clock'
import FinancePage from '@/app/(dashboard)/finance/page'

// 与页面 `getCurrentPeriod()` **同形**的本期派生（自然月 = 本月 1 号 ~ 今天）。
// 关键：它现在在**冻结之后**求值 ⇒ 与页面 `CURRENT_PERIOD` 同一时刻定格。
const fmtDate = (d: Date) => {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
const currentPeriod = {
  start: fmtDate(new Date(FROZEN_NOW.getFullYear(), FROZEN_NOW.getMonth(), 1)),
  end: fmtDate(FROZEN_NOW),
}

const mockSummary = {
  totalIncome: 150,
  totalRefund: 30,
  netIncome: 120,
  incomeCount: 2,
  refundCount: 1,
  pendingReceivable: 50,
  byPaymentMethod: [{ paymentMethod: 'wechat', income: 100, refund: 30, net: 70 }],
  dailyTrend: [{ date: '2026-08-15', income: 150, refund: 30, net: 120 }],
}

const mockTxns = [
  {
    id: 't1',
    transactionNo: 'FIN-20260815-0001',
    orderNo: 'MG202600001',
    type: 'income',
    amount: 100,
    paymentMethod: 'wechat',
    status: 'success',
    operator: 'admin',
    occurredAt: '2026-08-15T10:00:00',
    remark: '订单确认收款',
  },
]

describe('FinancePage', () => {
  const user = userEvent.setup()

  beforeEach(() => {
    vi.setSystemTime(FROZEN_NOW) // 每条用例复位到同一冻结时刻（模块级 currentPeriod 已定格）
    vi.clearAllMocks()
    mockGetSummary.mockResolvedValue({ data: { data: mockSummary } })
    mockGetTransactions.mockResolvedValue({
      data: { data: { items: mockTxns, total: 1 } },
    })
    mockGetReconciliation.mockResolvedValue({
      data: { data: { items: [], total: 0 } },
    })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('should render page title', () => {
    render(<FinancePage />)
    expect(screen.getByText('财务对账')).toBeInTheDocument()
    expect(screen.getByText(/资金流水、收支汇总与应收对账/)).toBeInTheDocument()
  })

  it('should render summary cards', async () => {
    render(<FinancePage />)
    await waitFor(() => {
      expect(mockGetSummary).toHaveBeenCalled()
    })
    expect(screen.getByText('本期收入')).toBeInTheDocument()
    expect(screen.getByText('本期退款')).toBeInTheDocument()
    expect(screen.getByText('净收入')).toBeInTheDocument()
    expect(screen.getByText('待收款')).toBeInTheDocument()
  })

  it('should render three tabs', () => {
    render(<FinancePage />)
    expect(screen.getByText('资金流水')).toBeInTheDocument()
    expect(screen.getByText('收支汇总')).toBeInTheDocument()
    expect(screen.getByText('应收对账')).toBeInTheDocument()
  })

  it('should load and display transactions', async () => {
    render(<FinancePage />)
    await waitFor(() => {
      expect(mockGetTransactions).toHaveBeenCalled()
    })
    await waitFor(() => {
      expect(screen.getByText('FIN-20260815-0001')).toBeInTheDocument()
      expect(screen.getByText('MG202600001')).toBeInTheDocument()
    })
  })

  it('should open 登记收支 modal', async () => {
    render(<FinancePage />)
    await user.click(screen.getByText('登记收支'))
    expect(screen.getByTestId('modal')).toBeInTheDocument()
    expect(screen.getByText('收支类型 *')).toBeInTheDocument()
  })

  // ── 应收对账差额语义（P2-1：少收/应退/多收 区分）──

  it('已完成+已退>0 订单差额显示「应退」而非「少收」', async () => {
    // given: 已完成订单，应收119.8 实收119.8 已退20 → 净应收差 +20（退款未核销）
    mockGetReconciliation.mockResolvedValue({
      data: { data: { items: [{
        orderId: 'o1', orderNo: '20260902507820031', customerName: '李雷',
        status: 'completed', receivableAmount: 119.8, receivedAmount: 119.8,
        refundAmount: 20, difference: 20,
      }], total: 1 } },
    })
    render(<FinancePage />)
    await user.click(screen.getByText('应收对账'))
    await waitFor(() => {
      expect(screen.getByText('应退')).toBeInTheDocument()
    })
    expect(screen.queryByText('少收')).not.toBeInTheDocument()
  })

  it('实收不足订单差额显示「少收」', async () => {
    // given: 待发货订单，应收119.8 实收0 已退0 → 差 +119.8（客户未付）
    mockGetReconciliation.mockResolvedValue({
      data: { data: { items: [{
        orderId: 'o2', orderNo: '2026090300001', customerName: '王五',
        status: 'confirmed', receivableAmount: 119.8, receivedAmount: 0,
        refundAmount: 0, difference: 119.8,
      }], total: 1 } },
    })
    render(<FinancePage />)
    await user.click(screen.getByText('应收对账'))
    await waitFor(() => {
      expect(screen.getByText('少收')).toBeInTheDocument()
    })
  })

  it('差额为 0 显示「已对平」', async () => {
    mockGetReconciliation.mockResolvedValue({
      data: { data: { items: [{
        orderId: 'o3', orderNo: '2026090300002', customerName: '赵六',
        status: 'completed', receivableAmount: 100, receivedAmount: 100,
        refundAmount: 0, difference: 0,
      }], total: 1 } },
    })
    render(<FinancePage />)
    await user.click(screen.getByText('应收对账'))
    await waitFor(() => {
      expect(screen.getByText('已对平')).toBeInTheDocument()
    })
  })

  // ── 本期默认时间范围（FN-004）：自然月 = 本月1号 ~ 今天 ──
  // 期望值 `currentPeriod` 见文件头（**模块级**，与页面同刻定格；issue #4761 第 2 条）

  it('打开页面默认填充本期（本月1号~今天）并生效查询', async () => {
    render(<FinancePage />)

    // 日期框被默认填充为本期范围
    await waitFor(() => {
      expect(screen.getByLabelText('开始日期')).toHaveValue(currentPeriod.start)
    })
    expect(screen.getByLabelText('结束日期')).toHaveValue(currentPeriod.end)
    // 三个数据源都按本期范围查询
    expect(mockGetSummary).toHaveBeenCalledWith({ startDate: currentPeriod.start, endDate: currentPeriod.end })
    expect(mockGetTransactions).toHaveBeenCalledWith(
      expect.objectContaining({ startDate: currentPeriod.start, endDate: currentPeriod.end })
    )
    expect(mockGetReconciliation).toHaveBeenCalledWith(
      expect.objectContaining({ startDate: currentPeriod.start, endDate: currentPeriod.end })
    )
  })

  it('重置后恢复本期（本月1号~今天）并重新查询', async () => {
    render(<FinancePage />)
    // 先修改日期框模拟用户筛选
    await user.clear(screen.getByLabelText('开始日期'))
    await user.type(screen.getByLabelText('开始日期'), '2025-01-01')
    await user.click(screen.getByText('重置'))

    expect(screen.getByLabelText('开始日期')).toHaveValue(currentPeriod.start)
    expect(screen.getByLabelText('结束日期')).toHaveValue(currentPeriod.end)
    expect(mockGetSummary).toHaveBeenLastCalledWith({ startDate: currentPeriod.start, endDate: currentPeriod.end })
  })

  // ── 登记收支「金额」的数值语义（issue #5228 缺口 2，**涉钱面**）──────────────
  //
  // ⚠️ 判据**不建在「`0.` 中间态」上**：jsdom 把 `type="number"` 的 `"0."` 归一成 `""`，
  // 真 Chromium 归一成 `"0"`（#5228 主会话真浏览器实测，两套读数**相反**）⇒ 谁在 jsdom 里拿它
  // 当判据，谁就是在拿与环境相反的读数下结论（必然假红或假绿）。这里一律用
  // `fireEvent.change` **一次给完整串**，钉的是与引擎无关的语义。

  /** 打开登记弹窗 → 给金额框一次性赋值（`null` = 保持空，不改动） */
  async function openCreateWithAmount(value: string | null) {
    render(<FinancePage />)
    await user.click(screen.getByText('登记收支'))
    const amount = screen.getByPlaceholderText('0.00') as HTMLInputElement
    if (value !== null) fireEvent.change(amount, { target: { value } })
    return amount
  }

  it('金额完整串 `0.5` ⇒ 原值提交 amount: 0.5（涉钱面：不取整、不被当空）', async () => {
    mockCreateTransaction.mockResolvedValue({ data: { data: {} } })
    await openCreateWithAmount('0.5')
    await user.click(screen.getByText('提交'))

    await waitFor(() => expect(mockCreateTransaction).toHaveBeenCalledTimes(1))
    expect(mockCreateTransaction.mock.calls[0][0]).toMatchObject({ amount: 0.5, type: 'income' })
  })

  it('金额留空 ⇒ 显式拒绝、**一个请求都不发**（空不是 0）', async () => {
    const amount = await openCreateWithAmount(null)
    expect(amount.value).toBe('')
    const { toast } = await import('sonner')
    const errSpy = vi.spyOn(toast, 'error')
    await user.click(screen.getByText('提交'))

    await waitFor(() => expect(errSpy).toHaveBeenCalledWith('请输入正确的金额'))
    expect(mockCreateTransaction).not.toHaveBeenCalled()
  })

  it('金额 `0` ⇒ 显式拒绝（不是静默按 0 提交、也不是被当空吞掉）', async () => {
    await openCreateWithAmount('0')
    const { toast } = await import('sonner')
    const errSpy = vi.spyOn(toast, 'error')
    await user.click(screen.getByText('提交'))

    await waitFor(() => expect(errSpy).toHaveBeenCalledWith('请输入正确的金额'))
    expect(mockCreateTransaction).not.toHaveBeenCalled()
  })
})
