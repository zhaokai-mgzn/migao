// case_ids: PR-080
//
// PR-080（issue #5177）：**加急插队**（不进池 / 单派 / 批内拒绝文案）在智能派单上的可执行判据。
//
// 三条口径（冻结契约）：
//   ① 加急单**不进池** —— 整段 `urgentLines` 单独渲染，且**不出现在成批候选**里（不是成批候选）；
//   ② 加急插队 = **同一个端点 + 单订单 + `pooled:false`**（一个动作）；
//   ③ 加急单混进 `pooled:true` 的批 ⇒ **422 VALIDATION_ERROR（整批拒绝）**——
//      拒绝文案必须**看得见**（红色错误条），不能只靠一次转瞬即逝的 toast。
//   ④ issue #7968：**整单派工 ⇒ 整单逐行指派** —— 多套成品帘的加急 / 外发单，一次派单
//      ⇒ `/dispatch` 的 `batches` 带**该单全部行**（只带一行 = 其余各套不领料、快照无 batchNo）。
//   ⑤ issue #7974：**展示与动作都是订单级** —— 一张多套订单在逐单表里**只有一行、一个按钮**，
//      行内列出全部套的物料/米数（改前按套渲染 = 同一单号 N 行、N 个按钮，看起来像逐套派）。
//
// issue #7943（用户 2026-10-27 裁定）：加急与外发是**同一件事**（不进池、逐单立即派、共用同一个
// 承接方设置）⇒ 合并成**一张表**；且**成批合并区置顶**（主操作），「加急 / 外发」区在其后。
// 本文件的结构判据因此从「加急区在成批区之前」翻转为「成批区在加急 / 外发区之前」（改前必红）。
//
// §15.1：断言必须落在**用户可见结果**上 —— 所以「派单成功」这条断言的是
// **屏幕上出现加工单号**（`加工单号 JG-...`），不是「API 被调用过」。
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { toast } from 'sonner'

const mockGetBoard = vi.fn()
const mockPreview = vi.fn()
const mockDispatch = vi.fn()
const mockProcessors = vi.fn()

vi.mock('@/lib/api', () => ({
  poolBoardApi: {
    getBoard: (...a: unknown[]) => mockGetBoard(...a),
    preview: (...a: unknown[]) => mockPreview(...a),
    dispatch: (...a: unknown[]) => mockDispatch(...a),
    processors: (...a: unknown[]) => mockProcessors(...a),
  },
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn(), dismiss: vi.fn() },
}))

import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import ProductionPoolPage from '@/app/(dashboard)/production/pool/page'
import {
  batchCandidateOrderIds,
  batchGroups,
  mustSurfaceDispatchError,
} from '@/lib/pool-board'
import type { PoolBoard, PoolDispatchResult, PoolGroup, PoolLine, PoolPreview } from '@/types'

const ok = (data: unknown) => ({ data: { data } })

const line = (over: Partial<PoolLine>): PoolLine => ({
  orderId: 'o1',
  orderNo: 'MG-0001',
  itemId: 'i1',
  productId: 'p1',
  productName: '遮光布',
  skuCode: '米白/2.8m',
  requiredMeters: 18.5,
  waitingSince: '2026-09-20T08:00:00+08:00',
  waitHours: 30,
  overdue: false,
  isUrgent: false,
  requiredDeliveryDate: null,
  deliveryDaysLeft: null,
  ...over,
})

/** 加急插队：两行（不同订单）；成批区：一个物料组一行 —— 三个订单互不重叠 */
const URGENT_A = line({
  orderId: 'u1',
  orderNo: 'MG-URG-1',
  itemId: 'iu1',
  isUrgent: true,
  waitHours: 6,
  requiredDeliveryDate: '2026-09-28',
  deliveryDaysLeft: 1,
})
const URGENT_B = line({
  orderId: 'u2',
  orderNo: 'MG-URG-2',
  itemId: 'iu2',
  isUrgent: true,
  waitHours: 2,
  requiredDeliveryDate: null,
  deliveryDaysLeft: null,
})
const POOLED_A = line({ orderId: 'o1', orderNo: 'MG-POOL-1', itemId: 'io1' })
/** 外发单（V194，issue #7746 后续）：`isOutsourced` ⇒ 与加急同区、派单前**必须**选承接方 */
const OUT_A = line({
  orderId: 'x1',
  orderNo: 'MG-OUT-1',
  itemId: 'ix1',
  waitHours: 5,
  isOutsourced: true,
})

