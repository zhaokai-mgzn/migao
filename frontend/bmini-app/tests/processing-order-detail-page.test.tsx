// case_ids: BM-040
/**
 * 「加工单详情」只读页（商家面）—— issue #6567
 *
 * ## 为什么是这五条
 * 这一页存在的理由只有一个：商家在「数据」页点一张待办卡片，要看到**这一单什么情况**，
 * 而不是拿起手机去扫码报工（旧落脚点是报工页：扫一扫 + 手输单号 + 「去登录工人身份」）。
 * ⇒ 判据必须同时钉住「该显示的显示了」与「**不该出现的没出现**」：
 *
 * | # | 判据 | 红证（怎么让它单独变红） |
 * |---|---|---|
 * | 1 | 抬头逐字来自服务端（加工单号 / 订单号 / 客户 / 交期） | 把某一行的值改成本地拼串 ⇒ 值对不上 ⇒ 红 |
 * | 2 | 工序名单走唯一口径 `逻辑名 · 部位` + 应做/已报数量原样 | 手拼工序名 ⇒ 显示名对不上 ⇒ 红 |
 * | 3 | 🔴 **纯只读**：源码（去注释）里没有扫一扫 / 工人登录 / 报工写入口记号 | 注入一个「扫一扫」按钮或 `scanResolve(` ⇒ 红 |
 * | 4 | 403 ⇒ **权限文案**（不是「没有数据」） | 把 `forbidden` 分支删掉 ⇒ 落到「加载失败」⇒ 红 |
 * | 5 | 「订单还没有加工单」与「加载失败」分开说；失败可重试 | 把 `data:null` 当失败 ⇒ 文案错 ⇒ 红 |
 */
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import * as fs from 'fs'
import * as path from 'path'

jest.mock('@tarojs/taro', () => ({
  __esModule: true,
  default: {
    getCurrentInstance: jest.fn(() => ({ router: { params: { orderId: 'order-1' } } })),
    navigateTo: jest.fn(),
    redirectTo: jest.fn(),
    getStorageSync: jest.fn(() => ''),
    setStorageSync: jest.fn(),
    removeStorageSync: jest.fn(),
    showToast: jest.fn(),
  },
  useDidShow: jest.fn(),
}))

jest.mock('../src/utils/request', () => ({
  get: jest.fn(),
  post: jest.fn(),
  put: jest.fn(),
  del: jest.fn(),
}))

import Taro from '@tarojs/taro'
import { get } from '../src/utils/request'
import OrderDetailPage from '../src/pages/production/order-detail/index'
import { stripComments } from './helpers/h5PlatformLists'

const mockGet = get as unknown as jest.Mock

const BRIEF = {
  success: true,
  data: {
    id: 'po-1',
    orderId: 'order-1',
    orderNo: 'SO-2026-001',
    processingOrderNo: 'MO-2026-001',
    customerName: '陈女士',
    expectedDeliveryDate: '2026-10-12',
  },
}

const OPERATIONS = {
  success: true,
  data: {
    order_id: 'order-1',
    positions: [
      {
        position_name: '布帘',
        operations: [
          {
            id: 'op-1',
            seq: 1,
            operation: '精裁-布',
            logical_name: '精裁',
            position: '布帘',
            group: 'g1',
            unit: '米',
            qty: 6,
            unit_price: 3,
            is_must_finish: true,
            is_start_marker: false,
            status: 'done',
            done_qty: 6,
          },
        ],
      },
    ],
    progress: { total: 1, done: 1, percent: 100 },
  },
}

/** 按 URL 分派桩响应（两条读面各自独立，便于单条失败/403 的用例） */
function stub(props: { brief?: any; operations?: any; briefError?: any; opsError?: any } = {}) {
  mockGet.mockImplementation((url: string) => {
    if (url.includes('/api/admin/processing-orders/')) {
      return props.briefError ? Promise.reject(props.briefError) : Promise.resolve(props.brief ?? BRIEF)
    }
    if (url.includes('/operations')) {
      return props.opsError ? Promise.reject(props.opsError) : Promise.resolve(props.operations ?? OPERATIONS)
    }
    return Promise.reject(new Error(`未桩住的端点：${url}`))
  })
}

