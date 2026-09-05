/**
 * 交互组件契约 — 后端 SSE interactive payload 经前端 store 透传字段不丢
 * case_ids: PP-001, PR-010, OR-001
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
    }
    const interactive = await parseInteractive(payload)
    expect(interactive?.component).toBe('choice')
    expect(interactive?.title).toBe(payload.title)
    expect(interactive?.options).toEqual(payload.options)
    expect(interactive?.pageMeta).toEqual(payload.pageMeta)
    expect(interactive?.multiSelect).toBe(true)
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