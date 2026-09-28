// case_ids: BM-009
/**
 * 售后处理（管理面手机端，issue #5654 项③）—— 端到端判据
 *
 * 链路：打开页面 → `GET /api/admin/after-sales`（列表）→ 点卡片 → `GET /{id}`（详情 + 状态历史）
 *       → **只出状态机允许的下一步** → 二次确认 → `PUT /{id}/status` → 刷新列表与详情。
 *
 * 判据：
 * ① 能打开能读数据：工单号 / 客户 / 类型 / 状态中文 / 退款金额（元）；
 * ② 详情含状态历史；
 * ③ **动作面 = 状态机的允许集**：`pending` ⇒ 处理中/已拒绝/已关闭（**没有**「已解决」）；
 *    `resolved` ⇒ 一个按钮都不出 + 「已是终态，不能再流转」；
 * ④ 二次确认：取消 ⇒ 一次都不调 PUT；确认 ⇒ `PUT {status:'processing'}` 逐字；
 * ⑤ **无权限有文案**：403 ⇒ 「无「售后处理」查看权限（需要权限码 after_sales:view）」；
 *    写权限不足（只有读码）⇒ 「无「售后处理」处理权限（需要权限码 order:refund）」且不发请求；
 * ⑥ 服务端状态机拒绝 ⇒ 原样透出中文文案（不吞）。
 */
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import Taro from '@tarojs/taro'

jest.mock('../src/store/authStore', () => ({
  useAuthStore: jest.fn(() => ({ isLoggedIn: true, user: { id: 'u1', nickname: '王老板' } })),
}))

jest.mock('../src/services/adminOpsService', () => ({
  ...jest.requireActual('../src/services/adminOpsService'),
  fetchMyPermissions: jest.fn(),
  listAfterSales: jest.fn(),
  getAfterSalesTicket: jest.fn(),
  updateAfterSalesStatus: jest.fn(),
}))

import AdminAfterSalesPage from '../src/pages/admin/after-sales/index'
import {
  fetchMyPermissions,
  getAfterSalesTicket,
  listAfterSales,
  updateAfterSalesStatus,
  type AfterSalesTicket,
} from '../src/services/adminOpsService'

const mockList = listAfterSales as jest.MockedFunction<typeof listAfterSales>
const mockDetail = getAfterSalesTicket as jest.MockedFunction<typeof getAfterSalesTicket>
const mockUpdate = updateAfterSalesStatus as jest.MockedFunction<typeof updateAfterSalesStatus>
const mockPermissions = fetchMyPermissions as jest.MockedFunction<typeof fetchMyPermissions>
const mockShowModal = Taro.showModal as jest.Mock

const PENDING: AfterSalesTicket = {
  id: 't1',
  ticketNo: 'AS-20260926-001',
  orderNo: 'SO-20260920-003',
  customerName: '李女士',
  ticketType: 'refund',
  status: 'pending',
  description: '窗帘尺寸不符，要求退款',
  refundAmount: 880.5,
}

const RESOLVED: AfterSalesTicket = {
  id: 't2',
  ticketNo: 'AS-20260920-007',
  customerName: '赵先生',
  ticketType: 'exchange',
  status: 'resolved',
  refundAmount: 0,
}

const PENDING_DETAIL: AfterSalesTicket = {
  ...PENDING,
  handlerName: '客服小张',
  statusHistory: [
    { status: 'pending', time: '2026-09-26 10:00', operator: '系统', remark: '客户提交' },
  ],
}

async function renderPage() {
  render(<AdminAfterSalesPage />)
  await screen.findByText('AS-20260926-001')
}

beforeEach(() => {
  jest.clearAllMocks()
  mockPermissions.mockResolvedValue(null)
  mockShowModal.mockResolvedValue({ confirm: true })
  mockList.mockResolvedValue({
    status: 'ok',
    data: { total: 2, page: 1, size: 20, items: [PENDING, RESOLVED] },
  })
  mockDetail.mockResolvedValue({ status: 'ok', data: PENDING_DETAIL })
  mockUpdate.mockResolvedValue({ status: 'ok', data: true })
})

