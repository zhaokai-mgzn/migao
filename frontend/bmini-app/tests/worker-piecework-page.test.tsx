// case_ids: BM-054
/**
 * 工人**我的计件**页判据（issue #7934；页面 = `src/pages/worker/piecework/index.tsx`）。
 *
 * 口径真值 = docs/design/worker-home-menu.md §6.3（2026-10-12 裁定「金额给工人看」）六条。
 * 本文件把其中**会红的四条**钉在渲染结果上（每条都能单独变红）：
 *
 * | # | 判据 | 红证（怎么让它单独变红） |
 * |---|---|---|
 * | ① | 🔴 **金额 = 服务端读数**：`合计` 逐值渲染服务端 `amount_total`，**不**把 `lines[].amount` 加起来 | 端侧自己求和 ⇒ 屏上出现「行的和」而不是 `amount_total` ⇒ 红 |
 * | ② | 🔴 **未定价显式列出且不进合计**：「N 道未定价（未计入合计）」+ 逐条工序；合计仍是服务端的值 | 把未定价当 0 元 / 把它算进合计 ⇒ 红 |
 * | ③ | 🔴 **绝不印 ¥0.00**：一整月都是未定价时只出未定价块（不出「合计 ¥0.00」）；真有定价行才出合计 | 全未定价时印 `¥0.00` ⇒ 红 |
 * | ④ | **空态 = 读了、真没有**（≠ 读不到） | 把读失败渲染成 `EMPTY_HINT` ⇒ 红 |
 * | ⑤ | **读不到 / 形状不对** ⇒ 「读取失败，请重试」+ 重试（再读一次），**不**冒充空态或 0 元 | 失败走空态 / 静默忽略 ⇒ 红 |
 * | ⑥ | 🔴 **作用域只认会话**：请求只带 `month`（首屏不带参数），**绝不**带 worker_id / worker_name | 请求带身份参数 ⇒ 红 |
 * | ⑦ | **期间切换只按服务端给的 can_prev / can_next**（端侧不推算月份边界）；401 ⇒ 引导登录 | 端侧自己算上月 ⇒ 红 |
 * | ⑧ | **只读**：屏上只有 刷新 / 上月 / 下月 / 去登录 / 重试，没有任何写动作 | 加一个「确认 / 保存 / 结算」按钮 ⇒ 红 |
 *
 * 数据源真值：`GET /api/worker/piecework`（后端 `ProductionService.workerPieceworkLedger`，
 * 与 H5 `/b/report/piecework.html` 同一个端点）⇒ 本页只格式化，不聚合。
 */
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

jest.mock('@tarojs/taro', () => {
  const store: Record<string, any> = {}
  return {
    __esModule: true,
    default: {
      navigateTo: jest.fn(),
      redirectTo: jest.fn(),
      getStorageSync: jest.fn((key: string) => (key in store ? store[key] : '')),
      setStorageSync: jest.fn((key: string, value: any) => {
        store[key] = value
      }),
      removeStorageSync: jest.fn((key: string) => {
        delete store[key]
      }),
      __clearStorage: () => {
        Object.keys(store).forEach((key) => delete store[key])
      },
    },
  }
})

jest.mock('../src/services/workerPieceworkService', () => ({
  readWorkerPiecework: jest.fn(),
}))

import Taro from '@tarojs/taro'
import WorkerPieceworkPage, {
  EMPTY_HINT,
  LOGIN_REQUIRED,
  MISSING,
  READ_FAILED_HINT,
  formatQty,
  formatYuan,
  pieceworkModel,
  unpricedNotice,
} from '../src/pages/worker/piecework/index'
import { readWorkerPiecework } from '../src/services/workerPieceworkService'
import { WORKER_TAB_LOGIN_ROUTE } from '../src/utils/inbound/gaps'
import {
  clearWorkerSession,
  getWorkerSessionId,
  setWorkerSessionId,
} from '../src/utils/workerSession'

const mockRead = readWorkerPiecework as jest.Mock

