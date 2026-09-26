// case_ids: PP-011, PG-019, PP-014
// PP-011（issue #4000，M4-H 按需单据渲染）：加工单生产明细页 /processing-orders/{id}/production
// —— 头部（加工单号/订单号/状态/进度/交期）+ 工序进度表 + 计件汇总 + 打印任务卡入口，
// 接口失败要有友好错误提示与重试（不白屏）。
// PG-019（issue #4202，前端半边）：存量加工单（positions 为空且非 cancelled）显示「补生成工序」
// → 调 POST /production/orders/{orderId}/instantiate（空 body）→ 刷新出工序表与二维码；
// 有数据 / 已取消时按钮不出现；任务卡占位文案不得误导（不得再指向「请先在订单详情生成加工单」）。
// PG-019（issue #4240，前端半边）：真值源 §1「二维码 token 化、可撤销」的 UI 发射点 ——
// 生产明细页「撤销二维码」入口（二次确认后才发 POST .../qr-token/revoke，按 processing:manage 显隐）
// → 撤销后刷新回占位态 + 可见「已撤销」反馈。
// PG-019（issue #4287，前端半边）：撤销的**恢复半边** —— 撤销成功后出现「重新生成二维码」入口
// → POST .../qr-token/regenerate（同 processing:manage 口径）→ 刷新出新码。
// 🔴 不得复用 instantiate（改价后软删实例 ⇒ done_qty 归零 ⇒ 计件工资被清）。
// PP-014（issue #4307 交付物 2，契约所有者 = 后端 4308）：`route_source` **四态**的用户侧可观测面
// —— derived 不提示 / partial 提示另一半取默认 / missing_route 提示「识别的是 X（route_requested_key）
// 但库里没这条路线」/ default 高亮提示核对工序与计件单价；字段缺失 = 未知 ⇒ 不得显示成「已派生」。
// PP-011（issue #4726，A 档）：加工单生产明细页「生成二维码（测试用）」入口 —— 把**加工单号**画成
// 纯文本码（**只读**：零写请求、qr_token 一字不动）+ 一键复制单号 + 按 processing:manage 显隐，
// 用于串联「扫码 → 手动输单号 → 报工 → 计件」端到端联调（B 档小程序码需 bmini 凭据，本单缺）。
// PP-011（issue #4946，用户裁定 2026-09-21）：**洗水码取代 A4 任务卡** —— 生产页传
// `positions` 给任务卡（每部位一张 60×30mm，码 = 该部位自己的 `scan_url`/`part_token`），
// 且「生成二维码（测试用）」弹层**逐张**出码（N 个部位 ⇒ N 张，各带人可读短码 + 复制短码），
// 不再是「一张单号码」。撤销语义（`qr_token` 为空 ⇒ 占位文案）逐字保留。
// PP-011（issue #4960 第 3 条 / #4961，2026-09-21）：① 实例显示名 `逻辑名 · 部位` 的**口径唯一性**
// —— 本页「卡在哪」原先手拼了一份，与同页进度表两套口径 ⇒ 改判为同走 `operationDisplayName`
// （正/负态各一条：`精裁 · 布帘` / 部位无关只显示逻辑名）；② 工序进度表那枚「必完」badge 退场。
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const mockDetail = vi.fn()
const mockGetOrderOperations = vi.fn()
const mockGetPiecework = vi.fn()
const mockInstantiate = vi.fn()
const mockRecordPrint = vi.fn()
const mockRevokeQrToken = vi.fn()
// issue #4287：撤销后的**恢复半边**（重新生成二维码）—— 必须是**窄**接口，不得复用 instantiate
// （instantiate 的签名幂等判据在改价后会软删实例、清掉 done_qty ⇒ 连带清掉计件工资）。
const mockRegenerateQrToken = vi.fn()
const mockRepriceUnpricedInstances = vi.fn()
// issue #4949 起「卡在哪」（`StuckPointsReport`）也走替身：缺省给空报表，
// 单条用例可覆盖出「卡点行」—— 那是**实例显示口径**（`逻辑名 · 部位`）的第三个消费面。
const mockGetStuckPoints = vi.fn()

vi.mock('@/lib/api', () => ({
  processingOrderApi: {
    detail: (...args: unknown[]) => mockDetail(...args),
  },
  productionApi: {
    getOrderOperations: (...args: unknown[]) => mockGetOrderOperations(...args),
    getPiecework: (...args: unknown[]) => mockGetPiecework(...args),
    instantiate: (...args: unknown[]) => mockInstantiate(...args),
    recordPrint: (...args: unknown[]) => mockRecordPrint(...args),
    revokeQrToken: (...args: unknown[]) => mockRevokeQrToken(...args),
    regenerateQrToken: (...args: unknown[]) => mockRegenerateQrToken(...args),
    repriceUnpricedInstances: (...args: unknown[]) => mockRepriceUnpricedInstances(...args),
    // issue #4949：本 mock 此前**缺** `getStuckPoints` ⇒ 页面调用时抛 TypeError 被 try/catch 吞掉
    // （测试仍 PASS，但 stderr 一直有噪音，且「卡在哪」面板恒走错误分支 —— 假覆盖）。
    // ⇒ 恒给**成功**值（缺省 = 空报表，见 `beforeEach`），让页面走真实渲染路径。
    getStuckPoints: (...args: unknown[]) => mockGetStuckPoints(...args),
  },
}))

// 权限显隐用例需要切换当前用户（usePermission → useAuthStore(selector)）
const mockUseAuthStore = vi.fn()
vi.mock('@/store/auth', () => ({
  useAuthStore: (selector: any) => (selector ? selector(mockUseAuthStore()) : mockUseAuthStore()),
}))

vi.mock('@/lib/use-route-id', () => ({
  useRouteId: () => 'JG-20260917-0001',
}))

import ProductionDetailPage from '@/app/(dashboard)/processing-orders/[id]/production/page'

const PROCESSING_ORDER = {
  id: 'po-1',
  orderId: 'order-uuid-1',
  orderNo: 'MG20260917001',
  processingOrderNo: 'JG-20260917-0001',
  customerName: '李四',
  expectedDeliveryDate: '2026-09-25',
  status: 'in_processing' as const,
  generatedAt: '2026-09-17 10:00:00',
}

/** issue #4946：纸面/弹层的码 = **该部位自己的** `scan_url`（不是加工单号，也不是单张 qr_token） */
const PART_SCAN_URL = 'https://app.migaozn.com/s/7K3M9QP2'
const PART_SHORT_CODE = '7K3M9QP2'
/** issue #4287：重新发码后该部位拿到的是**新**码（旧纸不作废就成了假话） */
const PART_SCAN_URL_REISSUED = 'https://app.migaozn.com/s/9Z2X4WQ7'
const PART_SHORT_CODE_REISSUED = '9Z2X4WQ7'

