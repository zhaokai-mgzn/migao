// case_ids: OB-001, OB-002, OB-003
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react'
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

  // ===== AI 自动甄别（OB-001/OB-002/OB-003） =====

  /** 走到步骤二并提交申请，返回提交按钮 */
  async function fillCompanyAndSubmit(user: ReturnType<typeof userEvent.setup>) {
    await user.type(screen.getByPlaceholderText('请输入手机号'), '13800138000')
    await user.type(screen.getByPlaceholderText('请输入6位验证码'), '123456')
    await user.click(screen.getByText('下一步'))
    await waitFor(() => {
      expect(screen.getByPlaceholderText('请输入企业名称')).toBeInTheDocument()
    })
    await user.type(screen.getByPlaceholderText('请输入企业名称'), '杭州测试布艺有限公司')
    await user.type(screen.getByPlaceholderText('请输入联系人姓名'), '张三')
    await user.click(screen.getByText('提交申请'))
  }

  it('步骤二含蜜罐隐藏字段（防自动化脚本）', async () => {
    const user = userEvent.setup()
    render(<RegisterPage />)
    await user.type(screen.getByPlaceholderText('请输入手机号'), '13800138000')
    await user.type(screen.getByPlaceholderText('请输入6位验证码'), '123456')
    await user.click(screen.getByText('下一步'))
    await waitFor(() => {
      const honeypot = screen.getByLabelText('请勿填写此字段')
      expect(honeypot).toBeInTheDocument()
      expect(honeypot.closest('div')).toHaveClass('hidden')
    })
  })

  it('步骤二文案提示 AI 自动甄别', async () => {
    const user = userEvent.setup()
    render(<RegisterPage />)
    await user.type(screen.getByPlaceholderText('请输入手机号'), '13800138000')
    await user.type(screen.getByPlaceholderText('请输入6位验证码'), '123456')
    await user.click(screen.getByText('下一步'))
    await waitFor(() => {
      expect(screen.getByText(/AI 智能甄别/)).toBeInTheDocument()
      expect(screen.getByText(/无需等待人工审核/)).toBeInTheDocument()
    })
  })

  it('AI 甄别通过 → 展示「审核通过」与「立即登录」', async () => {
    const user = userEvent.setup()
    mockSubmitRegistration.mockResolvedValue({
      data: {
        data: { applicationId: 100, status: 'approved', message: 'AI 甄别通过，欢迎入驻米高平台' },
      },
    })
    render(<RegisterPage />)
    await fillCompanyAndSubmit(user)

    await waitFor(() => {
      expect(screen.getByText('审核通过，欢迎入驻！')).toBeInTheDocument()
    })
    expect(screen.getByText(/企业账号已自动开通/)).toBeInTheDocument()
    expect(screen.getByText('立即登录')).toBeInTheDocument()
    expect(screen.getByText('米宝 · 企业智能助手')).toBeInTheDocument()
    expect(screen.getByText('小布 · 智能客服')).toBeInTheDocument()
  })

  it('AI 甄别驳回 → 展示驳回原因', async () => {
    const user = userEvent.setup()
    mockSubmitRegistration.mockResolvedValue({
      data: {
        data: {
          applicationId: 100,
          status: 'rejected',
          message: 'AI 甄别未通过',
          rejectReason: '企业名称暗示无资质金融业务',
        },
      },
    })
    render(<RegisterPage />)
    await fillCompanyAndSubmit(user)

    await waitFor(() => {
      expect(screen.getByText('审核未通过')).toBeInTheDocument()
    })
    expect(screen.getByText('企业名称暗示无资质金融业务')).toBeInTheDocument()
    expect(screen.getByText(/24 小时后重新提交/)).toBeInTheDocument()
  })

  it('提交时按钮显示「AI 甄别中」', async () => {
    const user = userEvent.setup()
    let resolveSubmit: (v: unknown) => void
    mockSubmitRegistration.mockReturnValue(
      new Promise((resolve) => { resolveSubmit = resolve })
    )
    render(<RegisterPage />)

    // 进入步骤二
    await user.type(screen.getByPlaceholderText('请输入手机号'), '13800138000')
    await user.type(screen.getByPlaceholderText('请输入6位验证码'), '123456')
    await user.click(screen.getByText('下一步'))
    await waitFor(() => {
      expect(screen.getByPlaceholderText('请输入企业名称')).toBeInTheDocument()
    })
    await user.type(screen.getByPlaceholderText('请输入企业名称'), '杭州测试布艺有限公司')
    await user.type(screen.getByPlaceholderText('请输入联系人姓名'), '张三')

    // fireEvent 不等待异步 handler，可观测到提交中的中间状态
    fireEvent.click(screen.getByText('提交申请'))
    await waitFor(() => {
      expect(screen.getByText('AI 甄别中...')).toBeInTheDocument()
    })
    await act(async () => {
      resolveSubmit!({ data: { data: { applicationId: 100, status: 'approved', message: 'ok' } } })
    })
    await waitFor(() => {
      expect(screen.getByText('审核通过，欢迎入驻！')).toBeInTheDocument()
    })
  })
})
