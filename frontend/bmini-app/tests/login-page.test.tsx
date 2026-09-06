/**
 * 登录页面测试（B 端商家版，issue #2977）
 *
 * 覆盖: 渲染、getPhoneNumber 授权回调登录、拒绝授权、loading 状态
 */
// case_ids: BM-001
import React from 'react'
import { render, screen, fireEvent, act } from '@testing-library/react'

// Mock stores
const mockBminiLoginAction = jest.fn()
const mockLogin = jest.fn()

jest.mock('../src/store/authStore', () => ({
  useAuthStore: jest.fn(() => ({
    isLoading: false,
    login: mockLogin,
    bminiLoginAction: mockBminiLoginAction,
  })),
}))

import Taro from '@tarojs/taro'
import LoginPage from '../src/pages/auth/login/index'

// 触发 Button open-type="getPhoneNumber" 的 onGetPhoneNumber 回调
function firePhoneAuth(detail: any) {
  const btn: any = screen.getByText('微信授权手机号登录')
  const node: any = (btn as any).closest?.('button') || btn.parentElement
  const propsKey = Object.keys(node).find((k: string) => k.startsWith('__reactProps$'))
  const onGetPhoneNumber = propsKey ? node[propsKey].onGetPhoneNumber : (node as any).onGetPhoneNumber
  return act(async () => {
    onGetPhoneNumber({ detail })
  })
}

describe('LoginPage', () => {
  beforeEach(() => {
    jest.clearAllMocks()
  })

  it('应渲染 B 端品牌标题和授权登录按钮', () => {
    render(<LoginPage />)

    expect(screen.getByText('米宝 · 商家助手')).toBeTruthy()
    expect(screen.getByText('微信授权手机号登录')).toBeTruthy()
    expect(screen.getByText('经营数据 · AI 客服 · 移动坐席')).toBeTruthy()
  })

  it('应渲染服务条款和隐私协议链接', () => {
    render(<LoginPage />)

    expect(screen.getByText('《服务条款》')).toBeTruthy()
    expect(screen.getByText('《隐私协议》')).toBeTruthy()
  })

  it('getPhoneNumber 授权成功 → 调用 bminiLoginAction(code)', async () => {
    mockBminiLoginAction.mockResolvedValueOnce(true)

    render(<LoginPage />)

    await firePhoneAuth({ code: 'phone-auth-code-1', errMsg: 'getPhoneNumber:ok' })

    expect(mockBminiLoginAction).toHaveBeenCalledWith('phone-auth-code-1')
  })

  it('登录成功应跳转到问米宝页', async () => {
    mockBminiLoginAction.mockResolvedValueOnce(true)

    render(<LoginPage />)

    await firePhoneAuth({ code: 'phone-auth-code-1', errMsg: 'getPhoneNumber:ok' })

    expect(Taro.switchTab).toHaveBeenCalledWith({
      url: '/pages/chat/index/index',
    })
  })

  it('用户拒绝授权 → 提示且不调用登录', async () => {
    render(<LoginPage />)

    await firePhoneAuth({ errMsg: 'getPhoneNumber:fail user deny' })

    expect(mockBminiLoginAction).not.toHaveBeenCalled()
    expect(Taro.showToast).toHaveBeenCalledWith(
      expect.objectContaining({ title: expect.stringContaining('授权') }),
    )
  })

  it('授权无 code → 提示重试且不调用登录', async () => {
    render(<LoginPage />)

    await firePhoneAuth({ errMsg: 'getPhoneNumber:ok' })

    expect(mockBminiLoginAction).not.toHaveBeenCalled()
    expect(Taro.showToast).toHaveBeenCalledWith(
      expect.objectContaining({ title: expect.stringContaining('重试') }),
    )
  })

  it('登录失败（手机号未匹配员工）→ 展示错误', async () => {
    mockBminiLoginAction.mockResolvedValueOnce(false)

    render(<LoginPage />)

    await firePhoneAuth({ code: 'phone-auth-code-x', errMsg: 'getPhoneNumber:ok' })

    // authStore 内 toast 展示后端错误，此处不跳转
    expect(Taro.switchTab).not.toHaveBeenCalled()
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