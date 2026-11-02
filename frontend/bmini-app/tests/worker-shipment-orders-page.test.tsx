// case_ids: BM-025, BM-034, BM-036, BM-051, BM-061
/**
 * 工人**待发货单**列表页（issue #7806 P1a；页面 = `src/pages/worker/shipment-orders/index.tsx`）
 *
 * 数据源 = `GET /api/worker/shipment/orders`（#7764 上线）。它只回「**多套全部完工** + 可发货状态 +
 * 作业单已完成」的订单 ⇒ **筛选是后端的事**，端侧只渲染。
 *
 * ## 判据（每条都能单独变红）
 *
 * | # | 判据 | 红证（怎么让它单独变红） |
 * |---|---|---|
 * | ① | 🔴 **前端不筛、不补算**：服务端给半完工行（`completed_sets=1 / total_sets=3`）⇒ 必须渲染该行、且照实显示 `1/3 套` | 页面里加一行 `items.filter(...)` ⇒ 行消失，红；把 `1/3` 改印成「全完工」⇒ 红 |
 * | ② | **空态 = 可行动文案**（说清「怎么才会有单」），且有稳定 testID | 把空态文案换成空串 / 只写「暂无」⇒ 红 |
 * | ③ | 🔴 **读不到 ≠ 空态**：读面失败渲染「失败 + 重试」，**不得**出现空态；点「重试」会再读一次 | 把失败也渲染成空态 ⇒ 红 |
 * | ④ | **截断不静默**：`scan.truncated=true` ⇒ 出「还有更多单未列出」 | 忽略 `truncated` ⇒ 红 |
 * | ⑤ | 🔴 **401 单独一态**：无工人会话 / 会话失效 ⇒ 引导「去登录工人身份」（跳 `WORKER_TAB_LOGIN_ROUTE`），而不是空态 / 失败态 | 把 401 当空态 ⇒ 红；不引导登录 ⇒ 红 |
 * | ⑥ | **内部值不上屏**：物流方式只显示 `logistics_type_label`（`express` / `logistics` 这类内部值一个都不许出现）；缺值印 `—` | 改印 `logistics_type` ⇒ 红 |
 */
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

jest.mock('@tarojs/taro', () => {
  // 真内存 storage：工人会话的**清除**必须能被读到（空实现会让「清了」与「没清」长得一样）
  const store: Record<string, any> = {}
  return {
    __esModule: true,
    default: {
      showToast: jest.fn(),
      navigateTo: jest.fn(),
      redirectTo: jest.fn(),
      getStorageSync: jest.fn((key: string) => (key in store ? store[key] : '')),
      setStorageSync: jest.fn((key: string, value: any) => {
        store[key] = value
      }),
      removeStorageSync: jest.fn((key: string) => {
        delete store[key]
      }),
      getCurrentInstance: jest.fn(() => ({ router: { params: {} } })),
      __clearStorage: () => {
        Object.keys(store).forEach((key) => delete store[key])
      },
    },
    useDidShow: jest.fn(),
  }
})

jest.mock('../src/services/workerShipmentOrdersService', () => ({
  listReadyShipmentOrders: jest.fn(),
}))

jest.mock('../src/services/workerService', () => ({
  fetchCurrentWorker: jest.fn(),
}))

// 发货联（50×70）打印：只经 `printRowsLabel`；通道与能力用替身钉住「不可用不点」。
jest.mock('../src/utils/inbound/terminalTransport', () => ({
  createPrintTransport: jest.fn(),
}))
jest.mock('../src/utils/inbound/labelPrint', () => ({
  printRowsLabel: jest.fn(),
}))
jest.mock('../src/utils/inbound/printCapability', () => ({
  probePrintCapability: jest.fn(() => ({
    ok: true,
    readyHint: '本机可打印：点「打印标签」选好打印机',
    hint: '',
  })),
  printFailureHint: jest.fn((reason: string) => `打印失败：${reason}`),
}))

import Taro from '@tarojs/taro'
import WorkerShipmentOrdersPage, { EMPTY_HINT } from '../src/pages/worker/shipment-orders/index'
import { listReadyShipmentOrders } from '../src/services/workerShipmentOrdersService'
import { fetchCurrentWorker } from '../src/services/workerService'
import { printRowsLabel } from '../src/utils/inbound/labelPrint'
import { createPrintTransport } from '../src/utils/inbound/terminalTransport'
import { probePrintCapability } from '../src/utils/inbound/printCapability'
import { WORKER_TAB_LOGIN_ROUTE } from '../src/utils/inbound/gaps'
import { clearWorkerSession, getWorkerSessionId, setWorkerSessionId } from '../src/utils/workerSession'

