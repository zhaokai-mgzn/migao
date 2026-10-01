// case_ids: PR-037, UI-074
//
// PR-037（issue #5034，V111）：入库单页面 —— 「建单（草稿，不动库存）→ 过账（自动生成批次号 +
//   自动加库存）→ 批次可追溯」这条动线在**前端**的可达性。
//   本文件只守**列表页**能守的部分：页面能渲染列表、建单入口**导航到独立整页**
//   `/inbound-orders/new`（issue #5844：建单不再是弹窗）、批次号在列表可见（UI-074）、
//   过账按钮只在草稿态出现。
//   🔴 建单表单本身的判据（一行 = 一个批次 / 数量口径 / 期初建账 / 明细批次号列）已随建单入口
//   迁到 `tests/unit/pages/inbound-orders-new.test.tsx`（**一条未弱化**，只是换了落点）。
//   （小数口径的判据本体见 tests/unit/lib/stock-quantity.test.ts 与 inbound-orders-decimal.test.tsx）
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

// 导航断言要拿到**稳定**的 push（setup.ts 里的 next/navigation mock 每次调用都新建 vi.fn）
const { mockPush, stableRouter } = vi.hoisted(() => {
  const mockPush = vi.fn()
  return {
    mockPush,
    stableRouter: {
      push: mockPush,
      replace: vi.fn(),
      back: vi.fn(),
      forward: vi.fn(),
      refresh: vi.fn(),
      prefetch: vi.fn(),
    },
  }
})

vi.mock('next/navigation', () => ({
  useRouter: () => stableRouter,
  usePathname: () => '/inbound-orders',
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
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

  it('「新建入库单」**导航**到独立整页 /inbound-orders/new（issue #5844：不再是弹窗）', async () => {
    render(<InboundOrdersPage />)
    await screen.findByText('RK-20260923-0001')

    fireEvent.click(screen.getByRole('button', { name: /新建入库单/ }))

    expect(mockPush).toHaveBeenCalledWith('/inbound-orders/new')
    // 🔴 本页**不得**因此出现建单表单：建单是那个整页的事（改前这里弹 `Modal`、
    //    商品结果被页脚截断 = 用户说的「布局很怪异」）
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '保存为草稿' })).not.toBeInTheDocument()
  })

  it('列表有「批次号」列：已过账显示真值、草稿显示「过账后生成」、作废显示「-」（UI-074）', async () => {
    mockList.mockResolvedValue({
      data: {
        data: [
          { ...draftRow, id: 'o-2', inboundNo: 'RK-20260923-0002', status: 'posted', batchNos: 'PC-20260923-0001' },
          { ...draftRow, batchNos: null },
          { ...draftRow, id: 'o-3', inboundNo: 'RK-20260923-0003', status: 'cancelled', batchNos: null },
        ],
      },
    })
    render(<InboundOrdersPage />)
    await screen.findByText('RK-20260923-0002')

    const table = screen.getByRole('table')
    expect(within(table).getByText('批次号')).toBeInTheDocument()

    const cellOf = (no: string) =>
      within(screen.getByText(no).closest('tr') as HTMLElement).getByTestId('inbound-batch-nos')
    // 已过账：显示服务端给的真值（前端不生成号段）
    expect(cellOf('RK-20260923-0002').textContent).toBe('PC-20260923-0001')
    // 草稿：未过账 ⇒ 「过账后生成」（批次号 = 「真的收货了」的标识，草稿不发号）
    expect(cellOf('RK-20260923-0001').textContent).toBe('过账后生成')
    // 作废：永远不会过账 ⇒ 「-」，**不**谎报成「过账后生成」
    expect(cellOf('RK-20260923-0003').textContent).toBe('-')
  })

  it('一个单多批次 ⇒ 聚合成「首个 等 N 个」（列表不把 N 个批次铺成 N 行）', async () => {
    mockList.mockResolvedValue({
      data: {
        data: [
          {
            ...draftRow,
            status: 'posted',
            batchNos: 'PC-20260923-0001,PC-20260923-0002,PC-20260923-0003',
          },
        ],
      },
    })
    render(<InboundOrdersPage />)
    await screen.findByText('RK-20260923-0001')

    const cell = within(screen.getByText('RK-20260923-0001').closest('tr') as HTMLElement).getByTestId(
      'inbound-batch-nos',
    )
    expect(cell.textContent).toBe('PC-20260923-0001 等 3 个')
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
