// case_ids: PR-046
//
// 入库单**读面**的小数展示口径（issue #5063）。
//   PR-045 = 库存米数支持 1 位小数（展示与提交同口径）。
//   ⚠️ 判据本体在 src/lib/stock-quantity.ts（纯函数，见 tests/unit/lib/stock-quantity.test.ts）；
//   本文件守的是「它**确实被接进了列表与详情的展示**」—— 后端把库存/数量列升到 NUMERIC(12,1) 后，
//   前端必须与后端同一判据，不能只在 lib 里对。
//
// 🔴 建单侧（数量/单价/卷长的提交语义、超精度拒绝、0.5 米可提交）**已迁到
//    `tests/unit/pages/inbound-orders-new.test.tsx`**（issue #5844：建单从弹窗改为独立整页
//    `/inbound-orders/new`）—— **判据一条未弱化**，只是换了落点；本文件只留读面。
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'

const mockList = vi.fn()
const mockDetail = vi.fn()

vi.mock('@/lib/api', () => ({
  inboundOrderApi: {
    list: (...a: unknown[]) => mockList(...a),
    detail: (...a: unknown[]) => mockDetail(...a),
    create: vi.fn(),
    post: vi.fn(),
    cancel: vi.fn(),
  },
  productApi: {
    getProducts: vi.fn(),
    getProduct: vi.fn(),
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
  totalAmount: 915,
  itemCount: 4,
  totalQuantity: 76.5,
}

/**
 * 明细四行 = 展示口径的四类形态：整数 / 一位小数 / **真浮点毛刺** / 字面量毛刺（实为 2.7）。
 * ⚠️ `2.7000000000000002` 这个字面量**就是 double 2.7**（最短表示 "2.7"）⇒ 它渲染成 "2.7"
 *    并不证明格式化生效；真正能证明的是 `1.1 + 2.2 = 3.3000000000000003` 那行。
 */
const decimalDetail = {
  id: 'o-1',
  inboundNo: 'RK-20260923-0001',
  inboundDate: '2026-09-23',
  supplier: '柯桥××布行',
  status: 'draft' as const,
  totalAmount: 915,
  items: [
    {
      id: 1,
      skuId: 11,
      productId: 'prod-1',
      skuCode: 'SKU-HALF',
      colorName: '米白',
      doorWidth: '2.8',
      quantity: 60.5,
      unitCost: 12.5,
      amount: 756.25,
      batchNo: null,
      dyeLot: 'G-1',
    },
    {
      id: 2,
      skuId: 12,
      productId: 'prod-1',
      skuCode: 'SKU-INT',
      colorName: '米白',
      doorWidth: '2.8',
      quantity: 10,
      unitCost: 12.5,
      amount: 125,
      batchNo: null,
      dyeLot: 'G-2',
    },
    {
      id: 3,
      skuId: 13,
      productId: 'prod-1',
      skuCode: 'SKU-FLOAT',
      colorName: '米白',
      doorWidth: '2.8',
      quantity: 1.1 + 2.2, // 3.3000000000000003
      unitCost: 12.5,
      amount: 41.25,
      batchNo: null,
      dyeLot: 'G-3',
    },
    {
      id: 4,
      skuId: 14,
      productId: 'prod-1',
      skuCode: 'SKU-NOISE',
      colorName: '米白',
      doorWidth: '2.8',
      quantity: 2.7000000000000002, // === 2.7
      unitCost: 12.5,
      amount: 33.75,
      batchNo: null,
      dyeLot: 'G-4',
    },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  mockList.mockResolvedValue({ data: { data: [draftRow] } })
})

describe('数量展示口径：最多 1 位小数、无浮点毛刺（PR-045）', () => {
  it('列表「行数 / 总数量」按 1 位小数收敛：73.80000000000001 ⇒ 4 / 73.8', async () => {
    mockList.mockResolvedValue({
      data: { data: [{ ...draftRow, itemCount: 4, totalQuantity: 73.80000000000001 }] },
    })
    render(<InboundOrdersPage />)
    await screen.findByText('RK-20260923-0001')

    expect(screen.getByText('4 / 73.8')).toBeInTheDocument()
    expect(screen.queryByText(/73\.80000000000001/)).not.toBeInTheDocument()
  })

  it('明细数量：60.5 ⇒ "60.5"、10 ⇒ "10"、3.3000000000000003 ⇒ "3.3"、2.7000000000000002 ⇒ "2.7"', async () => {
    mockDetail.mockResolvedValueOnce({ data: { data: decimalDetail } })
    render(<InboundOrdersPage />)
    await screen.findByText('RK-20260923-0001')

    const listRow = screen.getByText('RK-20260923-0001').closest('tr')!
    fireEvent.click(within(listRow).getByRole('button', { name: '详情' }))

    const rowOf = (sku: string) =>
      within(screen.getByText(sku, { exact: false }).closest('tr') as HTMLElement)
    await screen.findByText('SKU-HALF', { exact: false })
    expect(rowOf('SKU-HALF').getByText('60.5')).toBeInTheDocument()
    expect(rowOf('SKU-INT').getByText('10')).toBeInTheDocument()
    // 真毛刺：直接用原值渲染（`<td>{it.quantity}</td>`）会打出 3.3000000000000003 ⇒ 这条必红。
    expect(rowOf('SKU-FLOAT').getByText('3.3')).toBeInTheDocument()
    expect(screen.queryByText('3.3000000000000003')).not.toBeInTheDocument()
    expect(rowOf('SKU-NOISE').getByText('2.7')).toBeInTheDocument()
  })
})
