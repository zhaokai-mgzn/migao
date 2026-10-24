// case_ids: BM-040
/**
 * 「数据」页：**失败态 ≠ 空态**（issue #6666 判据 6）
 *
 * ## 治的形态（审计称，读码复核为真 —— 同页两套口径）
 *
 * `dashboardService.getDashboardStats()` 失败 ⇒ 返回 `null`；`getPendingTasks()` 失败 ⇒ 返回 `[]`
 * ⇒ 页面把「拉不到」渲染成「五张卡全是 `--`、无错误行、无重试」和「暂无待办，AI 正在处理中」。
 * 而**同一页**的生产待办块早已做对三态（`{status:'ok'|'forbidden'|'error'}`）——
 * 「看不到」被说成「没有」，正是本页自己文档里禁止的形态。
 *
 * ## 判据
 *
 * | # | 判据 | 回归时会怎么红 |
 * |---|---|---|
 * | 1 | 经营数据 `error` ⇒ 显式错误行 + **可点重试**（再发一次请求），且不渲染数字卡（不摆 `--`） | 吞成 `--` ⇒ 红 |
 * | 2 | 经营数据 `forbidden`(403) ⇒ 「无权限」，不是「全是 `--`」 | 403 当空 ⇒ 红 |
 * | 3 | 待办 `error` ⇒ 显式错误行；**不得**出现「暂无待办，AI 正在处理中」 | 失败当空 ⇒ 红 |
 * | 4 | 待办 `forbidden` ⇒ 「无权限查看待办」，不是「暂无待办」 | 403 当空 ⇒ 红 |
 * | 5 | 待办 `ok + 0 条` ⇒ 才是「暂无待办，AI 正在处理中」（空态语义只留给真空） | 把失败也渲染成空 ⇒ 红 |
 * | 6 | 全部 ok ⇒ 数字卡照常渲染（没有把正常路径改坏） | 误伤正常路径 ⇒ 红 |
 */
import React from 'react'
import '@testing-library/jest-dom'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

jest.mock('../src/utils/request', () => ({
  get: jest.fn(),
  post: jest.fn(),
  put: jest.fn(),
  patch: jest.fn(),
  del: jest.fn(),
}))

jest.mock('../src/store/authStore', () => ({
  useAuthStore: jest.fn(() => ({ user: { id: 'u1', nickname: '王老板', tenantId: 1 } })),
}))

// 底栏 tab（服务端 `mobileTabs`）：默认给「数据」这一格 —— 全页权限门（2026-10-18 裁定）
// 只在**服务端说没有这一格**时才拦；本文件其余用例测的是「有权限」的正常路径。
let mockMenu: { state: string; surfaces: any[]; tabs: any[] } = {
  state: 'ok',
  surfaces: [],
  tabs: [{ key: 'dashboard', title: '数据', route: '/pages/dashboard/index/index' }],
}
jest.mock('../src/components/admin/useMobileMenu', () => ({
  useMobileMenu: () => mockMenu,
}))

jest.mock('../src/utils/roleGuard', () => ({
  useMerchantSurfaceGuard: jest.fn(),
}))

import { get } from '../src/utils/request'
import DashboardPage from '../src/pages/dashboard/index/index'

const mockGet = get as jest.MockedFunction<typeof get>

const FULL_STATS = {
  todaySales: 123400,
  todayOrders: 12,
  monthRevenue: 5678000,
  todaySalesChange: 1.5,
  todayOrdersChange: -0.5,
  monthRevenueChange: 3.2,
  totalCustomers: 88,
  newCustomersToday: 3,
  activeSessions: 4,
  aiSessionRate: 66.7,
  totalProducts: 21,
  totalOrders: 30,
  totalTickets: 2,
  pendingShipOrders: 5,
  processingPendingOrders: 1,
  lowStockItems: 0,
}

const TODO_OK = {
  generated_at: '2026-10-10T09:00:00+08:00',
  todo_total: 0,
  todos: [],
  stats: {
    todo_total: 0,
    by_type: { to_schedule: 0, stuck: 0, to_ship: 0 },
    operations: { not_started: 0, in_progress: 0, completed: 0 },
    stuck_threshold_hours: 4,
    threshold_source: 'default',
    scan: { order_scan_limit: 50, truncated: false },
  },
}

const forbidden = () => Object.assign(new Error('403'), { statusCode: 403 })
const boom = () => new Error('network down')

type Mode = 'ok' | 'forbidden' | 'error'

function stub(opts: { stats?: Mode; tasks?: Mode; tasksData?: any[]; statsData?: any } = {}) {
  const { stats = 'ok', tasks = 'ok', tasksData = [], statsData = FULL_STATS } = opts
  mockGet.mockImplementation(async (url: string) => {
    if (url.includes('/api/admin/dashboard/stats')) {
      if (stats === 'forbidden') throw forbidden()
      if (stats === 'error') throw boom()
      return { success: true, data: statsData } as any
    }
    if (url.includes('/pending-tasks')) {
      if (tasks === 'forbidden') throw forbidden()
      if (tasks === 'error') throw boom()
      return { success: true, data: tasksData } as any
    }
    if (url.includes('/production/todo-overview')) return { success: true, data: TODO_OK } as any
    return { success: true, data: {} } as any
  })
}

