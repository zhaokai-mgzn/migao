// case_ids: BM-055
/**
 * 手机端登录：「员工账号 = 用户名 @ 企业编码」拆两格 + 中间固定 `@`，企业编码记住（issue #7944）
 *
 * ## 用户原话与冻结口径
 *
 * > 现在手机端登录不能默认显示企业编码，让浏览器记录下来上次登录的企业编码。员工登录也应该记录下来
 * > @企业编码，最好是只需要输入员工账号，除非是首次登录才需要输入，另外中间的@符号不需要输入，
 * > 设计成两个输入框，中间固定@号，这样更好
 *
 * | # | 判据 | 红证（怎么让它单独变红） |
 * |---|---|---|
 * | 1 | 员工面 = **两格**输入 + 中间的 `@` 是静态文本（不是输入框） | 退回一个「用户名@企业编码」输入框 ⇒ 红 |
 * | 2 | 首次（无记录）⇒ 两格都空；缺企业编码 ⇒ 本地拦下、不发请求 | 给企业编码编一个默认值 ⇒ 红 |
 * | 3 | 两格拼回**既有**标识（单 `@`，各自去首尾空白） | 只发用户名（漏掉 `@企业编码`）⇒ 红 |
 * | 4 | 成功 ⇒ 账号名与企业编码**分别**落盘（账号键不再是整串） | 仍存整串 / 少存企业编码 ⇒ 红 |
 * | 5 | 再次进入 ⇒ 企业编码预填；换人登录只改用户名即可提交 | 不预填 ⇒ 红 |
 * | 6 | 旧版整串存量（`用户名@企业编码`）⇒ 进页按最后一个 `@` 拆开预填 | 不迁移（整串塞进用户名框）⇒ 红 |
 * | 7 | 工人面（登录页工人 tab / 独立工人登录页）同样预填企业编码；PIN 永不预填 | 摘掉预填 / 预填 PIN ⇒ 红 |
 * | 8 | 两张面各记各的企业编码键（员工面不串到工人面，反之亦然） | 两面共用一个键 ⇒ 红 |
 *
 * ## 边界（照实登记）
 * · 只判**端侧落盘与提交形态**：租户仍只由服务端按企业编码解析（前端不解析、不传 tenantId）。
 * · 凭据反向红线（密码 / PIN / 验证码绝不落盘）由 `frontend/bmini-app/tests/login-remember-account.test.tsx`
 *   承担；本文件只顺带确认「落盘的是账号名 + 企业编码，不是整串标识」。
 */
import React from 'react'
import { render, screen, fireEvent, act, cleanup } from '@testing-library/react'

const mockEmployeeLoginAction = jest.fn()
const mockSmsLoginAction = jest.fn()
const mockGetState = jest.fn()
const mockWorkerLogin = jest.fn()

jest.mock('../src/store/authStore', () => ({
  useAuthStore: Object.assign(
    jest.fn(() => ({
      isLoading: false,
      employeeLoginAction: mockEmployeeLoginAction,
      smsLoginAction: mockSmsLoginAction,
    })),
    { getState: () => mockGetState() },
  ),
}))

jest.mock('../src/utils/auth', () => ({
  sendSmsCode: jest.fn(),
}))

jest.mock('../src/services/workerService', () => ({
  workerLogin: (...args: unknown[]) => mockWorkerLogin(...args),
}))

import Taro from '@tarojs/taro'
import LoginPage from '../src/pages/auth/login/index'
import WorkerLoginPage from '../src/pages/worker/login/index'
import { STORAGE_KEYS } from '../src/utils/constants'

const USERNAME_PLACEHOLDER = '用户名'
const EMPLOYEE_TENANT_PLACEHOLDER = '企业编码'
const WORKER_TENANT_PLACEHOLDER = '企业编码（向商家索取）'
const PASSWORD_PLACEHOLDER = '请输入密码'
const WORKER_NO_PLACEHOLDER = '请输入工号'
const PIN_PLACEHOLDER = '请输入 PIN'

const ALL_STORAGE_KEYS: string[] = Object.values(STORAGE_KEYS)
const TENANT_KEYS = [
  STORAGE_KEYS.LOGIN_TENANT_EMPLOYEE,
  STORAGE_KEYS.LOGIN_TENANT_WORKER,
] as const

function valueOf(placeholder: string): string {
  return (screen.getByPlaceholderText(placeholder) as HTMLInputElement).value
}

function type(placeholder: string, value: string): void {
  fireEvent.change(screen.getByPlaceholderText(placeholder), { target: { value } })
}

async function clickLogin(): Promise<void> {
  await act(async () => {
    fireEvent.click(screen.getByText('登录'))
  })
}

