/**
 * 消息气泡组件测试
 *
 * 覆盖: 用户/AI消息渲染、流式光标、时间戳、卡片、工具调用指示器
 */
import React from 'react'
import { render, screen } from '@testing-library/react'
import MessageBubble from '../src/components/chat/MessageBubble'
import type { Message } from '../src/types'

// Mock 子组件
jest.mock('../src/components/cards/ProductCard', () => {
  return function MockProductCard({ data }: any) {
    return <div data-testid="product-card">{data?.name || 'product'}</div>
  }
})
jest.mock('../src/components/cards/LogisticsCard', () => {
  return function MockLogisticsCard() {
    return <div data-testid="logistics-card">logistics</div>
  }
})
jest.mock('../src/components/cards/KnowledgeCard', () => {
  return function MockKnowledgeCard() {
    return <div data-testid="knowledge-card">knowledge</div>
  }
})
jest.mock('../src/components/cards/ToolCallIndicator', () => {
  return function MockToolCallIndicator({ toolName, status }: any) {
    return <div data-testid="tool-indicator">{toolName}: {status}</div>
  }
})

describe('MessageBubble', () => {
  const baseMsg: Message = {
    id: 'm1',
    role: 'user',
    content: '你好',
    created_at: new Date().toISOString(),
  }

  it('应渲染用户消息内容', () => {
    render(<MessageBubble message={baseMsg} />)
    expect(screen.getByText('你好')).toBeTruthy()
  })

  it('应渲染 AI 消息内容', () => {
    const aiMsg: Message = { ...baseMsg, id: 'm2', role: 'assistant', content: '你好！有什么可以帮助您？' }
    render(<MessageBubble message={aiMsg} />)
    expect(screen.getByText('你好！有什么可以帮助您？')).toBeTruthy()
  })

  it('流式消息应显示光标', () => {
    const streamingMsg: Message = {
      ...baseMsg,
      id: 'm3',
      role: 'assistant',
      content: '正在回复',
      isStreaming: true,
    }
    render(<MessageBubble message={streamingMsg} />)
    expect(screen.getByText('|')).toBeTruthy()
  })

  it('非流式消息不显示光标', () => {
    render(<MessageBubble message={baseMsg} />)
    expect(screen.queryByText('|')).toBeNull()
  })

  it('应渲染时间戳', () => {
    const now = new Date()
    const hours = String(now.getHours()).padStart(2, '0')
    const minutes = String(now.getMinutes()).padStart(2, '0')
    const expectedTime = `${hours}:${minutes}`

    render(<MessageBubble message={baseMsg} />)
    expect(screen.getByText(expectedTime)).toBeTruthy()
  })

  it('应渲染工具调用指示器', () => {
    const msg: Message = {
      ...baseMsg,
      role: 'assistant',
      tool_calls: [
        { tool: 'search_product', status: 'running' },
        { tool: 'get_order', status: 'completed' },
      ],
    }
    render(<MessageBubble message={msg} />)

    const indicators = screen.getAllByTestId('tool-indicator')
    expect(indicators).toHaveLength(2)
  })

  it('应渲染商品卡片', () => {
    const msg: Message = {
      ...baseMsg,
      role: 'assistant',
      content: '为您找到以下商品：',
      cards: [
        { type: 'product_list', data: { products: [{ name: '窗帘A' }] } },
      ],
    }
    render(<MessageBubble message={msg} />)

    expect(screen.getByTestId('product-card')).toBeTruthy()
  })

  it('应渲染物流卡片', () => {
    const msg: Message = {
      ...baseMsg,
      role: 'assistant',
      content: '物流信息：',
      cards: [
        { type: 'logistics', data: { status: '运输中' } },
      ],
    }
    render(<MessageBubble message={msg} />)

    expect(screen.getByTestId('logistics-card')).toBeTruthy()
  })

  it('应渲染知识库卡片', () => {
    const msg: Message = {
      ...baseMsg,
      role: 'assistant',
      content: '参考资料：',
      cards: [
        { type: 'knowledge', data: [{ title: '安装指南' }] },
      ],
    }
    render(<MessageBubble message={msg} />)

    expect(screen.getByTestId('knowledge-card')).toBeTruthy()
  })

  it('未知卡片类型应显示占位', () => {
    const msg: Message = {
      ...baseMsg,
      role: 'assistant',
      cards: [{ type: 'unknown_type', data: {} }],
    }
    render(<MessageBubble message={msg} />)

    expect(screen.getByText(/unknown_type/)).toBeTruthy()
  })

  it('应处理单个 cardData (兼容模式)', () => {
    const msg: Message = {
      ...baseMsg,
      role: 'assistant',
      content: '详情',
      cardData: { type: 'product_detail', data: { product: { name: '窗帘B' } } },
    }
    render(<MessageBubble message={msg} />)

    expect(screen.getByTestId('product-card')).toBeTruthy()
  })

  it('tool_call 类型无 content 时不渲染文本', () => {
    const msg: Message = {
      ...baseMsg,
      role: 'assistant',
      content: '',
      type: 'tool_call',
      toolCall: { tool: 'test_tool', status: 'running' },
    }
    render(<MessageBubble message={msg} />)

    expect(screen.getByTestId('tool-indicator')).toBeTruthy()
  })
})
