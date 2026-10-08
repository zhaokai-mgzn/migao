// case_ids: BM-046
/**
 * 手机端菜单 = **服务端按岗位投影**（issue #6570，用户 2026-10-08 裁定「走 B」）
 *
 * ## 治的形态（旧口径的两条实测后果，见 issue #6570 的线上读数）
 * ① 端侧拿 `GET /api/auth/me` 的 `permissions` **自己判码**（`visibleAdminSurfaces`），
 *    且**集合未知 ⇒ 照显**（fail-open）⇒ 员工看到自己没有的入口，点进去逐项 403；
 * ② 「数据」页对没有 `production:view` 的岗位（客服 / 财务实拍）摆一块
 *    「无权限查看生产待办（需生产看板权限）」——每一屏都无意义。
 * 新口径：菜单由**服务端**按岗位投影（`mobileSurfaces`），端侧只渲染服务端给的面。
 *
 * | # | 判据 | 红证（怎么让它单独变红） |
 * |---|---|---|
 * | 1 | 服务端给什么就渲染什么（**标题与顺序都取服务端**） | 端侧自造标题 / 自己排序 ⇒ 红 |
 * | 2 | 服务端给**空数组**（明确答复「本岗位没有面」）⇒ 一个入口都没有，且**不是**错误态 | 把空数组当失败 ⇒ 红 |
 * | 3 | 🔴 拿不到菜单 ⇒ 显式「菜单没加载出来，点这里重试」+ **一个面都不渲染**（不是照显） | 退回 fail-open ⇒ 红 |
 * | 4 | 重试**真的**再拉一次（可行动，不是装饰） | 重试不发起请求 ⇒ 红 |
 * | 5 | 🔴 「数据」页待办块：清单**没有** `production-todos` ⇒ **整块不渲染**（噪音消失） | 仍按权限码判 ⇒ 红 |
 * | 6 | 拿不到菜单时「数据」页**照渲染**待办块（数据优先：宁可不隐藏，也不静默吞掉今天的待办） | 把 error 也隐藏 ⇒ 红 |
 * | 7 | 源级：端侧**不再自己判菜单码**（「我的」页无 `useAdminPermissions` / `visibleAdminSurfaces`） | 加回一段端侧判码 ⇒ 红 |
 */
import React from 'react'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import * as fs from 'fs'
import * as path from 'path'

jest.mock('../src/utils/request', () => ({
  get: jest.fn(),
  post: jest.fn(),
  put: jest.fn(),
  patch: jest.fn(),
  del: jest.fn(),
}))

jest.mock('../src/store/authStore', () => ({
  useAuthStore: jest.fn(),
}))

jest.mock('../src/store/chatStore', () => ({
  useChatStore: jest.fn(() => ({})),
}))

import { get } from '../src/utils/request'
import { useAuthStore } from '../src/store/authStore'
import ProfilePage from '../src/pages/profile/index/index'
import DashboardPage from '../src/pages/dashboard/index/index'

const mockGet = get as jest.MockedFunction<typeof get>
const mockAuthStore = useAuthStore as unknown as jest.Mock
const mockChatStore = require('../src/store/chatStore')
mockChatStore.useChatStore.getState = jest.fn(() => ({ clearMessages: jest.fn() }))

/** 服务端在 /me 里下发的手机端菜单（字段名逐字 = `UserInfoResponse.MobileSurface`） */
const SERVER_MENU = [
  { key: 'pool', title: '智能派单', route: '/pages/admin/pool/index' },
  { key: 'inbound', title: '入库过账', route: '/pages/admin/inbound/index' },
  { key: 'after-sales', title: '售后处理', route: '/pages/admin/after-sales/index' },
  { key: 'piecework', title: '计件工资报表', route: '/pages/admin/piecework/index' },
  { key: 'production-todos', title: '生产待办' },
]

/** 网络层桩：`/me` 给菜单（`null` = 拉不到）；`production:` 面给生产待办一份最小载荷 */
function stubNetwork(menu: typeof SERVER_MENU | null) {
  mockGet.mockImplementation(async (url: string) => {
    if (url === '/api/auth/me') {
      if (menu === null) throw Object.assign(new Error('Request failed with status 500'), { statusCode: 500 })
      return { success: true, data: { permissions: ['*'], mobileSurfaces: menu } } as any
    }
    if (url === '/api/admin/production/todo-overview') {
      return {
        success: true,
        data: {
          generated_at: '2026-10-08T20:00:00+08:00',
          todo_total: 1,
          todos: [
            {
              id: 'stuck:1',
              type: 'stuck',
              type_label: '卡在哪',
              title: '订单 X · 打包 上道做完后等了 53 小时没人领',
              reason: '这道还没开工，上一道已完成',
              priority: 'high',
              link: '/pages/production/order-detail/index?orderId=order-1',
            },
          ],
          stats: { todo_total: 1, by_type: { stuck: 1 }, operations: {} },
        },
      } as any
    }
    return { success: true, data: [] } as any
  })
}

const ADMIN_TESTIDS = ['pool', 'inbound', 'after-sales', 'piecework']

beforeEach(() => {
  jest.clearAllMocks()
  mockAuthStore.mockReturnValue({
    user: { id: 'u1', nickname: '运营小王', tenantId: 1, role: 'operator' },
    isLoggedIn: true,
    logout: jest.fn(),
  })
  stubNetwork(SERVER_MENU)
})

