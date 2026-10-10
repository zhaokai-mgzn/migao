// case_ids: DA-004, UI-006
/**
 * 「**读面失败不得印派生零值**」——`/agent-workspace/sessions` **实例判据**（issue #6721）。
 *
 * ## 病灶（读 `git show origin/main:<path>` 核过）
 *
 * 顶部监控统计条自述「活跃 / 已结束 / **总会话数**（从 `store.sessions` 派生）」
 * （`frontend/admin-web/src/app/(dashboard)/agent-workspace/sessions/page.tsx`）。而
 * `fetchSessions` 失败时**不置任何失败读数**、`sessions` 保持 `[]` ⇒ 统计条**断言「总会话数 = 0」**。
 * 这是「**读不到被画成"就是 0"**」同族的第三处承载体：#6691（读面故障不得画成空态）⇒
 * #6703（读失败不得印派生零值）⇒ **本单**（统计条这一格）。
 *
 * ## 本文件钉住的四件事
 *
 *   ① 读面失败 ⇒ 统计条**不印派生 0**（0 换 `—`，且 `role="alert"` 给读屏器一个异常读法）；
 *   ② 读面失败 ⇒ 出现**常驻**失败面 + 重试出口（`agent-sessions-load-failed` / `-retry`）；
 *   ③ 点重试 ⇒ **真再发一次** `fetchSessions`，成功后统计条恢复**真实计数**（不是「锚点消失」）；
 *   ④ **反向对照**：读成功且**真为 0**（或真只有 0 个活跃）⇒ **照旧印 0**（真值 0 不许被判红）。
 *
 * ## 反假绿约束（`migao-acceptance`）
 *
 * - 失败一律来自 **store 的 `sessionsLoadFailed` 置位**（不依赖真实服务不可达）；
 * - ① 的判别力来自「`sessions` 为空 + `sessionsLoadFailed`」这个**改前必现**的组合
 *   （改前 `page.tsx` 在同样状态下渲染的就是 `共 0`，见 PR body 的红证读数）；
 * - ③ 钉住 `fetchSessions` 的**调用次数**与恢复后的**真值 3**，不是「锚点消失了」这类改前改后都绿的断言。
 *
 * ## 边界（照实登记）
 *
 * - 本文件只覆盖本页的**统计条**；列表体自身的失败面在
 *   `src/components/chat/SessionList.tsx`（#6713 的面，`chat-sessions-load-failed`），
 *   本页**不重复**那一处失败面文案（§31 P2 信息不重复）：本页的常驻失败面解释的是
 *   「**顶部这几格**为什么不可信」，截图与判据各判各的；
 * - 判不了「失败面渲染得够不够显眼」（那是 §15.7 读图的面）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

/** 可变的 mock store 状态（`sessionsLoadFailed` 由各用例置位，模拟 store 的失败读数） */
const storeState = vi.hoisted(() => ({
  sessions: [] as Array<Record<string, string>>,
  sessionsLoadFailed: false,
  fetchSessions: vi.fn(),
}))

vi.mock('@/store/chat', () => ({
  useChatStore: () => ({
    sessions: storeState.sessions,
    sessionsLoadFailed: storeState.sessionsLoadFailed,
    fetchSessions: storeState.fetchSessions,
    currentSessionId: null,
    messages: [],
    isStreaming: false,
    isLoadingSessions: false,
    isLoadingMessages: false,
    searchKeyword: '',
    quickActions: [],
    isLoadingQuickActions: false,
    createSession: vi.fn(),
    selectSession: vi.fn(),
    sendMessage: vi.fn(),
    closeSession: vi.fn(),
    reopenSession: vi.fn(),
    setSearchKeyword: vi.fn(),
    stopStreaming: vi.fn(),
    clearCurrentSession: vi.fn(),
    fetchQuickActions: vi.fn(),
  }),
}))

vi.mock('@/components/chat/SessionList', () => ({
  default: () => <div data-testid="session-list">SessionList</div>,
}))
vi.mock('@/components/chat/ChatArea', () => ({
  default: () => <div data-testid="chat-area">ChatArea</div>,
}))

import AgentSessionsPage from '@/app/(dashboard)/agent-workspace/sessions/page'

const SESSION = (id: string, status: string) => ({
  session_id: id,
  title: `会话${id}`,
  status,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
})

