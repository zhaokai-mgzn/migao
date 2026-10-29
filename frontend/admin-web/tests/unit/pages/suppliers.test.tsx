// case_ids: SP-001
// 供应商档案页（issue #7369，P0-1 段 1）：列表 / 账期口径 / 建档 / 停用 四条判据。

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

// UI 原语：**先摊开真值再覆盖**（issue #7007 的教训 —— 整模块 mock 会让页面新增原语时报错）
vi.mock('@/components/ui', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>()
  return {
    ...actual,
    Button: ({ children, onClick, loading, ...props }: any) => (
      <button onClick={onClick} disabled={loading} {...props}>{children}</button>
    ),
  }
})

vi.mock('lucide-react', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>()
  const stub = (name: string) => (props: any) => <span data-testid={`icon-${name}`} {...props} />
  return { ...actual, Plus: stub('plus'), Search: stub('search'), Truck: stub('truck') }
})

// 写面按 `inbound:create` 门控（#5983 范式）：默认给足写码；「只读」用例另行覆盖。
const mockHas = vi.fn((code: string) => code === 'inbound:create' || code === 'finance:create')
vi.mock('@/lib/permission', () => ({
  usePermission: () => ({ has: (code: string) => mockHas(code), loading: false }),
}))

const mockList = vi.fn()
const mockUnassigned = vi.fn()
const mockPayables = vi.fn()
const mockCreatePayment = vi.fn()
const mockCreate = vi.fn()
const mockUpdate = vi.fn()

vi.mock('@/lib/api', () => ({
  supplierApi: {
    list: (...args: unknown[]) => mockList(...args),
    unassignedInbound: (...args: unknown[]) => mockUnassigned(...args),
    payables: (...args: unknown[]) => mockPayables(...args),
    createPayment: (...args: unknown[]) => mockCreatePayment(...args),
    create: (...args: unknown[]) => mockCreate(...args),
    update: (...args: unknown[]) => mockUpdate(...args),
  },
}))

import SuppliersPage, { paymentTermsLabel } from '@/app/(dashboard)/suppliers/page'
import { toast } from 'sonner'

const ROWS = [
  { id: 'sup-1', name: '杭州染整一厂', contactName: '张厂长', contactPhone: '13900000000', paymentTermsDays: 30, status: 'active', remark: null },
  { id: 'sup-2', name: '绍兴现结布行', contactName: null, contactPhone: null, paymentTermsDays: 0, status: 'inactive', remark: null },
]