const board = (over: Partial<PoolBoard> = {}): PoolBoard => ({
  maxWaitHours: 24,
  poolingEnabled: false,
  orderCount: 1,
  lineCount: 1,
  overdueCount: 0,
  urgentCount: 2,
  warnings: [],
  urgentLines: [URGENT_A, URGENT_B],
  groups: [
    {
      // 🔴 issue #6523：`materialKey` 是机器键（不上屏），组标题渲染服务端 `materialLabel`
      materialKey: 'p1|米白/2.8m',
      materialLabel: '遮光布 × 米白/2.8m',
      productId: 'p1',
      skuCode: '米白/2.8m',
      orderCount: 1,
      requiredMeters: 18.5,
      lines: [POOLED_A],
    },
  ],
  ...over,
})

/**
 * 🔴 **散文主张 → 可执行夹具**（issue #5195，PR-080 `data_checks` 第 1/2 条）：
 *
 * > ①「加急单**不出现在任何** `groups[].lines`……**红证 = 让加急单照旧进池 ⇒ 该断言红**」
 * > ②「整批显式拒绝……**文案必须看得见**（不静默少派）」
 *
 * 这两条此前在本文件里**没有负向夹具**（`红证` 命中 = 0）⇒ 判别力只存在于措辞里。
 * 本 describe 用本仓既有范式（`tests/unit/lib/copy-no-markdown-emphasis.test.ts` 的正控/负控
 * + `tests/unit_ci_workflows/test_case_machine_fail_channel.py` 的 `TestInjectionRedProofs`）
 * 把它们落成**能单独变红**的注入式夹具：**同一个判据**分别跑真实实现与变异体。
 */
