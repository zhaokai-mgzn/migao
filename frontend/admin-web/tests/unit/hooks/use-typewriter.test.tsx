// case_ids: UI-079
/**
 * 客户端打字机（issue #5952；issue #7086 修「真实事件序下不播」）—— hook 级判据。
 *
 * 用户 2026-10-02 裁定：**选 2（客户端打字机）**，服务端仍整段下发
 * （`backend/ai-agent-service/app/agents/customer_service_agent.py::astream_chat`
 * 走 `graph.astream(stream_mode="updates")` = **节点级**更新；`finalize_turn` 有后置收口
 * 「追加确认卡 XML / 用工具返回 message 替换回复」⇒ 服务端逐字会与「收口后才是最终文本」冲突）。
 *
 * 🔴 **#7086 的根因与本文件的夹具纪律**：正文整段到达、紧随 `done`，`isStreaming` 翻假距正文到达
 * 只有几十～两百毫秒 ⇒ 旧 hook 的「`streaming: false` ⇒ 立刻等于全文」让揭示窗口 ≈ 0（一帧都播不完）。
 * ⇒ 本文件所有「直播」用例都必须用 {@link renderLive}（**先挂空占位、正文后到**），
 * **不许** `render(<Probe text={全文}/>)` 冒充直播 —— 后者是历史回放形态，用它测逐字会得出错误结论。
 *
 * 与实现无关的三条不变量（组件级判据见同目录 ../components/MessageList-typewriter.test.tsx）：
 * 1. 单调：已揭示字符数只增不减（收口替换时不许「先短后长再回退」）；
 * 2. 以最终内容为准：可见文本永远是**当前全文**的前缀；
 * 3. 有界收敛：`instant` / 减少动画 / 卸载 ⇒ 直接全文；直播消息在**有界时长**内揭完，不无限拖尾。
 *
 * 红证（修前红）：
 * - #7086 形态：把 hook 换回「`streaming` 一假即全文」或直接 `return text`（等效「无打字机」）⇒
 *   「UI-079-1 真实事件序」与「UI-079-1 真在逐字揭示」的「中途可见 < 全长」当场红；
 * - #5952 形态：本文件所测的 `useTypewriter` 在首版落地前**不存在**
 *   （全仓 `grep -rn "typewriter\|useTypewriter" frontend/admin-web/src` = 0 命中）⇒ import 即失败。
 */

import { describe, it, expect, vi, afterEach } from 'vitest'
import { act, render } from '@testing-library/react'
import {
  useTypewriter,
  TYPEWRITER_INTERVAL_MS,
  TYPEWRITER_MAX_REVEAL_MS,
} from '@/hooks/use-typewriter'

/** 把 hook 的返回值渲染进一个可探测节点：`data-count` = 可见字符数 */
function Probe({ text, instant = false, intervalMs }: {
  text: string
  instant?: boolean
  intervalMs?: number
}) {
  const visible = useTypewriter(text, { instant, intervalMs })
  return <span data-testid="tw" data-count={visible.length}>{visible}</span>
}

/**
 * **直播消息的真实形态**：store 在发送时同步插入 `content: ''` 的 AI 占位，正文随后到达
 * （`frontend/admin-web/src/store/chat.ts` 的 `aiMsg` 占位 + `handleSSEEvent('text')`）。
 * 直接 `render(<Probe text={全文}/>)` 是**历史回放**形态（挂载即完整 ⇒ 首帧全文）。
 */
function renderLive(text: string) {
  const view = render(<Probe text="" />)
  view.rerender(<Probe text={text} />)
  return view
}

/** 只走一个揭示间隔（`act` 包住，避免 act 警告） */
function tick(ms: number) {
  act(() => { vi.advanceTimersByTime(ms) })
}

function visible(): string {
  return document.querySelector('[data-testid="tw"]')?.textContent ?? ''
}

function visibleCount(): number {
  return Number(document.querySelector('[data-testid="tw"]')?.getAttribute('data-count'))
}

afterEach(() => {
  vi.useRealTimers()
})

