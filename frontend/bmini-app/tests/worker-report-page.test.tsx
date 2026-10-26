// case_ids: BM-014, BM-015, BM-025
/**
 * 工人**扫码报工页**判据（issue #7812 P2a；页面 = `src/pages/worker/report/index.tsx`）。
 *
 * 判据分两层：状态机的四条硬约束在 `tests/report-state.test.ts`（纯函数），本文件判**装配**——
 * 「同一份状态在屏幕上真的表现成那样」。每条都能单独变红：
 *
 * | # | 判据 | 红证 |
 * |---|---|---|
 * | ① | 未登录 ⇒ **没有报工按钮**，只有登录引导 | 把按钮渲染条件改成恒真 ⇒ 红 |
 * | ② | 工序未确定 ⇒ **没有报工按钮**（并说明为什么） | 同上 ⇒ 红 |
 * | ③ | 旧码 ⇒ 先出**套号清单**，不点就不出部位、也不出报工按钮；点第 2 套 ⇒ 才出部位 | 自动选第 1 套 ⇒ 红 |
 * | ④ | 报工后**只认回执**：显示服务端给的「下一道」，而不是自己猜 | 改成显示「下一道：定型」这类本地常量 ⇒ 红 |
 * | ⑤ | 401 ⇒ 引导登录（不当作"读不到/没工序"） | 把 401 渲染成一屏普通报工 ⇒ 红 |
 * | ⑥ | 提交在飞 ⇒ 按钮 disabled 且**只提交一次**（防连点记两笔计件） | 去掉 submitting 闸 ⇒ 红 |
 */
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

