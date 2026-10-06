// case_ids: UI-087, UI-089
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

/**
 * 库存明细页（`/stock-ledger`，issue #6404）—— 大菜单「仓储与物料 ▸ 库存明细」的第一屏。
 *
 * ## 这个页面存在的理由
 *
 * 后端只读端点 `GET /api/admin/stock-ledger`（issue #4055）**早就有了**，
 * agent 工具 `stock_ledger_query`（issue #5247）也有 —— **只有页面没有**：
 * `StockLedgerController` 的 javadoc 逐字登记「本轮只做只读端点，不做前端页面」。
 * 后果 = 同一个问题（「为什么系统说还有 30 米、实际只剩 12 米」）**米宝答得出来、商家点不出来**。
 *
 * ## 本文件钉住的三件事（每条都能单独变红）
 *
 * ① **流水看得见**：时间 / 货号·SKU / 变动 / 变动前 / 变动后 / 原因 / 单据号 / 操作人 / 成本；
 * ② 🔴 **成本 NULL = 「未知」**，不是 `¥0.00`、不是空白 —— `StockLedger` 的 javadoc 逐字：
 *    「NULL = 该次变更发生时成本未知（存量行全部为 NULL，**不伪造**）」；
 * ③ 🔴 **页面不重算**：`delta` / `beforeQty` / `afterQty` / 金额一律**原样渲染服务端值**
 *    （第二份口径必然会漂）；判别器 = 下面的**见证行**。
 *
 * ## 本文件另钉两件事（issue #6417 新增，UI-089）
 *
 * ④ **批次余量（每卷剩多少）看得见**：用户 2026-10-06 逐字「库存明细还是缺乏单批次的剩余量，
 *    比如 1 卷 = 67 米，经过加工裁剪后应该有个剩余米数」⇒ 视图 ② 一行 = 一个批次，
 *    `入库米数 / 已消耗 / **剩余米数**` 三列都在；
 * ⑤ 🔴 **批次视图也不重算**：`remainingMeters` 原样渲染（见证批次里它与 `inbound − consumed` 故意不等）。
 *
 * 菜单三源同构另见 `frontend/admin-web/tests/unit/lib/stock-ledger-menu-isomorphic.test.ts`。
 */

const mockLedger = vi.fn()
const mockGetProducts = vi.fn()
const mockBatches = vi.fn()

vi.mock('@/lib/api', () => ({
  stockLedgerApi: { ledger: (...args: unknown[]) => mockLedger(...args) },
  productApi: { getProducts: (...args: unknown[]) => mockGetProducts(...args) },
  batchStockApi: { batches: (...args: unknown[]) => mockBatches(...args) },
}))

/** 一行入库过账：成本三列都有值 */
const inboundRow = {
  id: 2,
  productId: 'prod-1',
  skuId: 12,
  skuCode: 'HZ-001-米白',
  delta: '50.0',
  beforeQty: '0.0',
  afterQty: '50.0',
  reason: 'inbound',
  refNo: 'RK-20261001-0001',
  note: null,
  unitCost: '24.80',
  costAmount: '1240.00',
  avgCostBefore: null,
  avgCostAfter: '24.80',
  operator: 'zhangsan',
  createdAt: '2026-10-01T10:00:00+08:00',
}

/** 存量行：成本三列全 NULL（= 成本未知，**不伪造 0**） */
const legacyRow = {
  id: 1,
  productId: 'prod-1',
  skuId: 9,
  skuCode: 'HZ-002-浅灰',
  delta: '-3.0',
  beforeQty: '50.0',
  afterQty: '47.0',
  reason: 'aftersales',
  refNo: 'AS-20260918-0001',
  note: null,
  unitCost: null,
  costAmount: null,
  avgCostBefore: null,
  avgCostAfter: null,
  operator: 'system',
  createdAt: '2026-09-18T09:00:00+08:00',
}

/**
 * 🔴 **见证行（witness）** —— 断言「页面不重算」的**唯一判别器**：
 * 服务端下发的 `delta` / `costAmount` 与「拿 before/after 现算」**故意不等**：
 *   · `delta: '-2.0'`，而 `afterQty − beforeQty = 4.0 − 10.0 =` **-6.0**；
 *   · `costAmount: '74.40'`，而 `|delta| × unitCost = 3 × 1.00 =` **3.00**。
 * 页面若自行重算 ⇒ 渲染出 -6 / ¥3.00 ⇒ 判据 ③ 红。
 *
 * ⚠️ 这行**不代表线上形态**（生产数据里两者恒等 —— 服务端在同一次写入里算出），
 * 它只作判别见证：**唯一能区分「渲染服务端值」与「现算」的输入，就是两者不等的输入**。
 */
