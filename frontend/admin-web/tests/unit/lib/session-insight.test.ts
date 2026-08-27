// case_ids: CH-001, CH-002, CH-003
/**
 * session-insight 纯函数单测 — 会话洞察面板（米宝工作助手）数据层
 *
 * 覆盖：工具元数据、历史 tool_calls 归一化、工具事件提取、
 * 待确认交互检测、业务对象实体提取/分组。
 *
 * 背景：米宝（B端工作助手）的工作范式是「查询 → validate_input →
 * confirm 交互卡 → 写操作 → 追问建议」，会话洞察面板基于
 * tool_calls 流水重建这份工作台账；历史接口只返回 {tool, args} 形状，
 * 归一化保证刷新页面后洞察数据依然可靠。
 */
import { describe, it, expect } from 'vitest'
import {
  getToolMeta,
  normalizeToolCall,
  normalizeToolCalls,
  extractToolEvents,
  detectPendingInteraction,
  extractEntities,
  groupEntities,
} from '@/lib/session-insight'
import type { ChatMessage } from '@/types'

// 宽松类型：历史消息的 tool_calls 为 {tool, args} 形状，不满足 ChatToolCall 声明
function msg(overrides: Partial<ChatMessage> & Record<string, any> = {}): ChatMessage {
  return { id: 'm1', role: 'assistant', content: '', ...overrides }
}

/** 模拟后端历史接口持久化的 tool_call 形状 {tool, args} */
const persistedCall = (tool: string, args: Record<string, unknown> = {}): any => ({ tool, args })

// ═══════════════════════════════════════════════════
// getToolMeta — 米宝工具中文名 / 领域 / 读写属性
// ═══════════════════════════════════════════════════

describe('getToolMeta', () => {
  it('maps read query tools to domain metadata', () => {
    expect(getToolMeta('order_query')).toEqual({ label: '查询订单', domain: 'order', write: false })
    expect(getToolMeta('product_search')).toEqual({ label: '搜索商品', domain: 'product', write: false })
    expect(getToolMeta('logistics_track')).toEqual({ label: '查询物流', domain: 'logistics', write: false })
    expect(getToolMeta('aftersale_query')).toEqual({ label: '查询售后', domain: 'aftersale', write: false })
    expect(getToolMeta('dashboard_stats')).toEqual({ label: '查询数据看板', domain: 'data', write: false })
  })

  it('marks write tools with write=true', () => {
    expect(getToolMeta('order_manage')).toEqual({ label: '订单管理', domain: 'order', write: true })
    expect(getToolMeta('product_manage')).toEqual({ label: '商品管理', domain: 'product', write: true })
    expect(getToolMeta('customer_manage')).toEqual({ label: '客户管理', domain: 'customer', write: true })
  })

  it('maps workflow tools (interact/handoff) to workflow domain', () => {
    expect(getToolMeta('interact')).toEqual({ label: '请求确认', domain: 'workflow', write: false })
    expect(getToolMeta('human_handoff')).toEqual({ label: '转人工', domain: 'workflow', write: false })
  })

  it('falls back to raw name for unknown tools', () => {
    expect(getToolMeta('unknown_tool_x')).toEqual({ label: 'unknown_tool_x', domain: 'workflow', write: false })
  })
})

// ═══════════════════════════════════════════════════
// normalizeToolCall / normalizeToolCalls — 历史与实时形状归一化
// ═══════════════════════════════════════════════════

describe('normalizeToolCall', () => {
  it('passes through live {name,input,status} shape unchanged', () => {
    const live = { name: 'product_search', input: { keyword: '窗帘' }, status: 'running' as const }
    expect(normalizeToolCall(live)).toEqual(live)
  })

  it('normalizes persisted {tool,args} shape to frontend shape', () => {
    expect(normalizeToolCall({ tool: 'order_query', args: { order_id: 'ORD-1' } })).toEqual({
      name: 'order_query',
      input: { order_id: 'ORD-1' },
      status: 'completed',
    })
  })

  it('marks persisted call as error when result.success is false', () => {
    expect(
      normalizeToolCall({ tool: 'order_manage', args: {}, result: { success: false, suggestion: '重试' } }),
    ).toEqual({
      name: 'order_manage',
      input: {},
      result: { success: false, suggestion: '重试' },
      status: 'error',
    })
  })

  it('keeps result on live completed calls', () => {
    expect(
      normalizeToolCall({ name: 'order_query', input: { order_id: 'ORD-1' }, status: 'completed', result: { ok: 1 } }),
    ).toEqual({ name: 'order_query', input: { order_id: 'ORD-1' }, status: 'completed', result: { ok: 1 } })
  })

  it('returns null for non-object or nameless entries', () => {
    expect(normalizeToolCall(null)).toBeNull()
    expect(normalizeToolCall(undefined)).toBeNull()
    expect(normalizeToolCall('order_query')).toBeNull()
    expect(normalizeToolCall({ input: {} })).toBeNull()
    expect(normalizeToolCall({ name: '' })).toBeNull()
  })
})

