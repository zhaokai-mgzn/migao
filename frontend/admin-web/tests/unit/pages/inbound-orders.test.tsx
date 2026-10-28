// case_ids: PR-037, UI-074, WH-004
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

// issue #5983：「新建入库单」按钮改为按 `inbound:create` 显隐（`canWrite = hasPermission('inbound:create')`）
// ⇒ 渲染必须带**登录态**，否则 user 为 null ⇒ 按钮恒不渲染（下方导航判据会假红）。
// 默认给管理员（`permissions: ['*']`）；要测「无码看不见」请改 `authMock.state.user.permissions`。
const authMock = vi.hoisted(() => ({
  state: {
    user: { id: '1', username: 'admin', name: '管理员', permissions: ['*'] as string[], roles: [] as string[] },
  },
}))
vi.mock('@/store/auth', () => ({
  useAuthStore: (selector?: (s: unknown) => unknown) =>
    typeof selector === 'function' ? selector(authMock.state) : authMock.state,
}))

const mockList = vi.fn()
const mockDetail = vi.fn()
const mockCreate = vi.fn()
const mockPost = vi.fn()
const mockCancel = vi.fn()
// #7807：仓列表只用于**筛选器的选项**（读失败不阻塞主列表）
const mockWarehouseList = vi.fn()

