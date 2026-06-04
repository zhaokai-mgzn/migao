import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// Mock useAuthStore
const mockLogin = vi.fn()
const mockSmsLogin = vi.fn()
const mockUseAuthStore = vi.fn()

vi.mock('@/store/auth', () => ({
  useAuthStore: (...args: any[]) => mockUseAuthStore(...args),
}))

// Mock next/link
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

// Mock next/navigation
const mockPush = vi.fn()
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush, replace: vi.fn() }),
  useSearchParams: () => ({ get: () => null }),
}))

// Mock sonner
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// Mock authApi
vi.mock('@/lib/api', () => ({
  authApi: { sendSmsCode: vi.fn() },
}))

// Mock lucide-react icons
vi.mock('lucide-react', () => ({
  Bot: (props: any) => <span data-testid="icon-bot" {...props} />,
  Eye: (props: any) => <span data-testid="icon-eye" {...props} />,
  EyeOff: (props: any) => <span data-testid="icon-eye-off" {...props} />,
  Loader2: (props: any) => <span data-testid="icon-loader" {...props} />,
  ShieldCheck: (props: any) => <span data-testid="icon-shield" {...props} />,
  Smartphone: (props: any) => <span data-testid="icon-smartphone" {...props} />,
  KeyRound: (props: any) => <span data-testid="icon-keyround" {...props} />,
  Phone: (props: any) => <span data-testid="icon-phone" {...props} />,
}))

// Mock Logo component
vi.mock('@/components/ui/Logo', () => ({
  default: (props: any) => <span data-testid="logo" {...props} />,
}))

import LoginPage from '@/app/login/page'

// Helper to switch to password tab
async function switchToPasswordTab(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByText('员工登录'))
}

