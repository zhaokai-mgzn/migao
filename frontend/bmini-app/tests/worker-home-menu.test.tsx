// case_ids: BM-014, BM-015, BM-025
/**
 * 工人工作台**入口显隐**判据（issue #7812）—— 商家反馈「后台勾了菜单，工人端没变」。
 *
 * ## 判据（每条都能单独变红）
 *
 * | # | 判据 | 红证 |
 * |---|---|---|
 * | ① | 只开 `rework` ⇒ 出现「返工记录」、**不出现**「拍照发货」；拍照入库 / 补打入库标签（无键）恒在 | 把入口写成无条件渲染 ⇒ 红 |
 * | ② | `pages` 空数组 ⇒ **fail-open 全开** | 空数组按「全关」⇒ 红 |
 * | ③ | 读不到（`unread`）⇒ 全开 + **一句显式提示** | 静默全开 / 静默全关 ⇒ 红 |
 * | ④ | 401 ⇒ 回未登录态、**不渲染任何功能卡** | 把 401 当「读不到」⇒ 卡片照旧出现 ⇒ 红 |
 *
 * ⑤ 「待发货单」只跟 **`to_ship`** 走（与「拍照发货」的 `shipment` **分开**，issue #7814）：
 *    只开 `shipment` ⇒ 不出现「待发货单」；开 `to_ship` ⇒ 出现。
 *
 * ⑥ 🔴 **`report` 键不再发射任何入口**（issue #7920，2026-10-27 用户裁定「把工人菜单页面的扫码报工
 *    菜单移除掉，直接用其他 app 的扫一扫功能替代」）：只开 `report` ⇒ 工人功能里**一个入口都不多**。
 *    报工页仍可达，但入口是**外部扫码**（服务端 302 → 启动器 redirectTo），不是这张菜单。
 */
import React from 'react'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'

jest.mock('@tarojs/taro', () => {
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
      __clearStorage: () => {
        Object.keys(store).forEach((key) => delete store[key])
      },
    },
    useDidShow: jest.fn(),
  }
})

jest.mock('../src/services/workerService', () => ({
  fetchCurrentWorker: jest.fn(),
  fetchWorkerPages: jest.fn(),
  workerLogout: jest.fn(),
}))

// issue #7921：入口上的待处理数 = 两个既有只读列表端点的行数
jest.mock('../src/services/workerShipmentOrdersService', () => ({
  listReadyShipmentOrders: jest.fn(),
}))
jest.mock('../src/services/workerReworkService', () => ({
  listWorkerReworkOrders: jest.fn(),
}))

import Taro from '@tarojs/taro'
import WorkerHomePage from '../src/pages/worker/home/index'
import { fetchCurrentWorker, fetchWorkerPages, workerLogout } from '../src/services/workerService'
import { listReadyShipmentOrders } from '../src/services/workerShipmentOrdersService'
import { listWorkerReworkOrders } from '../src/services/workerReworkService'
import { setWorkerSessionId } from '../src/utils/workerSession'

const WORKER = {
  session_id: 'sess-worker-1',
  worker_id: 'w-1',
  worker_no: 'G001',
  worker_name: '张三',
}
const mockFetch = fetchCurrentWorker as jest.Mock
const mockPages = fetchWorkerPages as jest.Mock
const mockLogout = workerLogout as jest.Mock
const mockShipmentOrders = listReadyShipmentOrders as jest.Mock
const mockReworkOrders = listWorkerReworkOrders as jest.Mock

async function renderWithPages(pages: string[] | null, unread = false) {
  setWorkerSessionId(WORKER.session_id)
  mockFetch.mockResolvedValue({ success: true, data: WORKER })
  mockPages.mockResolvedValue({ pages, unread, unauthorized: false })
  render(<WorkerHomePage />)
  await screen.findByText('工号 G001')
  await waitFor(() => expect(mockPages).toHaveBeenCalled())
  // 菜单开关是异步读回的 ⇒ 等它应用到 state 再断言（否则断言跑在 fail-open 默认态上）
  await act(async () => {})
  return screen
}

