// case_ids: OR-001, CH-001, UI-013
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
jest.mock('../src/components/cards/OrderCard', () => {
  return function MockOrderCard() {
    return <div data-testid="order-card">order</div>
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

  it('应渲染订单卡片（不再落入 📎 order 占位符）', () => {
    const msg: Message = {
      ...baseMsg,
      role: 'assistant',
      content: '为您查询到以下订单：',
      cards: [
        { type: 'order', data: { orders: [{ order_no: 'ORD-1001', status: 'shipped', status_text: '已发货' }] } },
      ],
    }
    render(<MessageBubble message={msg} />)

    expect(screen.getByTestId('order-card')).toBeTruthy()
    // 占位符不应出现：order 卡片类型必须有专门渲染分支
    expect(screen.queryByText(/📎 order/)).toBeNull()
  })

  it('应渲染单订单 cardData（{"order": ...} 兼容模式）', () => {
    const msg: Message = {
      ...baseMsg,
      role: 'assistant',
      content: '您的订单：',
      cardData: { type: 'order', data: { order: { order_no: 'ORD-2002', status: 'completed' } } },
    }
    render(<MessageBubble message={msg} />)

    expect(screen.getByTestId('order-card')).toBeTruthy()
    expect(screen.queryByText(/📎 order/)).toBeNull()
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

  // UI-013: 纯图消息（content 空 + images 有）不渲染空文本区，仅渲染图片
  it('纯图消息（无文本）渲染图片缩略图且不渲染空文本区', () => {
    const imgMsg: Message = {
      ...baseMsg,
      id: 'm-img',
      content: '',
      images: ['https://img.example.com/curtain.jpg'],
    }
    const { container } = render(<MessageBubble message={imgMsg} />)

    // 图片渲染（Taro Image mock 为 <img>）
    const img = container.querySelector('img')
    expect(img).toBeTruthy()
    expect(img?.getAttribute('src')).toBe('https://img.example.com/curtain.jpg')
    // 无空文本区（.message-bubble__content 不应存在）
    expect(container.querySelector('.message-bubble__content')).toBeNull()
  })

  // GB-02（GB/T 47746-2026, issue #2780）：AI 助手 / 人工客服来源标识
  it('assistant 文本消息应显示「AI 助手」来源标识', () => {
    const aiMsg: Message = {
      ...baseMsg,
      role: 'assistant',
      content: '这是 AI 回复',
    }
    render(<MessageBubble message={aiMsg} />)
    expect(screen.getByText(/AI 助手/)).toBeTruthy()
  })

  it('assistant 无文本（纯工具/卡片消息）不显示来源标识（不影响卡片语义与截图基线）', () => {
    const toolMsg: Message = {
      ...baseMsg,
      role: 'assistant',
      content: '',
      type: 'tool_call',
      toolCall: { tool: 'curtain_calc', status: 'completed' },
    }
    render(<MessageBubble message={toolMsg} />)
    expect(screen.queryByText(/AI 助手/)).toBeNull()
  })

  it('source=human 的消息显示「人工客服」标识且不显示「AI 助手」（转人工后人机可区分）', () => {
    const humanMsg: Message = {
      ...baseMsg,
      role: 'assistant',
      source: 'human',
      content: '您好，我是人工客服',
    }
    render(<MessageBubble message={humanMsg} />)
    // 标签（锚定首尾，避免与正文「我是人工客服」误匹配）
    expect(screen.getByText(/^👩‍💼 人工客服$/)).toBeTruthy()
    expect(screen.queryByText(/^🤖 AI 助手$/)).toBeNull()
  })

  it('user 消息不显示来源标识', () => {
    render(<MessageBubble message={baseMsg} />)
    expect(screen.queryByText(/AI 助手/)).toBeNull()
    expect(screen.queryByText(/人工客服/)).toBeNull()
  })
})
