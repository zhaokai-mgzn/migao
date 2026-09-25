// case_ids: PR-080
//
// PR-080（issue #5177）：**加急插队**（不进池 / 单派 / 批内拒绝文案）在智能派单上的可执行判据。
//
// 三条口径（冻结契约）：
//   ① 加急单**不进池** —— 整段 `urgentLines` 单独渲染，且**不出现在成批候选**里（不是成批候选）；
//   ② 加急插队 = **同一个端点 + 单订单 + `pooled:false`**（一个动作）；
//   ③ 加急单混进 `pooled:true` 的批 ⇒ **422 VALIDATION_ERROR（整批拒绝）**——
//      拒绝文案必须**看得见**（红色错误条），不能只靠一次转瞬即逝的 toast。
//
// §15.1：断言必须落在**用户可见结果**上 —— 所以「派单成功」这条断言的是
// **屏幕上出现加工单号**（`加工单号 JG-...`），不是「API 被调用过」。
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { toast } from 'sonner'

const mockGetBoard = vi.fn()
const mockPreview = vi.fn()
const mockDispatch = vi.fn()

vi.mock('@/lib/api', () => ({
  poolBoardApi: {
    getBoard: (...a: unknown[]) => mockGetBoard(...a),
    preview: (...a: unknown[]) => mockPreview(...a),
    dispatch: (...a: unknown[]) => mockDispatch(...a),
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
      materialKey: '遮光布 / 米白 / 2.8m',
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

  it('⑤ 接线：前端两条红证必须与页面**同源**（页面真的用这三个口径）', () => {
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
    expect(problems).toEqual([])
  })
})

describe('智能派单 · 加急插队区（PR-080）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetBoard.mockResolvedValue(ok(board()))
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

  it('加急插队区**结构性**排在成批区之前，且加急单不出现在成批候选里（不进池）', async () => {
    const { container } = render(<ProductionPoolPage />)
    await waitFor(() => expect(screen.getByTestId('pool-urgent-table')).toBeInTheDocument())

    // ① 结构性优先：整段 urgentLines 渲染在 groups 之前（**不是前端排序的结果**）
    const html = container.innerHTML
    expect(html.indexOf('pool-urgent-table')).toBeGreaterThan(-1)
    expect(html.indexOf('pool-urgent-table')).toBeLessThan(html.indexOf('pool-groups-section'))

    // ② 加急单**不进池**：成批区里没有它们（有的话就是「当成成批候选」= 会给商家一个必然 422 的勾选）
    const groupsSection = screen.getByTestId('pool-groups-section')
    expect(within(groupsSection).queryByText('MG-URG-1')).toBeNull()
    expect(within(groupsSection).queryByText('MG-URG-2')).toBeNull()
    // 池内那一单照常在成批区（反向断言：不能把成批区整个渲染没了来「通过」上面两条）
    expect(within(groupsSection).getByText('MG-POOL-1')).toBeInTheDocument()

    // ③ 池视图列齐全：单号 / 物料 / 需求米数 / 等待时长 / 加急标记 / 到货日
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
    expect(mockDispatch).toHaveBeenCalledWith({
      orderIds: ['u1'],
      batches: [],
      assignmentRule: null,
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
      batches: [],
      assignmentRule: null,
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

  it('顶部必须看得见「池化开关未开启」（缺省关，不是隐形状态）', async () => {
    render(<ProductionPoolPage />)
    await waitFor(() => expect(screen.getByTestId('pool-status-pooling')).toBeInTheDocument())
    expect(screen.getByTestId('pool-status-pooling')).toHaveTextContent('未开启')
    expect(screen.getByTestId('pool-status-max-wait')).toHaveTextContent('24')
  })
})