describe('UI-079 useTypewriter — 客户端打字机', () => {
  it('UI-079-1 真在逐字揭示：中途可见字符数 < 总长，最终 == 总长', () => {
    vi.useFakeTimers()
    const text = '这是一段足够长的黄金策回复，用来观察它是不是真的一个字一个字出现。'
    renderLive(text)

    expect(visibleCount()).toBe(0)
    tick(TYPEWRITER_INTERVAL_MS * 3)
    // 判据 1 的关键读数：t 时刻可见 **严格少于** 全文
    expect(visibleCount()).toBe(3)
    expect(visibleCount()).toBeLessThan(text.length)
    // 且可见文本是全文前缀（不是乱码 / 不是别的内容）
    expect(text.startsWith(visible())).toBe(true)

    tick(TYPEWRITER_INTERVAL_MS * (text.length - 3))
    expect(visibleCount()).toBe(text.length)
    expect(visible()).toBe(text)
  })

  it('🔴 UI-079-1 真实事件序：正文整段到达后不因任何生命周期信号立刻收敛（#7086）', () => {
    vi.useFakeTimers()
    const text = '黄金策的整段回复在一个 SSE text 事件里到达，紧随其后就是 done。'
    // 直播形态：空占位 → 正文**整段**到达；此后没有任何「结束」信号能让揭示跳到全文
    renderLive(text)

    tick(TYPEWRITER_INTERVAL_MS * 5)
    // 旧实现（streaming 一假即全文）在这里是全长 ⇒ 本条当场红
    expect(visibleCount()).toBe(5)
    expect(visibleCount()).toBeLessThan(text.length)

    tick(TYPEWRITER_INTERVAL_MS * text.length)
    expect(visible()).toBe(text)
    // 揭完即**停表**（不留常驻定时器）
    expect(vi.getTimerCount()).toBe(0)
  })

  it('UI-079-2 收口替换不卡：先短后长 ⇒ 最终是收口版，且揭示进度一次都没有回退', () => {
    vi.useFakeTimers()
    const first = '收到，正在查询…'
    const sealed = '收到，正在查询…订单 SO-2026-001 已发货，预计明天送达。'
    const { rerender } = renderLive(first)

    tick(TYPEWRITER_INTERVAL_MS) // 揭示首版第 1 个字

    // 采样全程（每次只看一个间隔）：「先短后长再回退」若发生，读数序列就会出现下降
    const samples: number[] = [visibleCount()]
    rerender(<Probe text={sealed} />) // finalize_turn 收口：整段替换为「收口版」
    for (let i = 0; i < sealed.length; i++) {
      samples.push(visibleCount())
      tick(TYPEWRITER_INTERVAL_MS)
    }
    samples.push(visibleCount())

    for (let i = 1; i < samples.length; i++) {
      expect(samples[i]).toBeGreaterThanOrEqual(samples[i - 1])
    }

    // 中途可见文本必须始终是「收口版」的前缀（以最终内容为准，不是先到的那版）
    tick(TYPEWRITER_INTERVAL_MS * (sealed.length + 1))
    expect(visible()).toBe(sealed)
    expect(visibleCount()).toBe(sealed.length)
  })

  it('UI-079-2 反向：收口版比先到的更短 ⇒ 立刻夹到收口版，不出现越界可见文本', () => {
    vi.useFakeTimers()
    const first = '收到，正在查询订单信息…'
    const sealed = '已处理。'
    const { rerender } = renderLive(first)

    tick(TYPEWRITER_INTERVAL_MS * 5)
    expect(visibleCount()).toBe(5)

    rerender(<Probe text={sealed} />) // 收口后更短
    tick(TYPEWRITER_INTERVAL_MS)

    expect(visibleCount()).toBe(sealed.length)
    expect(visible()).toBe(sealed)
  })

  it('UI-079-3 有界收敛：长文不无限拖尾 —— 整段在 TYPEWRITER_MAX_REVEAL_MS 内揭完', () => {
    vi.useFakeTimers()
    const text = '长'.repeat(600)
    renderLive(text)

    tick(TYPEWRITER_INTERVAL_MS)
    // 不是「一次到位」：首帧只走一个步长
    expect(visibleCount()).toBeGreaterThan(0)
    expect(visibleCount()).toBeLessThan(text.length)

    tick(TYPEWRITER_MAX_REVEAL_MS)
    expect(visibleCount()).toBe(text.length)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('UI-079-3 历史回放 / 已结束会话（挂载即完整）⇒ 首帧即全文，不重播', () => {
    const text = '历史消息一进来就是完整的'
    render(<Probe text={text} />)
    expect(visibleCount()).toBe(text.length)
    expect(visible()).toBe(text)
  })

  it('UI-079-3 用户主动中断（instant）⇒ 立刻等于全文，不拖尾', () => {
    vi.useFakeTimers()
    const text = '被中断前已经收下的文本'
    const { rerender } = renderLive(text)
    tick(TYPEWRITER_INTERVAL_MS)
    expect(visibleCount()).toBe(1)

    rerender(<Probe text={text} instant />)
    expect(visible()).toBe(text)
  })

  it('UI-079-3 组件卸载 ⇒ 定时器被清掉，不再有任何状态更新（无卡死/无泄漏）', () => {
    vi.useFakeTimers()
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const { unmount } = renderLive('一二三四五六七八九十')
    tick(TYPEWRITER_INTERVAL_MS * 2)
    unmount()
    expect(() => tick(TYPEWRITER_INTERVAL_MS * 20)).not.toThrow()
    expect(vi.getTimerCount()).toBe(0)
    expect(errorSpy).not.toHaveBeenCalled()
    errorSpy.mockRestore()
  })

  it('UI-079-3 用户偏好减少动画 ⇒ 直接显示全文（不做逐字）', () => {
    const original = window.matchMedia
    window.matchMedia = ((query: string) => ({
      matches: query.includes('prefers-reduced-motion: reduce'),
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })) as unknown as typeof window.matchMedia

    try {
      const text = '减少动画时应当一次性看到全文'
      renderLive(text)
      expect(visible()).toBe(text)
    } finally {
      window.matchMedia = original
    }
  })

  it('UI-079 边界：文本还没到时不做任何揭示，不抛错', () => {
    vi.useFakeTimers()
    const { rerender } = render(<Probe text="" />)
    expect(visibleCount()).toBe(0)
    tick(TYPEWRITER_INTERVAL_MS * 5)
    expect(visibleCount()).toBe(0)
    rerender(<Probe text="来字了" />)
    tick(TYPEWRITER_INTERVAL_MS * 3)
    expect(visibleCount()).toBe(3)
  })
})
