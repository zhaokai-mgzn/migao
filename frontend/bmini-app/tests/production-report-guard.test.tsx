// case_ids: BM-006
/**
 * 报工双击/重试防护测试（issue #4116 §5-1，M4-G-3 前端侧）。
 *
 * ## 病灶
 * 工人在扫工页手快连点两次「完成报工」⇒ `handleReport` 并发进入两次 ⇒ 发出**两个**报工请求
 * ⇒ 一次报工被记两遍（`done_qty` 翻倍、计件虚高）。原实现既无 in-flight 锁也无 disabled
 * （前端零防护），服务端幂等键也挡不住 —— 连点产生的是**两个不同的幂等键**。
 *
 * ## 本文件锁三条（每条都有红证）
 * ① 连点两次 ⇒ `reportOperation` 只被调用**一次**（in-flight 锁）；
 * ② 报工在飞期间该按钮 `disabled`（可见面防护，工人点不动）；
 * ③ 报工结束（含失败）⇒ 锁释放、按钮恢复可点（一次网络异常不得把按钮永久锁死）。
 *
 * 另有一条：`reportOperation` 必须带幂等键请求头（服务端同键重放的前提）——
 * 见 `productionService.test.ts`（网络层，本文件 mock 掉服务层故测不到）。
 */
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

jest.mock('@tarojs/taro', () => ({
  __esModule: true,
  default: {
    scanCode: jest.fn(),
    showToast: jest.fn(),
    navigateTo: jest.fn(),
    getStorageSync: jest.fn(() => ''),
    setStorageSync: jest.fn(),
    removeStorageSync: jest.fn(),
  },
  useDidShow: jest.fn(),
}))

jest.mock('../src/services/productionService', () => ({
  ...jest.requireActual('../src/services/productionService'),
  getOrderOperations: jest.fn(),
  reportOperation: jest.fn(),
  // 锁用**真身**（不 mock）：本文件的判据就是「锁真的挡住了第二笔」
}))

jest.mock('../src/store/authStore', () => ({
  useAuthStore: jest.fn(() => ({
    user: { id: 'u1', nickname: '张师傅', avatar: null, tenantId: 1, role: 'operator' },
  })),
}))

import Taro from '@tarojs/taro'
import ProductionPage from '../src/pages/production/index/index'
import {
  getOrderOperations,
  reportInFlightLock,
  reportOperation,
} from '../src/services/productionService'
import type { OrderOperations } from '../src/services/productionService'

const ORDER_ID = 'CSO260915-02615'

function makeDetail(): OrderOperations {
  return {
    order_id: ORDER_ID,
    qr_token: 'qr-token-1',
    positions: [
      {
        position_name: '布帘',
        operations: [
          {
            id: 'op1', seq: 1, operation: '精裁', group: '裁剪', unit: '米',
            qty: 11, unit_price: 3.5, factor: 1, is_must_finish: false,
            is_start_marker: true, status: 'done', done_qty: 11,
          },
          {
            id: 'op2', seq: 2, operation: '韩褶', group: '车位', unit: '米',
            qty: 11, unit_price: 5, factor: 1, is_must_finish: true,
            is_start_marker: false, status: 'pending', done_qty: 0,
          },
        ],
      },
    ],
    progress: { total: 2, done: 1, percent: 50 },
  }
}

const mockGet = getOrderOperations as jest.Mock
const mockReport = reportOperation as jest.Mock

/** 手动可控的 deferred（用于把请求悬停在「在飞」状态） */
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

/** 打开扫码页并等列表渲染完成 */
async function openPage() {
  render(<ProductionPage />)
  fireEvent.click(screen.getByText('扫一扫'))
  await screen.findByText('韩褶')
}

describe('ProductionPage 报工防连点（issue #4116 §5-1）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    // 锁是模块级单例：上一用例若把请求悬停在在飞状态，锁会残留 ⇒ 用例间必须复位
    reportInFlightLock.release()
    ;(Taro.scanCode as jest.Mock).mockResolvedValue({ result: ORDER_ID })
    mockGet.mockResolvedValue({ success: true, data: makeDetail() })
    mockReport.mockResolvedValue({
      success: true,
      data: { operation_id: 'op2', done_qty: 11, status: 'done', order_completed: false },
    })
  })

  it('连点三次「完成报工」⇒ 只发出一次报工请求（锁本身，非靠 disabled 代偿）', async () => {
    const pending = deferred<any>()
    mockReport.mockReturnValue(pending.promise)
    await openPage()

    const button = screen.getAllByText('完成报工')[0]
    // 为什么用**原生 dispatchEvent 连续同步派发**（而不是 3 次 fireEvent.click）：
    //   ① `fireEvent` 内部包 act() ⇒ 第一次点击后 React 已把按钮刷成 disabled，
    //      而 jsdom/浏览器都会跳过 disabled 元素上的点击 ⇒ 后续点击根本到不了
    //      `handleReport` ⇒ 断言被 disabled 代偿（实测：把锁整个拔掉，这条照样绿）；
    //   ② 原生派发不经 act() ⇒ React 18 的自动批处理把 state 更新推迟到处理器之后，
    //      三次点击都在同一个同步段内到达 ⇒ **唯一**能挡住第 2/3 次的只有锁本身。
    // 实测判别性：拔掉 `tryAcquire` 后，本用例收到 3 次调用（红）。
    for (let i = 0; i < 3; i += 1) {
      button.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
    }

    expect(mockReport).toHaveBeenCalledTimes(1)

    pending.resolve({
      success: true,
      data: { operation_id: 'op2', done_qty: 11, status: 'done', order_completed: false },
    })
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2))
    // 结束之后锁释放：仍是一次调用（没有排队的第二个请求被补发）
    expect(mockReport).toHaveBeenCalledTimes(1)
  })

  it('报工在飞期间按钮 disabled（工人点不动）且文案切换为「报工中…」', async () => {
    const pending = deferred<any>()
    mockReport.mockReturnValue(pending.promise)
    await openPage()

    fireEvent.click(screen.getAllByText('完成报工')[0])

    const inFlight = await screen.findByText('报工中…')
    expect(inFlight.closest('button')?.hasAttribute('disabled')).toBe(true)

    pending.resolve({
      success: true,
      data: { operation_id: 'op2', done_qty: 11, status: 'done', order_completed: false },
    })
    // 结束后恢复可点（锁已释放）
    await waitFor(() => expect(screen.getAllByText('完成报工').length).toBeGreaterThan(0))
  })

  it('报工失败（success=false）⇒ 锁释放，按钮可再次点击（不永久锁死）', async () => {
    mockReport.mockResolvedValueOnce({ success: false, message: '前道工序「精裁」尚未完成' })
    await openPage()

    fireEvent.click(screen.getAllByText('完成报工')[0])
    expect(await screen.findByText('前道工序「精裁」尚未完成')).toBeTruthy()

    // 失败后再点 ⇒ 真的会再发一次（锁只在 in-flight 期间生效）
    mockReport.mockResolvedValueOnce({
      success: true,
      data: { operation_id: 'op2', done_qty: 11, status: 'done', order_completed: false },
    })
    fireEvent.click(screen.getAllByText('完成报工')[0])
    await waitFor(() => expect(mockReport).toHaveBeenCalledTimes(2))
  })
})