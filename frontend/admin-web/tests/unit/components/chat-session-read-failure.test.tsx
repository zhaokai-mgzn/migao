// case_ids: UI-011, CH-028
/**
 * 「**读面失败不得与空态同屏**」——**实例判据**（issue #6713）。
 *
 * ## 病灶（真机实测，main `2adad8660`）
 *
 * 注入「所有 admin 读接口 500」后打开 `/chat`，**6 秒后**（避开拦截器 toast 的 ≈4s 存活窗口）：
 *
 * ```
 * 屏上文本: 暂无会话 | 选择或创建一个对话 | …
 * 像空态 = true ｜ 像失败 = false ｜ 相关锚点 = 无（0 个）
 * ```
 *
 * 即：**读面故障被渲染成「真的没有会话」**——`store/chat.ts` 的 `fetchSessions` 失败分支只
 * `console.error`（#6664 删掉的那个 `error` 字段是「全仓无消费点」的假承诺，删对了，
 * 但**没有补上真出口**），而 `SessionList.tsx` 把「列表为空」直接画成「暂无会话」。
 *
 * ## 本文件钉住的四件事（每条红在**自己那条断言**上）
 *
 *   ① 注入「读会话列表失败」⇒ 屏上**不得**出现「暂无会话」（失败不是空）；
 *   ② ⇒ 必须出现**常驻**失败面（`data-testid="chat-sessions-load-failed"`，`role="alert"`）；
 *   ③ ⇒ 点重试**真重发**（调用次数 +1）且恢复真实列表（不是只把文案抹掉）；
 *   ④ **反向对照**：读成功且**真为空** ⇒ 「暂无会话」照旧（不得把空态一并判红）。
 *
 * ## 反假绿约束（`migao-acceptance`）
 *
 * - 失败一律来自 **mock 接口 reject**（不依赖真实服务不可达）；
 * - ① 的判别力来自「失败后 `sessions` 仍为 `[]` ⇒ 三层三元落到空态那一支」这个**改前必现**的组合
 *   （改前读数见 PR body）；
 * - ③ 钉住**调用次数**与**恢复后的真值**（不是「锚点消失了」这类改前改后都绿的断言）；
 * - 本文件走**真 store**（`useChatStore` + 真 `fetchSessions`），只 mock `chatApi.getSessions`
 *   ⇒ 「UI 读的失败读数」与「store 写的失败读数」**同一个真值**，不是两份 mock 各说各话。
 *
 * ## 边界（照实登记）
 *
 * - 只覆盖 `/chat` 与 `/agent-workspace/sessions` **共用的组件链**
 *   （`SessionList` + `store/chat.ts`）——两页共用同一个 `fetchSessions`，修组件 = 两页同时修好；
 * - `/agent-workspace/sessions` 顶部**统计条**（活跃 / 已结束 / 共 N）在失败时印的是**派生自
 *   `sessions` 的 0**，形态与计数行同族但**不在本单**（issue #6713 = `/chat` 列表体；
 *   那边若判定要修，走 `count-row-derived-scan.mjs` 那把尺子）—— 如实登记，不假装覆盖；
 * - **不测真机**：屏上「失败面够不够显眼 / 够不够常驻」是 §15.7 真机读图的面，见 PR 报告。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// ── 只 mock 读接口本身（store / 组件走真代码，见文件头「反假绿约束」）──
const { mockGetSessions } = vi.hoisted(() => ({ mockGetSessions: vi.fn() }))

vi.mock('@/lib/api', () => ({
  chatApi: {
    getSessions: (...args: unknown[]) => mockGetSessions(...args),
    createSession: vi.fn(),
    getHistory: vi.fn().mockResolvedValue({ data: { messages: [] } }),
    closeSession: vi.fn(),
    reopenSession: vi.fn(),
  },
}))

vi.mock('@/store/auth', () => ({
  useAuthStore: { getState: () => ({ accessToken: 'test-token' }) },
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn(), loading: vi.fn(), dismiss: vi.fn() },
}))

import SessionList from '@/components/chat/SessionList'
import { useChatStore } from '@/store/chat'

const TEST_TIMEOUT = 20_000

/** 服务端 `/api/chat/sessions` 的成功载荷（`data.items` 形态，见 store 的映射） */
const SESSIONS_PAYLOAD = {
  data: {
    items: [
      { id: 's1', title: '会话一', status: 'active', updated_at: '2026-10-10T10:00:00Z' },
      { id: 's2', title: '会话二', status: 'active', updated_at: '2026-10-10T09:00:00Z' },
    ],
  },
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  // 每例都从「没有会话」的初值起（失败态与空态的分歧就从这里来）
  useChatStore.setState({
    sessions: [],
    currentSessionId: null,
    messageStore: {},
    streams: {},
    isLoadingSessions: false,
  })
})

