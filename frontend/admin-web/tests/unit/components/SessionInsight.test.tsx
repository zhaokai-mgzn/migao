// case_ids: UI-019
/**
 * SessionInsight（会话简报抽屉）组件测试
 *
 * 覆盖 UI-019「米宝工作台『洞察』重构为『会话简报』」组件侧：
 *  - 标题/顶部按钮文案为「会话简报」；四区块齐备（结论/需要你处理/办理结果/接下来可以问）
 *  - 业务语言结论，不渲染工具原始名与 agent 内部动作（order_query/参数校验）
 *  - 办理结果明细行带状态徽标/金额/客户；建议 chip 点击即发送
 *  - 会话标识保留（弱化展示）；空会话显示友好空态
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import SessionInsight from '@/components/chat/SessionInsight'
import { useChatStore } from '@/store/chat'
import type { ChatSession, ChatMessage } from '@/types'

function assistantMsg(overrides: Partial<ChatMessage>): ChatMessage {
  return { id: `m-${Math.random().toString(36).slice(2, 8)}`, role: 'assistant', content: '', ...overrides }
}

function userMsg(content: string): ChatMessage {
  return { id: `m-${Math.random().toString(36).slice(2, 8)}`, role: 'user', content }
}

/** 一个完整业务会话：查询订单(卡片+建议) + 待确认交互 + 失败操作 */
const SESSION_ID = 'sess-001'
const SESSION: ChatSession = {
  session_id: SESSION_ID,
  title: '测试会话',
  status: 'active',
  message_count: 5,
  created_at: '2026-09-01T10:00:00Z',
  updated_at: '2026-09-01T10:10:00Z',
}

function buildMessages(): ChatMessage[] {
  return [
    userMsg('查看订单 A001'),
    assistantMsg({
      tool_calls: [
        {
          name: 'order_query',
          input: { order_no: 'A001' },
          status: 'completed',
          result: { success: true },
        },
      ],
      cards: [
        {
          type: 'order',
          data: {
            order: { id: 'o1', orderNo: 'A001', status: 'shipped', totalAmount: 2340, customerName: '张三' },
          },
        },
      ],
      suggestions: ['查看该订单物流', '查看客户历史订单'],
    }),
    userMsg('把 A002 改成已发货'),
    assistantMsg({
      tool_calls: [
        {
          name: 'order_manage',
          input: { order_no: 'A002', status: 'shipped' },
          status: 'error',
          result: { success: false, suggestion: '订单 A002 不存在或已删除' },
        },
      ],
    }),
    assistantMsg({
      interactive: {
        component: 'confirm',
        title: '确认修改订单 A001 为已发货？',
        fields: [{ label: '订单', value: 'A001' }],
        confirmLabel: '确认',
      },
    }),
  ]
}

beforeEach(() => {
  const sendMessage = vi.fn().mockResolvedValue(undefined)
  useChatStore.setState({
    currentSessionId: SESSION_ID,
    sessions: [SESSION],
    messages: buildMessages(),
    sendMessage,
  } as Partial<typeof useChatStore.getState>)
})

describe('SessionInsight 会话简报', () => {
  it('抽屉标题为「会话简报」，展开四区块', () => {
    render(<SessionInsight isOpen onClose={vi.fn()} />)
    expect(screen.getByText('会话简报')).toBeInTheDocument()
    expect(screen.getByText('会话结论')).toBeInTheDocument()
    expect(screen.getByText('需要你处理')).toBeInTheDocument()
    expect(screen.getByText('办理结果')).toBeInTheDocument()
    expect(screen.getByText('接下来可以问')).toBeInTheDocument()
  })

  it('会话结论为业务语言：聚合查询 + 失败原因 + 待确认提示', () => {
    render(<SessionInsight isOpen onClose={vi.fn()} />)
    expect(screen.getByText('查询了 1 笔订单')).toBeInTheDocument()
    expect(screen.getByText('订单管理失败：订单 A002 不存在或已删除')).toBeInTheDocument()
    expect(screen.getByText('有 1 项操作待你确认')).toBeInTheDocument()
  })

  it('需要你处理：渲染待确认安全闸卡（insight-pending-confirm）', () => {
    render(<SessionInsight isOpen onClose={vi.fn()} />)
    const pending = screen.getByTestId('insight-pending-confirm')
    expect(pending).toBeInTheDocument()
    expect(screen.getByText('米宝在等你确认')).toBeInTheDocument()
    expect(screen.getByText('确认修改订单 A001 为已发货？')).toBeInTheDocument()
  })

  it('办理结果：订单明细行带状态徽标/金额/客户，点击跳订单详情', () => {
    render(<SessionInsight isOpen onClose={vi.fn()} />)
    expect(screen.getByText('订单 A001')).toBeInTheDocument()
    expect(screen.getByText('已发货')).toBeInTheDocument()
    expect(screen.getByText('¥2,340.00')).toBeInTheDocument()
    expect(screen.getByText('张三')).toBeInTheDocument()
    const detailLink = screen.getByTitle('查看订单 A001 详情')
    expect(detailLink).toHaveAttribute('href', '/orders/o1')
  })

  it('接下来可以问：渲染建议 chip，点击即发送', () => {
    const sendMessage = vi.fn().mockResolvedValue(undefined)
    useChatStore.setState({ sendMessage } as Partial<typeof useChatStore.getState>)
    render(<SessionInsight isOpen onClose={vi.fn()} />)
    const suggestion = screen.getByText('查看该订单物流')
    expect(suggestion).toBeInTheDocument()
    fireEvent.click(suggestion)
    expect(sendMessage).toHaveBeenCalledWith('查看该订单物流')
  })

  it('不渲染机器语言：工具原始名与参数校验均不可见', () => {
    render(<SessionInsight isOpen onClose={vi.fn()} />)
    expect(screen.queryByText(/order_query|order_manage/)).not.toBeInTheDocument()
    expect(screen.queryByText('参数校验')).not.toBeInTheDocument()
    expect(screen.queryByText('处理进度')).not.toBeInTheDocument()
  })

  it('会话标识保留（弱化展示），拷贝按钮存在', () => {
    render(<SessionInsight isOpen onClose={vi.fn()} />)
    expect(screen.getByText(new RegExp(SESSION_ID))).toBeInTheDocument()
    expect(screen.getByTitle('复制会话标识')).toBeInTheDocument()
  })

  it('空会话 → 友好空态', () => {
    useChatStore.setState({ messages: [] } as Partial<typeof useChatStore.getState>)
    render(<SessionInsight isOpen onClose={vi.fn()} />)
    expect(screen.getByText(/向米宝提问后/)).toBeInTheDocument()
  })

  it('isOpen=false → 抽屉收起（不可见）', () => {
    render(<SessionInsight isOpen={false} onClose={vi.fn()} />)
    expect(screen.getByTestId('session-insight-drawer')).toHaveClass('invisible')
  })
})