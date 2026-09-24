// case_ids: CH-021
/**
 * 同页填充的**端到端前端接线**（issue #5368 包 2）：SSE `page_fill` 事件 → store → 页面订阅者。
 *
 * 为什么必须有这条：`store/chat.ts` 的 SSE `switch` 里少一个 `case` ⇒ 后端推得再对，
 * **页面永远收不到**（表单不填、且没有任何东西会变红 —— 构建绿、单测绿、类型绿）。
 * 本用例用真实 SSE 帧驱动 store（与 `interactive-contract.test.ts` 同一套驱动方式），
 * 断言订阅者**真的**拿到了计划，且事件**没有**被写进任何 message 状态
 * （它不是聊天消息的一部分：刷新即消失，不落盘）。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act } from '@testing-library/react'

const mockAuthGetState = vi.fn()

vi.mock('@/store/auth', () => ({
  useAuthStore: {
    getState: () => mockAuthGetState(),
  },
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn(), loading: vi.fn(), dismiss: vi.fn() },
}))

vi.mock('@/lib/api', () => ({
  chatApi: {
    AI_SERVICE_URL: 'http://localhost:8001',
    getSessions: vi.fn(),
    getHistory: vi.fn(),
  },
}))

import { useChatStore } from '@/store/chat'
import { subscribePageFill } from '@/lib/agent-page-fill'

const PLAN = {
  component: 'page_fill',
  target_type: 'product',
  fields: [
    { key: 'name', label: '商品名称', value: '雪尼尔遮光窗帘', source: '[图片识别]',
      reason: null, candidates: [], note: null, note_source: null },
    { key: 'color', label: '颜色', value: null, source: null,
      reason: '店铺目录里没有「雾霾蓝」⇒ 宁可不填', candidates: [{ value: '藏青', reason: '最接近' }],
      note: null, note_source: null },
  ],
}

async function drivePageFillEvent(payload: unknown) {
  const mockRead = vi.fn()
    .mockResolvedValueOnce({
      done: false,
      value: new TextEncoder().encode(
        'event: page_fill\ndata: ' + JSON.stringify(payload) + '\n\n',
      ),
    })
    .mockResolvedValueOnce({ done: true, value: undefined })

  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    body: { getReader: () => ({ read: mockRead, cancel: vi.fn(), releaseLock: vi.fn() }) },
  })

  await act(async () => {
    await useChatStore.getState().sendMessage('照这张图建个商品')
  })
}

describe('SSE page_fill → store → 页面订阅者（同页填充端到端）', () => {
  let received: unknown[] = []
  let off: () => void = () => {}

  beforeEach(() => {
    vi.clearAllMocks()
    received = []
    mockAuthGetState.mockReturnValue({ accessToken: 'fake-token', user: null })
    useChatStore.setState({
      sessions: [],
      currentSessionId: 'sess1',
      messages: [],
      isStreaming: false,
      abortController: null,
      choiceSelections: {},
    })
    off = subscribePageFill('product', (plan) => received.push(plan))
  })

  afterEach(() => off())

  it('计划原样送达页面订阅者（值 + 候选 + 来源都不丢）', async () => {
    await drivePageFillEvent(PLAN)
    expect(received).toHaveLength(1)
    const plan = received[0] as typeof PLAN
    expect(plan.target_type).toBe('product')
    expect(plan.fields.map((f) => f.key)).toEqual(['name', 'color'])
    expect(plan.fields[0].source).toBe('[图片识别]')
    expect(plan.fields[1].candidates).toEqual([{ value: '藏青', reason: '最接近' }])
  })

  it('计划不进任何 message 状态（瞬时通道：刷新即消失，不落盘）', async () => {
    await drivePageFillEvent(PLAN)
    const messages = useChatStore.getState().messages
    const serialized = JSON.stringify(messages)
    expect(serialized).not.toContain('雾霾蓝')
    expect(serialized).not.toContain('page_fill')
  })
})