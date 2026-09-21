// case_ids: BM-006, PG-058
/**
 * 工人端「扫码 ⇒ 一屏 ⇒ 开工/领活」主闭环（切片 ②，issue #4698；设计 `set-code-and-scan-loop.md` §4）。
 *
 * 🔴 <b>2026-09-21 语义改判（issue #4967）</b>：扫码 = <b>开工 / 领活</b>（用户逐字「工人都是先扫码报工后再真实进行生产」）
 * ⇒ 按钮文案由【完成】改为【开工】；记账时点与端点**一字未变**。
 *
 * <p>判据（每条都能红）：</p>
 * <ol>
 *   <li><b>新码 ⇒ A 模式一屏</b>：套号 · 部位 + 系统推断的工序（逻辑名 · 部位）+ 应做数量 + 一个大按钮
 *       【开工】（一次扫码 = 1 步，不需要工人选部位/找工序/填数量）；</li>
 *   <li><b>点【开工】</b>⇒ 只调一次 `completeByScan(token, operation_id, 幂等键)`（数量/身份都**不传**：
 *       数量缺省由服务端取剩余应做，身份由服务端从工人 session 解）；成功后把服务端给的
 *       <b>下一道</b>就地换到屏上并刷新本单进度；</li>
 *   <li>🔴 <b>未确定工序</b>（`operation=null`）⇒ 屏上**没有**【开工】按钮，`completeByScan`
 *       一次都不调（未确定不得记账）；</li>
 *   <li>🔴 <b>旧码降级</b>（`granularity="order"`）⇒ 显式提示「必须选部位」+ 带出本单工序，
 *       **不**出【开工】按钮（绝不默认取第 1 套）；</li>
 *   <li><b>一键改</b>：点候选 ⇒ 带着 `operation_id` 重新解析（由**服务端**校验归属）；</li>
 *   <li><b>弱网</b>：传输层失败 ⇒ 进既有补传队列且**复用同一个幂等键**（补传不会重复计件）。</li>
 * </ol>
 *
 * <p>mock：Taro API（scanCode + 真内存 storage）+ productionService（网络层）+ authStore。
 * 在飞锁用**真身**（判据 2 的「只调一次」依赖它真的挡住第二笔）。</p>
 */
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

/** 启动参数（深链直达用；本文件不涉及，给空对象避免 undefined） */
let launchParams: Record<string, string> = {}

jest.mock('@tarojs/taro', () => {
  const store: Record<string, any> = {}
  return {
    __esModule: true,
    default: {
      scanCode: jest.fn(),
      showToast: jest.fn(),
      navigateTo: jest.fn(),
      getStorageSync: jest.fn((key: string) => (key in store ? store[key] : '')),
      setStorageSync: jest.fn((key: string, value: any) => {
        store[key] = value
      }),
      removeStorageSync: jest.fn((key: string) => {
        delete store[key]
      }),
      getCurrentInstance: jest.fn(() => ({ router: { params: launchParams } })),
      onNetworkStatusChange: jest.fn(),
      getNetworkType: jest.fn(),
      __clearStorage: () => {
        Object.keys(store).forEach((key) => delete store[key])
      },
    },
    useDidShow: jest.fn(),
  }
})

jest.mock('../src/services/productionService', () => ({
  // 锁用真身（issue #4116 §5-1）：页面调用 reportInFlightLock.tryAcquire()，mock 掉会拿到 undefined
  ...jest.requireActual('../src/services/productionService'),
  getOrderOperations: jest.fn(),
  reportOperation: jest.fn(),
  shipOrder: jest.fn(),
  getOrderPiecework: jest.fn(),
  scanResolve: jest.fn(),
  completeByScan: jest.fn(),
}))

jest.mock('../src/store/authStore', () => ({
  useAuthStore: jest.fn(() => ({
    user: { id: 'u1', nickname: '张师傅', avatar: null, tenantId: 1, role: 'worker' },
  })),
}))

import Taro from '@tarojs/taro'
import ProductionPage from '../src/pages/production/index/index'
import {
  completeByScan,
  getOrderOperations,
  getOrderPiecework,
  reportInFlightLock,
  scanResolve,
} from '../src/services/productionService'
import type { OrderOperations, ScanResolveResult } from '../src/services/productionService'
import { listPendingReports } from '../src/utils/productionOffline'

const ORDER_ID = 'CSO260915-02615'
const SET_NO = `${ORDER_ID}-014`
const TOKEN = 'scan-token-4698b'

const mockGet = getOrderOperations as jest.Mock
const mockScan = scanResolve as jest.Mock
const mockComplete = completeByScan as jest.Mock
const mockPiecework = getOrderPiecework as jest.Mock

/** 冻结契约响应（`GET .../operations`，字段名逐字对齐 issue #3997 契约 1） */
function makeDetail(): OrderOperations {
  return {
    order_id: ORDER_ID,
    positions: [
      {
        position_name: '布帘',
        order_item_id: 'oi-cloth',
        position_kind: '布帘',
        operations: [
          {
            id: 'op-cloth',
            seq: 1,
            operation: '精裁-布',
            group: '裁剪',
            unit: '米',
            qty: 11,
            unit_price: 3.5,
            is_must_finish: true,
            is_start_marker: false,
            status: 'pending',
            done_qty: 0,
          },
        ],
      },
    ],
    progress: { total: 1, done: 0, percent: 0 },
    work_logs: [],
  }
}

