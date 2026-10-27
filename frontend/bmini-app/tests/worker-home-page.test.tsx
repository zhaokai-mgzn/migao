// case_ids: BM-034
/**
 * 工人首页（issue #6467 切片 1，S2）：纯工人设备的落地页 —— **只**给工人面三件事，
 * 一件商家面东西都不出现。
 *
 * ## 为什么必须有这一页
 * 现场（2026-10-07 生产）：管理员账号在 H5 上用**商家**身份点「完成报工」⇒
 * `POST /api/worker/production/scan/complete` 401 + 请求层「登录已过期」把商家登录态清掉、
 * 踢回登录页 ⇒ 重登再点仍然如此。根因之一是**端侧没有工人身份的落点**：
 * 工人登录后只能落进商家的 tabBar（问黄金策/数据/坐席/我的），而工人零商家权限
 * （`/api/admin/**` 拒绝集合含 `worker`）⇒ 看见商家菜单只会 403 / 空页。
 *
 * ## 本文件锁四条（每条都有红证）
 * ① **身份卡读服务端**：工号 + 姓名来自 `fetchCurrentWorker()`（服务端 session），
 *    不是前端 state 拼的（页头显示的正是「这笔活会记到谁头上」= 计件工资的凭证）；
 * ② **三件工人功能入口**各自跳对路由（入库 / 补打 / 发货，均走 `utils/inbound/gaps.ts` 的路由常量
 *    —— 单一真值，不写字面量）；🔴 原常驻主按钮「扫码报工」已随报工页下架删除
 *    （2026-10-14，issue #6868 实现包 D1）⇒ 本条**反向**钉住它不再出现（留着就是死链）；
 * ③ **不出现任何商家面入口**（问黄金策 / 数据 / 坐席 / 管理面 4 项）；
 * ④ **退出工人身份**（身份条里的「退出」）= `workerLogout()` + 清本机工人态 + 回登录页的工人入口。
 *
 * ## 红证（每条判据的失败形态）
 * - 身份卡改读 `getCachedWorker()` 而不调 `fetchCurrentWorker()` ⇒ ①红（服务端真值不取）。
 * - 把「拍照入库」入口指向别处 / 删掉 ⇒ ②红。
 * - 把「扫码报工」主按钮加回来（= 指向已删除的报工页）⇒ ②红（本文件的反向断言）。
 * - 往页面加一行「问黄金策」⇒ ③红。
 * - 退出只清本机不调 `workerLogout()`（服务端 session 还活着 ⇒ 下一个人扫码记到上一个人头上）⇒ ④红。
 */
import React from 'react'
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react'

jest.mock('@tarojs/taro', () => {
  // 真内存 storage：工人态的清除必须能被**读到**（`jest.fn()` 空实现会让「真的清了」与
  // 「没清」长得一样）。
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
      __getStorage: () => ({ ...store }),
    },
    useDidShow: jest.fn(),
  }
})

jest.mock('../src/services/workerService', () => ({
  fetchCurrentWorker: jest.fn(),
  workerLogout: jest.fn(),
  // issue #7812：工作台入口按「工人端菜单」显隐 ⇒ 本页会读一次页面集。
  // 默认 = 读到了但没给（null）⇒ fail-open 全开（与线上未收窄的工人一致）。
  fetchWorkerPages: jest.fn(),
}))

// issue #7921：入口上的「待处理数」= 两个既有只读列表端点的行数（端侧不新增计数端点）
jest.mock('../src/services/workerShipmentOrdersService', () => ({
  listReadyShipmentOrders: jest.fn(),
}))
jest.mock('../src/services/workerReworkService', () => ({
  listWorkerReworkOrders: jest.fn(),
}))

import Taro from '@tarojs/taro'
import WorkerHomePage from '../src/pages/worker/home/index'
import { fetchCurrentWorker, fetchWorkerPages, workerLogout } from '../src/services/workerService'
import { ADMIN_SURFACES } from '../src/utils/adminPermission'
import {
  INBOUND_PAGE_ROUTE,
  PIECEWORK_PAGE_ROUTE,
  REPRINT_PAGE_ROUTE,
  REWORK_PAGE_ROUTE,
  SHIPMENT_ORDERS_PAGE_ROUTE,
  SHIPMENT_PAGE_ROUTE,
  WORKER_TAB_LOGIN_ROUTE,
} from '../src/utils/inbound/gaps'
import { listReadyShipmentOrders } from '../src/services/workerShipmentOrdersService'
import { listWorkerReworkOrders } from '../src/services/workerReworkService'
import {
  clearWorkerSession,
  getWorkerSessionId,
  setWorkerSessionId,
} from '../src/utils/workerSession'

const WORKER = {
  session_id: 'sess-worker-1',
  worker_id: 'w-1',
  worker_no: 'G001',
  worker_name: '张三',
}

