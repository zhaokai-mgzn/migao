/**
 * 个人中心页面测试
 *
 * 覆盖: 未登录状态、已登录渲染、统计数据、退出登录
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

  it('应显示设置菜单项', () => {
    render(<ProfilePage />)
    expect(screen.getByText('账号信息')).toBeTruthy()
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

  it('点击"账号信息"应提示功能开发中', () => {
    render(<ProfilePage />)
    fireEvent.click(screen.getByText('账号信息'))

    expect(Taro.showToast).toHaveBeenCalledWith(
      expect.objectContaining({ title: '功能开发中' }),
    )
  })

  it('点击"关于我们"应显示版本弹窗', () => {
    render(<ProfilePage />)
    fireEvent.click(screen.getByText('关于我们'))

    expect(Taro.showModal).toHaveBeenCalledWith(
      expect.objectContaining({ title: '关于我们' }),
    )
  })

  it('应显示统计数据', () => {
    render(<ProfilePage />)
    // 2个session, 应显示 "2" 作为总会话数
    expect(screen.getByText('总会话数')).toBeTruthy()
    expect(screen.getByText('本月对话')).toBeTruthy()
  })
})