/** 服务端读数（**合计 2000 ≠ 两行之和 1234.5** —— 这个差值是判据 ① 的判别力所在）。 */
const LEDGER = {
  worker_name: '张三',
  period: '2026-10',
  amount_total: 2000,
  qty_total: 12,
  lines: [
    { logical_name: '打褶', position: '布帘', qty: 10, amount: 1000 },
    { logical_name: '侧缝', position: '布帘', qty: 2, amount: 234.5 },
  ],
  unpriced: { qty: 0, operations: [] as any[] },
  prev_period: '2026-09',
  next_period: null,
  can_prev: true,
  can_next: false,
}

function loggedIn() {
  setWorkerSessionId('sess-piecework-1')
}

async function renderReady(data: any = LEDGER, waitTestId = 'worker-piecework-summary') {
  loggedIn()
  mockRead.mockResolvedValue({ success: true, data, message: '' })
  render(<WorkerPieceworkPage />)
  await screen.findByTestId(waitTestId)
  return screen
}

beforeEach(() => {
  jest.clearAllMocks()
  ;(Taro as any).__clearStorage()
  mockRead.mockResolvedValue({ success: true, data: LEDGER, message: '' })
})

describe('工人「我的计件」页（issue #7934）', () => {
  it('① 🔴 合计 = 服务端 amount_total（端侧不把 lines 加起来）', async () => {
    await renderReady()
    // 服务端给 2000；两行之和是 1234.5 —— 屏上必须只有前者
    expect(screen.getByText('合计 ¥2,000.00')).toBeTruthy()
    expect(screen.queryByText(/¥1,234\.50/)).toBeNull()
    // 逐笔照服务端给的行渲染（数量 + 金额）
    expect(screen.getByTestId('worker-piecework-line-0').textContent).toContain('打褶 · 布帘')
    expect(screen.getByTestId('worker-piecework-line-0').textContent).toContain('¥1,000.00')
    expect(screen.getByText('共 12 件')).toBeTruthy()
  })

  it('② 🔴 未定价显式列出、且不进合计（合计仍是服务端的值）', async () => {
    await renderReady({
      ...LEDGER,
      amount_total: 200,
      lines: [{ logical_name: '打褶', position: '布帘', qty: 10, amount: 200 }],
      unpriced: { qty: 3, operations: [{ logical_name: '卷边', qty: 3 }] },
    })
    expect(screen.getByTestId('worker-piecework-unpriced-count').textContent).toBe(
      unpricedNotice(1),
    )
    expect(screen.getByTestId('worker-piecework-unpriced').textContent).toContain('卷边 · 3 件')
    expect(screen.getByText('合计 ¥200.00')).toBeTruthy()
  })

  it('③ 🔴 一整月都是未定价 ⇒ 只出未定价块，**绝不**印 ¥0.00', async () => {
    await renderReady({
      ...LEDGER,
      amount_total: 0,
      qty_total: 0,
      lines: [],
      unpriced: { qty: 6, operations: [{ logical_name: '卷边', qty: 6 }] },
    }, 'worker-piecework-unpriced')
    const body = document.body.textContent ?? ''
    expect(body).not.toContain('¥0.00')
    expect(screen.queryByTestId('worker-piecework-summary')).toBeNull()
    expect(screen.getByTestId('worker-piecework-unpriced-count').textContent).toBe(unpricedNotice(1))
    // 也不是「这一月没干活」
    expect(screen.queryByTestId('worker-piecework-empty')).toBeNull()
  })

  it('④ 空态 = 读了、真没有（如实说，不印 0 元）', async () => {
    await renderReady(
      { ...LEDGER, amount_total: 0, qty_total: 0, lines: [], unpriced: { qty: 0, operations: [] } },
      'worker-piecework-empty',
    )
    expect(screen.getByTestId('worker-piecework-empty').textContent).toBe(EMPTY_HINT)
    expect(screen.queryByTestId('worker-piecework-summary')).toBeNull()
    expect(document.body.textContent ?? '').not.toContain('¥0.00')
  })

  it('⑤ 🔴 读不到 ⇒ 「读取失败，请重试」+ 重试（不冒充空态 / 不冒充 0 元）', async () => {
    loggedIn()
    mockRead.mockResolvedValueOnce({ success: false, message: '', statusCode: 500 })
    render(<WorkerPieceworkPage />)
    await screen.findByTestId('worker-piecework-error')
    expect(screen.getByTestId('worker-piecework-error').textContent).toContain(READ_FAILED_HINT)
    expect(screen.queryByTestId('worker-piecework-empty')).toBeNull()
    expect(document.body.textContent ?? '').not.toContain('¥0.00')

    mockRead.mockResolvedValueOnce({ success: true, data: LEDGER, message: '' })
    fireEvent.click(screen.getByTestId('worker-piecework-retry'))
    await waitFor(() => expect(mockRead).toHaveBeenCalledTimes(2))
    await screen.findByTestId('worker-piecework-summary')
  })

  it('⑤ 读数形状不对（成功但没有 amount_total）⇒ 也按「读不到」呈现', async () => {
    loggedIn()
    mockRead.mockResolvedValueOnce({ success: true, data: { period: '2026-10' }, message: '' })
    render(<WorkerPieceworkPage />)
    expect((await screen.findByTestId('worker-piecework-error')).textContent).toContain(READ_FAILED_HINT)
    expect(screen.queryByTestId('worker-piecework-empty')).toBeNull()
  })

  it('⑥ 🔴 请求只带 month（首屏不带参数），绝不带 worker_id / worker_name', async () => {
    await renderReady()
    // 首屏 = 服务端按业务当前自然月：一个参数都不传
    expect(mockRead.mock.calls[0]).toEqual([undefined])
    for (const call of mockRead.mock.calls) {
      expect(call.length).toBeLessThanOrEqual(1)
    }
  })

  it('⑦ 期间切换只按服务端给的 can_prev / prev_period（端侧不推算月份边界）', async () => {
    await renderReady()
    // can_next = false ⇒ 屏上没有「下月」
    expect(screen.queryByTestId('worker-piecework-next')).toBeNull()
    fireEvent.click(screen.getByTestId('worker-piecework-prev'))
    await waitFor(() => expect(mockRead).toHaveBeenLastCalledWith('2026-09'))
  })

  it('⑦ 401 ⇒ 引导登录（清本机工人身份，跳工人登录入口）', async () => {
    loggedIn()
    mockRead.mockResolvedValueOnce({ success: false, message: '未登录', statusCode: 401 })
    render(<WorkerPieceworkPage />)
    expect((await screen.findByTestId('worker-piecework-login-required')).textContent).toContain(
      LOGIN_REQUIRED,
    )
    expect(getWorkerSessionId()).toBeNull()
    fireEvent.click(screen.getByTestId('worker-piecework-login'))
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: WORKER_TAB_LOGIN_ROUTE })
  })

  it('⑧ 只读：屏上只有 刷新 / 上月（没有任何写动作）', async () => {
    await renderReady()
    const buttons = screen.getAllByRole('button').map((node) => (node.textContent ?? '').trim())
    expect(new Set(buttons)).toEqual(new Set(['刷新', '上月']))
    expect(document.body.textContent ?? '').not.toMatch(/确认|保存|提交|结算|锁定/)
  })

  it('展示函数：金额 / 件数缺值 ⇒ —（**绝不**回落成 ¥0.00 / 0）', () => {
    expect(formatYuan(1234.5)).toBe('¥1,234.50')
    expect(formatYuan('2000')).toBe('¥2,000.00')
    expect(formatYuan(null)).toBe(MISSING)
    expect(formatYuan(undefined)).toBe(MISSING)
    expect(formatQty(null)).toBe(MISSING)
    expect(formatQty(3)).toBe('3')
    // 形状不对 ⇒ 模型返回 null（页面据此走「读不到」）
    expect(pieceworkModel(null)).toBeNull()
    expect(pieceworkModel({ period: '2026-10' } as any)).toBeNull()
  })

  afterAll(() => {
    clearWorkerSession()
  })
})
