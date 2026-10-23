// case_ids: PRC-005, APV-002
import { describe, expect, it, beforeEach, vi } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import PriceBooksPage from '@/app/(dashboard)/price-books/page'

/**
 * 价格本页面（issue #7375 段 3）—— 三条纪律的**前端**判据。
 *
 * 后端已保证「价必须 > 0」「低于成本要审批」，但页面若把这些错误吞掉（只显示「保存失败」），
 * 运营就不知道该怎么办 —— 而价格是毛利的第一变量。
 */
const priceBookApi = vi.hoisted(() => ({
  list: vi.fn(),
  upsertProtocol: vi.fn(),
  upsertVipLevel: vi.fn(),
  upsertTier: vi.fn(),
  remove: vi.fn(),
}))

const approvalApi = vi.hoisted(() => ({ submit: vi.fn() }))
vi.mock('@/lib/api', () => ({ priceBookApi, approvalApi }))
vi.mock('@/lib/permission', () => ({ usePermission: () => ({ has: () => true, permissions: [], isAdmin: true }) }))

const wrap = <T,>(data: T) => Promise.resolve({ data: { success: true, data } })

const EMPTY_BOOK = { skuId: 1024, protocol: [], vipLevels: [], tiers: [] }

describe('价格本页面', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    priceBookApi.list.mockImplementation(() => wrap(EMPTY_BOOK))
  })

  it('🔴 没填 SKU 时只给提示，不打接口（价格本按 SKU 维护）', async () => {
    render(<PriceBooksPage />)
    await waitFor(() => expect(screen.getByTestId('price-books-hint')).toBeInTheDocument())
    expect(priceBookApi.list).not.toHaveBeenCalled()
  })

  it('三层价格为空时各自显示「未设置」，**不显示 ¥0.00**', async () => {
    render(<PriceBooksPage />)
    fireEvent.change(screen.getByTestId('price-books-sku'), { target: { value: '1024' } })

    await waitFor(() => expect(screen.getByTestId('price-books-empty-protocol')).toBeInTheDocument())
    expect(screen.getByTestId('price-books-empty-vip-level')).toBeInTheDocument()
    expect(screen.getByTestId('price-books-empty-tier')).toBeInTheDocument()
    expect(screen.getByTestId('price-books-empty-protocol').textContent).toContain('未设置')
    expect(document.body.textContent).not.toContain('¥0.00')
  })

  it('有价时按层列出（协议价显示客户、等级价显示等级、阶梯价显示门槛）', async () => {
    priceBookApi.list.mockImplementation(() => wrap({
      skuId: 1024,
      protocol: [{ id: 'p1', customer_id: 'c-9', price: 88 }],
      vipLevels: [{ id: 'v1', vip_level: 'vip2', price: 92 }],
      tiers: [{ id: 't1', min_qty: 50, max_qty: 99, price: 85 }],
    }))
    render(<PriceBooksPage />)
    fireEvent.change(screen.getByTestId('price-books-sku'), { target: { value: '1024' } })

    await waitFor(() => expect(screen.getByTestId('price-books-list-protocol')).toBeInTheDocument())
    expect(screen.getByTestId('price-books-list-protocol').textContent).toContain('c-9')
    expect(screen.getByTestId('price-books-list-vip-level').textContent).toContain('vip2')
    expect(screen.getByTestId('price-books-list-tier').textContent).toContain('满 50 米')
  })

  it('🔴 价格 ≤ 0 时前端先拦（0 元等于白送），且不打保存接口', async () => {
    render(<PriceBooksPage />)
    fireEvent.change(screen.getByTestId('price-books-sku'), { target: { value: '1024' } })
    await waitFor(() => expect(screen.getByTestId('price-books-empty-protocol')).toBeInTheDocument())

    fireEvent.click(screen.getByText('新增价格'))
    fireEvent.change(screen.getByTestId('price-books-target'), { target: { value: 'c-9' } })
    fireEvent.change(screen.getByTestId('price-books-price'), { target: { value: '0' } })
    fireEvent.click(screen.getByTestId('price-books-save'))

    await waitFor(() => expect(screen.getByTestId('price-books-form-error')).toBeInTheDocument())
    expect(screen.getByTestId('price-books-form-error').textContent).toContain('必须大于 0')
    expect(priceBookApi.upsertProtocol).not.toHaveBeenCalled()
  })

  it('🔴 后端拒绝时**显示服务端原文**（低于成本的改价需要审批）', async () => {
    priceBookApi.upsertProtocol.mockRejectedValue({
      response: { status: 400, data: { error: { message: '协议价 ¥80.00 低于该 SKU 成本 ¥100.00，必须先有「改价」审批' } } },
    })
    render(<PriceBooksPage />)
    fireEvent.change(screen.getByTestId('price-books-sku'), { target: { value: '1024' } })
    await waitFor(() => expect(screen.getByTestId('price-books-empty-protocol')).toBeInTheDocument())

    fireEvent.click(screen.getByText('新增价格'))
    fireEvent.change(screen.getByTestId('price-books-target'), { target: { value: 'c-9' } })
    fireEvent.change(screen.getByTestId('price-books-price'), { target: { value: '80' } })
    fireEvent.click(screen.getByTestId('price-books-save'))

    await waitFor(() => expect(screen.getByTestId('price-books-form-error')).toBeInTheDocument())
    expect(screen.getByTestId('price-books-form-error').textContent).toContain('改价')
  })

  it('🔴 低于成本被拒 ⇒ 就地开「改价」审批：ref = 当前 SKU id（不必手抄）', async () => {
    priceBookApi.upsertProtocol.mockRejectedValue({
      response: {
        status: 400,
        data: {
          message:
            '协议价 ¥50 低于该 SKU 成本 ¥95（差 ¥45），必须先有已通过的「改价」审批：objectType=price_change，objectRef=1024，金额 ≥ 成本价',
        },
      },
    })
    approvalApi.submit.mockResolvedValue({ data: { success: true, data: { id: 'ap-9' } } })
    render(<PriceBooksPage />)
    fireEvent.change(screen.getByTestId('price-books-sku'), { target: { value: '1024' } })
    await waitFor(() => expect(screen.getByTestId('price-books-empty-protocol')).toBeInTheDocument())

    fireEvent.click(screen.getByText('新增价格'))
    fireEvent.change(screen.getByTestId('price-books-target'), { target: { value: 'c-9' } })
    fireEvent.change(screen.getByTestId('price-books-price'), { target: { value: '50' } })
    fireEvent.click(screen.getByTestId('price-books-save'))

    // 服务端原话照旧上屏
    await waitFor(() => expect(screen.getByTestId('price-books-form-error').textContent).toContain('改价'))
    // 申请入口自动摆出来：对象 = SKU 1024，金额不预填（前端拿不到成本价）但提示点名门槛
    expect((await screen.findByTestId('approval-request-target')).textContent).toContain('SKU 1024')
    expect((screen.getByTestId('approval-request-amount') as HTMLInputElement).value).toBe('')
    expect(screen.getByTestId('approval-request-amount-hint').textContent).toContain('成本价')

    fireEvent.change(screen.getByTestId('approval-request-amount'), { target: { value: '95' } })
    fireEvent.change(screen.getByTestId('approval-request-reason'), { target: { value: '老客户长期合作' } })
    fireEvent.click(screen.getByTestId('approval-request-submit'))
    await waitFor(() =>
      expect(approvalApi.submit).toHaveBeenCalledWith(
        expect.objectContaining({
          objectType: 'price_change',
          objectRef: '1024',
          amount: 95,
          reason: '老客户长期合作',
        }),
      ),
    )
  })
})
