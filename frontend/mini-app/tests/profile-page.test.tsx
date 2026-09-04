// case_ids: OR-001, AS-001, UI-015
/**
 * 个人中心页面测试
 *
 * 覆盖: 未登录状态、已登录渲染、统计数据、退出登录
 *
 * UI-015: 移除「账号信息」占位入口（功能开发中 → 占位消失，避免 POC 演示露馅）
 */
import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'

// Mock Taro
jest.mock('@tarojs/taro', () => {
  const storage: Record<string, any> = {}
  return {
    __esModule: true,
    default: {
      showToast: jest.fn(),
      showModal: jest.fn(() => Promise.resolve({ confirm: true })),
      redirectTo: jest.fn(),
      switchTab: jest.fn(),
      getStorageSync: jest.fn((k: string) => storage[k] ?? ''),
      setStorageSync: jest.fn((k: string, v: any) => { storage[k] = v }),
      removeStorageSync: jest.fn((k: string) => { delete storage[k] }),
      __clearStorage: () => { Object.keys(storage).forEach(k => delete storage[k]) },
    },
    useDidShow: jest.fn(),
  }
})

const mockLogout = jest.fn()
const mockSetUser = jest.fn()
const mockClearMessages = jest.fn()
const mockBindMiniPhone = jest.fn()

jest.mock('../src/store/authStore', () => ({
  useAuthStore: jest.fn(() => ({
    user: { id: 'u1', nickname: '测试用户', avatar: null, tenant_id: 1 },
    isLoggedIn: true,
    setUser: mockSetUser,
    logout: mockLogout,
  })),
}))

jest.mock('../src/store/chatStore', () => ({
  useChatStore: jest.fn(() => ({
    sessions: [
      { id: 's1', created_at: new Date().toISOString() },
      { id: 's2', created_at: '2023-01-01T00:00:00Z' },
    ],
  })),
}))

// chatStore.getState() 也需要 mock
const chatStoreMock = require('../src/store/chatStore')
chatStoreMock.useChatStore.getState = jest.fn(() => ({
  clearMessages: mockClearMessages,
}))

jest.mock('../src/services/userService', () => ({
  getUserInfo: jest.fn(),
  bindMiniPhone: (...args: any[]) => mockBindMiniPhone(...args),
}))

jest.mock('../src/services/productService', () => ({
  getMyOrders: jest.fn(() => Promise.resolve([
    { id: 'o1', order_no: 'ORD-1001', status: 'shipped', status_text: '已发货', total_amount: 299.5, created_at: '2026-06-01T10:00:00Z' },
  ])),
  getMyTickets: jest.fn(() => Promise.resolve([
    { id: 't1', ticket_no: 'AS-001', status: 'pending', ticket_type: 'refund', created_at: '2026-06-01T10:00:00Z' },
    { id: 't2', ticket_no: 'AS-002', status: 'processing', ticket_type: 'return', created_at: '2026-06-02T10:00:00Z' },
  ])),
}))

import Taro from '@tarojs/taro'
import ProfilePage from '../src/pages/profile/index/index'
import { useAuthStore } from '../src/store/authStore'

