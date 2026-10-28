// case_ids: SP-006
// 采购单页面（issue #7369，P0-1 段 4；issue #7567 起明细只能从公共选品器里勾）：
// 列表真值 / 收货进度 / 建单 payload / 收货超收拦截 / 关单须写原因 / **商家不许手打 SKU**。

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

// UI 原语：先摊开真值再覆盖（issue #7007 的教训 —— 整模块 mock 会让页面新增原语时报错）
vi.mock('@/components/ui', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>()
  return {
    ...actual,
    Button: ({ children, onClick, loading, ...props }: any) => (
      <button onClick={onClick} disabled={loading} {...props}>{children}</button>
    ),
  }
})

// 写面按 `inbound:create` 门控（#5983 范式）：默认给足写码；只读用例另行覆盖
const mockHas = vi.fn((code: string) => code === 'inbound:create')
vi.mock('@/lib/permission', () => ({
  usePermission: () => ({ has: (code: string) => mockHas(code), loading: false }),
}))

const mockList = vi.fn()
const mockCreate = vi.fn()
const mockReceive = vi.fn()
const mockClose = vi.fn()
const mockSuppliers = vi.fn()
const mockGetProducts = vi.fn()
const mockGetProduct = vi.fn()

vi.mock('@/lib/api', () => ({
  purchaseOrderApi: {
    list: (...args: unknown[]) => mockList(...args),
    create: (...args: unknown[]) => mockCreate(...args),
    receive: (...args: unknown[]) => mockReceive(...args),
    close: (...args: unknown[]) => mockClose(...args),
  },
  supplierApi: {
    list: (...args: unknown[]) => mockSuppliers(...args),
  },
  productApi: {
    getProducts: (...args: unknown[]) => mockGetProducts(...args),
    getProduct: (...args: unknown[]) => mockGetProduct(...args),
  },
}))

import PurchaseOrdersPage, { purchaseStatusLabel } from '@/app/(dashboard)/purchase-orders/page'

/** 线上真实量级（> 2^53）：采购明细的 skuId 就是这种串 */
const SKU_ID = '2097126615461462018'

const ORDER = {
  id: 'po-1',
  poNo: 'CG-20261020-0001',
  supplierId: 'sup-1',
  supplierName: '杭州染整一厂',
  orderDate: '2026-10-20',
  expectedDate: '2026-10-25',
  status: 'partially_received' as const,
  totalAmount: 1000,
  remark: null,
  closedAt: null,
  closedReason: null,
  items: [
    {
      id: 'it-1',
      skuId: SKU_ID,
      productId: 'prod-1',
      quantity: 100,
      unitPrice: 10,
      amount: 1000,
      receivedQuantity: 40,
      remainingQuantity: 60,
      // 展示名由服务端解析（issue #7567）：收货面认商品用，不印雪花号
      productName: '遮光窗帘布',
      skuCode: 'H-2699-01',
      colorName: '米白',
      doorWidth: '3.2',
    },
  ],
  receipts: [{ id: 'r-1', itemId: 'it-1', quantity: 40, receivedAt: '2026-10-20', inboundOrderId: null }],
}

const CLOSED = {
  ...ORDER,
  id: 'po-2',
  poNo: 'CG-20261019-0002',
  status: 'closed' as const,
  closedReason: '供应商断货',
}

/** 建单走法（issue #7567）：搜商品 → 点商品 → 勾 SKU（**没有**可手打 SKU 的输入框） */
async function pickSku() {
  fireEvent.change(screen.getByLabelText('搜索商品'), { target: { value: '遮光' } })
  fireEvent.click(await screen.findByRole('button', { name: /遮光窗帘布/ }, { timeout: 3000 }))
  fireEvent.click(await screen.findByRole('checkbox', undefined, { timeout: 3000 }))
}