describe('供应商档案页', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockHas.mockImplementation((code: string) => code === 'inbound:create' || code === 'finance:create')
    mockList.mockResolvedValue({ data: { data: ROWS } })
    mockUnassigned.mockResolvedValue({ data: { data: [] } })
    mockPayables.mockResolvedValue({ data: { data: {
      suppliers: [], totalReceived: 0, totalOutstanding: 0, paymentsRecorded: true,
    } } })
    mockCreatePayment.mockResolvedValue({ data: { data: {} } })
    mockCreate.mockResolvedValue({ data: { data: ROWS[0] } })
    mockUpdate.mockResolvedValue({ data: { data: ROWS[0] } })
  })

  it('第一屏拉取服务端列表并如实渲染（不自己造数）', async () => {
    render(<SuppliersPage />)
    await waitFor(() => {
      expect(mockList).toHaveBeenCalled()
    })
    await waitFor(() => {
      expect(screen.getByTestId('supplier-row-sup-1')).toBeInTheDocument()
    })
    expect(screen.getByText('杭州染整一厂')).toBeInTheDocument()
    expect(screen.getByText('张厂长')).toBeInTheDocument()
    // 账期口径：30 天 / 现结（0 不是「未设置」）
    expect(screen.getByTestId('supplier-terms-sup-1')).toHaveTextContent('30 天')
    expect(screen.getByTestId('supplier-terms-sup-2')).toHaveTextContent('现结')
  })

  // issue #8048：加载态 = 通用表格骨架（#8036 口径），不再是裸「加载中…」+ 空白表体。
  it('加载中：渲染 table-skeleton，且不出现裸「加载中…」文案（#8048）', async () => {
    mockList.mockReturnValue(new Promise(() => {}))
    render(<SuppliersPage />)
    expect(await screen.findByTestId('table-skeleton')).toBeInTheDocument()
    // 红证：把加载分支改回裸「加载中…」div ⇒ 本条红
    expect(screen.queryByText(/加载中/)).not.toBeInTheDocument()
  })

  it('账期展示口径：未设置 / 现结 / N 天 三态可分', () => {
    expect(paymentTermsLabel(null)).toBe('未设置')
    expect(paymentTermsLabel(undefined)).toBe('未设置')
    expect(paymentTermsLabel(0)).toBe('现结')
    expect(paymentTermsLabel(45)).toBe('45 天')
  })

  it('建档：名称去空白后提交，账期留空发 null（不是 0）', async () => {
    render(<SuppliersPage />)
    await waitFor(() => expect(screen.getByTestId('supplier-table')).toBeInTheDocument())

    fireEvent.click(screen.getByText('新建供应商'))
    fireEvent.change(screen.getByTestId('supplier-form-name'), { target: { value: '  南通织造厂  ' } })
    fireEvent.change(screen.getByTestId('supplier-form-terms'), { target: { value: '' } })
    fireEvent.click(screen.getByText('保存'))

    await waitFor(() => {
      expect(mockCreate).toHaveBeenCalledWith(expect.objectContaining({
        name: '南通织造厂',
        paymentTermsDays: null,
        status: 'active',
      }))
    })
  })

  it('停用：走同一条更新写面，带上原字段与 inactive', async () => {
    render(<SuppliersPage />)
    await waitFor(() => expect(screen.getByTestId('supplier-table')).toBeInTheDocument())

    fireEvent.click(screen.getByTestId('supplier-toggle-sup-1'))

    await waitFor(() => {
      expect(mockUpdate).toHaveBeenCalledWith('sup-1', expect.objectContaining({
        name: '杭州染整一厂',
        status: 'inactive',
        paymentTermsDays: 30,
      }))
    })
    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith('已停用「杭州染整一厂」')
    })
  })

  it('账期越界在前端就拦下（不发请求）', async () => {
    render(<SuppliersPage />)
    await waitFor(() => expect(screen.getByTestId('supplier-table')).toBeInTheDocument())

    fireEvent.click(screen.getByText('新建供应商'))
    fireEvent.change(screen.getByTestId('supplier-form-name'), { target: { value: '越界厂' } })
    fireEvent.change(screen.getByTestId('supplier-form-terms'), { target: { value: '400' } })
    fireEvent.click(screen.getByText('保存'))

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith('账期天数须在 0~365 之间（0 = 现结，留空 = 未设置）')
    })
    expect(mockCreate).not.toHaveBeenCalled()
  })

  it('无写码 ⇒ 建/改入口整项不渲染（不是点下去才 403，#5983 范式）', async () => {
    mockHas.mockImplementation(() => false)
    render(<SuppliersPage />)
    await waitFor(() => expect(screen.getByTestId('supplier-table')).toBeInTheDocument())
    expect(screen.queryByText('新建供应商')).toBeNull()
    expect(screen.queryByTestId('supplier-toggle-sup-1')).toBeNull()
    expect(screen.getAllByText('只读').length).toBeGreaterThan(0)
  })

  it('待指派清单：卡上列出名字 / 单数 / 最近日期，且「建档」把名字预填进表单', async () => {
    mockUnassigned.mockResolvedValue({ data: { data: [
      { supplierName: '没建过档的厂', orderCount: 3, lastInboundDate: '2026-10-01' },
      { supplierName: '老数据厂', orderCount: 1, lastInboundDate: null },
    ] } })
    render(<SuppliersPage />)

    await waitFor(() => expect(screen.getByTestId('supplier-unassigned')).toBeInTheDocument())
    expect(screen.getByText('没建过档的厂')).toBeInTheDocument()
    expect(screen.getByTestId('unassigned-没建过档的厂')).toHaveTextContent('3 张入库单')
    expect(screen.getByTestId('unassigned-没建过档的厂')).toHaveTextContent('2026-10-01')

    fireEvent.click(screen.getByTestId('unassigned-create-没建过档的厂'))
    expect(screen.getByTestId('supplier-form-name')).toHaveValue('没建过档的厂')
  })

  it('无待指派 ⇒ 整卡不渲染（空卡比没有卡更吵）', async () => {
    render(<SuppliersPage />)
    await waitFor(() => expect(screen.getByTestId('supplier-table')).toBeInTheDocument())
    expect(screen.queryByTestId('supplier-unassigned')).toBeNull()
  })

  it('应付对账卡：逐家累计收货额 + 合计；A 段把「已付」显示成「未登记」而不是 ¥0.00', async () => {
    mockPayables.mockResolvedValue({ data: { data: {
      suppliers: [
        { supplierId: 'sup-1', supplierName: '杭州染整一厂', status: 'active', receivedAmount: 12500.4,
          orderCount: 4, firstInboundDate: '2026-09-01', lastInboundDate: '2026-10-10',
          paidAmount: 0, paymentsRecorded: false, outstanding: 12500.4 },
        { supplierId: 'sup-2', supplierName: '宏达布行', status: 'inactive', receivedAmount: 0,
          orderCount: 0, firstInboundDate: null, lastInboundDate: null,
          paidAmount: 0, paymentsRecorded: false, outstanding: 0 },
      ],
      totalReceived: 12500.4, totalOutstanding: 12500.4, paymentsRecorded: false,
    } } })
    render(<SuppliersPage />)

    await waitFor(() => expect(screen.getByTestId('supplier-payables')).toBeInTheDocument())
    const row = screen.getByTestId('payable-sup-1')
    expect(row).toHaveTextContent('杭州染整一厂')
    expect(row).toHaveTextContent('¥12500.40')
    expect(row).toHaveTextContent('2026-10-10')
    // 关键：不能说「已付 ¥0.00」——那是把「没做付款登记」说成「一分没付」
    expect(row).toHaveTextContent('未登记')
    expect(screen.getByTestId('supplier-payables')).toHaveTextContent('合计 ¥12500.40')
    expect(screen.getByTestId('supplier-payables')).toHaveTextContent('不是「尚欠」')
    expect(screen.getByTestId('payable-sup-2')).toHaveTextContent('已停用')
  })

  it('没有任何收货额 ⇒ 整卡不渲染（空表比没有表更吵）', async () => {
    render(<SuppliersPage />)
    await waitFor(() => expect(screen.getByTestId('supplier-table')).toBeInTheDocument())
    expect(screen.queryByTestId('supplier-payables')).toBeNull()
  })

  it('登记付款：只提交实付金额与方式（不猜冲抵哪几张单），提交后刷新对账', async () => {
    mockPayables.mockResolvedValue({ data: { data: {
      suppliers: [{ supplierId: 'sup-1', supplierName: '杭州染整一厂', status: 'active',
        receivedAmount: 12500.4, orderCount: 4, firstInboundDate: null, lastInboundDate: '2026-10-10',
        paidAmount: 2500.4, paymentsRecorded: true, outstanding: 10000 }],
      totalReceived: 12500.4, totalOutstanding: 10000, paymentsRecorded: true,
    } } })
    render(<SuppliersPage />)

    await waitFor(() => expect(screen.getByTestId('payable-sup-1')).toBeInTheDocument())
    // 尚欠 = 收货额 − 已付（段 3-B 起是真值）
    expect(screen.getByTestId('payable-sup-1')).toHaveTextContent('¥10000.00')

    fireEvent.click(screen.getByTestId('payable-pay-sup-1'))
    fireEvent.change(screen.getByTestId('pay-amount'), { target: { value: '1200' } })
    fireEvent.change(screen.getByTestId('pay-method'), { target: { value: 'cash' } })
    fireEvent.click(screen.getByTestId('pay-submit'))

    await waitFor(() => expect(mockCreatePayment).toHaveBeenCalledTimes(1))
    const payload = mockCreatePayment.mock.calls[0][0] as Record<string, unknown>
    expect(payload.supplierId).toBe('sup-1')
    expect(payload.amount).toBe(1200)
    expect(payload.method).toBe('cash')
    // 关键：不带 allocations —— 不替财务猜「这笔钱付的是哪几张单」
    expect(payload.allocations).toBeUndefined()
  })

  it('付款金额非法 ⇒ 前端就拦下（不发请求）', async () => {
    mockPayables.mockResolvedValue({ data: { data: {
      suppliers: [{ supplierId: 'sup-1', supplierName: '杭州染整一厂', status: 'active',
        receivedAmount: 500, orderCount: 1, firstInboundDate: null, lastInboundDate: '2026-10-10',
        paidAmount: 0, paymentsRecorded: true, outstanding: 500 }],
      totalReceived: 500, totalOutstanding: 500, paymentsRecorded: true,
    } } })
    render(<SuppliersPage />)
    await waitFor(() => expect(screen.getByTestId('payable-pay-sup-1')).toBeInTheDocument())

    fireEvent.click(screen.getByTestId('payable-pay-sup-1'))
    fireEvent.change(screen.getByTestId('pay-amount'), { target: { value: '0' } })
    fireEvent.click(screen.getByTestId('pay-submit'))

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('必须大于 0'))
    expect(mockCreatePayment).not.toHaveBeenCalled()
  })

  // ── issue #8066（扫描器判据①「读失败被吞」收口）────────────────────────────
  // 改前：两块补充读面的 catch 里 `setUnassigned([])` / `setPayables(null)` ⇒ 条件渲染整块消失，
  // 屏上只剩主列表 ⇒ 商家读成「没有待建档的供应商」/「没有应付」。两条各钉 失败面 / 不冒充 / 重试真重发。
  it('待指派清单读失败：常驻失败锚在场 + 不画成「没有待建档的供应商」+ 重试真的重发', async () => {
    mockUnassigned.mockRejectedValueOnce(new Error('unassigned down'))
    render(<SuppliersPage />)

    const anchor = await screen.findByTestId('supplier-unassigned-error')
    expect(anchor).toHaveTextContent('待指派清单读取失败')
    expect(anchor).toHaveTextContent('不是「没有待建档的供应商」')
    expect(screen.queryByTestId('supplier-unassigned')).toBeNull()

    const before = mockUnassigned.mock.calls.length
    mockUnassigned.mockResolvedValue({ data: { data: [
      { supplierName: '没建过档的厂', orderCount: 3, lastInboundDate: '2026-10-01' },
    ] } })
    fireEvent.click(screen.getByTestId('supplier-unassigned-error-retry'))
    await waitFor(() => expect(screen.queryByTestId('supplier-unassigned-error')).toBeNull())
    // 重试**真的**重发（不是只把失败态擦掉）
    expect(mockUnassigned.mock.calls.length).toBe(before + 1)
    await waitFor(() => expect(screen.getByTestId('supplier-unassigned')).toBeInTheDocument())
  }, 20_000) // ⏱ 整例 20s：失败面等到底时 RTL 的 asyncUtilTimeout 是 5s（否则红成 Test timed out = 没跑到断言）

  it('应付对账读失败：常驻失败锚在场 + 不画成「没有应付」+ 重试真的重发', async () => {
    mockPayables.mockRejectedValueOnce(new Error('payables down'))
    render(<SuppliersPage />)

    const anchor = await screen.findByTestId('supplier-payables-error')
    expect(anchor).toHaveTextContent('应付对账读取失败')
    expect(anchor).toHaveTextContent('不是「没有应付」')
    expect(screen.queryByTestId('supplier-payables')).toBeNull()

    const before = mockPayables.mock.calls.length
    mockPayables.mockResolvedValue({ data: { data: {
      suppliers: [{
        supplierId: 'sup-1', supplierName: '杭州染整一厂', status: 'active',
        receivedAmount: 500, orderCount: 2, lastInboundDate: '2026-10-01',
        paidAmount: 0, paymentsRecorded: false,
      }],
      totalReceived: 500, totalOutstanding: 500, paymentsRecorded: false,
    } } })
    fireEvent.click(screen.getByTestId('supplier-payables-error-retry'))
    await waitFor(() => expect(screen.queryByTestId('supplier-payables-error')).toBeNull())
    // 重试**真的**重发（不是只把失败态擦掉）
    expect(mockPayables.mock.calls.length).toBe(before + 1)
    await waitFor(() => expect(screen.getByTestId('supplier-payables')).toBeInTheDocument())
  }, 20_000) // ⏱ 同上：整例预算必须长于 asyncUtilTimeout，红要显形为断言失败
})
