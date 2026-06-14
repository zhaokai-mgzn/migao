/**
 * 登录页面测试
 *
 * 覆盖: 渲染、登录按钮点击、自动登录跳转、loading状态
 */
import React from 'react'
import { render, screen, fireEvent, act } from '@testing-library/react'

// Mock stores
const mockLogin = jest.fn()
const mockCheckAuth = jest.fn(() => false)

jest.mock('../src/store/authStore', () => ({
  useAuthStore: jest.fn(() => ({
    isLoading: false,
    checkAuth: mockCheckAuth,
    login: mockLogin,
  })),
}))

jest.mock('../src/utils/constants', () => ({
  DEFAULT_TENANT_ID: 1,
}))

import Taro from '@tarojs/taro'
import LoginPage from '../src/pages/auth/login/index'

describe('LoginPage', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    mockCheckAuth.mockReturnValue(false)
  })

  it('应渲染品牌标题和登录按钮', () => {
    render(<LoginPage />)

    expect(screen.getByText('小布 · 智能购物助手')).toBeTruthy()
    expect(screen.getByText('微信一键登录')).toBeTruthy()
    expect(screen.getByText('您的专属智能购物助手')).toBeTruthy()
  })

  it('应渲染服务条款和隐私协议链接', () => {
    render(<LoginPage />)

    expect(screen.getByText('《服务条款》')).toBeTruthy()
    expect(screen.getByText('《隐私协议》')).toBeTruthy()
  })

  it('点击登录按钮应调用 login', async () => {
    mockLogin.mockResolvedValueOnce(true)

    render(<LoginPage />)

    await act(async () => {
      fireEvent.click(screen.getByText('微信一键登录'))
    })

    expect(mockLogin).toHaveBeenCalledWith(1) // DEFAULT_TENANT_ID
  })

  it('登录成功应跳转到对话页', async () => {
    mockLogin.mockResolvedValueOnce(true)

    render(<LoginPage />)

    await act(async () => {
      fireEvent.click(screen.getByText('微信一键登录'))
    })

    expect(Taro.switchTab).toHaveBeenCalledWith({
      url: '/pages/chat/index/index',
    })
  })

  it('已登录应自动跳转', () => {
    mockCheckAuth.mockReturnValue(true)

    render(<LoginPage />)

    expect(Taro.switchTab).toHaveBeenCalledWith({
      url: '/pages/chat/index/index',
    })
  })

  it('Loading 状态应显示"登录中..."', () => {
    const { useAuthStore } = require('../src/store/authStore')
    ;(useAuthStore as jest.Mock).mockReturnValue({
      isLoading: true,
      checkAuth: mockCheckAuth,
      login: mockLogin,
    })

    render(<LoginPage />)

    expect(screen.getByText('登录中...')).toBeTruthy()
  })

  it('点击服务条款应显示弹窗', () => {
    render(<LoginPage />)

    fireEvent.click(screen.getByText('《服务条款》'))

    expect(Taro.showModal).toHaveBeenCalledWith(
      expect.objectContaining({ title: '服务条款' }),
    )
  })

  it('点击隐私协议应显示弹窗', () => {
    render(<LoginPage />)

    fireEvent.click(screen.getByText('《隐私协议》'))

    expect(Taro.showModal).toHaveBeenCalledWith(
      expect.objectContaining({ title: '隐私协议' }),
    )
  })
})