const mockList = listReadyShipmentOrders as jest.Mock
const mockFetch = fetchCurrentWorker as jest.Mock
const mockPrintRows = printRowsLabel as jest.Mock
const mockCreateTransport = createPrintTransport as jest.Mock
const mockProbe = probePrintCapability as jest.Mock

const WORKER = {
  session_id: 'sess-worker-1',
  worker_id: 'w-1',
  worker_no: 'G001',
  worker_name: '张三',
}

/** 全完工行（服务端正常形态）。 */
const READY_ROW = {
  order_id: 'o-1',
  order_no: '0901-000084',
  status: 'producing',
  status_label: '生产中',
  created_at: '2026-09-01T10:00:00+08:00',
  customer_name: '肖风伟',
  customer_phone: '13849944707',
  customer_address: '洛阳市涧西区珠江路 18 号 3 单元 502',
  logistics_type: 'logistics',
  logistics_type_label: '物流专线',
  logistics_company: '四季安',
  total_sets: 3,
  completed_sets: 3,
  processing_order_no: 'JG-20260901-001',
  remark: '样品货款 600 元',
  // 随货标识（issue #7856，服务端已下发）：发货联的帘种 / 安装信息行
  curtain_types: '布帘/纱帘',
  install_community: '珠江路小区',
  install_rooms: '客厅\n主卧',
}

/** 半完工行：服务端**不该**给（给了也照实渲染、不许前端偷偷修好或丢掉）。 */
const HALF_ROW = {
  ...READY_ROW,
  order_id: 'o-2',
  order_no: '0901-000085',
  completed_sets: 1,
  logistics_type: 'express',
  logistics_type_label: '快递',
  logistics_company: '顺丰',
}

function okPage(items: any[], scan: any = { limit: 200, truncated: false }) {
  return { success: true, data: { total: items.length, items, scan } }
}

function renderPage() {
  return render(<WorkerShipmentOrdersPage />)
}

