// case_ids: BM-009
/**
 * 智能派单（管理面手机端，issue #5654 项①）—— 端到端判据
 *
 * 链路：打开页面 → `GET /api/admin/production/pool`（池 + 加急插队区）→ 勾选 → 预览
 *       → 二次确认 → `POST .../pool/dispatch` → 逐单结果上屏 + 重新拉池。
 *
 * 判据（每条都能被注入式改坏 ⇒ 红）：
 * ① 能打开 / 能读数据：单号、物料、需求米数、等待时长、池化开关状态、超时告警都在屏上；
 * ② 关键动作能提交：勾选 → 预览（服务端五个米数原样渲染）→ 确认派单 ⇒ 调一次 dispatch，参数逐字；
 * ③ **二次确认**：弹窗取消 ⇒ **一次都不调** dispatch（红证：去掉确认分支 ⇒ 必红）；
 * ④ **加急单不进成批**：加急区走「立刻单派」= 单订单 + `pooled:false`；
 * ⑤ **失败不静默**：逐单失败也上屏（`success:false` 的那行必须看得见）；
 * ⑥ **无权限有文案**：403 ⇒ 「无「智能派单」查看权限（需要权限码 processing:view）」；
 * ⑦ 未勾选 ⇒ 明说「先勾选要合并派单的加工单」，且不发预览请求。
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
  getProductionPool: jest.fn(),
  previewPoolDispatch: jest.fn(),
  dispatchPoolOrders: jest.fn(),
}))

import AdminPoolPage from '../src/pages/admin/pool/index'
import {
  dispatchPoolOrders,
  fetchMyPermissions,
  getProductionPool,
  previewPoolDispatch,
  type PoolBoard,
} from '../src/services/adminOpsService'

const mockGetPool = getProductionPool as jest.MockedFunction<typeof getProductionPool>
const mockPreview = previewPoolDispatch as jest.MockedFunction<typeof previewPoolDispatch>
const mockDispatch = dispatchPoolOrders as jest.MockedFunction<typeof dispatchPoolOrders>
const mockPermissions = fetchMyPermissions as jest.MockedFunction<typeof fetchMyPermissions>
const mockShowModal = Taro.showModal as jest.Mock

const LINE = (
  orderId: string,
  orderNo: string,
  over: Partial<Record<string, unknown>> = {},
) => ({
  orderId,
  orderNo,
  itemId: `${orderId}-item`,
  productId: 'p1',
  productName: '布帘A',
  skuCode: '米白/2.8',
  requiredMeters: 10,
  waitingSince: '2026-09-26T08:00:00+08:00',
  waitHours: 5,
  overdue: false,
  isUrgent: false,
  ...over,
})

const BOARD: PoolBoard = {
  maxWaitHours: 24,
  poolingEnabled: false,
  orderCount: 2,
  lineCount: 2,
  overdueCount: 1,
  urgentCount: 1,
  warnings: [
    { orderId: 'u1', orderNo: 'SO-U1', waitHours: 30, message: '订单 SO-U1 已等 30.0 小时，请立刻单派' },
  ],
  urgentLines: [LINE('u1', 'SO-U1', { isUrgent: true, overdue: true, waitHours: 30 })],
  groups: [
    {
      materialKey: 'p1|米白/2.8',
      productId: 'p1',
      skuCode: '米白/2.8',
      orderCount: 2,
      requiredMeters: 20,
      lines: [LINE('o1', 'SO-001'), LINE('o2', 'SO-002', { waitHours: 3 })],
    },
  ],
}

const PREVIEW = {
  orderCount: 2,
  assignmentRule: 'fifo',
  formulaMeters: 20,
  pooledPlannedMeters: 17.5,
  savedMeters: 2.5,
  perOrderPlannedMeters: 19,
  poolingGainMeters: 1.5,
}

async function renderPage() {
  render(<AdminPoolPage />)
  await waitFor(() => expect(mockGetPool).toHaveBeenCalled())
  await screen.findByText('SO-001')
}

beforeEach(() => {
  jest.clearAllMocks()
  mockPermissions.mockResolvedValue(null)
  mockShowModal.mockResolvedValue({ confirm: true })
  mockGetPool.mockResolvedValue({ status: 'ok', data: BOARD })
  mockPreview.mockResolvedValue({ status: 'ok', data: PREVIEW })
  mockDispatch.mockResolvedValue({
    status: 'ok',
    data: [
      { orderRef: 'o1', processingOrderNo: 'JG-001', success: true },
      { orderRef: 'o2', success: false, message: '批次余量不足，无法派单' },
    ],
  })
})

describe('管理面①智能派单（issue #5654）', () => {
  it('能打开能读数据：池化开关状态 / 超时告警 / 加急区 / 物料分组都在屏上', async () => {
    await renderPage()
    expect(screen.getByTestId('pool-pooling-state').textContent).toContain('池化派单未开启')
    expect(screen.getByTestId('pool-overdue').textContent).toContain('1 张单已超过滞留上限')
    expect(screen.getByTestId('pool-overdue').textContent).toContain('请立刻单派')
    expect(screen.getByTestId('pool-urgent-u1')).toBeTruthy()
    expect(screen.getByTestId('pool-group-p1|米白/2.8')).toBeTruthy()
    expect(screen.getByTestId('pool-line-o1').textContent).toContain('需求 10.00 米')
    expect(screen.getByTestId('pool-line-o2').textContent).toContain('已等待 3 小时')
  })

  it('关键动作能提交：勾选 → 预览（服务端米数原样）→ 确认派单 → 逐单结果上屏', async () => {
    await renderPage()
    fireEvent.click(screen.getByTestId('pool-line-o1'))
    fireEvent.click(screen.getByTestId('pool-line-o2'))
    expect(screen.getByTestId('pool-selected-count').textContent).toContain('已选 2 单')

    fireEvent.click(screen.getByTestId('pool-preview-btn'))
    await waitFor(() => expect(mockPreview).toHaveBeenCalledWith(['o1', 'o2']))
    // 五个米数**逐字服务端值**（前端相减 20−17.5 会得到 2.5 —— 这里刻意让服务端值不同源可辨：
    // perOrderPlannedMeters=19 ≠ formulaMeters=20，若前端自己算「节省」就会写成 1.00）
    expect(screen.getByTestId('pool-preview-formula').textContent).toContain('20.00')
    expect(screen.getByTestId('pool-preview-saved').textContent).toContain('2.50')
    expect(screen.getByTestId('pool-preview-per_order').textContent).toContain('19.00')
    expect(screen.getByTestId('pool-preview-gain').textContent).toContain('1.50')

    fireEvent.click(screen.getByTestId('pool-dispatch-btn'))
    await waitFor(() => expect(mockDispatch).toHaveBeenCalledWith(['o1', 'o2'], true))
    const result = await screen.findByTestId('pool-dispatch-result')
    expect(result.textContent).toContain('SO-001')
    expect(result.textContent).toContain('JG-001')
    // 逐单失败必须上屏（不静默少派）
    expect(result.textContent).toContain('SO-002')
    expect(result.textContent).toContain('批次余量不足，无法派单')
    // 派单成功后重新拉池
    await waitFor(() => expect(mockGetPool.mock.calls.length).toBeGreaterThan(1))
  })

  it('二次确认：弹窗取消 ⇒ 一次都不调 dispatch（不可逆动作的护栏）', async () => {
    mockShowModal.mockResolvedValue({ confirm: false })
    await renderPage()
    fireEvent.click(screen.getByTestId('pool-line-o1'))
    fireEvent.click(screen.getByTestId('pool-dispatch-btn'))
    await waitFor(() => expect(mockShowModal).toHaveBeenCalled())
    expect(mockDispatch).not.toHaveBeenCalled()
  })

  it('加急单不进成批：立刻单派 = 单订单 + pooled:false', async () => {
    await renderPage()
    fireEvent.click(screen.getByTestId('pool-urgent-dispatch-u1'))
    await waitFor(() => expect(mockDispatch).toHaveBeenCalledWith(['u1'], false))
    // 加急行不在成批候选里（点它不改变已选数）
    expect(screen.getByTestId('pool-selected-count').textContent).toContain('已选 0 单')
  })

  it('无权限有文案：403 ⇒ 逐字「无「智能派单」查看权限（需要权限码 processing:view）」', async () => {
    mockGetPool.mockResolvedValue({
      status: 'forbidden',
      message: '无「智能派单」查看权限（需要权限码 processing:view）',
    })
    render(<AdminPoolPage />)
    const block = await screen.findByTestId('admin-surface-forbidden')
    expect(block.textContent).toBe('无「智能派单」查看权限（需要权限码 processing:view）')
  })

  it('写权限不足 ⇒ 文案上屏且**不发请求**（不让管理员白等一次必然 403 的往返）', async () => {
    mockPermissions.mockResolvedValue(['processing:view'])
    await renderPage()
    fireEvent.click(screen.getByTestId('pool-line-o1'))
    fireEvent.click(screen.getByTestId('pool-preview-btn'))
    await waitFor(() =>
      expect(screen.getByTestId('pool-notice').textContent).toBe(
        '无「智能派单」派单权限（需要权限码 processing:update）',
      ),
    )
    expect(mockPreview).not.toHaveBeenCalled()

    fireEvent.click(screen.getByTestId('pool-dispatch-btn'))
    await waitFor(() => expect(screen.getByTestId('pool-notice')).toBeTruthy())
    expect(mockDispatch).not.toHaveBeenCalled()
  })

  it('未勾选 ⇒ 明说「先勾选要合并派单的加工单」且不发预览请求', async () => {
    await renderPage()
    fireEvent.click(screen.getByTestId('pool-preview-btn'))
    await waitFor(() =>
      expect(screen.getByTestId('pool-notice').textContent).toBe('先勾选要合并派单的加工单'),
    )
    expect(mockPreview).not.toHaveBeenCalled()
  })
})
