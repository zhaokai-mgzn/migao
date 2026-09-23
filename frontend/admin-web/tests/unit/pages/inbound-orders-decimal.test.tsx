// case_ids: PR-046, PR-048, PR-062, UI-055
//
// 入库单页面 —— **库存米数小数化（0.1 米粒度，issue #5063）** 的前端动线。
//   PR-045 = 库存米数支持 1 位小数（入库 60.5 米被接受、**原值**提交）；
//   PR-047 = 超过 1 位小数 ⇒ **显式拒绝**（fail-closed、文案说清位数、**不静默取整/截断**）。
//   ⚠️ 判据本体在 src/lib/stock-quantity.ts（纯函数，见 tests/unit/lib/stock-quantity.test.ts）；
//   本文件守的是「它**确实被接进了提交前校验与展示**」——
//   后端把库存/数量列升到 NUMERIC(12,1) 后，前端必须与后端同一判据，不能只在 lib 里对。
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

/** 建单弹窗走法复用既有 tests/unit/pages/inbound-orders.test.tsx：选商品 → 勾 SKU → 数量输入框。 */
async function openCreateWithLine() {
  fireEvent.click(screen.getByRole('button', { name: /新建入库单/ }))
  fireEvent.change(screen.getByPlaceholderText('商品名称 / 货号'), { target: { value: '遮光' } })
  fireEvent.click(await screen.findByRole('button', { name: /遮光窗帘布/ }))
  fireEvent.click(await screen.findByRole('checkbox'))
  return screen.findByLabelText(/数量$/)
}

/** 渲染页面 → 填一个数量 → 点「保存为草稿」。 */
async function submitQuantity(value: string) {
  render(<InboundOrdersPage />)
  await screen.findByText('RK-20260923-0001')
  const qty = await openCreateWithLine()
  fireEvent.change(qty, { target: { value } })
  fireEvent.click(screen.getByRole('button', { name: '保存为草稿' }))
}

describe('入库数量：1 位小数（PR-045，issue #5063）', () => {
  it('60.5 米通过提交前校验，并按**原值** 60.5 提交（改前 Number.isInteger 必红）', async () => {
    mockCreate.mockResolvedValue({ data: { data: decimalDetail } })
    await submitQuantity('60.5')

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1))
    // 原值提交：不得被取整成 61、也不得被截断成 60。
    expect(mockCreate.mock.calls[0][0].items).toEqual([
      {
        productId: 'prod-1',
        skuId: 11,
        quantity: 60.5,
        unitCost: null,
        dyeLot: null,
        // 采购收货（缺省来源）不带旧系统批次号（V118 / issue #5153）
        legacyBatchNo: null,
        rollLengthM: null,
      },
    ])
    const { toast } = await import('sonner')
    expect(toast.error).not.toHaveBeenCalled()
  })

  it('整数 10 逐值不变地通过（本单只放开小数位，不改整数场景）', async () => {
    mockCreate.mockResolvedValue({ data: { data: decimalDetail } })
    await submitQuantity('10')

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1))
    expect(mockCreate.mock.calls[0][0].items[0].quantity).toBe(10)
  })
})

describe('入库数量：超 1 位小数显式拒绝（PR-047，issue #5063）', () => {
  it.each(['2.755', '1.05'])(
    '%s ⇒ 提交前拦下（不静默取整），文案含「1 位小数」，且不调建单接口',
    async (value) => {
      await submitQuantity(value)

      const { toast } = await import('sonner')
      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('1 位小数')),
      )
      // 没有把 2.755 变成 2.8 / 2.7 发出去 —— fail-closed。
      expect(mockCreate).not.toHaveBeenCalled()
    },
  )

  // 下限自 issue #5153（GAP-12）起由「≥1 米」放宽为「**大于 0** 米」：
  //   0.5 米的实物尾料**必须能提交**（用户逐字：「剩余了大量的 0.5 米左右的批次布料」）；
  //   0 / 负数仍逐条被拒（放宽下限不等于取消下限）。判据本体见 lib/stock-quantity.test.ts。
  it('0.5 ⇒ **通过**（实物尾料可登记；改前被 ≥1 挡在提交前）', async () => {
    mockCreate.mockResolvedValue({ data: { data: decimalDetail } })
    await submitQuantity('0.5')

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1))
    expect(mockCreate.mock.calls[0][0].items[0].quantity).toBe(0.5)
  })

  it.each(['0', '-1'])('%s ⇒ 仍按「大于 0」下限拒绝（下限仍存在）', async (value) => {
    await submitQuantity(value)

    const { toast } = await import('sonner')
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('大于 0')),
    )
    expect(mockCreate).not.toHaveBeenCalled()
  })
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