describe('🔴 红证夹具：「加急不进池」与「拒绝文案看得见」的注入式负控（issue #5195）', () => {
  /** 加急单的订单 id（来自本文件的真实看板夹具 `board()`） */
  const URGENT_IDS = ['u1', 'u2']

  /** **变异体**：让加急单照旧进池（把 `urgentLines` 并进第一个物料组）—— 单点「缺陷」形态 */
  const mergeUrgentIntoGroups = (b: PoolBoard): PoolBoard => ({
    ...b,
    groups: batchGroups(b).map((g: PoolGroup, i: number) =>
      i === 0 ? { ...g, lines: [...(g.lines ?? []), ...(b.urgentLines ?? [])] } : g
    ),
  })

  it('① 正控：变异体「加急单照旧进池」⇒ 成批候选里**当场**出现加急单号（该断言必红）', () => {
    const leaked = batchCandidateOrderIds(mergeUrgentIntoGroups(board()))
    expect(URGENT_IDS.filter((id) => leaked.includes(id))).toEqual(URGENT_IDS)
  })

  it('② 负控（对照组）：真实看板夹具下加急单**零进池** —— 红是变异体造成的，不是判据本来就红', () => {
    const candidates = batchCandidateOrderIds(board())
    expect(URGENT_IDS.filter((id) => candidates.includes(id))).toEqual([])
    // 自证非空：成批候选确实有内容（空集上「没有加急单」恒真 = 空断言）
    expect(candidates).toEqual(['o1'])
  })

  /** 被拒绝的文案（= 本文件第 3 条 DOM 判据里服务端回的那句） */
  const REJECTION = '加急订单不能混入池化批次，请单独派单（加急插队）'

  /** **判据本体**（正控与负控跑同一份）：被拒绝 ⇒ 必须有可见文案，否则 = 静默少派 */
  const silentViolations = (surfaces: (m: string) => boolean, message: string) =>
    surfaces(message) ? [] : ['被拒绝却没有可见文案（静默少派）']

  it('③ 正控：把失败面静默吞掉（`() => false`）⇒ 「拒绝文案看得见」判据当场报出静默违规', () => {
    expect(silentViolations(() => false, REJECTION)).toEqual(['被拒绝却没有可见文案（静默少派）'])
  })

  it('④ 负控（对照组）：真实口径下零静默违规，且空白文案**不算**上屏', () => {
    expect(silentViolations(mustSurfaceDispatchError, REJECTION)).toEqual([])
    expect(silentViolations(mustSurfaceDispatchError, '   ')).toEqual([
      '被拒绝却没有 visible 文案（静默少派）',
    ].map(() => '被拒绝却没有可见文案（静默少派）'))
  })

  it('⑤ 接线：前端红证必须与页面**同源**（页面真的用这些口径）', () => {
    const src = readFileSync(
      join(process.cwd(), 'src/app/(dashboard)/production/pool/page.tsx'),
      'utf-8'
    )
    const problems: string[] = []
    if (!/^\s*import\s+\{[^}]*batchGroups[^}]*\}\s+from\s+'@\/lib\/pool-board'/m.test(src)) {
      problems.push('页面没有 import batchGroups ⇒ 「成批候选」口径与红证脱钩')
    }
    if (!src.includes('batchGroups(board)')) {
      problems.push('页面没有用 batchGroups(board) 取成批候选（自己又写了一份 board?.groups ?? []）')
    }
    if (!src.includes('mustSurfaceDispatchError(dispatchError)')) {
      problems.push('失败红条的渲染条件没有走 mustSurfaceDispatchError ⇒ 「文案看得见」判据与页面脱钩')
    }
    // 🔴 类级锁（issue #7968）：订单级派单只能从「整单行」口径取批次指派 ——
    // 退回 `buildPoolRequest([line])`（只带被点的那一行）⇒ 本项当场红，不用等真库看见另一套没领料。
    const dispatchSingleBody = src.slice(
      src.indexOf('const dispatchSingle'),
      src.indexOf('const dispatchBatch'),
    )
    if (
      !src.includes('singleDispatchLinesOfOrder') ||
      !dispatchSingleBody.includes('singleDispatchLinesOfOrder(board, order.orderId)')
    ) {
      problems.push('「立即派单」没有按整单行取批次指派（singleDispatchLinesOfOrder）⇒ 多套成品帘只有一套领料')
    }
    // 🔴 类级锁（issue #7974）：逐单区必须按**订单**渲染 —— 退回「`singleDispatchLines.map` 一套一行」即红
    if (!src.includes('singleDispatchOrders(board)') || !src.includes('singleOrders.map')) {
      problems.push('逐单区没有按订单归并渲染（singleDispatchOrders）⇒ 多套订单又变成一套一行/一个按钮')
    }
    expect(problems).toEqual([])
  })
})