/** `GET /scan` 的新码响应（切片 ① 的形状；`operation` = 系统推断的下一道） */
function makeScan(overrides: Partial<ScanResolveResult> = {}): ScanResolveResult {
  return {
    granularity: 'set_position',
    order_id: ORDER_ID,
    processing_order_no: ORDER_ID,
    set_no: SET_NO,
    set_index: 14,
    position: { order_item_id: 'oi-cloth', position_kind: '布帘', position_name: '布艺遮光帘A' },
    operation: {
      operation_id: 'op-cloth',
      logical_name: '定型',
      position: '布帘',
      unit: '米',
      qty: 11,
      unit_price: 3.5,
      seq: 6,
      status: 'pending',
      determined_by: 'inferred',
      rerouted: false,
    },
    alternatives: [],
    set_progress: { total: 1, done: 0, percent: 0 },
    // 本套工序明细（issue #4967 交付物 2；逐字照 ProductionScanService#setOverview 的形状）
    set_overview: {
      set_no: SET_NO,
      set_index: 14,
      positions: [
        {
          order_item_id: 'oi-cloth',
          position_kind: '布帘',
          position_name: '布艺遮光帘A',
          operations: [
            { operation_id: 'op-cloth', logical_name: '定型', position: '布帘', seq: 6, qty: 11, unit: '米', unit_price: 3.5, status: 'pending', done_qty: 0 },
            { operation_id: 'op-roll', logical_name: '打卷', position: '布帘', seq: 9, qty: 1, unit: '套', unit_price: null, status: 'pending', done_qty: 0 },
          ],
        },
      ],
    },
    completed: false,
    needs_selection: [],
    ...overrides,
  }
}