vi.mock('@/lib/api', () => ({
  inboundOrderApi: {
    list: (...a: unknown[]) => mockList(...a),
    detail: (...a: unknown[]) => mockDetail(...a),
    create: (...a: unknown[]) => mockCreate(...a),
    post: (...a: unknown[]) => mockPost(...a),
    cancel: (...a: unknown[]) => mockCancel(...a),
  },
  warehouseApi: {
    list: (...a: unknown[]) => mockWarehouseList(...a),
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
  // 默认零仓：既有判据（列表 / 视图 / 详情）都不该被仓库筛选影响 —— 候选 ≤1 时筛选器不渲染
  mockWarehouseList.mockResolvedValue({ data: { data: [] } })
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
    // 类别维（issue #7794）：默认视图 = 原料仓入库 ⇒ 请求必须带 bizCategory=fabric
    // （不带 = 后端不过滤 = 成品单混进原料仓列表，正是本单要修的形态）
    expect(mockList).toHaveBeenCalledWith({ keyword: undefined, status: '', bizCategory: 'fabric' })
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

  it('详情明细：卷数 / 卷长(米/卷) / 入库米数(米) 三列 —— 米数用服务端值，卷长原值直读', async () => {
    // 🔴 三条断言各自有判别力：
    //   ① **入库米数 = 服务端 `meters`**（issue #7709）：历史拍照行的 `quantity` 还是卷数（1），
    //      页面必须显示 70 —— 拿 `quantity` 顶替就是「入库单说 1 米、库存也说 1 米」的那个形态；
    //   ② 卷长 `58.55` ⇒ **不得**被渲染成 `58.6`（卷长是 `NUMERIC(8,2)`，而 `formatStockQuantity`
    //      是**库存米数**的 0.1 米粒度格式化器；拿它渲染卷长 = 静默改数）；
    //   ③ 卷长未填 ⇒ `-`，**不是** `0`（「0 米一卷」与「没填卷长」不是一回事）。
    mockDetail.mockResolvedValueOnce({
      data: {
        data: {
          ...draftDetail,
          items: [
            // 历史拍照行：quantity 存的是卷数、meters 是还原后的米数
            { ...draftDetail.items[0], id: 100, skuCode: 'SKU-LEGACY', quantity: 1, rollCount: null, rollLengthM: 70, meters: 70 },
            // 新行：卷数 1 + 卷长 58.55 ⇒ 米数 58.5
            { ...draftDetail.items[0], id: 101, skuCode: 'SKU-ROLL', quantity: 58.5, rollCount: 1, rollLengthM: 58.55, meters: 58.5 },
            // 按米录入（卷长只是留档）
            { ...draftDetail.items[0], id: 102, skuCode: 'SKU-NOROLL', quantity: 30, rollCount: null, rollLengthM: null, meters: 30 },
          ],
        },
      },
    })
    render(<InboundOrdersPage />)
    await screen.findByText('RK-20260923-0001')

    fireEvent.click(
      within(screen.getByText('RK-20260923-0001').closest('tr')!).getByRole('button', { name: '详情' }),
    )

    const detailTable = (await screen.findByText('卷长(米/卷)')).closest('table') as HTMLTableElement
    const rowOf = (sku: string) =>
      within(within(detailTable).getByText(sku, { exact: false }).closest('tr') as HTMLElement)
    // 列序：0 货号/颜色/门幅 · 1 卷数 · 2 卷长(米/卷) · 3 入库米数(米) · 4 单价 · 5 金额 · 6 批次号 · 7 缸号 · 8 旧系统批次号
    expect(rowOf('SKU-LEGACY').getAllByRole('cell')[1].textContent).toBe('-')
    expect(rowOf('SKU-LEGACY').getAllByRole('cell')[2].textContent).toBe('70')
    expect(rowOf('SKU-LEGACY').getAllByRole('cell')[3].textContent).toBe('70')
    expect(rowOf('SKU-ROLL').getAllByRole('cell')[1].textContent).toBe('1')
    expect(rowOf('SKU-ROLL').getAllByRole('cell')[2].textContent).toBe('58.55')
    expect(rowOf('SKU-ROLL').getAllByRole('cell')[3].textContent).toBe('58.5')
    expect(rowOf('SKU-NOROLL').getAllByRole('cell')[1].textContent).toBe('-')
    expect(rowOf('SKU-NOROLL').getAllByRole('cell')[2].textContent).toBe('-')
    expect(rowOf('SKU-NOROLL').getAllByRole('cell')[3].textContent).toBe('30')
    // #7799 反向（原料单零回归）：来源订单号是**成品单**的列，布料入库不挂订单 ⇒ 这里不出现
    expect(screen.queryByText('来源订单号')).not.toBeInTheDocument()
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

// ============================================================
// 两个视图（issue #7794）—— 用户 2026-10-26 逐字
// 「要区分原料仓入库和成品仓入库，别混在一起了」
// ============================================================
// 守四件事：① 默认视图请求带 bizCategory=fabric（现有行为零回归）；
//   ② 切到成品视图即带 bizCategory=finished，且**只读**（无建单 / 期初建账入口）；
//   ③ 列随视图变：成品视图无 供应商 / 批次号 / 金额，有 明细行数 + 套数合计；
//   ④ 成品单详情看得到 套号 / 仓位号 / 短码，数量「N 套」，不显示 米数 / 单价 / 金额。
// 后端侧同判据：InboundOrderServiceTest.InboundBizCategory / InboundOrderQueryMapperTest（#7794 两条）。

const finishedRow = {
  id: 'o-finished-1',
  inboundNo: 'RK-20261026-0001',
  bizCategory: 'finished' as const,
  inboundDate: '2026-10-26',
  warehouse: '成品仓',
  status: 'posted' as const,
  totalAmount: 0,
  itemCount: 6,
  totalQuantity: 6,
  setCount: 2,
  supplier: '',
  batchNos: null,
}

const finishedDetail = {
  id: 'o-finished-1',
  inboundNo: 'RK-20261026-0001',
  bizCategory: 'finished' as const,
  inboundDate: '2026-10-26',
  warehouse: '成品仓',
  status: 'posted' as const,
  totalAmount: 0,
  postedBy: '13800000000',
  postedAt: '2026-10-26T10:00:00Z',
  items: [
    {
      id: 900,
      productId: 'prod-9',
      productName: '布帘',
      setNo: 'JG-20261026-001-001',
      binCode: 'A-01',
      shortCode: 'AB12CD34',
      // #7799：成品单由打包产生 ⇒ 每行都能回查来源订单
      orderNo: 'SO-20261026-0001',
      quantity: 1,
      unit: 'set',
    },
    {
      id: 901,
      productId: 'prod-9',
      productName: '纱帘',
      setNo: 'JG-20261026-001-001',
      binCode: 'A-02',
      shortCode: 'EF56GH78',
      orderNo: 'SO-20261026-0001',
      quantity: 1,
      unit: 'set',
    },
  ],
}

describe('入库单两个视图：原料仓 / 成品仓（#7794）', () => {
  it('默认「原料仓入库」视图：请求带 bizCategory=fabric，且药丸选中态正确（零回归）', async () => {
    render(<InboundOrdersPage />)
    await screen.findByText('RK-20260923-0001')

    expect(mockList).toHaveBeenCalledWith({ keyword: undefined, status: '', bizCategory: 'fabric' })
    expect(screen.getByTestId('inbound-tab-fabric')).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByTestId('inbound-tab-finished')).toHaveAttribute('aria-selected', 'false')
    // 反向（零回归）：原料仓视图**仍**有 供应商 / 批次号 / 金额 三列与两个入口
    const table = screen.getByRole('table')
    expect(within(table).getByText('供应商')).toBeInTheDocument()
    expect(within(table).getByText('批次号')).toBeInTheDocument()
    expect(within(table).getByText('金额')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /新建入库单/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /期初建账导入/ })).toBeInTheDocument()
  })

  it('点「成品仓入库」⇒ 请求带 bizCategory=finished，且只读：没有 新建入库单 / 期初建账导入', async () => {
    render(<InboundOrdersPage />)
    await screen.findByText('RK-20260923-0001')

    mockList.mockResolvedValue({ data: { data: [finishedRow] } })
    fireEvent.click(screen.getByTestId('inbound-tab-finished'))

    expect(await screen.findByText('RK-20261026-0001')).toBeInTheDocument()
    expect(mockList).toHaveBeenLastCalledWith({ keyword: undefined, status: '', bizCategory: 'finished' })
    expect(screen.getByTestId('inbound-tab-finished')).toHaveAttribute('aria-selected', 'true')
    // 成品单只由打包自动建 ⇒ 成品视图是只读面（手工建一张成品单没有对应写面）
    expect(screen.queryByText('新建入库单')).not.toBeInTheDocument()
    expect(screen.queryByText('期初建账导入')).not.toBeInTheDocument()
  })

  it('成品视图列随视图变：无 供应商 / 批次号 / 金额；有 明细行数 与 套数合计（显示「N 套」）', async () => {
    render(<InboundOrdersPage />)
    await screen.findByText('RK-20260923-0001')
    mockList.mockResolvedValue({ data: { data: [finishedRow] } })
    fireEvent.click(screen.getByTestId('inbound-tab-finished'))
    await screen.findByText('RK-20261026-0001')

    const table = screen.getByRole('table')
    // 成品单这几列恒空 ⇒ 不渲染（§31 P2 信息不重复；留着就是噪声）
    expect(within(table).queryByText('供应商')).not.toBeInTheDocument()
    expect(within(table).queryByText('批次号')).not.toBeInTheDocument()
    expect(within(table).queryByText('金额')).not.toBeInTheDocument()
    // 换上的两列：明细行数（= 部位数）与 套数合计（= 不同套号个数，服务端算）
    expect(within(table).getByText('明细行数')).toBeInTheDocument()
    expect(within(table).getByText('套数合计')).toBeInTheDocument()
    expect(within(table).getByTestId('inbound-finished-item-count').textContent).toBe('6')
    expect(within(table).getByTestId('inbound-finished-set-count').textContent).toBe('2 套')
  })

  it('成品单详情：套号 / 仓位号 / 短码 三列 + 数量「N 套」，不显示 米数 / 单价 / 金额', async () => {
    mockDetail.mockResolvedValueOnce({ data: { data: finishedDetail } })
    render(<InboundOrdersPage />)
    await screen.findByText('RK-20260923-0001')
    mockList.mockResolvedValue({ data: { data: [finishedRow] } })
    fireEvent.click(screen.getByTestId('inbound-tab-finished'))
    await screen.findByText('RK-20261026-0001')

    fireEvent.click(
      within(screen.getByText('RK-20261026-0001').closest('tr')!).getByRole('button', { name: '详情' }),
    )

    const detailTable = (await screen.findByText('套号')).closest('table') as HTMLTableElement
    expect(within(detailTable).getByText('仓位号')).toBeInTheDocument()
    expect(within(detailTable).getByText('短码')).toBeInTheDocument()
    // 真值逐行渲染（不重算、不截断）；同一套的两个部位（布帘 / 纱帘）共享同一个套号 ⇒ 两行都有
    expect(within(detailTable).getAllByText('JG-20261026-001-001').length).toBe(2)
    expect(within(detailTable).getByText('A-01')).toBeInTheDocument()
    expect(within(detailTable).getByText('A-02')).toBeInTheDocument()
    expect(within(detailTable).getByText('AB12CD34')).toBeInTheDocument()
    // 数量按「N 套」显示（成品行恒 1 套）
    expect(within(detailTable).getAllByText('1 套').length).toBe(2)
    // 成品行不碰米数库存、没有成本口径 ⇒ 这三列不出现
    expect(screen.queryByText('入库米数(米)')).not.toBeInTheDocument()
    expect(screen.queryByText('卷长(米/卷)')).not.toBeInTheDocument()
    expect(screen.queryByText('单价')).not.toBeInTheDocument()
    expect(screen.queryByText('金额')).not.toBeInTheDocument()
    expect(screen.queryByText('金额合计')).not.toBeInTheDocument()
  })

  it('站内信深链未命中原料仓 ⇒ 给一行可点提示切到成品视图（不静默空白）', async () => {
    window.history.pushState({}, '', '/inbound-orders?keyword=RK-20261026-0001')
    try {
      mockList.mockResolvedValue({ data: { data: [] } })
      render(<InboundOrdersPage />)

      const hint = await screen.findByTestId('inbound-other-view-hint')
      expect(hint.textContent).toContain('该单可能在「成品仓入库」')
      // 深链按默认（原料仓）视图读
      expect(mockList).toHaveBeenCalledWith({ keyword: 'RK-20261026-0001', status: '', bizCategory: 'fabric' })

      mockList.mockResolvedValue({ data: { data: [finishedRow] } })
      fireEvent.click(within(hint).getByRole('button', { name: /查看成品仓入库/ }))

      expect(await screen.findByText('RK-20261026-0001')).toBeInTheDocument()
      expect(mockList).toHaveBeenLastCalledWith({
        keyword: 'RK-20261026-0001',
        status: '',
        bizCategory: 'finished',
      })
    } finally {
      window.history.pushState({}, '', '/')
    }
  })
})

// ============================================================ #7799 成品视图两处收口

/**
 * #7799 / WH-004：成品入库视图（#7794 落的）两处收口。
 *
 * ① 状态筛选去掉「草稿」—— 成品单恒为 `posted`（打包自动建单即过账），「草稿」在这个视图里**恒空**；
 *    原料视图仍含（工人拍照草稿停在那里）⇒ 反向判据。
 * ② 成品单明细补「来源订单号」—— 成品行不挂 SKU 货号，没有它就无法回查是哪张订单的。
 */
describe('成品视图两处收口（#7799）', () => {
  const statusOptionLabels = () =>
    Array.from((screen.getByRole('combobox') as HTMLSelectElement).options).map((o) => o.textContent)

  it('状态筛选：成品视图**不含**「草稿」，原料视图**仍含**（反向零回归）', async () => {
    render(<InboundOrdersPage />)
    await screen.findByText('RK-20260923-0001')

    // 原料视图：草稿是真状态（工人拍照草稿），不许顺手删掉
    expect(statusOptionLabels()).toContain('草稿')
    expect(statusOptionLabels()).toEqual(['全部状态', '草稿', '已过账', '已作废'])

    mockList.mockResolvedValue({ data: { data: [finishedRow] } })
    fireEvent.click(screen.getByTestId('inbound-tab-finished'))
    await screen.findByText('RK-20261026-0001')

    // 成品视图：草稿选项没了，其余状态仍在
    expect(statusOptionLabels()).not.toContain('草稿')
    expect(statusOptionLabels()).toEqual(['全部状态', '已过账', '已作废'])
  })

  it('成品单明细多一列「来源订单号」= item.orderNo（两行都渲染真值）', async () => {
    mockDetail.mockResolvedValueOnce({ data: { data: finishedDetail } })
    render(<InboundOrdersPage />)
    await screen.findByText('RK-20260923-0001')
    mockList.mockResolvedValue({ data: { data: [finishedRow] } })
    fireEvent.click(screen.getByTestId('inbound-tab-finished'))
    await screen.findByText('RK-20261026-0001')

    fireEvent.click(
      within(screen.getByText('RK-20261026-0001').closest('tr')!).getByRole('button', { name: '详情' }),
    )

    const detailTable = (await screen.findByText('套号')).closest('table') as HTMLTableElement
    expect(within(detailTable).getByText('来源订单号')).toBeInTheDocument()
    // 同一套的两个部位同属一张订单 ⇒ 两行都显示同一个单号
    expect(within(detailTable).getAllByText('SO-20261026-0001').length).toBe(2)
  })

  it('没有来源订单号（历史行 / 正常应有）⇒ 显示「—」，不留空白格', async () => {
    mockDetail.mockResolvedValueOnce({
      data: {
        data: {
          ...finishedDetail,
          items: [{ ...finishedDetail.items[0], orderNo: null }, finishedDetail.items[1]],
        },
      },
    })
    render(<InboundOrdersPage />)
    await screen.findByText('RK-20260923-0001')
    mockList.mockResolvedValue({ data: { data: [finishedRow] } })
    fireEvent.click(screen.getByTestId('inbound-tab-finished'))
    await screen.findByText('RK-20261026-0001')

    fireEvent.click(
      within(screen.getByText('RK-20261026-0001').closest('tr')!).getByRole('button', { name: '详情' }),
    )

    const detailTable = (await screen.findByText('套号')).closest('table') as HTMLTableElement
    expect(within(detailTable).getByText('—')).toBeInTheDocument()
  })
})

// ============================================================ #7807 按仓库筛选

/**
 * #7807：入库单列表要能**按仓库查单** —— 改前只有「仓库」文本列可看，查不了。
 *
 * 守五件事：
 *   ① 原料视图有 ≥2 个原料仓 ⇒ 渲染仓库下拉；选了仓 ⇒ 请求带该 `warehouseId`；
 *   ② 切成品视图 ⇒ 选项只剩成品仓，且请求**不再带**旧 warehouseId（重置与重载同一次更新，
 *      不许出现「先按旧仓查一次成品视图」的中间请求）；
 *   ③ 候选仓只有 1 个 ⇒ **不渲染**该筛选（一个只有一种取值的控件是噪声，§31 P1）；
 *   ④ 反向：原料视图的选项里**没有**成品仓（选它一定查不出东西）；
 *   ⑤ 仓列表读失败 ⇒ 筛选器不渲染即可，主列表自己的读失败态 / 成功态一字不动。
 */
const warehouse = (id: number, name: string, warehouseType: string) => ({
  id,
  code: `W-${id}`,
  name,
  warehouseType,
  isDefault: false,
  status: 'active',
})

const RAW_WAREHOUSE_A = warehouse(1, '原料一号仓', 'material')
const RAW_WAREHOUSE_B = warehouse(2, '原料二号仓', 'store')
const FINISHED_WAREHOUSE_A = warehouse(9, '成品一号仓', 'finished')
const FINISHED_WAREHOUSE_B = warehouse(10, '成品二号仓', 'finished')

describe('入库单列表按仓库筛选（#7807）', () => {
  interface Option {
    value: string
    label: string | null
  }

  const filterEl = () => screen.queryByTestId('inbound-warehouse-filter') as HTMLSelectElement | null
  const optionsOf = (el: HTMLSelectElement): Option[] =>
    Array.from(el.options).map((o) => ({ value: o.value, label: o.textContent }))
  const lastParams = () => mockList.mock.calls[mockList.mock.calls.length - 1][0]

  /** 等筛选器出现**且**选项等于 expected —— 不存在即抛（把「没渲染也通过」挡在门外） */
  const waitForOptions = async (expected: Option[]): Promise<HTMLSelectElement> => {
    await waitFor(() => {
      const el = filterEl()
      if (!el) throw new Error('期望渲染仓库筛选器（候选仓 ≥2 个）')
      expect(optionsOf(el)).toEqual(expected)
    })
    const el = filterEl()
    if (!el) throw new Error('仓库筛选器在断言之后消失')
    return el
  }

  it('原料视图：≥2 个原料仓 ⇒ 渲染筛选；选第二个仓 ⇒ 请求带该 warehouseId', async () => {
    mockWarehouseList.mockResolvedValue({
      data: { data: [RAW_WAREHOUSE_A, RAW_WAREHOUSE_B, FINISHED_WAREHOUSE_A] },
    })
    render(<InboundOrdersPage />)
    await screen.findByText('RK-20260923-0001')

    // 首项 = 「全部仓库」（value 空）⇒「不选」与后端 `warehouseId = null`（不过滤）同一语义
    const el = await waitForOptions([
      { value: '', label: '全部仓库' },
      { value: '1', label: '原料一号仓' },
      { value: '2', label: '原料二号仓' },
    ])

    fireEvent.change(el, { target: { value: '2' } })

    await waitFor(() =>
      expect(lastParams()).toEqual({
        keyword: undefined,
        status: '',
        bizCategory: 'fabric',
        warehouseId: 2,
      }),
    )
  })

  it('切成品视图 ⇒ 只剩成品仓选项，且请求里不再带旧 warehouseId（重置与重载同一次更新）', async () => {
    mockWarehouseList.mockResolvedValue({
      data: { data: [RAW_WAREHOUSE_A, RAW_WAREHOUSE_B, FINISHED_WAREHOUSE_A, FINISHED_WAREHOUSE_B] },
    })
    render(<InboundOrdersPage />)
    await screen.findByText('RK-20260923-0001')

    const fabricFilter = await waitForOptions([
      { value: '', label: '全部仓库' },
      { value: '1', label: '原料一号仓' },
      { value: '2', label: '原料二号仓' },
    ])
    fireEvent.change(fabricFilter, { target: { value: '2' } })
    await waitFor(() => expect(lastParams().warehouseId).toBe(2))

    mockList.mockResolvedValue({ data: { data: [finishedRow] } })
    fireEvent.click(screen.getByTestId('inbound-tab-finished'))
    await screen.findByText('RK-20261026-0001')

    // 选项随视图换（原料仓在新视图里选不到）
    await waitForOptions([
      { value: '', label: '全部仓库' },
      { value: '9', label: '成品一号仓' },
      { value: '10', label: '成品二号仓' },
    ])

    // 旧值（原料二号仓 id=2）在成品视图里不存在 ⇒ 必须重置
    await waitFor(() => expect(lastParams().bizCategory).toBe('finished'))
    expect(lastParams().warehouseId).toBeUndefined()
    // 反向：不许出现「先按旧仓查一次成品视图」的中间请求
    expect(mockList.mock.calls.map((c) => c[0])).not.toContainEqual(
      expect.objectContaining({ bizCategory: 'finished', warehouseId: 2 }),
    )
  })

  it('候选仓只有 1 个 ⇒ 不渲染仓库筛选（一个只有一种取值的控件是噪声）', async () => {
    mockWarehouseList.mockResolvedValue({ data: { data: [RAW_WAREHOUSE_A, FINISHED_WAREHOUSE_A] } })
    render(<InboundOrdersPage />)
    await screen.findByText('RK-20260923-0001')
    await waitFor(() => expect(mockWarehouseList).toHaveBeenCalled())

    expect(filterEl()).toBeNull()
    // 筛选器不渲染 ≠ 列表不查：主列表请求照旧（原料视图 + 不带仓库条件）
    expect(mockList).toHaveBeenCalledWith({ keyword: undefined, status: '', bizCategory: 'fabric' })
  })

  it('反向：原料视图的选项里没有成品仓（选它一定查不出东西）', async () => {
    mockWarehouseList.mockResolvedValue({
      data: { data: [RAW_WAREHOUSE_A, RAW_WAREHOUSE_B, FINISHED_WAREHOUSE_A] },
    })
    render(<InboundOrdersPage />)
    await screen.findByText('RK-20260923-0001')

    const el = await waitForOptions([
      { value: '', label: '全部仓库' },
      { value: '1', label: '原料一号仓' },
      { value: '2', label: '原料二号仓' },
    ])
    expect(optionsOf(el).map((o) => o.label)).not.toContain('成品一号仓')
    expect(optionsOf(el).map((o) => o.value)).not.toContain('9')
  })

  it('仓列表读失败 ⇒ 筛选器不渲染，主列表照常（筛选器故障不阻塞读单）', async () => {
    mockWarehouseList.mockRejectedValue(new Error('warehouses 500'))
    render(<InboundOrdersPage />)

    expect(await screen.findByText('RK-20260923-0001')).toBeInTheDocument()
    await waitFor(() => expect(mockWarehouseList).toHaveBeenCalled())
    expect(filterEl()).toBeNull()
  })
})

describe('空态话术（issue #8040）：说清「为什么空 / 去哪建」，两个视图各自说人话', () => {
  it('原料仓视图：真没有入库单 ⇒ 说清去哪建；筛了单号 ⇒ 说清换个条件', async () => {
    mockList.mockResolvedValue({ data: { data: [] } })
    render(<InboundOrdersPage />)

    // ① 真为空：说清建单入口（不再是裸「暂无入库单」）
    const trulyEmpty = await screen.findByText(/还没有原料仓入库单/)
    expect(trulyEmpty.textContent).toContain('新建入库单')
    expect(screen.queryByText('暂无入库单')).toBeNull()

    // ② 成品视图 + 筛了单号 ⇒ 改口说「换个条件」（原料视图带单号走的是深链提示，见既有用例）
    fireEvent.click(screen.getByTestId('inbound-tab-finished'))
    fireEvent.change(screen.getByPlaceholderText('入库单号'), { target: { value: 'RK-NOT-EXIST' } })
    expect(await screen.findByText(/没有符合筛选条件的入库单/)).toBeInTheDocument()
  })

  it('成品仓视图：空态说清「打包后自动生成」，不说成手工建单', async () => {
    mockList.mockResolvedValue({ data: { data: [] } })
    render(<InboundOrdersPage />)
    fireEvent.click(screen.getByTestId('inbound-tab-finished'))

    const finishedEmpty = await screen.findByText(/还没有成品仓入库单/)
    expect(finishedEmpty.textContent).toContain('打包')
    // 反向对照：成品单没有手工建单入口 ⇒ 空态不许让商家去点一个不存在的按钮
    expect(finishedEmpty.textContent).not.toContain('新建入库单')
  })
})