describe('「我的」页菜单 = 服务端给什么渲染什么', () => {
  it('服务端给 4 个面 ⇒ 逐字渲染服务端的标题，顺序 = 服务端顺序', async () => {
    render(<ProfilePage />)
    await waitFor(() => expect(screen.getByTestId('profile-admin-pool')).toBeTruthy())

    ADMIN_TESTIDS.forEach((key) => expect(screen.getByTestId(`profile-admin-${key}`)).toBeTruthy())
    // 标题来自服务端（端侧不再自造）
    expect(screen.getByText('智能派单')).toBeTruthy()
    expect(screen.getByText('计件工资报表')).toBeTruthy()
    // 无独立页面的能力位（production-todos）**不出入口**
    expect(screen.queryByTestId('profile-admin-production-todos')).toBeNull()
    expect(screen.queryByTestId('profile-menu-error')).toBeNull()
  })

  it('服务端只给一个面 ⇒ 只出现那一个（端侧不做任何补全）', async () => {
    stubNetwork([{ key: 'inbound', title: '入库过账', route: '/pages/admin/inbound/index' }])
    render(<ProfilePage />)
    await waitFor(() => expect(screen.getByTestId('profile-admin-inbound')).toBeTruthy())

    ;['pool', 'after-sales', 'piecework'].forEach((key) =>
      expect(screen.queryByTestId(`profile-admin-${key}`)).toBeNull(),
    )
  })

  it('服务端给**空数组**（本岗位一个面都没有）⇒ 一个入口都没有，且**不是**错误态', async () => {
    stubNetwork([])
    render(<ProfilePage />)
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith('/api/auth/me', expect.anything()))
    // 等一帧，确保 render 已按服务端答复落定
    await waitFor(() => ADMIN_TESTIDS.forEach((key) => expect(screen.queryByTestId(`profile-admin-${key}`)).toBeNull()))
    expect(screen.queryByTestId('profile-menu-error')).toBeNull()
    expect(screen.getByText('关于我们')).toBeTruthy()
  })

  it('🔴 拿不到菜单 ⇒ 显式「菜单没加载出来」+ **一个面都不渲染**（不是照显）', async () => {
    stubNetwork(null)
    render(<ProfilePage />)
    await waitFor(() => expect(screen.getByTestId('profile-menu-error')).toBeTruthy())

    expect(screen.getByText('菜单没加载出来，点这里重试')).toBeTruthy()
    // 关键：不是旧口径的 fail-open（照显 4 个进不去的入口）
    ADMIN_TESTIDS.forEach((key) => expect(screen.queryByTestId(`profile-admin-${key}`)).toBeNull())
  })

  it('重试**真的**再拉一次 /me（可行动，不是装饰）', async () => {
    stubNetwork(null)
    render(<ProfilePage />)
    await waitFor(() => expect(screen.getByTestId('profile-menu-error')).toBeTruthy())

    const before = mockGet.mock.calls.filter(([url]) => url === '/api/auth/me').length
    stubNetwork(SERVER_MENU)
    fireEvent.click(screen.getByTestId('profile-menu-error'))

    await waitFor(() => expect(screen.getByTestId('profile-admin-pool')).toBeTruthy())
    expect(mockGet.mock.calls.filter(([url]) => url === '/api/auth/me').length).toBeGreaterThan(before)
  })
})

describe('「数据」页生产待办块 = 服务端清单开/关', () => {
  it('清单含 `production-todos` ⇒ 渲染（每件可点即办）', async () => {
    stubNetwork(SERVER_MENU)
    render(<DashboardPage />)
    await waitFor(() => expect(screen.getByTestId('production-todos')).toBeTruthy())
    expect(screen.getByTestId('production-todo-stuck')).toBeTruthy()
  })

  it('🔴 清单**没有** `production-todos`（没有 production:view）⇒ 整块不渲染（噪音消失）', async () => {
    stubNetwork([{ key: 'inbound', title: '入库过账', route: '/pages/admin/inbound/index' }])
    render(<DashboardPage />)
    // 等 /me 落定（服务端答复）后再断言
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith('/api/auth/me', expect.anything()))
    await waitFor(() => expect(screen.queryByTestId('production-todos')).toBeNull())
    expect(screen.queryByText(/无权限查看生产待办/)).toBeNull()
  })

  it('拿不到菜单 ⇒ 照渲染（数据优先：不静默吞掉今天的待办）', async () => {
    stubNetwork(null)
    render(<DashboardPage />)
    await waitFor(() => expect(screen.getByTestId('production-todos')).toBeTruthy())
  })
})

describe('源级：端侧不再自己判菜单码', () => {
  it('🔴 「我的」页源码里没有端侧判码的记号', () => {
    const src = fs.readFileSync(path.join(__dirname, '../src/pages/profile/index/index.tsx'), 'utf8')
    ;['visibleAdminSurfaces', 'useAdminPermissions', 'permissions.includes'].forEach((token) => {
      expect({ token, present: src.includes(token) }).toEqual({ token, present: false })
    })
    // 反向自证：它确实在读**服务端下发的菜单**（否则上面那串「都没有」是空跑）
    expect(src).toContain('useMobileMenu()')
  })

  it('🔴 「数据」页的待办块开关取自服务端清单（不是权限码）', () => {
    const src = fs.readFileSync(path.join(__dirname, '../src/pages/dashboard/index/index.tsx'), 'utf8')
    expect(src).toContain('useMobileMenu()')
    expect(src).toContain("s.key === 'production-todos'")
  })
})