describe('normalizeToolCalls', () => {
  it('returns empty array for non-array input', () => {
    expect(normalizeToolCalls(undefined)).toEqual([])
    expect(normalizeToolCalls(null)).toEqual([])
    expect(normalizeToolCalls({ tool: 'x' })).toEqual([])
  })

  it('keeps valid entries and drops invalid ones', () => {
    expect(
      normalizeToolCalls([
        { tool: 'order_query', args: { order_id: 'ORD-1' } },
        null,
        { name: 'product_search', input: {}, status: 'running' },
      ]),
    ).toEqual([
      { name: 'order_query', input: { order_id: 'ORD-1' }, status: 'completed' },
      { name: 'product_search', input: {}, status: 'running' },
    ])
  })
})

// ═══════════════════════════════════════════════════
// extractToolEvents — 工作流时间线（最新在前）
// ═══════════════════════════════════════════════════

describe('extractToolEvents', () => {
  it('extracts events newest-first with tool metadata', () => {
    const messages: ChatMessage[] = [
      msg({ id: 'm1', tool_calls: [{ name: 'order_query', input: {}, status: 'completed' }] }),
      msg({ id: 'm2', tool_calls: [{ name: 'product_search', input: {}, status: 'completed' }] }),
    ]

    const events = extractToolEvents(messages)

    expect(events).toHaveLength(2)
    expect(events[0].messageId).toBe('m2')
    expect(events[0].tool.name).toBe('product_search')
    expect(events[0].meta.label).toBe('搜索商品')
    expect(events[1].messageId).toBe('m1')
    expect(events[1].tool.name).toBe('order_query')
  })

  it('normalizes persisted tool_calls within messages', () => {
    const messages: ChatMessage[] = [
      msg({ tool_calls: [persistedCall('logistics_track', { tracking_no: 'SF-1' })] }),
    ]

    const events = extractToolEvents(messages)

    expect(events).toHaveLength(1)
    expect(events[0].tool).toEqual({
      name: 'logistics_track',
      input: { tracking_no: 'SF-1' },
      status: 'completed',
    })
    expect(events[0].meta.domain).toBe('logistics')
  })

  it('ignores messages without tool_calls', () => {
    const messages: ChatMessage[] = [
      msg({ role: 'user', content: '你好' }),
      msg({ content: '你好呀' }),
    ]
    expect(extractToolEvents(messages)).toEqual([])
  })
})

// ═══════════════════════════════════════════════════
// detectPendingInteraction — 米宝在等你确认
// ═══════════════════════════════════════════════════

describe('detectPendingInteraction', () => {
  const confirmInteractive = { component: 'confirm' as const, title: '确认创建订单' }

  it('detects unanswered interactive on the last assistant message', () => {
    const messages: ChatMessage[] = [
      msg({ role: 'user', content: '创建订单' }),
      msg({ id: 'a1', interactive: confirmInteractive }),
    ]
    expect(detectPendingInteraction(messages)).toEqual(confirmInteractive)
  })

  it('returns null when the user has answered the interactive', () => {
    const messages: ChatMessage[] = [
      msg({ role: 'user', content: '创建订单' }),
      msg({ id: 'a1', interactive: confirmInteractive }),
      msg({ role: 'user', content: '确认' }),
      msg({ id: 'a2', content: '订单已创建' }),
    ]
    expect(detectPendingInteraction(messages)).toBeNull()
  })

  it('returns null when last message is from the user', () => {
    const messages: ChatMessage[] = [
      msg({ id: 'a1', interactive: confirmInteractive }),
      msg({ role: 'user', content: '确认' }),
    ]
    expect(detectPendingInteraction(messages)).toBeNull()
  })

  it('ignores aborted interactives', () => {
    const messages: ChatMessage[] = [
      msg({ role: 'user', content: '创建订单' }),
      msg({ id: 'a1', interactive: confirmInteractive, wasAborted: true }),
    ]
    expect(detectPendingInteraction(messages)).toBeNull()
  })

  it('returns null for empty messages', () => {
    expect(detectPendingInteraction([])).toBeNull()
  })
})

// ═══════════════════════════════════════════════════
// extractEntities — 业务对象实体提取
// ═══════════════════════════════════════════════════