describe('WorkerShipmentOrdersPage 待发货单列表（issue #7806 P1a）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    ;(Taro as any).__clearStorage()
    setWorkerSessionId(WORKER.session_id)
    mockFetch.mockResolvedValue({ success: true, data: WORKER })
    mockList.mockResolvedValue(okPage([READY_ROW]))
    mockCreateTransport.mockResolvedValue({
      id: 'fake-rows',
      label: '测试打印机',
      print: jest.fn(),
    })
    mockPrintRows.mockResolvedValue({ ok: true, transportId: 'fake-rows', transportLabel: '测试打印机' })
    mockProbe.mockReturnValue({
      ok: true,
      readyHint: '本机可打印：点「打印标签」选好打印机',
      hint: '',
    })
  })

  afterEach(() => {
    clearWorkerSession()
  })

  it('① 列表照服务端给的行渲染：半完工行**不得**被过滤，且照实显示 1/3 套', async () => {
    mockList.mockResolvedValue(okPage([READY_ROW, HALF_ROW]))
    renderPage()

    await screen.findByTestId('shipment-orders-list')

    // 两行都在（前端没有偷偷筛掉半完工行 —— 那是第二份完工口径）
    expect(screen.getByTestId('shipment-orders-row-0')).toBeTruthy()
    expect(screen.getByTestId('shipment-orders-row-1')).toBeTruthy()
    expect(screen.getByTestId('shipment-orders-no-1').textContent).toContain('0901-000085')

    // 全完工行 vs 半完工行：读数照实
    expect(screen.getByTestId('shipment-orders-sets-0').textContent).toContain('3 套（全完工）')
    expect(screen.getByTestId('shipment-orders-sets-1').textContent).toContain('1/3 套')

    // 收货信息与物流类型：`物流类型标签 · 公司`
    expect(screen.getByTestId('shipment-orders-consignee-0').textContent).toContain('肖风伟')
    expect(screen.getByTestId('shipment-orders-consignee-0').textContent).toContain('13849944707')
    expect(screen.getByTestId('shipment-orders-address-0').textContent).toContain('洛阳市涧西区珠江路')
    expect(screen.getByTestId('shipment-orders-logistics-0').textContent).toContain('物流专线 · 四季安')
    expect(screen.getByTestId('shipment-orders-logistics-1').textContent).toContain('快递 · 顺丰')
  })

  it('⓪ 0 单时计数行只说「待发货 0 单」——不带「（全部套已完工）」', async () => {
    mockList.mockResolvedValue(okPage([]))
    renderPage()

    await screen.findByTestId('shipment-orders-empty')
    const count = screen.getByTestId('shipment-orders-count').textContent ?? ''
    expect(count).toContain('待发货 0 单')
    expect(count).not.toContain('全部套已完工')
    // 有单时括号照旧（结论只在有对象时成立）
    mockList.mockResolvedValue(okPage([READY_ROW]))
    renderPage()
    await screen.findByTestId('shipment-orders-list')
    expect(screen.getAllByTestId('shipment-orders-count')[1].textContent).toContain('待发货 1 单（全部套已完工）')
  })

  it('⑥ 内部值不上屏 + 缺值印 —（不印 0 / 不猜「快递」）', async () => {
    mockList.mockResolvedValue(
      okPage([
        {
          ...READY_ROW,
          logistics_type: 'logistics',
          logistics_type_label: null,
          logistics_company: null,
          customer_name: '',
          customer_phone: null,
          customer_address: '   ',
        },
      ]),
    )
    renderPage()

    await screen.findByTestId('shipment-orders-list')
    const logistics = screen.getByTestId('shipment-orders-logistics-0').textContent ?? ''
    expect(logistics).toContain('—')
    expect(logistics).not.toContain('logistics')
    expect(logistics).not.toContain('express')
    expect(logistics).not.toContain('快递')

    expect(screen.getByTestId('shipment-orders-consignee-0').textContent).toContain('—')
    expect(screen.getByTestId('shipment-orders-address-0').textContent).toContain('—')
  })

  it('② 空态 = 可行动文案（说清怎么才会有单）', async () => {
    mockList.mockResolvedValue(okPage([]))
    renderPage()

    const empty = await screen.findByTestId('shipment-orders-empty')
    expect(empty.textContent).toContain(EMPTY_HINT)
    expect(EMPTY_HINT).toContain('最后一道工序报完后')
    expect(screen.queryByTestId('shipment-orders-list')).toBeNull()
  })

  it('③ 读不到 ≠ 空态：失败态出「重试」，点它再读一次', async () => {
    mockList.mockResolvedValueOnce({ success: false, message: '网络超时，请再按一次' })
    renderPage()

    const error = await screen.findByTestId('shipment-orders-error')
    expect(error.textContent).toContain('网络超时')
    // 🔴 失败**不得**渲染成空态（「没有单」与「读不到」是两个事实）
    expect(screen.queryByTestId('shipment-orders-empty')).toBeNull()

    mockList.mockResolvedValueOnce(okPage([READY_ROW]))
    fireEvent.click(screen.getByTestId('shipment-orders-retry'))
    await screen.findByTestId('shipment-orders-list')
    expect(mockList).toHaveBeenCalledTimes(2)
  })

  it('④ 截断不静默：truncated=true ⇒ 出「还有更多单未列出」', async () => {
    mockList.mockResolvedValue(okPage([READY_ROW], { limit: 200, truncated: true }))
    renderPage()

    const hint = await screen.findByTestId('shipment-orders-truncated')
    expect(hint.textContent).toContain('还有更多单未列出')
  })

  it('⑤ 未登录（本机无工人会话）⇒ 只渲染引导 + 「去登录工人身份」，不读列表', async () => {
    clearWorkerSession()
    renderPage()

    expect(await screen.findByTestId('shipment-orders-login-required')).toBeTruthy()
    expect(screen.queryByTestId('shipment-orders-list')).toBeNull()
    expect(screen.queryByTestId('shipment-orders-empty')).toBeNull()
    // 没有工人会话就不该打读面（省一次必 401 的请求）
    expect(mockList).not.toHaveBeenCalled()

    fireEvent.click(screen.getByTestId('shipment-orders-login'))
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: WORKER_TAB_LOGIN_ROUTE })
  })

  it('⑤ 读面回 401（会话失效）⇒ 清本机工人身份 + 引导登录，而不是空态 / 失败态', async () => {
    mockList.mockResolvedValue({ success: false, message: '尚未登录工人身份', statusCode: 401 })
    renderPage()

    expect(await screen.findByTestId('shipment-orders-login-required')).toBeTruthy()
    expect(screen.queryByTestId('shipment-orders-empty')).toBeNull()
    expect(screen.queryByTestId('shipment-orders-error')).toBeNull()
    expect(getWorkerSessionId()).toBeNull()

    fireEvent.click(screen.getByTestId('shipment-orders-login'))
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: WORKER_TAB_LOGIN_ROUTE })
  })

  it('页头：显示当前工人（取自服务端）+ 点「刷新」会再读一次', async () => {
    renderPage()

    await screen.findByTestId('shipment-orders-list')
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(1))
    expect(screen.getByTestId('shipment-orders-worker').textContent).toContain('张三')

    fireEvent.click(screen.getByTestId('shipment-orders-refresh'))
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(2))
  })

  it('⑦ 发货联：预览 = /w/ 同一份行清单（含随货标识），打印走 printRowsLabel（50×70）', async () => {
    renderPage()
    await screen.findByTestId('shipment-orders-list')

    fireEvent.click(screen.getByTestId('shipment-orders-label-0'))
    const preview = await screen.findByTestId('shipment-orders-label-preview')
    expect(preview.textContent).toContain('发货联 · 0901-000084')

    const rows = screen.getByTestId('shipment-orders-label-rows').textContent ?? ''
    for (const label of [
      '订单号',
      '收货人',
      '电话',
      '地址',
      '帘种',
      '安装小区',
      '安装位置',
      '物流类型',
      '物流公司',
      '下单日期',
      '套数',
      '备注',
    ]) {
      expect(rows).toContain(label)
    }
    expect(rows).toContain('布帘/纱帘')
    expect(rows).toContain('珠江路小区')
    expect(rows).toContain('物流专线')
    expect(rows).toContain('四季安')
    expect(rows).toContain('3 套（全完工）')
    expect(rows).toContain('2026-09-01')

    fireEvent.click(screen.getByTestId('shipment-orders-label-print'))
    await waitFor(() => expect(mockPrintRows).toHaveBeenCalledTimes(1))
    const deps = mockPrintRows.mock.calls[0][0]
    expect(deps.capability.ok).toBe(true)
    expect(typeof deps.render).toBe('function')
    await waitFor(() =>
      expect(screen.getByTestId('shipment-orders-label-notice').textContent).toContain('已送出打印'),
    )
  })

  it('⑧ 发货联下单日期按 Asia/Shanghai 取日（16:30Z ⇒ 次日，不按 UTC 切）', async () => {
    mockList.mockResolvedValue(
      okPage([{ ...READY_ROW, created_at: '2026-09-01T16:30:00Z' }]),
    )
    renderPage()
    await screen.findByTestId('shipment-orders-list')
    fireEvent.click(screen.getByTestId('shipment-orders-label-0'))

    await screen.findByTestId('shipment-orders-label-preview')
    const rows = screen.getByTestId('shipment-orders-label-rows').textContent ?? ''
    expect(rows).toContain('2026-09-02')
    expect(rows).not.toContain('2026-09-01')
  })

  it('⑨ 可选附注缺值 ⇒ 发货联整行不印（不拿「帘种 —」白吃 50mm 版心）', async () => {
    mockList.mockResolvedValue(
      okPage([
        {
          ...READY_ROW,
          curtain_types: null,
          install_community: '  ',
          install_rooms: '',
          remark: '',
        },
      ]),
    )
    renderPage()
    await screen.findByTestId('shipment-orders-list')
    fireEvent.click(screen.getByTestId('shipment-orders-label-0'))

    await screen.findByTestId('shipment-orders-label-preview')
    const rows = screen.getByTestId('shipment-orders-label-rows').textContent ?? ''
    for (const optional of ['帘种', '安装小区', '安装位置', '备注']) {
      expect(rows).not.toContain(optional)
    }
  })

  it('⑩ 本机不能打印 ⇒ 发货联打印按钮 disabled + 先给可行动文案（不点了才失败）', async () => {
    mockProbe.mockReturnValueOnce({
      ok: false,
      reason: 'insecure-context',
      hint: '当前地址不是 HTTPS，手机不能直连打印机',
      readyHint: '',
    })
    renderPage()
    await screen.findByTestId('shipment-orders-list')
    fireEvent.click(screen.getByTestId('shipment-orders-label-0'))

    const button = await screen.findByTestId('shipment-orders-label-print')
    expect((button as any).disabled).toBe(true)
    expect(screen.getByTestId('shipment-orders-label-capability').textContent).toContain('HTTPS')
    fireEvent.click(button)
    expect(mockPrintRows).not.toHaveBeenCalled()
  })
})
