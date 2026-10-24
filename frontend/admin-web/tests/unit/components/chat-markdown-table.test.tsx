// case_ids: UI-126
/**
 * PC（admin-web）聊天气泡的 **GFM 表格**渲染 —— issue #7235 / 用例 UI-126
 *
 * ## 为什么要有这条（同族核查）
 *
 * 用户 2026-10-18 报的是**手机端**表格裸 markdown；PC 侧走 `react-markdown` + `remark-gfm`，
 * GFM 表格**应当**本来就渲染成 `<table>` —— 但**没有任何判据**把守（UI-084 只覆盖软换行/粗体），
 * 而 #6346 挂上的 `remark-breaks` 恰恰会改写换行语义（表格是「换行敏感」的块级结构）。
 * 本文件把「PC 真的渲染成表格」变成常驻回归判据：以后谁改插件组合 / 清洗逻辑把它弄坏，这里当场红。
 *
 * ## 判据（逐条能红）
 *
 * ① 标准 GFM 表格 ⇒ `<table>` 1 个、`<th>` 3 个、`<td>` 6 个，**DOM 文本零字面 `|`**；
 * ② `remark-breaks` 在场时表格仍成表（不是被折成 `<br>` 连起来的裸文本）；
 * ③ 表格前后段落仍是 `<p>`（块级语义不串）；
 * ④ 负控：普通句子里的 `|`（`a | b`）不渲染成表格；
 * ⑤ 对齐标记不报错且列数不错位。
 *
 * 红证（判别力自证）：把 `remarkPlugins` 里的 `remarkGfm` 摘掉再跑 ⇒ 判据 ①（`<table>` 零命中）
 * 与 ⑤ 当场红（可复制命令写 PR body）。
 *
 * 本文件**不 mock react-markdown / remark 插件**（判据必须打在真实渲染管线上）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import type { ChatMessage } from '@/types'

const mockChatStore = {
  messages: [] as ChatMessage[],
  currentSessionId: 's1' as string | null,
  isLoadingMessages: false,
  isStreaming: false,
  sessions: [{ id: 's1' }] as Array<{ id: string }>,
}

vi.mock('@/store/chat', () => ({
  useChatStore: (selector?: (state: typeof mockChatStore) => unknown) =>
    typeof selector === 'function' ? selector(mockChatStore) : mockChatStore,
}))

vi.mock('@/store/auth', () => ({
  useAuthStore: { getState: () => ({ accessToken: 'test-token' }) },
}))

vi.mock('@/lib/api', () => ({
  chatApi: {
    AI_SERVICE_URL: 'http://localhost:8001',
    getSessions: vi.fn(),
    createSession: vi.fn(),
    getHistory: vi.fn(),
  },
}))

vi.mock('@/lib/utils', () => ({
  cn: (...args: Array<string | undefined | false | null>) => args.filter(Boolean).join(' '),
}))

vi.mock('@/hooks/use-typewriter', () => ({
  TYPEWRITER_INTERVAL_MS: 20,
  useTypewriter: (text: string) => text,
}))

vi.mock('@/components/chat/InteractiveMessage', () => ({ default: () => null }))
vi.mock('@/components/chat/WelcomePanel', () => ({ default: () => null }))
vi.mock('@/components/chat/ToolResultCard', () => ({ default: () => null }))

import MessageList from '@/components/chat/MessageList'

function aiMsg(content: string): ChatMessage {
  return {
    id: 'ai-table-1',
    role: 'assistant',
    content,
    isStreaming: false,
    created_at: '2026-10-18T08:45:00+08:00',
  }
}

beforeEach(() => {
  mockChatStore.messages = []
  mockChatStore.currentSessionId = 's1'
  mockChatStore.isLoadingMessages = false
})

const TABLE = [
  '最近的售后工单：',
  '',
  '| 工单号 | 客户 | 状态 |',
  '| --- | --- | --- |',
  '| AS-20261018-0005 | 回归客户-O5 | 🟡 待处理 |',
  '| AS-20261018-0004 | 回归客户-O1 | 🟡 待处理 |',
].join('\n')

describe('MessageList — UI-126 PC 表格渲染', () => {
  it('① 标准 GFM 表格渲染成 <table>，DOM 文本零字面管道符', () => {
    mockChatStore.messages = [aiMsg(TABLE)]
    const view = render(<MessageList />)
    expect(view.container.querySelectorAll('table')).toHaveLength(1)
    expect(view.container.querySelectorAll('th')).toHaveLength(3)
    expect(view.container.querySelectorAll('td')).toHaveLength(6)
    expect(view.container.textContent).not.toContain('|')
    expect(view.container.textContent).not.toContain('---')
    view.unmount()
  })

  it('② remark-breaks 在场时表格仍成表（不被折成 <br> 裸文本）', () => {
    mockChatStore.messages = [aiMsg(TABLE)]
    const view = render(<MessageList />)
    const table = view.container.querySelector('table')
    expect(view.container.querySelectorAll('table')).toHaveLength(1)
    expect(table?.querySelectorAll('tr')).toHaveLength(3)
    // 表格行不靠 <br> 硬折：表格容器内不得出现换行插件产生的 <br>
    expect(table?.querySelectorAll('br')).toHaveLength(0)
    view.unmount()
  })

  it('③ 表格前后段落仍是 <p>（块级语义不串）', () => {
    mockChatStore.messages = [aiMsg(`${TABLE}\n\n共 2 条。`)]
    const view = render(<MessageList />)
    const paragraphs = Array.from(view.container.querySelectorAll('p')).map((p) => p.textContent)
    expect(paragraphs).toContain('最近的售后工单：')
    expect(paragraphs).toContain('共 2 条。')
    view.unmount()
  })

  it('④ 负控：普通句子里的 | 不是表格', () => {
    mockChatStore.messages = [aiMsg('尺码 a | b 都可以')]
    const view = render(<MessageList />)
    expect(view.container.querySelector('table')).toBeNull()
    expect(view.container.textContent).toContain('a | b')
    view.unmount()
  })

  it('⑤ 对齐标记不报错，列数不错位', () => {
    const md = ['| 左 | 中 | 右 |', '| :-- | :-: | --: |', '| 1 | 2 | 3 |'].join('\n')
    mockChatStore.messages = [aiMsg(md)]
    const view = render(<MessageList />)
    expect(view.container.querySelectorAll('th')).toHaveLength(3)
    expect(view.container.querySelectorAll('td')).toHaveLength(3)
    const aligned = view.container.querySelectorAll('th[style*="text-align"]')
    expect(aligned).toHaveLength(3)
    view.unmount()
  })
})
