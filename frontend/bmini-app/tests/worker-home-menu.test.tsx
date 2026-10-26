// case_ids: BM-014, BM-015, BM-025
/**
 * 工人工作台**入口显隐**判据（issue #7812）—— 商家反馈「后台勾了菜单，工人端没变」。
 *
 * ## 判据（每条都能单独变红）
 *
 * | # | 判据 | 红证 |
 * |---|---|---|
 * | ① | 只开 `report` ⇒ 出现「扫码报工」、**不出现**「拍照发货」；拍照入库 / 补打入库标签（无键）恒在 | 把入口写成无条件渲染 ⇒ 红 |
 * | ② | `pages` 空数组 ⇒ **fail-open 全开** | 空数组按「全关」⇒ 红 |
 * | ③ | 读不到（`unread`）⇒ 全开 + **一句显式提示** | 静默全开 / 静默全关 ⇒ 红 |
 * | ④ | 401 ⇒ 回未登录态、**不渲染任何功能卡** | 把 401 当「读不到」⇒ 卡片照旧出现 ⇒ 红 |
 *
 * ⑤ 「待发货单」只跟 **`to_ship`** 走（与「拍照发货」的 `shipment` **分开**，issue #7814）：
 *    只开 `shipment` ⇒ 不出现「待发货单」；开 `to_ship` ⇒ 出现。
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

import Taro from '@tarojs/taro'
import WorkerHomePage from '../src/pages/worker/home/index'
import { fetchCurrentWorker, fetchWorkerPages, workerLogout } from '../src/services/workerService'
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

async function renderWithPages(pages: string[] | null, unread = false) {
  setWorkerSessionId(WORKER.session_id)
  mockFetch.mockResolvedValue({ success: true, data: WORKER })
  mockPages.mockResolvedValue({ pages, unread, unauthorized: false })
  render(<WorkerHomePage />)
  await screen.findByText('工号 G001')
  await waitFor(() => expect(mockPages).toHaveBeenCalled())
  return screen
}

describe('工人工作台入口按「工人端菜单」显隐（issue #7812）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    ;(Taro as any).__clearStorage()
    mockLogout.mockResolvedValue(undefined)
  })

  it('① 只开 report ⇒ 有「扫码报工」，没有「拍照发货」；无键的两条恒在', async () => {
    await renderWithPages(['report'])

    expect(screen.getByText('扫码报工')).toBeTruthy()
    expect(screen.queryByText('拍照发货')).toBeNull()
    // 工人面固有（后端无页面键）⇒ 不受开关影响
    expect(screen.getByText('拍照入库')).toBeTruthy()
    expect(screen.getByText('补打入库标签')).toBeTruthy()
  })

  it('①反向 全开（默认集合）⇒ 扫码报工与拍照发货都在', async () => {
    await renderWithPages(['report', 'shipment'])
    expect(screen.getByText('扫码报工')).toBeTruthy()
    expect(screen.getByText('拍照发货')).toBeTruthy()
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

  it('② 空数组 ⇒ fail-open 全开（不能因为「一份空配置」把活挡掉）', async () => {
    await renderWithPages([])
    expect(screen.getByText('扫码报工')).toBeTruthy()
    expect(screen.getByText('拍照发货')).toBeTruthy()
    expect(screen.getByText('待发货单')).toBeTruthy()
    expect(screen.getByText('拍照入库')).toBeTruthy()
  })

  it('③ 读不到 ⇒ 全开 + 一句显式提示（不说话的全开等于静默降级）', async () => {
    await renderWithPages(null, true)
    expect(screen.getByText('扫码报工')).toBeTruthy()
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
      expect(screen.queryByText('扫码报工')).toBeNull()
    })
    expect(await screen.findByText(/请先用工号 \+ PIN 登录工人身份/)).toBeTruthy()
  })

  it('入口点击跳自己的路由（静态字面锚点的行为面）', async () => {
    await renderWithPages(['report', 'shipment'])
    fireEvent.click(screen.getByText('扫码报工'))
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: '/pages/worker/report/index' })
  })
})
