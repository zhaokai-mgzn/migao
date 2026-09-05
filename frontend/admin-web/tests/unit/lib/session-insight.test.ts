// case_ids: UI-019
/**
 * session-insight（会话简报）纯函数推导测试
 *
 * 覆盖 UI-019「米宝工作台『洞察』重构为『会话简报』」：
 *  - buildSessionBrief   — 业务语言会话结论（查询聚合/写操作完成/失败/待确认）
 *  - extractLedgerRows   — 办理结果明细行（订单带状态/金额/客户，卡片 → 兜底 arg 去重）
 *  - collectSuggestions  — 最近 assistant 消息的后续问题建议
 *
 * 关键约束：结论与明细全部是业务语言，不出现工具原始名（order_query 等）与
 * agent 内部动作（参数校验/请求确认）。
 */
import { describe, it, expect } from 'vitest'
import {
  buildSessionBrief,
  extractLedgerRows,
  collectSuggestions,
} from '@/lib/session-insight'
import type { ChatMessage } from '@/types'

// ═══════════════════════════════════════════════════════════
// Fixture 构造
// ═══════════════════════════════════════════════════════════

function assistantMsg(overrides: Partial<ChatMessage>): ChatMessage {
  return {
    id: `m-${Math.random().toString(36).slice(2, 8)}`,
    role: 'assistant',
    content: '',
    ...overrides,
  }
}

/** 订单查询成功（含卡片） */
function orderQuerySuccess(orderNo: string, status: string, amount: number, customer: string, id?: string): ChatMessage {
  return assistantMsg({
    tool_calls: [
      {
        name: 'order_query',
        input: { order_no: orderNo },
        status: 'completed',
        result: { success: true },
      },
    ],
    cards: [
      {
        type: 'order',
        data: {
          order: {
            id: id ?? `o-${orderNo}`,
            orderNo,
            status,
            totalAmount: amount,
            customerName: customer,
          },
        },
      },
    ],
  })
}

/** 订单查询失败（result.suggestion 业务化原因） */
function orderQueryFailed(orderNo: string, suggestion: string): ChatMessage {
  return assistantMsg({
    tool_calls: [
      {
        name: 'order_query',
        input: { order_no: orderNo },
        status: 'error',
        result: { success: false, suggestion },
      },
    ],
  })
}

/** 写操作成功（创建售后工单） */
function aftersaleCreateDone(ticketNo: string): ChatMessage {
  return assistantMsg({
    tool_calls: [
      {
        name: 'aftersale_create',
        input: { ticket_no: ticketNo },
        status: 'completed',
        result: { success: true },
      },
    ],
  })
}

/** agent 内部编排工具（参数校验/请求确认）— 不应进入结论 */
function internalWorkflowTools(): ChatMessage {
  return assistantMsg({
    tool_calls: [
      { name: 'validate_input', input: { order_no: 'A001' }, status: 'completed', result: { success: true } },
      { name: 'interact', input: {}, status: 'completed', result: { success: true } },
    ],
  })
}

/** 待用户确认的交互卡（写操作安全闸） */
function pendingConfirm(): ChatMessage {
  return assistantMsg({
    interactive: {
      component: 'confirm',
      title: '确认修改订单 A001 为已发货？',
      fields: [{ label: '订单', value: 'A001' }],
      confirmLabel: '确认',
    },
  })
}

// ═══════════════════════════════════════════════════════════
// buildSessionBrief — 会话结论
// ═══════════════════════════════════════════════════════════

