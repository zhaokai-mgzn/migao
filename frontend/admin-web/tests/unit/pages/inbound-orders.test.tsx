// case_ids: PR-037
//
// PR-037（issue #5034，V111）：入库单页面 —— 「建单（草稿，不动库存）→ 过账（自动生成批次号 +
//   自动加库存）→ 批次可追溯」这条动线在**前端**的可达性。
//   本文件只守前端能守的部分：页面能渲染列表、建单弹窗把明细按「一行 = 一个批次」提交、
//   数量必须 ≥1 的整数在**提交前**就被挡住（不是等后端 400）、过账按钮只在草稿态出现。
//   「过账真的加了库存 / 批次号真的生成了 / 成本真的按移动加权平均算了」由后端守：
//   backend/admin-api/src/test/java/com/migao/admin/service/InboundOrderServiceTest.java（PR-029~033）。
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'

const mockList = vi.fn()
const mockDetail = vi.fn()
const mockCreate = vi.fn()
const mockPost = vi.fn()
const mockCancel = vi.fn()
const mockGetProducts = vi.fn()
const mockGetProduct = vi.fn()

vi.mock('@/lib/api', () => ({
  inboundOrderApi: {
    list: (...a: unknown[]) => mockList(...a),
    detail: (...a: unknown[]) => mockDetail(...a),
    create: (...a: unknown[]) => mockCreate(...a),
    post: (...a: unknown[]) => mockPost(...a),
    cancel: (...a: unknown[]) => mockCancel(...a),
  },
  productApi: {
    getProducts: (...a: unknown[]) => mockGetProducts(...a),
    getProduct: (...a: unknown[]) => mockGetProduct(...a),
  },
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

import InboundOrdersPage from '@/app/(dashboard)/inbound-orders/page'

const draftRow = {
  id: 'o-1',
  inboundNo: 'RK-20260923-0001',
  inboundDate: '2026-09-23',
  supplier: '柯桥××布行',
  warehouse: '一号仓',
  status: 'draft' as const,
  totalAmount: 375,
  itemCount: 1,
  totalQuantity: 30,
}

const postedRow = { ...draftRow, id: 'o-2', inboundNo: 'RK-20260923-0002', status: 'posted' as const }

const draftDetail = {
  id: 'o-1',
  inboundNo: 'RK-20260923-0001',
  inboundDate: '2026-09-23',
  supplier: '柯桥××布行',
  status: 'draft' as const,
  totalAmount: 375,
  items: [
    {
      id: 100,
      skuId: 11,
      productId: 'prod-1',
      skuCode: 'HUOHAO-01',
      colorName: '米白',
      doorWidth: '2.8',
      quantity: 30,
      unitCost: 12.5,
      amount: 375,
      batchNo: null,
      dyeLot: 'G-2026-0912',
    },
  ],
}

const postedDetail = {
  ...draftDetail,
  status: 'posted' as const,
  postedBy: '13800000000',
  postedAt: '2026-09-23T10:00:00Z',
  items: [{ ...draftDetail.items[0], batchNo: 'PC-20260923-0001' }],
}

beforeEach(() => {
  vi.clearAllMocks()
  mockList.mockResolvedValue({ data: { data: [draftRow, postedRow] } })
  mockGetProducts.mockResolvedValue({
    data: { data: { items: [{ id: 'prod-1', name: '遮光窗帘布', skuCode: 'HUOHAO-01' }] } },
  })
  mockGetProduct.mockResolvedValue({
    data: {
      data: {
        id: 'prod-1',
        name: '遮光窗帘布',
        skus: [
          { id: '11', colorName: '米白', doorWidth: '2.8', sellingMethod: 'bulk_cut', price: 30, stock: 5 },
        ],
      },
    },
  })
})

describe('入库单页面（PR-037 / issue #5034）', () => {
  it('渲染列表：单号、状态、行数/总数量都在（列表不是空壳）', async () => {
    render(<InboundOrdersPage />)

    expect(await screen.findByText('RK-20260923-0001')).toBeInTheDocument()
    expect(screen.getByText('RK-20260923-0002')).toBeInTheDocument()
    // 状态列：草稿与已过账各一条。
    // ⚠️ 断言限定在**表格内** —— 「草稿」在状态下拉框的选项里也出现一次，
    //    用全局 getByText 会命中两个元素（那是断言写错，不是页面错）。
    const table = screen.getByRole('table')
    expect(within(table).getByText('草稿')).toBeInTheDocument()
    expect(within(table).getByText('已过账')).toBeInTheDocument()
    // 行数 / 总数量聚合
    expect(screen.getAllByText('1 / 30').length).toBe(2)
    expect(mockList).toHaveBeenCalledWith({ keyword: undefined, status: '' })
  })

  it('建单：勾选 SKU 后按「一行 = 一个批次」提交，数量与单价随行提交', async () => {
    mockCreate.mockResolvedValue({ data: { data: draftDetail } })
    render(<InboundOrdersPage />)
    await screen.findByText('RK-20260923-0001')

    fireEvent.click(screen.getByRole('button', { name: /新建入库单/ }))
    // 商品搜索结果出现后选中商品 → 加载 SKU
    fireEvent.change(screen.getByPlaceholderText('商品名称 / 货号'), { target: { value: '遮光' } })
    const productBtn = await screen.findByRole('button', { name: /遮光窗帘布/ })
    fireEvent.click(productBtn)

    const skuCheckbox = await screen.findByRole('checkbox')
    fireEvent.click(skuCheckbox)

    // 明细行出现：数量默认 1，改为 30、填单价 12.5、填缸号
    const qty = await screen.findByLabelText(/数量$/)
    fireEvent.change(qty, { target: { value: '30' } })
    fireEvent.change(screen.getByLabelText(/单价$/), { target: { value: '12.5' } })
    fireEvent.change(screen.getByLabelText(/缸号$/), { target: { value: 'G-2026-0912' } })

    fireEvent.click(screen.getByRole('button', { name: '保存为草稿' }))

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1))
    const payload = mockCreate.mock.calls[0][0]
    expect(payload.items).toEqual([
      {
        productId: 'prod-1',
        skuId: 11,
        quantity: 30,
        unitCost: 12.5,
        dyeLot: 'G-2026-0912',
        rollLengthM: null,
      },
    ])
    // 草稿态提交 —— 不得调过账
    expect(mockPost).not.toHaveBeenCalled()
  })

  it('数量非整数 ⇒ 提交前就被挡住（不把 0.5 米发给后端），且不调建单接口', async () => {
    render(<InboundOrdersPage />)
    await screen.findByText('RK-20260923-0001')

    fireEvent.click(screen.getByRole('button', { name: /新建入库单/ }))
    fireEvent.change(screen.getByPlaceholderText('商品名称 / 货号'), { target: { value: '遮光' } })
    fireEvent.click(await screen.findByRole('button', { name: /遮光窗帘布/ }))
    fireEvent.click(await screen.findByRole('checkbox'))

    fireEvent.change(await screen.findByLabelText(/数量$/), { target: { value: '0.5' } })
    fireEvent.click(screen.getByRole('button', { name: '保存为草稿' }))

    expect(mockCreate).not.toHaveBeenCalled()
    const { toast } = await import('sonner')
    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('≥1 的整数'))
  })

  it('详情：草稿态显示「过账后生成」且有过账按钮；过账后显示批次号、过账按钮消失', async () => {
    mockDetail.mockResolvedValueOnce({ data: { data: draftDetail } })
    render(<InboundOrdersPage />)
    await screen.findByText('RK-20260923-0001')

    // 打开草稿单详情
    const draftRowEl = screen.getByText('RK-20260923-0001').closest('tr')!
    fireEvent.click(within(draftRowEl).getByRole('button', { name: '详情' }))
    expect(await screen.findByText('过账后生成')).toBeInTheDocument()
    const postBtn = screen.getByRole('button', { name: /过账（生成批次号并加库存）/ })
    expect(postBtn).toBeInTheDocument()

    // 过账 → 详情刷新为已过账（批次号出现）
    mockPost.mockResolvedValue({ data: { data: postedDetail } })
    mockList.mockResolvedValue({ data: { data: [postedRow] } })
    fireEvent.click(postBtn)

    expect(await screen.findByText('PC-20260923-0001')).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /过账（生成批次号并加库存）/ })).not.toBeInTheDocument(),
    )
  })

  it('已过账的单：详情里没有过账/作废入口（库存已进台账，冲销须另开单据）', async () => {
    mockDetail.mockResolvedValueOnce({ data: { data: postedDetail } })
    render(<InboundOrdersPage />)
    await screen.findByText('RK-20260923-0002')

    const postedRowEl = screen.getByText('RK-20260923-0002').closest('tr')!
    fireEvent.click(within(postedRowEl).getByRole('button', { name: '详情' }))

    expect(await screen.findByText('PC-20260923-0001')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /过账（生成批次号并加库存）/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '作废' })).not.toBeInTheDocument()
  })
})
