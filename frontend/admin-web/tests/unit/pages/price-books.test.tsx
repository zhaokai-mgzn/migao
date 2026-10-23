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
const productApi = vi.hoisted(() => ({ getProducts: vi.fn(), getProduct: vi.fn() }))
vi.mock('@/lib/api', () => ({ priceBookApi, approvalApi, productApi }))
vi.mock('@/lib/permission', () => ({ usePermission: () => ({ has: () => true, permissions: [], isAdmin: true }) }))

const wrap = <T,>(data: T) => Promise.resolve({ data: { success: true, data } })

/** 线上真实量级：SKU id 是雪花号字符串（> 2^53），`Number()` 会吞末位（#5904 同族） */
const SKU_ID = '2097126615461462018'
const EMPTY_BOOK = { skuId: SKU_ID, protocol: [], vipLevels: [], tiers: [] }

/** 选 SKU 的走法（issue #7567）：搜商品 → 点商品 → 单选那个 SKU（**没有**手打编号的输入框） */
async function pickSku() {
  fireEvent.change(screen.getByLabelText('搜索商品'), { target: { value: '遮光' } })
  fireEvent.click(await screen.findByRole('button', { name: /遮光窗帘布/ }, { timeout: 3000 }))
  fireEvent.click(await screen.findByRole('radio', undefined, { timeout: 3000 }))
}

describe('价格本页面', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    priceBookApi.list.mockImplementation(() => wrap(EMPTY_BOOK))
    productApi.getProducts.mockResolvedValue({
      data: { data: { items: [{ id: 'prod-1', name: '遮光窗帘布', skuCode: 'HUOHAO-01' }] } },
    })
    productApi.getProduct.mockResolvedValue({
      data: {
        data: {
          id: 'prod-1',
          name: '遮光窗帘布',
          skus: [{ id: SKU_ID, colorName: '米白', doorWidth: '3.2', stock: 86, price: 30, status: 'active' }],
        },
      },
    })
  })

  it('🔴 没选 SKU 时只给提示，不打接口；页面上**没有**手打 SKU 编号的输入框（issue #7567）', async () => {
    render(<PriceBooksPage />)
    await waitFor(() => expect(screen.getByTestId('price-books-hint')).toBeInTheDocument())
    expect(screen.queryByTestId('price-books-sku')).not.toBeInTheDocument()
    expect(priceBookApi.list).not.toHaveBeenCalled()
  })

  it('🔴 选中的 SKU 原样字符串交给后端（雪花号不得经 Number() 截断，issue #5904 同族）', async () => {
    render(<PriceBooksPage />)
    await pickSku()

    await waitFor(() => expect(priceBookApi.list).toHaveBeenCalled())
    const params = priceBookApi.list.mock.calls[0][0] as { skuId: unknown }
    expect(typeof params.skuId).toBe('string')
    expect(params.skuId).toBe(SKU_ID)
    expect(params.skuId).not.toBe(String(Number(SKU_ID)))
    // 页面上说清「正在维护哪个 SKU」，且**不印**雪花号
    await waitFor(() => expect(screen.getByTestId('price-books-selected')).toHaveTextContent('遮光窗帘布'))
    expect(screen.queryByText(SKU_ID)).not.toBeInTheDocument()
  })

  it('三层价格为空时各自显示「未设置」，**不显示 ¥0.00**', async () => {
    render(<PriceBooksPage />)
    await pickSku()

    await waitFor(() => expect(screen.getByTestId('price-books-empty-protocol')).toBeInTheDocument())
    expect(screen.getByTestId('price-books-empty-vip-level')).toBeInTheDocument()
    expect(screen.getByTestId('price-books-empty-tier')).toBeInTheDocument()
    expect(screen.getByTestId('price-books-empty-protocol').textContent).toContain('未设置')
    expect(document.body.textContent).not.toContain('¥0.00')
  })

  it('有价时按层列出（协议价显示客户、等级价显示等级、阶梯价显示门槛）', async () => {
    priceBookApi.list.mockImplementation(() => wrap({
      skuId: SKU_ID,
      protocol: [{ id: 'p1', customer_id: 'c-9', price: 88 }],
      vipLevels: [{ id: 'v1', vip_level: 'vip2', price: 92 }],
      tiers: [{ id: 't1', min_qty: 50, max_qty: 99, price: 85 }],
    }))
    render(<PriceBooksPage />)
    await pickSku()

    await waitFor(() => expect(screen.getByTestId('price-books-list-protocol')).toBeInTheDocument())
    expect(screen.getByTestId('price-books-list-protocol').textContent).toContain('c-9')
    expect(screen.getByTestId('price-books-list-vip-level').textContent).toContain('vip2')
    expect(screen.getByTestId('price-books-list-tier').textContent).toContain('满 50 米')
  })

  it('🔴 价格 ≤ 0 时前端先拦（0 元等于白送），且不打保存接口', async () => {
    render(<PriceBooksPage />)
    await pickSku()
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
    await pickSku()
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
    await pickSku()
    await waitFor(() => expect(screen.getByTestId('price-books-empty-protocol')).toBeInTheDocument())

    fireEvent.click(screen.getByText('新增价格'))
    fireEvent.change(screen.getByTestId('price-books-target'), { target: { value: 'c-9' } })
    fireEvent.change(screen.getByTestId('price-books-price'), { target: { value: '50' } })
    fireEvent.click(screen.getByTestId('price-books-save'))

    // 服务端原话照旧上屏
    await waitFor(() => expect(screen.getByTestId('price-books-form-error').textContent).toContain('改价'))
    // 申请入口自动摆出来：对象 = 选中的 SKU（展示名），金额不预填（前端拿不到成本价）但提示点名门槛
    expect((await screen.findByTestId('approval-request-target')).textContent).toContain('遮光窗帘布')
    expect((screen.getByTestId('approval-request-amount') as HTMLInputElement).value).toBe('')
    expect(screen.getByTestId('approval-request-amount-hint').textContent).toContain('成本价')

    fireEvent.change(screen.getByTestId('approval-request-amount'), { target: { value: '95' } })
    fireEvent.change(screen.getByTestId('approval-request-reason'), { target: { value: '老客户长期合作' } })
    fireEvent.click(screen.getByTestId('approval-request-submit'))
    await waitFor(() =>
      expect(approvalApi.submit).toHaveBeenCalledWith(
        expect.objectContaining({
          objectType: 'price_change',
          objectRef: SKU_ID,
          amount: 95,
          reason: '老客户长期合作',
        }),
      ),
    )
  })
})