describe('ProfilePage', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    // 重置 mock 到已登录状态
    ;(useAuthStore as unknown as jest.Mock).mockReturnValue({
      user: { id: 'u1', nickname: '测试用户', avatar: null, tenant_id: 1 },
      isLoggedIn: true,
      setUser: mockSetUser,
      logout: mockLogout,
    })
  })

  it('已登录应显示用户昵称', () => {
    render(<ProfilePage />)
    expect(screen.getByText('测试用户')).toBeTruthy()
  })

  it('已登录应显示用户 ID', () => {
    render(<ProfilePage />)
    expect(screen.getByText('ID: u1')).toBeTruthy()
  })

  it('应显示头像首字母', () => {
    render(<ProfilePage />)
    expect(screen.getByText('测')).toBeTruthy()
  })

  it('应显示设置菜单项（账号信息占位已移除，UI-015）', () => {
    render(<ProfilePage />)
    // UI-015：无「功能开发中」占位入口残留
    expect(screen.queryByText('账号信息')).toBeNull()
    expect(screen.getByText('关于我们')).toBeTruthy()
    expect(screen.getByText('隐私协议')).toBeTruthy()
  })

  it('应显示退出登录按钮', () => {
    render(<ProfilePage />)
    expect(screen.getByText('退出登录')).toBeTruthy()
  })

  it('未登录应显示"请先登录"', () => {
    ;(useAuthStore as unknown as jest.Mock).mockReturnValue({
      user: null,
      isLoggedIn: false,
      setUser: mockSetUser,
      logout: mockLogout,
    })

    render(<ProfilePage />)
    expect(screen.getByText('请先登录')).toBeTruthy()
    expect(screen.getByText('去登录')).toBeTruthy()
  })

  it('未登录点击"去登录"应跳转', () => {
    ;(useAuthStore as unknown as jest.Mock).mockReturnValue({
      user: null,
      isLoggedIn: false,
      setUser: mockSetUser,
      logout: mockLogout,
    })

    render(<ProfilePage />)
    fireEvent.click(screen.getByText('去登录'))

    expect(Taro.redirectTo).toHaveBeenCalledWith({
      url: '/pages/auth/login/index',
    })
  })

  it('点击"关于我们"应显示版本弹窗', () => {
    render(<ProfilePage />)
    fireEvent.click(screen.getByText('关于我们'))

    expect(Taro.showModal).toHaveBeenCalledWith(
      expect.objectContaining({ title: '关于我们' }),
    )
  })

  it('应显示我的订单与售后入口', async () => {
    render(<ProfilePage />)
    expect(screen.getByText(/我的订单/)).toBeTruthy()
    expect(screen.getByText(/我的售后/)).toBeTruthy()
    // 订单数据渲染（异步）
    await screen.findByText('ORD-1001')
    await screen.findByText('AS-001')
    // issue #2857: 售后工单状态/类型中文展示（refund→退款 / return→退货 / pending→待处理 / processing→处理中）
    await screen.findByText(/退款 · 待处理/)
    await screen.findByText(/退货 · 处理中/)
    // 不出现英文 raw 值残留
    expect(screen.queryByText(/refund|return|pending|processing/)).toBeNull()
  })

  it('点击订单应唤起对话追问进度', async () => {
    render(<ProfilePage />)
    await screen.findByText('ORD-1001')
    fireEvent.click(screen.getByText('ORD-1001'))
    expect(Taro.switchTab).toHaveBeenCalledWith({ url: '/pages/chat/index/index' })
  })

  it('未绑定手机号应显示绑定入口', () => {
    render(<ProfilePage />)
    expect(screen.getByText(/绑定手机号/)).toBeTruthy()
  })

  it('已绑定手机号应显示脱敏手机号（不显示绑定按钮）', () => {
    ;(useAuthStore as unknown as jest.Mock).mockReturnValue({
      user: { id: 'u1', nickname: '测试用户', avatar: null, tenant_id: 1, phone: '13900139000' },
      isLoggedIn: true,
      setUser: mockSetUser,
      logout: mockLogout,
    })
    render(<ProfilePage />)
    expect(screen.getByText('📱 139****9000')).toBeTruthy()
    expect(screen.queryByText(/绑定手机号/)).toBeNull()
  })

  it('getPhoneNumber 授权成功 → 调 bindMiniPhone 并更新 user', async () => {
    mockBindMiniPhone.mockResolvedValueOnce({ phone: '13900139000', boundOrders: 2 })
    render(<ProfilePage />)

    const btn = screen.getByText(/绑定手机号/)
    // Taro Button 的 props（含 onGetPhoneNumber）暴露在 DOM 节点的 __reactProps$ key 上
    const node: any = (btn as any).closest('button')
    const propsKey = Object.keys(node).find((k) => k.startsWith('__reactProps$'))
    const onGetPhoneNumber = propsKey ? node[propsKey].onGetPhoneNumber : null
    expect(onGetPhoneNumber).toBeTruthy()
    // 模拟微信授权成功回调 e.detail.code
    await onGetPhoneNumber({ detail: { code: 'wx-phone-code', errMsg: 'getPhoneNumber:ok' } })
    await Promise.resolve()
    expect(mockBindMiniPhone).toHaveBeenCalledWith('wx-phone-code')
    // setUser 以新 phone 更新
    expect(mockSetUser).toHaveBeenCalledWith(
      expect.objectContaining({ phone: '13900139000' }),
    )
  })

  it('getPhoneNumber 授权取消 → 不调 bindMiniPhone', async () => {
    mockBindMiniPhone.mockClear()
    render(<ProfilePage />)
    const btn = screen.getByText(/绑定手机号/)
    const node: any = (btn as any).closest('button')
    const propsKey = Object.keys(node).find((k) => k.startsWith('__reactProps$'))
    const onGetPhoneNumber = propsKey ? node[propsKey].onGetPhoneNumber : null
    if (onGetPhoneNumber) {
      await onGetPhoneNumber({ detail: { errMsg: 'getPhoneNumber:fail user deny' } })
    }
    expect(mockBindMiniPhone).not.toHaveBeenCalled()
  })
})