const OPERATIONS = {
  order_id: 'order-uuid-1',
  qr_token: 'qr-token-abc123',
  positions: [
    {
      position_name: '布帘',
      // issue #4946：粒度 = 商品行 = 部位，码 = 该部位自己的 `scan_url`（人可读短码 = part_short_code）
      order_item_id: 'item-1',
      position_kind: '布帘',
      set_no: 'JG-20260917-0001-001',
      product_name: '布艺遮光帘A',
      part_token: 'part-token-1',
      part_short_code: PART_SHORT_CODE,
      scan_url: PART_SCAN_URL,
      operations: [
        {
          id: 'op-1',
          seq: 1,
          operation: '精裁-布',
          group: '裁剪',
          unit: '套',
          qty: 2,
          unit_price: 8.5,
          is_must_finish: false,
          status: 'done',
          done_qty: 2,
        },
        {
          id: 'op-2',
          seq: 2,
          operation: '外帘装袋',
          group: '后道',
          unit: '件',
          qty: 2,
          unit_price: 3,
          is_must_finish: true,
          status: 'pending',
          done_qty: 0,
        },
      ],
    },
  ],
  progress: { total: 2, done: 1, percent: 50 },
}

const PIECEWORK = {
  total: 17,
  per_worker: { 蒋雪云: 17 },
  per_operation: [{ operation: '精裁-布', amount: 17 }],
}

const ok = (data: unknown) => ({ data: { success: true, data } })

/**
 * 撤销后后端语义：`qr_token` 置空（工序实例仍在），见 PG-019 data_checks「二维码撤销」。
 *
 * issue #4946：任务卡印的是**部位自己的码**（`scan_url`/`part_token`）⇒ 撤销必须覆盖它们
 * （码失效 ⇒ 读面不再给码），否则页面上仍挂着已作废的码、纸面占位文案也不会出现。
 */
const OPERATIONS_REVOKED = {
  ...OPERATIONS,
  qr_token: null,
  positions: OPERATIONS.positions.map((position) => ({
    ...position,
    part_token: null,
    part_short_code: null,
    scan_url: null,
  })),
}

/**
 * issue #4287 重新发码后的读面：`qr_token` 与每张部位码都换成**新的**
 * （撤销 = 旧纸作废 ⇒ 重新发码**绝不能**把旧码搬回来，否则「已失效」是假话）。
 */
const OPERATIONS_REISSUED = {
  ...OPERATIONS,
  qr_token: 'qr-token-new',
  positions: OPERATIONS.positions.map((position) => ({
    ...position,
    part_token: 'part-token-2',
    part_short_code: PART_SHORT_CODE_REISSUED,
    scan_url: PART_SCAN_URL_REISSUED,
  })),
}

