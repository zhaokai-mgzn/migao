// case_ids: PR-037, PR-046, PR-048, PR-062, UI-074
//
// 「新增入库单」**独立整页** `/inbound-orders/new`（issue #5844，用户 2026-10-01 裁定：
//   「新增入库单的布局很怪异，应该和订单，商品设计风格对齐」）。
//
// 本文件守的是**建单动线的前端判据**（从 tests/unit/pages/inbound-orders.test.tsx /
// inbound-orders-decimal.test.tsx / inbound-orders-opening.test.tsx **迁移**过来 —— 同一批判据
// 换了个落点，**一条都没弱化**）：
//   ① 版式：是**整页**（页头返回 + Card 分区 + 吸底汇总条），**不再有建单弹窗**
//      —— 与 /orders/new、/products/new 同族（UI-074）；
//   ② 建单：勾 SKU ⇒ 一行 = 一个批次 ⇒ 提交 payload **逐字段**不变（PR-037）；
//   ③ 数值语义：数量「大于 0 且最多 1 位小数」（PR-046 / PR-048 / UI-055）；
//   ④ 期初建账单条录入：来源=opening ⇒ 旧系统批次号列 + 0.5 米尾料可提交（PR-062）；
//   ⑤ 批次号「看得见」：明细列在草稿态恒为「过账后生成」（**草稿不发号**，生成时机不变，UI-074）。
//
// ⚠️ 建单契约**本次一字未改**：payload 字段与改造前逐字相同 —— 它由下面第 ② 条逐字段钉住。
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const mockCreate = vi.fn()
const mockGetProducts = vi.fn()
const mockGetProduct = vi.fn()

// 用 vi.hoisted 造**稳定**的 router 对象：否则每次渲染都换一个新 push，断言取不到调用记录
const { mockPush, stableRouter } = vi.hoisted(() => {
  const mockPush = vi.fn()
  const stableRouter = {
    push: mockPush,
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }
  return { mockPush, stableRouter }
})

vi.mock('next/navigation', () => ({
  useRouter: () => stableRouter,
  usePathname: () => '/inbound-orders/new',
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
}))

