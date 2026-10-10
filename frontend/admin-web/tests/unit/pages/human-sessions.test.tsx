// case_ids: CH-008, CH-017
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

// lucide-react mock — 页面使用 Bot/MessageSquare/Send
vi.mock('lucide-react', () => {
  const stub = (name: string) => (props: any) => <span data-testid={`icon-${name}`} {...props} />
  return {
    Bot: stub('bot'),
    MessageSquare: stub('message-square'),
    Send: stub('send'),
  }
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

function detailResolve(detail: any) {
  return Promise.resolve({ data: { success: true, data: detail } })
}

const baseSession = {
  id: 'as-1',
  customerId: 'cust-1',
  customerName: '张先生',
  aiSessionId: 'ai-1',
  status: 'waiting' as const,
  priority: 1,
  reason: '窗帘色差',
  queuePosition: 0,
  createdAt: '2026-09-01T10:00:00Z',
  startedAt: '2026-09-01T10:00:00Z',
}

const detailWithAiContext = {
  ...baseSession,
  status: 'active',
  aiContextSummary: '顾客反馈窗帘色差，要求人工处理',
  aiContext: [
    { role: 'user', content: '窗帘有色差吗？' },
    { role: 'assistant', content: '正在为您核实，请稍候。' },
  ],
  messages: [
    {
      id: 'msg-1',
      senderType: 'agent',
      senderId: 'emp-1',
      senderName: '客服小王',
      contentType: 'text',
      content: '您好，我是人工客服，已看到您之前和 AI 客服的沟通，我来帮您处理。',
      isInternal: false,
      createdAt: '2026-09-01T10:01:00Z',
    },
  ],
}

const detailWithoutAiContext = {
  ...baseSession,
  aiContextSummary: null,
  aiContext: null,
  messages: [
    {
      id: 'msg-2',
      senderType: 'agent',
      senderId: 'emp-1',
      senderName: '客服小王',
      contentType: 'text',
      content: '您好，请问有什么可以帮您？',
      isInternal: false,
      createdAt: '2026-09-01T10:01:00Z',
    },
  ],
}

describe('在线接待工作台 - 转人工前 AI 对话上下文展示（GB/T 47746-2026, issue #2776）', () => {
  beforeEach(() => {
    getSessionsMock.mockReset()
    getSessionMock.mockReset()
  })

  it('会话含 aiContext 时展示 AI 对话分区 + 摘要 + 人工接待分隔，人工消息照常渲染', async () => {
    getSessionsMock.mockResolvedValue(listResolve([baseSession]))
    getSessionMock.mockResolvedValue(detailResolve(detailWithAiContext))

    render(<HumanAgentSessionsPage />)

    // 等会话卡片「可见」再点击 —— 不能只等 mock 被调用：mock 已调用但列表还没 render 时
    // getByText 会抛 getElementError（全量套件负载下偶发，issue #3688）
    fireEvent.click(await screen.findByText('张先生'))
    // 前置条件（触发确认）：会话列表 API 确已调用 —— 结果可见性由上方 click 起效断言
    expect(getSessionsMock).toHaveBeenCalled()

    // AI 上下文分区（标题/摘要/角色标注/内容）
    expect(await screen.findByText(/顾客与 AI 客服（元元）的对话 · 转人工前/)).toBeInTheDocument()
    expect(screen.getByText(/📋 对话摘要：顾客反馈窗帘色差，要求人工处理/)).toBeInTheDocument()
    expect(screen.getByText('元元 · 企业智能客服')).toBeInTheDocument()
    expect(screen.getByText('窗帘有色差吗？')).toBeInTheDocument()
    expect(screen.getByText('正在为您核实，请稍候。')).toBeInTheDocument()
    // 人工接待分隔
    expect(screen.getByText(/以下为人工接待记录/)).toBeInTheDocument()
    // 人工客服消息仍正常展示
    expect(screen.getByText(/您好，我是人工客服/)).toBeInTheDocument()
  })

  it('会话无 aiContext（老会话/空快照）时不渲染 AI 分区，页面正常', async () => {
    getSessionsMock.mockResolvedValue(listResolve([baseSession]))
    getSessionMock.mockResolvedValue(detailResolve(detailWithoutAiContext))

    render(<HumanAgentSessionsPage />)

    // 同上：等卡片可见再点击（issue #3688）
    fireEvent.click(await screen.findByText('张先生'))
    expect(getSessionsMock).toHaveBeenCalled()

    // 详情「可见」断言：等详情加载完成后再断言页面状态（不能只等 getSessionMock 被调用）
    expect(await screen.findByText(/您好，请问有什么可以帮您/)).toBeInTheDocument()
    // 前置条件（触发确认）：详情 API 确已调用
    expect(getSessionMock).toHaveBeenCalled()
    // 无 aiContext：不渲染 AI 分区，页面正常
    expect(screen.queryByText(/顾客与 AI 客服（元元）的对话 · 转人工前/)).not.toBeInTheDocument()
    expect(screen.queryByText(/以下为人工接待记录/)).not.toBeInTheDocument()
  })
})

/**
 * 修复包 #6664 第 1 条：转人工接待**发送失败零提示**。
 *
 * 改前（缺陷形态）：`handleSend` 的 catch 只有 `console.error`，且
 * `res.data?.success === false` 时**什么都不做** —— 客服以为回了，其实没发出去。
 * 判据：失败必须可见（哪条没发出去 + 重试出口），**输入内容不得丢**，成功才清空。
 */
describe('在线接待工作台 - 发送失败可见 + 输入不丢（issue #6664 第 1 条）', () => {
  beforeEach(() => {
    getSessionsMock.mockReset()
    getSessionMock.mockReset()
    sendMessageMock.mockReset()
    getSessionsMock.mockResolvedValue(listResolve([baseSession]))
    getSessionMock.mockResolvedValue(detailResolve(detailWithoutAiContext))
  })

  async function openSessionAndType(text: string) {
    render(<HumanAgentSessionsPage />)
    fireEvent.click(await screen.findByText('张先生'))
    const box = await screen.findByPlaceholderText(/输入回复内容/)
    fireEvent.change(box, { target: { value: text } })
    return box as HTMLTextAreaElement
  }

  it('① 发送接口抛错 ⇒ 失败提示可见 + 输入内容仍在 + 列表无新增消息', async () => {
    sendMessageMock.mockRejectedValue(new Error('network down'))
    const box = await openSessionAndType('这条发不出去')

    fireEvent.click(screen.getByRole('button', { name: /发送/ }))

    // 失败可见（人话，不带内部错误细节）
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toMatch(/发送失败/)
    expect(alert.textContent).toMatch(/这条发不出去/)
    // 可重试出口
    expect(screen.getByRole('button', { name: /重试/ })).toBeEnabled()
    // 输入不丢
    expect(box).toHaveValue('这条发不出去')
    // 消息列表没有冒出一条本地幻觉消息
    expect(screen.queryByText('这条发不出去', { selector: '.whitespace-pre-wrap' })).toBeNull()
  })

  it('② 接口 200 但 success=false ⇒ 同样可见失败（不是静默）', async () => {
    sendMessageMock.mockResolvedValue({ data: { success: false, message: '会话已结束' } })
    const box = await openSessionAndType('成功标志为假')

    fireEvent.click(screen.getByRole('button', { name: /发送/ }))

    expect((await screen.findByRole('alert')).textContent).toMatch(/发送失败/)
    expect(box).toHaveValue('成功标志为假')
  })

  it('③ 重试成功后：输入清空 + 新消息出现在列表（失败提示消失）', async () => {
    sendMessageMock.mockRejectedValueOnce(new Error('boom'))
    const box = await openSessionAndType('重试就好')

    fireEvent.click(screen.getByRole('button', { name: /发送/ }))
    await screen.findByRole('alert')

    // 重试这一条：接口这次成功，且详情回读里带上这条消息
    sendMessageMock.mockResolvedValueOnce({ data: { success: true } })
    getSessionMock.mockResolvedValue(
      detailResolve({
        ...detailWithoutAiContext,
        messages: [
          ...detailWithoutAiContext.messages,
          {
            id: 'msg-sent',
            senderType: 'agent',
            senderId: 'emp-1',
            senderName: '客服小王',
            contentType: 'text',
            content: '重试就好',
            isInternal: false,
            createdAt: '2026-09-01T10:02:00Z',
          },
        ],
      }),
    )

    fireEvent.click(screen.getByRole('button', { name: /重试/ }))

    await waitFor(() => expect(sendMessageMock).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(box).toHaveValue(''))
    expect(await screen.findByText('重试就好')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('④ 失败提示里不出现内部标识（无堆栈 / 英文错误码 / 字段名）', async () => {
    sendMessageMock.mockRejectedValue(new Error('AxiosError: Request failed with status code 500'))
    await openSessionAndType('别泄漏内部细节')

    fireEvent.click(screen.getByRole('button', { name: /发送/ }))

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).not.toMatch(/Axios|Error|status code|stack|\b500\b/i)
  })
})

/**
 * 修复包 #6664 第 2 条：列表 / 详情**拉取失败显示成空态**。
 * 判据：失败态与空态分离 —— 接口失败时**不得**渲染「暂无转人工会话」，且给重试出口。
 */
describe('在线接待工作台 - 失败态 ≠ 空态（issue #6664 第 2 条）', () => {
  beforeEach(() => {
    getSessionsMock.mockReset()
    getSessionMock.mockReset()
  })

  it('① 会话列表拉取失败 ⇒ 显示加载失败 + 重试，绝不显示「暂无转人工会话」', async () => {
    getSessionsMock.mockRejectedValue(new Error('boom'))

    render(<HumanAgentSessionsPage />)

    expect(await screen.findByText(/加载失败/)).toBeInTheDocument()
    expect(screen.queryByText(/暂无转人工会话/)).toBeNull()
  })

  it('② 列表**成功但为空** ⇒ 仍走空态（失败态没有吃掉空态）', async () => {
    getSessionsMock.mockResolvedValue(listResolve([]))

    render(<HumanAgentSessionsPage />)

    expect(await screen.findByText(/暂无转人工会话/)).toBeInTheDocument()
    expect(screen.queryByText(/加载失败/)).toBeNull()
  })

  it('③ 详情拉取失败 ⇒ 右侧说「加载失败」且能重试，不说「选择左侧会话」（那是未选中态）', async () => {
    getSessionsMock.mockResolvedValue(listResolve([baseSession]))
    getSessionMock.mockRejectedValue(new Error('boom'))

    render(<HumanAgentSessionsPage />)
    fireEvent.click(await screen.findByText('张先生'))

    expect(await screen.findByText(/加载失败/)).toBeInTheDocument()
    expect(screen.queryByText(/选择左侧会话开始接待/)).toBeNull()
    expect(screen.getByRole('button', { name: /重试/ })).toBeEnabled()
  })

  it('④ 失败后点重试 ⇒ 重新取数并渲染出内容（重试不是摆设）', async () => {
    getSessionsMock.mockRejectedValueOnce(new Error('boom'))

    render(<HumanAgentSessionsPage />)
    await screen.findByText(/加载失败/)

    getSessionsMock.mockResolvedValue(listResolve([baseSession]))
    fireEvent.click(screen.getByRole('button', { name: /重试/ }))

    expect(await screen.findByText('张先生')).toBeInTheDocument()
  })
})

/**
 * 修复包 #6664 第 7 条：日期口径收敛到唯一真值源 `common/DateTimeCell`
 * （两行：`YYYY-MM-DD` + `HH:mm`）。改前本页只印 `HH:mm`，看不出是哪一天。
 */
describe('在线接待工作台 - 日期走唯一真值源 DateTimeCell（issue #6664 第 7 条）', () => {
  it('会话卡片与消息时间都渲染 日期 + 时刻（不止 HH:mm）', async () => {
    getSessionsMock.mockResolvedValue(listResolve([baseSession]))
    getSessionMock.mockResolvedValue(detailResolve(detailWithoutAiContext))

    render(<HumanAgentSessionsPage />)
    fireEvent.click(await screen.findByText('张先生'))

    await screen.findByText(/您好，请问有什么可以帮您/)
    // DateTimeCell 的两行形态：`YYYY-MM-DD` + `HH:mm`（时区无关断言，不写死换算后的时刻）
    expect(screen.getAllByText(/^\d{4}-\d{2}-\d{2}$/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/^\d{2}:\d{2}$/).length).toBeGreaterThan(0)
  })
})
