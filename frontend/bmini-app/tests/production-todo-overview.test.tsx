// case_ids: BM-006
// ⚠️ 用例关联（如实登记）：BM-006 = B 端小程序**生产页族**（页面消费服务端下发的生产对象 +
// 跳转进 `/pages/production/index/index`）—— 本页每条待办的落脚点正是那个页面。
// **未固化项**：本能力（生产概览「待办优先」页 / 端点）**没有专属行为用例** ——
// `.github/cases/**` 本轮由并行包独占（写面冲突隔离），补新用例 + 跑 `render_cases.py`
// 需另开一包；已登记在 PR body 的「未固化项」一节。
/**
 * 生产概览（待办优先）—— B 端「数据」Tab（issue #5641）
 *
 * 链路：打开「数据」Tab → `GET /api/admin/production/todo-overview`（服务端规则引擎聚合）
 *       → **第一屏**先答「今天要处理的 N 件事」（每条可点即办）→ 经营数字退第二屏。
 *
 * 断言口径（对应 issue 验收标准）：
 * ① 每一条待办都**逐字来自服务端**（前端不生成、不重算、不归因）；
 * ② 三种空态互不混淆：`ok+0` ⇒「今天没有待处理」/ `403` ⇒「无权限」/ 失败 ⇒「加载失败」；
 * ③ 每条待办可点进**已声明的页面路由**（拿 `app.config.ts` 的 pages 当判据 ⇒ 不是死链）；
 * ④ 第一屏条数与第二屏计数**同源一致**；
 * ⑤ 三态进度照给，但「做了一半」**不作告警**（无紧急标记）。
 */
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import * as fs from 'fs'
import * as path from 'path'

jest.mock('../src/utils/request', () => ({
  get: jest.fn(),
  post: jest.fn(),
  put: jest.fn(),
  del: jest.fn(),
}))

jest.mock('../src/store/authStore', () => ({
  useAuthStore: jest.fn(() => ({ user: { id: 'u1', nickname: '王老板', tenantId: 1 } })),
}))

import Taro from '@tarojs/taro'
import { get } from '../src/utils/request'
import DashboardPage from '../src/pages/dashboard/index/index'
import {
  getProductionTodoOverview,
  productionTodoTargetUrl,
  type ProductionTodo,
  type ProductionTodoOverview,
} from '../src/services/dashboardService'

const mockGet = get as jest.MockedFunction<typeof get>

/** 页面路由真值源：跳转目标必须在这份 pages 清单里（拿它当「不是死链」的判据）。 */
const APP_CONFIG_SOURCE = fs.readFileSync(
  path.join(__dirname, '../src/app.config.ts'),
  'utf8',
)

const PRODUCTION_PAGE = '/pages/production/index/index'

const TODOS: ProductionTodo[] = [
  {
    id: 'stuck:op-9',
    type: 'stuck',
    type_label: '卡在哪',
    priority: 'high',
    title: '订单 SO20260926001 · 精裁 · 布帘 上道做完后等了 6.0 小时没人领',
    reason: '这道还没开工（没报过工），上一道已完成，已等待 6.0 小时（超过阈值 4.0 小时，来源：default）',
    criterion: 'stuck_not_started_over_threshold',
    link: `${PRODUCTION_PAGE}?orderId=order-1`,
    target: { kind: 'operation', id: 'op-9', order_id: 'order-1' },
    evidence: { state: 'not_started', stalled_hours: 6, threshold_hours: 4, threshold_source: 'default' },
  },
  {
    id: 'to_ship:order-2',
    type: 'to_ship',
    type_label: '待发货',
    priority: 'high',
    title: '订单 SO20260926002 加工单已完成，可以发货了',
    reason: '含加工项且加工单已完成，订单仍未发货',
    criterion: 'processing_completed_order_not_shipped',
    link: `${PRODUCTION_PAGE}?orderId=order-2`,
    evidence: { order_status: 'producing', processing_completed: true },
  },
  {
    id: 'to_schedule:order-3',
    type: 'to_schedule',
    type_label: '待排产',
    priority: 'medium',
    title: '订单 SO20260926003 已确认，还没排产',
    reason: '订单已确认且含加工项，但该单还没有任何工序实例，需要排产',
    criterion: 'order_confirmed_without_operations',
    link: `${PRODUCTION_PAGE}?orderId=order-3`,
    evidence: { order_status: 'confirmed', operation_instance_count: 0 },
  },
]

