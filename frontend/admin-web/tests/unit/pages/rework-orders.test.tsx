// case_ids: RWK-001
import { describe, expect, it, beforeEach, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import ReworkOrdersPage, { actionsFor, isOpen } from '@/app/(dashboard)/rework-orders/page'

/**
 * 返工单页面（issue #7377，P1-5 质量闭环的商家面）。
 *
 * 守住三件事（都与后端判据一一对应）：
 * 1. **状态机唯一**：动作按钮只按状态给（待开工只有「开工/取消」，返工中只有「完工/取消」，
 *    已闭环没有动作）—— 出现「已闭环还能点完工」就是验收里那条「已闭环但返工单还在做」；
 * 2. **本页不产生金额**：返工成本走返工报工，页面写口径说明而**不写 ¥0.00**；
 * 3. **服务端拒绝原话上屏**：已闭环/已驳回的售后单开单、重复开单都是服务端拒的，不许吞成「操作失败」。
 */
const reworkOrderApi = vi.hoisted(() => ({
  list: vi.fn(),
  detail: vi.fn(),
  create: vi.fn(),
  start: vi.fn(),
  complete: vi.fn(),
  cancel: vi.fn(),
}))

vi.mock('@/lib/api', () => ({ reworkOrderApi }))
vi.mock('@/lib/permission', () => ({
  usePermission: () => ({ has: () => true, permissions: [], isAdmin: true }),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const wrap = <T,>(data: T) => Promise.resolve({ data: { success: true, data } })

const DRAFT = {
  id: 'rw1',
  reworkNo: 'FG202610230001',
  source: 'after_sales' as const,
  afterSalesTicketId: 'SH-20261023-0001',
  orderId: 'o1',
  orderNo: 'SO-20261023-0001',
  processingOrderId: null,
  processingOrderNo: null,
  operationName: null,
  qty: null,
  workerName: null,
  status: 'draft' as const,
  reason: '帘头褶皱不齐',
  createdByName: '王小美',
  startedAt: null,
  completedAt: null,
}

const DOING = { ...DRAFT, id: 'rw2', reworkNo: 'FG202610230002', status: 'in_progress' as const, startedAt: '2026-10-23T09:10:00+08:00' }
const DONE = { ...DRAFT, id: 'rw3', reworkNo: 'FG202610230003', status: 'done' as const, startedAt: '2026-10-23T08:00:00+08:00', completedAt: '2026-10-23T09:30:00+08:00' }

/** 售后来源、但只登记了加工单 id（老数据）⇒ 关联加工单要回落到 id，不能空白 */
const LEGACY_AFTER_SALES = { ...DRAFT, id: 'rw7', reworkNo: 'FG202610230007', processingOrderId: 'po-legacy' }

/** 售后来源 + 加工单号与 id 都有 ⇒ 单号优先（不摆内部 id） */
const AFTER_SALES = {
  ...DRAFT,
  id: 'rw6',
  reworkNo: 'FG202610230006',
  processingOrderId: 'po-9',
  processingOrderNo: 'JG-20261023-0009',
}

/**
 * 车间工人报返工（issue #7860）：没有售后单，带工序 / 数量 / 报工人。
 * 报工人与建单人在库里可能是同一个人 ⇒ 页面只留一列「发起人」，不重复两列。
 */
const WORKER = {
  ...DRAFT,
  id: 'rw5',
  reworkNo: 'FG202610230005',
  source: 'worker' as const,
  afterSalesTicketId: '',
  orderNo: null,
  processingOrderId: 'po-9',
  processingOrderNo: 'JG-20261023-0009',
  operationName: '帘头拼缝',
  qty: 12,
  workerName: '李师傅',
  createdByName: null,
  reason: '拼缝走偏',
}

describe('返工单页面', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    reworkOrderApi.list.mockImplementation(() => wrap([]))
  })

  it('没有返工单 ⇒ 空态（不是空白表格），并给出下一步', async () => {
    render(<ReworkOrdersPage />)

    await waitFor(() => expect(screen.getByTestId('rework-orders-empty')).toBeInTheDocument())
    expect(screen.getByTestId('rework-orders-empty').textContent).toContain('开返工单')
    expect(screen.queryByTestId('rework-orders-table')).toBeNull()
  })

  it('🟢 状态机唯一：待开工只有「开工/取消」，返工中只有「完工/取消」，已闭环没有动作', () => {
    expect(actionsFor('draft')).toEqual(['start', 'cancel'])
    expect(actionsFor('in_progress')).toEqual(['complete', 'cancel'])
    expect(actionsFor('done')).toEqual([])
    expect(actionsFor('cancelled')).toEqual([])
    // 「还在路上」的口径与页面计数同源
    expect(isOpen(DRAFT)).toBe(true)
    expect(isOpen(DONE)).toBe(false)
  })

  it('🔴 已闭环的单**不出现**完工/开工按钮（否则就是「已闭环但返工单还在做」）', async () => {
    reworkOrderApi.list.mockImplementation(() => wrap([DRAFT, DOING, DONE]))
    render(<ReworkOrdersPage />)

    await waitFor(() => expect(screen.getByTestId('rework-orders-table')).toBeInTheDocument())
    // 待开工：开工 + 取消，没有完工
    expect(screen.getByTestId('rework-start-rw1')).toBeInTheDocument()
    expect(screen.getByTestId('rework-cancel-rw1')).toBeInTheDocument()
    expect(screen.queryByTestId('rework-complete-rw1')).toBeNull()
    // 返工中：完工 + 取消，没有开工
    expect(screen.getByTestId('rework-complete-rw2')).toBeInTheDocument()
    expect(screen.queryByTestId('rework-start-rw2')).toBeNull()
    // 已闭环：一个动作都没有
    expect(screen.queryByTestId('rework-complete-rw3')).toBeNull()
    expect(screen.queryByTestId('rework-start-rw3')).toBeNull()
    expect(screen.queryByTestId('rework-cancel-rw3')).toBeNull()
    expect(screen.getByTestId('rework-row-rw3').textContent).toContain('已闭环')
  })

  it('状态计数 = 未完结（待开工 + 返工中）/ 已完成 / 已取消', async () => {
    reworkOrderApi.list.mockImplementation(() =>
      wrap([DRAFT, DOING, DONE, { ...DRAFT, id: 'rw4', status: 'cancelled' as const }]),
    )
    render(<ReworkOrdersPage />)

    await waitFor(() => expect(screen.getByTestId('rework-counts')).toBeInTheDocument())
    const text = screen.getByTestId('rework-counts').textContent || ''
    expect(text).toContain('未完结 2 张')
    expect(text).toContain('待开工 1')
    expect(text).toContain('返工中 1')
    expect(text).toContain('已完成 1 张')
    expect(text).toContain('已取消 1 张')
  })

  it('按状态筛选只留该状态的行（空结果给空态，不是空表格）', async () => {
    reworkOrderApi.list.mockImplementation(() => wrap([DRAFT, DONE]))
    render(<ReworkOrdersPage />)

    await waitFor(() => expect(screen.getByTestId('rework-orders-table')).toBeInTheDocument())
    fireEvent.change(screen.getByTestId('rework-filter-status'), { target: { value: 'done' } })

    await waitFor(() => expect(screen.queryByTestId('rework-row-rw1')).toBeNull())
    expect(screen.getByTestId('rework-row-rw3')).toBeInTheDocument()

    fireEvent.change(screen.getByTestId('rework-filter-status'), { target: { value: 'cancelled' } })
    await waitFor(() => expect(screen.getByTestId('rework-orders-empty')).toBeInTheDocument())
  })

  it('开工 ⇒ 调 start 并刷新列表', async () => {
    reworkOrderApi.list.mockImplementation(() => wrap([DRAFT]))
    reworkOrderApi.start.mockImplementation(() => wrap({ ...DRAFT, status: 'in_progress' }))
    render(<ReworkOrdersPage />)

    await waitFor(() => expect(screen.getByTestId('rework-start-rw1')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('rework-start-rw1'))

    await waitFor(() => expect(reworkOrderApi.start).toHaveBeenCalledWith('rw1'))
    await waitFor(() => expect(reworkOrderApi.list).toHaveBeenCalledTimes(2))
  })

  it('🔴 服务端拒绝的原话上屏（不许吞成「操作失败」）', async () => {
    reworkOrderApi.list.mockImplementation(() => wrap([DRAFT]))
    reworkOrderApi.start.mockRejectedValue({
      response: { status: 400, data: { message: '该售后单已闭环，不能开返工' } },
    })
    render(<ReworkOrdersPage />)

    await waitFor(() => expect(screen.getByTestId('rework-start-rw1')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('rework-start-rw1'))

    await waitFor(() => expect(screen.getByTestId('rework-action-error')).toBeInTheDocument())
    expect(screen.getByTestId('rework-action-error').textContent).toContain('该售后单已闭环')
  })

  it('开单：售后单号必填（缺了当场拦，不发请求）', async () => {
    render(<ReworkOrdersPage />)

    await waitFor(() => expect(screen.getByTestId('rework-create')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('rework-create'))
    fireEvent.click(screen.getByTestId('rework-create-submit'))

    await waitFor(() => expect(screen.getByTestId('rework-form-error')).toBeInTheDocument())
    expect(screen.getByTestId('rework-form-error').textContent).toContain('售后单号')
    expect(reworkOrderApi.create).not.toHaveBeenCalled()
  })

  it('开单成功：带上售后单号 + 原因 + 关联加工单，弹窗关闭并刷新', async () => {
    reworkOrderApi.create.mockImplementation(() => wrap(DRAFT))
    render(<ReworkOrdersPage />)

    await waitFor(() => expect(screen.getByTestId('rework-create')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('rework-create'))
    fireEvent.change(screen.getByTestId('rework-form-ticket'), { target: { value: 'SH-20261023-0001' } })
    fireEvent.change(screen.getByTestId('rework-form-reason'), { target: { value: '帘头褶皱不齐' } })
    fireEvent.change(screen.getByTestId('rework-form-processing'), { target: { value: 'JG-20261023-0008' } })
    fireEvent.click(screen.getByTestId('rework-create-submit'))

    await waitFor(() =>
      expect(reworkOrderApi.create).toHaveBeenCalledWith({
        afterSalesTicketId: 'SH-20261023-0001',
        reason: '帘头褶皱不齐',
        processingOrderId: 'JG-20261023-0008',
      }),
    )
    await waitFor(() => expect(screen.queryByTestId('rework-form-ticket')).toBeNull())
    await waitFor(() => expect(reworkOrderApi.list).toHaveBeenCalledTimes(2))
  })

  it('🔴 本页不产生金额：整页不出现 ¥0.00，且写明成本口径（回工报工 ⇒ 质量成本）', async () => {
    reworkOrderApi.list.mockImplementation(() => wrap([DRAFT, DONE]))
    render(<ReworkOrdersPage />)

    await waitFor(() => expect(screen.getByTestId('rework-orders-table')).toBeInTheDocument())
    expect(document.body.textContent).not.toContain('¥0.00')
    expect(document.body.textContent).toContain('返工成本按「返工报工」的计件金额计入质量成本')
    // 有出口（去报表中心看质量成本），不是一句空说明
    expect(screen.getByText('去报表中心看质量成本')).toBeInTheDocument()
  })

  it('加载失败 ⇒ 常驻失败态 + 可重试出口', async () => {
    reworkOrderApi.list.mockRejectedValue({ response: { status: 500, data: {} } })
    render(<ReworkOrdersPage />)

    await waitFor(() => expect(screen.getByTestId('rework-orders-load-error')).toBeInTheDocument())
    expect(screen.getByTestId('rework-orders-load-error-retry')).toBeInTheDocument()
  })

  it('🟢 车间工人报返工的行：来源「车间返工」+ 工序 / 数量 / 报工人，没有售后单', async () => {
    reworkOrderApi.list.mockImplementation(() => wrap([WORKER]))
    render(<ReworkOrdersPage />)

    await waitFor(() => expect(screen.getByTestId('rework-orders-table')).toBeInTheDocument())
    // 来源：worker ⇒ 人话「车间返工」，不是内部标识
    expect(screen.getByTestId('rework-source-rw5').textContent).toBe('车间返工')
    expect(screen.getByTestId('rework-operation-rw5').textContent).toBe('帘头拼缝')
    expect(screen.getByTestId('rework-qty-rw5').textContent).toBe('12')
    // 报工人上屏为「发起人」（同一信息不重复两列，「建单人」列已撤）
    expect(screen.getByTestId('rework-initiator-rw5').textContent).toBe('李师傅')
    expect(screen.getByText('发起人')).toBeInTheDocument()
    expect(screen.queryByText('建单人')).toBeNull()
    // 车间来源没有售后单 ⇒ 单元格是「—」（不是空白）
    expect(screen.getByTestId('rework-ticket-rw5').textContent).toBe('—')
    // 关联加工单优先显示单号，不摆内部 id
    expect(screen.getByTestId('rework-processing-rw5').textContent).toBe('JG-20261023-0009')
    // 车间来源照样能开工 / 取消（动作逻辑不变）
    expect(screen.getByTestId('rework-start-rw5')).toBeInTheDocument()
    expect(screen.getByTestId('rework-cancel-rw5')).toBeInTheDocument()
    // 副标题把车间来源的存在说出来，不用惊叹号
    expect(document.body.textContent).toContain('车间工人报返工的单也会出现在这里')
    expect(document.body.textContent).not.toContain('！')
  })

  it('售后来源的行仍渲染「售后」，既有列零回归', async () => {
    reworkOrderApi.list.mockImplementation(() => wrap([AFTER_SALES, LEGACY_AFTER_SALES, DRAFT]))
    render(<ReworkOrdersPage />)

    await waitFor(() => expect(screen.getByTestId('rework-orders-table')).toBeInTheDocument())
    expect(screen.getByTestId('rework-source-rw6').textContent).toBe('售后')
    expect(screen.getByTestId('rework-ticket-rw6').textContent).toBe('SH-20261023-0001')
    // 售后来源没有报工人 ⇒ 发起人回落到建单人（列语义没变）
    expect(screen.getByTestId('rework-initiator-rw6').textContent).toBe('王小美')
    // 工序 / 数量：售后来源没有这两项 ⇒ 空值文案（不是 0 / 空白）
    expect(screen.getByTestId('rework-operation-rw6').textContent).toBe('—')
    expect(screen.getByTestId('rework-qty-rw6').textContent).toBe('—')
    // 加工单号与 id 都在 ⇒ 单号优先；只有 id 的老数据 ⇒ 回落 id；都没有 ⇒ 「—」
    expect(screen.getByTestId('rework-processing-rw6').textContent).toBe('JG-20261023-0009')
    expect(screen.getByTestId('rework-processing-rw7').textContent).toBe('po-legacy')
    expect(screen.getByTestId('rework-processing-rw1').textContent).toBe('—')
  })
})
