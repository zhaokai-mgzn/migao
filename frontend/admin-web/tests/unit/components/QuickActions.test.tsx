// case_ids: PR-053
/**
 * 快捷操作里的**工具类入口**（issue #7351）
 *
 * 判据：
 * 1. 服务端 `tools`（营销海报）与六格问句 `actions` 分开渲染；
 * 2. 点工具入口发送服务端下发的 prompt（不在前端写死文案）；
 * 3. store 解析响应时同时收 `actions` / `tools`（旧服务端没有 `tools` 字段 ⇒ 空数组，不崩）。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import QuickActions from '@/components/chat/QuickActions'
import { useChatStore } from '@/store/chat'

const ACTIONS = [
  { id: 'daily_business', name: '今日经营', icon: 'bar-chart-3', prompt: '今天经营怎么样？' },
  { id: 'low_stock', name: '库存告急', icon: 'package', prompt: '有哪些低库存的商品？' },
]
const TOOLS = [
  { id: 'marketing_poster', name: '营销海报', icon: 'image', prompt: '我要给商品做一张营销海报' },
]

describe('QuickActions 工具类入口（营销海报）', () => {
  const originalFetch = global.fetch

  beforeEach(() => {
    useChatStore.setState({ currentSessionId: 'sess_1', isStreaming: false })
    global.fetch = vi.fn(async () => ({
      ok: true,
      json: async () => ({ success: true, data: { actions: ACTIONS, tools: TOOLS } }),
    })) as unknown as typeof fetch
  })

  afterEach(() => {
    global.fetch = originalFetch
    useChatStore.setState({ currentSessionId: null, quickActions: [], quickTools: [] })
  })

  it('渲染工具入口并发送服务端给的 prompt', async () => {
    const sendMessage = vi.fn()
    useChatStore.setState({ sendMessage })

    render(<QuickActions />)

    const toolButton = await screen.findByTestId('quick-tool-action')
    expect(toolButton.textContent).toContain('营销海报')
    // 六格问句照旧渲染（工具入口不挤占问句入口）
    expect(screen.getByText('今日经营')).toBeTruthy()

    fireEvent.click(toolButton)
    expect(sendMessage).toHaveBeenCalledWith('我要给商品做一张营销海报')
  })

  it('store 解析响应时同时收 actions 与 tools', async () => {
    await useChatStore.getState().fetchQuickActions()
    expect(useChatStore.getState().quickActions).toEqual(ACTIONS)
    expect(useChatStore.getState().quickTools).toEqual(TOOLS)
  })

  it('旧服务端没有 tools 字段 ⇒ 空数组（不崩、不造入口）', async () => {
    global.fetch = vi.fn(async () => ({
      ok: true,
      json: async () => ({ success: true, data: { actions: ACTIONS } }),
    })) as unknown as typeof fetch

    await useChatStore.getState().fetchQuickActions()
    await waitFor(() => expect(useChatStore.getState().quickTools).toEqual([]))
  })
})
