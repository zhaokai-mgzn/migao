// case_ids: BM-047
/**
 * 坐席页：底栏常驻之后，没权限 = **「问黄金策」同一做法**（用户 2026-10-18 裁定）
 *
 * ## 治的形态
 *
 * 底栏不再按权限删格 ⇒ 没有 `agent:session` 的员工**也能进本页**。改前两层都在骗人：
 * ① `agentSessionService.getAgentSessions` 把**任何失败**吞成「空清单」；
 * ② 页面对失败没有 catch ⇒ 403 要么永远转圈，要么被画成「队列空闲，AI 正在处理中」。
 * 两条合起来 = **把「看不到」说成「没有」**（§31 P3 的同族：故障被画成业务事实）。
 *
 * ## 判据（每条都能单独变红）
 *
 * | # | 判据 | 红证（怎么让它单独变红） |
 * |---|---|---|
 * | 1 | 接口 403 ⇒ `sessions-gate-denied`：逐字「需要管理员授权」+ 「…在「员工管理」中为你开通「移动坐席」权限」；**不得**出现「队列空闲」 | 把 403 当空态 / 只印一句无权限 ⇒ 红 |
 * | 2 | 对照读数：200 空队列 ⇒ 正常渲染「队列空闲」，**不**恒显授权缺失态 | 授权门恒显 / 判断反了 ⇒ 红 |
 * | 3 | 非 403 失败 ⇒ `sessions-error`（「加载失败，点此重试」），既不是授权缺失态也不是空态 | 把 500 当无权限 / 当空态 ⇒ 红 |
 * | 4 | 🔴 服务端 `mobileTabs` 里没有 `sessions` ⇒ 整页授权缺失态（即使接口恰好还能读） | 只看接口、不看服务端清单 ⇒ 红 |
 * | 5 | 对照读数：服务端给了 `sessions` ⇒ 不拦（正常渲染队列） | 权限门恒显 ⇒ 红 |
 * | 6 | `loading` / `error`（拿不到菜单）⇒ **不拦**（拿不到 ≠ 没权限） | 把「未知」当「无权」⇒ 红 |
 */
import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'

jest.mock('../src/utils/request', () => ({
  get: jest.fn(),
  post: jest.fn(),
  put: jest.fn(),
  patch: jest.fn(),
  del: jest.fn(),
}))

// 底栏与本判据无关（它自己有整套类级守卫：tests/merchant-tabbar.test.tsx）——
// 桩掉，避免它再去打 /api/auth/me
jest.mock('../src/components/MerchantTabBar', () => ({
  __esModule: true,
  default: () => null,
}))

// 服务端下发的底栏 tab（`mobileTabs`）：默认「菜单没拿到」⇒ 不拦，交给接口 403 三态。
// 判据 4/5 自己改成「服务端明确答复」的两种形态。
let mockMenu: { state: string; surfaces: any[]; tabs: any[] } = { state: 'error', surfaces: [], tabs: [] }
jest.mock('../src/components/admin/useMobileMenu', () => ({
  useMobileMenu: () => mockMenu,
}))

import { get } from '../src/utils/request'
import SessionsPage from '../src/pages/sessions/index/index'

const mockGet = get as jest.MockedFunction<typeof get>

/** 403 的形态：`utils/request` 抛出的 Error 带 `statusCode`（与 dashboardService 同源） */
const forbidden = () => Object.assign(new Error('Request failed with status 403'), { statusCode: 403 })

describe('坐席页三态（底栏一律可见之后，无权限也必须说人话）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    mockMenu = { state: 'error', surfaces: [], tabs: [] }
  })

  it('无 agent:session（接口 403）⇒ 与「问黄金策」同一做法：「需要管理员授权」+ 可行动引导', async () => {
    mockGet.mockRejectedValue(forbidden())
    render(<SessionsPage />)

    await waitFor(() => expect(screen.getByTestId('sessions-gate-denied')).toBeTruthy())
    expect(screen.getByText('需要管理员授权')).toBeTruthy()
    expect(screen.getByText('请联系企业管理员在「员工管理」中为你开通「移动坐席」权限')).toBeTruthy()
    expect(screen.queryByText('队列空闲，AI 正在处理中')).toBeNull()
  })

  it('对照读数：有权限（200 空队列）⇒ 正常渲染「队列空闲」，不恒显授权缺失态', async () => {
    mockGet.mockResolvedValue({ success: true, data: { items: [], total: 0 } } as never)
    render(<SessionsPage />)

    await waitFor(() => expect(screen.getByText('队列空闲，AI 正在处理中')).toBeTruthy())
    expect(screen.queryByTestId('sessions-gate-denied')).toBeNull()
  })

  it('非 403 失败 ⇒ 「加载失败，点此重试」（既不是授权缺失态，也不是空态）', async () => {
    mockGet.mockRejectedValue(new Error('Request failed with status 500'))
    render(<SessionsPage />)

    await waitFor(() => expect(screen.getByTestId('sessions-error')).toBeTruthy())
    expect(screen.getByText('坐席队列加载失败，点此重试')).toBeTruthy()
    expect(screen.queryByTestId('sessions-gate-denied')).toBeNull()
    expect(screen.queryByText('队列空闲，AI 正在处理中')).toBeNull()
  })

  // ══════════════════════════════════════════════════════════════════════════
  // 底栏常驻（用户 2026-10-18 裁定）⇒ 没权限也能点进来：整页给授权缺失态。
  // 判定只读**服务端** `mobileTabs`（`MobileSurfaces.visibleTabsFor` 的投影），端侧不判权限码。
  // ══════════════════════════════════════════════════════════════════════════
  it('🔴 服务端说没有「坐席」这一格 ⇒ 整页「需要管理员授权」（即使接口恰好还能读）', async () => {
    mockMenu = { state: 'ok', surfaces: [], tabs: [{ key: 'chat', title: '问黄金策', route: '/pages/chat/index/index' }] }
    mockGet.mockResolvedValue({ success: true, data: { items: [], total: 0 } } as never)
    render(<SessionsPage />)

    await waitFor(() => expect(screen.getByTestId('sessions-gate-denied')).toBeTruthy())
    expect(screen.getByText('需要管理员授权')).toBeTruthy()
    expect(screen.queryByText('队列空闲，AI 正在处理中')).toBeNull()
  })

  it('对照读数：服务端给了「坐席」这一格 ⇒ 不拦（正常渲染队列）', async () => {
    mockMenu = {
      state: 'ok',
      surfaces: [],
      tabs: [{ key: 'sessions', title: '坐席', route: '/pages/sessions/index/index' }],
    }
    mockGet.mockResolvedValue({ success: true, data: { items: [], total: 0 } } as never)
    render(<SessionsPage />)

    await waitFor(() => expect(screen.getByText('队列空闲，AI 正在处理中')).toBeTruthy())
    expect(screen.queryByTestId('sessions-gate-denied')).toBeNull()
  })
})
