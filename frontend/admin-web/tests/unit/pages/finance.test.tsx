import React from 'react';
// case_ids: FN-001, FN-002, FN-003
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
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
      <label>{label}</label>
      <input value={value} onChange={onChange} onKeyDown={onKeyDown} {...props} />
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

import FinancePage from '@/app/(dashboard)/finance/page'

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
    vi.clearAllMocks()
    mockGetSummary.mockResolvedValue({ data: { data: mockSummary } })
    mockGetTransactions.mockResolvedValue({
      data: { data: { items: mockTxns, total: 1 } },
    })
    mockGetReconciliation.mockResolvedValue({
      data: { data: { items: [], total: 0 } },
    })
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
})
