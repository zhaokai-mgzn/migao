import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// Mock useAuthStore
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

// Mock authApi (still used for handleSendCode)
vi.mock('@/lib/api', () => ({
  authApi: { sendSmsCode: vi.fn().mockResolvedValue(undefined) },
}))

// Mock lucide-react icons
vi.mock('lucide-react', () => ({
  Loader2: (props: any) => <span data-testid="icon-loader" {...props} />,
  ShieldCheck: (props: any) => <span data-testid="icon-shield" {...props} />,
  Smartphone: (props: any) => <span data-testid="icon-smartphone" {...props} />,
}))

// Mock Logo component
vi.mock('@/components/ui/Logo', () => ({
  default: (props: any) => <span data-testid="logo" {...props} />,
}))

import LoginPage from '@/app/login/page'

describe('LoginPage', () => {
  const user = userEvent.setup()

  beforeEach(() => {
    vi.clearAllMocks()
    mockUseAuthStore.mockReturnValue({
      smsLogin: mockSmsLogin,
      isAuthenticated: false,
    })
  })

  // ── 基础渲染 ──

  it('should render login form with SMS fields', () => {
    render(<LoginPage />)
    expect(screen.getByText('手机号登录')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('请输入手机号')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('请输入6位验证码')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /登 录/ })).toBeInTheDocument()
  })

  it('should render system title and description', () => {
    render(<LoginPage />)
    expect(screen.getByText('米高')).toBeInTheDocument()
    expect(screen.getByText('企业级AI电商管理解决方案')).toBeInTheDocument()
  })

  it('should render logo', () => {
    render(<LoginPage />)
    expect(screen.getByTestId('logo')).toBeInTheDocument()
  })

  // ── 验证码发送 ──

  it('should render send code button', () => {
    render(<LoginPage />)
    expect(screen.getByRole('button', { name: '获取验证码' })).toBeInTheDocument()
  })

  it('should show phone validation error when sending code with empty phone', async () => {
    render(<LoginPage />)
    await user.click(screen.getByRole('button', { name: '获取验证码' }))
    expect(screen.getByText('请输入正确的11位手机号')).toBeInTheDocument()
  })

  it('should show phone validation error when sending code with invalid phone', async () => {
    render(<LoginPage />)
    await user.type(screen.getByPlaceholderText('请输入手机号'), '12345')
    await user.click(screen.getByRole('button', { name: '获取验证码' }))
    expect(screen.getByText('请输入正确的11位手机号')).toBeInTheDocument()
  })

  // ── 表单验证 ──

  it('should show validation errors for empty SMS fields', async () => {
    render(<LoginPage />)
    await user.click(screen.getByRole('button', { name: /登 录/ }))
    expect(screen.getByText('请输入手机号')).toBeInTheDocument()
    expect(screen.getByText('请输入验证码')).toBeInTheDocument()
  })

  it('should show phone format validation error', async () => {
    render(<LoginPage />)
    await user.type(screen.getByPlaceholderText('请输入手机号'), '12345')
    await user.click(screen.getByRole('button', { name: /登 录/ }))
    expect(screen.getByText('请输入正确的11位手机号')).toBeInTheDocument()
  })

  it('should clear phone error when typing', async () => {
    render(<LoginPage />)
    await user.click(screen.getByRole('button', { name: /登 录/ }))
    expect(screen.getByText('请输入手机号')).toBeInTheDocument()
    await user.type(screen.getByPlaceholderText('请输入手机号'), '1')
    expect(screen.queryByText('请输入手机号')).not.toBeInTheDocument()
  })

  // ── 短信登录 ──

  it('should call smsLogin on valid SMS form submission', async () => {
    mockSmsLogin.mockResolvedValue(undefined)
    render(<LoginPage />)
    await user.type(screen.getByPlaceholderText('请输入手机号'), '13800138000')
    await user.type(screen.getByPlaceholderText('请输入6位验证码'), '123456')
    await user.click(screen.getByRole('button', { name: /登 录/ }))

    await waitFor(() => {
      expect(mockSmsLogin).toHaveBeenCalledWith('13800138000', '123456')
    })
  })

  it('should redirect to dashboard after successful login', async () => {
    mockSmsLogin.mockResolvedValue(undefined)
    render(<LoginPage />)
    await user.type(screen.getByPlaceholderText('请输入手机号'), '13800138000')
    await user.type(screen.getByPlaceholderText('请输入6位验证码'), '123456')
    await user.click(screen.getByRole('button', { name: /登 录/ }))

    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith('/dashboard')
    })
  })

  it('should show SMS login error message on failure', async () => {
    mockSmsLogin.mockRejectedValue({ message: '验证码错误' })
    render(<LoginPage />)
    await user.type(screen.getByPlaceholderText('请输入手机号'), '13800138000')
    await user.type(screen.getByPlaceholderText('请输入6位验证码'), '123456')
    await user.click(screen.getByRole('button', { name: /登 录/ }))

    await waitFor(() => {
      expect(screen.getByText('验证码错误')).toBeInTheDocument()
    })
  })

  it('should show fallback error message when no message in error', async () => {
    mockSmsLogin.mockRejectedValue({})
    render(<LoginPage />)
    await user.type(screen.getByPlaceholderText('请输入手机号'), '13800138000')
    await user.type(screen.getByPlaceholderText('请输入6位验证码'), '123456')
    await user.click(screen.getByRole('button', { name: /登 录/ }))

    await waitFor(() => {
      expect(screen.getByText('登录失败')).toBeInTheDocument()
    })
  })

  it('should extract error message from response.data.message', async () => {
    mockSmsLogin.mockRejectedValue({ response: { data: { message: '短信验证码已过期' } } })
    render(<LoginPage />)
    await user.type(screen.getByPlaceholderText('请输入手机号'), '13800138000')
    await user.type(screen.getByPlaceholderText('请输入6位验证码'), '123456')
    await user.click(screen.getByRole('button', { name: /登 录/ }))

    await waitFor(() => {
      expect(screen.getByText('短信验证码已过期')).toBeInTheDocument()
    })
  })

  // ── 加载状态 ──

  it('should show loading state on login button', async () => {
    mockSmsLogin.mockImplementation(() => new Promise(() => {}))
    render(<LoginPage />)
    await user.type(screen.getByPlaceholderText('请输入手机号'), '13800138000')
    await user.type(screen.getByPlaceholderText('请输入6位验证码'), '123456')
    await user.click(screen.getByRole('button', { name: /登 录/ }))

    await waitFor(() => {
      expect(screen.getByText('登录中...')).toBeInTheDocument()
    })
  })

  it('should disable login button while loading', async () => {
    mockSmsLogin.mockImplementation(() => new Promise(() => {}))
    render(<LoginPage />)
    await user.type(screen.getByPlaceholderText('请输入手机号'), '13800138000')
    await user.type(screen.getByPlaceholderText('请输入6位验证码'), '123456')
    await user.click(screen.getByRole('button', { name: /登 录/ }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /登录中/ })).toBeDisabled()
    })
  })

  // ── 验证码只允许数字 ──

  it('should strip non-digit characters from code input', async () => {
    render(<LoginPage />)
    await user.type(screen.getByPlaceholderText('请输入6位验证码'), 'a1b2c3')
    const input = screen.getByPlaceholderText('请输入6位验证码') as HTMLInputElement
    expect(input.value).toBe('123')
  })
})
