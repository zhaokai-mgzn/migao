// case_ids: BM-040
/**
 * 「加工单详情」页的**卡点块**（issue #6597 缺陷 B）
 *
 * ## 治的形态
 *
 * 商家从「数据」页点一张「卡在哪」待办进这一页，看到的是**工序进度**，看不到**这一单卡在哪**
 * —— 判据本体（谁卡了 / 等了多久 / 阈值多少 / 阈值从哪来）服务端早就算好了
 * （`GET /api/admin/production/stuck-points?processing_order_id=…`，
 * `backend/admin-api/src/main/java/com/migao/admin/service/ProductionStuckPointService.java`），
 * 这一页从未读它 ⇒ 商家点进来仍是「看不出卡在哪」。
 *
 * ## 六条判据（红证 = 怎么让它单独变红）
 *
 * | # | 判据 | 红证 |
 * |---|---|---|
 * | 1 | 有卡点 ⇒ 逐条渲染**工序显示名 + 等了多久 + 阈值与来源** | 删掉卡点块 ⇒ `getByTestId` 取不到 ⇒ 红 |
 * | 2 | 🔴 三串读数**逐字等于** mock 响应里的服务端值 | 前端自己 `toFixed(1)` 重算/换阈值口径 ⇒ 值对不上 ⇒ 红 |
 * | 3 | 🔴 有卡点 ⇒ 抬头只渲一条服务端标量（不随卡点数增长） | 抬头按 `stuck` 逐条展开 ⇒ 条数 > 1 ⇒ 红 |
 * | 4 | 无卡点（`stuck:[]`）⇒ 整块**不渲染**（`queryByTestId` 为 null） | 摆「暂无卡点」空壳 ⇒ 取得到 ⇒ 红 |
 * | 5 | 🔴 卡点面失败 ⇒ 工序进度照旧 + 卡点块一句提示，整页不报错 | 让卡点失败把整页判成 `error` ⇒ 进度块消失 ⇒ 红 |
 * | 6 | 🔴 前端**不重算**：源码（去注释）里没有阈值比较 / 等待时长算式 | 注入 `stalled_hours > threshold_hours` ⇒ 红 |
 */
import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
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

import { get, post } from '../src/utils/request'
import OrderDetailPage from '../src/pages/production/order-detail/index'
import { getStuckPoints } from '../src/services/stuckPointService'
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

/**
 * 卡点面桩（**逐字照服务端响应形状**：
 * `ProductionStuckPointService#report` 的 `mode / threshold_hours / threshold_source / stuck_total / stuck[]`）。
 * 读数刻意不是整数：`stalled_hours: 6.5` —— 前端若自己 `toFixed(1)` 重算就会露出第二份口径。
 */
const STUCK = {
  success: true,
  data: {
    mode: 'A',
    threshold_hours: 4,
    threshold_source: 'default',
    stuck_total: 1,
    stuck: [
      {
        kind: 'not_started',
        processing_order_id: 'order-1',
        set_id: 'set-1',
        set_no: 'T1',
        position: { order_item_id: 'item-1', position_name: '布帘' },
        operation: { operation_id: 'op-2', logical_name: '车缝', position: '布帘', seq: 2, qty: 6, done_qty: 0 },
        predecessor: { operation_id: 'op-1', logical_name: '精裁', seq: 1, done_at: '2026-10-08T10:00:00+08:00' },
        stalled_hours: 6.5,
        threshold_hours: 4,
        threshold_source: 'default',
      },
    ],
  },
}

/** 按 URL 分派桩响应（三条读面各自独立，便于单条失败/403 的用例） */
function stub(props: { brief?: any; operations?: any; stuck?: any; stuckError?: any } = {}) {
  mockGet.mockImplementation((url: string) => {
    if (url.includes('/api/admin/production/stuck-points')) {
      return props.stuckError ? Promise.reject(props.stuckError) : Promise.resolve(props.stuck ?? STUCK)
    }
    if (url.includes('/api/admin/processing-orders/')) {
      return Promise.resolve(props.brief ?? BRIEF)
    }
    if (url.includes('/operations')) {
      return Promise.resolve(props.operations ?? OPERATIONS)
    }
    return Promise.reject(new Error(`未桩住的端点：${url}`))
  })
}