jest.mock('@tarojs/taro', () => {
  const store: Record<string, any> = {}
  return {
    __esModule: true,
    default: {
      showToast: jest.fn(),
      navigateTo: jest.fn(),
      scanCode: jest.fn(),
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
    useDidShow: jest.fn(),
  }
})

jest.mock('../src/services/workerService', () => ({
  fetchCurrentWorker: jest.fn(),
}))

// 报工写面 = **单一实现**（`services/productionService.ts`，守卫 production-single-write-entry）
jest.mock('../src/services/productionService', () => ({
  scanResolve: jest.fn(),
  completeByScan: jest.fn(),
}))

import Taro from '@tarojs/taro'
import WorkerReportPage from '../src/pages/worker/report/index'
import { fetchCurrentWorker } from '../src/services/workerService'
import { completeByScan, scanResolve } from '../src/services/productionService'
import { WORKER_TAB_LOGIN_ROUTE } from '../src/utils/inbound/gaps'
import { setWorkerSessionId } from '../src/utils/workerSession'
import type { ReportView } from '../src/utils/reportState'

const WORKER = { session_id: 's', worker_id: 'w-1', worker_no: 'G001', worker_name: '张三' }

const MAIN_VIEW: ReportView = {
  granularity: 'set_position',
  set_no: 2,
  position: { order_item_id: 'item-1', position_name: '布帘', position_kind: '布帘' },
  operation: { operation_id: 'op-1', logical_name: '车被', qty: 11, unit: '米' },
  alternatives: [],
  needs_selection: [],
  set_progress: { done: 1, total: 3 },
}

const NO_OPERATION_VIEW: ReportView = { ...MAIN_VIEW, operation: null, completed: true }

const LEGACY_VIEW: ReportView = {
  granularity: 'order',
  operation: null,
  needs_selection: [
    {
      set_id: 'set-1',
      set_no: 1,
      positions: [{ order_item_id: 'item-1', position_name: '布帘', position_kind: '布帘' }],
    },
    {
      set_id: 'set-2',
      set_no: 2,
      positions: [{ order_item_id: 'item-3', position_name: '纱帘', position_kind: '纱帘' }],
    },
  ],
}

const mockFetchWorker = fetchCurrentWorker as jest.Mock
const mockResolve = scanResolve as jest.Mock
const mockComplete = completeByScan as jest.Mock

async function bootLoggedIn() {
  setWorkerSessionId(WORKER.session_id)
  mockFetchWorker.mockResolvedValue({ success: true, data: WORKER })
  render(<WorkerReportPage />)
  await screen.findByText(/当前工人/)
}

/** 手输码 → 解析（不依赖小程序扫码弹窗，测试里也能跑）。 */
async function scanByManual(code: string) {
  fireEvent.change(screen.getByTestId('worker-report-manual'), { target: { value: code } })
  fireEvent.click(screen.getByTestId('worker-report-manual-submit'))
  await waitFor(() => expect(mockResolve).toHaveBeenCalled())
}

describe('扫码报工页（issue #7812）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    ;(Taro as any).__clearStorage()
  })

  it('① 未登录 ⇒ 没有报工按钮，只有登录引导', async () => {
    ;(Taro as any).__clearStorage()
    render(<WorkerReportPage />)
    expect(await screen.findByTestId('worker-report-login-required')).toBeTruthy()
    expect(screen.queryByTestId('worker-report-submit')).toBeNull()

    fireEvent.click(screen.getByTestId('worker-report-login'))
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: WORKER_TAB_LOGIN_ROUTE })
  })

  it('② 工序未确定 ⇒ 没有报工按钮，并说明原因', async () => {
    await bootLoggedIn()
    mockResolve.mockResolvedValue({ success: true, data: NO_OPERATION_VIEW })
    await scanByManual('ab12cd34')

    expect(await screen.findByTestId('worker-report-no-operation')).toBeTruthy()
    expect(screen.queryByTestId('worker-report-submit')).toBeNull()
  })

  it('③ 旧码 ⇒ 先出套号清单；点第 2 套才出部位，全程没有报工按钮', async () => {
    await bootLoggedIn()
    mockResolve.mockResolvedValue({ success: true, data: LEGACY_VIEW })
    await scanByManual('LEGACY-1')

    expect(await screen.findByTestId('worker-report-sets')).toBeTruthy()
    expect(screen.queryByTestId('worker-report-positions')).toBeNull()
    expect(screen.queryByTestId('worker-report-submit')).toBeNull()

    fireEvent.click(screen.getByTestId('worker-report-set-1')) // 第 2 套（index 1）
    expect(screen.getByTestId('worker-report-positions')).toBeTruthy()

    mockResolve.mockResolvedValue({ success: true, data: MAIN_VIEW })
    fireEvent.click(screen.getByTestId('worker-report-position-0'))
    await waitFor(() =>
      expect(mockResolve).toHaveBeenLastCalledWith('LEGACY-1', undefined, {
        setId: 'set-2',
        orderItemId: 'item-3',
      }),
    )
  })

  it('④ 报工 ⇒ 提交体正确，回执只显示服务端给的下一道', async () => {
    await bootLoggedIn()
    mockResolve.mockResolvedValue({ success: true, data: MAIN_VIEW })
    await scanByManual('ab12cd34')

    // 回执由**服务端**给（下面这道「定型」只存在于这一个 mock 里 —— 前端自己编不出来）
    mockComplete.mockResolvedValue({
      success: true,
      data: { next_operation: { operation_id: 'op-9', logical_name: '定型' }, set_completed: false },
    })
    fireEvent.click(await screen.findByTestId('worker-report-submit'))
    await waitFor(() => expect(mockComplete).toHaveBeenCalledTimes(1))
    expect(mockComplete).toHaveBeenCalledWith(
      'ab12cd34',
      'op-1',
      expect.any(String),
      expect.objectContaining({ qty: 11 }),
      null,
    )

    expect(await screen.findByTestId('worker-report-receipt')).toBeTruthy()
    expect(screen.getByTestId('worker-report-receipt').textContent).toContain('定型')
  })

  it('⑤ 401 ⇒ 回登录引导（不当作「没工序」）', async () => {
    await bootLoggedIn()
    mockResolve.mockResolvedValue({ success: false, statusCode: 401, message: '登录已失效' })
    await scanByManual('ab12cd34')

    expect(await screen.findByTestId('worker-report-login-required')).toBeTruthy()
    expect(screen.queryByTestId('worker-report-submit')).toBeNull()
  })

  it('⑥ 提交在飞 ⇒ 按钮 disabled，再点也不会提交第二次（防连点记两笔）', async () => {
    await bootLoggedIn()
    mockResolve.mockResolvedValue({ success: true, data: MAIN_VIEW })
    await scanByManual('ab12cd34')

    let release: (v: any) => void = () => {}
    mockComplete.mockImplementation(
      () => new Promise((resolve) => {
        release = resolve
      }),
    )
    const button = await screen.findByTestId('worker-report-submit')
    fireEvent.click(button)
    await waitFor(() => expect(mockComplete).toHaveBeenCalledTimes(1))

    fireEvent.click(button) // 连点
    expect(mockComplete).toHaveBeenCalledTimes(1)
    expect((button as any).disabled).toBe(true)

    release({ success: false, message: '网络超时' })
    await waitFor(() => expect((button as any).disabled).toBe(false))
  })
})
