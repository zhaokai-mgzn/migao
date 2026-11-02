// case_ids: PR-081
//
// issue #7091（AI 裁定 A）：智能派单列表里**库存不足的行**必须在列表上预先看得出来 ——
// 服务端读面下发只读字段 `stockSatisfiable`，前端据此**禁用勾选** + 行内一句「库存不足，先入库」。
//
// 病灶（现场逐字）：14 单长得一模一样，点完「一键合并派单」才报「库存里没有能裁出它的批次」，
// 且**一次只报一行** ⇒ 「全选 → 合并派单」必失败，反复发生。
//
// 本文件的可执行判据：
//   ① 缺料行：复选框 `disabled`，且**该行内**有「库存不足，先入库」
//      （§31 P1：做成**行内标记**，不是顶部横幅 —— 它随行数增长，常驻面不得随条数长高）
//   ② 同一张单的**另一料组行**也禁用（勾选粒度 = **订单** ⇒ 只要一行缺料整单就派不出去）
//   ③ 可派行仍可勾；「全选」只勾得住可派的单（缺料单不得被全选带进「一键合并派单」）
//   ④ 判别力（负控）：把夹具的 `stockSatisfiable` 全改 true（或整个字段缺席 = 老服务端）
//      ⇒ 复选框全可用、候选集含该单 ⇒ 上面那些断言不是恒真。
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'

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

import ProductionPoolPage from '@/app/(dashboard)/production/pool/page'
import { batchCandidateOrderIds } from '@/lib/pool-board'
import type { PoolBoard, PoolGroup, PoolLine } from '@/types'

const ok = (data: unknown) => ({ data: { data } })

const line = (over: Partial<PoolLine>): PoolLine => ({
  orderId: 'o1',
  orderNo: 'MG-0001',
  itemId: 'i1',
  productId: 'p1',
  productName: '遮光布',
  skuCode: '米白/2.8m',
  requiredMeters: 2,
  waitingSince: '2026-09-20T08:00:00+08:00',
  waitHours: 5,
  overdue: false,
  isUrgent: false,
  requiredDeliveryDate: null,
  deliveryDaysLeft: null,
  stockSatisfiable: true,
  ...over,
})

/** 布组：oA 有库存；oB **缺料**（现场那一行） */
const CLOTH: PoolGroup = {
  materialKey: 'p1|米白/2.8m',
  materialLabel: '遮光布 × 米白/2.8m',
  productId: 'p1',
  skuCode: '米白/2.8m',
  orderCount: 2,
  requiredMeters: 4,
  lines: [
    line({ orderId: 'oA', orderNo: 'MG-0001', itemId: 'iA' }),
    line({ orderId: 'oB', orderNo: 'MG-0002', itemId: 'iB1', stockSatisfiable: false }),
  ],
}

/** 纱组：同一张 oB 的**另一行**（这一行自己有库存）；oB 缺料的是布那行 ⇒ 整单仍派不出去 */
const YARN: PoolGroup = {
  materialKey: 'p1|白/1.4m',
  materialLabel: '遮光布 × 白/1.4m',
  productId: 'p1',
  skuCode: '白/1.4m',
  orderCount: 2,
  requiredMeters: 4,
  lines: [
    line({ orderId: 'oB', orderNo: 'MG-0002', itemId: 'iB2', skuCode: '白/1.4m' }),
    line({ orderId: 'oC', orderNo: 'MG-0003', itemId: 'iC', skuCode: '白/1.4m' }),
  ],
}

const board = (groups: PoolGroup[] = [CLOTH, YARN]): PoolBoard => ({
  maxWaitHours: 24,
  poolingEnabled: true,
  orderCount: 3,
  lineCount: 4,
  overdueCount: 0,
  urgentCount: 0,
  warnings: [],
  urgentLines: [],
  groups,
})

const PREVIEW = {
  orderCount: 2,
  assignmentRule: 'fifo',
  formulaMeters: 4,
  pooledPlannedMeters: 4,
  savedMeters: 0,
  perOrderPlannedMeters: 4,
  poolingGainMeters: 0,
}