const mockFetch = fetchCurrentWorker as jest.Mock
const mockLogout = workerLogout as jest.Mock
const mockPages = fetchWorkerPages as jest.Mock
const mockShipmentOrders = listReadyShipmentOrders as jest.Mock
const mockReworkOrders = listWorkerReworkOrders as jest.Mock

/** 有工人身份 + 服务端认出当前工人 ⇒ 落在工人首页的**正跑**形态 */
async function renderLoggedIn() {
  setWorkerSessionId(WORKER.session_id)
  mockFetch.mockResolvedValue({ success: true, data: WORKER })
  render(<WorkerHomePage />)
  await screen.findByText('工号 G001')
  // 🔴 菜单开关是**异步**读回来的（`fetchWorkerPages().then(...)`）⇒ 只等身份卡会与它赛跑
  //    （CI 上实测偶发红：断言跑在 fail-open 默认态上）。这里把所有待 settle 的微任务冲刷掉，
  //    让后面的入口断言读到的是**菜单应用之后**的那一版。
  await act(async () => {})
}

describe('WorkerHomePage 工人首页（issue #6467 判据 2）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    ;(Taro as any).__clearStorage()
    mockFetch.mockResolvedValue({ success: true, data: WORKER })
    mockLogout.mockResolvedValue(undefined)
    mockPages.mockResolvedValue({ pages: null, unread: false, unauthorized: false })
    mockShipmentOrders.mockResolvedValue({ success: true, data: { items: [] }, message: '' })
    mockReworkOrders.mockResolvedValue({ success: true, data: { orders: [] }, message: '' })
  })

  it('🔴 身份卡 = 服务端当前工人（工号 + 姓名），不是前端 state', async () => {
    await renderLoggedIn()

    expect(mockFetch).toHaveBeenCalledTimes(1)
    expect(screen.getByText('工号 G001')).toBeTruthy()
    expect(screen.getByText('张三')).toBeTruthy()
    // 红证：身份卡改读 `getCachedWorker()`（不调服务端）⇒ 本断言收到 0 次调用（红）
  })

  it('工人功能入口各自跳对路由（都走 gaps.ts 的路由常量，不写字面量）', async () => {
    await renderLoggedIn()

    fireEvent.click(screen.getByText('拍照入库'))
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: INBOUND_PAGE_ROUTE })

    fireEvent.click(screen.getByText('补打入库标签'))
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: REPRINT_PAGE_ROUTE })

    // 第 4 条（issue #6761）：#5648 的后端早已就绪，缺的就是这个入口
    fireEvent.click(screen.getByText('拍照发货'))
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: SHIPMENT_PAGE_ROUTE })

    // 待发货单（issue #7806 P1a）与返工记录（issue #7921）都是**只读名单页**
    fireEvent.click(screen.getByText('待发货单'))
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: SHIPMENT_ORDERS_PAGE_ROUTE })

    fireEvent.click(screen.getByText('返工记录'))
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: REWORK_PAGE_ROUTE })

    // 我的计件（issue #7934）：入口从**报工详情页**页头搬到本页（工人菜单）
    fireEvent.click(screen.getByText('我的计件'))
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: PIECEWORK_PAGE_ROUTE })

    // 路由常量本身与 app.config 的登记逐字一致（守卫 page-entry-reachability / G0 另核）
    expect(INBOUND_PAGE_ROUTE).toBe('/pages/worker/inbound/index')
    expect(REPRINT_PAGE_ROUTE).toBe('/pages/worker/reprint/index')
    expect(SHIPMENT_PAGE_ROUTE).toBe('/pages/worker/shipment/index')
    expect(PIECEWORK_PAGE_ROUTE).toBe('/pages/worker/piecework/index')
  })

  it('🔴 不出现任何商家面入口（问黄金策 / 数据 / 坐席 / 管理面 4 项 + 「我的」）', async () => {
    await renderLoggedIn()

    for (const merchantEntry of ['问黄金策', '数据', '坐席', '我的']) {
      expect({ merchantEntry, visible: screen.queryByText(merchantEntry) !== null }).toEqual({
        merchantEntry,
        visible: false,
      })
    }
    // 管理面 4 项的标签取自唯一真值（`ADMIN_SURFACES`），不手抄第二份名单
    for (const surface of ADMIN_SURFACES) {
      expect({ label: surface.label, visible: screen.queryByText(surface.label) !== null }).toEqual({
        label: surface.label,
        visible: false,
      })
    }
  })

  it('🔴 退出工人身份 ⇒ workerLogout() + 清本机工人态 + 回登录页的工人入口', async () => {
    await renderLoggedIn()
    expect(getWorkerSessionId()).toBe(WORKER.session_id)

    await act(async () => {
      fireEvent.click(screen.getByText('退出'))
    })

    // 服务端 session 必须结束（只清本机 ⇒ 下一个人扫码记到上一个人头上）
    expect(mockLogout).toHaveBeenCalledTimes(1)
    expect(getWorkerSessionId()).toBeNull()
    expect(Taro.redirectTo).toHaveBeenCalledWith({ url: WORKER_TAB_LOGIN_ROUTE })
  })

  it('无工人身份 ⇒ 不给工人功能入口，渲染引导 + 「去登录工人身份」', async () => {
    clearWorkerSession()
    mockFetch.mockResolvedValue({ success: false, message: '未登录工人身份' })

    render(<WorkerHomePage />)

    expect(await screen.findByText(/请先用工号 \+ PIN 登录工人身份/)).toBeTruthy()
    expect(screen.queryByText('返工记录')).toBeNull()
    expect(screen.queryByText('拍照发货')).toBeNull()
    expect(screen.queryByText('退出')).toBeNull()

    fireEvent.click(screen.getByText('去登录工人身份'))
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: WORKER_TAB_LOGIN_ROUTE })
  })

  it('服务端读不到当前工人（如 session 已失效）⇒ 回落成「未登录」而不是留着上一个人的名字', async () => {
    setWorkerSessionId('stale-session')
    mockFetch.mockResolvedValue({ success: false, message: '尚未登录工人身份或登录已失效' })

    render(<WorkerHomePage />)

    expect(await screen.findByText(/请先用工号 \+ PIN 登录工人身份/)).toBeTruthy()
    expect(screen.queryByText('张三')).toBeNull()
    expect(getWorkerSessionId()).toBeNull()
  })

  // ── issue #7920（2026-10-27 用户裁定）：工作台不再有「扫码报工」入口 ──
  it('🔴 「扫码报工」入口已移除：扫码由微信 / 手机相机承担，本页不再发射报工页入口', async () => {
    await renderLoggedIn()

    expect(screen.queryByText('扫码报工')).toBeNull()
    // 反向钉住：本页的跳转里**不许**再出现报工页（报工页只由外部扫码 302 → 启动器 redirectTo 到达）
    const urls = (Taro.navigateTo as jest.Mock).mock.calls.map((call) => String(call[0]?.url ?? ''))
    expect(urls.filter((url) => url.startsWith('/pages/worker/report/index'))).toEqual([])
  })

  // ── issue #7921：返工记录入口（工人档案的 `rework` 键） ──
  it('🔴 返工记录入口按工人档案的 `rework` 键显隐（勾了就出现）', async () => {
    mockPages.mockResolvedValue({ pages: ['report', 'rework'], unread: false, unauthorized: false })
    await renderLoggedIn()

    // 等待「菜单已应用」的可观察读数（收窄集里没有 to_ship ⇒ 待发货单消失），再断言返工记录在
    await waitFor(() => expect(screen.queryByText('待发货单')).toBeNull())
    expect(screen.getByText('返工记录')).toBeTruthy()
  })

  it('🔴 档案没勾 `rework` ⇒ 返工记录入口不出现（勾了才出现，不是恒显示）', async () => {
    mockPages.mockResolvedValue({ pages: ['report', 'to_ship'], unread: false, unauthorized: false })
    await renderLoggedIn()

    // 等待「菜单已应用」的可观察读数（收窄集里没有 shipment ⇒ 拍照发货消失），再断言返工记录不在
    await waitFor(() => expect(screen.queryByText('拍照发货')).toBeNull())
    expect(screen.queryByText('返工记录')).toBeNull()
    expect(screen.getByText('待发货单')).toBeTruthy()
  })

  // ── issue #7921：两条只读名单入口上的「待处理数」（红色数字） ──
  it('🔴 待处理数 = 服务端列表行数（>0 才显示红色数字）', async () => {
    mockShipmentOrders.mockResolvedValue({ success: true, data: { items: [{}, {}] }, message: '' })
    mockReworkOrders.mockResolvedValue({
      success: true,
      data: { orders: [{}, {}, {}] },
      message: '',
    })
    await renderLoggedIn()

    expect((await screen.findByTestId('worker-home-badge-to-ship')).textContent).toBe('2')
    expect((await screen.findByTestId('worker-home-badge-rework')).textContent).toBe('3')
  })

  it('🔴 读不到 / 没有待处理 ⇒ 不显示数字（绝不冒充 0）', async () => {
    mockShipmentOrders.mockResolvedValue({ success: false, message: '网络抖了一下' })
    mockReworkOrders.mockResolvedValue({ success: false, message: '网络抖了一下' })
    await renderLoggedIn()
    await act(async () => {})

    expect(screen.queryByTestId('worker-home-badge-to-ship')).toBeNull()
    expect(screen.queryByTestId('worker-home-badge-rework')).toBeNull()
  })
})