describe('LoginPage', () => {
  const user = userEvent.setup()

  beforeEach(() => {
    vi.clearAllMocks()
    mockUseAuthStore.mockReturnValue({
      login: mockLogin,
      smsLogin: mockSmsLogin,
      isLoading: false,
    })
  })

  it('should render login form with SMS tab by default', () => {
    render(<LoginPage />)
    expect(screen.getByText('手机号登录')).toBeInTheDocument()
    expect(screen.getByLabelText('手机号')).toBeInTheDocument()
    expect(screen.getByLabelText('验证码')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /登 录/ })).toBeInTheDocument()
  })

  it('should render system title and description', () => {
    render(<LoginPage />)
    expect(screen.getByText('有客')).toBeInTheDocument()
    expect(screen.getByText('企业级AI电商管理解决方案')).toBeInTheDocument()
  })

  it('should show validation errors for empty SMS fields', async () => {
    render(<LoginPage />)
    await user.click(screen.getByRole('button', { name: /登 录/ }))
    expect(screen.getByText('请输入手机号')).toBeInTheDocument()
    expect(screen.getByText('请输入验证码')).toBeInTheDocument()
  })

  it('should show phone format validation error', async () => {
    render(<LoginPage />)
    await user.type(screen.getByLabelText('手机号'), '12345')
    await user.click(screen.getByRole('button', { name: /登 录/ }))
    expect(screen.getByText('请输入正确的11位手机号')).toBeInTheDocument()
  })

  it('should call smsLogin on valid SMS form submission', async () => {
    mockSmsLogin.mockResolvedValue(undefined)
    render(<LoginPage />)
    await user.type(screen.getByLabelText('手机号'), '13800138000')
    await user.type(screen.getByLabelText('验证码'), '123456')
    await user.click(screen.getByRole('button', { name: /登 录/ }))

    await waitFor(() => {
      expect(mockSmsLogin).toHaveBeenCalledWith('13800138000', '123456')
    })
  })

  it('should show SMS login error message on failure', async () => {
    mockSmsLogin.mockRejectedValue({ message: '验证码错误' })
    render(<LoginPage />)
    await user.type(screen.getByLabelText('手机号'), '13800138000')
    await user.type(screen.getByLabelText('验证码'), '123456')
    await user.click(screen.getByRole('button', { name: /登 录/ }))

    await waitFor(() => {
      expect(screen.getByText('验证码错误')).toBeInTheDocument()
    })
  })

  // ========== Password tab tests ==========

  it('should switch to password tab and show password form', async () => {
    render(<LoginPage />)
    await switchToPasswordTab(user)
    expect(screen.getByText('员工登录', { selector: 'h2' })).toBeInTheDocument()
    expect(screen.getByLabelText('账号')).toBeInTheDocument()
    expect(screen.getByLabelText('密码')).toBeInTheDocument()
  })

  it('should show validation errors for empty password fields', async () => {
    render(<LoginPage />)
    await switchToPasswordTab(user)
    await user.click(screen.getByRole('button', { name: /登 录/ }))
    expect(screen.getByText('请输入用户名/手机号/邮箱')).toBeInTheDocument()
    expect(screen.getByText('请输入密码')).toBeInTheDocument()
  })

  it('should show password length validation error', async () => {
    render(<LoginPage />)
    await switchToPasswordTab(user)
    await user.type(screen.getByLabelText('账号'), 'admin')
    await user.type(screen.getByLabelText('密码'), '12345')
    await user.click(screen.getByRole('button', { name: /登 录/ }))
    expect(screen.getByText('密码长度不能少于6位')).toBeInTheDocument()
  })

  it('should call login on valid password form submission', async () => {
    mockLogin.mockResolvedValue(undefined)
    render(<LoginPage />)
    await switchToPasswordTab(user)
    await user.type(screen.getByLabelText('账号'), 'admin')
    await user.type(screen.getByLabelText('密码'), 'admin123')
    await user.click(screen.getByRole('button', { name: /登 录/ }))

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith('admin', 'admin123', true, '')
    })
  })

  it('should show password login error message on failure', async () => {
    mockLogin.mockRejectedValue({ message: '用户名或密码错误' })
    render(<LoginPage />)
    await switchToPasswordTab(user)
    await user.type(screen.getByLabelText('账号'), 'admin')
    await user.type(screen.getByLabelText('密码'), 'wrongpass')
    await user.click(screen.getByRole('button', { name: /登 录/ }))

    await waitFor(() => {
      expect(screen.getByText('用户名或密码错误')).toBeInTheDocument()
    })
  })

  it('should toggle password visibility', async () => {
    render(<LoginPage />)
    await switchToPasswordTab(user)
    const passwordInput = screen.getByLabelText('密码')
    expect(passwordInput).toHaveAttribute('type', 'password')

    const toggleButtons = screen.getAllByRole('button')
    const toggleBtn = toggleButtons.find(btn => btn.getAttribute('tabindex') === '-1')
    expect(toggleBtn).toBeDefined()

    await user.click(toggleBtn!)
    expect(passwordInput).toHaveAttribute('type', 'text')
  })

  it('should have remember me checkbox checked by default', async () => {
    render(<LoginPage />)
    await switchToPasswordTab(user)
    const checkbox = screen.getByRole('checkbox')
    expect(checkbox).toBeChecked()
  })

  it('should toggle remember me checkbox', async () => {
    render(<LoginPage />)
    await switchToPasswordTab(user)
    const checkbox = screen.getByRole('checkbox')
    await user.click(checkbox)
    expect(checkbox).not.toBeChecked()
  })

  it('should pass rememberMe=false when unchecked', async () => {
    mockLogin.mockResolvedValue(undefined)
    render(<LoginPage />)
    await switchToPasswordTab(user)
    await user.type(screen.getByLabelText('账号'), 'admin')
    await user.type(screen.getByLabelText('密码'), 'admin123')
    await user.click(screen.getByRole('checkbox')) // uncheck
    await user.click(screen.getByRole('button', { name: /登 录/ }))

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith('admin', 'admin123', false, '')
    })
  })

  it('should disable inputs when loading (SMS tab)', () => {
    mockUseAuthStore.mockReturnValue({
      login: mockLogin,
      smsLogin: mockSmsLogin,
      isLoading: true,
    })
    render(<LoginPage />)
    expect(screen.getByLabelText('手机号')).toBeDisabled()
    expect(screen.getByLabelText('验证码')).toBeDisabled()
  })

  it('should show loading state on submit button', () => {
    mockUseAuthStore.mockReturnValue({
      login: mockLogin,
      smsLogin: mockSmsLogin,
      isLoading: true,
    })
    render(<LoginPage />)
    expect(screen.getByText('登录中...')).toBeInTheDocument()
  })

  it('should show employee login heading on password tab', async () => {
    render(<LoginPage />)
    await switchToPasswordTab(user)
    // "员工登录" appears in both the tab button and the heading, use getAllByText
    const elements = screen.getAllByText('员工登录')
    expect(elements.length).toBeGreaterThanOrEqual(1)
  })

  it('should clear field errors when typing (password tab)', async () => {
    render(<LoginPage />)
    await switchToPasswordTab(user)
    await user.click(screen.getByRole('button', { name: /登 录/ }))
    expect(screen.getByText('请输入用户名/手机号/邮箱')).toBeInTheDocument()

    await user.type(screen.getByLabelText('账号'), 'a')
    expect(screen.queryByText('请输入用户名/手机号/邮箱')).not.toBeInTheDocument()
  })
})
