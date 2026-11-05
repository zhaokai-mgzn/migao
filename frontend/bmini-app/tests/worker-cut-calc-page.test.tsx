// case_ids: MC-222
/**
 * 工人端**裁高计算**页判据（issue #7813 P2b；页面 = `src/pages/worker/cut-calc/index.tsx`）。
 *
 * 判据分两层：数字口径与四条硬约束在 `tests/worker-read-faces.test.ts`（纯函数）；本文件判**装配** ——
 * 「同一份状态在屏幕上真的表现成那样」。每条都能单独变红：
 *
 * | # | 判据 | 红证 |
 * |---|---|---|
 * | ① | 大字 = 服务端算出的裁高（三位小数），**端侧不重算** | 页面改成自己把 `base + hits` 加起来 ⇒ 红 |
 * | ② | 未登录 ⇒ **屏上没有任何动作**（没有扫一扫 / 没有输入框），只有去登录 | 把扫码块渲染条件去掉 ⇒ 红 |
 * | ③ | 缺必需取值 ⇒ 明说缺什么，**不显示 0 / 上一件的值** | 把缺值渲染成 `0.000` ⇒ 红 |
 * | ④ | 「去报工」只把**这次扫到的码**交给报工页（不猜套 / 不猜工序） | 把套号 / 工序塞进 URL ⇒ 红 |
 * | ⑤ | 读失败 ≠ 空态：具名错误态 + 可重试 | 把失败渲染成空白 ⇒ 红 |
 * | ⑥ | 本页**没有写动作**（不报工、不写机器）：源码里不出现写入口 | 加一次 `completeByScan(` ⇒ 红 |
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

jest.mock('../src/services/workerCutService', () => ({
  fetchCuttingHeight: jest.fn(),
}))

// 扫码能力：本文件默认「小程序端可用」（`scanCode` 走得到）；另一条用例钉住「不可用 ⇒ 不摆按钮」
jest.mock('../src/utils/platform', () => ({
  canUseNativeScan: jest.fn(() => true),
  isH5: () => false,
  isWeapp: () => true,
}))

import Taro from '@tarojs/taro'
import WorkerCutCalcPage from '../src/pages/worker/cut-calc/index'
import { fetchCurrentWorker } from '../src/services/workerService'
import { fetchCuttingHeight } from '../src/services/workerCutService'
import { canUseNativeScan } from '../src/utils/platform'
import { setWorkerSessionId } from '../src/utils/workerSession'
import { CUT_CALC_PAGE_ROUTE, REPORT_PAGE_ROUTE, WORKER_LOGIN_ROUTE } from '../src/utils/inbound/gaps'

const WORKER = { session_id: 's', worker_id: 'w-1', worker_no: 'G001', worker_name: '张三' }

const DATA = {
  order: { order_no: 'SO-1', processing_order_no: 'JG-001', customer_name: '王女士', set_no: 2, set_count: 3 },
  positions: [
    {
      order_item_id: 'item-2',
      position_name: '纱帘',
      scanned: true,
      base: 2.7,
      cutting_height: 3.028,
      rounding: { mode: 'half_up', digits: 3 },
      hits: [{ key: 'hem', name: '卷边', value: 0.328, direction: 'add' }],
      misses: [],
      missing: [],
    },
  ],
  batch_required: false,
  batch_no: null,
}

const mockWorker = fetchCurrentWorker as jest.Mock
const mockCut = fetchCuttingHeight as jest.Mock
const mockNative = canUseNativeScan as jest.Mock

beforeEach(() => {
  jest.clearAllMocks()
  ;(Taro as any).__clearStorage?.()
  mockWorker.mockResolvedValue({ success: true, data: WORKER })
  mockNative.mockReturnValue(true)
})

const mountLoggedIn = async () => {
  setWorkerSessionId('s-1')
  render(<WorkerCutCalcPage />)
  await screen.findByTestId('worker-cut-calc-scan')
}

const scanByManual = async (code: string) => {
  fireEvent.change(screen.getByTestId('worker-cut-calc-manual'), { target: { value: code } })
  fireEvent.click(screen.getByTestId('worker-cut-calc-manual-submit'))
}

describe('② 未登录 ⇒ 屏上没有任何动作', () => {
  test('只有一句引导 + 去登录；没有扫一扫、没有输入框', async () => {
    render(<WorkerCutCalcPage />)
    expect(await screen.findByTestId('worker-cut-calc-login-required')).toBeTruthy()
    expect(screen.queryByTestId('worker-cut-calc-scan')).toBeNull()
    expect(screen.queryByTestId('worker-cut-calc-scan-button')).toBeNull()
    expect(screen.queryByTestId('worker-cut-calc-manual')).toBeNull()
  })

  test('去登录走工人登录页（不是商家登录页）', async () => {
    render(<WorkerCutCalcPage />)
    fireEvent.click(await screen.findByTestId('worker-cut-calc-login'))
    expect((Taro.navigateTo as jest.Mock).mock.calls[0][0].url).toBe(WORKER_LOGIN_ROUTE)
  })
})

describe('① 大字 = 服务端给的裁高值（端侧不重算）', () => {
  test('扫一次 ⇒ 部位 / 成品高 / 命中项 / 裁高大字', async () => {
    mockCut.mockResolvedValue({ success: true, data: DATA })
    await mountLoggedIn()
    await scanByManual('JG-001')

    expect((await screen.findByTestId('worker-cut-calc-height')).textContent).toContain('请在机器屏输入 3.028 米')
    expect((screen.getByTestId('worker-cut-calc-order')).textContent).toContain('JG-001')
    expect((screen.getByTestId('worker-cut-calc-hits')).textContent).toContain('卷边')
    expect((screen.getByTestId('worker-cut-calc-worker')).textContent).toContain('张三')
    expect(mockCut).toHaveBeenCalledWith('JG-001')
  })
})

describe('③ 缺必需取值 ⇒ 明说缺什么，不猜数', () => {
  test('missing 非空 ⇒ 大字说明算不出，且不出现 0.000', async () => {
    mockCut.mockResolvedValue({
      success: true,
      data: {
        ...DATA,
        positions: [
          { order_item_id: 'item-9', position_name: '帘头', scanned: true, base: null, cutting_height: null, missing: ['finished_height'] },
        ],
      },
    })
    await mountLoggedIn()
    await scanByManual('JG-001')

    const big = await screen.findByTestId('worker-cut-calc-height')
    expect((big).textContent).toContain('缺少finished_height')
    expect((big).textContent).toContain('算不出裁剪高度')
    expect(big.textContent).not.toContain('0.000')
  })
})

describe('④ 去报工只交这次扫到的码', () => {
  test('URL 带 t=<码>，不带套号 / 工序', async () => {
    mockCut.mockResolvedValue({ success: true, data: DATA })
    await mountLoggedIn()
    await scanByManual('  JG-001  ')
    fireEvent.click(await screen.findByTestId('worker-cut-calc-report'))

    const url = (Taro.navigateTo as jest.Mock).mock.calls[0][0].url as string
    expect(url).toBe(`${REPORT_PAGE_ROUTE}?t=JG-001`)
    expect(url).not.toContain('set_id')
    expect(url).not.toContain('operation_id')
  })
})

describe('⑤ 读失败 ≠ 空态', () => {
  test('失败 ⇒ 具名错误态 + 可重试；不显示空白的「一屏」', async () => {
    mockCut.mockResolvedValue({ success: false, message: '读取裁高失败，请重试' })
    await mountLoggedIn()
    await scanByManual('JG-404')

    expect((await screen.findByTestId('worker-cut-calc-read-failed')).textContent).toContain('读取裁高失败')
    expect(screen.queryByTestId('worker-cut-calc-card')).toBeNull()
    fireEvent.click(screen.getByTestId('worker-cut-calc-retry'))
    await waitFor(() => expect(screen.getByTestId('worker-cut-calc-scan')).toBeTruthy())
  })

  test('401 ⇒ 回未登录态（不当作「读不到」）', async () => {
    mockCut.mockResolvedValue({ success: false, message: '登录已失效', statusCode: 401 })
    await mountLoggedIn()
    await scanByManual('JG-001')
    expect(await screen.findByTestId('worker-cut-calc-login-required')).toBeTruthy()
  })
})

describe('扫码入口：没有原生扫码能力时不留死路', () => {
  test('canUseNativeScan 为假 ⇒ 不摆「扫一扫」，手输仍在', async () => {
    mockNative.mockReturnValue(false)
    await mountLoggedIn()
    expect(screen.queryByTestId('worker-cut-calc-scan-button')).toBeNull()
    expect(screen.getByTestId('worker-cut-calc-scan-entry-hint')).toBeTruthy()
    expect(screen.getByTestId('worker-cut-calc-manual')).toBeTruthy()
  })
})

describe('⑥ 本页没有写动作（只读面）', () => {
  test('源码里不出现任何报工 / 质检写入口（出现即红）', () => {
    const raw = fs.readFileSync(
      path.join(__dirname, '..', 'src', 'pages', 'worker', 'cut-calc', 'index.tsx'),
      'utf8',
    )
    // 只判**代码面**：注释里写「/w/ 的【完成】走 …/scan/complete」是留痕，不是调用点
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
    // 反向对照：页面确实在做「导航过去报工」这件事（不是把按钮删掉了事）
    expect(source).toContain('reportHandoffUrl(')
    expect(CUT_CALC_PAGE_ROUTE).toBe('/pages/worker/cut-calc/index')
  })
})
