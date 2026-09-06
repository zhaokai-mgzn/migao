// case_ids: BM-001, UI-015
/**
 * 个人中心页面测试（B 端商家版，issue #2977）
 *
 * 覆盖: 未登录状态、已登录渲染（角色/租户）、菜单、退出登录
 *
 * B 端语义：聚焦员工身份（昵称/角色/租户）+ 关于/隐私 + 退出；
 * 不展示 C 端消费者功能（我的订单/我的售后/绑定手机号——B 端员工管理他人的订单）
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
const mockClearMessages = jest.fn()

jest.mock('../src/store/authStore', () => ({
  useAuthStore: jest.fn(() => ({
    user: { id: 'u1', nickname: '运营小王', avatar: null, tenant_id: 1, role: 'operator', tenantName: '词元通达' },
    isLoggedIn: true,
    logout: mockLogout,
  })),
}))

jest.mock('../src/store/chatStore', () => ({
  useChatStore: jest.fn(() => ({})),
}))

// chatStore.getState() 也需要 mock
const chatStoreMock = require('../src/store/chatStore')
chatStoreMock.useChatStore.getState = jest.fn(() => ({
  clearMessages: mockClearMessages,
}))

import Taro from '@tarojs/taro'
import ProfilePage from '../src/pages/profile/index/index'
import { useAuthStore } from '../src/store/authStore'

describe('ProfilePage', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    // 重置 mock 到已登录状态（B 端员工）
    ;(useAuthStore as unknown as jest.Mock).mockReturnValue({
      user: { id: 'u1', nickname: '运营小王', avatar: null, tenant_id: 1, role: 'operator', tenantName: '词元通达' },
      isLoggedIn: true,
      logout: mockLogout,
    })
  })

  it('已登录应显示员工昵称', () => {
    render(<ProfilePage />)
    expect(screen.getByText('运营小王')).toBeTruthy()
  })

  it('应显示角色标签（operator → 运营经理）', () => {
    render(<ProfilePage />)
    expect(screen.getByText('运营经理')).toBeTruthy()
  })

  it('应显示租户名', () => {
    render(<ProfilePage />)
    expect(screen.getByText('词元通达')).toBeTruthy()
  })

  it('应显示头像首字母', () => {
    render(<ProfilePage />)
    expect(screen.getByText('运')).toBeTruthy()
  })

  it('应显示菜单项（关于我们/隐私协议）', () => {
    render(<ProfilePage />)
    expect(screen.getByText('关于我们')).toBeTruthy()
    expect(screen.getByText('隐私协议')).toBeTruthy()
  })

  it('B 端员工不展示 C 端消费者功能（无订单/售后/绑定手机号入口）', () => {
    render(<ProfilePage />)
    expect(screen.queryByText(/我的订单/)).toBeNull()
    expect(screen.queryByText(/我的售后/)).toBeNull()
    expect(screen.queryByText(/绑定手机号/)).toBeNull()
  })

  it('应显示退出登录按钮', () => {
    render(<ProfilePage />)
    expect(screen.getByText('退出登录')).toBeTruthy()
  })

  it('未登录应显示"请先登录"', () => {
    ;(useAuthStore as unknown as jest.Mock).mockReturnValue({
      user: null,
      isLoggedIn: false,
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

  it('点击"隐私协议"应显示弹窗', () => {
    render(<ProfilePage />)
    fireEvent.click(screen.getByText('隐私协议'))

    expect(Taro.showModal).toHaveBeenCalledWith(
      expect.objectContaining({ title: '隐私协议' }),
    )
  })

  it('退出登录：确认后调用 logout + 清空对话 + 跳登录页', () => {
    ;(Taro.showModal as jest.Mock).mockImplementation((opts) => {
      opts.success({ confirm: true })
      return Promise.resolve({ confirm: true })
    })

    render(<ProfilePage />)
    fireEvent.click(screen.getByText('退出登录'))

    expect(mockLogout).toHaveBeenCalled()
    expect(mockClearMessages).toHaveBeenCalled()
    expect(Taro.redirectTo).toHaveBeenCalledWith({
      url: '/pages/auth/login/index',
    })
  })
})