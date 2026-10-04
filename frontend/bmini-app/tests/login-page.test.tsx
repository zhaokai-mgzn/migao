/**
 * B 端登录页测试（米宝商家端，issue #5485 起＝账号密码；issue #5721 加管理员短信入口）
 *
 * 覆盖: 渲染（账号 + 密码 + 登录按钮）、提交调用、空输入拦截、
 *       成功跳转、失败不跳转、密码框遮蔽、微信授权按钮已退场、
 *       两个入口的切换、管理员「手机号 + 验证码」链路（发码 / 冷却 / 提交 / 失败不跳转）
 */
// case_ids: AU-001, AU-003, AU-006, BM-001, BM-002, BM-027
import React from 'react'
import { render, screen, fireEvent, act } from '@testing-library/react'

// Mock stores
const mockEmployeeLoginAction = jest.fn()
const mockSmsLoginAction = jest.fn()
const mockLogin = jest.fn()
const mockGetState = jest.fn()
// 发码是**副作用调用**（不进 store），页面直接从 utils/auth 取 ⇒ 这里 mock 掉整模块
const mockSendSmsCode = jest.fn()

jest.mock('../src/store/authStore', () => ({
  useAuthStore: Object.assign(
    jest.fn(() => ({
      isLoading: false,
      login: mockLogin,
      employeeLoginAction: mockEmployeeLoginAction,
      smsLoginAction: mockSmsLoginAction,
    })),
    // 登录页在动作之后读的是**最新**状态（首登强制改密 ⇒ 去改密页）
    { getState: () => mockGetState() },
  ),
}))

jest.mock('../src/utils/auth', () => ({
  sendSmsCode: (...args: unknown[]) => mockSendSmsCode(...args),
}))

import Taro from '@tarojs/taro'
import LoginPage from '../src/pages/auth/login/index'

const IDENTIFIER_PLACEHOLDER = '如 zhangsan@acme'
const PASSWORD_PLACEHOLDER = '请输入密码'
const PHONE_PLACEHOLDER = '请输入管理员手机号'
const CODE_PLACEHOLDER = '请输入验证码'

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

    expect(screen.getByText('米宝 · 企业智能生产管家')).toBeTruthy()
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

