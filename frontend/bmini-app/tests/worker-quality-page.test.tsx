// case_ids: MC-226
/**
 * 工人端**质检记录**页判据（issue #7813 P2b；页面 = `src/pages/worker/quality/index.tsx`）。
 *
 * 判据分两层：状态词与空态在 `tests/worker-read-faces.test.ts`（纯函数）；本文件判**装配**。
 * 每条都能单独变红：
 *
 * | # | 判据 | 红证 |
 * |---|---|---|
 * | ① | 旧码 ⇒ 先选套 + 部位，选完才按「这一件」读记录（多套同部位不能串） | 解析完直接按部位行读（默认第 1 套）⇒ 红 |
 * | ② | 🔴 读失败 ⇒ 屏上说「未读到」，**绝不说「正常」**；空态只在真的读到「没有记录」时出现 | 把失败并进「正常」⇒ 红 |
 * | ③ | 403（未开通「质检」）⇒ **可行动**提示（找管理员），不说成「没有记录」 | 把 403 当空态 ⇒ 红 |
 * | ④ | 记录行：结果词 + 原因 + 检验人（服务端字段原样，端侧不聚合） | 端侧自己按 result 分组合并 ⇒ 红 |
 * | ⑤ | 工序未确定 ⇒ 明说；屏上**没有写动作**（不记返工、不复检） | 加一个「记返工」按钮 ⇒ 红 |
 * | ⑥ | 未登录 ⇒ 没有任何动作，只有去登录 | 去掉身份分流 ⇒ 红 |
 */
import fs from 'fs'
import path from 'path'
import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'

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

jest.mock('../src/services/workerQualityService', () => ({
  fetchQualityLatest: jest.fn(),
}))

jest.mock('../src/utils/platform', () => ({
  canUseNativeScan: jest.fn(() => true),
  isH5: () => false,
  isWeapp: () => true,
}))

import Taro from '@tarojs/taro'
import WorkerQualityPage from '../src/pages/worker/quality/index'
import { fetchCurrentWorker } from '../src/services/workerService'
import { scanResolve } from '../src/services/productionService'
import { fetchQualityLatest } from '../src/services/workerQualityService'
import { setWorkerSessionId } from '../src/utils/workerSession'
import { QUALITY_NOT_ENABLED_HINT, QUALITY_EMPTY_HINT } from '../src/utils/workerReadFaces'
import { WORKER_LOGIN_ROUTE } from '../src/utils/inbound/gaps'

const WORKER = { session_id: 's', worker_id: 'w-1', worker_no: 'G001', worker_name: '张三' }

const READY = {
  granularity: 'set_position',
  order_id: 'o-1',
  processing_order_no: 'JG-001',
  set_no: '2',
  position: { order_item_id: 'item-3', position_name: '纱帘' },
  operation: { operation_id: 'op-9', logical_name: '质检', qty: 1, unit: '件' },
  alternatives: [],
  needs_selection: [],
}

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

const mockWorker = fetchCurrentWorker as jest.Mock
const mockResolve = scanResolve as jest.Mock
const mockQuality = fetchQualityLatest as jest.Mock

beforeEach(() => {
  jest.clearAllMocks()
  ;(Taro as any).__clearStorage?.()
  mockWorker.mockResolvedValue({ success: true, data: WORKER })
})

const mountLoggedIn = async () => {
  setWorkerSessionId('s-1')
  render(<WorkerQualityPage />)
  await screen.findByTestId('worker-quality-scan')
}

const scanByManual = async (code: string) => {
  fireEvent.change(screen.getByTestId('worker-quality-manual'), { target: { value: code } })
  fireEvent.click(screen.getByTestId('worker-quality-manual-submit'))
}

describe('② 状态词只认服务端：读失败绝不说「正常」', () => {
  test('读到「没有记录」⇒ 正常 + 空态说明', async () => {
    mockResolve.mockResolvedValue({ success: true, data: READY })
    mockQuality.mockResolvedValue({ success: true, data: { order_item_id: 'item-3', latest: null, records: [] } })
    await mountLoggedIn()
    await scanByManual('JG-001')

    expect((await screen.findByTestId('worker-quality-state')).textContent).toBe('正常')
    expect(screen.getByTestId('worker-quality-empty').textContent).toContain(QUALITY_EMPTY_HINT)
    expect(mockQuality).toHaveBeenCalledWith('item-3', '2')
  })

  test('🔴 读失败 ⇒ 「未读到」，不显示「正常」，也不显示「没有记录」', async () => {
    mockResolve.mockResolvedValue({ success: true, data: READY })
    mockQuality.mockResolvedValue({ success: false, message: '读取质检记录失败，请重试' })
    await mountLoggedIn()
    await scanByManual('JG-001')

    expect((await screen.findByTestId('worker-quality-state')).textContent).toBe('未读到')
    expect(screen.queryByText(/默认没问题/)).toBeNull()
    expect(screen.getByTestId('worker-quality-failed').textContent).toContain('读取质检记录失败')
  })

  test('待复检 / 已判报废 走服务端的 result（端侧不自己判）', async () => {
    mockResolve.mockResolvedValue({ success: true, data: READY })
    mockQuality.mockResolvedValue({
      success: true,
      data: {
        order_item_id: 'item-3',
        latest: { result: 'rework', reason_label: '布面污渍', reason: '左下角', inspector_name: '李四', inspected_at: '2026-10-30 09:12' },
        records: [{ result: 'rework', reason_label: '布面污渍', reason: '左下角', inspector_name: '李四', inspected_at: '2026-10-30 09:12' }],
      },
    })
    await mountLoggedIn()
    await scanByManual('JG-001')

    expect((await screen.findByTestId('worker-quality-state')).textContent).toBe('待复检')
    const records = screen.getByTestId('worker-quality-records')
    expect(records.textContent).toContain('布面污渍（左下角）')
    expect(records.textContent).toContain('检验人 李四')
    expect(records.textContent).toContain('2026-10-30 09:12')
  })
})

