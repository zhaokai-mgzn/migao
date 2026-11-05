// case_ids: MC-222
/**
 * 工人端**精裁清单**页判据（issue #7813 P2b；页面 = `src/pages/worker/cut-plan/index.tsx`）。
 *
 * 判据分两层：判据与格式化在 `tests/worker-read-faces.test.ts`（纯函数）；本文件判**装配**。
 * 每条都能单独变红：
 *
 * | # | 判据 | 红证 |
 * |---|---|---|
 * | ① | 🔴 旧码 ⇒ 先出**套号清单**，不点就不出部位、也**不出任何裁片**；点第 2 套才出部位 | 解析完直接渲染裁片（默认取第 1 套）⇒ 红 |
 * | ② | 选完套 + 部位 ⇒ 带着 selection 重新解析，显示这一套的裁片（裁多长 × 几片 / 用料 / 批次） | 不重新解析（沿用旧一屏）⇒ 红 |
 * | ③ | 工序未确定 ⇒ 明说「这道工序还没定」；**没有报工按钮**（只有导航去报工） | 把「去报工」改成直接提交 / 把提示删掉 ⇒ 红 |
 * | ④ | `cut_plan` 为空 ⇒ **具名空态**（不是空白、不是假行） | 渲染一行「裁 — × —」 ⇒ 红 |
 * | ⑤ | 未登录 ⇒ 没有任何动作，只有去登录 | 去掉身份分流 ⇒ 红 |
 * | ⑥ | 本页没有写动作（源码里不出现写入口） | 加一次 `completeByScan(` ⇒ 红 |
 */
import fs from 'fs'
import path from 'path'
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

