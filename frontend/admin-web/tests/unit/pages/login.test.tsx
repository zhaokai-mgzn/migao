// case_ids: AU-001, AU-003, AU-004, AU-005, UI-037
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// Mock useAuthStore
const mockEmployeeLogin = vi.fn()
const mockSmsLogin = vi.fn()
const mockUseAuthStore = vi.fn()

vi.mock('@/store/auth', () => ({
  useAuthStore: (...args: any[]) => mockUseAuthStore(...args),
}))

// Mock next/link
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

// Mock next/navigation（callbackUrl 可逐用例控制）
const mockPush = vi.fn()
const mockReplace = vi.fn()
const mockSearchParamsGet = vi.fn()
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush, replace: mockReplace }),
  useSearchParams: () => ({ get: (...args: any[]) => mockSearchParamsGet(...args) }),
}))

// Mock sonner
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// Mock authApi (still used for handleSendCode)
const mockSendSmsCode = vi.fn()
vi.mock('@/lib/api', () => ({
  authApi: { sendSmsCode: (...args: any[]) => mockSendSmsCode(...args) },
}))

// Mock lucide-react icons
vi.mock('lucide-react', () => ({
  Loader2: (props: any) => <span data-testid="icon-loader" {...props} />,
  ShieldCheck: (props: any) => <span data-testid="icon-shield" {...props} />,
  Smartphone: (props: any) => <span data-testid="icon-smartphone" {...props} />,
  User: (props: any) => <span data-testid="icon-user" {...props} />,
  Lock: (props: any) => <span data-testid="icon-lock" {...props} />,
}))

// Mock Logo component
vi.mock('@/components/ui/Logo', () => ({
  default: (props: any) => <span data-testid="logo" {...props} />,
}))

import LoginPage from '@/app/login/page'

/** 切到「管理员登录」入口 */
async function switchToAdminTab(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('tab', { name: /管理员登录/ }))
}