beforeEach(() => {
  jest.clearAllMocks()
  mockGetState.mockReturnValue({ user: { mustChangePassword: false } })
  for (const key of ALL_STORAGE_KEYS) Taro.removeStorageSync(key)
})

afterEach(() => {
  cleanup()
})

describe('员工账号：两格 + 固定 @（issue #7944）', () => {
  it('判据 1：员工面是两格输入 + 中间固定的 @（@ 是静态文本，不是输入框）', () => {
    render(<LoginPage />)

    const at = document.querySelector('.login-identifier__at')
    // 取不到就直接红（不做「元素在不在」的期望式 —— 那是弱断言）
    if (!at) throw new Error('取不到 .login-identifier__at —— 中间的 @ 分隔符没渲染出来')
    expect(at.textContent).toBe('@')
    // `@` 不可编辑：它下面没有 input
    expect(at.querySelector('input')).toBeNull()
    // 反空跑：确实是**两格**（两侧各一个原生 input）
    expect(document.querySelectorAll('.login-identifier input').length).toBe(2)
    expect(valueOf(USERNAME_PLACEHOLDER)).toBe('')
    expect(valueOf(EMPLOYEE_TENANT_PLACEHOLDER)).toBe('')
  })

  it('判据 2：首次登录缺企业编码 ⇒ 本地拦下、不发请求（不编默认编码）', async () => {
    render(<LoginPage />)
    type(USERNAME_PLACEHOLDER, 'zhangsan')
    type(PASSWORD_PLACEHOLDER, 'init-pass-123')
    await clickLogin()

    expect(mockEmployeeLoginAction).not.toHaveBeenCalled()
    expect(Taro.showToast).toHaveBeenCalledWith(
      expect.objectContaining({ title: expect.stringContaining('企业编码') }),
    )
  })

  it('判据 3：两格拼回既有标识（单 @，各自去首尾空白）', async () => {
    mockEmployeeLoginAction.mockResolvedValueOnce(true)

    render(<LoginPage />)
    type(USERNAME_PLACEHOLDER, '  zhangsan  ')
    type(EMPLOYEE_TENANT_PLACEHOLDER, '  acme  ')
    type(PASSWORD_PLACEHOLDER, 'init-pass-123')
    await clickLogin()

    expect(mockEmployeeLoginAction).toHaveBeenCalledWith('zhangsan@acme', 'init-pass-123')
  })

  it('判据 4：成功后账号名 / 企业编码**分别**落盘（账号键不再是整串）', async () => {
    mockEmployeeLoginAction.mockResolvedValueOnce(true)

    render(<LoginPage />)
    type(USERNAME_PLACEHOLDER, 'zhangsan')
    type(EMPLOYEE_TENANT_PLACEHOLDER, 'acme')
    type(PASSWORD_PLACEHOLDER, 'init-pass-123')
    await clickLogin()

    expect(Taro.getStorageSync(STORAGE_KEYS.LOGIN_ACCOUNT_EMPLOYEE)).toBe('zhangsan')
    expect(Taro.getStorageSync(STORAGE_KEYS.LOGIN_TENANT_EMPLOYEE)).toBe('acme')
    // 落盘值里不出现整串标识（否则「拆两格」只是展示层假象）
    const written = [STORAGE_KEYS.LOGIN_ACCOUNT_EMPLOYEE, STORAGE_KEYS.LOGIN_TENANT_EMPLOYEE]
      .map((key) => String(Taro.getStorageSync(key)))
      .join('\n')
    expect(written).not.toContain('@')
  })

  it('判据 5：再次进入 ⇒ 企业编码预填，换人登录只改用户名即可提交', async () => {
    mockEmployeeLoginAction.mockResolvedValueOnce(true)
    Taro.setStorageSync(STORAGE_KEYS.LOGIN_ACCOUNT_EMPLOYEE, 'zhangsan')
    Taro.setStorageSync(STORAGE_KEYS.LOGIN_TENANT_EMPLOYEE, 'acme')

    render(<LoginPage />)

    expect(valueOf(USERNAME_PLACEHOLDER)).toBe('zhangsan')
    expect(valueOf(EMPLOYEE_TENANT_PLACEHOLDER)).toBe('acme')

    // 换一个员工登录：只改用户名，**不碰**企业编码
    type(USERNAME_PLACEHOLDER, 'lisi')
    type(PASSWORD_PLACEHOLDER, 'init-pass-123')
    await clickLogin()

    expect(mockEmployeeLoginAction).toHaveBeenCalledWith('lisi@acme', 'init-pass-123')
  })

  it('判据 6：旧版整串存量（用户名@企业编码）⇒ 进页拆成两格预填（老用户不必再"首次"一次）', () => {
    Taro.setStorageSync(STORAGE_KEYS.LOGIN_ACCOUNT_EMPLOYEE, 'zhangsan@acme')

    render(<LoginPage />)

    expect(valueOf(USERNAME_PLACEHOLDER)).toBe('zhangsan')
    expect(valueOf(EMPLOYEE_TENANT_PLACEHOLDER)).toBe('acme')
  })

  it('判据 8：员工面登录不写工人面的企业编码键（两张面各记各的）', async () => {
    mockEmployeeLoginAction.mockResolvedValueOnce(true)

    render(<LoginPage />)
    type(USERNAME_PLACEHOLDER, 'zhangsan')
    type(EMPLOYEE_TENANT_PLACEHOLDER, 'acme')
    type(PASSWORD_PLACEHOLDER, 'init-pass-123')
    await clickLogin()

    expect(Taro.getStorageSync(STORAGE_KEYS.LOGIN_TENANT_EMPLOYEE)).toBe('acme')
    expect(Taro.getStorageSync(STORAGE_KEYS.LOGIN_TENANT_WORKER)).toBe('')
  })
})