describe('buildSessionBrief', () => {
  it('空会话 → 无结论行，订单合计为空', () => {
    const brief = buildSessionBrief([])
    expect(brief.lines).toEqual([])
    expect(brief.totals).toEqual({ orders: 0, amount: null })
  })

  it('查询订单成功（含卡片）→ 聚合为「查询了 N 笔订单」+ 订单金额合计', () => {
    const messages = [
      orderQuerySuccess('A001', 'shipped', 2340, '张三'),
      orderQuerySuccess('A002', 'pending', 168, '李四'),
    ]
    const brief = buildSessionBrief(messages)
    expect(brief.lines).toContainEqual({ kind: 'done', text: '查询了 2 笔订单' })
    expect(brief.totals).toEqual({ orders: 2, amount: 2508 })
  })

  it('同一订单号跨消息去重：合计只算一笔', () => {
    const messages = [
      orderQuerySuccess('A001', 'shipped', 2340, '张三'),
      orderQuerySuccess('A001', 'completed', 2340, '张三'),
    ]
    const brief = buildSessionBrief(messages)
    expect(brief.totals).toEqual({ orders: 1, amount: 2340 })
  })

  it('写操作完成 → 「已创建售后工单」业务语言', () => {
    const brief = buildSessionBrief([aftersaleCreateDone('AF-9')])
    expect(brief.lines).toContainEqual({ kind: 'done', text: '已创建售后工单' })
  })

  it('查询失败 → failed 行携带业务化原因', () => {
    const brief = buildSessionBrief([orderQueryFailed('A001', '订单不存在或已删除')])
    expect(brief.lines).toContainEqual({ kind: 'failed', text: '查询订单失败：订单不存在或已删除' })
  })

  it('待确认交互 → pending 行提示操作待确认', () => {
    const brief = buildSessionBrief([orderQuerySuccess('A001', 'pending', 168, '张三'), pendingConfirm()])
    expect(brief.lines).toContainEqual({ kind: 'pending', text: '有 1 项操作待你确认' })
  })

  it('结论不含 agent 内部工具：参数校验/请求确认不产出任何行，也不出现工具原始名', () => {
    const messages = [internalWorkflowTools(), orderQuerySuccess('A001', 'shipped', 2340, '张三')]
    const brief = buildSessionBrief(messages)
    // 不产出「已完成参数校验」「已完成请求确认」
    expect(brief.lines).not.toContainEqual({ kind: 'done', text: '已完成参数校验' })
    expect(brief.lines).not.toContainEqual({ kind: 'done', text: '已完成请求确认' })
    // 全部行文本中不得出现工具原始名（机器语言）
    for (const line of brief.lines) {
      expect(line.text).not.toMatch(/order_query|validate_input|interact|tool/i)
    }
  })

  it('数据看板查询 → 「查看了经营数据」', () => {
    const msg = assistantMsg({
      tool_calls: [
        { name: 'dashboard_stats', input: {}, status: 'completed', result: { success: true } },
      ],
    })
    const brief = buildSessionBrief([msg])
    expect(brief.lines).toContainEqual({ kind: 'done', text: '查看了经营数据' })
  })
})

// ═══════════════════════════════════════════════════════════
// extractLedgerRows — 办理结果明细
// ═══════════════════════════════════════════════════════════

describe('extractLedgerRows', () => {
  it('订单卡片 → 明细行带状态/金额/客户/详情跳转', () => {
    const msg = orderQuerySuccess('A001', 'shipped', 2340, '张三')
    const rows = extractLedgerRows([msg])
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({
      type: 'order',
      label: '订单 A001',
      status: 'shipped',
      amount: 2340,
      customer: '张三',
      href: `/orders/o-A001`,
      followUp: '查看订单 A001',
    })
  })

  it('订单卡片列表（orders: [...]）→ 每单一行', () => {
    const msg = assistantMsg({
      cards: [
        {
          type: 'order',
          data: {
            orders: [
              { id: 'o1', orderNo: 'A001', status: 'pending', totalAmount: 168, customerName: '张三' },
              { id: 'o2', orderNo: 'A002', status: 'shipped', totalAmount: 2340, customerName: '李四' },
            ],
          },
        },
      ],
    })
    const rows = extractLedgerRows([msg])
    expect(rows).toHaveLength(2)
    expect(rows.map(r => r.label)).toEqual(['订单 A001', '订单 A002'])
  })

  it('无卡片但有工具入参 → 兜底明细行（无状态/金额/跳转）', () => {
    const msg = assistantMsg({
      tool_calls: [{ name: 'order_query', input: { order_no: 'B001' }, status: 'completed', result: { success: true } }],
    })
    const rows = extractLedgerRows([msg])
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ type: 'order', label: '订单 B001', followUp: '查看订单 B001' })
    expect(rows[0].status).toBeUndefined()
    expect(rows[0].href).toBeUndefined()
  })

  it('卡片与入参同一订单 → 跨来源去重为一行', () => {
    const messages = [
      orderQuerySuccess('A001', 'shipped', 2340, '张三'),
      assistantMsg({
        tool_calls: [{ name: 'order_query', input: { order_no: 'A001' }, status: 'completed', result: { success: true } }],
      }),
    ]
    const rows = extractLedgerRows(messages)
    expect(rows).toHaveLength(1)
  })

  it('物流卡片 → 明细行带物流状态', () => {
    const msg = assistantMsg({
      tool_calls: [{ name: 'logistics_track', input: { tracking_no: 'SF123' }, status: 'completed', result: { success: true } }],
      cards: [
        { type: 'logistics', data: { trackingNo: 'SF123', company: '顺丰', status: '运输中', tracks: [] } },
      ],
    })
    const rows = extractLedgerRows([msg])
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({
      type: 'logistics',
      label: '物流 SF123',
      status: '运输中',
      followUp: '查询物流 SF123',
    })
  })
})

// ═══════════════════════════════════════════════════════════
// collectSuggestions — 接下来可以问
// ═══════════════════════════════════════════════════════════

describe('collectSuggestions', () => {
  it('取最近一条 assistant 消息的后续建议', () => {
    const messages = [
      assistantMsg({ suggestions: ['查看该订单物流', '查看客户历史订单'] }),
      assistantMsg({ suggestions: ['确认订单信息', '打印发货单'] }),
    ]
    expect(collectSuggestions(messages)).toEqual(['确认订单信息', '打印发货单'])
  })

  it('无建议 → 空数组', () => {
    expect(collectSuggestions([assistantMsg({ content: '你好' })])).toEqual([])
  })
})