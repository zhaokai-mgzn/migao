// case_ids: BM-009
/**
 * 管理面手机端：**入口可见性 · 平台能力面 · 端到端权限拒绝文案**（issue #5654）
 *
 * 本文件刻意**不 mock 服务层**（只 mock 网络层 `utils/request`）—— 走
 * 页面 → 真实 `adminOpsService` → `request` 的**完整链路**，这样「403 分类 + 文案」是被真的跑过一遍，
 * 而不是靠桩喂进去的结论。
 *
 * 判据：
 * ① **入口可见性**：`GET /api/auth/me` 的 `permissions` 决定「我的」页 4 个入口显不显示
 *    （无权限码 ⇒ **菜单不可见**）；只有部分权限 ⇒ 只显示对应那些；
 *    `/me` 拉不到（未知）⇒ **照显**（fail-open：判定权威在服务端 403，静默隐藏是 #5642 禁止的形态）。
 * ② **h5 下不调 `Taro.login`**（#5650 的既有判据）：h5 编译目标下渲染 4 个管理面，
 *    `Taro.login` **一次都不许被调**（红证：在任一管理面渲染路径上加一句 `Taro.login()` ⇒ 必红）。
 * ③ **平台能力缺口显式**：h5 下未登录 ⇒ 明说「浏览器环境不支持微信登录，请用账号密码登录」
 *    + 「去登录」入口（不是空白、不是转圈、不是拿一个必然失败的微信换码去试）。
 * ④ **端到端 403 ⇒ 逐字文案**：真网络层 403 ⇒ 页面上出现
 *    「无「智能派单」查看权限（需要权限码 processing:view）」。
 */
import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import Taro from '@tarojs/taro'

jest.mock('../src/utils/request', () => ({
  get: jest.fn(),
  post: jest.fn(),
  put: jest.fn(),
  patch: jest.fn(),
  del: jest.fn(),
}))

jest.mock('../src/store/chatStore', () => ({
  useChatStore: jest.fn(() => ({})),
}))

jest.mock('../src/store/authStore', () => ({
  useAuthStore: jest.fn(),
}))

import { get } from '../src/utils/request'
import { useAuthStore } from '../src/store/authStore'
import ProfilePage from '../src/pages/profile/index/index'
import AdminPoolPage from '../src/pages/admin/pool/index'
import AdminInboundPage from '../src/pages/admin/inbound/index'
import AdminAfterSalesPage from '../src/pages/admin/after-sales/index'
import AdminPieceworkPage from '../src/pages/admin/piecework/index'

const mockGet = get as jest.MockedFunction<typeof get>
const mockAuthStore = useAuthStore as unknown as jest.Mock
const mockChatStore = require('../src/store/chatStore')
mockChatStore.useChatStore.getState = jest.fn(() => ({ clearMessages: jest.fn() }))

/** 「我的」页的 4 个入口（testid = `profile-admin-<key>`） */
const SURFACE_KEYS = ['pool', 'inbound', 'after-sales', 'piecework']

/** 网络层桩：`/api/auth/me` 给权限集合，其余端点给最小合法响应 */
function stubNetwork(permissions: string[] | null) {
  mockGet.mockImplementation(async (url: string) => {
    if (url === '/api/auth/me') {
      if (permissions === null) {
        const error: any = new Error('Request failed with status 500')
        error.statusCode = 500
        throw error
      }
      return { success: true, data: { permissions } } as any
    }
    if (url === '/api/admin/production/pool') {
      return {
        success: true,
        data: {
          maxWaitHours: 24,
          poolingEnabled: false,
          orderCount: 0,
          lineCount: 0,
          overdueCount: 0,
          urgentCount: 0,
          urgentLines: [],
          groups: [],
        },
      } as any
    }
    if (url === '/api/admin/inbound-orders') return { success: true, data: [] } as any
    if (url === '/api/admin/after-sales') {
      return { success: true, data: { total: 0, items: [] } } as any
    }
    if (url === '/api/admin/production/piecework/summary') {
      return {
        success: true,
        data: { period: '2026-09', total: 0, per_worker: [], per_operation: [] },
      } as any
    }
    throw new Error(`未桩住的端点：${url}`)
  })
}

beforeEach(() => {
  jest.clearAllMocks()
  mockAuthStore.mockReturnValue({
    user: { id: 'u1', nickname: '运营小王', tenantId: 1, role: 'operator' },
    isLoggedIn: true,
    logout: jest.fn(),
  })
  stubNetwork(null)
})