describe('ProductionPage（扫码 ⇒ 一屏 ⇒ 开工/领活，切片 ②；issue #4967 语义改判）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    launchParams = {}
    ;(Taro as any).__clearStorage()
    // 锁是模块级单例：用例之间必须复位（否则上一例的 in-flight 会挡住本例）
    reportInFlightLock.release()
    ;(Taro.scanCode as jest.Mock).mockResolvedValue({ result: TOKEN })
    mockGet.mockResolvedValue({ success: true, data: makeDetail() })
    mockPiecework.mockResolvedValue({ success: true, data: { total: 0, per_worker: {}, per_operation: [] } })
    mockScan.mockResolvedValue({ success: true, data: makeScan() })
    mockComplete.mockResolvedValue({
      success: true,
      data: {
        operation_id: 'op-cloth',
        done_qty: 11,
        status: 'done',
        order_completed: false,
        worker_name: '张师傅',
        identity_source: 'server_session',
        set_no: SET_NO,
        next_operation: null,
        set_completed: true,
      },
    })
  })

  it('新码 ⇒ 一屏：套号 · 部位 + 工序 + 应做数量 + 【开工】（工人不选部位/不找工序/不填数量）', async () => {
    render(<ProductionPage />)
    fireEvent.click(screen.getByText('扫一扫'))

    // 一屏（设计 §4.1）：一行大字 = 工序 · 应做数量
    expect(await screen.findByText('定型 · 布帘 · 应做 11米')).toBeTruthy()
    expect(screen.getByText(`${SET_NO} · 布艺遮光帘A`)).toBeTruthy()
    // 🔴 按钮文案 = 【开工】（issue #4967：扫码 = 开工 / 领活）
    expect(screen.getByText('开工')).toBeTruthy()
    expect(screen.queryByText('完成')).toBeNull()
    // 同时带出本单工序/进度（扫一次不用再查单）
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(ORDER_ID))
    // 屏上不该出现「选部位」之类的额外交互
    expect(screen.queryByText(/选择部位/)).toBeNull()
  })

  it('点【开工】⇒ 只调一次 completeByScan（数量/身份都不传）+ 刷新本单 + 屏上换「下一道」', async () => {
    const next = makeScan()
    mockComplete.mockResolvedValue({
      success: true,
      data: {
        operation_id: 'op-cloth',
        done_qty: 11,
        status: 'done',
        order_completed: false,
        worker_name: '张师傅',
        next_operation: { ...next.operation!, operation_id: 'op-next', logical_name: '打卷', position: '布帘' },
        set_completed: false,
      },
    })

    render(<ProductionPage />)
    fireEvent.click(screen.getByText('扫一扫'))
    fireEvent.click(await screen.findByText('开工'))

    await waitFor(() => expect(mockComplete).toHaveBeenCalledTimes(1))
    const [token, operationId, requestId] = mockComplete.mock.calls[0]
    expect(token).toBe(TOKEN)
    expect(operationId).toBe('op-cloth')
    // 幂等键随请求头走（服务端据此不重复计件）——非空即可
    expect(typeof requestId).toBe('string')
    expect(requestId.length).toBeGreaterThan(0)
    // 一屏闭环：服务端给的「下一道」就地换到屏上
    expect(await screen.findByText('打卷 · 布帘 · 应做 11米')).toBeTruthy()
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(ORDER_ID))
    // 本机明细记的是**服务端回执**的工人名（请求体不含身份）
    expect(screen.getByText(/张师傅 · 定型 · 布帘 · 11/)).toBeTruthy()
  })

  it('🔴 未确定工序（operation=null）⇒ 屏上没有【开工】，completeByScan 一次都不调', async () => {
    mockScan.mockResolvedValue({
      success: true,
      data: makeScan({ operation: null, completed: true }),
    })

    render(<ProductionPage />)
    fireEvent.click(screen.getByText('扫一扫'))

    expect(await screen.findByText('本套工序都已被领走，无需再领')).toBeTruthy()
    expect(screen.queryByText('开工')).toBeNull()
    expect(mockComplete).not.toHaveBeenCalled()
  })

  it('🔴 旧码降级（granularity=order）⇒ 提示必须选部位 + 带出本单工序，绝不出【开工】', async () => {
    mockScan.mockResolvedValue({
      success: true,
      data: makeScan({ granularity: 'order', set_no: null, position: null, operation: null,
        needs_selection: ['set', 'position'], completed: null }),
    })

    render(<ProductionPage />)
    fireEvent.click(screen.getByText('扫一扫'))

    await waitFor(() =>
      expect(Taro.showToast).toHaveBeenCalledWith(
        expect.objectContaining({ title: expect.stringContaining('请选择部位') }),
      ),
    )
    expect(screen.queryByText('开工')).toBeNull()
    expect(mockComplete).not.toHaveBeenCalled()
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(ORDER_ID))
  })

  it('一键改：点候选 ⇒ 带 operation_id 重新解析（归属由服务端校验）', async () => {
    mockScan
      .mockResolvedValueOnce({
        success: true,
        data: makeScan({
          alternatives: [{ operation_id: 'op-alt', logical_name: '打卷', position: '布帘', qty: 11, unit: '米' }],
        }),
      })
      .mockResolvedValueOnce({
        success: true,
        data: makeScan({
          operation: { ...makeScan().operation!, operation_id: 'op-alt', logical_name: '打卷',
            determined_by: 'picked' },
        }),
      })

    render(<ProductionPage />)
    fireEvent.click(screen.getByText('扫一扫'))

    fireEvent.click(await screen.findByText('打卷 · 布帘 · 11米'))

    await waitFor(() => expect(mockScan).toHaveBeenCalledWith(TOKEN, 'op-alt'))
    expect(await screen.findByText('打卷 · 布帘 · 应做 11米')).toBeTruthy()
  })

  // ============================================================ 按套展示工序细节（issue #4967 交付物 2）

  it('🔴 扫码后按套展示工序细节：本套各部位的工序明细（逻辑名/应做+单位/单价/状态/已报）', async () => {
    render(<ProductionPage />)
    fireEvent.click(screen.getByText('扫一扫'))

    expect(await screen.findByText(`第 ${SET_NO} 套 · 本套工序`)).toBeTruthy()
    expect(screen.getByText('布艺遮光帘A')).toBeTruthy()
    // 待做的那道：逻辑名 + 应做数量+单位；另一行是单价/状态/已报
    expect(screen.getByText('定型 · 应做 11米')).toBeTruthy()
    expect(screen.getByText('¥3.50/米 · 待领 · 已报 0米')).toBeTruthy()
    // 未定价 ≠ 0（V90/#4696）：显式写「未定价」，不折 0
    expect(screen.getByText('未定价 · 待领 · 已报 0套')).toBeTruthy()
  })

  it('🔴 缺值不渲染：set_overview 缺失 / positions 为空 ⇒ 明细块一个字节都不出现', async () => {
    mockScan.mockResolvedValue({
      success: true,
      data: makeScan({ set_overview: null }),
    })

    render(<ProductionPage />)
    fireEvent.click(screen.getByText('扫一扫'))

    expect(await screen.findByText('定型 · 布帘 · 应做 11米')).toBeTruthy()
    expect(screen.queryByText(`第 ${SET_NO} 套 · 本套工序`)).toBeNull()
    expect(screen.queryByText(/undefined/)).toBeNull()
    expect(screen.queryByText(/NaN/)).toBeNull()
  })

  it('弱网：传输层失败 ⇒ 进既有补传队列，且**复用同一个幂等键**（补传不会重复计件）', async () => {
    mockComplete.mockResolvedValue({ success: false, offline: true, message: '网络异常' })

    render(<ProductionPage />)
    fireEvent.click(screen.getByText('扫一扫'))
    fireEvent.click(await screen.findByText('开工'))

    await waitFor(() => expect(mockComplete).toHaveBeenCalledTimes(1))
    const requestId = mockComplete.mock.calls[0][2]
    const queued = listPendingReports()
    expect(queued).toHaveLength(1)
    expect(queued[0].requestId).toBe(requestId)
    expect(queued[0].operationId).toBe('op-cloth')
    expect(await screen.findByText(/已存入本机待补传队列/)).toBeTruthy()
  })
})