describe('智能派单 · 加急插队区（PR-080）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetBoard.mockResolvedValue(ok(board()))
    mockProcessors.mockResolvedValue(ok([{ id: 'sup-1', name: '朝阳加工厂' }]))
    // 🔴 显式注解成 `PoolPreview`：形状写错（例如把 `perOrderPlannedMeters` 写成 map）⇒ **tsc 红**
    const urgentPreview: PoolPreview = {
        orderCount: 1,
        assignmentRule: 'best-fit',
        formulaMeters: 18.5,
        pooledPlannedMeters: 18.5,
        savedMeters: 0,
        // 🔴 `perOrderPlannedMeters` 是**一个数**（逐单派应领**合计**），不是 orderId→米数 的映射
        perOrderPlannedMeters: 18.5,
        poolingGainMeters: 0,
    }
    mockPreview.mockResolvedValue(ok(urgentPreview))
  })

  it('外发入口（承接方 + 回厂日）在**加急 / 外发区**内、逐单表格之前，不在成批区（issue #7746 / #7943）', async () => {
    const { container } = render(<ProductionPoolPage />)
    await waitFor(() => expect(screen.getByTestId('pool-urgent-table')).toBeInTheDocument())

    // ① 结构性：与「立即派单」同区 —— 排在加急表格**之前**（生造 DOM 顺序断言，不靠视觉）
    const html = container.innerHTML
    const consignee = html.indexOf('data-testid="pool-consignee"')
    expect(consignee, '外发入口不见了').toBeGreaterThan(-1)
    expect(consignee, '外发入口必须排在逐单表格之前（同区、表格上方）').toBeLessThan(
      html.indexOf('pool-urgent-table'),
    )

    // ② 反向：不在成批区里（改前它在 `pool-groups-section` 内 ⇒ 本断言红）
    const groupsSection = screen.getByTestId('pool-groups-section')
    expect(within(groupsSection).queryByTestId('pool-consignee')).toBeNull()

    // ③ 标题必须同时覆盖两件事（退回「只有加急」= 红）
    expect(screen.getByText('加急 / 外发订单（不参与合并，整单立即派）')).toBeInTheDocument()
    // ④ 合并成一个区：旧的「外发订单」独立卡**取不到**（issue #7943）
    expect(screen.queryByTestId('pool-outsourced-section')).toBeNull()
  })

  it('承接方下拉为空 ⇒ 给「去供应商新建」入口；有加工厂档案时不摆（issue #7955）', async () => {
    // ① 没有任何加工厂：下拉只有「本厂自做」= 死路（用户当场问「承接方需要在哪添加」）
    //    ⇒ 必须给出口（加工厂档案 = 供应商页里「类型 = 加工厂（外发作业）」）
    // ⚠️ 必须是 `mockResolvedValueOnce`：默认实现（beforeEach）= 朝阳加工厂，改默认实现会让 ② 也拿到空表
    mockProcessors.mockResolvedValueOnce(ok([]))
    const first = render(<ProductionPoolPage />)
    const link = await screen.findByTestId('pool-processor-empty-link')
    expect(link).toHaveAttribute('href', '/suppliers')
    expect(link).toHaveTextContent('去供应商新建')
    first.unmount()

    // ② 负控：有档案（默认夹具 = 朝阳加工厂）⇒ 取不到该入口（不是「永远挂着」）
    render(<ProductionPoolPage />)
    const select = await screen.findByLabelText('承接方')
    await waitFor(() => expect(within(select).getByText('朝阳加工厂')).toBeInTheDocument())
    expect(screen.queryByTestId('pool-processor-empty-link')).toBeNull()
  })

  it('**成批区置顶**、「加急 / 外发」区在其后（issue #7943），且加急单不出现在成批候选里（不进池）', async () => {
    const { container } = render(<ProductionPoolPage />)
    await waitFor(() => expect(screen.getByTestId('pool-urgent-table')).toBeInTheDocument())

    // ① 结构：成批合并（主操作）是页面**第一个**内容区块，「加急 / 外发」在其后
    //    （改前是「加急区在前」⇒ 本断言必红；两段都在，不是把另一段渲染没了来「通过」）
    const html = container.innerHTML
    expect(html.indexOf('pool-groups-section')).toBeGreaterThan(-1)
    expect(html.indexOf('pool-urgent-section')).toBeGreaterThan(-1)
    expect(
      html.indexOf('pool-groups-section'),
      '成批合并区必须排在「加急 / 外发」区之前（用户 2026-10-27 裁定：主操作置顶）',
    ).toBeLessThan(html.indexOf('pool-urgent-section'))

    // ② 加急单**不进池**：成批区里没有它们（有的话就是「当成成批候选」= 会给商家一个必然 422 的勾选）
    const groupsSection = screen.getByTestId('pool-groups-section')
    expect(within(groupsSection).queryByText('MG-URG-1')).toBeNull()
    expect(within(groupsSection).queryByText('MG-URG-2')).toBeNull()
    // 池内那一单照常在成批区（反向断言：不能把成批区整个渲染没了来「通过」上面两条）
    expect(within(groupsSection).getByText('MG-POOL-1')).toBeInTheDocument()

    // ③ 池视图列齐全：单号 / 成品帘（套数 + 物料 + 米数）/ 等待时长 / 加急标记 / 到货日
    const urgentRow = screen.getByTestId('pool-line-u1')
    expect(urgentRow).toHaveTextContent('MG-URG-1')
    expect(urgentRow).toHaveTextContent('遮光布')
    expect(urgentRow).toHaveTextContent('18.50')
    expect(urgentRow).toHaveTextContent('6 小时')
    expect(urgentRow).toHaveTextContent('加急')
    expect(urgentRow).toHaveTextContent('2026-09-28')
    // 未指定到货日 ⇒ 「未指定」（不猜一个日期）
    expect(screen.getByTestId('pool-line-u2')).toHaveTextContent('未指定')
  })

  it('加急与外发**合并在同一张表**（一张表 / 一个空态），旧的外发独立卡不再存在（issue #7943）', async () => {
    mockGetBoard.mockResolvedValue(
      ok(board({ outsourcedLines: [OUT_A], outsourcedCount: 1 })),
    )
    const { container } = render(<ProductionPoolPage />)

    const table = await screen.findByTestId('pool-urgent-table')
    // ① 同表：加急单与外发单都在**这一张**表里（不是两张卡各一张表）
    expect(within(table).getByText('MG-URG-1')).toBeInTheDocument()
    expect(within(table).getByText('MG-OUT-1')).toBeInTheDocument()
    // ② 顺序 = 两个服务端数组的拼接序（加急在前、外发在后）—— 前端**不重排**
    const html = container.innerHTML
    expect(html.indexOf('pool-line-u1')).toBeLessThan(html.indexOf('pool-outsourced-line-x1'))
    // ③ 外发行带「外发」标记（它是「必须先选承接方」的原因，不能靠空白让商家猜）
    expect(screen.getByTestId('pool-outsourced-line-x1')).toHaveTextContent('外发')
    // ④ 一张表 ⇒ 一个表头：「操作」列只出现一次
    expect(within(table).getAllByText('操作')).toHaveLength(1)
    // ⑤ 旧的外发独立卡不再渲染（合并 = 移除外发那一块）
    expect(screen.queryByTestId('pool-outsourced-section')).toBeNull()
  })

  it('加急与外发**都为空** ⇒ 只渲染**一个**空态（旧形态是两张卡两段空态）', async () => {
    mockGetBoard.mockResolvedValue(
      ok(board({ urgentLines: [], urgentCount: 0, outsourcedLines: [], outsourcedCount: 0 })),
    )
    render(<ProductionPoolPage />)

    await waitFor(() =>
      expect(screen.getByText('当前没有加急或外发待派订单')).toBeInTheDocument(),
    )
    expect(screen.getAllByText('当前没有加急或外发待派订单')).toHaveLength(1)
    // 旧的两段空态文案都要消失（否则就是「合并了标题、没合并空态」）
    expect(screen.queryByText('当前没有加急待派订单')).toBeNull()
    expect(screen.queryByText('当前没有待派的外发订单')).toBeNull()
    // 空态代替表格（不是空表 + 空态并排）
    expect(screen.queryByTestId('pool-urgent-table')).toBeNull()
  })

  it('点「加急插队派单」⇒ 单订单 + pooled:false，且**屏幕上出现加工单号**（结果可见）', async () => {
    // 🔴 显式注解成 `PoolDispatchResult[]`：形状写错 ⇒ **tsc 红**（同 batch 测试的注释）
    const jumpResult: PoolDispatchResult[] = [
        {
          orderRef: 'u1',
          processingOrderNo: 'JG-20260925-0007',
          success: true,
          message: null,
          code: null,
          suggestion: null,
        },
    ]
    mockDispatch.mockResolvedValue(ok(jumpResult))
    // 派单成功后看板刷新：加急区空掉（那一单已经派走了）
    mockGetBoard
      .mockResolvedValueOnce(ok(board()))
      .mockResolvedValue(ok(board({ urgentLines: [URGENT_B], urgentCount: 1 })))

    render(<ProductionPoolPage />)
    await waitFor(() => expect(screen.getByTestId('pool-dispatch-single-u1')).toBeInTheDocument())

    fireEvent.click(screen.getByTestId('pool-dispatch-single-u1'))

    await waitFor(() => expect(mockDispatch).toHaveBeenCalledTimes(1))
    // ② 加急插队 = 同一个端点 + **单订单** + **pooled:false**（一个动作）
    // issue #6408：加急单也**逐行带指派**（同一个动作、同一个端点）—— 否则这一单同样一张料都不领
    expect(mockDispatch).toHaveBeenCalledWith({
      orderIds: ['u1'],
      batches: [{ orderId: 'u1', itemId: 'iu1' }],
      assignmentRule: 'fifo',
      pooled: false,
    })

    // ① §15.1：断言**用户可见结果** —— 加工单号真的出现在界面上（不是「API 被调用过」）
    await waitFor(() => {
      expect(screen.getByTestId('pool-dispatch-results')).toHaveTextContent('JG-20260925-0007')
    })
    expect(screen.getByTestId('pool-dispatch-results')).toHaveTextContent('MG-URG-1')
    // toast 里也带加工单号（不是只说一句「成功」）
    expect(toast.success).toHaveBeenCalledWith(
      expect.stringContaining('JG-20260925-0007'),
    )
    // 看板已刷新：派走的那一单从加急区消失（**用户可见**，而不是只 toast）
    await waitFor(() => expect(screen.queryByTestId('pool-line-u1')).toBeNull())
    expect(screen.getByTestId('pool-line-u2')).toBeInTheDocument()
  })

  it('加急单混进成批批 ⇒ 422 拒绝文案在页面上**看得见**（整批拒绝，不静默少派）', async () => {
    mockDispatch.mockRejectedValueOnce(
      new Error('加急订单不能混入池化批次，请单独派单（加急插队）'),
    )

    render(<ProductionPoolPage />)
    // 把池内那一单勾上 → 成批派单
    const checkbox = await screen.findByLabelText('选择订单 MG-POOL-1')
    fireEvent.click(checkbox)
    fireEvent.click(screen.getByTestId('pool-dispatch-batch'))

    await waitFor(() => expect(mockDispatch).toHaveBeenCalledTimes(1))
    expect(mockDispatch).toHaveBeenCalledWith({
      orderIds: ['o1'],
      batches: [{ orderId: 'o1', itemId: 'io1' }],
      assignmentRule: 'fifo',
      pooled: true,
    })

    await waitFor(() => {
      expect(screen.getByTestId('pool-dispatch-error')).toHaveTextContent(
        '加急订单不能混入池化批次，请单独派单（加急插队）',
      )
    })
    // **整批拒绝**：不得出现任何「部分成功」的结果行（静默少派就是这条要防的形态）
    expect(screen.queryByTestId('pool-dispatch-results')).toBeNull()
  })

  it('#6588 顶部不再有「合并派单开关」徽标（只读状态不当控件摆），状态条读数照旧', async () => {
    render(<ProductionPoolPage />)
    await waitFor(() => expect(screen.getByTestId('pool-status-max-wait')).toBeInTheDocument())
    expect(screen.queryByTestId('pool-status-pooling')).toBeNull()
    expect(screen.getByTestId('pool-status-max-wait')).toHaveTextContent('24')
    expect(screen.getByTestId('pool-status-order-count')).toBeInTheDocument()
  })
})

