// case_ids: BM-009
/**
 * 入库过账（管理面手机端，issue #5654 项②）—— 端到端判据
 *
 * 链路：打开页面 → `GET /api/admin/inbound-orders`（列表）→ 点卡片 → `GET /{id}`（详情）
 *       → 草稿单出「过账」→ 二次确认 → `PATCH /{id} {action:'post'}` → 刷新列表与详情。
 *
 * 判据：
 * ① 能打开能读数据：单号 / 状态（中文）/ 供应商 / 日期 / 行数 / 金额（**元**两位小数）；
 * ② 详情懒加载：点卡片才拉详情，明细逐行渲染（货号 · 颜色 · 门幅 / 数量 / 批次）；
 * ③ **过账按钮只对草稿出现**（已过账的单不出现按钮，给「已由谁何时过账」）；
 * ④ 二次确认：取消 ⇒ 一次都不调 PATCH；确认 ⇒ 恰好一次 + 参数逐字 `{action:'post'}`；
 * ⑤ **无权限有文案**：403 ⇒ 「无「入库过账」查看权限（需要权限码 inbound:view）」；
 *    写权限不足 ⇒ 「无「入库过账」过账权限（需要权限码 inbound:create）」且**不发请求**；
 * ⑥ 筛选：切「草稿」⇒ 列表请求带 `status=draft`。
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
  listInboundOrders: jest.fn(),
  getInboundOrder: jest.fn(),
  postInboundOrder: jest.fn(),
}))

import AdminInboundPage from '../src/pages/admin/inbound/index'
import {
  fetchMyPermissions,
  getInboundOrder,
  listInboundOrders,
  postInboundOrder,
  type InboundOrder,
  type InboundOrderLine,
} from '../src/services/adminOpsService'

const mockList = listInboundOrders as jest.MockedFunction<typeof listInboundOrders>
const mockDetail = getInboundOrder as jest.MockedFunction<typeof getInboundOrder>
const mockPost = postInboundOrder as jest.MockedFunction<typeof postInboundOrder>
const mockPermissions = fetchMyPermissions as jest.MockedFunction<typeof fetchMyPermissions>
const mockShowModal = Taro.showModal as jest.Mock

const DRAFT: InboundOrderLine = {
  id: 'i1',
  inboundNo: 'RK-20260926-0001',
  supplier: '绍兴柯桥布行',
  inboundDate: '2026-09-26',
  status: 'draft',
  totalAmount: 4200.5,
  itemCount: 2,
  totalQuantity: 300,
}

const POSTED: InboundOrderLine = {
  id: 'i2',
  inboundNo: 'RK-20260925-0009',
  supplier: '杭州临平纺织',
  inboundDate: '2026-09-25',
  status: 'posted',
  totalAmount: 1800,
  itemCount: 1,
  totalQuantity: 120,
}

const DETAIL: InboundOrder = {
  id: 'i1',
  inboundNo: 'RK-20260926-0001',
  status: 'draft',
  totalAmount: 4200.5,
  items: [
    {
      id: 1,
      skuCode: 'BL-001',
      colorName: '米白',
      doorWidth: '2.8m',
      quantity: 200,
      unitCost: 14,
      amount: 2800,
      batchNo: null,
    },
    {
      id: 2,
      skuCode: 'BL-002',
      colorName: '浅灰',
      doorWidth: '2.8m',
      quantity: 100,
      unitCost: 14.005,
      amount: 1400.5,
      batchNo: null,
    },
  ],
}

async function renderPage() {
  render(<AdminInboundPage />)
  await screen.findByText('RK-20260926-0001')
}

beforeEach(() => {
  jest.clearAllMocks()
  mockPermissions.mockResolvedValue(null)
  mockShowModal.mockResolvedValue({ confirm: true })
  mockList.mockResolvedValue({ status: 'ok', data: [DRAFT, POSTED] })
  mockDetail.mockResolvedValue({ status: 'ok', data: DETAIL })
  mockPost.mockResolvedValue({
    status: 'ok',
    data: { ...DETAIL, status: 'posted', postedBy: '13800000000', postedAt: '2026-09-26T21:00:00+08:00' },
  })
})

describe('管理面②入库过账（issue #5654）', () => {
  it('能打开能读数据：单号 / 状态中文 / 供应商 / 行数 / 元金额', async () => {
    await renderPage()
    expect(screen.getByTestId('inbound-row-i1').textContent).toContain('RK-20260926-0001')
    expect(screen.getByTestId('inbound-row-i1').textContent).toContain('绍兴柯桥布行')
    expect(screen.getByTestId('inbound-row-i1').textContent).toContain('2 行 / 300 件')
    expect(screen.getByTestId('inbound-row-i1').textContent).toContain('¥4200.50')
    expect(screen.getByTestId('inbound-status-i1').textContent).toBe('草稿')
    expect(screen.getByTestId('inbound-status-i2').textContent).toBe('已过账')
  })

  it('详情懒加载：点卡片才拉详情，明细逐行渲染', async () => {
    await renderPage()
    expect(mockDetail).not.toHaveBeenCalled()
    fireEvent.click(screen.getByText('RK-20260926-0001'))
    await waitFor(() => expect(mockDetail).toHaveBeenCalledWith('i1'))
    const detail = await screen.findByTestId('inbound-detail-i1')
    expect(detail.textContent).toContain('BL-001 · 米白 · 2.8m')
    expect(detail.textContent).toContain('数量 200')
    expect(detail.textContent).toContain('过账后生成批次号')
    expect(screen.getByTestId('inbound-post-btn-i1')).toBeTruthy()
  })

  it('过账按钮只对草稿出现；已过账的单给「已由谁何时过账」', async () => {
    mockDetail.mockResolvedValue({
      status: 'ok',
      data: { ...DETAIL, id: 'i2', status: 'posted', postedBy: '张三', postedAt: '2026-09-25T18:00:00+08:00' },
    })
    await renderPage()
    fireEvent.click(screen.getByText('RK-20260925-0009'))
    const posted = await screen.findByTestId('inbound-posted-i2')
    expect(posted.textContent).toContain('张三')
    expect(screen.queryByTestId('inbound-post-btn-i2')).toBeNull()
  })

  it('过账：二次确认后恰好调一次 PATCH，且刷新列表', async () => {
    await renderPage()
    fireEvent.click(screen.getByText('RK-20260926-0001'))
    fireEvent.click(await screen.findByTestId('inbound-post-btn-i1'))
    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1))
    expect(mockPost).toHaveBeenCalledWith('i1')
    await waitFor(() => expect(mockList.mock.calls.length).toBeGreaterThan(1))
    expect(screen.getByTestId('inbound-detail-i1').textContent).toContain('13800000000')
  })

  it('二次确认：取消 ⇒ 一次都不调 PATCH（过账不可逆）', async () => {
    mockShowModal.mockResolvedValue({ confirm: false })
    await renderPage()
    fireEvent.click(screen.getByText('RK-20260926-0001'))
    fireEvent.click(await screen.findByTestId('inbound-post-btn-i1'))
    await waitFor(() => expect(mockShowModal).toHaveBeenCalled())
    expect(mockPost).not.toHaveBeenCalled()
  })

  it('无权限有文案：403 ⇒ 逐字「无「入库过账」查看权限（需要权限码 inbound:view）」', async () => {
    mockList.mockResolvedValue({
      status: 'forbidden',
      message: '无「入库过账」查看权限（需要权限码 inbound:view）',
    })
    render(<AdminInboundPage />)
    const block = await screen.findByTestId('admin-surface-forbidden')
    expect(block.textContent).toBe('无「入库过账」查看权限（需要权限码 inbound:view）')
  })

  it('写权限不足 ⇒ 文案上屏且不发请求（读权有、写权没有的仓管看得见单、过不了账）', async () => {
    mockPermissions.mockResolvedValue(['inbound:view'])
    await renderPage()
    fireEvent.click(screen.getByText('RK-20260926-0001'))
    fireEvent.click(await screen.findByTestId('inbound-post-btn-i1'))
    await waitFor(() =>
      expect(screen.getByTestId('inbound-notice').textContent).toBe(
        '无「入库过账」过账权限（需要权限码 inbound:create）',
      ),
    )
    expect(mockPost).not.toHaveBeenCalled()
  })

  it('过账失败 ⇒ 服务端文案上屏（不静默）', async () => {
    mockPost.mockResolvedValue({ status: 'error', message: '仅草稿状态的入库单可以过账' })
    await renderPage()
    fireEvent.click(screen.getByText('RK-20260926-0001'))
    fireEvent.click(await screen.findByTestId('inbound-post-btn-i1'))
    await waitFor(() =>
      expect(screen.getByTestId('inbound-notice').textContent).toBe('仅草稿状态的入库单可以过账'),
    )
  })

  it('筛选：切「草稿」⇒ 列表请求带 status=draft', async () => {
    await renderPage()
    fireEvent.click(screen.getByTestId('inbound-filter-draft'))
    await waitFor(() => expect(mockList).toHaveBeenCalledWith({ status: 'draft' }))
  })
})
