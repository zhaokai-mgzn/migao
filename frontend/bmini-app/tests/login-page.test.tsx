/**
 * B 端员工登录页测试（米宝商家端，issue #5485 起＝账号密码）
 *
 * 覆盖: 渲染（账号 + 密码 + 登录按钮）、提交调用、空输入拦截、
 *       成功跳转、失败不跳转、密码框遮蔽、微信授权按钮已退场
 */
// case_ids: AU-001, AU-003, AU-006, BM-001, BM-002
import React from 'react'
import { render, screen, fireEvent, act } from '@testing-library/react'

// Mock stores
const mockEmployeeLoginAction = jest.fn()
const mockLogin = jest.fn()
const mockGetState = jest.fn()

jest.mock('../src/store/authStore', () => ({
  useAuthStore: Object.assign(
    jest.fn(() => ({
      isLoading: false,
      login: mockLogin,
      employeeLoginAction: mockEmployeeLoginAction,
    })),
    // 登录页在动作之后读的是**最新**状态（首登强制改密 ⇒ 去改密页）
    { getState: () => mockGetState() },
  ),
}))

import Taro from '@tarojs/taro'
import LoginPage from '../src/pages/auth/login/index'

const IDENTIFIER_PLACEHOLDER = '如 zhangsan@acme'
const PASSWORD_PLACEHOLDER = '请输入密码'

/** 填表：用户名@企业编码 + 密码 */
function fillForm(identifier: string, password: string) {
  fireEvent.change(screen.getByPlaceholderText(IDENTIFIER_PLACEHOLDER), {
    target: { value: identifier },
  })
  fireEvent.change(screen.getByPlaceholderText(PASSWORD_PLACEHOLDER), {
    target: { value: password },
  })
}

/** 点击登录：等异步提交链路走完（switchTab 在 `await` 之后才发生） */
async function clickLogin() {
  await act(async () => {
    fireEvent.click(screen.getByText('登录'))
  })
}

