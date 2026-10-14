// case_ids: UI-098
/**
 * 黄金策对话正文的强调渲染（issue #6910，用户 2026-10-14 实测截图）—— **真 markdown 管线面**。
 *
 * ## 为什么这一层不能用替身
 *
 * 缺陷本身发生在 CommonMark 的解析里（flanking 规则 × 中文标点），**不是**本仓自己的正则 ——
 * 所以这里**不 mock `react-markdown` / `remark-gfm` / `remark-breaks`**（既有 MessageList 测试
 * 都把 react-markdown 换成 `<span>` ⇒ 那条替身永远看不见真解析结果）。判据是**两条同时**成立：
 * ① 屏幕上**不再出现** `**`；② 该加粗的地方**真的有** `<strong>`（只判 ① 的话，把标记删掉也能绿 = 空判据）。
 *
 * ## 红证（修前实测）
 *
 * 把 `MessageList` 的 `normalizeCjkEmphasis(visibleContent)` 换回 `visibleContent`：
 * 本文件「截图原句 / 整条回复 / 闭合侧 / 代码面」四条当场红（本机实测 **7 failed | 2 passed**，
 * `**` 进了 textContent、`<strong>` 数为 0）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import type { ChatMessage } from '@/types'

const ZWSP = '\u200B'

/** 去掉零宽空格：断言一律对「商家真正看得见的字」下，ZWSP 只允许以「不可见」的方式存在 */
const strip = (text: string | null | undefined): string => (text ?? '').split(ZWSP).join('')

const mockChatStore = {
  messages: [] as ChatMessage[],
  currentSessionId: 's1' as string | null,
  isLoadingMessages: false,
  isStreaming: false,
  sessions: [] as Array<{ id: string }>,
}

vi.mock('@/store/chat', () => ({
  useChatStore: (selector?: (state: typeof mockChatStore) => unknown) =>
    typeof selector === 'function' ? selector(mockChatStore) : mockChatStore,
}))

vi.mock('@/components/chat/InteractiveMessage', () => ({ default: () => null }))
vi.mock('@/components/chat/WelcomePanel', () => ({ default: () => null }))
vi.mock('@/components/chat/ToolResultCard', () => ({ default: () => null }))

// 打字机在这里**不逐步**（组件级只关心 markdown 结果）：真实 hook 的 20ms 定时器会让
// `waitFor` 轮询被 React 更新饿死（同 MessageList-typewriter.test.tsx 的实测理由）；
// 于是本文件的断言全是**同步**的（内容首帧就在，不必等）。
vi.mock('@/hooks/use-typewriter', () => ({
  TYPEWRITER_INTERVAL_MS: 20,
  useTypewriter: (text: string) => text,
}))

import MessageList from '@/components/chat/MessageList'

/** 截图里那条回复的逐字原文（用户 2026-10-14 实测） */
const SCREENSHOT_REPLY = [
  '你是新同事呀，欢迎！这条给你说清楚 👇',
  '',
  '**下单（新建订单）不在我这边办理——黄金策在订单域只做查询和分析，代下单、改单、发货这些我都不做。**',
  '',
  '下单入口：后台的**「订单列表」页**，页面里的「新建订单」入口。订单在那里创建、也都是在那边推进状态（发货、确认收货等）。',
  '',
  '坦白说一句：我这边没有步骤级的操作指引（比如第几步填什么、按钮在哪），页面上的具体字串要以页面实际为准，我不瞎编。',
  '',
  '**我能帮上忙的部分**（你下单前可以先让我查，照着填就行）：',
  '• 查商品和规格价 → 商品名给我就行',
  '• 查客户档案（电话、地址）→ 姓名或手机号给我',
  '• 查实时库存 → 确认有没有货',
].join('\n')

function aiMsg(content: string): ChatMessage {
  return {
    id: 'ai-1',
    role: 'assistant',
    content,
    isStreaming: false,
    created_at: '2026-10-14T15:00:00+08:00',
  }
}

/**
 * 取 markdown 容器；不在就**具名抛错**（不是「弱断言」：`not.toBeNull()` 这类凑数断言会被
 * QA Growth Gate 判红 —— 本文件第一版就是这样被 CI 抓到的）。
 */
function markdownRoot(container: HTMLElement): HTMLElement {
  const el = container.querySelector('div.prose')
  if (!el) throw new Error('markdown 容器（div.prose）没渲染出来 —— 组件结构变了？')
  return el as HTMLElement
}