describe('加工单生产明细页', () => {
  beforeEach(() => {
    // 默认 operator（持有 processing:manage ⇒ 撤销入口可见）
    mockUseAuthStore.mockReset().mockReturnValue({
      user: { id: 'u-1', name: '运营', roles: ['operator'], permissions: ['processing:manage'] },
    })
    mockDetail.mockReset().mockResolvedValue(ok(PROCESSING_ORDER))
    mockGetOrderOperations.mockReset().mockResolvedValue(ok(OPERATIONS))
    mockGetPiecework.mockReset().mockResolvedValue(ok(PIECEWORK))
    mockInstantiate.mockReset().mockResolvedValue(ok({ qr_token: 'qr-token-abc123', operation_count: 2 }))
    mockRecordPrint.mockReset().mockResolvedValue(ok({ print_count: 1 }))
    mockRevokeQrToken.mockReset().mockResolvedValue(ok({ order_id: 'order-uuid-1', qr_token: null, revoked: true }))
    mockRegenerateQrToken.mockReset().mockResolvedValue(
      ok({ order_id: 'order-uuid-1', qr_token: 'qr-token-new', part_codes: 1 }),
    )
    mockRepriceUnpricedInstances.mockReset().mockResolvedValue(
      ok({ filled: 1, already_priced: 1, still_unpriced: 0, batch_id: 'batch-1' }),
    )
    // 「卡在哪」缺省 = 空报表（issue #4949：不抛错、走真实渲染路径）
    mockGetStuckPoints.mockReset().mockResolvedValue(
      ok({
        mode: 'A',
        threshold_hours: 4,
        threshold_source: 'default',
        states: { not_started: 0, in_progress: 0, completed: 0 },
        stuck_total: 0,
        stuck: [],
      }),
    )
  })

  it('渲染头部信息：加工单号/订单号/状态/交期 + 进度百分比', async () => {
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-header')).toBeInTheDocument())

    expect(screen.getByTestId('production-processing-order-no')).toHaveTextContent('JG-20260917-0001')
    expect(screen.getByTestId('production-order-no')).toHaveTextContent('MG20260917001')
    expect(screen.getByTestId('production-status')).toHaveTextContent('加工中')
    expect(screen.getByTestId('production-delivery-date')).toHaveTextContent('2026-09-25')
    expect(screen.getByTestId('production-progress-text')).toHaveTextContent('50%')
    expect(screen.getByTestId('production-progress-text')).toHaveTextContent('1/2')
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '50')
  })

  it('用加工单上的 orderId 拉工序与计件，并渲染工序表 + 计件合计（「必完」badge 已退场，issue #4961）', async () => {
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('operation-row-op-1')).toBeInTheDocument())

    expect(mockGetOrderOperations).toHaveBeenCalledWith('order-uuid-1')
    expect(mockGetPiecework).toHaveBeenCalledWith('order-uuid-1')
    // ⚠️ issue #4961 改判（本行原断言 `operation-row-op-2` 里有「必完」badge，夹具 op-2 的
    // `is_must_finish: true` 就是它的红证）：完工口径改为「全部工序实例全绿」后这枚 badge 退场
    // ⇒ 判据换成**反向断言**；删的是门槛标记，**不是**这一行 —— 工序显示名与计件合计照旧。
    expect(screen.queryByText('必完')).toBeNull()
    expect(within(screen.getByTestId('operation-row-op-2')).getByText('外帘装袋')).toBeInTheDocument()
    expect(screen.getByTestId('piecework-total')).toHaveTextContent('¥17.00')
  })

  // ── 实例显示口径（issue #4960 第 3 条核查）：`逻辑名 · 部位` 全站**只有一份**拼装 ──
  // 「卡在哪」这一行此前在本页**手拼**了 `${logical_name} · ${position}`，与同页进度表
  // （`ProductionProgressTable` → `operationDisplayName`）**两套口径** ⇒ 现在两处都走同一份。
  // ⚠️ 夹具**刻意造出两套实现会分歧的输入**（否则这条判据是空断言）：
  //   ③ 键值带空白（helper 冻结口径会 trim）④ 缺 `logical_name`（helper 不发明名字）。
  it('「卡在哪」的工序名走唯一口径（`逻辑名 · 部位`）：有部位 ⇒ `精裁 · 布帘`；部位无关 ⇒ 只显示逻辑名、不拼空部位', async () => {
    mockGetStuckPoints.mockResolvedValue(
      ok({
        mode: 'A',
        threshold_hours: 4,
        threshold_source: 'default',
        states: { not_started: 4, in_progress: 0, completed: 0 },
        stuck_total: 4,
        stuck: [
          // ① 正：有部位 ⇒ `逻辑名 · 部位`
          {
            set_id: 'set-1',
            set_no: 'JG-20260917-0001-001',
            operation: { operation_id: 'op-1', logical_name: '精裁', position: '布帘', seq: 1 },
            stalled_hours: 5.5,
          },
          // ② 负：部位无关工序（`position` 为 null）⇒ 只显示逻辑名，**不拼空部位**
          {
            set_id: 'set-2',
            set_no: 'JG-20260917-0001-002',
            operation: { operation_id: 'op-9', logical_name: '外帘装袋', position: null, seq: 9 },
            stalled_hours: 7,
          },
          // ③ 红证：键值带空白 ⇒ helper 的冻结口径会 trim（改前的手拼形态渲染成 ` 韩褶  ·  纱帘 `）
          {
            set_id: 'set-3',
            set_no: 'JG-20260917-0001-003',
            operation: { operation_id: 'op-3', logical_name: ' 韩褶 ', position: ' 纱帘 ', seq: 3 },
            stalled_hours: 2,
          },
          // ④ 红证：缺 `logical_name`（老数据 / 自建工序）⇒ **不发明名字**，落既有空态符 `—`
          //    （改前的手拼形态按 `position` 有值走前半支 ⇒ 渲染成 ` · 布帘`，名是空的）
          {
            set_id: 'set-4',
            set_no: 'JG-20260917-0001-004',
            operation: { operation_id: 'op-4', logical_name: null, position: '布帘', seq: 4 },
            stalled_hours: 3,
          },
        ],
      }),
    )
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getAllByTestId('production-stuck-points-row')).toHaveLength(4))
    const rows = screen.getAllByTestId('production-stuck-points-row')

    // ① 正：逐字 `精裁 · 布帘`（分隔符两侧各一个空格 —— 与 helper 的冻结口径一致）
    expect(rows[0]).toHaveTextContent('精裁 · 布帘')
    // ② 负：只显示逻辑名；**不得**出现空部位拖尾（`外帘装袋 ·`）或空态符（`—`）
    expect(rows[1]).toHaveTextContent('外帘装袋')
    expect(rows[1]).not.toHaveTextContent('外帘装袋 ·')
    expect(rows[1]).not.toHaveTextContent('—')
    // ③ 红证：空白被 trim 掉（手拼形态在这里判红）
    expect(rows[2]).toHaveTextContent('韩褶 · 纱帘')
    // ④ 红证：读面没给逻辑名 ⇒ 落空态符，**不得**把「部位」冒充成工序名
    expect(rows[3]).toHaveTextContent('—')
    expect(rows[3]).not.toHaveTextContent('· 布帘')
  })

  // ── 套口径（issue #4686，用户裁定 2026-09-20「一樘窗 = 一套」）──
  // 「工序进度」区块的分组**不是**「部位」（部位 = 布帘/纱帘/帘头，读面键 = `position_kind`），
  // 而是**套**（一樘窗 = 一套）；组头按行业口径显示「第 N 套 / 共 M 套」
  // （真值源 `docs/curtain-production-rules.md` 的「第 N 套/共 M 套」口径 —— 按该文本检索，不写行号）。
  it('工序进度按「套」分组：组头显示「第 1 套 / 共 1 套」，不再把一樘窗称作「部位」', async () => {
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('operation-row-op-1')).toBeInTheDocument())

    // 本夹具 = 单窗订单 ⇒ 逐字「第 1 套 / 共 1 套」
    // ⚠️ 必须**限定在进度表内**（issue #4949）：洗水码纸面（屏幕上 `display:none`）此后也印同一句话，
    // 全页 `getByText` 会命中 2 个元素 ⇒ 误报「multiple elements found」。这里要钉的是**进度表组头**。
    expect(within(screen.getByTestId('position-group-布帘')).getByText('第 1 套 / 共 1 套')).toBeInTheDocument()

    // 红证（改前实测）：组头逐字为「部位：布帘」⇒ 下面两条改前必红
    const group = screen.getByTestId('position-group-布帘')
    expect(within(group).queryByText(/部位/)).toBeNull()
    // 保留可识别信息：这一套是**哪一樘窗**（position_name 作副标题，不再当「部位」标签）
    expect(within(group).getByText('布帘')).toBeInTheDocument()
  })

  it('「打印任务卡」按钮调用 window.print（任务卡含二维码）', async () => {
    const printSpy = vi.spyOn(window, 'print').mockImplementation(() => {})
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-header')).toBeInTheDocument())

    // 任务卡随页面挂载（屏幕隐藏、打印显形），二维码内容是 qr_token。
    // ⚠️ 必须**等元素**而不是假设它已在场（issue #4709 顺带修，全量跑实测偶发）：
    // 任务卡依赖 `getOrderOperations` 的解析（qr_token 来自它），而上一行的
    // `production-header` 来自**另一个** promise（`processingOrderApi.detail`）⇒
    // 只等 header 会在高负载（全量并行跑）下偶发拿不到二维码（同 §15.1「等元素而非定长 sleep」）。
    await waitFor(() => expect(screen.getByTestId('task-card-qr')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('production-print-button'))

    // issue #4717：断言的对象本身就必须是**被等待的可观察条件**（#4414 口径 ——
    // 「把同步断言并进同一个 waitFor，等的是『调用发生』这件事本身」）。
    //
    // 改前形态 = `await waitFor(A)` 之后紧跟 `expect(B)` 的**同步**断言 ⇒ A 与 B 由不同
    // commit 产出时就是竞态。本用例的 A（`task-card-qr`）来自 `TaskCardPrint` 的
    // **被动副作用**（portal + `if (!mounted) return null`，见 components/production/TaskCardPrint.tsx）
    // ⇒ 它比页头晚一次 commit；全量并行（负载高）下那次刷新被拖后 ⇒ 窗口变宽 ⇒ 偶发红。
    await waitFor(() => expect(printSpy).toHaveBeenCalledTimes(1))

    printSpy.mockRestore()
  })

  it('打印时上报打印计数，且计数接口失败不阻断打印（fire-and-forget）', async () => {
    const printSpy = vi.spyOn(window, 'print').mockImplementation(() => {})
    mockRecordPrint.mockRejectedValueOnce(new Error('boom'))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-header')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('production-print-button'))

    // 先调计数端点（不 await 结果），再打印。
    // 这里的**同步**断言是**因果成立**的（#4717 同族自查）：`handlePrint` 里
    // `recordPrint(...)` 与 `window.print()` 是**同一段同步代码**（前者不 await）⇒
    // 「recordPrint 已被调用」一旦成立，`window.print()` 必已发生，不存在跨 commit 窗口。
    await waitFor(() => expect(mockRecordPrint).toHaveBeenCalledWith('order-uuid-1'))
    expect(printSpy).toHaveBeenCalledTimes(1)

    printSpy.mockRestore()
  })

  it('工序接口失败：给出提示且不白屏（计件仍展示）', async () => {
    mockGetOrderOperations.mockRejectedValue(new Error('boom'))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-operations-error')).toBeInTheDocument())

    expect(screen.getByTestId('production-operations-error')).toHaveTextContent('工序进度加载失败')
    expect(screen.getByTestId('production-header')).toBeInTheDocument()
    expect(screen.getByTestId('piecework-total')).toHaveTextContent('¥17.00')
  })

  it('加工单详情失败：显示错误提示 + 重试按钮（可重新拉取）', async () => {
    mockDetail.mockRejectedValueOnce(new Error('network'))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-error')).toBeInTheDocument())
    expect(screen.getByTestId('production-error')).toHaveTextContent('加载加工单失败')

    await userEvent.click(screen.getByTestId('production-retry-button'))

    await waitFor(() => expect(screen.getByTestId('production-header')).toBeInTheDocument())
    expect(mockDetail).toHaveBeenCalledTimes(2)
  })

  it('加工单无工序实例：空态提示，不报错', async () => {
    mockGetOrderOperations.mockResolvedValue(ok({ order_id: 'order-uuid-1', qr_token: null, positions: [], progress: { total: 0, done: 0, percent: 0 } }))
    mockGetPiecework.mockResolvedValue(ok({ total: 0, per_worker: {}, per_operation: [] }))
    render(<ProductionDetailPage />)

    // issue #4414：页面有**两个独立请求**（工序 + 计件）；waitFor 只等了其中一个，
    // 后两条**同步断言**依赖另一个已 resolve ⇒ 间歇性红（部署关键路径）。
    // ⇒ 一次 waitFor 同时断言三者。
    await waitFor(() => {
      expect(screen.getByText('暂无工序数据')).toBeInTheDocument()
      expect(screen.getByText('暂无计件数据')).toBeInTheDocument()
      expect(screen.getByTestId('task-card-qr-placeholder')).toBeInTheDocument()
    })
  })

  // ── PG-019：存量加工单补生成工序（issue #4202 前端半边）──

  it('存量加工单（positions 空 + 非 cancelled）：显示「补生成工序」按钮', async () => {
    mockGetOrderOperations.mockResolvedValue(ok({ order_id: 'order-uuid-1', qr_token: null, positions: [], progress: { total: 0, done: 0, percent: 0 } }))
    mockGetPiecework.mockResolvedValue(ok({ total: 0, per_worker: {}, per_operation: [] }))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-instantiate-button')).toBeInTheDocument())
    expect(screen.getByTestId('production-instantiate-button')).toHaveTextContent('补生成工序')
  })

  it('点击「补生成工序」：调 instantiate（空 body）→ 刷新出工序表与二维码', async () => {
    mockGetOrderOperations
      .mockResolvedValueOnce(ok({ order_id: 'order-uuid-1', qr_token: null, positions: [], progress: { total: 0, done: 0, percent: 0 } }))
      .mockResolvedValue(ok(OPERATIONS))
    mockGetPiecework.mockResolvedValue(ok(PIECEWORK))
    mockInstantiate.mockResolvedValue(ok({ qr_token: 'qr-token-abc123', operation_count: 2 }))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-instantiate-button')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('production-instantiate-button'))

    // 空 body = 服务端按订单自动派生工序（冻结契约：positions 可选）
    await waitFor(() => expect(mockInstantiate).toHaveBeenCalledWith('order-uuid-1'))
    // 刷新后出真实工序行 + 二维码；按钮消失（已有工序）
    await waitFor(() => expect(screen.getByTestId('operation-row-op-1')).toBeInTheDocument())
    expect(screen.getByTestId('task-card-qr')).toBeInTheDocument()
    expect(screen.queryByTestId('production-instantiate-button')).not.toBeInTheDocument()
  })

  it('补生成失败：错误提示可见，且按钮保留（可重试）', async () => {
    mockGetOrderOperations.mockResolvedValue(ok({ order_id: 'order-uuid-1', qr_token: null, positions: [], progress: { total: 0, done: 0, percent: 0 } }))
    mockGetPiecework.mockResolvedValue(ok({ total: 0 }))
    mockInstantiate.mockRejectedValueOnce(new Error('422 positions 不能为空'))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-instantiate-button')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('production-instantiate-button'))

    await waitFor(() => expect(screen.getByTestId('production-instantiate-error')).toBeInTheDocument())
    expect(screen.getByTestId('production-instantiate-button')).toBeInTheDocument()
  })

  it('已有工序实例：不显示「补生成工序」（避免误重插行）', async () => {
    render(<ProductionDetailPage />)
    await waitFor(() => expect(screen.getByTestId('operation-row-op-1')).toBeInTheDocument())

    expect(screen.queryByTestId('production-instantiate-button')).not.toBeInTheDocument()
  })

  it('已取消加工单：不显示「补生成工序」（终态不可重生成）', async () => {
    mockDetail.mockResolvedValue(ok({ ...PROCESSING_ORDER, status: 'cancelled' }))
    mockGetOrderOperations.mockResolvedValue(ok({ order_id: 'order-uuid-1', qr_token: null, positions: [], progress: { total: 0, done: 0, percent: 0 } }))
    mockGetPiecework.mockResolvedValue(ok({ total: 0 }))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-header')).toBeInTheDocument())
    expect(screen.queryByTestId('production-instantiate-button')).not.toBeInTheDocument()
  })

  it('任务卡占位文案不误导：不得再指向「请先在订单详情生成加工单」', async () => {
    mockGetOrderOperations.mockResolvedValue(ok({ order_id: 'order-uuid-1', qr_token: null, positions: [], progress: { total: 0, done: 0, percent: 0 } }))
    mockGetPiecework.mockResolvedValue(ok({ total: 0 }))
    render(<ProductionDetailPage />)

    // 任务卡是 portal + display:none（打印才显形）⇒ 判文案只看 DOM 存在性，不能用 innerText
    await waitFor(() => expect(screen.getByTestId('task-card-no')).toHaveTextContent('JG-20260917-0001'))
    const placeholder = screen.getByTestId('task-card-qr-placeholder')
    // 加工单**已生成**，二维码缺的真成因是「工序未生成」⇒ 不得再指回去生成加工单
    expect(placeholder.textContent).not.toContain('请先在订单详情生成加工单')
    // 指引指向本页的补生成工序（同一修复面的正向判据）
    expect(screen.getByTestId('production-instantiate-button')).toHaveTextContent('补生成工序')
  })

  // ── PG-019（#4240 前端半边）：撤销二维码入口（真值源 §1「token 化、可撤销」）──

  it('#4240 有二维码 + 有 processing:manage：入口可达，点开只弹二次确认（未确认不发请求）', async () => {
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('task-card-qr')).toBeInTheDocument())
    const entry = screen.getByTestId('production-revoke-button')
    expect(entry).toHaveTextContent('撤销二维码')

    await userEvent.click(entry)

    // 二次确认弹窗出现（口径：真值源 §1 撤销是安全相关写操作，避免误触作废已打印纸件）
    expect(await screen.findByRole('dialog', { name: '撤销二维码' })).toBeInTheDocument()
    // **未确认 ⇒ 一个请求都不许发**（红证：去掉确认直接调端点 ⇒ 本条必红）
    expect(mockRevokeQrToken).not.toHaveBeenCalled()
  })

  it('#4240 弹窗点「取消」：关窗且不发请求', async () => {
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('task-card-qr')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('production-revoke-button'))
    await screen.findByRole('dialog', { name: '撤销二维码' })

    await userEvent.click(screen.getByTestId('production-revoke-cancel'))

    await waitFor(() => expect(screen.queryByRole('dialog', { name: '撤销二维码' })).not.toBeInTheDocument())
    expect(mockRevokeQrToken).not.toHaveBeenCalled()
    // 入口保留（可再次发起）
    expect(screen.getByTestId('production-revoke-button')).toBeInTheDocument()
  })

  it('#4240 确认撤销：按 orderId 调 revoke → 刷新回占位态 + 可见「已撤销」反馈 + 入口消失', async () => {
    mockGetOrderOperations
      .mockResolvedValueOnce(ok(OPERATIONS))
      .mockResolvedValue(ok(OPERATIONS_REVOKED))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('task-card-qr')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('production-revoke-button'))
    await screen.findByRole('dialog', { name: '撤销二维码' })
    // issue #4287：入口已落地 ⇒ 弹层不再需要「本页无法重新发码」的免责声明（那是 #4949 的临时措辞），
    // 改为如实指向撤销成功后可用的入口。
    expect(screen.getByTestId('production-revoke-reissue-hint')).toHaveTextContent('重新生成二维码')
    await userEvent.click(screen.getByTestId('production-revoke-confirm'))

    // 生产端点一律走**订单 id**（不是加工单号），与既有 instantiate/print 同口径
    await waitFor(() => expect(mockRevokeQrToken).toHaveBeenCalledWith('order-uuid-1'))

    // 撤销后刷新数据 ⇒ 任务卡二维码回到占位态（旧码在页面上不再出现）
    await waitFor(() => expect(screen.getByTestId('task-card-qr-placeholder')).toBeInTheDocument())
    expect(screen.queryByTestId('task-card-qr')).not.toBeInTheDocument()
    // 占位文案要说清为什么没码（不能仍指向不存在的「补生成工序」按钮）
    expect(screen.getByTestId('task-card-qr-placeholder').textContent).toContain('已撤销')

    // 可见反馈（屏幕上的「已撤销」提示，不是仅 toast）
    const notice = screen.getByTestId('production-revoke-success')
    expect(notice).toBeVisible()
    expect(notice).toHaveTextContent('已撤销')
    expect(notice).toHaveTextContent('旧码')
    // 已无可撤销对象 ⇒ 入口收起（防对空 token 重复撤销）
    expect(screen.queryByTestId('production-revoke-button')).not.toBeInTheDocument()
  })

  it('#4240 权限显隐：无 processing:manage（客服）时入口不渲染（有二维码也不渲染）', async () => {
    mockUseAuthStore.mockReturnValue({
      user: { id: 'u-2', name: '客服小王', roles: ['customer_service'], permissions: ['order:list'] },
    })
    render(<ProductionDetailPage />)

    // 页面数据照常加载（工序/二维码都在）—— 挡住的只是写入口
    await waitFor(() => expect(screen.getByTestId('task-card-qr')).toBeInTheDocument())
    // 红证：去掉显隐判断（无条件渲染按钮）⇒ 本条必红
    expect(screen.queryByTestId('production-revoke-button')).not.toBeInTheDocument()
    // 其它入口不受影响（打印任务卡沿用类级 order:list 口径，仍可见）
    expect(screen.getByTestId('production-print-button')).toBeInTheDocument()
  })

  it('#4240 无二维码（qr_token 为空）：不渲染撤销入口（无可撤销对象）', async () => {
    mockGetOrderOperations.mockResolvedValue(ok({ ...OPERATIONS_REVOKED, positions: [] }))
    mockGetPiecework.mockResolvedValue(ok({ total: 0 }))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-header')).toBeInTheDocument())
    expect(screen.queryByTestId('production-revoke-button')).not.toBeInTheDocument()
  })

  it('#4240 撤销失败：弹窗内可见错误提示，不误报成功，入口保留（可重试）', async () => {
    mockRevokeQrToken.mockRejectedValueOnce(new Error('403 Forbidden'))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('task-card-qr')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('production-revoke-button'))
    await screen.findByRole('dialog', { name: '撤销二维码' })
    await userEvent.click(screen.getByTestId('production-revoke-confirm'))

    await waitFor(() => expect(screen.getByTestId('production-revoke-error')).toBeInTheDocument())
    expect(screen.getByTestId('production-revoke-error')).toHaveTextContent('撤销二维码失败')
    // 失败不得走到「已撤销」反馈，也不得把二维码改成占位态
    expect(screen.queryByTestId('production-revoke-success')).not.toBeInTheDocument()
    expect(screen.getByTestId('task-card-qr')).toBeInTheDocument()
    expect(screen.getByTestId('production-revoke-button')).toBeInTheDocument()
  })

  // ── #4287：撤销后的「重新生成二维码」入口（缺口闭合；**不得**复用 instantiate）──
  // 病根（改前实测）：撤销把 `qr_token` 与**每张部位码**都置空，而页面上没有任何入口能重新发码
  // （「补生成工序」只在 0 部位时渲染）⇒ 商家撤销后印不出可扫的任务卡（#4949 只能写免责声明）。
  // 🔴 硬约束：**不得**把「重新生成」接到 instantiate —— 它的签名幂等判据在工序库改价后会
  // 软删旧实例并重插 ⇒ `done_qty` 归零 ⇒ 连带清掉该单的计件工资。

  it('#4287 撤销成功后：出现「重新生成二维码」入口；点击按 orderId 调 regenerate → 刷新出新码', async () => {
    mockGetOrderOperations
      .mockResolvedValueOnce(ok(OPERATIONS)) // 首屏：有码（可撤销）
      .mockResolvedValueOnce(ok(OPERATIONS_REVOKED)) // 撤销后：占位（此时才该出现重新生成入口）
      .mockResolvedValue(ok(OPERATIONS_REISSUED)) // 重新发码后：新码上屏
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('task-card-qr')).toBeInTheDocument())
    // 有码时**没有**可重发的对象（对一张有效的码重发 = 静默作废已打印的纸）
    expect(screen.queryByTestId('production-regenerate-button')).not.toBeInTheDocument()

    await userEvent.click(screen.getByTestId('production-revoke-button'))
    await screen.findByRole('dialog', { name: '撤销二维码' })
    await userEvent.click(screen.getByTestId('production-revoke-confirm'))

    // 红证（改前实测）：撤销后页面上**没有任何**重新发码入口 ⇒ findByTestId 超时必红
    const entry = await screen.findByTestId('production-regenerate-button')
    expect(entry).toHaveTextContent('重新生成二维码')
    expect(entry).toBeVisible()

    await userEvent.click(entry)

    // 生产端点一律走**订单 id**（与 revoke/instantiate/print 同口径）
    await waitFor(() => expect(mockRegenerateQrToken).toHaveBeenCalledWith('order-uuid-1'))
    // 红证：把入口接到 instantiate ⇒ 下面两条必红（那会清掉报工 ⇒ 计件工资没了）
    expect(mockInstantiate).not.toHaveBeenCalled()
    expect(mockRevokeQrToken).toHaveBeenCalledTimes(1)
    // 新码来自**服务端刷新**（不是本地编造）：任务卡二维码回来了，且是**新码**而非旧码
    await waitFor(() => expect(screen.getByTestId('task-card-qr')).toBeInTheDocument())
    expect(screen.getByTestId('task-card-qr').querySelector('title')?.textContent).toBe(PART_SCAN_URL_REISSUED)
    expect(screen.getByTestId('production-regenerate-success')).toBeVisible()
  })

  it('#4287 重新生成失败：可见错误提示、不误报成功、入口保留（可重试）', async () => {
    mockGetOrderOperations.mockResolvedValue(ok(OPERATIONS_REVOKED))
    mockRegenerateQrToken.mockRejectedValueOnce(new Error('403 Forbidden'))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-regenerate-button')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('production-regenerate-button'))

    await waitFor(() => expect(screen.getByTestId('production-regenerate-error')).toBeInTheDocument())
    expect(screen.getByTestId('production-regenerate-error')).toHaveTextContent('重新生成二维码失败')
    // 失败不得留下「已重新生成」的假反馈
    expect(screen.queryByTestId('production-regenerate-success')).not.toBeInTheDocument()
    expect(screen.getByTestId('production-regenerate-button')).toBeInTheDocument()
  })

  it('#4287 权限显隐：无 processing:manage（客服）时不渲染「重新生成二维码」', async () => {
    mockUseAuthStore.mockReturnValue({
      user: { id: 'u-2', name: '客服小王', roles: ['customer_service'], permissions: ['order:list'] },
    })
    mockGetOrderOperations.mockResolvedValue(ok(OPERATIONS_REVOKED))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-header')).toBeInTheDocument())
    // 缺口态（qr_token 为空）也不渲染 —— 与 revoke 同码（方法级 processing:manage），避免可见却 403
    expect(screen.queryByTestId('production-regenerate-button')).not.toBeInTheDocument()
    // 其它入口不受影响（打印任务卡沿用类级 order:list 口径）
    expect(screen.getByTestId('production-print-button')).toBeInTheDocument()
  })

  // ── #4726：「生成二维码（测试用）」入口（A 档 = 加工单号纯文本码）──
  // 用户原话（2026-09-20）：「能不能在这里加个按钮生成二维码，这样就能串联起来扫码生产&计件了，
  // 这个按钮主要是用来测试」。串联链路 = 屏幕出码 → 任意扫码工具读到**加工单号** →
  // 工人在 bmini 报工页**手动输入**单号 → 报工 → 计件（#3997/#4206 已存在的那一页）。
  // A 档**不是**「扫一下就进」（要手输单号）；B 档小程序码才是（本单凭据不齐，见 PR body）。

  it('#4726 有 processing:manage：页头渲染「生成二维码（测试用）」入口', async () => {
    render(<ProductionDetailPage />)
    await waitFor(() => expect(screen.getByTestId('production-header')).toBeInTheDocument())

    // 红证（改前实测）：改前无该入口 ⇒ getByTestId 直接抛
    //   「Unable to find an element by: [data-testid="production-test-qr-button"]」⇒ 必红
    const entry = screen.getByTestId('production-test-qr-button')
    expect(entry).toHaveTextContent('生成二维码')
    // 「测试用」必须写在**入口文案**上（不能让商家误当成正式发码入口）
    expect(entry).toHaveTextContent('测试用')
  })

  it('#4946 点开弹层：**逐张**出码（第 0 张 = 该部位自己的 scan_url，不是单号码、不是 qr_token）+ 明示「测试用」', async () => {
    render(<ProductionDetailPage />)
    await waitFor(() => expect(screen.getByTestId('production-header')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('production-test-qr-button'))

    // 红证（改前实测）：点击后无二维码/无单号 ⇒ findByRole 超时必红
    const dialog = await screen.findByRole('dialog', { name: '生成二维码（测试用）' })

    const qr = within(dialog).getByTestId('production-test-qr-code-0')
    expect(qr.tagName.toLowerCase()).toBe('svg')
    // qrcode.react 的 title prop → svg <title>；断言**该部位自己的扫码内容**真的进了二维码组件
    // （issue #4946：逐张出码，第 0 张 = 第 0 个部位）
    expect(within(qr).getByTitle(PART_SCAN_URL)).toBeInTheDocument()
    expect(qr.querySelectorAll('path').length).toBeGreaterThan(0)
    // 内容不得是 qr_token（任务卡的码与「测试用」弹层的码都不是单号拼接串）
    expect(within(qr).queryByTitle('qr-token-abc123')).toBeNull()

    // 屏幕上也要有可读的单号文本（扫码工具读不出来时人眼可核）
    expect(within(dialog).getByTestId('production-test-qr-order-no')).toHaveTextContent('JG-20260917-0001')
    // 弹层内明示「测试用」+ 说明要手输单号（不得暗示「扫一下就进」）
    expect(dialog.textContent).toContain('测试用')
    expect(dialog.textContent).toContain('手动输入')
  })

  it('#4726 弹层「复制单号」：把加工单号写进剪贴板', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    render(<ProductionDetailPage />)
    await waitFor(() => expect(screen.getByTestId('production-header')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('production-test-qr-button'))
    await screen.findByRole('dialog', { name: '生成二维码（测试用）' })
    await userEvent.click(screen.getByTestId('production-test-qr-copy'))

    // 复制的是**加工单号**（工人粘进 bmini 报工页的单号输入框）
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('JG-20260917-0001'))
  })

  it('#4726 只读护栏：生成二维码 / 复制单号**零写请求**，qr_token 一字不动', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    render(<ProductionDetailPage />)
    await waitFor(() => expect(screen.getByTestId('task-card-qr')).toBeInTheDocument())

    // 操作前：任务卡二维码内容 = **该部位自己的码**（issue #4946；页面上的权威扫码入口）
    const codeBefore = screen.getByTestId('task-card-qr').querySelector('title')?.textContent
    expect(codeBefore).toBe(PART_SCAN_URL)

    await userEvent.click(screen.getByTestId('production-test-qr-button'))
    await screen.findByRole('dialog', { name: '生成二维码（测试用）' })
    await userEvent.click(screen.getByTestId('production-test-qr-copy'))

    // 红证：在入口 handler 里注入「生成即写库」（调 revokeQrToken / instantiate）⇒ 下面必红
    expect(mockRevokeQrToken).not.toHaveBeenCalled()
    expect(mockInstantiate).not.toHaveBeenCalled()
    expect(mockRecordPrint).not.toHaveBeenCalled()
    // 也不许借生成之名重新拉数据（生成是纯前端渲染，不触发任何网络）
    expect(mockGetOrderOperations).toHaveBeenCalledTimes(1)
    expect(mockGetPiecework).toHaveBeenCalledTimes(1)
    // 码内容一字不动（撤销/重发都会让它变）
    expect(screen.getByTestId('task-card-qr').querySelector('title')?.textContent).toBe(PART_SCAN_URL)
    // 测试码弹层开着也不影响权威码的存在
    expect(screen.getByTestId('task-card-qr')).toBeInTheDocument()
  })

  // ── #4946：弹层**逐张**出码（N 个商品/部位 ⇒ N 张码，各带短码 + 复制短码）──
  // 用户裁定（2026-09-21）：「一个加工单里有 3 个商品，就要出 3 张，每张二维码对应自己的工序」。
  const OPERATIONS_THREE_PARTS = {
    ...OPERATIONS,
    positions: [
      { ...OPERATIONS.positions[0] },
      {
        position_name: '纱帘',
        order_item_id: 'item-2',
        position_kind: '纱帘',
        set_no: 'JG-20260917-0001-001',
        product_name: '纱帘B',
        part_token: 'part-token-2',
        part_short_code: 'QW8Z2N4B',
        scan_url: 'https://app.migaozn.com/s/QW8Z2N4B',
        operations: [
          { id: 'op-3', seq: 1, operation: '韩褶-纱', logical_name: '韩褶', position: '纱帘', group: '车位', unit: '折', qty: 24, status: 'pending', done_qty: 0 },
        ],
      },
      // 第 3 个部位还没有码（未生成 / 已撤销）⇒ 逐张如实说明，不画假码
      {
        position_name: '帘头',
        order_item_id: 'item-3',
        position_kind: '帘头',
        set_no: 'JG-20260917-0001-002',
        product_name: '帘头C',
        part_token: null,
        part_short_code: null,
        scan_url: null,
        operations: [],
      },
    ],
  }

  it('#4946 弹层逐张出码：N 个部位 ⇒ N 张（各 = 自己的 scan_url + 短码 + 复制短码），缺码的那张如实说明', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    mockGetOrderOperations.mockResolvedValue(ok(OPERATIONS_THREE_PARTS))
    render(<ProductionDetailPage />)

    // 纸面侧先成立：3 个部位 ⇒ **恰好** 3 张洗水码（页面把 positions 原样交给任务卡）
    await waitFor(() => expect(screen.getByTestId('task-card-label-2')).toBeInTheDocument())
    expect(screen.getAllByTestId(/^task-card-label-\d$/)).toHaveLength(3)
    expect(within(screen.getByTestId('task-card-label-2')).getByTestId('task-card-qr-placeholder')).toBeInTheDocument()

    await userEvent.click(screen.getByTestId('production-test-qr-button'))
    const dialog = await screen.findByRole('dialog', { name: '生成二维码（测试用）' })

    // 逐张：第 0/1 张真码（各自不同的 scan_url），第 2 张无码 ⇒ 只出说明，不画假码
    expect(within(within(dialog).getByTestId('production-test-qr-code-0')).getByTitle(PART_SCAN_URL)).toBeInTheDocument()
    expect(
      within(within(dialog).getByTestId('production-test-qr-code-1')).getByTitle('https://app.migaozn.com/s/QW8Z2N4B'),
    ).toBeInTheDocument()
    expect(within(dialog).queryByTestId('production-test-qr-code-2')).toBeNull()

    // 每张都标明是**哪一件**（商品名/部位名）+ 人可读短码
    const first = within(dialog).getByTestId('production-test-qr-position-0')
    expect(first).toHaveTextContent('布帘')
    expect(first).toHaveTextContent(PART_SHORT_CODE)
    const third = within(dialog).getByTestId('production-test-qr-position-2')
    expect(third).toHaveTextContent('帘头')
    expect(third).toHaveTextContent('暂无码')

    // 逐张「复制短码」：复制的是**该部位的短码**（工人手输用），不是加工单号
    await userEvent.click(within(dialog).getByTestId('production-test-qr-copy-1'))
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('QW8Z2N4B'))
    expect(writeText).not.toHaveBeenCalledWith('JG-20260917-0001')
  })

  it('#4726 权限显隐：无 processing:manage（客服）时入口不渲染', async () => {
    mockUseAuthStore.mockReturnValue({
      user: { id: 'u-2', name: '客服小王', roles: ['customer_service'], permissions: ['order:list'] },
    })
    render(<ProductionDetailPage />)
    await waitFor(() => expect(screen.getByTestId('production-header')).toBeInTheDocument())

    // 红证：去掉 hasPermission('processing:manage') 判断（无条件渲染按钮）⇒ 本条必红
    expect(screen.queryByTestId('production-test-qr-button')).not.toBeInTheDocument()
    // 页面照常加载；打印入口沿用类级 order:list 口径，不受影响
    expect(screen.getByTestId('production-print-button')).toBeInTheDocument()
  })
})