describe('LoginPage', () => {
  const user = userEvent.setup()

  beforeEach(() => {
    vi.clearAllMocks()
    mockSearchParamsGet.mockReturnValue(null)
    mockSendSmsCode.mockResolvedValue(undefined)
    mockUseAuthStore.mockReturnValue({
      employeeLogin: mockEmployeeLogin,
      smsLogin: mockSmsLogin,
      isAuthenticated: false,
      user: null,
    })
  })

  // ── 两个入口：谁用哪个要一眼看懂（#5485）──

  it('渲染两个登录入口：员工登录 / 管理员登录，并默认停在员工登录', () => {
    render(<LoginPage />)
    expect(screen.getByRole('tab', { name: /员工登录/ })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /管理员登录/ })).toBeInTheDocument()
    // 默认 = 员工入口（账号 + 密码），管理员入口的手机号表单不渲染
    expect(screen.getByPlaceholderText('用户名@企业编码')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('请输入密码')).toBeInTheDocument()
    expect(screen.queryByPlaceholderText('请输入手机号')).not.toBeInTheDocument()
  })

  it('员工入口说明账号形态为「用户名@企业编码」并指向管理员分配', () => {
    render(<LoginPage />)
    expect(screen.getByText(/用户名@企业编码/)).toBeInTheDocument()
    expect(screen.getByText(/请联系企业管理员在「员工管理」中分配用户名与初始密码/)).toBeInTheDocument()
  })

  it('管理员入口说明「仅管理员可用、员工用账号密码」（#5485 AU-004 的引导面）', async () => {
    render(<LoginPage />)
    await switchToAdminTab(user)
    expect(screen.getByText(/仅企业管理员与平台超管可使用短信验证码登录/)).toBeInTheDocument()
    expect(screen.getByPlaceholderText('请输入手机号')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('请输入6位验证码')).toBeInTheDocument()
    // 切到管理员后不再展示员工账号密码表单
    expect(screen.queryByPlaceholderText('用户名@企业编码')).not.toBeInTheDocument()
  })

  it('渲染系统标题与 Logo', () => {
    render(<LoginPage />)
    expect(screen.getByText('米高')).toBeInTheDocument()
    expect(screen.getByText('企业级AI电商管理解决方案')).toBeInTheDocument()
    expect(screen.getByTestId('logo')).toBeInTheDocument()
  })

  // ── 员工登录（AU-001）──

  it('员工登录：把标识**原样**交给 store（不解析企业编码、不拼 tenantId）', async () => {
    mockEmployeeLogin.mockResolvedValue({ mustChangePassword: false })
    render(<LoginPage />)
    await user.type(screen.getByPlaceholderText('用户名@企业编码'), 'zhangsan@tenant_7478359537')
    await user.type(screen.getByPlaceholderText('请输入密码'), 'Init#12345')
    await user.click(screen.getByRole('button', { name: /登 录/ }))

    await waitFor(() => {
      // 逐字断言：含下划线的存量编码形态必须原样透传（前端不得改写/截断/转数字）
      expect(mockEmployeeLogin).toHaveBeenCalledWith('zhangsan@tenant_7478359537', 'Init#12345')
    })
    // 只传两个参数 —— 第三个参数（tenantId 之类）一旦出现就是「前端自己解析租户」的回归
    expect(mockEmployeeLogin.mock.calls[0]).toHaveLength(2)
  })

  it('员工登录成功且无需改密 → 回 callbackUrl', async () => {
    mockEmployeeLogin.mockResolvedValue({ mustChangePassword: false })
    mockSearchParamsGet.mockReturnValue('/orders')
    render(<LoginPage />)
    await user.type(screen.getByPlaceholderText('用户名@企业编码'), 'zhangsan@migao')
    await user.type(screen.getByPlaceholderText('请输入密码'), 'Init#12345')
    await user.click(screen.getByRole('button', { name: /登 录/ }))

    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith('/orders')
    })
  })

  it('员工登录成功但 mustChangePassword → **直接**去改密页（不进业务页，AU-006 的前端半边）', async () => {
    mockEmployeeLogin.mockResolvedValue({ mustChangePassword: true })
    render(<LoginPage />)
    await user.type(screen.getByPlaceholderText('用户名@企业编码'), 'zhangsan@migao')
    await user.type(screen.getByPlaceholderText('请输入密码'), 'Init#12345')
    await user.click(screen.getByRole('button', { name: /登 录/ }))

    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith('/change-password')
    })
    expect(mockPush).not.toHaveBeenCalledWith('/dashboard')
  })

  it('员工登录失败：展示服务端原文（反枚举 —— 三种病因同一条文案，前端不得改写，AU-003）', async () => {
    mockEmployeeLogin.mockRejectedValue({
      response: { status: 401, data: { success: false, error: { code: 'UNAUTHORIZED', message: '账号或密码错误' } } },
    })
    render(<LoginPage />)
    await user.type(screen.getByPlaceholderText('用户名@企业编码'), 'zhangsan@migao')
    await user.type(screen.getByPlaceholderText('请输入密码'), 'wrong-password')
    await user.click(screen.getByRole('button', { name: /登 录/ }))

    await waitFor(() => {
      expect(screen.getByText('账号或密码错误')).toBeInTheDocument()
    })
  })

  it('员工登录：账号格式不合规（缺 @）时本地拦截，不发请求', async () => {
    render(<LoginPage />)
    await user.type(screen.getByPlaceholderText('用户名@企业编码'), 'zhangsan')
    await user.type(screen.getByPlaceholderText('请输入密码'), 'Init#12345')
    await user.click(screen.getByRole('button', { name: /登 录/ }))

    expect(screen.getByText('账号格式为 用户名@企业编码')).toBeInTheDocument()
    expect(mockEmployeeLogin).not.toHaveBeenCalled()
  })

  it('员工登录：不校验企业编码字符集/用户名规则（那是服务端的事，前端写更严的正则会把合法用户挡在门外）', async () => {
    mockEmployeeLogin.mockResolvedValue({ mustChangePassword: false })
    render(<LoginPage />)
    // 含下划线、含点、大写字母的标识一律放行到服务端
    await user.type(screen.getByPlaceholderText('用户名@企业编码'), 'Zhang.San-01@tenant_7478359537')
    await user.type(screen.getByPlaceholderText('请输入密码'), 'Init#12345')
    await user.click(screen.getByRole('button', { name: /登 录/ }))

    await waitFor(() => {
      expect(mockEmployeeLogin).toHaveBeenCalledWith('Zhang.San-01@tenant_7478359537', 'Init#12345')
    })
  })

  it('员工登录：空账号/空密码给出必填提示', async () => {
    render(<LoginPage />)
    await user.click(screen.getByRole('button', { name: /登 录/ }))
    expect(screen.getByText('请输入账号')).toBeInTheDocument()
    expect(screen.getByText('请输入密码')).toBeInTheDocument()
  })

  // ── 管理员登录（AU-005：仍可用）──

  it('管理员登录：手机号 + 短信验证码仍可登录并回 callbackUrl', async () => {
    mockSmsLogin.mockResolvedValue({ mustChangePassword: false })
    mockSearchParamsGet.mockReturnValue('/dashboard')
    render(<LoginPage />)
    await switchToAdminTab(user)
    await user.type(screen.getByPlaceholderText('请输入手机号'), '13800138000')
    await user.type(screen.getByPlaceholderText('请输入6位验证码'), '123456')
    await user.click(screen.getByRole('button', { name: /登 录/ }))

    await waitFor(() => {
      expect(mockSmsLogin).toHaveBeenCalledWith('13800138000', '123456')
    })
    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith('/dashboard')
    })
  })

  it('管理员登录失败：展示服务端引导文案（非 admin 员工走短信时服务端会拒绝并给出引导）', async () => {
    mockSmsLogin.mockRejectedValue({
      response: { status: 403, data: { success: false, error: { code: 'ROLE_NOT_ALLOWED', message: '该账号不是管理员，请使用账号密码登录' } } },
    })
    render(<LoginPage />)
    await switchToAdminTab(user)
    await user.type(screen.getByPlaceholderText('请输入手机号'), '13800138000')
    await user.type(screen.getByPlaceholderText('请输入6位验证码'), '123456')
    await user.click(screen.getByRole('button', { name: /登 录/ }))

    await waitFor(() => {
      expect(screen.getByText('该账号不是管理员，请使用账号密码登录')).toBeInTheDocument()
    })
  })

  it('管理员登录：手机号格式与验证码位数校验', async () => {
    render(<LoginPage />)
    await switchToAdminTab(user)
    await user.type(screen.getByPlaceholderText('请输入手机号'), '12345')
    await user.click(screen.getByRole('button', { name: /登 录/ }))
    expect(screen.getByText('请输入正确的11位手机号')).toBeInTheDocument()
    expect(screen.getByText('请输入验证码')).toBeInTheDocument()
    expect(mockSmsLogin).not.toHaveBeenCalled()
  })

  it('管理员登录：无 message 字段时回落到通用文案', async () => {
    mockSmsLogin.mockRejectedValue({})
    render(<LoginPage />)
    await switchToAdminTab(user)
    await user.type(screen.getByPlaceholderText('请输入手机号'), '13800138000')
    await user.type(screen.getByPlaceholderText('请输入6位验证码'), '123456')
    await user.click(screen.getByRole('button', { name: /登 录/ }))

    await waitFor(() => {
      expect(screen.getByText('登录失败')).toBeInTheDocument()
    })
  })

  // ── 验证码发送 / 加载态 ──

  it('发送验证码：手机号为空时报错，不发请求', async () => {
    render(<LoginPage />)
    await switchToAdminTab(user)
    await user.click(screen.getByRole('button', { name: '获取验证码' }))
    expect(screen.getByText('请输入正确的11位手机号')).toBeInTheDocument()
    expect(mockSendSmsCode).not.toHaveBeenCalled()
  })

  it('发送验证码：合法手机号调用接口并进入倒计时', async () => {
    render(<LoginPage />)
    await switchToAdminTab(user)
    await user.type(screen.getByPlaceholderText('请输入手机号'), '13800138000')
    await user.click(screen.getByRole('button', { name: '获取验证码' }))

    await waitFor(() => {
      expect(mockSendSmsCode).toHaveBeenCalledWith('13800138000')
    })
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /重新发送/ })).toBeInTheDocument()
    })
  })

  it('登录中：按钮禁用并显示登录中', async () => {
    mockEmployeeLogin.mockImplementation(() => new Promise(() => {}))
    render(<LoginPage />)
    await user.type(screen.getByPlaceholderText('用户名@企业编码'), 'zhangsan@migao')
    await user.type(screen.getByPlaceholderText('请输入密码'), 'Init#12345')
    await user.click(screen.getByRole('button', { name: /登 录/ }))

    await waitFor(() => {
      expect(screen.getByText('登录中...')).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: /登录中/ })).toBeDisabled()
  })

  it('退出再切回入口：清掉上一次的报错', async () => {
    mockEmployeeLogin.mockRejectedValue({ response: { data: { error: { message: '账号或密码错误' } } } })
    render(<LoginPage />)
    await user.type(screen.getByPlaceholderText('用户名@企业编码'), 'zhangsan@migao')
    await user.type(screen.getByPlaceholderText('请输入密码'), 'wrong')
    await user.click(screen.getByRole('button', { name: /登 录/ }))
    await waitFor(() => {
      expect(screen.getByText('账号或密码错误')).toBeInTheDocument()
    })
    await switchToAdminTab(user)
    expect(screen.queryByText('账号或密码错误')).not.toBeInTheDocument()
  })

  // ── 验证码只允许数字 ──

  it('验证码输入框过滤非数字字符', async () => {
    render(<LoginPage />)
    await switchToAdminTab(user)
    await user.type(screen.getByPlaceholderText('请输入6位验证码'), 'a1b2c3')
    const input = screen.getByPlaceholderText('请输入6位验证码') as HTMLInputElement
    expect(input.value).toBe('123')
  })
})