const witnessRow = {
  id: 3,
  productId: 'prod-1',
  skuId: 20,
  skuCode: 'HZ-003-深蓝',
  delta: '-2.0',
  beforeQty: '10.0',
  afterQty: '4.0',
  reason: 'manual',
  refNo: null,
  note: '盘点差异',
  unitCost: '1.00',
  costAmount: '74.40',
  avgCostBefore: null,
  avgCostAfter: null,
  operator: 'lisi',
  createdAt: '2026-10-02T08:00:00+08:00',
}

const paged = (items: unknown[], total = items.length) => ({
  data: { data: { items, total, page: 1, size: 20 } },
})

import StockLedgerPage from '@/app/(dashboard)/stock-ledger/page'

beforeEach(() => {
  vi.clearAllMocks()
  mockLedger.mockResolvedValue(paged([inboundRow, legacyRow]))
  mockGetProducts.mockResolvedValue(paged([{ id: 'prod-1', name: '遮光窗帘布料' }]))
})

describe('库存明细页（issue #6404 / UI-087）', () => {
  it('① 流水看得见：时间 / 货号·SKU / 变动 / 变动前 / 变动后 / 原因 / 单据号 / 操作人 / 成本', async () => {
    render(<StockLedgerPage />)

    const rows = await screen.findAllByTestId('stock-ledger-row')
    expect(rows).toHaveLength(2)

    const cells = (i: number, id: string) =>
      screen.getAllByTestId(id)[i].textContent

    expect(cells(0, 'ledger-sku')).toContain('HZ-001-米白')
    expect(cells(0, 'ledger-delta')).toBe('+50')
    expect(cells(0, 'ledger-before')).toBe('0')
    expect(cells(0, 'ledger-after')).toBe('50')
    expect(cells(0, 'ledger-reason')).toBe('入库过账')
    expect(cells(0, 'ledger-refno')).toBe('RK-20261001-0001')
    expect(cells(0, 'ledger-operator')).toBe('zhangsan')
    expect(cells(0, 'ledger-cost')).toBe('¥1240.00')
    // 时间列非空（本地时区可读形态；不钉死格式，钉「不是空白」）
    expect(cells(0, 'ledger-time')).not.toBe('')
    expect(cells(0, 'ledger-time')).not.toBe('—')
  })

  it('② 成本 NULL ⇒「未知」（不是 ¥0.00、不是空白）；数量 NULL ⇒「-」', async () => {
    mockLedger.mockResolvedValue(
      paged([legacyRow, { ...inboundRow, id: 4, delta: null, beforeQty: null, afterQty: null }]),
    )
    render(<StockLedgerPage />)

    await screen.findAllByTestId('stock-ledger-row')
    const costs = screen.getAllByTestId('ledger-cost')
    // 存量行：unitCost / costAmount 全 NULL ⇒ 「未知」（**不得**回落成 0 或 ¥0.00）
    expect(costs[0].textContent).toBe('未知')
    expect(costs[0].textContent).not.toContain('0.00')
    // 数量缺值 ⇒ 「-」（与「成本未知」区分开：一个是读不出，一个是这行没有数）
    expect(screen.getAllByTestId('ledger-delta')[1].textContent).toBe('-')
    expect(screen.getAllByTestId('ledger-before')[1].textContent).toBe('-')
  })

  it('③ 页面不重算：见证行下渲染的是**服务端值**（现算会得 -6 / ¥3.00 ⇒ 本用例红）', async () => {
    mockLedger.mockResolvedValue(paged([witnessRow]))
    render(<StockLedgerPage />)

    await screen.findAllByTestId('stock-ledger-row')
    const text = screen.getByTestId('stock-ledger-row').textContent ?? ''
    // 服务端说 -2.0 ⇒ 显示 -2；`afterQty − beforeQty` = -6（页面若自算就露馅）
    expect(screen.getByTestId('ledger-delta').textContent).toBe('-2')
    expect(screen.getByTestId('ledger-before').textContent).toBe('10')
    expect(screen.getByTestId('ledger-after').textContent).toBe('4')
    // 服务端说 74.40 ⇒ 显示 ¥74.40；`|delta| × unitCost` = 3.00（页面若自算就露馅）
    expect(screen.getByTestId('ledger-cost').textContent).toBe('¥74.40')
    expect(text).not.toContain('-6')
    expect(text).not.toContain('¥3.00')
  })

  it('④ 未知 reason **原样显示**（不吞成空白 —— 读不出 ≠ 没有原因）', async () => {
    mockLedger.mockResolvedValue(paged([{ ...inboundRow, reason: 'stocktake' }]))
    render(<StockLedgerPage />)

    await screen.findAllByTestId('stock-ledger-row')
    expect(screen.getByTestId('ledger-reason').textContent).toBe('stocktake')
  })

  it('⑤ 商品筛选：先走既有商品搜索拿 productId，**绝不把关键词发给台账端点**', async () => {
    const user = userEvent.setup()
    render(<StockLedgerPage />)
    await screen.findAllByTestId('stock-ledger-row')

    await user.type(screen.getByLabelText('搜索商品'), '遮光')
    await user.click(screen.getByRole('button', { name: '搜索商品' }))
    await waitFor(() => expect(mockGetProducts).toHaveBeenCalled())
    expect(mockGetProducts.mock.calls[0][0]).toMatchObject({ keyword: '遮光' })

    // 选中候选 ⇒ 台账端点收到的是 productId（端点没有关键词参数）
    await user.click(await screen.findByTestId('product-option'))
    await waitFor(() =>
      expect(mockLedger).toHaveBeenLastCalledWith(
        expect.objectContaining({ productId: 'prod-1' }),
      ),
    )
    const lastParams = mockLedger.mock.calls.at(-1)![0] as Record<string, unknown>
    for (const forbidden of ['keyword', 'name', 'skuCode']) {
      expect(Object.keys(lastParams)).not.toContain(forbidden)
    }
    expect(screen.getByTestId('selected-product').textContent).toContain('遮光窗帘布料')
  })

  it('⑥ 单据号筛选 + 重置：refNo 透传；重置回到无筛选', async () => {
    const user = userEvent.setup()
    render(<StockLedgerPage />)
    await screen.findAllByTestId('stock-ledger-row')

    await user.type(screen.getByLabelText('业务单据号'), 'RK-20261001-0001')
    await user.click(screen.getByRole('button', { name: '查询' }))
    await waitFor(() =>
      expect(mockLedger).toHaveBeenLastCalledWith(
        expect.objectContaining({ refNo: 'RK-20261001-0001' }),
      ),
    )

    await user.click(screen.getByRole('button', { name: '重置' }))
    expect(screen.getByLabelText('业务单据号')).toHaveValue('')
    await waitFor(() =>
      expect(mockLedger).toHaveBeenLastCalledWith(
        expect.objectContaining({ refNo: undefined }),
      ),
    )
  })

  it('⑦ 空列表 ⇒「暂无库存流水」（不显示假数据）', async () => {
    mockLedger.mockResolvedValue(paged([]))
    render(<StockLedgerPage />)

    expect(await screen.findByText('暂无库存流水')).toBeInTheDocument()
    expect(screen.queryAllByTestId('stock-ledger-row')).toHaveLength(0)
  })

  it('⑧ 读面失败 ⇒ 可行动话术（说清可能是权限，不是空白页）', async () => {
    mockLedger.mockRejectedValue(new Error('403'))
    render(<StockLedgerPage />)

    const err = await screen.findByTestId('stock-ledger-error')
    expect(err.textContent).toContain('权限')
    expect(screen.queryAllByTestId('stock-ledger-row')).toHaveLength(0)
  })
})

