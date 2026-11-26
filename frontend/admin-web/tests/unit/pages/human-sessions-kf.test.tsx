// case_ids: KF-029
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

// lucide-react mock（页面用 Bot/MessageSquare/Send）—— 必须 spread actual，见既有用例的说明
vi.mock('lucide-react', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>()
  const stub = (name: string) => (props: any) => <span data-testid={`icon-${name}`} {...props} />
  return { ...actual, Bot: stub('bot'), MessageSquare: stub('message-square'), Send: stub('send') }
})

const { getSessionsMock, getSessionMock, sendMessageMock } = vi.hoisted(() => ({
  getSessionsMock: vi.fn(),
  getSessionMock: vi.fn(),
  sendMessageMock: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  agentSessionApi: {
    getSessions: (...args: any[]) => getSessionsMock(...args),
    getSession: (...args: any[]) => getSessionMock(...args),
    sendMessage: (...args: any[]) => sendMessageMock(...args),
  },
}))

import HumanAgentSessionsPage from '@/app/(dashboard)/agent-workspace/human-sessions/page'

function listResolve(items: any[]) {
  return Promise.resolve({ data: { success: true, data: { items, total: items.length } } })
}
function detailResolve(session: any) {
  return Promise.resolve({
    data: { success: true, data: { ...session, status: 'active', messages: [] } },
  })
}

const plainSession = {
  id: 'as-plain',
  customerId: 'cust-1',
  customerName: '张先生',
  aiSessionId: 'ai-1',
  status: 'active',
  priority: 1,
  reason: '窗帘色差',
  queuePosition: 0,
  createdAt: '2026-11-25T10:00:00Z',
  startedAt: '2026-11-25T10:00:00Z',
}

const kfSession = {
  ...plainSession,
  id: 'as-kf',
  customerName: '李女士',
  channel: 'wechat_kf',
  sendStatus: 'accepted',
  budgetUsed: 2,
  budgetLimit: 5,
}

describe('工作台：微信客服状态渲染（issue #9202 / 母单 #9194 子项 2 前端面）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sendMessageMock.mockResolvedValue({ data: { success: true, data: {} } })
  })

  it('微信客服会话 ⇒ 渠道标识 + 发送状态 + 48h 余量', async () => {
    getSessionsMock.mockReturnValue(listResolve([kfSession]))
    render(<HumanAgentSessionsPage />)

    await waitFor(() => expect(screen.getByTestId('kf-badge-as-kf')).toBeTruthy())
    expect(screen.getByTestId('kf-badge-as-kf').textContent).toContain('微信客服')
    expect(screen.getByTestId('kf-send-status-as-kf').textContent).toContain('已接收')
    expect(screen.getByTestId('kf-budget-as-kf').textContent).toContain('2/5')
  })

  it('普通人工会话 ⇒ 不出现任何微信客服标识（不得伪造渠道）', async () => {
    getSessionsMock.mockReturnValue(listResolve([plainSession]))
    render(<HumanAgentSessionsPage />)

    await waitFor(() => expect(screen.getByText('张先生')).toBeTruthy())
    expect(screen.queryByTestId('kf-badge-as-plain')).toBeNull()
    expect(screen.queryByText('微信客服')).toBeNull()
  })

  it('sendStatus=unknown ⇒ 明确的「状态未知」，不留空白', async () => {
    getSessionsMock.mockReturnValue(
      listResolve([{ ...kfSession, sendStatus: 'unknown' }]),
    )
    render(<HumanAgentSessionsPage />)

    await waitFor(() => expect(screen.getByTestId('kf-send-status-as-kf')).toBeTruthy())
    expect(screen.getByTestId('kf-send-status-as-kf').textContent).toContain('状态未知')
  })

  it('余量用尽（5/5）⇒ 输入框禁用 + 明确文案', async () => {
    const exhausted = { ...kfSession, budgetUsed: 5 }
    getSessionsMock.mockReturnValue(listResolve([exhausted]))
    getSessionMock.mockReturnValue(detailResolve(exhausted))
    render(<HumanAgentSessionsPage />)

    await waitFor(() => expect(screen.getByTestId('kf-badge-as-kf')).toBeTruthy())
    fireEvent.click(screen.getByText('李女士'))

    await waitFor(() => expect(screen.getByTestId('kf-budget-exhausted')).toBeTruthy())
    const textarea = screen.getByPlaceholderText(/48 小时|额度/)
    expect((textarea as HTMLTextAreaElement).disabled).toBe(true)
  })
})