const statsCalls = () => mockGet.mock.calls.filter((c) => String(c[0]).includes('/api/admin/dashboard/stats')).length

beforeEach(() => {
  jest.clearAllMocks()
  // 每个用例都从「有权限」起跑（个别用例自己改）
  mockMenu = {
    state: 'ok',
    surfaces: [],
    tabs: [{ key: 'dashboard', title: '数据', route: '/pages/dashboard/index/index' }],
  }
})

describe('「数据」页三态（issue #6666 判据 6）', () => {
  it('🔴 经营数据失败 ⇒ 显式错误行 + 可点重试（再发一次请求），且不摆 `--` 蒙人', async () => {
    stub({ stats: 'error' })
    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByTestId('dashboard-stats-error')).toBeInTheDocument())
    // 不渲染数字卡（「拿不到就别说」，不摆 `--` 这种占位）
    expect(screen.queryByText('今日销售额')).toBeNull()
    expect(screen.getByTestId('dashboard-stats-error').textContent).toMatch(/重试/)

    const before = statsCalls()
    fireEvent.click(screen.getByTestId('dashboard-stats-error'))
    await waitFor(() => expect(statsCalls()).toBeGreaterThan(before))
  })

  it('🔴 经营数据 403 ⇒ 「无权限」，不是「全是 `--`」', async () => {
    stub({ stats: 'forbidden' })
    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByTestId('dashboard-stats-forbidden')).toBeInTheDocument())
    expect(screen.getByTestId('dashboard-stats-forbidden').textContent).toMatch(/无权限/)
    expect(screen.queryByText('今日销售额')).toBeNull()
  })

  it('🔴 待办失败 ⇒ 显式错误行，**不得**说成「暂无待办，AI 正在处理中」', async () => {
    stub({ tasks: 'error' })
    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByTestId('dashboard-tasks-error')).toBeInTheDocument())
    expect(screen.queryByText('暂无待办，AI 正在处理中')).toBeNull()
  })

  it('🔴 待办 403 ⇒ 「无权限查看待办」', async () => {
    stub({ tasks: 'forbidden' })
    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByTestId('dashboard-tasks-forbidden')).toBeInTheDocument())
    expect(screen.getByTestId('dashboard-tasks-forbidden').textContent).toMatch(/无权限/)
    expect(screen.queryByText('暂无待办，AI 正在处理中')).toBeNull()
  })

  it('真·空态（ok + 0 条）⇒ 才说「暂无待办，AI 正在处理中」', async () => {
    stub({ tasks: 'ok', tasksData: [] })
    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByText('暂无待办，AI 正在处理中')).toBeInTheDocument())
    expect(screen.queryByTestId('dashboard-tasks-error')).toBeNull()
  })

  it('全部 ok ⇒ 数字卡照常渲染（正常路径没被改坏）', async () => {
    stub()
    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByText('今日销售额')).toBeInTheDocument())
    expect(screen.getByText('今日订单')).toBeInTheDocument()
    expect(screen.queryByTestId('dashboard-stats-error')).toBeNull()
    expect(screen.queryByTestId('dashboard-stats-forbidden')).toBeNull()
  })

  // ══════════════════════════════════════════════════════════════════════════
  // 底栏常驻（用户 2026-10-18 裁定）⇒ 没权限也能点进「数据」页：整页给
  // **与「问黄金策」同一做法**的授权缺失态（逐字「需要管理员授权」+ 可行动引导），
  // 而不是让几张卡各印一句「无权限」。——判定只读服务端 `mobileTabs`。
  // ══════════════════════════════════════════════════════════════════════════
  it('🔴 服务端说没有「数据」这一格 ⇒ 整页「需要管理员授权」+ 引导，不渲染经营数据', async () => {
    mockMenu = { state: 'ok', surfaces: [], tabs: [{ key: 'chat', title: '问黄金策', route: '/pages/chat/index/index' }] }
    stub()
    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByTestId('dashboard-gate-denied')).toBeInTheDocument())
    expect(screen.getByText('需要管理员授权')).toBeInTheDocument()
    expect(screen.getByText('请联系企业管理员在「员工管理」中为你开通「经营数据」权限')).toBeInTheDocument()
    expect(screen.queryByText('今日销售额')).toBeNull()
  })

  it('对照读数：拿不到菜单（loading / error）⇒ **不拦**（拿不到 ≠ 没权限）', async () => {
    mockMenu = { state: 'error', surfaces: [], tabs: [] }
    stub()
    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByText('今日销售额')).toBeInTheDocument())
    expect(screen.queryByTestId('dashboard-gate-denied')).toBeNull()
  })
})