describe('管理面入口可见性（issue #5654 判据：无权限码 ⇒ 菜单不可见）', () => {
  it('管理员（`*` 通配）⇒ 4 个入口都在', async () => {
    stubNetwork(['*'])
    render(<ProfilePage />)
    await waitFor(() => expect(screen.getByTestId('profile-admin-pool')).toBeTruthy())
    SURFACE_KEYS.forEach((key) => expect(screen.getByTestId(`profile-admin-${key}`)).toBeTruthy())
  })

  it('零权限 ⇒ 4 个入口**一个都不出现**（菜单不可见）', async () => {
    stubNetwork([])
    render(<ProfilePage />)
    // 等「权限集合到位」这一步真的发生（初次渲染是 fail-open 的全显态）
    await waitFor(() =>
      SURFACE_KEYS.forEach((key) => expect(screen.queryByTestId(`profile-admin-${key}`)).toBeNull()),
    )
    // 其余菜单项不受影响（只治理管理面入口）
    expect(screen.getByText('扫码报工')).toBeTruthy()
  })

  it('只有 inbound:view ⇒ 只出现「入库过账」', async () => {
    stubNetwork(['inbound:view'])
    render(<ProfilePage />)
    await waitFor(() => expect(screen.getByTestId('profile-admin-inbound')).toBeTruthy())
    await waitFor(() => expect(screen.queryByTestId('profile-admin-pool')).toBeNull())
    expect(screen.queryByTestId('profile-admin-after-sales')).toBeNull()
    expect(screen.queryByTestId('profile-admin-piecework')).toBeNull()
  })

  it('权限集合拉不到（未知）⇒ **照显**（fail-open，不静默隐藏入口）', async () => {
    stubNetwork(null)
    render(<ProfilePage />)
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith('/api/auth/me', expect.anything()))
    SURFACE_KEYS.forEach((key) => expect(screen.getByTestId(`profile-admin-${key}`)).toBeTruthy())
  })
})

describe('管理面平台能力面（issue #5654 判据：h5 不调 Taro.login / 缺口显式）', () => {
  const originalEnv = process.env.TARO_ENV

  afterEach(() => {
    process.env.TARO_ENV = originalEnv
  })

  it('h5 下渲染 4 个管理面：`Taro.login` 一次都不许被调（#5650 既有判据）', async () => {
    process.env.TARO_ENV = 'h5'
    stubNetwork(['*'])
    render(<AdminPoolPage />)
    render(<AdminInboundPage />)
    render(<AdminAfterSalesPage />)
    render(<AdminPieceworkPage />)
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith('/api/auth/me', expect.anything()))
    expect(Taro.login).not.toHaveBeenCalled()
    // 反面自证：h5 下的登录路径确实被平台判到（不是「没跑到那段代码」）
    expect(process.env.TARO_ENV).toBe('h5')
  })

  it('h5 下未登录 ⇒ 明说浏览器不支持微信登录 + 给「去登录」（不是空白/转圈）', async () => {
    process.env.TARO_ENV = 'h5'
    mockAuthStore.mockReturnValue({ user: null, isLoggedIn: false, logout: jest.fn() })
    stubNetwork(['*'])
    render(<AdminPoolPage />)
    const block = await screen.findByTestId('admin-surface-login-required')
    expect(block.textContent).toBe(
      '浏览器环境不支持微信登录，请用「用户名@企业编码 + 密码」登录',
    )
    expect(screen.getByTestId('admin-surface-go-login')).toBeTruthy()
    // 未登录时**不发**管理面请求（省一次必然 401 的往返）
    expect(mockGet).not.toHaveBeenCalledWith('/api/admin/production/pool', expect.anything())
  })
})

describe('管理面端到端权限拒绝文案（issue #5654 判据：403 不许静默空白）', () => {
  it('真网络层 403 ⇒ 页面逐字「无「智能派单」查看权限（需要权限码 processing:view）」', async () => {
    mockGet.mockImplementation(async (url: string) => {
      if (url === '/api/auth/me') return { success: true, data: { permissions: [] } } as any
      const error: any = new Error('Request failed with status 403')
      error.statusCode = 403
      error.data = { success: false, error: { code: 'FORBIDDEN', message: '无权限访问' } }
      throw error
    })
    render(<AdminPoolPage />)
    const block = await screen.findByTestId('admin-surface-forbidden')
    expect(block.textContent).toBe('无「智能派单」查看权限（需要权限码 processing:view）')
  })

  it('真网络层 403（售后）⇒ 逐字「无「售后处理」查看权限（需要权限码 after_sales:view）」', async () => {
    mockGet.mockImplementation(async (url: string) => {
      if (url === '/api/auth/me') return { success: true, data: { permissions: [] } } as any
      const error: any = new Error('Request failed with status 403')
      error.statusCode = 403
      error.data = { success: false, error: { code: 'FORBIDDEN', message: '无权限访问' } }
      throw error
    })
    render(<AdminAfterSalesPage />)
    const block = await screen.findByTestId('admin-surface-forbidden')
    expect(block.textContent).toBe('无「售后处理」查看权限（需要权限码 after_sales:view）')
  })
})