describe('#7091 智能派单 · 缺料行的不可勾选 + 行内提示', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetBoard.mockResolvedValue(ok(board()))
    mockPreview.mockResolvedValue(ok(PREVIEW))
    mockDispatch.mockResolvedValue(ok([]))
  })

  it('① 缺料行：复选框 disabled + **行内**「库存不足，先入库」；同料组的可派行不受影响', async () => {
    render(<ProductionPoolPage />)

    const cloth = await screen.findByTestId('pool-group-0')
    const shortRow = within(cloth).getByTestId('pool-line-oB')
    expect(within(shortRow).getByRole('checkbox')).toBeDisabled()
    // 提示在**这一行里**（§31 P1：行内标记；不是顶部横幅 / 不是整屏告警块）
    expect(within(shortRow).getByText('库存不足，先入库')).toBeInTheDocument()
    expect(within(shortRow).getByTestId('pool-line-stock-hint-oB')).toBeInTheDocument()

    const okRow = within(cloth).getByTestId('pool-line-oA')
    expect(within(okRow).getByRole('checkbox')).not.toBeDisabled()
    expect(within(okRow).queryByText('库存不足，先入库')).toBeNull()
    // 全屏只有**这一处**提示（缺料的事实只由缺料行承载，不重复念）
    expect(screen.getAllByText('库存不足，先入库')).toHaveLength(1)
  })

  it('② 同一张单的另一料组行也禁用（勾选粒度 = 订单）；提示只落在**自己缺料**的那一行', async () => {
    render(<ProductionPoolPage />)

    const yarn = await screen.findByTestId('pool-group-1')
    const sibling = within(yarn).getByTestId('pool-line-oB')
    expect(
      within(sibling).getByRole('checkbox'),
      '一单跨两个料组：布缺料 ⇒ 这张单整单派不出去 ⇒ 纱那行同样不可勾',
    ).toBeDisabled()
    expect(
      within(sibling).queryByText('库存不足，先入库'),
      '纱这一行自己有库存 ⇒ 不在这一行说它缺料（事实归缺料行）',
    ).toBeNull()
  })

  it('③ 「全选」跳过缺料单：只勾住可派单，派单入参里没有那张注定被拒的单', async () => {
    render(<ProductionPoolPage />)
    await screen.findByTestId('pool-group-0')

    const selectAll = screen.getByTestId('pool-select-all')
    expect(selectAll).toHaveTextContent('全选 2 单') // oA + oC（oB 缺料、去重后仍是 1 单）
    fireEvent.click(selectAll)

    await waitFor(() => expect(screen.getByTestId('pool-dispatch-batch')).not.toBeDisabled())
    fireEvent.click(screen.getByTestId('pool-dispatch-batch'))

    await waitFor(() => expect(mockDispatch).toHaveBeenCalledTimes(1))
    const request = mockDispatch.mock.calls[0][0] as { orderIds: string[]; batches: { orderId: string }[] }
    expect(request.orderIds).toEqual(['oA', 'oC'])
    expect(request.orderIds).not.toContain('oB')
  })

  it('④ 判别力（负控）：库存字段全为 true / 整个缺席 ⇒ 复选框全可用、候选集含该单（上面不是恒真断言）', async () => {
    // 负控一：服务端明确说都够
    const allEnough = board([
      { ...CLOTH, lines: CLOTH.lines.map((l) => ({ ...l, stockSatisfiable: true })) },
      YARN,
    ])
    expect(batchCandidateOrderIds(allEnough)).toEqual(['oA', 'oB', 'oC'])

    // 负控二：老服务端 / 桩数据不带队字段 ⇒ 不可判定 ⇒ 按可派处理（不制造假阻塞）
    const legacy = board([
      { ...CLOTH, lines: CLOTH.lines.map(({ stockSatisfiable: _drop, ...rest }) => rest as PoolLine) },
      YARN,
    ])
    expect(batchCandidateOrderIds(legacy)).toEqual(['oA', 'oB', 'oC'])

    mockGetBoard.mockResolvedValue(ok(allEnough))
    render(<ProductionPoolPage />)
    await screen.findByTestId('pool-group-0')
    const cloth = screen.getByTestId('pool-group-0')
    expect(within(cloth).getByTestId('pool-line-oB').querySelector('input[type="checkbox"]')).not.toBeDisabled()
    expect(screen.queryByText('库存不足，先入库')).toBeNull()
    expect(screen.getByTestId('pool-select-all')).toHaveTextContent('全选 3 单')
  })
})