describe('加工单详情页（商家只读面）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    stub()
  })

  it('抬头与工序逐字来自服务端（加工单号 / 订单号 / 客户 / 交期 + 工序进度）', async () => {
    render(<OrderDetailPage />)
    await waitFor(() => expect(screen.getByTestId('order-detail-header')).toBeTruthy())

    expect(screen.getByText('加工单号')).toBeTruthy()
    expect(screen.getByText('MO-2026-001')).toBeTruthy()
    expect(screen.getByText('订单号')).toBeTruthy()
    expect(screen.getByText('SO-2026-001')).toBeTruthy()
    expect(screen.getByText('客户')).toBeTruthy()
    expect(screen.getByText('陈女士')).toBeTruthy()
    expect(screen.getByText('交期')).toBeTruthy()
    expect(screen.getByText('2026-10-12')).toBeTruthy()
    // 工序名走唯一口径（`逻辑名 · 部位`），数量原样
    expect(screen.getByText('精裁 · 布帘')).toBeTruthy()
    expect(screen.getByText('应做 6米 · 已报 6米')).toBeTruthy()
    expect(screen.getByText('已完成 1/1')).toBeTruthy()
  })

  it('拿不到的字段**不渲染那一行**（不补默认值、不摆占位）', async () => {
    stub({ brief: { success: true, data: { id: 'po-1', orderId: 'order-1', processingOrderNo: 'MO-1' } } })
    render(<OrderDetailPage />)
    await waitFor(() => expect(screen.getByTestId('order-detail-header')).toBeTruthy())

    expect(screen.getByText('MO-1')).toBeTruthy()
    expect(screen.queryByText('客户')).toBeNull()
    expect(screen.queryByText('交期')).toBeNull()
    expect(screen.queryByText('订单号')).toBeNull()
  })

  it('🔴 403 ⇒ 显式权限文案（**不是**「没有数据」，也不是「加载失败」）', async () => {
    stub({ briefError: Object.assign(new Error('无权限'), { statusCode: 403 }) })
    render(<OrderDetailPage />)
    await waitFor(() => expect(screen.getByTestId('order-detail-forbidden')).toBeTruthy())

    expect(screen.getByText('无「生产看板」查看权限（需要权限码 production:view）')).toBeTruthy()
    expect(screen.queryByTestId('order-detail-no-processing-order')).toBeNull()
    expect(screen.queryByTestId('order-detail-error')).toBeNull()
  })

  it('订单还没有加工单（服务端 `success + data:null`）⇒ 单独一句，不当失败', async () => {
    stub({ brief: { success: true, data: null } })
    render(<OrderDetailPage />)
    await waitFor(() => expect(screen.getByTestId('order-detail-no-processing-order')).toBeTruthy())

    expect(screen.getByText('这笔订单还没有加工单')).toBeTruthy()
    expect(screen.queryByTestId('order-detail-error')).toBeNull()
    expect(screen.queryByTestId('order-detail-forbidden')).toBeNull()
  })

  it('加载失败 ⇒ 错误文案 + 可重试（重试真的再发一次请求）', async () => {
    stub({ briefError: new Error('boom') })
    render(<OrderDetailPage />)
    await waitFor(() => expect(screen.getByTestId('order-detail-error')).toBeTruthy())

    const callsBefore = mockGet.mock.calls.length
    fireEvent.click(screen.getByText('重试'))
    await waitFor(() => expect(mockGet.mock.calls.length).toBeGreaterThan(callsBefore))
  })

  it('没带参数 ⇒ 说清「从数据页的待办点进来」，不发任何请求', async () => {
    ;(Taro.getCurrentInstance as jest.Mock).mockReturnValue({ router: { params: {} } })
    render(<OrderDetailPage />)
    await waitFor(() => expect(screen.getByTestId('order-detail-missing-id')).toBeTruthy())
    expect(mockGet).not.toHaveBeenCalled()
  })

  it('🔴 纯只读：源码（去注释）里没有任何工人面记号', () => {
    const src = stripComments(
      fs.readFileSync(path.join(__dirname, '../src/pages/production/order-detail/index.tsx'), 'utf8'),
    )
    ;[
      '扫一扫',
      '去登录工人身份',
      'scanResolve',
      'completeByScan',
      'getWorkerOrderOperations',
      'hasWorkerSession',
      'WORKER_TAB_LOGIN_ROUTE',
      'PRODUCTION_WORKER_LOGIN_REQUIRED',
      'workerSessionHeaders',
    ].forEach((token) => {
      expect({ token, present: src.includes(token) }).toEqual({ token, present: false })
    })
    // 反向自证：源码里**确实**在消费那两条只读读面（否则上面那串「都没出现」是空跑）
    expect(src).toContain('getProcessingOrderBrief(')
    expect(src).toContain('getOrderOperations(')
  })
})