/**
 * 页面的真实接线 = 进页即拉会话列表（`/chat/page.tsx` 与
 * `/agent-workspace/sessions/page.tsx` 都这么写，`fetchSessions` **不由列表组件自己发起**）。
 * ⇒ 本文件先 `render` 再把**这一次真实的进页拉取**驱动起来，断言都落在它跑完之后。
 */
async function enterPageAndFetch() {
  render(<SessionList />)
  await act(async () => {
    await useChatStore.getState().fetchSessions()
  })
}

describe('读面失败不得与空态同屏（issue #6713）', () => {
  it(
    '① 读会话列表失败 ⇒ 屏上不得出现「暂无会话」（失败不是空）',
    async () => {
      mockGetSessions.mockRejectedValue(new Error('获取会话列表失败: 500'))
      await enterPageAndFetch()

      expect(mockGetSessions).toHaveBeenCalledTimes(1)
      // 失败分支真的跑完了（isLoadingSessions 落回 false）⇒ 屏上这一段确实是**终态**，不是「还在转圈」
      expect(useChatStore.getState().isLoadingSessions).toBe(false)

      // 🔴 改前：`sessions === []` ⇒ 三层三元落到空态那一支 ⇒ 这行**当场红**
      expect(screen.queryByText('暂无会话')).not.toBeInTheDocument()
    },
    TEST_TIMEOUT,
  )

  it(
    '② 读会话列表失败 ⇒ 必须出现常驻失败面（role=alert，与 toast 的 4s 存活无关）',
    async () => {
      mockGetSessions.mockRejectedValue(new Error('获取会话列表失败: 500'))
      await enterPageAndFetch()

      const anchor = screen.getByTestId('chat-sessions-load-failed')
      expect(anchor).toBeInTheDocument()
      expect(anchor).toHaveAttribute('role', 'alert')
      // 失败话术说「读不到」，不是「没有」（不得归因成权限 / 不得伪装成空）
      expect(anchor.textContent).toContain('读取失败')
      expect(anchor.textContent).not.toContain('暂无')
      expect(useChatStore.getState().isLoadingSessions).toBe(false)
    },
    TEST_TIMEOUT,
  )

  it(
    '③ 点重试 ⇒ 真重发（调用次数 +1）且恢复真实列表',
    async () => {
      mockGetSessions.mockRejectedValueOnce(new Error('获取会话列表失败: 500'))
      mockGetSessions.mockResolvedValueOnce(SESSIONS_PAYLOAD)
      await enterPageAndFetch()

      const retry = screen.getByTestId('chat-sessions-load-failed-retry')
      expect(mockGetSessions).toHaveBeenCalledTimes(1)

      await userEvent.click(retry)

      await waitFor(() => expect(mockGetSessions).toHaveBeenCalledTimes(2))
      expect(await screen.findByText('会话一')).toBeInTheDocument()
      expect(screen.queryByTestId('chat-sessions-load-failed')).not.toBeInTheDocument()
      expect(screen.queryByText('暂无会话')).not.toBeInTheDocument()

      // 「真重发」的反向对照：改前那种「只把文案抹掉」的写法会让调用次数停在 1
      expect(mockGetSessions).toHaveBeenCalledTimes(2)
    },
    TEST_TIMEOUT,
  )

  it(
    '④ 反向对照：读成功且**真为空** ⇒ 「暂无会话」照旧（空态没有被判红）',
    async () => {
      mockGetSessions.mockResolvedValue({ data: { items: [] } })
      await enterPageAndFetch()

      expect(screen.getByText('暂无会话')).toBeInTheDocument()
      expect(screen.queryByTestId('chat-sessions-load-failed')).not.toBeInTheDocument()
    },
    TEST_TIMEOUT,
  )
})
