// case_ids: UI-078

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

/**
 * 发货单列表页（/shipments）—— 大菜单「仓储与物料 ▸ 发货单」的第一屏（issue #5939）。
 *
 * 用户的报障（2026-10-02 原话）：「我让你开发过发货单的，但是在大菜单上没见到这个单据」。
 * 本文件钉住**页面侧**的三件事：
 *   ① 全量发货单看得见（单号 / 订单号 / 客户 / 发货人 / 发货时间 / 实发）；
 *   ② 缺值**显式**，不伪装：未发货 ⇒「未发货」（不填当前时间）、发货人未采集 ⇒「-」、
 *      无明细 ⇒「无实发明细」（不是 0、不是空白）；
 *   ③ **补打**走 #5914 的唯一打印入口：取订单 → 打开**纸面自检层**（真尺寸 A4）。
 * 菜单三源同构另见 `tests/unit/lib/shipments-menu-isomorphic.test.ts`。
 */

const mockList = vi.fn()
const mockGetOrder = vi.fn()

vi.mock('@/lib/api', () => ({
  shipmentApi: {
    list: (...args: any[]) => mockList(...args),
  },
  orderApi: {
    getOrder: (...args: any[]) => mockGetOrder(...args),
  },
}))

const mockPush = vi.fn()
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
}))

/** 列表一行：已发货、工人拍照、有实发明细 */
const shippedRow = {
  id: 's-1',
  shipmentNo: 'FH-20261002120000-A001',
  orderId: 'o-1',
  orderNo: 'CSO261002-0001',
  customerName: '张女士',
  source: 'worker_photo',
  packedAt: '2026-10-02T10:00:00+08:00',
  shippedAt: '2026-10-02T12:00:00+08:00',
  shippedByWorkerName: '小王',
  trackingNo: 'SF1234567890',
  logisticsCompany: '顺丰',
  itemCount: 2,
  shippedTotals: { set_count: 2, roll_count: 0, by_unit: { 米: 12.5 } },
}

/** 列表一行：只打包未发货、发货人未采集、无明细 */
const packedRow = {
  id: 's-2',
  shipmentNo: 'FH-20261002130000-A002',
  orderId: 'o-2',
  orderNo: 'CSO261002-0002',
  customerName: null,
  source: 'worker',
  packedAt: '2026-10-02T13:00:00+08:00',
  shippedAt: null,
  shippedByWorkerName: null,
  trackingNo: null,
  logisticsCompany: null,
  itemCount: 0,
  shippedTotals: { set_count: 0, roll_count: 0, by_unit: {} },
}

const order = {
  id: 'o-1',
  orderNo: 'CSO261002-0001',
  customerName: '张女士',
  status: 'shipped',
  items: [],
}

import Shipments, { shippedSummary } from '@/app/(dashboard)/shipments/page'

beforeEach(() => {
  vi.clearAllMocks()
  mockList.mockResolvedValue({ data: { data: [shippedRow, packedRow] } })
  mockGetOrder.mockResolvedValue({ data: { data: order } })
})