function overview(todos: ProductionTodo[] = TODOS): ProductionTodoOverview {
  const byType: Record<string, number> = { to_schedule: 0, stuck: 0, to_ship: 0 }
  todos.forEach(todo => {
    byType[todo.type] = (byType[todo.type] ?? 0) + 1
  })
  return {
    generated_at: '2026-09-26T18:00:00+08:00',
    todo_total: todos.length,
    todos,
    stats: {
      todo_total: todos.length,
      by_type: byType,
      operations: { not_started: 5, in_progress: 2, completed: 8 },
      stuck_threshold_hours: 4,
      threshold_source: 'default',
      scan: { order_scan_limit: 50, truncated: false },
    },
  }
}

/** 网络层桩：按路径分发（页面一次并发拉三个端点）。 */
function stubNetwork(payload: ProductionTodoOverview) {
  mockGet.mockImplementation(async (url: string) => {
    if (url === '/api/admin/production/todo-overview') {
      return { success: true, data: payload } as any
    }
    if (url === '/api/admin/dashboard/stats') {
      return { success: true, data: { todaySales: 0, todayOrders: 0, monthRevenue: 0 } } as any
    }
    return { success: true, data: [] } as any
  })
}

beforeEach(() => {
  jest.clearAllMocks()
})

describe('生产概览（待办优先）页', () => {
  test('第一屏先答「今天要处理的 N 件事」，且条数 = 真正渲染出来的条数', async () => {
    stubNetwork(overview())
    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByText(/今天要处理的 3 件事/)).toBeTruthy())

    // 三条待办逐条渲染（类型来自服务端 type/type_label，不是前端按条件拼的）
    expect(screen.getByTestId('production-todo-stuck')).toBeTruthy()
    expect(screen.getByTestId('production-todo-to_ship')).toBeTruthy()
    expect(screen.getByTestId('production-todo-to_schedule')).toBeTruthy()
    // 文案逐字来自服务端（「上道做完后等了 N 小时没人领」是服务端规则引擎算的，前端不生成）
    expect(screen.getByText(/上道做完后等了 6\.0 小时没人领/)).toBeTruthy()
    expect(screen.getByText(/超过阈值 4\.0 小时，来源：default/)).toBeTruthy()
  })

  test('每件可点即办：点一下跳**服务端给的**页面路由，且该路由在 app.config 里已声明（不是死链）', async () => {
    stubNetwork(overview())
    render(<DashboardPage />)
    await waitFor(() => expect(screen.getByTestId('production-todo-stuck')).toBeTruthy())

    fireEvent.click(screen.getByTestId('production-todo-stuck'))

    expect(Taro.navigateTo).toHaveBeenCalledTimes(1)
    const url = (Taro.navigateTo as jest.Mock).mock.calls[0][0].url as string
    expect(url).toBe(`${PRODUCTION_PAGE}?orderId=order-1`)
    // 死链判据：URL 的页面部分必须在 app.config.ts 的 pages 清单里
    // （Taro 口径：pages 清单不带前导 `/`，navigateTo 的 url 带 —— 归一后再比）
    const page = url.split('?')[0].replace(/^\//, '')
    expect(APP_CONFIG_SOURCE).toContain(`'${page}'`)
  })

  test('🔴 空态如实：今天没有待处理；页面不出现 undefined / NaN 这类占位', async () => {
    stubNetwork(overview([]))
    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByText('今天没有待处理')).toBeTruthy())
    expect(screen.queryByTestId('production-todo-stuck')).toBeNull()
    expect(document.body.textContent).not.toMatch(/undefined|NaN/)
  })

  test('🔴 403 不当空态：无权限 ⇒ 显示无权限，**不**冒充「今天没有待处理」', async () => {
    mockGet.mockImplementation(async (url: string) => {
      if (url === '/api/admin/production/todo-overview') {
        throw Object.assign(new Error('Request failed with status 403'), { statusCode: 403 })
      }
      return { success: true, data: [] } as any
    })
    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByText(/无权限查看生产待办/)).toBeTruthy())
    expect(screen.queryByText('今天没有待处理')).toBeNull()
  })

  test('🔴 失败不当空态：加载失败 ⇒ 如实说失败，也**不**冒充「今天没有待处理」', async () => {
    mockGet.mockImplementation(async (url: string) => {
      if (url === '/api/admin/production/todo-overview') {
        throw Object.assign(new Error('boom'), { statusCode: 500 })
      }
      return { success: true, data: [] } as any
    })
    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByText(/生产待办加载失败/)).toBeTruthy())
    expect(screen.queryByText('今天没有待处理')).toBeNull()
  })

  test('🔴 第一屏条数与第二屏计数一致（同源聚合，不出现「第一屏 N 件、点进去 M 件」）', async () => {
    stubNetwork(overview())
    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByTestId('production-todo-total')).toBeTruthy())

    const firstScreen = screen.getAllByTestId(/^production-todo-(stuck|to_ship|to_schedule)$/)
    const secondScreenText = screen.getByTestId('production-todo-total').textContent ?? ''
    const secondScreenTotal = Number(secondScreenText.match(/今天要处理的 (\d+) 件/)?.[1])

    expect(firstScreen).toHaveLength(3)
    expect(secondScreenTotal).toBe(firstScreen.length)
    expect(secondScreenText).toContain('待排产 1')
    expect(secondScreenText).toContain('卡在哪 1')
    expect(secondScreenText).toContain('待发货 1')
  })

  test('三态进度照给，但「做了一半」**不作告警**（进度块里没有紧急标记）', async () => {
    stubNetwork(overview())
    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByTestId('production-progress')).toBeTruthy())

    const progress = screen.getByTestId('production-progress')
    expect(progress.textContent).toContain('没开工 5')
    expect(progress.textContent).toContain('做了一半 2')
    expect(progress.textContent).toContain('已完成 8')
    expect(progress.textContent).not.toContain('紧急')
    // 阈值来源透传（端点不另设阈值 ⇒ 页面上「阈值从哪来」可见）
    expect(progress.textContent).toContain('系统兜底默认值')
  })

  test('服务层：拉取结果是三态（ok / forbidden / error），403 与「空」可区分', async () => {
    stubNetwork(overview([]))
    await expect(getProductionTodoOverview()).resolves.toMatchObject({ status: 'ok' })

    mockGet.mockImplementation(async () => {
      throw Object.assign(new Error('403'), { statusCode: 403 })
    })
    await expect(getProductionTodoOverview()).resolves.toEqual({ status: 'forbidden' })

    mockGet.mockImplementation(async () => {
      throw new Error('network down')
    })
    await expect(getProductionTodoOverview()).resolves.toEqual({ status: 'error' })
  })

  test('死链防护：服务端没给合法页面路由 ⇒ 该条不可点（不给点进去是空白的入口）', () => {
    expect(productionTodoTargetUrl({ ...TODOS[0], link: '' })).toBeNull()
    expect(productionTodoTargetUrl({ ...TODOS[0], link: 'https://example.com/x' })).toBeNull()
    expect(productionTodoTargetUrl(TODOS[0])).toBe(`${PRODUCTION_PAGE}?orderId=order-1`)
  })
})