describe('管理面③售后处理（issue #5654）', () => {
  it('能打开能读数据：工单号 / 客户 / 类型 / 状态中文 / 金额', async () => {
    await renderPage()
    const row = screen.getByTestId('as-row-t1')
    expect(row.textContent).toContain('AS-20260926-001')
    expect(row.textContent).toContain('李女士')
    expect(row.textContent).toContain('refund')
    expect(row.textContent).toContain('¥880.50')
    expect(screen.getByTestId('as-status-t1').textContent).toBe('待处理')
    expect(screen.getByTestId('as-status-t2').textContent).toBe('已解决')
  })

  it('详情懒加载并含状态历史', async () => {
    await renderPage()
    expect(mockDetail).not.toHaveBeenCalled()
    fireEvent.click(screen.getByText('AS-20260926-001'))
    await waitFor(() => expect(mockDetail).toHaveBeenCalledWith('t1'))
    const detail = await screen.findByTestId('as-detail-t1')
    expect(detail.textContent).toContain('窗帘尺寸不符，要求退款')
    expect(detail.textContent).toContain('客服小张')
    expect(screen.getByTestId('as-history-t1-0').textContent).toContain('待处理 · 2026-09-26 10:00')
  })

  it('动作面 = 状态机允许集：pending 出三个下一步、**没有**「已解决」', async () => {
    await renderPage()
    fireEvent.click(screen.getByText('AS-20260926-001'))
    expect(await screen.findByTestId('as-status-btn-t1-processing')).toBeTruthy()
    expect(screen.getByTestId('as-status-btn-t1-rejected')).toBeTruthy()
    expect(screen.getByTestId('as-status-btn-t1-closed')).toBeTruthy()
    // 「已解决」不是 pending 的合法目标（后端 STATUS_TRANSITIONS）⇒ 页面上不该有这个按钮
    expect(screen.queryByTestId('as-status-btn-t1-resolved')).toBeNull()
  })

  it('终态（resolved）⇒ 一个动作按钮都不出 + 明说不可再流转', async () => {
    mockDetail.mockResolvedValue({ status: 'ok', data: { ...RESOLVED, statusHistory: [] } })
    await renderPage()
    fireEvent.click(screen.getByText('AS-20260920-007'))
    expect(await screen.findByTestId('as-terminal-t2')).toBeTruthy()
    expect(screen.queryByTestId('as-status-btn-t2-processing')).toBeNull()
    expect(screen.queryByTestId('as-status-btn-t2-closed')).toBeNull()
  })

  it('处理动作：二次确认后 PUT {status} 逐字，并刷新列表与详情', async () => {
    await renderPage()
    fireEvent.click(screen.getByText('AS-20260926-001'))
    fireEvent.click(await screen.findByTestId('as-status-btn-t1-processing'))
    await waitFor(() => expect(mockUpdate).toHaveBeenCalledWith('t1', 'processing'))
    await waitFor(() => expect(mockList.mock.calls.length).toBeGreaterThan(1))
    await waitFor(() => expect(mockDetail.mock.calls.length).toBeGreaterThan(1))
  })

  it('二次确认：取消 ⇒ 一次都不调 PUT', async () => {
    mockShowModal.mockResolvedValue({ confirm: false })
    await renderPage()
    fireEvent.click(screen.getByText('AS-20260926-001'))
    fireEvent.click(await screen.findByTestId('as-status-btn-t1-closed'))
    await waitFor(() => expect(mockShowModal).toHaveBeenCalled())
    expect(mockUpdate).not.toHaveBeenCalled()
  })

  it('无权限有文案：403 ⇒ 逐字「无「售后处理」查看权限（需要权限码 after_sales:view）」', async () => {
    mockList.mockResolvedValue({
      status: 'forbidden',
      message: '无「售后处理」查看权限（需要权限码 after_sales:view）',
    })
    render(<AdminAfterSalesPage />)
    const block = await screen.findByTestId('admin-surface-forbidden')
    expect(block.textContent).toBe('无「售后处理」查看权限（需要权限码 after_sales:view）')
  })

  it('写权限不足（只有读码）⇒ 文案上屏且不发请求', async () => {
    mockPermissions.mockResolvedValue(['after_sales:view'])
    await renderPage()
    fireEvent.click(screen.getByText('AS-20260926-001'))
    fireEvent.click(await screen.findByTestId('as-status-btn-t1-processing'))
    await waitFor(() =>
      expect(screen.getByTestId('as-notice').textContent).toBe(
        '无「售后处理」处理权限（需要权限码 order:refund）',
      ),
    )
    expect(mockUpdate).not.toHaveBeenCalled()
  })

  it('服务端状态机拒绝 ⇒ 原样透出中文文案（不吞、不泛化）', async () => {
    mockUpdate.mockResolvedValue({
      status: 'error',
      message: '工单状态不允许从 [待处理] 变更为 [已解决]',
    })
    await renderPage()
    fireEvent.click(screen.getByText('AS-20260926-001'))
    fireEvent.click(await screen.findByTestId('as-status-btn-t1-processing'))
    await waitFor(() =>
      expect(screen.getByTestId('as-notice').textContent).toBe(
        '工单状态不允许从 [待处理] 变更为 [已解决]',
      ),
    )
  })
})