describe('发货单列表页（issue #5939 / UI-078）', () => {
  it('① 全量发货单看得见：单号 / 订单号 / 客户 / 发货人 / 实发', async () => {
    render(<Shipments />)

    expect(await screen.findByText('FH-20261002120000-A001')).toBeInTheDocument()
    expect(screen.getByText('CSO261002-0001')).toBeInTheDocument()
    expect(screen.getByText('张女士')).toBeInTheDocument()
    expect(screen.getByText('小王')).toBeInTheDocument()
    // 实发：by_unit（米）+ 套数（显式填过的行求和；roll_count = 0 ⇒ 不显示「0 卷」）
    expect(screen.getByText('12.5米 / 2 套')).toBeInTheDocument()
    expect(screen.queryByText(/0 卷/)).toBeNull()
  })

  it('② 缺值显式：未发货 ⇒「未发货」（不填时间）、发货人未采集 ⇒「-」、无明细 ⇒「无实发明细」', async () => {
    render(<Shipments />)

    expect(await screen.findByText('FH-20261002130000-A002')).toBeInTheDocument()
    const shippedAtCells = screen.getAllByTestId('shipment-shipped-at')
    expect(shippedAtCells[1].textContent).toBe('未发货')
    const shipperCells = screen.getAllByTestId('shipment-shipper')
    expect(shipperCells[1].textContent).toBe('-')
    const shippedCells = screen.getAllByTestId('shipment-shipped')
    expect(shippedCells[1].textContent).toBe('无实发明细')
    // 客户名为空 ⇒ 「-」，不是空白
    expect(screen.getByText('CSO261002-0002').closest('tr')?.textContent).toContain('-')
  })

  it('③ 实发汇总口径：0 的维度不显示（0 = 这一维不适用，不是「发了 0」）', () => {
    expect(shippedSummary(shippedRow as any)).toBe('12.5米 / 2 套')
    expect(shippedSummary(packedRow as any)).toBe('无实发明细')
    // 只有卷数、没有米数/套数
    expect(
      shippedSummary({ itemCount: 1, shippedTotals: { set_count: 0, roll_count: 3, by_unit: {} } } as any),
    ).toBe('3 卷')
    // 读面没给汇总（服务端老版本 / 字段缺失）⇒ 仍要说清「无明细」，不是空白
    expect(shippedSummary({ itemCount: 0, shippedTotals: null } as any)).toBe('无实发明细')
  })

  it('④ 关键词筛选：点「查询」按关键词取数；「重置」清空关键词', async () => {
    const user = userEvent.setup()
    render(<Shipments />)
    await waitFor(() => expect(mockList).toHaveBeenCalledWith({ keyword: undefined }))

    await user.type(screen.getByLabelText('搜索发货单'), 'CSO261002-0002')
    await user.click(screen.getByRole('button', { name: '查询' }))
    await waitFor(() =>
      expect(mockList).toHaveBeenLastCalledWith({ keyword: 'CSO261002-0002' }),
    )

    await user.click(screen.getByRole('button', { name: '重置' }))
    expect(screen.getByLabelText('搜索发货单')).toHaveValue('')
    await waitFor(() => expect(mockList).toHaveBeenLastCalledWith({ keyword: undefined }))
  })

  it('⑤ 空列表 ⇒「暂无发货单」；读面失败 ⇒ **失败态**（不是空态，issue #6664 第 3 条）', async () => {
    mockList.mockResolvedValue({ data: { data: [] } })
    const { unmount } = render(<Shipments />)
    expect(await screen.findByText('暂无发货单')).toBeInTheDocument()
    // 空态不得同时说「加载失败」（两态互斥）
    expect(screen.queryByText(/加载失败/)).toBeNull()
    unmount()

    // 读面故障 ≠「没有发货单」—— 故障说「加载失败」+ 重试出口，且不留半截数据
    mockList.mockRejectedValue(new Error('boom'))
    render(<Shipments />)
    expect(await screen.findByText(/加载失败/)).toBeInTheDocument()
    expect(screen.queryByText('暂无发货单')).toBeNull()
    expect(screen.queryAllByTestId('shipment-row')).toHaveLength(0)
    expect(screen.getByRole('button', { name: /重试/ })).toBeEnabled()
  })

  it('⑤b 失败后点重试 ⇒ 重新取数并渲染出列表（重试不是摆设）', async () => {
    mockList.mockRejectedValueOnce(new Error('boom'))
    render(<Shipments />)
    await screen.findByText(/加载失败/)

    mockList.mockResolvedValue({ data: { data: [shippedRow] } })
    fireEvent.click(screen.getByRole('button', { name: /重试/ }))

    expect(await screen.findByText('FH-20261002120000-A001')).toBeInTheDocument()
    expect(screen.queryByText(/加载失败/)).toBeNull()
  })

  it('⑥ 补打：取订单 → 打开纸面自检层（真尺寸 A4 发货单）；取不到订单 ⇒ 不弹预览层', async () => {
    const user = userEvent.setup()
    render(<Shipments />)
    await screen.findByText('FH-20261002120000-A001')

    await user.click(screen.getByLabelText('补打 FH-20261002120000-A001'))
    expect(mockGetOrder).toHaveBeenCalledWith('o-1')
    const preview = await screen.findByLabelText('发货单打印预览')
    expect(preview).toBeInTheDocument()
    expect(screen.getByTestId('print-preview-print')).toBeInTheDocument()

    // 反向：订单取不到 ⇒ 不打开预览层（宁可什么都不弹，也不弹一张缺数据的纸）
    mockGetOrder.mockRejectedValue(new Error('404'))
    await user.click(screen.getByLabelText('补打 FH-20261002130000-A002'))
    await waitFor(() => expect(mockGetOrder).toHaveBeenCalledTimes(2))
    expect(screen.getAllByLabelText('发货单打印预览')).toHaveLength(1)
  })

  it('⑦ 「查看订单」跳该发货单对应的订单（不是发货单本身）', async () => {
    const user = userEvent.setup()
    render(<Shipments />)
    await screen.findByText('FH-20261002120000-A001')

    await user.click(screen.getAllByRole('button', { name: '查看订单' })[0])
    expect(mockPush).toHaveBeenCalledWith('/orders/o-1')
  })
})