describe('工人面：企业编码预填（issue #7944）', () => {
  it('判据 7a：登录页工人 tab ⇒ 企业编码预填、PIN 不预填', () => {
    Taro.setStorageSync(STORAGE_KEYS.LOGIN_ACCOUNT_WORKER, 'W-042')
    Taro.setStorageSync(STORAGE_KEYS.LOGIN_TENANT_WORKER, 'acme')

    render(<LoginPage />)
    fireEvent.click(screen.getByText('工人登录'))

    expect(valueOf(WORKER_NO_PLACEHOLDER)).toBe('W-042')
    expect(valueOf(WORKER_TENANT_PLACEHOLDER)).toBe('acme')
    expect(valueOf(PIN_PLACEHOLDER)).toBe('')
  })

  it('判据 7b：工人 tab 登录成功 ⇒ 企业编码落到**工人面**的键（不串到员工面）', async () => {
    mockWorkerLogin.mockResolvedValueOnce({ success: true, data: { worker_name: '张三' } })

    render(<LoginPage />)
    fireEvent.click(screen.getByText('工人登录'))
    type(WORKER_NO_PLACEHOLDER, 'W-007')
    type(PIN_PLACEHOLDER, 'pin-1234')
    type(WORKER_TENANT_PLACEHOLDER, ' acme ')
    await clickLogin()

    expect(mockWorkerLogin).toHaveBeenCalledWith('W-007', 'pin-1234', undefined, 'acme')
    expect(Taro.getStorageSync(STORAGE_KEYS.LOGIN_TENANT_WORKER)).toBe('acme')
    expect(Taro.getStorageSync(STORAGE_KEYS.LOGIN_TENANT_EMPLOYEE)).toBe('')
  })

  it('判据 7c：独立工人登录页 ⇒ 企业编码预填、PIN 不预填，成功写回同一个键', async () => {
    Taro.setStorageSync(STORAGE_KEYS.LOGIN_ACCOUNT_WORKER, 'W-042')
    Taro.setStorageSync(STORAGE_KEYS.LOGIN_TENANT_WORKER, 'acme')
    mockWorkerLogin.mockResolvedValueOnce({ success: true, data: { worker_name: '张三' } })

    render(<WorkerLoginPage />)

    // 独立工人登录页的 placeholder 与工人 tab 不同（'工号' / 'PIN'，不是 '请输入…'）
    expect(valueOf('工号')).toBe('W-042')
    expect(valueOf(WORKER_TENANT_PLACEHOLDER)).toBe('acme')
    expect(valueOf('PIN')).toBe('')

    type('PIN', 'pin-1234')
    await clickLogin()

    expect(Taro.getStorageSync(STORAGE_KEYS.LOGIN_TENANT_WORKER)).toBe('acme')
    // 反空跑：确实调了工人登录（否则「键还在」可能只是什么都没发生）
    expect(mockWorkerLogin).toHaveBeenCalledTimes(1)
  })

  it('判据 7d：两张面**都**有企业编码键时各用各的（不共用同一个键）', () => {
    Taro.setStorageSync(STORAGE_KEYS.LOGIN_TENANT_EMPLOYEE, 'acme-employee')
    Taro.setStorageSync(STORAGE_KEYS.LOGIN_TENANT_WORKER, 'acme-worker')

    render(<LoginPage />)
    expect(valueOf(EMPLOYEE_TENANT_PLACEHOLDER)).toBe('acme-employee')
    fireEvent.click(screen.getByText('工人登录'))
    expect(valueOf(WORKER_TENANT_PLACEHOLDER)).toBe('acme-worker')

    // 反空跑：两个键真的是两个不同的键
    expect(new Set<string>(TENANT_KEYS).size).toBe(2)
  })
})