describe('加工单详情页 · 「卡在哪」块（issue #6597）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    stub()
  })

  it('🔴 有卡点 ⇒ 工序显示名 + 等待时长 + 阈值来源都来自服务端响应', async () => {
    render(<OrderDetailPage />)
    await waitFor(() => expect(screen.getByTestId('order-detail-stuck')).toBeTruthy())

    // 工序显示名走唯一口径（响应里 operation{logical_name, position} ⇒ `车缝 · 布帘`）
    expect(screen.getByText('车缝 · 布帘')).toBeTruthy()
    // 读数逐字来自响应（6.5 小时 / 阈值 4 小时 / 来源 default）—— 前端只展示、不重算
    expect(screen.getByTestId('order-detail-stuck-row').textContent).toContain('6.5 小时')
    expect(screen.getByTestId('order-detail-stuck').textContent).toContain('超过 4 小时')
    expect(screen.getByTestId('order-detail-stuck').textContent).toContain('系统兜底默认值')
  })

  it('🔴 三串读数逐字等于 mock 响应里的服务端值（前端不重算 —— 换口径必红）', async () => {
    // 反空跑：先把桩数值换成另一组（前端若照搬就会跟着变，若自己算就会钉在旧值）
    stub({
      stuck: {
        success: true,
        data: {
          ...STUCK.data,
          threshold_hours: 7,
          threshold_source: 'history',
          stuck: [{ ...STUCK.data.stuck[0], stalled_hours: 9.25, threshold_hours: 7, threshold_source: 'history' }],
        },
      },
    })
    render(<OrderDetailPage />)
    await waitFor(() => expect(screen.getByTestId('order-detail-stuck')).toBeTruthy())

    const block = screen.getByTestId('order-detail-stuck').textContent ?? ''
    expect(block).toContain('9.25 小时')
    expect(block).toContain('超过 7 小时')
    expect(block).toContain('历史中位数')
  })

  it('🔴 常驻面克制：抬头只渲一条（不随卡点数增长），逐条读数各一行', async () => {
    const rows = [
      { ...STUCK.data.stuck[0], operation: { ...STUCK.data.stuck[0].operation, operation_id: 'op-2', logical_name: '车缝' } },
      { ...STUCK.data.stuck[0], operation: { ...STUCK.data.stuck[0].operation, operation_id: 'op-3', logical_name: '整烫' }, stalled_hours: 5.5 },
    ]
    stub({ stuck: { success: true, data: { ...STUCK.data, stuck_total: 2, stuck: rows } } })
    render(<OrderDetailPage />)
    await waitFor(() => expect(screen.getAllByTestId('order-detail-stuck-row')).toHaveLength(2))

    const block = screen.getByTestId('order-detail-stuck').textContent ?? ''
    expect(block).toContain('这单有 2 道')
    // 抬头里的「超过 N 小时」只出现一次（两条卡点不各念一遍阈值）
    expect((block.match(/超过/g) ?? []).length).toBe(1)
  })

  it('🔴 没有卡点 ⇒ 整块不渲染（不摆「暂无卡点」空壳）', async () => {
    stub({ stuck: { success: true, data: { ...STUCK.data, stuck_total: 0, stuck: [] } } })
    render(<OrderDetailPage />)
    await waitFor(() => expect(screen.getByTestId('order-detail-operations')).toBeTruthy())

    expect(screen.queryByTestId('order-detail-stuck')).toBeNull()
    expect(screen.queryByTestId('order-detail-stuck-row')).toBeNull()
  })

  it('🔴 卡点面失败 ⇒ 工序进度照旧 + 卡点块一句可行动提示，整页**不**判成失败', async () => {
    stub({ stuckError: new Error('boom') })
    render(<OrderDetailPage />)
    await waitFor(() => expect(screen.getByTestId('order-detail-stuck-hint')).toBeTruthy())

    // 工序进度照常（卡点面单独失败不拖垮整页）
    expect(screen.getByTestId('order-detail-progress').textContent).toContain('已完成 1/1')
    expect(screen.getByTestId('order-detail-operations')).toBeTruthy()
    // 整页**不是**错误态：没有整页错误块、也没有「还没有加工单」
    expect(screen.queryByTestId('order-detail-error')).toBeNull()
    expect(screen.queryByTestId('order-detail-no-processing-order')).toBeNull()
    expect(screen.queryByTestId('order-detail-stuck-row')).toBeNull()
  })

  it('🔴 纯只读：本页只发 GET（新增的卡点面不得带来任何写请求）', async () => {
    render(<OrderDetailPage />)
    await waitFor(() => expect(screen.getByTestId('order-detail-stuck')).toBeTruthy())

    expect(mockGet).toHaveBeenCalled()
    expect(post as unknown as jest.Mock).not.toHaveBeenCalled()
    const urls = mockGet.mock.calls.map((call) => String(call[0]))
    expect(urls.some((url) => url.includes('stuck-points'))).toBe(true)
  })

  it('🔴 前端**不重算**卡点：源码（去注释）里没有阈值比较 / 等待时长算式', () => {
    const src = stripComments(
      fs.readFileSync(path.join(__dirname, '../src/pages/production/order-detail/index.tsx'), 'utf8'),
    )
    const stuckSrc = stripComments(
      fs.readFileSync(path.join(__dirname, '../src/services/stuckPointService.ts'), 'utf8'),
    )
    ;[
      'stalled_hours >',
      'stalled_hours <',
      'threshold_hours >',
      'threshold_hours <',
      'Date.now()',
      'new Date(',
    ].forEach((token) => {
      expect({ where: 'page', token, present: src.includes(token) }).toEqual({ where: 'page', token, present: false })
      expect({ where: 'service', token, present: stuckSrc.includes(token) }).toEqual({ where: 'service', token, present: false })
    })
    // 反向自证：真的读了服务端下发的读数（否则上面那串「都没出现」是空跑）
    expect(src).toContain('getStuckPoints(')
    expect(src).toContain('stalled_hours')
    expect(src).toContain('threshold_hours')
  })

  it('服务层：卡点面是只读三态，403 与「空」可区分（空 = ok + stuck:[]）', async () => {
    await expect(getStuckPoints('order-1')).resolves.toMatchObject({ status: 'ok' })

    mockGet.mockImplementation(async (url: string) => {
      expect(String(url)).toContain('processing_order_id=order-1')
      return { success: true, data: { ...STUCK.data, stuck_total: 0, stuck: [] } }
    })
    await expect(getStuckPoints('order-1')).resolves.toMatchObject({ status: 'ok' })

    mockGet.mockImplementation(async () => {
      throw Object.assign(new Error('403'), { statusCode: 403 })
    })
    await expect(getStuckPoints('order-1')).resolves.toEqual({ status: 'forbidden' })

    mockGet.mockImplementation(async () => {
      throw new Error('network down')
    })
    await expect(getStuckPoints('order-1')).resolves.toEqual({ status: 'error' })
  })
})
