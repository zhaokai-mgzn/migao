// case_ids: UI-082
/**
 * WelcomePanel 组件测试 — B 端 agent 称呼改名（issue #6525）
 *
 * 为什么补这条（而不是当作"顺手改了一句文案"）：
 * 面板标题从「欢迎使用**米宝**」改成「欢迎使用**黄金策**」是**用户可见的称呼变更**，而
 * Growth Gate 的规则（`.github/tech-stack.yml`：`frontend/admin-web/src/components/**\/*.tsx`
 * ⇒ `tests/unit/components/{组件名}.test.ts`）要求这类改动带同名单测 —— 该组件**此前没有测试文件**
 * ⇒ 「改了没人管」。本文件给「标题 = B 端称呼」与「旧称呼 / C 端称呼不得出现在 B 端面板」各一个会红的判据。
 *
 * 红证（可复算，在 `frontend/admin-web` 目录下跑 `npx vitest run --dir tests/unit/components WelcomePanel`）：
 *   把 `src/components/chat/WelcomePanel.tsx` 的标题换回「欢迎使用米宝」⇒ 本文件当场红
 *   （`getByRole('heading', …)` 找不到 + `queryByText(/米宝/)` 非空）。
 */
import { describe, it, expect, vi } from 'vitest'
import { createElement } from 'react'
import { render, screen } from '@testing-library/react'

import WelcomePanel from '@/components/chat/WelcomePanel'

const mockChatStore = {
  sendMessage: vi.fn(),
  createSession: vi.fn().mockResolvedValue(undefined),
  currentSessionId: null as string | null,
}

vi.mock('@/store/chat', () => ({
  useChatStore: Object.assign(
    (selector?: (state: unknown) => unknown) =>
      typeof selector === 'function' ? selector(mockChatStore) : mockChatStore,
    { getState: () => mockChatStore },
  ),
}))

describe('WelcomePanel 品牌称呼（issue #6525）', () => {
  it('标题用 B 端称呼「黄金策」', () => {
    render(createElement(WelcomePanel))
    expect(screen.getByRole('heading', { name: /欢迎使用黄金策/ })).toBeInTheDocument()
  })

  it('旧称呼（米宝 / 小布）与 C 端称呼（元元）都不得出现在 B 端面板', () => {
    render(createElement(WelcomePanel))
    expect(screen.queryByText(/米宝|小布|元元/)).toBeNull()
  })
})