// ══════════════════════════════════════════════════════════════════════════════
// 管理员短信入口（issue #5721）
//
// 为什么这条链必须有：管理员身份在设计上是「手机号 + 短信」，而 #5485 之后 H5 只留了
// 员工入口（用户名@企业编码 + 密码），存量账号 `users.username` 又为 NULL
// ⇒ 管理员在**唯一可达的 H5** 上无路可走（线上实测：用户拿 13800138000 + 万能码登录失败）。
// ══════════════════════════════════════════════════════════════════════════════
describe('LoginPage · 管理员短信入口（issue #5721）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    // `clearAllMocks` 不清**排队中的** `mockResolvedValueOnce` ⇒ 上一条用例没用掉的返回值会漏到下一条，
    // 把「失败」装成「成功」（实测：服务端拒绝那条因此判红）。这里显式 reset 掉实现队列。
    mockEmployeeLoginAction.mockReset()
    mockSmsLoginAction.mockReset()
    mockSendSmsCode.mockReset()
    mockGetState.mockReturnValue({ user: { mustChangePassword: false } })
    mockSendSmsCode.mockResolvedValue({ success: true })
  })

  /** 切到管理员 tab（两个 tab 的文案互不相同，取精确文本） */
  function switchToAdminTab() {
    fireEvent.click(screen.getByText('管理员登录'))
  }

  /** 填管理员表单 */
  function fillAdminForm(phone: string, code: string) {
    fireEvent.change(screen.getByPlaceholderText(PHONE_PLACEHOLDER), {
      target: { value: phone },
    })
    fireEvent.change(screen.getByPlaceholderText(CODE_PLACEHOLDER), {
      target: { value: code },
    })
  }

  it('两个入口并列渲染，默认停在员工入口（员工字段在、管理员字段不在）', () => {
    render(<LoginPage />)

    expect(screen.getByText('员工登录')).toBeTruthy()
    expect(screen.getByText('管理员登录')).toBeTruthy()
    expect(screen.getByPlaceholderText(IDENTIFIER_PLACEHOLDER)).toBeTruthy()
    expect(screen.queryByPlaceholderText(PHONE_PLACEHOLDER)).toBeNull()
  })

  it('切到管理员入口 ⇒ 渲染手机号 + 验证码 + 获取验证码，员工字段退场', () => {
    render(<LoginPage />)
    switchToAdminTab()

    expect(screen.getByText('手机号')).toBeTruthy()
    expect(screen.getByText('验证码')).toBeTruthy()
    expect(screen.getByText('获取验证码')).toBeTruthy()
    expect(screen.queryByPlaceholderText(IDENTIFIER_PLACEHOLDER)).toBeNull()
    expect(screen.queryByPlaceholderText(PASSWORD_PLACEHOLDER)).toBeNull()
  })

  it('未填手机号就点获取验证码 ⇒ 本地拦截并提示，不发请求', async () => {
    render(<LoginPage />)
    switchToAdminTab()

    await act(async () => {
      fireEvent.click(screen.getByText('获取验证码'))
    })

    expect(mockSendSmsCode).not.toHaveBeenCalled()
    expect(Taro.showToast).toHaveBeenCalledWith(
      expect.objectContaining({ title: expect.stringContaining('手机号') }),
    )
  })

  it('点获取验证码 ⇒ sendSmsCode(phone)，并进入冷却（按钮变「…s 后重发」且不重复发）', async () => {
    render(<LoginPage />)
    switchToAdminTab()

    fireEvent.change(screen.getByPlaceholderText(PHONE_PLACEHOLDER), {
      target: { value: '13800138000' },
    })
    await act(async () => {
      fireEvent.click(screen.getByText('获取验证码'))
    })

    expect(mockSendSmsCode).toHaveBeenCalledWith('13800138000')
    // 冷却：文案换成倒计时，期间再点不再发（服务端另有频控，这里是端侧的省事层）
    const cooling = screen.queryByText('获取验证码')
    expect(cooling).toBeNull()
    await act(async () => {
      fireEvent.click(screen.getByText(/后重发/))
    })
    expect(mockSendSmsCode).toHaveBeenCalledTimes(1)
  })

  it('发码失败 ⇒ 展示**服务端文案**且不进冷却（不把失败装成成功）', async () => {
    mockSendSmsCode.mockResolvedValueOnce({ success: false, error: '短信发送过于频繁，请稍后再试' })

    render(<LoginPage />)
    switchToAdminTab()
    fireEvent.change(screen.getByPlaceholderText(PHONE_PLACEHOLDER), {
      target: { value: '13800138000' },
    })
    await act(async () => {
      fireEvent.click(screen.getByText('获取验证码'))
    })

    expect(Taro.showToast).toHaveBeenCalledWith(
      expect.objectContaining({ title: '短信发送过于频繁，请稍后再试' }),
    )
    expect(screen.getByText('获取验证码')).toBeTruthy()
  })

  it('空输入提交被本地拦下（手机号 / 验证码都拦）', async () => {
    render(<LoginPage />)
    switchToAdminTab()

    await act(async () => {
      fireEvent.click(screen.getByText('登录'))
    })
    expect(mockSmsLoginAction).not.toHaveBeenCalled()

    fireEvent.change(screen.getByPlaceholderText(PHONE_PLACEHOLDER), {
      target: { value: '13800138000' },
    })
    await act(async () => {
      fireEvent.click(screen.getByText('登录'))
    })
    expect(mockSmsLoginAction).not.toHaveBeenCalled()
    expect(Taro.showToast).toHaveBeenCalledWith(
      expect.objectContaining({ title: expect.stringContaining('验证码') }),
    )
  })

  it('提交 ⇒ smsLoginAction(phone, code)，成功进主界面', async () => {
    // ⚠️ 手机号/验证码是 `type="number"`（移动端要数字键盘）⇒ **填不进带空格的串**
    // （`<input type=number>` 会把非法字符清成空串，实测过）。端侧仍保留 `.trim()` 作纵深防御，
    // 但那条分支在这个输入类型下不可达，故不写「去空白」的断言（写了就是空断言）。
    mockSmsLoginAction.mockResolvedValueOnce(true)

    render(<LoginPage />)
    switchToAdminTab()
    fillAdminForm('13800138000', '123456')
    await act(async () => {
      fireEvent.click(screen.getByText('登录'))
    })

    expect(mockSmsLoginAction).toHaveBeenCalledWith('13800138000', '123456')
    expect(mockEmployeeLoginAction).not.toHaveBeenCalled()
    expect(Taro.switchTab).toHaveBeenCalledWith({ url: '/pages/chat/index/index' })
  })

  it('管理员首登强制改密 ⇒ 与员工入口同款去向（先去改密页）', async () => {
    mockSmsLoginAction.mockResolvedValueOnce(true)
    mockGetState.mockReturnValue({ user: { mustChangePassword: true } })

    render(<LoginPage />)
    switchToAdminTab()
    fillAdminForm('13800138000', '123456')
    await act(async () => {
      fireEvent.click(screen.getByText('登录'))
    })

    expect(Taro.switchTab).not.toHaveBeenCalled()
    expect(Taro.redirectTo).toHaveBeenCalledWith({ url: '/pages/auth/change-password/index' })
  })

  it('服务端拒绝（非管理员 / 验证码错 ⇒ 401 + 同一文案）⇒ 不跳转，文案由 store 展示', async () => {
    mockSmsLoginAction.mockResolvedValueOnce(false)

    render(<LoginPage />)
    switchToAdminTab()
    fillAdminForm('13900000000', '000000')
    await act(async () => {
      fireEvent.click(screen.getByText('登录'))
    })

    // 页面不自行判角色、不编造文案（角色门禁与反枚举文案的唯一真值都在服务端）
    expect(mockSmsLoginAction).toHaveBeenCalledTimes(1)
    expect(Taro.switchTab).not.toHaveBeenCalled()
  })
})