jest.mock('@tarojs/taro', () => {
  const store: Record<string, any> = {}
  return {
    __esModule: true,
    default: {
      showToast: jest.fn(),
      navigateTo: jest.fn(() => Promise.resolve()),
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

jest.mock('../src/services/productionService', () => ({
  scanResolve: jest.fn(),
}))

jest.mock('../src/utils/platform', () => ({
  canUseNativeScan: jest.fn(() => true),
  isH5: () => false,
  isWeapp: () => true,
}))

import Taro from '@tarojs/taro'
import WorkerCutPlanPage from '../src/pages/worker/cut-plan/index'
import { fetchCurrentWorker } from '../src/services/workerService'
import { scanResolve } from '../src/services/productionService'
import { setWorkerSessionId } from '../src/utils/workerSession'
import { REPORT_PAGE_ROUTE, WORKER_LOGIN_ROUTE } from '../src/utils/inbound/gaps'

const WORKER = { session_id: 's', worker_id: 'w-1', worker_no: 'G001', worker_name: '张三' }

/** 服务端降级响应的真形态（`ProductionScanService#degradedView`）。 */
const LEGACY = {
  granularity: 'order',
  order_id: 'o-1',
  processing_order_no: 'JG-001',
  set_no: null,
  operation: null,
  alternatives: [],
  needs_selection: ['set', 'position'],
  selections: [
    { set_id: 'set-1', set_no: 1, positions: [{ order_item_id: 'item-1', position_name: '布帘' }] },
    { set_id: 'set-2', set_no: 2, positions: [{ order_item_id: 'item-3', position_name: '纱帘' }] },
  ],
}

/** 选完套 + 部位后的一屏（带本套精裁清单）。 */
const READY = {
  granularity: 'set_position',
  order_id: 'o-1',
  processing_order_no: 'JG-001',
  set_no: '2',
  position: { order_item_id: 'item-3', position_name: '纱帘' },
  operation: { operation_id: 'op-1', logical_name: '裁剪', qty: 2, unit: '片' },
  alternatives: [],
  needs_selection: [],
  set_overview: {
    set_no: '2',
    positions: [],
    cut_plan: [
      {
        order_item_id: 'item-3',
        position_name: '纱帘',
        component: '左片',
        panel_length_m: 6.15,
        panel_count: 2,
        fabric_meters: 12.3,
        batch_no: 'PC-01',
        batch_meters: 12.3,
      },
    ],
  },
}

const mockWorker = fetchCurrentWorker as jest.Mock
const mockResolve = scanResolve as jest.Mock

beforeEach(() => {
  jest.clearAllMocks()
  ;(Taro as any).__clearStorage?.()
  mockWorker.mockResolvedValue({ success: true, data: WORKER })
})

const mountLoggedIn = async () => {
  setWorkerSessionId('s-1')
  render(<WorkerCutPlanPage />)
  await screen.findByTestId('worker-cut-plan-scan')
}

const scanByManual = async (code: string) => {
  fireEvent.change(screen.getByTestId('worker-cut-plan-manual'), { target: { value: code } })
  fireEvent.click(screen.getByTestId('worker-cut-plan-manual-submit'))
}

describe('① 旧码 ⇒ 先选套再选部位，绝不默认取第 1 套', () => {
  test('旧码 ⇒ 出套号清单；裁片**一个都不显示**，也没有报工按钮', async () => {
    mockResolve.mockResolvedValue({ success: true, data: LEGACY })
    await mountLoggedIn()
    await scanByManual('LEGACY-1')

    expect(await screen.findByTestId('worker-cut-plan-sets')).toBeTruthy()
    expect(screen.getByTestId('worker-cut-plan-set-0')).toBeTruthy()
    expect(screen.getByTestId('worker-cut-plan-set-1')).toBeTruthy()
    // ①：没点套之前，部位不出现、卡片（裁片）不出现
    expect(screen.queryByTestId('worker-cut-plan-positions')).toBeNull()
    expect(screen.queryByTestId('worker-cut-plan-card')).toBeNull()
    expect(screen.queryByText(/裁 6\.150 米/)).toBeNull()
    // ②：屏上没有任何「报工」提交按钮（只有导航去报工，且此刻还没到 ready）
    expect(screen.queryByRole('button', { name: '报工' })).toBeNull()
  })

  test('点第 2 套 ⇒ 才出部位；点部位 ⇒ 带着 selection 重新解析', async () => {
    mockResolve.mockResolvedValueOnce({ success: true, data: LEGACY })
    await mountLoggedIn()
    await scanByManual('LEGACY-1')

    fireEvent.click(await screen.findByTestId('worker-cut-plan-set-1'))
    expect(screen.getByTestId('worker-cut-plan-positions')).toBeTruthy()
    expect(screen.getByTestId('worker-cut-plan-position-0')).toBeTruthy()

    mockResolve.mockResolvedValueOnce({ success: true, data: READY })
    fireEvent.click(screen.getByTestId('worker-cut-plan-position-0'))

    expect(await screen.findByTestId('worker-cut-plan-card')).toBeTruthy()
    expect(mockResolve).toHaveBeenLastCalledWith('LEGACY-1', undefined, {
      setId: 'set-2',
      orderItemId: 'item-3',
    })
  })
})

describe('② 裁片逐条搬：裁多长 × 几片 / 用料 / 批次', () => {
  test('新码 ⇒ 直接出这一套的裁片行', async () => {
    mockResolve.mockResolvedValue({ success: true, data: READY })
    await mountLoggedIn()
    await scanByManual('JG-001')

    const rows = await screen.findByTestId('worker-cut-plan-rows')
    expect(rows.textContent).toContain('裁 6.150 米 × 2 片')
    expect(rows.textContent).toContain('纱帘 · 左片')
    expect(rows.textContent).toContain('用料 12.300 米')
    expect(screen.getByTestId('worker-cut-plan-batch').textContent).toContain('批次 PC-01')
    expect(screen.getByTestId('worker-cut-plan-piece').textContent).toContain('第 2 套')
    expect(screen.getByTestId('worker-cut-plan-worker').textContent).toContain('张三')
  })
})

describe('③ 工序未确定 ⇒ 明说 + 没有报工按钮', () => {
  test('operation 为 null ⇒ 提示「这道工序还没定」，屏上仍只有导航去报工', async () => {
    mockResolve.mockResolvedValue({ success: true, data: { ...READY, operation: null } })
    await mountLoggedIn()
    await scanByManual('JG-001')

    expect((await screen.findByTestId('worker-cut-plan-operation-hint')).textContent).toContain(
      '这道工序还没定',
    )
    expect(screen.queryByRole('button', { name: '报工' })).toBeNull()
    // 导航去报工只交码（④）：不猜套 / 不猜工序
    fireEvent.click(screen.getByTestId('worker-cut-plan-report'))
    const url = (Taro.navigateTo as jest.Mock).mock.calls[0][0].url as string
    expect(url).toBe(`${REPORT_PAGE_ROUTE}?t=JG-001`)
    expect(url).not.toContain('operation_id')
  })
})

describe('④ cut_plan 为空 ⇒ 具名空态（不是空白、不是假行）', () => {
  test('没有裁片 ⇒ 说清「这一套没有精裁输出」，且不渲染任何行', async () => {
    mockResolve.mockResolvedValue({ success: true, data: { ...READY, set_overview: { set_no: '2', positions: [], cut_plan: [] } } })
    await mountLoggedIn()
    await scanByManual('JG-001')

    const empty = await screen.findByTestId('worker-cut-plan-empty')
    expect(empty.textContent).toContain('没有精裁输出')
    expect(screen.queryByTestId('worker-cut-plan-rows')).toBeNull()
  })
})

describe('⑤ 未登录 ⇒ 没有任何动作', () => {
  test('只有去登录，没有扫一扫 / 输入框', async () => {
    render(<WorkerCutPlanPage />)
    expect(await screen.findByTestId('worker-cut-plan-login-required')).toBeTruthy()
    expect(screen.queryByTestId('worker-cut-plan-scan')).toBeNull()
    fireEvent.click(screen.getByTestId('worker-cut-plan-login'))
    expect((Taro.navigateTo as jest.Mock).mock.calls[0][0].url).toBe(WORKER_LOGIN_ROUTE)
  })
})

describe('⑥ 本页没有写动作（只读面）', () => {
  test('源码里不出现任何报工 / 质检写入口（出现即红）', () => {
    const raw = fs.readFileSync(
      path.join(__dirname, '..', 'src', 'pages', 'worker', 'cut-plan', 'index.tsx'),
      'utf8',
    )
    const source = raw
      .split('\n')
      .map((line) => {
        const trimmed = line.trimStart()
        return trimmed.startsWith('//') || trimmed.startsWith('*') || trimmed.startsWith('/*') ? '' : line
      })
      .join('\n')
    for (const forbidden of ['completeByScan(', 'reportOperationFree(', 'createQuality(', 'scan/complete']) {
      expect(source).not.toContain(forbidden)
    }
    expect(source).toContain('reportHandoffUrl(')
  })
})