vi.mock('@/lib/api', () => ({
  inboundOrderApi: {
    create: (...a: unknown[]) => mockCreate(...a),
  },
  productApi: {
    getProducts: (...a: unknown[]) => mockGetProducts(...a),
    getProduct: (...a: unknown[]) => mockGetProduct(...a),
  },
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

import NewInboundOrderPage from '@/app/(dashboard)/inbound-orders/new/page'

const createdOrder = {
  id: 'o-1',
  inboundNo: 'RK-20260923-0001',
  inboundDate: '2026-09-23',
  supplier: '柯桥××布行',
  status: 'draft' as const,
  totalAmount: 375,
  items: [],
}

beforeEach(() => {
  vi.clearAllMocks()
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

/** 建单页走法：选商品 → 勾 SKU → 返回三格（数量 / 单价 / 卷长） */
async function openWithLine() {
  fireEvent.change(screen.getByPlaceholderText('商品名称 / 货号'), { target: { value: '遮光' } })
  fireEvent.click(await screen.findByRole('button', { name: /遮光窗帘布/ }))
  fireEvent.click(await screen.findByRole('checkbox'))
  return {
    qty: (await screen.findByLabelText(/数量$/)) as HTMLInputElement,
    cost: screen.getByLabelText(/单价$/) as HTMLInputElement,
    roll: screen.getByLabelText(/卷长$/) as HTMLInputElement,
  }
}

describe('建单页版式：整页（不是弹窗），与 /orders/new、/products/new 同族（UI-074）', () => {
  it('页头（返回 + 标题 + 一句口径）+ 两个分区卡片 + 吸底汇总条都在；页面里**没有**弹窗', async () => {
    render(<NewInboundOrderPage />)

    // 页头：h1 标题 + 返回按钮（点它回列表）
    expect(screen.getByRole('heading', { level: 1, name: '新增入库单' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '返回' })).toBeInTheDocument()
    // 分区卡片：单据信息 / 入库明细 两个 h2
    expect(screen.getByRole('heading', { level: 2, name: '单据信息' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: '入库明细' })).toBeInTheDocument()
    // 吸底汇总条（与 /orders/new 的 fee-summary-bar 同族）
    const bar = screen.getByTestId('inbound-create-summary-bar')
    expect(bar).toBeInTheDocument()
    expect(screen.getByTestId('inbound-create-total')).toHaveTextContent('¥0.00')
    // 🔴 本页**不是弹窗**：改造前建单是 `Modal`（role=dialog），「版式怪异」就出在那个弹窗里
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('「返回」与「取消」都回列表页（同一落点，不留在半截表单上）', async () => {
    render(<NewInboundOrderPage />)

    fireEvent.click(screen.getByRole('button', { name: '返回' }))
    expect(mockPush).toHaveBeenCalledWith('/inbound-orders')

    mockPush.mockClear()
    fireEvent.click(screen.getByRole('button', { name: '取消' }))
    expect(mockPush).toHaveBeenCalledWith('/inbound-orders')
  })

  it('「入库日期」占满整行（奇数个字段的最后一个满行；改前右半留空 —— issue #5871）', async () => {
    render(<NewInboundOrderPage />)

    const dateField = screen.getByTestId('inbound-date-field')
    // 日期控件还在，且仍是原生 date 输入
    expect(dateField.querySelectorAll('input[type="date"]').length).toBe(1)

    const grid = dateField.parentElement as HTMLElement
    expect(grid).toHaveClass('md:grid-cols-2')

    // 🔴 本单的靶心：**恰好 1 个**字段跨 2 列，且它就是日期字段。
    //    改前：0 个跨列 ⇒ 第 3 行右半留空（用户看到的"怪异"之一）；
    //    若有人顺手把别的字段也拉宽 ⇒ 数量 > 1 ⇒ 红（防静默扩大改动）。
    const spanning = Array.from(grid.children).filter((el) => el.className.includes('md:col-span-2'))
    expect(spanning.length).toBe(1)
    expect(spanning[0]).toBe(dateField)
    expect(grid.children.length).toBe(5)
  })
})

describe('建单：一行 = 一个批次，payload 逐字段（PR-037）', () => {
  it('勾选 SKU 后提交：数量/单价/缸号随行提交，采购收货不带旧系统批次号', async () => {
    mockCreate.mockResolvedValue({ data: { data: createdOrder } })
    render(<NewInboundOrderPage />)

    const { qty } = await openWithLine()
    fireEvent.change(qty, { target: { value: '30' } })
    fireEvent.change(screen.getByLabelText(/单价$/), { target: { value: '12.5' } })
    fireEvent.change(screen.getByLabelText(/缸号$/), { target: { value: 'G-2026-0912' } })
    fireEvent.click(screen.getByRole('button', { name: '保存为草稿' }))

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1))
    const payload = mockCreate.mock.calls[0][0]
    // 采购收货（缺省来源）不得带旧系统批次号（V118 / issue #5153：两列两义，填了后端会拒）
    expect(payload.source).toBe('purchase')
    expect(payload.items).toEqual([
      {
        productId: 'prod-1',
        skuId: 11,
        quantity: 30,
        unitCost: 12.5,
        dyeLot: 'G-2026-0912',
        legacyBatchNo: null,
        rollLengthM: null,
      },
    ])
    // 建完回列表（新单在列表里是草稿，过账在详情弹窗里做）
    expect(mockPush).toHaveBeenCalledWith('/inbound-orders')
  })

  it('一行都没有 ⇒ 拦住（不调建单接口）', async () => {
    render(<NewInboundOrderPage />)
    fireEvent.click(screen.getByRole('button', { name: '保存为草稿' }))

    const { toast } = await import('sonner')
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('至少勾选一个 SKU')),
    )
    expect(mockCreate).not.toHaveBeenCalled()
  })
})

describe('批次号「看得见」（UI-074）—— 生成时机**不变**：草稿不发号', () => {
  it('明细表有「批次号」列，且草稿态逐行显示「过账后生成」（不是空白、不是假号）', async () => {
    render(<NewInboundOrderPage />)
    await openWithLine()

    const table = screen.getByRole('table')
    expect(table).toBeInTheDocument()
    const header = table.querySelector('thead')!
    expect(header.textContent).toContain('批次号')
    // 列头在、行里也得有值：草稿未过账 ⇒ 「过账后生成」
    // （批次号 PC-yyyyMMdd-NNNN 由服务端在**过账**时逐行生成，草稿阶段不得凭空造号）
    expect(table.querySelector('tbody')!.textContent).toContain('过账后生成')
    // 不许出现「像批次号但不是」的东西（前端不生成号段）
    expect(table.querySelector('tbody')!.textContent).not.toMatch(/PC-\d{8}-\d{4}/)
  })
})

describe('入库数量：1 位小数（PR-046，issue #5063）', () => {
  it('60.5 米通过提交前校验，并按**原值** 60.5 提交（改前 Number.isInteger 必红）', async () => {
    mockCreate.mockResolvedValue({ data: { data: createdOrder } })
    render(<NewInboundOrderPage />)
    const { qty } = await openWithLine()
    fireEvent.change(qty, { target: { value: '60.5' } })
    fireEvent.click(screen.getByRole('button', { name: '保存为草稿' }))

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1))
    // 原值提交：不得被取整成 61、也不得被截断成 60。
    // ⚠️ 断言挂在**整个 items 数组**上（不是 `items[0]`）—— 数组长度也是判据的一部分
    //    （迁移前如此，迁移不许降级）。
    expect(mockCreate.mock.calls[0][0].items).toEqual([{
      productId: 'prod-1',
      skuId: 11,
      quantity: 60.5,
      unitCost: null,
      dyeLot: null,
      legacyBatchNo: null,
      rollLengthM: null,
    }])
    const { toast } = await import('sonner')
    expect(toast.error).not.toHaveBeenCalled()
  })

  it('整数 10 逐值不变地通过（本单只放开小数位，不改整数场景）', async () => {
    mockCreate.mockResolvedValue({ data: { data: createdOrder } })
    render(<NewInboundOrderPage />)
    const { qty } = await openWithLine()
    fireEvent.change(qty, { target: { value: '10' } })
    fireEvent.click(screen.getByRole('button', { name: '保存为草稿' }))

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1))
    expect(mockCreate.mock.calls[0][0].items[0].quantity).toBe(10)
  })
})