// ── 视图 ②：批次余量（issue #6417 / UI-089）──────────────────────────────────
/** 一行批次：一卷 67 米，裁剪掉 20 米 ⇒ 服务端说还剩 46.5（**故意**不等于 67−20，见 ⑩） */
const batchRow = {
  batchId: 11,
  batchNo: 'PC-20261001-0001',
  productId: 'prod-1',
  skuId: 12,
  skuCode: 'HZ-001-米白',
  inboundNo: 'RK-20261001-0001',
  dyeLot: 'G-77',
  receivedDate: '2026-10-01',
  unitCost: '24.80',
  inboundMeters: '67.0',
  consumedMeters: '20.0',
  remainingMeters: '46.5',
}

/** 一卷用尽的批次（余量 0）—— 表里仍然列出（「用完了」本身是要看的信息） */
const exhaustedRow = {
  ...batchRow,
  batchId: 12,
  batchNo: 'PC-20260920-0007',
  skuCode: 'HZ-002-浅灰',
  dyeLot: null,
  inboundMeters: '50.0',
  consumedMeters: '50.0',
  remainingMeters: '0.0',
}

const list = (items: unknown[]) => ({ data: { data: items } })

describe('批次余量视图（issue #6417 / UI-089）', () => {
  it('⑨ 每卷一行：批次号 / 货号·SKU / 缸号 / 入库单 / 入库米数 / 已消耗 / **剩余米数** / 收货日期', async () => {
    const user = userEvent.setup()
    mockBatches.mockResolvedValue(list([batchRow, exhaustedRow]))
    render(<StockLedgerPage />)
    await screen.findAllByTestId('stock-ledger-row')

    await user.click(screen.getByTestId('view-batch'))
    // 未选商品 ⇒ 显式提示（不是空白表）
    expect(await screen.findByTestId('batch-need-product')).toBeInTheDocument()

    await user.type(screen.getByLabelText('搜索商品'), '遮光')
    await user.click(screen.getByRole('button', { name: '搜索商品' }))
    await user.click(await screen.findByTestId('product-option'))

    const rows = await screen.findAllByTestId('batch-row')
    expect(rows).toHaveLength(2)
    expect(mockBatches).toHaveBeenLastCalledWith(expect.objectContaining({ productId: 'prod-1' }))

    const cells = (i: number, id: string) => screen.getAllByTestId(id)[i].textContent
    expect(cells(0, 'batch-no')).toBe('PC-20261001-0001')
    expect(cells(0, 'batch-sku')).toBe('HZ-001-米白')
    expect(cells(0, 'batch-dyelot')).toBe('G-77')
    expect(cells(0, 'batch-inbound-no')).toBe('RK-20261001-0001')
    expect(cells(0, 'batch-inbound')).toBe('67')
    expect(cells(0, 'batch-consumed')).toBe('20')
    // 🔴 用户要的那一列
    expect(cells(0, 'batch-remaining')).toBe('46.5')
    expect(cells(0, 'batch-received')).toBe('2026-10-01')
    // 缺值不空白、不伪造：缸号 null ⇒ 「—」；用尽的批次照样列出（余量 0 本身是要看的信息）
    expect(cells(1, 'batch-dyelot')).toBe('—')
    expect(cells(1, 'batch-remaining')).toBe('0')
  })

  it('⑩ 不重算：remainingMeters 原样渲染（见证批次 67−20 ≠ 46.5；现算会得 47 ⇒ 本用例红）', async () => {
    const user = userEvent.setup()
    mockBatches.mockResolvedValue(list([batchRow]))
    render(<StockLedgerPage />)
    await screen.findAllByTestId('stock-ledger-row')

    await user.click(screen.getByTestId('view-batch'))
    await user.type(screen.getByLabelText('搜索商品'), '遮光')
    await user.click(screen.getByRole('button', { name: '搜索商品' }))
    await user.click(await screen.findByTestId('product-option'))
    await screen.findAllByTestId('batch-row')

    const row = screen.getByTestId('batch-row').textContent ?? ''
    expect(screen.getByTestId('batch-remaining').textContent).toBe('46.5')
    expect(screen.getByTestId('batch-inbound').textContent).toBe('67')
    expect(screen.getByTestId('batch-consumed').textContent).toBe('20')
    // 现算值 47 不得出现（那意味着页面自己减了一遍 = 第二份会漂的口径）
    expect(row).not.toContain('47')
  })

  it('⑪ 未选商品：给可行动提示且**不发请求**（端点是全量无分页，不做一次拉全量）', async () => {
    const user = userEvent.setup()
    render(<StockLedgerPage />)
    await screen.findAllByTestId('stock-ledger-row')

    await user.click(screen.getByTestId('view-batch'))
    expect(await screen.findByTestId('batch-need-product')).toBeInTheDocument()
    expect(mockBatches).not.toHaveBeenCalled()
    expect(screen.queryAllByTestId('batch-row')).toHaveLength(0)
  })

  it('⑫ 两个读面不串：批次视图不渲染 SKU 流水；读面失败 ⇒ 可行动话术', async () => {
    const user = userEvent.setup()
    mockBatches.mockRejectedValue(new Error('403'))
    render(<StockLedgerPage />)
    await screen.findAllByTestId('stock-ledger-row')

    await user.click(screen.getByTestId('view-batch'))
    await user.type(screen.getByLabelText('搜索商品'), '遮光')
    await user.click(screen.getByRole('button', { name: '搜索商品' }))
    await user.click(await screen.findByTestId('product-option'))

    const err = await screen.findByTestId('batch-error')
    expect(err.textContent).toContain('权限')
    expect(screen.queryAllByTestId('batch-row')).toHaveLength(0)
    // 批次视图下不得残留 SKU 流水行（两本账量纲不同，串起来就是假口径）
    expect(screen.queryAllByTestId('stock-ledger-row')).toHaveLength(0)
    // 也读不到「单据号」筛选（它只对流水视图有意义）
    expect(screen.queryByLabelText('业务单据号')).toBeNull()
  })
})