/**
 * 渲染一条 AI 回复。
 *
 * ⚠️ 取文本一律取**markdown 容器**（`div.prose`）而不是整个 `container`：气泡外面还有时间戳，
 * 整容器的 `textContent` 会把「15:00」也算进来，等式断言会假红。
 */
function renderReply(content: string) {
  mockChatStore.messages = [aiMsg(content)]
  const view = render(<MessageList />)
  const md = markdownRoot(view.container)
  const visible = strip(md.textContent)
  const strongs = Array.from(md.querySelectorAll('strong')).map((el) => strip(el.textContent))
  return { view, md, visible, strongs }
}

beforeEach(() => {
  mockChatStore.messages = []
  mockChatStore.currentSessionId = 's1'
  mockChatStore.isLoadingMessages = false
})

describe('MessageList — UI-098 中文标点旁的强调必须真的渲染成 <strong>', () => {
  it('UI-098 截图原句：`后台的**「订单列表」页**，` ⇒ 加粗在、星号不在', () => {
    const { md, visible, strongs } = renderReply('下单入口：后台的**「订单列表」页**，页面里的「新建订单」入口。')

    expect(strongs).toContain('「订单列表」页')
    expect(md.textContent).not.toContain('**')
    // 零可见变化：去掉零宽空格后逐字等于原文去掉标记
    expect(visible).toBe('下单入口：后台的「订单列表」页，页面里的「新建订单」入口。')
  })

  it('UI-098 整条回复（截图全文）：三处强调全部成立，且通篇不再出现 `**`', () => {
    const { md, visible, strongs } = renderReply(SCREENSHOT_REPLY)

    expect(strongs).toHaveLength(3)
    expect(strongs[0]).toContain('黄金策在订单域只做查询和分析')
    expect(strongs[1]).toBe('「订单列表」页')
    expect(strongs[2]).toBe('我能帮上忙的部分')

    expect(md.textContent).not.toContain('**')
    expect(md.innerHTML).not.toContain('**')
    // 正文一句不缺（`<br>`/块级边界在 textContent 里不产生分隔符 ⇒ 用包含断言，不用全等）
    expect(visible).toContain('你是新同事呀，欢迎！这条给你说清楚 👇')
    expect(visible).toContain('坦白说一句：我这边没有步骤级的操作指引')
    expect(visible).toContain('• 查实时库存 → 确认有没有货')
  })

  it('UI-098 闭合侧失效：`**「重点」**文本` 同样要加粗（不许只修开标记那一半）', () => {
    const { md, visible, strongs } = renderReply('**「重点」**文本')

    expect(strongs).toEqual(['「重点」'])
    expect(md.textContent).not.toContain('**')
    expect(visible).toBe('「重点」文本')
  })

  it('UI-098 负控：本来正常的形态与「不是强调」的星号逐字不动，且一个 ZWSP 都不许插', () => {
    // ⚠️ 各占一段（空行分隔）：同一段里的单个 `*` 会跨行与后面的 `****` 配对（CommonMark 的软换行），
    // 那属于 markdown 自身行为、与本模块无关 —— 混在一起会得到一条读不懂的假红。
    const plain = ['**A**：**B**', '', 'snake_case_name 与 a_b_c', '', '2 * 3 * 4 = 24', '', '手机号 138****8888'].join('\n')
    const { md, strongs } = renderReply(plain)

    expect(strongs).toEqual(['A', 'B'])
    expect(md.textContent).not.toContain(ZWSP)
    expect(md.textContent).toContain('snake_case_name 与 a_b_c')
    expect(md.textContent).toContain('2 * 3 * 4 = 24')
    expect(md.textContent).toContain('138****8888')
  })

  it('UI-098 代码面：行内代码与围栏代码块里的 `**` 逐字保留（不插 ZWSP、不被加粗）', () => {
    const content = [
      '看代码 `a**「x」**b`，正文 的**「说明」**。',
      '',
      '```python',
      'print("中文**「不会被动」**")',
      '```',
    ].join('\n')
    const { md, strongs } = renderReply(content)

    const codes = Array.from(md.querySelectorAll('code')).map((el) => el.textContent)
    expect(codes).toContain('a**「x」**b')
    expect(codes.some((c) => c?.includes('print("中文**「不会被动」**")'))).toBe(true)
    // 代码面之外的正文该加粗的还是加粗了（跳过代码 ≠ 整行跳过）
    expect(strongs).toContain('「说明」')
  })
})