describe('③ 403（未开通「质检」）⇒ 可行动提示，不冒充空态', () => {
  test('说清找管理员开通，且不显示「没有记录」', async () => {
    mockResolve.mockResolvedValue({ success: true, data: READY })
    mockQuality.mockResolvedValue({ success: false, statusCode: 403, message: '无权限' })
    await mountLoggedIn()
    await scanByManual('JG-001')

    expect((await screen.findByTestId('worker-quality-notEnabled')).textContent).toContain(
      '请让管理员',
    )
    // 🔴 403 时状态词必须是「未读到」（读到「没有记录」才敢说正常 —— 403 是没读到）
    expect(screen.getByTestId('worker-quality-state').textContent).toBe('未读到')
    expect(screen.queryByText(QUALITY_EMPTY_HINT)).toBeNull()
    expect(QUALITY_NOT_ENABLED_HINT).toContain('质检')
  })
})

describe('① 旧码 ⇒ 选套 + 部位后才读记录（多套同部位不串）', () => {
  test('旧码屏上没有状态词；选第 2 套 + 部位 ⇒ 按这一件读', async () => {
    mockResolve.mockResolvedValueOnce({ success: true, data: LEGACY })
    await mountLoggedIn()
    await scanByManual('LEGACY-1')

    expect(await screen.findByTestId('worker-quality-sets')).toBeTruthy()
    expect(screen.queryByTestId('worker-quality-state')).toBeNull()
    expect(mockQuality).not.toHaveBeenCalled()

    fireEvent.click(screen.getByTestId('worker-quality-set-1'))
    expect(screen.getByTestId('worker-quality-positions')).toBeTruthy()

    mockResolve.mockResolvedValueOnce({ success: true, data: READY })
    mockQuality.mockResolvedValue({ success: true, data: { order_item_id: 'item-3', latest: null, records: [] } })
    fireEvent.click(screen.getByTestId('worker-quality-position-0'))

    expect(await screen.findByTestId('worker-quality-state')).toBeTruthy()
    expect(mockQuality).toHaveBeenCalledWith('item-3', '2')
    expect(mockResolve).toHaveBeenLastCalledWith('LEGACY-1', undefined, {
      setId: 'set-2',
      orderItemId: 'item-3',
    })
  })
})

describe('⑤ 工序未确定 ⇒ 明说；屏上没有任何写动作', () => {
  test('operation 为 null ⇒ 提示「这道工序还没定」；不出现记返工 / 复检按钮', async () => {
    mockResolve.mockResolvedValue({ success: true, data: { ...READY, operation: null } })
    mockQuality.mockResolvedValue({ success: true, data: { order_item_id: 'item-3', latest: null, records: [] } })
    await mountLoggedIn()
    await scanByManual('JG-001')

    expect((await screen.findByTestId('worker-quality-operation-hint')).textContent).toContain(
      '这道工序还没定',
    )
    for (const label of ['记返工', '复检通过', '复检仍有问题', '报工']) {
      expect(screen.queryByRole('button', { name: label })).toBeNull()
    }
  })
})

describe('⑥ 未登录 ⇒ 没有任何动作', () => {
  test('只有去登录，没有扫一扫 / 输入框', async () => {
    render(<WorkerQualityPage />)
    expect(await screen.findByTestId('worker-quality-login-required')).toBeTruthy()
    expect(screen.queryByTestId('worker-quality-scan')).toBeNull()
    fireEvent.click(screen.getByTestId('worker-quality-login'))
    expect((Taro.navigateTo as jest.Mock).mock.calls[0][0].url).toBe(WORKER_LOGIN_ROUTE)
  })
})

describe('源码：只读面（出现写入口即红）', () => {
  test('页面与它的服务都不出现质检 / 报工的写调用', () => {
    const stripComments = (raw: string) =>
      raw
        .split('\n')
        .map((line) => {
          const trimmed = line.trimStart()
          return trimmed.startsWith('//') || trimmed.startsWith('*') || trimmed.startsWith('/*') ? '' : line
        })
        .join('\n')
    const page = stripComments(
      fs.readFileSync(path.join(__dirname, '..', 'src', 'pages', 'worker', 'quality', 'index.tsx'), 'utf8'),
    )
    const service = stripComments(
      fs.readFileSync(path.join(__dirname, '..', 'src', 'services', 'workerQualityService.ts'), 'utf8'),
    )
    for (const forbidden of ['completeByScan(', 'reportOperationFree(', 'createQuality(', '/inspections']) {
      expect(page).not.toContain(forbidden)
      expect(service).not.toContain(forbidden)
    }
  })
})