describe('入库数量：超 1 位小数显式拒绝（PR-048，issue #5063）', () => {
  it.each(['2.755', '1.05'])(
    '%s ⇒ 提交前拦下（不静默取整），文案含「1 位小数」，且不调建单接口',
    async (value) => {
      render(<NewInboundOrderPage />)
      const { qty } = await openWithLine()
      fireEvent.change(qty, { target: { value } })
      fireEvent.click(screen.getByRole('button', { name: '保存为草稿' }))

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
    mockCreate.mockResolvedValue({ data: { data: createdOrder } })
    render(<NewInboundOrderPage />)
    const { qty } = await openWithLine()
    fireEvent.change(qty, { target: { value: '0.5' } })
    fireEvent.click(screen.getByRole('button', { name: '保存为草稿' }))

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1))
    expect(mockCreate.mock.calls[0][0].items[0].quantity).toBe(0.5)
  })

  it.each(['0', '-1'])('%s ⇒ 仍按「大于 0」下限拒绝（下限仍存在）', async (value) => {
    render(<NewInboundOrderPage />)
    const { qty } = await openWithLine()
    fireEvent.change(qty, { target: { value } })
    fireEvent.click(screen.getByRole('button', { name: '保存为草稿' }))

    const { toast } = await import('sonner')
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('大于 0')))
    expect(mockCreate).not.toHaveBeenCalled()
  })
})

