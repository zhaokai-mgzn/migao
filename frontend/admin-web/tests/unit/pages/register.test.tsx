import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// Mock APIs
const mockSendSmsCode = vi.fn()
const mockSubmitRegistration = vi.fn()

vi.mock('@/lib/api', () => ({
  authApi: {
    sendSmsCode: (...args: any[]) => mockSendSmsCode(...args),
    submitRegistration: (...args: any[]) => mockSubmitRegistration(...args),
  },
  fileApi: {
    uploadFile: vi.fn(),
  },
}))

// Mock next/link
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

// Mock sonner
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// Mock Logo component
vi.mock('@/components/ui/Logo', () => ({
  default: () => <div data-testid="logo">Logo</div>,
}))

import RegisterPage from '@/app/register/page'

describe('RegisterPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSendSmsCode.mockResolvedValue({ data: { success: true } })
  })

  it('should render registration title', async () => {
    render(<RegisterPage />)
    await waitFor(() => {
      expect(screen.getByText('企业入驻申请')).toBeInTheDocument()
    })
  })

  it('should render subtitle', async () => {
    render(<RegisterPage />)
    await waitFor(() => {
      expect(screen.getByText('米高 · AI智能管理平台')).toBeInTheDocument()
    })
  })

  it('should render step indicator with step 1 active', async () => {
    render(<RegisterPage />)
    await waitFor(() => {
      expect(screen.getByText('手机验证')).toBeInTheDocument()
      expect(screen.getByText('企业信息')).toBeInTheDocument()
    })
  })

  it('should render phone form in step 1', async () => {
    render(<RegisterPage />)
    await waitFor(() => {
      expect(screen.getByPlaceholderText('请输入手机号')).toBeInTheDocument()
      expect(screen.getByPlaceholderText('请输入6位验证码')).toBeInTheDocument()
      expect(screen.getByText('获取验证码')).toBeInTheDocument()
    })
  })

  it('should render next step button', async () => {
    render(<RegisterPage />)
    await waitFor(() => {
      expect(screen.getByText('下一步')).toBeInTheDocument()
    })
  })

  it('should render back to login link', async () => {
    render(<RegisterPage />)
    await waitFor(() => {
      expect(screen.getByText('← 返回登录')).toBeInTheDocument()
    })
  })

  it('should render Logo component', async () => {
    render(<RegisterPage />)
    await waitFor(() => {
      expect(screen.getByTestId('logo')).toBeInTheDocument()
    })
  })

  it('should show phone validation error when submitting empty phone', async () => {
    const user = userEvent.setup()
    render(<RegisterPage />)
    await waitFor(() => {
      expect(screen.getByText('下一步')).toBeInTheDocument()
    })
    await user.click(screen.getByText('下一步'))
    await waitFor(() => {
      expect(screen.getByText('请输入手机号')).toBeInTheDocument()
    })
  })

  it('should transition to step 2 after valid phone + code', async () => {
    const user = userEvent.setup()
    render(<RegisterPage />)

    await waitFor(() => {
      expect(screen.getByText('手机号验证')).toBeInTheDocument()
    })

    const phoneInput = screen.getByPlaceholderText('请输入手机号')
    const codeInput = screen.getByPlaceholderText('请输入6位验证码')

    // 使用 fireEvent 直接设置值以避免 userEvent 的异步时序问题
    await user.clear(phoneInput)
    await user.type(phoneInput, '13800138000')
    await user.clear(codeInput)
    await user.type(codeInput, '123456')

    // 点击表单中的下一步按钮提交
    const nextBtn = screen.getByText('下一步')
    await user.click(nextBtn)

    // 步骤 2 渲染后，企业名称输入框出现
    await waitFor(() => {
      expect(screen.getByPlaceholderText('请输入企业名称')).toBeInTheDocument()
    })
  })
})