// ============================================================ 外发区（V194，issue #7746 后续）

describe('外发区：订单标记「外发加工」⇒ 不进池、逐单立即派、必须先选承接方', () => {
  const boardWithOutsourced = (): PoolBoard =>
    board({ outsourcedLines: [OUT_A], outsourcedCount: 1 })

  it('外发单与加急**同区**（不进成批候选）；未选承接方时「立即派单」不可用', async () => {
    mockGetBoard.mockResolvedValue(ok(boardWithOutsourced()))
    render(<ProductionPoolPage />)

    const section = await screen.findByTestId('pool-urgent-section')
    expect(within(section).getByText('MG-OUT-1')).toBeInTheDocument()
    const groups = screen.getByTestId('pool-groups-section')
    expect(within(groups).queryByText('MG-OUT-1')).toBeNull()
    expect(screen.getByTestId('pool-outsourced-dispatch-x1')).toBeDisabled()
  })

  it('选了承接方 ⇒ 立即派单带 processorSupplierId（单订单 + pooled:false），结果行显示**单号**', async () => {
    mockGetBoard.mockResolvedValue(ok(boardWithOutsourced()))
    mockDispatch.mockResolvedValue(
      ok([{ orderRef: 'x1', success: true, processingOrderNo: 'JG-1', message: null, code: null, suggestion: null }]),
    )
    render(<ProductionPoolPage />)
    await screen.findByTestId('pool-urgent-section')

    fireEvent.change(screen.getByLabelText('承接方'), { target: { value: 'sup-1' } })
    const btn = screen.getByTestId('pool-outsourced-dispatch-x1')
    await waitFor(() => expect(btn).not.toBeDisabled())
    fireEvent.click(btn)

    await waitFor(() => expect(mockDispatch).toHaveBeenCalled())
    const body = mockDispatch.mock.calls[0][0] as Record<string, unknown>
    expect(body.orderIds).toEqual(['x1'])
    expect(body.pooled).toBe(false)
    expect(body.processorSupplierId).toBe('sup-1')

    // 结果可见（§15.1）：结果卡上显示的是**单号**（不是订单 id）。
    // 🔴 累积映射必须覆盖外发行（`singleDispatchLines`）—— 改前它只累积 urgentLines ⇒ 这里渲染成 `x1`。
    await waitFor(() =>
      expect(screen.getByTestId('pool-dispatch-results')).toHaveTextContent('MG-OUT-1'),
    )
    expect(screen.getByTestId('pool-dispatch-results')).toHaveTextContent('JG-1')
  })
})