// ── 路线来源提示（issue #4307 交付物 2 / #4308 P1「静默回落」的用户侧可观测面）──
// 四态：derived 不提示；partial 提示「另一半取默认值」；missing_route 提示「识别的是 X，
// 但库里没有这条路线」；default 高亮提示「本单没有填部位/做法，请核对工序与计件单价」。
// 红证（实现前）：三态全部静默 ⇒ 罗马帘订单拿到布帘 11 道工序而用户面零提示。
describe('加工单生产明细页 — 路线来源提示（PP-014）', () => {
  const withRoute = (routeSource: string, routeKey: string, routeRequestedKey?: string) => ({
    ...PROCESSING_ORDER,
    routeSource,
    routeKey,
    ...(routeRequestedKey ? { routeRequestedKey } : {}),
  })

  beforeEach(() => {
    mockUseAuthStore.mockReset().mockReturnValue({
      user: { id: 'u-1', name: '运营', roles: ['operator'], permissions: ['processing:manage'] },
    })
    mockGetOrderOperations.mockReset().mockResolvedValue(ok(OPERATIONS))
    mockGetPiecework.mockReset().mockResolvedValue(ok(PIECEWORK))
    mockRecordPrint.mockReset().mockResolvedValue(ok({ print_count: 1 }))
  })

  it('default（两维全不命中）：高亮提示 + 报出实际使用的路线键', async () => {
    mockDetail.mockReset().mockResolvedValue(ok(withRoute('default', '布帘×韩褶')))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-route-default')).toBeInTheDocument())
    expect(screen.getByTestId('production-route-default')).toHaveTextContent('没有填部位/做法')
    expect(screen.getByTestId('production-route-default')).toHaveTextContent('请核对工序与计件单价')
    expect(screen.getByTestId('production-route-default-detail')).toHaveTextContent('布帘×韩褶')
    expect(screen.queryByTestId('production-route-partial')).not.toBeInTheDocument()
  })

  it('partial（只命中一维）：提示另一半取默认值，且不显示成 default', async () => {
    mockDetail.mockReset().mockResolvedValue(ok(withRoute('partial', '纱帘×韩褶')))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-route-partial')).toBeInTheDocument())
    expect(screen.getByTestId('production-route-partial')).toHaveTextContent('只填了一半')
    expect(screen.queryByTestId('production-route-default')).not.toBeInTheDocument()
  })

  it('missing_route（两维都命中但库里没这条路线）：报出识别到的键 route_requested_key', async () => {
    mockDetail.mockReset().mockResolvedValue(ok(withRoute('missing_route', '布帘×韩褶', '罗马帘×韩褶')))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-route-missing_route')).toBeInTheDocument())
    expect(screen.getByTestId('production-route-missing_route')).toHaveTextContent('工序库里没有这条路线')
    expect(screen.getByTestId('production-route-missing_route-detail')).toHaveTextContent('本单识别的是 罗马帘×韩褶')
    expect(screen.getByTestId('production-route-missing_route-detail')).toHaveTextContent('本单实际使用：布帘×韩褶')
  })

  it('derived（正常派生）/ 字段缺失：不提示，且不得把「未知」显示成「已派生」', async () => {
    mockDetail.mockReset().mockResolvedValue(ok(withRoute('derived', '布帘×韩褶')))
    const { unmount } = render(<ProductionDetailPage />)
    await waitFor(() => expect(screen.getByTestId('production-header')).toBeInTheDocument())
    expect(screen.queryByTestId('production-route-default')).not.toBeInTheDocument()
    expect(screen.queryByTestId('production-route-partial')).not.toBeInTheDocument()
    expect(screen.queryByTestId('production-route-missing_route')).not.toBeInTheDocument()
    unmount()

    // 存量实例（字段缺失）⇒ 静默 = 未知，不提示任何来源
    mockDetail.mockReset().mockResolvedValue(ok(PROCESSING_ORDER))
    render(<ProductionDetailPage />)
    await waitFor(() => expect(screen.getByTestId('production-header')).toBeInTheDocument())
    expect(screen.queryByTestId('production-route-default')).not.toBeInTheDocument()
    expect(screen.queryByTestId('production-route-partial')).not.toBeInTheDocument()
    expect(screen.queryByTestId('production-route-missing_route')).not.toBeInTheDocument()
  })

  // ── 未定价实例的显式补价入口（issue #4709 C）──
  // 红证（改前）：页面上**没有任何入口**能补价 —— 商家在部位价目矩阵里补了价，而**已实例化**的
  // 旧单快照仍是 `null`（未定价）⇒ 工人那批活的钱算不出来；重新实例化不是可用路径
  // （`null` 与 `0` 同签名 ⇒ 不触发；`null → 非 0` 触发但会软删重插 + 报工进度清零）。
  const OPERATIONS_UNPRICED = {
    ...OPERATIONS,
    positions: [
      {
        position_name: '遮光布料X',
        operations: [
          {
            id: 'op-u1',
            seq: 1,
            operation: '打包',
            position: '布料',
            group: '后道',
            unit: '米',
            qty: 10,
            unit_price: null,
            price_state: 'unpriced',
            status: 'pending',
            done_qty: 0,
          },
          {
            id: 'op-p1',
            seq: 2,
            operation: '精裁-布',
            group: '裁剪',
            unit: '套',
            qty: 2,
            unit_price: 8.5,
            price_state: 'priced',
            status: 'done',
            done_qty: 2,
          },
        ],
      },
    ],
  }

  it('有未定价工序实例 ⇒ 出现「按当前价重算」入口，点击调端点并给出可见反馈', async () => {
    mockGetOrderOperations.mockReset().mockResolvedValue(ok(OPERATIONS_UNPRICED))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-reprice-button')).toBeInTheDocument())
    // 只数**未定价**那道（价 0 / 有价都不算未定价）
    expect(screen.getByTestId('production-reprice-button')).toHaveTextContent('1 道')

    await userEvent.click(screen.getByTestId('production-reprice-button'))

    await waitFor(() => expect(mockRepriceUnpricedInstances).toHaveBeenCalledWith('order-uuid-1'))
    await waitFor(() =>
      expect(screen.getByTestId('production-reprice-notice')).toHaveTextContent('已按当前价补齐 1 道'),
    )
  })

  it('矩阵格仍为空（still_unpriced > 0）⇒ 反馈说清「还有几道没定价」，不只报成功', async () => {
    mockGetOrderOperations.mockReset().mockResolvedValue(ok(OPERATIONS_UNPRICED))
    mockRepriceUnpricedInstances.mockResolvedValue(
      ok({ filled: 0, already_priced: 1, still_unpriced: 1, batch_id: null }),
    )
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-reprice-button')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('production-reprice-button'))

    await waitFor(() =>
      expect(screen.getByTestId('production-reprice-notice')).toHaveTextContent('仍有 1 道未定价'),
    )
  })

  it('边界：无未定价实例 ⇒ 入口不出现（不制造噪音）', async () => {
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-header')).toBeInTheDocument())
    expect(screen.queryByTestId('production-reprice-button')).not.toBeInTheDocument()
  })

  it('边界：无 processing:manage ⇒ 入口不出现（写面端点方法级权限，避免按钮可见却 403）', async () => {
    mockUseAuthStore.mockReturnValue({
      user: { id: 'u-2', name: '客服小王', roles: ['customer_service'], permissions: ['order:list'] },
    })
    mockGetOrderOperations.mockReset().mockResolvedValue(ok(OPERATIONS_UNPRICED))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-header')).toBeInTheDocument())
    expect(screen.queryByTestId('production-reprice-button')).not.toBeInTheDocument()
  })
})