describe('LoginPage', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    // 缺省：普通员工（不强制改密）⇒ 直接进主界面
    mockGetState.mockReturnValue({ user: { mustChangePassword: false } })
  })

  it('应渲染品牌、账号密码两个输入框与登录按钮', () => {
    render(<LoginPage />)

    expect(screen.getByText('米宝 · 商家助手')).toBeTruthy()
    expect(screen.getByText('经营数据 · AI 客服 · 移动坐席')).toBeTruthy()
    expect(screen.getByText('用户名@企业编码')).toBeTruthy()
    expect(screen.getByText('密码')).toBeTruthy()
    expect(screen.getByText('登录')).toBeTruthy()
    expect(screen.getByPlaceholderText(IDENTIFIER_PLACEHOLDER)).toBeTruthy()
  })

  it('密码框是遮蔽输入（password → type="password"）', () => {
    render(<LoginPage />)

    const pwd = screen.getByPlaceholderText(PASSWORD_PLACEHOLDER) as HTMLInputElement
    expect(pwd.getAttribute('type')).toBe('password')
  })

  it('填表提交 → employeeLoginAction(identifier, password)（AU-001 / BM-001）', async () => {
    mockEmployeeLoginAction.mockResolvedValueOnce(true)

    render(<LoginPage />)
    fillForm('zhangsan@acme', 'init-pass-123')
    await clickLogin()

    expect(mockEmployeeLoginAction).toHaveBeenCalledWith('zhangsan@acme', 'init-pass-123')
  })

  it('账号两侧空白应去掉后再提交（不解析租户，只做去空白）', async () => {
    mockEmployeeLoginAction.mockResolvedValueOnce(true)

    render(<LoginPage />)
    fillForm('  zhangsan@acme  ', 'init-pass-123')
    await clickLogin()

    expect(mockEmployeeLoginAction).toHaveBeenCalledWith('zhangsan@acme', 'init-pass-123')
  })

  it('登录成功应跳转到问米宝页', async () => {
    mockEmployeeLoginAction.mockResolvedValueOnce(true)

    render(<LoginPage />)
    fillForm('zhangsan@acme', 'init-pass-123')
    await clickLogin()

    expect(Taro.switchTab).toHaveBeenCalledWith({
      url: '/pages/chat/index/index',
    })
  })

  it('mustChangePassword=true ⇒ 不进主界面，直接转首登改密页（AU-006）', async () => {
    mockEmployeeLoginAction.mockResolvedValueOnce(true)
    mockGetState.mockReturnValue({ user: { mustChangePassword: true } })

    render(<LoginPage />)
    fillForm('zhangsan@acme', 'init-pass-123')
    await clickLogin()

    // 改密前后端只放行白名单接口 ⇒ 放进主界面只会每个功能都 403（用户读成「小程序坏了」）
    expect(Taro.switchTab).not.toHaveBeenCalled()
    expect(Taro.redirectTo).toHaveBeenCalledWith({ url: '/pages/auth/change-password/index' })
  })

  it('mustChangePassword 非真 ⇒ 直接进主界面', async () => {
    mockEmployeeLoginAction.mockResolvedValueOnce(true)
    mockGetState.mockReturnValue({ user: { mustChangePassword: false, id: 'emp-1' } })

    render(<LoginPage />)
    fillForm('zhangsan@acme', 'init-pass-123')
    await clickLogin()

    expect(Taro.redirectTo).not.toHaveBeenCalledWith({ url: '/pages/auth/change-password/index' })
    expect(Taro.switchTab).toHaveBeenCalledWith({ url: '/pages/chat/index/index' })
  })

  it('账号为空 → 本地拦截并提示，不发请求', async () => {
    render(<LoginPage />)
    fillForm('   ', 'init-pass-123')
    await clickLogin()

    expect(mockEmployeeLoginAction).not.toHaveBeenCalled()
    expect(Taro.showToast).toHaveBeenCalledWith(
      expect.objectContaining({ title: expect.stringContaining('用户名@企业编码') }),
    )
  })

  it('密码为空 → 本地拦截并提示，不发请求', async () => {
    render(<LoginPage />)
    fillForm('zhangsan@acme', '')
    await clickLogin()

    expect(mockEmployeeLoginAction).not.toHaveBeenCalled()
    expect(Taro.showToast).toHaveBeenCalledWith(
      expect.objectContaining({ title: expect.stringContaining('密码') }),
    )
  })

  it('登录失败（后端统一 401 文案）→ 不跳转（AU-003）', async () => {
    mockEmployeeLoginAction.mockResolvedValueOnce(false)

    render(<LoginPage />)
    fillForm('zhangsan@acme', 'wrong-pass')
    await clickLogin()

    // 失败原因由 authStore 内部 showToast（同一 401 文案），页面不自行编造区分文案、不跳转
    expect(mockEmployeeLoginAction).toHaveBeenCalledTimes(1)
    expect(Taro.switchTab).not.toHaveBeenCalled()
  })

  it('微信授权手机号按钮已整条退场（BM-002）', () => {
    render(<LoginPage />)

    expect(screen.queryByText('微信授权手机号登录')).toBeNull()
    expect(screen.queryByText(/微信授权/)).toBeNull()
    expect(document.body.innerHTML).not.toContain('getPhoneNumber')
  })

  it('点击服务条款应显示弹窗', () => {
    render(<LoginPage />)

    fireEvent.click(screen.getByText('《服务条款》'))

    expect(Taro.showModal).toHaveBeenCalledWith(
      expect.objectContaining({ title: '服务条款' }),
    )
  })

  it('点击隐私协议应显示弹窗，且文案不再承诺手机号用途', () => {
    render(<LoginPage />)

    fireEvent.click(screen.getByText('《隐私协议》'))

    expect(Taro.showModal).toHaveBeenCalledWith(
      expect.objectContaining({ title: '隐私协议' }),
    )
    const content = (Taro.showModal as jest.Mock).mock.calls[0][0].content as string
    expect(content).not.toContain('手机号')
  })
})