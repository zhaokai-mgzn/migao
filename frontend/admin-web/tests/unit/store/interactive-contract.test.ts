/**
 * 交互组件契约 — 后端 SSE interactive payload 经前端 store 透传字段不丢
 * case_ids: PP-001, PR-010, OR-001, UI-031
 *
 * 背景（sess_fba38395ed094a9d 系列，issue #2892/#2894/#2896）：
 * - 后端 interact 工具 → SSE interactive payload 字段由
 *   backend/ai-agent-service/tests/test_interact_payload_contract.py 锁定白名单；
 * - 本测试用「等价于后端 interact 输出的完整 payload」走前端 store 的 SSE 解析，
 *   断言 messages[].interactive 全字段保留 —— 防 store 漏透传导致渲染丢失
 *   （回归：pageMeta 曾不被 store 持久化，翻页控件永不渲染）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
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

// chatApi mock：仅 AI_SERVICE_URL 被 sendMessage 使用
vi.mock('@/lib/api', () => ({
  chatApi: {
    AI_SERVICE_URL: 'http://localhost:8001',
    getSessions: vi.fn(),
    getHistory: vi.fn(),
  },
}))

import { useChatStore } from '@/store/chat'
import { chatApi } from '@/lib/api'

/** 构造一次 SSE interactive 事件并驱动 store 解析，返回 messages 里最后的 interactive */
async function parseInteractive(payload: Record<string, unknown>) {
  const mockRead = vi.fn()
    .mockResolvedValueOnce({
      done: false,
      value: new TextEncoder().encode(
        'event: interactive\ndata: ' + JSON.stringify({
          type: payload.component, // SSE 事件 type = 组件类型（与后端 SSEEvent.interactive 一致）
          ...payload,
        }) + '\n\n',
      ),
    })
    .mockResolvedValueOnce({ done: true, value: undefined })

  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    body: { getReader: () => ({ read: mockRead, cancel: vi.fn(), releaseLock: vi.fn() }) },
  })

  await act(async () => {
    await useChatStore.getState().sendMessage('触发交互组件')
  })
  const msgs = useChatStore.getState().messages
  return msgs[msgs.length - 1]?.interactive
}

describe('interactive component contract (后端 SSE payload ↔ 前端 store 透传)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockAuthGetState.mockReturnValue({ accessToken: 'fake-token', user: null })
    useChatStore.setState({
      sessions: [],
      currentSessionId: 'sess1',
      messages: [],
      isStreaming: false,
      abortController: null,
      choiceSelections: {},
    })
  })

  it('choice 完整 payload（含 pageMeta/multiSelect）经 store 透传后字段不丢', async () => {
    const payload = {
      component: 'choice',
      title: '请选择加工项（可多选）',
      options: [
        { label: '1. 打孔加工 ¥8/米', value: 'pi_hole' },
        { label: '2. 韩式折边 ¥12/米', value: 'pi_pleat' },
      ],
      pageMeta: { current: 1, total: 2, totalCount: 16, tool: 'processing_item_query', params: '{"page":1,"size":10}' },
      multiSelect: true,
      multiSelectSubmitPrefix: '已选加工项：',
      multiSelectSubmitLabel: '完成选择',
      multiSelectSkipLabel: '不需要加工项',
    }
    const interactive = await parseInteractive(payload)
    expect(interactive?.component).toBe('choice')
    expect(interactive?.title).toBe(payload.title)
    expect(interactive?.options).toEqual(payload.options)
    expect(interactive?.pageMeta).toEqual(payload.pageMeta)
    expect(interactive?.multiSelect).toBe(true)
    // #3032：多选提交文案字段透传（色号/规格卡不再硬编码加工项语义）
    expect(interactive?.multiSelectSubmitPrefix).toBe('已选加工项：')
    expect(interactive?.multiSelectSubmitLabel).toBe('完成选择')
    expect(interactive?.multiSelectSkipLabel).toBe('不需要加工项')
  })

  it('confirm payload 全字段透传（confirmValue 携带上下文路由）', async () => {
    const payload = {
      component: 'confirm',
      title: '确认创建商品？',
      fields: [{ label: '商品名称', value: '遮光窗帘' }],
      confirmLabel: '确认创建',
      confirmValue: '确认创建商品遮光窗帘',
      cancelLabel: '再想想',
      cancelValue: '取消创建',
    }
    const interactive = await parseInteractive(payload)
    expect(interactive?.confirmLabel).toBe('确认创建')
    expect(interactive?.confirmValue).toBe('确认创建商品遮光窗帘')
    expect(interactive?.cancelValue).toBe('取消创建')
  })

  it('form payload 全字段透传', async () => {
    const payload = {
      component: 'form',
      title: '新建商品 — 识别结果已预填',
      formFields: [{ key: 'name', label: '商品名称', value: '雪尼尔窗帘' }],
      submitLabel: '提交并确认',
    }
    const interactive = await parseInteractive(payload)
    expect(interactive?.submitLabel).toBe('提交并确认')
    expect(interactive?.formFields?.[0]?.key).toBe('name')
  })
})

// ═══════════════════════════════════════════════════
// selectSession 历史回放透传（issue #3036 / UI-031）
// ═══════════════════════════════════════════════════

describe('selectSession 历史回放 interactive 透传', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockAuthGetState.mockReturnValue({ accessToken: 'fake-token', user: null })
    useChatStore.setState({
      sessions: [],
      currentSessionId: null,
      messages: [],
      isStreaming: false,
      abortController: null,
      choiceSelections: {},
    })
  })

  async function loadHistoryWith(historyMessages: any[]) {
    (chatApi.getHistory as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { messages: historyMessages },
    })
    await act(async () => {
      await useChatStore.getState().selectSession('sess1')
    })
  }

  it('历史消息的 interactive + interactive_answered 原样透传（已答卡片回放后仍只读）', async () => {
    const interactive = {
      component: 'confirm',
      title: '确认创建订单',
      fields: [{ label: '商品', value: '窗帘-001' }],
    }
    await loadHistoryWith([
      {
        id: 'm-user', session_id: 'sess1', role: 'user', content: '确认',
        content_type: 'text', created_at: '2026-06-20T10:00:00Z',
      },
      {
        id: 'm-ai', session_id: 'sess1', role: 'assistant', content: '请确认订单信息',
        content_type: 'text', created_at: '2026-06-20T10:00:01Z',
        interactive,
        interactive_answered: true,
      },
    ])

    const msgs = useChatStore.getState().messages
    const aiMsg = msgs.find(m => m.id === 'm-ai')
    expect(aiMsg?.interactive).toEqual(interactive)
    expect(aiMsg?.interactiveAnswered).toBe(true)
  })

  it('未答交互（interactive_answered=false）历史回放后仍保持可交互状态', async () => {
    const interactive = {
      component: 'choice',
      title: '请选择加工项',
      options: [{ label: '打孔加工', value: 'pi_hole' }],
    }
    await loadHistoryWith([
      {
        id: 'm-ai', session_id: 'sess1', role: 'assistant', content: '请选择加工项',
        content_type: 'text', created_at: '2026-06-20T10:00:00Z',
        interactive,
        interactive_answered: false,
      },
    ])

    const msgs = useChatStore.getState().messages
    const aiMsg = msgs.find(m => m.id === 'm-ai')
    expect(aiMsg?.interactive).toEqual(interactive)
    expect(aiMsg?.interactiveAnswered).toBe(false)
  })
})