// ============================================================ 整单展示 / 整单派单（issue #7974 + #7968）

/**
 * 用户 2026-10-28 两次现场（逐字）：
 * > 一个加急订单有多套成品帘时，点击某个商品行直接派工会整单派工，但是只有被选中的那套成品帘
 * > 指定了批次号，应该要整单都指派
 * > 既然是整单派单，那应该改成整单派单的交互形式，现在是根据订单套展示和派单的
 *
 * 口径：
 * ① **展示 = 订单**：一张多套订单在逐单表里**只有一行**，行内列出该单全部套的物料与米数；
 * ② **动作 = 订单**：该行**只有一个**「立即派单」按钮，一次派整单；
 * ③ **指派 = 整单逐行**：`batches` 带该单全部行（issue #7968），不是只有某一行。
 *
 * 红证：
 * - 退回按套渲染（N 行、N 个按钮）⇒「恰好一行 / 恰好一个按钮」断言当场红；
 * - 退回只带一行 ⇒ `batches` 断言当场红。
 */
describe('多套成品帘的整单立即派：一张订单一行一个按钮，一次覆盖全部行（issue #7974 / #7968）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetBoard.mockResolvedValue(ok(board()))
    mockProcessors.mockResolvedValue(ok([{ id: 'sup-1', name: '朝阳加工厂' }]))
  })

  /** 一张加急单 = 两套成品帘（同一 orderId、两个 itemId；米数刻意不同，证明两套都被渲染） */
  const MULTI_CLOTH = line({
    orderId: 'm1',
    orderNo: 'MG-URG-MULTI',
    itemId: 'im1',
    productName: '遮光布',
    requiredMeters: 18.5,
    isUrgent: true,
  })
  const MULTI_SHEER = line({
    orderId: 'm1',
    orderNo: 'MG-URG-MULTI',
    itemId: 'im2',
    productName: '素纱',
    skuCode: '米白/2.0m',
    requiredMeters: 12,
    isUrgent: true,
  })

  it('多套加急单 ⇒ **恰好一行、恰好一个按钮**；行内两套物料/米数都在；点击后 batches 两行', async () => {
    mockGetBoard.mockResolvedValue(
      ok(board({ urgentLines: [MULTI_CLOTH, MULTI_SHEER], urgentCount: 1 })),
    )
    mockDispatch.mockResolvedValue(
      ok([
        {
          orderRef: 'm1',
          processingOrderNo: 'JG-20261028-0001',
          success: true,
          message: null,
          code: null,
          suggestion: null,
        },
      ]),
    )

    render(<ProductionPoolPage />)
    await waitFor(() => expect(screen.getByTestId('pool-urgent-table')).toBeInTheDocument())

    // ① 订单级展示：同一单**只出现一行**（改前按套渲染 = 两行 ⇒ 本断言红）
    const rows = screen.getAllByTestId('pool-line-m1')
    expect(rows).toHaveLength(1)
    const row = rows[0]

    // ② 行内 = 该单全部套（信息不丢：两套的商品 / 颜色门幅 / 米数都在）
    expect(row).toHaveTextContent('2 套成品帘')
    expect(row).toHaveTextContent('遮光布')
    expect(row).toHaveTextContent('米白/2.8m')
    expect(row).toHaveTextContent('18.50 米')
    expect(row).toHaveTextContent('素纱')
    expect(row).toHaveTextContent('米白/2.0m')
    expect(row).toHaveTextContent('12.00 米')

    // ③ 一个订单一个动作：行内**恰好一个**「立即派单」按钮（改前两套 = 两个按钮 ⇒ 本断言红）
    const buttons = within(row).getAllByRole('button', { name: '立即派单' })
    expect(buttons).toHaveLength(1)
    fireEvent.click(buttons[0])

    await waitFor(() => expect(mockDispatch).toHaveBeenCalledTimes(1))
    expect(mockDispatch).toHaveBeenCalledWith({
      orderIds: ['m1'],
      batches: [
        { orderId: 'm1', itemId: 'im1' },
        { orderId: 'm1', itemId: 'im2' },
      ],
      assignmentRule: 'fifo',
      pooled: false,
    })
  })

  it('多套外发单同样一行一个按钮；未选承接方时不可用，选后一次派整单', async () => {
    const out1 = line({
      orderId: 'mx',
      orderNo: 'MG-OUT-MULTI',
      itemId: 'xm1',
      requiredMeters: 18.5,
      isOutsourced: true,
    })
    const out2 = line({
      orderId: 'mx',
      orderNo: 'MG-OUT-MULTI',
      itemId: 'xm2',
      productName: '素纱',
      skuCode: '米白/2.0m',
      requiredMeters: 12,
      isOutsourced: true,
    })
    mockGetBoard.mockResolvedValue(
      ok(board({ outsourcedLines: [out1, out2], outsourcedCount: 1 })),
    )
    mockDispatch.mockResolvedValue(
      ok([
        {
          orderRef: 'mx',
          processingOrderNo: 'JG-20261028-0002',
          success: true,
          message: null,
          code: null,
          suggestion: null,
        },
      ]),
    )

    render(<ProductionPoolPage />)
    await screen.findByTestId('pool-urgent-section')

    // 一张外发单同样**只有一行一个按钮**
    const rows = screen.getAllByTestId('pool-outsourced-line-mx')
    expect(rows).toHaveLength(1)
    const row = rows[0]
    expect(row).toHaveTextContent('2 套成品帘')
    expect(row).toHaveTextContent('素纱')
    const button = within(row).getByRole('button', { name: '立即派单' })
    expect(button).toBeDisabled()

    fireEvent.change(screen.getByLabelText('承接方'), { target: { value: 'sup-1' } })
    await waitFor(() => expect(button).not.toBeDisabled())
    fireEvent.click(button)

    await waitFor(() => expect(mockDispatch).toHaveBeenCalledTimes(1))
    const body = mockDispatch.mock.calls[0][0] as Record<string, unknown>
    expect(body.batches).toEqual([
      { orderId: 'mx', itemId: 'xm1' },
      { orderId: 'mx', itemId: 'xm2' },
    ])
    expect(body.orderIds).toEqual(['mx'])
    expect(body.pooled).toBe(false)
  })
})