describe('工人工作台入口按「工人端菜单」显隐（issue #7812）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    ;(Taro as any).__clearStorage()
    mockLogout.mockResolvedValue(undefined)
    mockShipmentOrders.mockResolvedValue({ success: true, data: { items: [] }, message: '' })
    mockReworkOrders.mockResolvedValue({ success: true, data: { orders: [] }, message: '' })
  })

  it('① 只开 rework ⇒ 有「返工记录」，没有「拍照发货」；无键的两条恒在', async () => {
    await renderWithPages(['rework'])

    expect(screen.getByText('返工记录')).toBeTruthy()
    expect(screen.queryByText('拍照发货')).toBeNull()
    // 工人面固有（后端无页面键）⇒ 不受开关影响
    expect(screen.getByText('拍照入库')).toBeTruthy()
    expect(screen.getByText('补打入库标签')).toBeTruthy()
  })

  it('①反向 全开（默认集合）⇒ 返工记录与拍照发货都在', async () => {
    await renderWithPages(['rework', 'shipment'])
    expect(screen.getByText('返工记录')).toBeTruthy()
    expect(screen.getByText('拍照发货')).toBeTruthy()
  })

  it('⑥ `report` 键不再发射入口（扫码报工菜单已移除，扫码由微信 / 手机相机承担）', async () => {
    await renderWithPages(['report'])

    expect(screen.queryByText('扫码报工')).toBeNull()
    // 无键的两条照旧（固有能力）
    expect(screen.getByText('拍照入库')).toBeTruthy()
    expect(screen.getByText('补打入库标签')).toBeTruthy()
    // 也不许退回成「全部入口」：受键控制的那几条都不在
    expect(screen.queryByText('拍照发货')).toBeNull()
    expect(screen.queryByText('待发货单')).toBeNull()
    expect(screen.queryByText('返工记录')).toBeNull()
    // issue #7934：我的计件由 `piecework` 键控制，`report` 开着不等于它开着
    expect(screen.queryByText('我的计件')).toBeNull()
  })

  it('⑤ 待发货单只跟 `to_ship` 走：只开 shipment 时**不出现**（两个能力分开勾）', async () => {
    await renderWithPages(['report', 'shipment'])
    expect(screen.getByText('拍照发货')).toBeTruthy()
    expect(screen.queryByText('待发货单')).toBeNull()
  })

  it('⑤反向 开 `to_ship` ⇒ 出现待发货单（默认集合里就有它）', async () => {
    await renderWithPages(['report', 'shipment', 'to_ship'])
    expect(screen.getByText('待发货单')).toBeTruthy()
  })

  it('⑦ 我的计件只跟 `piecework` 走（issue #7934：入口从报工详情页搬到本菜单）', async () => {
    await renderWithPages(['piecework'])
    expect(screen.getByText('我的计件')).toBeTruthy()
    // 没开的照旧不出现（不是「一条开 ⇒ 全开」）
    expect(screen.queryByText('返工记录')).toBeNull()
    expect(screen.queryByText('拍照发货')).toBeNull()
    expect(screen.queryByText('待发货单')).toBeNull()
    // 无键的两条恒在
    expect(screen.getByText('拍照入库')).toBeTruthy()
    expect(screen.getByText('补打入库标签')).toBeTruthy()
  })

  it('② 空数组 ⇒ fail-open 全开（不能因为「一份空配置」把活挡掉）', async () => {
    await renderWithPages([])
    expect(screen.getByText('返工记录')).toBeTruthy()
    expect(screen.getByText('拍照发货')).toBeTruthy()
    expect(screen.getByText('待发货单')).toBeTruthy()
    expect(screen.getByText('拍照入库')).toBeTruthy()
    // 我的计件（issue #7934）在默认集合里 ⇒ fail-open 时也在
    expect(screen.getByText('我的计件')).toBeTruthy()
    // 空数组 = 全开，但**没有**「扫码报工」这条入口（它已从菜单移除，不是被收窄）
    expect(screen.queryByText('扫码报工')).toBeNull()
  })

  it('③ 读不到 ⇒ 全开 + 一句显式提示（不说话的全开等于静默降级）', async () => {
    await renderWithPages(null, true)
    expect(screen.getByText('返工记录')).toBeTruthy()
    expect(screen.getByTestId('worker-home-pages-unread')).toBeTruthy()
    // 文案是人话：不摆内部键
    expect(screen.queryByText(/report|shipment|页面键/)).toBeNull()
  })

  it('④ 401 ⇒ 回未登录态，不渲染任何功能卡', async () => {
    setWorkerSessionId(WORKER.session_id)
    mockFetch.mockResolvedValue({ success: true, data: WORKER })
    mockPages.mockResolvedValue({ pages: null, unread: false, unauthorized: true })
    render(<WorkerHomePage />)
    await screen.findByText('工号 G001')

    await waitFor(() => {
      expect(screen.queryByText('返工记录')).toBeNull()
    })
    expect(await screen.findByText(/请先用工号 \+ PIN 登录工人身份/)).toBeTruthy()
  })

  it('入口点击跳自己的路由（静态字面锚点的行为面）', async () => {
    await renderWithPages(['rework', 'shipment'])
    fireEvent.click(screen.getByText('返工记录'))
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: '/pages/worker/rework/index' })
  })

  /**
   * ⏱ **菜单开关晚到**（回归钉，2026-10-27 CI 实测踩到）：`fetchWorkerPages()` 是异步的，
   * 它 resolve 之前页面处于 fail-open 默认态。改前本文件的断言在「默认态」上跑，本地恰好赢、
   * CI 上输 ⇒ 红了两次。本判据把**顺序**钉死：先全开（读不到），读到后**收敛**到实际页面集。
   */
  it('⏱ 菜单开关晚到：先 fail-open 全开，读到 pages 后收敛到实际集合', async () => {
    setWorkerSessionId(WORKER.session_id)
    mockFetch.mockResolvedValue({ success: true, data: WORKER })
    let release: (value: any) => void = () => {}
    mockPages.mockReturnValue(
      new Promise((resolve) => {
        release = resolve
      }),
    )
    render(<WorkerHomePage />)
    await screen.findByText('工号 G001')

    // ① 还没读到 ⇒ fail-open：受键控制的入口都在
    expect(screen.getByText('返工记录')).toBeTruthy()
    expect(screen.getByText('拍照发货')).toBeTruthy()

    // ② 读到「只开 report」⇒ 收敛：受键控制的三条都收起
    await act(async () => {
      release({ pages: ['report'], unread: false, unauthorized: false })
    })
    await waitFor(() => expect(screen.queryByText('返工记录')).toBeNull())
    expect(screen.queryByText('拍照发货')).toBeNull()
    expect(screen.queryByText('待发货单')).toBeNull()
  })
})
