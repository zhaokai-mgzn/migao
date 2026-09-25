// case_ids: AU-006
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// Mock useAuthStore（页面只用 changePassword / logout / isLoading）
const mockChangePassword = vi.fn()
const mockLogout = vi.fn()
let mockIsLoading = false
vi.mock('@/store/auth', () => ({
  useAuthStore: () => ({
    changePassword: (...args: any[]) => mockChangePassword(...args),
    logout: (...args: any[]) => mockLogout(...args),
    isLoading: mockIsLoading,
  }),
}))

// Mock next/navigation
const mockPush = vi.fn()
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush, replace: vi.fn() }),
}))

// Mock lucide-react icons
vi.mock('lucide-react', () => ({
  KeyRound: (props: any) => <span data-testid="icon-key" {...props} />,
  Loader2: (props: any) => <span data-testid="icon-loader" {...props} />,
  LogOut: (props: any) => <span data-testid="icon-logout" {...props} />,
}))

vi.mock('@/components/ui/Logo', () => ({
  default: (props: any) => <span data-testid="logo" {...props} />,
}))

import ChangePasswordPage from '@/app/change-password/page'

describe('ChangePasswordPage（首登强制改密页，issue #5485）', () => {
  const user = userEvent.setup()

  beforeEach(() => {
    vi.clearAllMocks()
    mockIsLoading = false
    mockChangePassword.mockResolvedValue(undefined)
  })

  it('渲染三个密码字段与「首次登录请先修改密码」说明', () => {
    render(<ChangePasswordPage />)
    expect(screen.getByText('首次登录，请先修改密码')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('请输入管理员给你的初始密码')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('请输入新密码')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('请再次输入新密码')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /修改密码并进入系统/ })).toBeInTheDocument()
  })

  it('空字段提交：三项都给出必填提示且不发请求', async () => {
    render(<ChangePasswordPage />)
    await user.click(screen.getByRole('button', { name: /修改密码并进入系统/ }))

    expect(screen.getByText('请输入当前密码（初始密码）')).toBeInTheDocument()
    expect(screen.getByText('请输入新密码')).toBeInTheDocument()
    expect(screen.getByText('请再次输入新密码')).toBeInTheDocument()
    expect(mockChangePassword).not.toHaveBeenCalled()
  })

  it('两次新密码不一致：本地拦截，不发请求（确认密码是纯前端校验，不进请求体）', async () => {
    render(<ChangePasswordPage />)
    await user.type(screen.getByPlaceholderText('请输入管理员给你的初始密码'), 'Init#12345')
    await user.type(screen.getByPlaceholderText('请输入新密码'), 'MyOwn#67890')
    await user.type(screen.getByPlaceholderText('请再次输入新密码'), 'MyOwn#67891')
    await user.click(screen.getByRole('button', { name: /修改密码并进入系统/ }))

    expect(screen.getByText('两次输入的新密码不一致')).toBeInTheDocument()
    expect(mockChangePassword).not.toHaveBeenCalled()
  })

  it('改密成功：调用 changePassword(旧, 新) 并直接进业务页（响应里的新凭据已由 store 接管）', async () => {
    render(<ChangePasswordPage />)
    await user.type(screen.getByPlaceholderText('请输入管理员给你的初始密码'), 'Init#12345')
    await user.type(screen.getByPlaceholderText('请输入新密码'), 'MyOwn#67890')
    await user.type(screen.getByPlaceholderText('请再次输入新密码'), 'MyOwn#67890')
    await user.click(screen.getByRole('button', { name: /修改密码并进入系统/ }))

    await waitFor(() => {
      // 逐字断言：确认密码不进 body（服务端只要 oldPassword/newPassword 两个键）
      expect(mockChangePassword).toHaveBeenCalledWith('Init#12345', 'MyOwn#67890')
    })
    expect(mockChangePassword.mock.calls[0]).toHaveLength(2)
    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith('/dashboard')
    })
  })

  it('改密失败（弱密码 422）：直接展示服务端 message，停在改密页', async () => {
    mockChangePassword.mockRejectedValue({
      response: {
        status: 422,
        data: { success: false, error: { code: 'VALIDATION_ERROR', message: '新密码强度不足：至少 8 位且含字母与数字' } },
      },
    })
    render(<ChangePasswordPage />)
    await user.type(screen.getByPlaceholderText('请输入管理员给你的初始密码'), 'Init#12345')
    await user.type(screen.getByPlaceholderText('请输入新密码'), '123')
    await user.type(screen.getByPlaceholderText('请再次输入新密码'), '123')
    await user.click(screen.getByRole('button', { name: /修改密码并进入系统/ }))

    await waitFor(() => {
      expect(screen.getByText('新密码强度不足：至少 8 位且含字母与数字')).toBeInTheDocument()
    })
    expect(mockPush).not.toHaveBeenCalled()
  })

  it('旧密码错（422）：展示服务端原文，不跳转', async () => {
    mockChangePassword.mockRejectedValue({
      response: { status: 422, data: { error: { message: '原密码不正确' } } },
    })
    render(<ChangePasswordPage />)
    await user.type(screen.getByPlaceholderText('请输入管理员给你的初始密码'), 'wrong-old')
    await user.type(screen.getByPlaceholderText('请输入新密码'), 'MyOwn#67890')
    await user.type(screen.getByPlaceholderText('请再次输入新密码'), 'MyOwn#67890')
    await user.click(screen.getByRole('button', { name: /修改密码并进入系统/ }))

    await waitFor(() => {
      expect(screen.getByText('原密码不正确')).toBeInTheDocument()
    })
    expect(mockPush).not.toHaveBeenCalled()
  })

  it('改不了密码时的出口：可退出登录（登出在强制改密白名单内）', async () => {
    render(<ChangePasswordPage />)
    await user.click(screen.getByRole('button', { name: /退出登录/ }))
    expect(mockLogout).toHaveBeenCalled()
  })

  it('提交中：按钮禁用并显示提交中', () => {
    mockIsLoading = true
    render(<ChangePasswordPage />)
    expect(screen.getByRole('button', { name: /提交中/ })).toBeDisabled()
  })
})