describe('期初建账单条录入（PR-062，V118 / issue #5153）', () => {
  it('来源选「期初建账」⇒ 出现旧系统批次号列，**0.5 米能提交**且旧号随行提交', async () => {
    mockCreate.mockResolvedValue({ data: { data: createdOrder } })
    render(<NewInboundOrderPage />)

    // ① 先按**采购收货**（缺省来源）加一行 ⇒ **没有**「旧系统批次号」列
    //    （那一列对采购入库没有意义：旧系统批次号与系统批次号两列两义，填了后端会拒）
    const { qty } = await openWithLine()
    expect(screen.queryByLabelText(/旧系统批次号/)).toBeNull()

    // ② 切到「期初建账」⇒ 明细表多出该列（可填）
    fireEvent.change(screen.getByLabelText('单据来源'), { target: { value: 'opening' } })
    expect(screen.getByText('旧系统批次号')).toBeInTheDocument()
    expect(await screen.findByLabelText(/旧系统批次号/)).toBeInTheDocument()

    fireEvent.change(qty, { target: { value: '0.5' } })
    fireEvent.change(screen.getByLabelText(/旧系统批次号/), { target: { value: 'OLD-2024-0001' } })
    fireEvent.click(screen.getByRole('button', { name: '保存为草稿' }))

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1))
    const payload = mockCreate.mock.calls[0][0]
    expect(payload.source).toBe('opening')
    // 🔴 **七字段逐值 + 数组长度**（`toEqual`，不是 `toMatchObject`）——迁移**不许降级**：
    //    只钉两个字段会漏掉「少一个键」「多一行」「unitCost/dyeLot/rollLengthM 写错」这类回归。
    expect(payload.items).toEqual([
      {
        productId: 'prod-1',
        skuId: 11,
        quantity: 0.5,
        unitCost: null,
        dyeLot: null,
        legacyBatchNo: 'OLD-2024-0001',
        rollLengthM: null,
      },
    ])
    const { toast } = await import('sonner')
    expect(toast.error).not.toHaveBeenCalled()
  })
})

// ========== 建单三格（数量 / 单价 / 卷长）的数值语义（issue #5228 缺口 2 / UI-055）==========
//
// ⚠️ 判据**不建在「`0.` 中间态」上**：jsdom 把 `type="number"` 的 `"0."` 归一成 `""`，
// 真 Chromium 归一成 `"0"`（#5228 主会话真浏览器实测，两套读数**相反**）。这里一律用
// `fireEvent.change` **一次给完整串**，钉的是与引擎无关的语义：
// 完整串 ⇒ 原值提交；空 ⇒ `null`（**不是 0**）；`0` ⇒ **不被当空**。
describe('入库三格（数量 / 单价 / 卷长）的数值语义 —— 与引擎无关（UI-055）', () => {
  it('三格各给完整串 `0.5` ⇒ 原值提交 0.5（不取整、不当空）', async () => {
    mockCreate.mockResolvedValue({ data: { data: createdOrder } })
    render(<NewInboundOrderPage />)
    const { qty, cost, roll } = await openWithLine()
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
    mockCreate.mockResolvedValue({ data: { data: createdOrder } })
    render(<NewInboundOrderPage />)
    const { cost, roll } = await openWithLine()
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
    mockCreate.mockResolvedValue({ data: { data: createdOrder } })
    render(<NewInboundOrderPage />)
    const { roll } = await openWithLine()
    fireEvent.change(roll, { target: { value: '0' } })
    fireEvent.click(screen.getByRole('button', { name: '保存为草稿' }))

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1))
    expect(mockCreate.mock.calls[0][0].items[0].rollLengthM).toBe(0)
  })

  it('单价 `0` ⇒ 显式拒绝并说清口径（既不静默当 0 提交、也不静默当空）', async () => {
    render(<NewInboundOrderPage />)
    const { cost } = await openWithLine()
    fireEvent.change(cost, { target: { value: '0' } })
    fireEvent.click(screen.getByRole('button', { name: '保存为草稿' }))

    const { toast } = await import('sonner')
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('入库单价必须大于 0')),
    )
    expect(mockCreate).not.toHaveBeenCalled()
  })
})