/** 三个会话（2 活跃 + 1 已结束）—— 统计条的真实读数 = `活跃 2 / 已结束 1 / 共 3` */
const REAL_SESSIONS = [SESSION('s1', 'active'), SESSION('s2', 'active'), SESSION('s3', 'closed')]

/** 统计条读数（读屏面上的值；`—` 表示「不可信」） */
function statsText(): string {
  return screen.getByTestId('session-stats-bar').textContent ?? ''
}

describe('AgentSessionsPage — 读面失败不印派生零值（issue #6721）', () => {
  beforeEach(() => {
    storeState.sessions = []
    storeState.sessionsLoadFailed = false
    storeState.fetchSessions = vi.fn().mockResolvedValue(undefined)
  })

  it('① 读会话列表失败 ⇒ 顶部统计条不印派生 0（0 换「—」）', () => {
    storeState.sessionsLoadFailed = true
    render(<AgentSessionsPage />)
    // 改前形态：`sessions = []` ⇒ 三格都印 0 ⇒ 屏上逐字 `0活跃0已结束0共`（事实性断言，而真相是读不到）
    expect(statsText(), '读失败时统计条三格都不得断言 0').not.toMatch(/0活跃|0已结束|0共/)
    expect(statsText(), '三个派生值都必须换成「—」（不可信读数）').toMatch(/—活跃—已结束—共/)
    // 且统计条整体带 `role="alert"`：不印 ≠ 不告知 —— 读屏器仍要读到一个异常
    expect(screen.getByTestId('session-stats-bar')).toHaveAttribute('role', 'alert')
  })

  it('② 读会话列表失败 ⇒ 常驻失败面 + 重试出口', () => {
    storeState.sessionsLoadFailed = true
    render(<AgentSessionsPage />)
    const banner = screen.getByTestId('agent-sessions-load-failed')
    expect(banner).toBeInTheDocument()
    expect(banner).toHaveAttribute('role', 'alert')
    expect(screen.getByTestId('agent-sessions-load-failed-retry')).toBeInTheDocument()
  })

  it('③ 点重试 ⇒ 真再发一次请求，且统计条恢复真实计数 2 / 1 / 3', async () => {
    const user = userEvent.setup()
    storeState.sessionsLoadFailed = true
    // 第 1 次调用 = 页面挂载那一次的**失败**读（store 转为「失败」读数：保留上次成功值 / 空列表）；
    // 第 2 次 = 点「重新加载」这一次 —— 成功落真实列表。⇒ 重试用例与页面的挂载读**共存**，不改页面契约。
    storeState.fetchSessions = vi.fn().mockImplementation(async () => {
      if (storeState.fetchSessions.mock.calls.length === 1) {
        storeState.sessions = []
        storeState.sessionsLoadFailed = true
      } else {
        storeState.sessions = REAL_SESSIONS
        storeState.sessionsLoadFailed = false
      }
    })
    render(<AgentSessionsPage />)

    const callsBefore = storeState.fetchSessions.mock.calls.length
    await user.click(screen.getByTestId('agent-sessions-load-failed-retry'))

    await waitFor(() => {
      expect(storeState.fetchSessions.mock.calls.length).toBe(callsBefore + 1)
      expect(statsText()).toContain('共')
      expect(statsText()).toContain('3')
    })
    expect(statsText(), '失败读数恢复后不得再留「—」').not.toContain('—')
    expect(screen.queryByTestId('agent-sessions-load-failed')).toBeNull()
  })

  it('④ 反向对照：读成功且真为 0 ⇒ 照旧印 0（真值 0 不许被判红）', () => {
    storeState.sessions = []
    storeState.sessionsLoadFailed = false
    render(<AgentSessionsPage />)
    expect(statsText(), '真为 0 时照旧印 0').toContain('共')
    expect(statsText()).toContain('0')
    expect(statsText(), '读成功时不得出现「—」').not.toContain('—')
    expect(screen.queryByTestId('agent-sessions-load-failed')).toBeNull()
  })

  it('④b 反向对照：读成功且真只有 0 个活跃 ⇒ 活跃印 0、「共」印真总数', () => {
    storeState.sessions = [SESSION('s9', 'closed')]
    render(<AgentSessionsPage />)
    expect(statsText()).toContain('活跃')
    expect(statsText()).toContain('1')
    expect(statsText(), '读成功时不得出现「—」').not.toContain('—')
  })
})
