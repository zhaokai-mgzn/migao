// case_ids: OB-001
// 复用既有用例 OB-001（POST /api/auth/register 提交契约）。
// OB-001（issue #4363 前端半边；契约所有者 #4361）：注册页「行业」从**自由文本**改为**受控下拉**。
// 病根：自由文本（原 placeholder「如：布艺纺织、家居建材、电子商务等」）不能当行业模板键
// ⇒ 开租自动套用生产种子时匹配不到模板，且会**静默**落不到任何模板。
// 反 placeholder：断言落到**真实提交载荷**（industry = code），不是只断言控件存在。
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const mockSendSmsCode = vi.fn()
const mockSubmitRegistration = vi.fn()

vi.mock('@/lib/api', () => ({
  authApi: {
    sendSmsCode: (...args: unknown[]) => mockSendSmsCode(...args),
    submitRegistration: (...args: unknown[]) => mockSubmitRegistration(...args),
  },
  fileApi: { uploadFile: vi.fn() },
}))

vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>{children}</a>
  ),
}))

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

vi.mock('@/components/ui/Logo', () => ({ default: () => <div data-testid="logo">Logo</div> }))

import RegisterPage from '@/app/register/page'

/** 走到步骤二（企业信息）——步骤一必须先过手机号校验 */
async function gotoStepTwo(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByPlaceholderText('请输入手机号'), '13800138000')
  await user.type(screen.getByPlaceholderText('请输入6位验证码'), '123456')
  await user.click(screen.getByText('下一步'))
  await waitFor(() => expect(screen.getByPlaceholderText('请输入企业名称')).toBeInTheDocument())
}

/** 填必填项并提交，返回真实提交载荷 */
async function submitAndGetPayload(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByPlaceholderText('请输入企业名称'), '杭州测试布艺有限公司')
  await user.type(screen.getByPlaceholderText('请输入联系人姓名'), '张三')
  await user.click(screen.getByText('提交申请'))
  await waitFor(() => expect(mockSubmitRegistration).toHaveBeenCalledTimes(1))
  return mockSubmitRegistration.mock.calls[0][0] as { industry?: string }
}

describe('注册页「行业」受控下拉（issue #4363）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSendSmsCode.mockResolvedValue({ data: { success: true } })
    mockSubmitRegistration.mockResolvedValue({
      data: { data: { applicationId: 1, status: 'approved', message: 'ok' } },
    })
  })

  it('行业控件是下拉（select），不再是自由文本输入框', async () => {
    const user = userEvent.setup()
    render(<RegisterPage />)
    await gotoStepTwo(user)

    const industry = screen.getByLabelText(/行业/)
    expect(industry.tagName).toBe('SELECT')
    // 旧自由文本的 placeholder 必须消失（否则等于两套输入并存）
    expect(screen.queryByPlaceholderText('如：布艺纺织、家居建材、电子商务等')).not.toBeInTheDocument()
  })

  it('选项 = 空占位 + 冻结词表两项（value 是 code，显示名是中文）', async () => {
    const user = userEvent.setup()
    render(<RegisterPage />)
    await gotoStepTwo(user)

    const options = within(screen.getByLabelText(/行业/) as HTMLSelectElement).getAllByRole('option')
    expect(options.map((o) => (o as HTMLOptionElement).value)).toEqual(['', 'curtain', 'other'])
    expect(options.map((o) => o.textContent)).toEqual(['请选择行业（选填）', '布艺 / 窗帘', '其他'])
  })

  it('选「布艺 / 窗帘」⇒ 提交载荷 industry = curtain（code，不是显示名）', async () => {
    const user = userEvent.setup()
    render(<RegisterPage />)
    await gotoStepTwo(user)

    await user.selectOptions(screen.getByLabelText(/行业/), 'curtain')
    const payload = await submitAndGetPayload(user)
    expect(payload.industry).toBe('curtain')
  })

  it('选「其他」⇒ 提交载荷 industry = other + 显式提示不套用模板（不静默）', async () => {
    const user = userEvent.setup()
    render(<RegisterPage />)
    await gotoStepTwo(user)

    await user.selectOptions(screen.getByLabelText(/行业/), 'other')
    expect(screen.getByTestId('register-industry-other-hint')).toHaveTextContent('不自动套用')

    const payload = await submitAndGetPayload(user)
    expect(payload.industry).toBe('other')
  })

  it('不选行业 ⇒ 载荷不带 industry（不静默落默认模板）', async () => {
    const user = userEvent.setup()
    render(<RegisterPage />)
    await gotoStepTwo(user)

    const payload = await submitAndGetPayload(user)
    expect(payload.industry).toBeUndefined()
  })
})