describe('采购单页面', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockHas.mockImplementation((code: string) => code === 'inbound:create')
    mockList.mockResolvedValue({ data: { data: [ORDER, CLOSED] } })
    mockSuppliers.mockResolvedValue({
      data: { data: [{ id: 'sup-1', name: '杭州染整一厂', status: 'active' }] },
    })
    mockGetProducts.mockResolvedValue({
      data: { data: { items: [{ id: 'prod-1', name: '遮光窗帘布', skuCode: 'HUOHAO-01' }] } },
    })
    mockGetProduct.mockResolvedValue({
      data: {
        data: {
          id: 'prod-1',
          name: '遮光窗帘布',
          skus: [{ id: SKU_ID, colorName: '米白', doorWidth: '3.2', stock: 86, price: 30, status: 'active' }],
        },
      },
    })
    mockCreate.mockResolvedValue({ data: { data: ORDER } })
    mockReceive.mockResolvedValue({ data: { data: ORDER } })
    mockClose.mockResolvedValue({ data: { data: CLOSED } })
  })

  it('第一屏拉服务端列表并如实渲染：单号 / 供应商 / 收货进度 / 金额', async () => {
    render(<PurchaseOrdersPage />)
    await waitFor(() => expect(screen.getByTestId('purchase-row-CG-20261020-0001')).toBeInTheDocument())
    const row = screen.getByTestId('purchase-row-CG-20261020-0001')
    expect(row).toHaveTextContent('CG-20261020-0001')
    expect(row).toHaveTextContent('杭州染整一厂')
    // 收货进度是后端派生值（40 / 100），前端不自己算
    expect(row).toHaveTextContent('40 / 100')
    expect(row).toHaveTextContent('¥1000.00')
  })

  // issue #8048：加载态 = 通用表格骨架（#8036 口径），不再是裸「加载中…」+ 空白表体。
  it('加载中：渲染 table-skeleton，且不出现裸「加载中…」文案（#8048）', async () => {
    mockList.mockReturnValue(new Promise(() => {}))
    render(<PurchaseOrdersPage />)
    expect(await screen.findByTestId('table-skeleton')).toBeInTheDocument()
    // 红证：把加载分支改回裸「加载中…」div ⇒ 本条红
    expect(screen.queryByText(/加载中/)).not.toBeInTheDocument()
    expect(screen.queryByTestId('purchase-orders-loading')).not.toBeInTheDocument()
  })

  it('状态上屏是人话；未登记的值给「其他」而不回显机器值（issue #6668）', async () => {
    expect(purchaseStatusLabel('ordered')).toBe('待收货')
    expect(purchaseStatusLabel('partially_received')).toBe('部分收货')
    expect(purchaseStatusLabel('received')).toBe('已收齐')
    expect(purchaseStatusLabel('closed')).toBe('已关闭')
    expect(purchaseStatusLabel('cancelled_by_server' as never)).not.toBe('cancelled_by_server')

    render(<PurchaseOrdersPage />)
    await waitFor(() => expect(screen.getByTestId('purchase-row-CG-20261020-0001')).toBeInTheDocument())
    expect(screen.getByText('部分收货')).toBeInTheDocument()
    // 关闭的单把原因印出来（半年后要能解释为什么少了货）
    expect(screen.getByText('供应商断货')).toBeInTheDocument()
  })

  it('建单 payload：明细从选品器勾出来（带 productId）、状态字段一个都不带（状态由后端派生）', async () => {
    render(<PurchaseOrdersPage />)
    await waitFor(() => expect(screen.getByTestId('purchase-create')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('purchase-create'))
    await pickSku()
    fireEvent.change(screen.getByTestId('purchase-form-qty-0'), { target: { value: '50' } })
    fireEvent.change(screen.getByTestId('purchase-form-price-0'), { target: { value: '12.5' } })
    fireEvent.click(screen.getByTestId('purchase-form-submit'))

    await waitFor(() => expect(mockCreate).toHaveBeenCalled())
    const payload = mockCreate.mock.calls[0][0]
    expect(payload.supplierId).toBe('sup-1')
    // 雪花号**逐字字符串**提交（`Number()` 会吞末位）；productId 一并带上（服务端有这列）
    expect(payload.items).toEqual([{ skuId: SKU_ID, productId: 'prod-1', quantity: 50, unitPrice: 12.5 }])
    expect(typeof payload.items[0].skuId).toBe('string')
    expect(payload.status).toBeUndefined()
  })

  it('🔴 商家不许手打 SKU（issue #7567）：建单弹窗里**没有** SKU 文本输入框，空明细说清怎么加', async () => {
    render(<PurchaseOrdersPage />)
    await waitFor(() => expect(screen.getByTestId('purchase-create')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('purchase-create'))

    // 改前这里是 `<input placeholder="SKU">`（要人抄 19 位雪花号）
    expect(screen.queryByPlaceholderText('SKU')).not.toBeInTheDocument()
    expect(screen.getByTestId('purchase-form-empty')).toHaveTextContent('勾选规格即加入')
    // 空明细 ⇒ 本地拦下，不发请求
    fireEvent.click(screen.getByTestId('purchase-form-submit'))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('至少要有一行明细'))
    expect(mockCreate).not.toHaveBeenCalled()
  })

  it('建单拦截：没选供应商 / 数量不大于 0 都不发请求（错在本地就停住）', async () => {
    render(<PurchaseOrdersPage />)
    await waitFor(() => expect(screen.getByTestId('purchase-create')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('purchase-create'))
    fireEvent.change(screen.getByTestId('purchase-form-supplier'), { target: { value: '' } })
    await pickSku()
    fireEvent.change(screen.getByTestId('purchase-form-qty-0'), { target: { value: '0' } })
    fireEvent.click(screen.getByTestId('purchase-form-submit'))
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(mockCreate).not.toHaveBeenCalled()
  })

  it('收货：只提交没填数量之外的行；超过未收数量在本地拦下（后端也会拦，双保险）', async () => {
    render(<PurchaseOrdersPage />)
    await waitFor(() => expect(screen.getByTestId('purchase-receive-CG-20261020-0001')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('purchase-receive-CG-20261020-0001'))

    // 收货面认商品靠展示名（商品 / 颜色 / 门幅）—— 内部雪花号一个字符都不许上屏
    expect(screen.getByText(/遮光窗帘布 \/ 米白 \/ 3\.2/)).toBeInTheDocument()
    expect(screen.queryByText(SKU_ID)).not.toBeInTheDocument()

    // 未收 60，填 80 ⇒ 本地拦截
    fireEvent.change(screen.getByTestId(`purchase-receive-qty-${SKU_ID}`), { target: { value: '80' } })
    fireEvent.click(screen.getByTestId('purchase-receive-submit'))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('超过未收数量'))
    expect(mockReceive).not.toHaveBeenCalled()

    // 填 60 ⇒ 正常提交（lines 带 itemId + quantity）
    fireEvent.change(screen.getByTestId(`purchase-receive-qty-${SKU_ID}`), { target: { value: '60' } })
    fireEvent.click(screen.getByTestId('purchase-receive-submit'))
    await waitFor(() => expect(mockReceive).toHaveBeenCalled())
    expect(mockReceive.mock.calls[0][0]).toBe('po-1')
    expect(mockReceive.mock.calls[0][1].lines).toEqual([{ itemId: 'it-1', quantity: 60 }])
  })

  it('关单：不写原因不发请求；写了才调接口（不许删单，只许留原因关闭）', async () => {
    render(<PurchaseOrdersPage />)
    await waitFor(() => expect(screen.getByTestId('purchase-close-CG-20261020-0001')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('purchase-close-CG-20261020-0001'))
    fireEvent.click(screen.getByTestId('purchase-close-submit'))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('请写关闭原因'))
    expect(mockClose).not.toHaveBeenCalled()

    fireEvent.change(screen.getByTestId('purchase-close-reason'), { target: { value: '到不齐，剩两卷布' } })
    fireEvent.click(screen.getByTestId('purchase-close-submit'))
    await waitFor(() => expect(mockClose).toHaveBeenCalledWith('po-1', '到不齐，剩两卷布'))
  })

  it('服务端取不到商品名时如实说「商品信息缺失」，**绝不**拿雪花号顶替（内部标识不上屏）', async () => {
    mockList.mockResolvedValue({
      data: {
        data: [
          {
            ...ORDER,
            items: [
              {
                id: 'it-1',
                skuId: SKU_ID,
                productId: null,
                quantity: 100,
                unitPrice: 10,
                amount: 1000,
                receivedQuantity: 40,
                remainingQuantity: 60,
                productName: null,
                skuCode: null,
                colorName: null,
                doorWidth: null,
              },
            ],
          },
        ],
      },
    })
    render(<PurchaseOrdersPage />)
    await waitFor(() => expect(screen.getByTestId('purchase-receive-CG-20261020-0001')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('purchase-receive-CG-20261020-0001'))

    expect(screen.getByText('商品信息缺失')).toBeInTheDocument()
    expect(screen.queryByText(SKU_ID)).not.toBeInTheDocument()
  })

  it('只读岗位（无 inbound:create）：看得见列表，但没有任何写按钮', async () => {
    mockHas.mockImplementation(() => false)
    render(<PurchaseOrdersPage />)
    await waitFor(() => expect(screen.getByTestId('purchase-row-CG-20261020-0001')).toBeInTheDocument())
    expect(screen.queryByTestId('purchase-create')).not.toBeInTheDocument()
    expect(screen.queryByTestId('purchase-receive-CG-20261020-0001')).not.toBeInTheDocument()
    expect(screen.queryByTestId('purchase-close-CG-20261020-0001')).not.toBeInTheDocument()
  })

  it('加载失败给出可重试的错误面（不假装空列表 —— 「没有采购单」是业务结论）', async () => {
    mockList.mockRejectedValue(new Error('boom'))
    render(<PurchaseOrdersPage />)
    await waitFor(() => expect(screen.getByTestId('purchase-orders-load-error')).toBeInTheDocument())
    expect(screen.queryByTestId('purchase-orders-empty')).not.toBeInTheDocument()
  })
})