// ========== 建单三格（数量 / 单价 / 卷长）的数值语义（issue #5228 缺口 2）==========
//
// ⚠️ 判据**不建在「`0.` 中间态」上**：jsdom 把 `type="number"` 的 `"0."` 归一成 `""`，
// 真 Chromium 归一成 `"0"`（#5228 主会话真浏览器实测，两套读数**相反**）。这里一律用
// `fireEvent.change` **一次给完整串**，钉的是与引擎无关的语义：
// 完整串 ⇒ 原值提交；空 ⇒ `null`（**不是 0**）；`0` ⇒ **不被当空**。
describe('入库三格（数量 / 单价 / 卷长）的数值语义 —— 与引擎无关（issue #5228 缺口 2）', () => {
  /** 打开建单弹窗 → 勾一行（默认数量 1）→ 返回三格 */
  async function threeCells() {
    render(<InboundOrdersPage />)
    await screen.findByText('RK-20260923-0001')
    const qty = await openCreateWithLine()
    return {
      qty,
      cost: screen.getByLabelText(/单价$/) as HTMLInputElement,
      roll: screen.getByLabelText(/卷长$/) as HTMLInputElement,
    }
  }

  it('三格各给完整串 `0.5` ⇒ 原值提交 0.5（不取整、不当空）', async () => {
    mockCreate.mockResolvedValue({ data: { data: decimalDetail } })
    const { qty, cost, roll } = await threeCells()
    fireEvent.change(qty, { target: { value: '0.5' } })
    fireEvent.change(cost, { target: { value: '0.5' } })
    fireEvent.change(roll, { target: { value: '0.5' } })
    fireEvent.click(screen.getByRole('button', { name: '保存为草稿' }))

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1))
    expect(mockCreate.mock.calls[0][0].items[0]).toMatchObject({
      quantity: 0.5,
      unitCost: 0.5,
      rollLengthM: 0.5,
    })
  })

  it('单价 / 卷长 留空 ⇒ `null`（**不是 0**）—— 「没填」与「填了 0」是两回事', async () => {
    mockCreate.mockResolvedValue({ data: { data: decimalDetail } })
    const { cost, roll } = await threeCells()
    // 空态先在自己这一层确认（不依赖 DOM 对非法数字的归一化，故也与引擎无关）
    expect(cost.value).toBe('')
    expect(roll.value).toBe('')
    fireEvent.click(screen.getByRole('button', { name: '保存为草稿' }))

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1))
    const item = mockCreate.mock.calls[0][0].items[0]
    expect(item.unitCost).toBeNull()
    expect(item.rollLengthM).toBeNull()
  })

  it('卷长 `0` 不被当空：输入 0 ⇒ 提交 rollLengthM: 0（不是 null）', async () => {
    mockCreate.mockResolvedValue({ data: { data: decimalDetail } })
    const { roll } = await threeCells()
    fireEvent.change(roll, { target: { value: '0' } })
    fireEvent.click(screen.getByRole('button', { name: '保存为草稿' }))

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1))
    expect(mockCreate.mock.calls[0][0].items[0].rollLengthM).toBe(0)
  })

  it('单价 `0` ⇒ 显式拒绝并说清口径（既不静默当 0 提交、也不静默当空）', async () => {
    const { cost } = await threeCells()
    fireEvent.change(cost, { target: { value: '0' } })
    fireEvent.click(screen.getByRole('button', { name: '保存为草稿' }))

    const { toast } = await import('sonner')
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('入库单价必须大于 0')),
    )
    expect(mockCreate).not.toHaveBeenCalled()
  })
})