describe('extractEntities', () => {
  it('extracts order entity from persisted tool args', () => {
    const messages: ChatMessage[] = [
      msg({ tool_calls: [persistedCall('order_query', { order_id: 'ORD-001' })] }),
    ]
    const entities = extractEntities(messages)
    expect(entities).toHaveLength(1)
    expect(entities[0]).toEqual({
      type: 'order', value: 'ORD-001', label: '订单 ORD-001', followUp: '查看订单 ORD-001',
    })
  })

  it('extracts logistics entity from live tool input', () => {
    const messages: ChatMessage[] = [
      msg({ tool_calls: [{ name: 'logistics_track', input: { tracking_no: 'SF-99' }, status: 'completed' }] }),
    ]
    expect(extractEntities(messages)[0]).toEqual({
      type: 'logistics', value: 'SF-99', label: '物流 SF-99', followUp: '查询物流 SF-99',
    })
  })

  it('extracts aftersale and customer entities from input keys', () => {
    const messages: ChatMessage[] = [
      msg({
        tool_calls: [
          { name: 'aftersale_query', input: { ticket_no: 'AS-7' }, status: 'completed' },
          { name: 'customer_manage', input: { customer_name: '王女士' }, status: 'completed' },
        ],
      }),
    ]
    const entities = extractEntities(messages)
    expect(entities.map(e => e.type)).toEqual(['aftersale', 'customer'])
    expect(entities[0].followUp).toBe('查看售后工单 AS-7')
    expect(entities[1].followUp).toBe('查看客户 王女士')
  })

  it('extracts product entities from live cards', () => {
    const messages: ChatMessage[] = [
      msg({
        cards: [
          { type: 'product_list', data: { products: [{ name: '遮光窗帘' }, { name: '透光纱帘' }] } },
        ],
      }),
    ]
    const entities = extractEntities(messages)
    expect(entities.map(e => e.value)).toEqual(['遮光窗帘', '透光纱帘'])
    expect(entities[0].followUp).toBe('查看 遮光窗帘 详情')
  })

  it('extracts entities from completed tool results (live)', () => {
    const messages: ChatMessage[] = [
      msg({
        tool_calls: [
          {
            name: 'order_query', input: {}, status: 'completed',
            result: { success: true, data: { order: { orderNo: 'ORD-R1' } } },
          },
          {
            name: 'logistics_track', input: {}, status: 'completed',
            result: { tracking_no: 'SF-R', status: '运输中' },
          },
        ],
      }),
    ]
    const entities = extractEntities(messages)
    expect(entities.map(e => `${e.type}:${e.value}`)).toEqual(['order:ORD-R1', 'logistics:SF-R'])
  })

  it('deduplicates entities across tool_calls and cards', () => {
    const messages: ChatMessage[] = [
      msg({
        tool_calls: [{ name: 'order_query', input: { order_id: 'ORD-001' }, status: 'completed' }],
        cards: [{ type: 'order', data: { order: { orderNo: 'ORD-001' } } }],
      }),
    ]
    const entities = extractEntities(messages)
    expect(entities).toHaveLength(1)
    expect(entities[0].value).toBe('ORD-001')
  })

  it('ignores empty values and messages without entities', () => {
    const messages: ChatMessage[] = [
      msg({ tool_calls: [{ name: 'order_query', input: { order_id: '' }, status: 'completed' }] }),
      msg({ content: '普通闲聊' }),
    ]
    expect(extractEntities(messages)).toEqual([])
  })
})

// ═══════════════════════════════════════════════════
// groupEntities — 按业务域分组
// ═══════════════════════════════════════════════════

describe('groupEntities', () => {
  it('groups entities by type preserving first-occurrence order', () => {
    const entities = [
      { type: 'order' as const, value: 'O1', label: '订单 O1', followUp: '查看订单 O1' },
      { type: 'product' as const, value: 'P1', label: '商品 P1', followUp: '查看 P1 详情' },
      { type: 'order' as const, value: 'O2', label: '订单 O2', followUp: '查看订单 O2' },
      { type: 'logistics' as const, value: 'L1', label: '物流 L1', followUp: '查询物流 L1' },
    ]

    const groups = groupEntities(entities)

    expect(groups.map(g => g.type)).toEqual(['order', 'product', 'logistics'])
    expect(groups.map(g => g.label)).toEqual(['订单', '商品', '物流'])
    expect(groups[0].entities.map(e => e.value)).toEqual(['O1', 'O2'])
  })

  it('returns empty array for empty input', () => {
    expect(groupEntities([])).toEqual([])
  })
})
