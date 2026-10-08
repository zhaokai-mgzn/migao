// case_ids: UI-079
/**
 * 客户端打字机（issue #5952）—— hook 级判据。
 *
 * 用户 2026-10-02 裁定：**选 2（客户端打字机）**，服务端仍整段下发
 * （`backend/ai-agent-service/app/agents/customer_service_agent.py::astream_chat`
 * 走 `graph.astream(stream_mode="updates")` = **节点级**更新；`finalize_turn` 有后置收口
 * 「追加确认卡 XML / 用工具返回 message 替换回复」⇒ 服务端逐字会与「收口后才是最终文本」冲突）。
 *
 * 与实现无关的三条不变量（组件级判据见同目录 ../components/MessageList-typewriter.test.tsx）：
 * 1. 单调：已揭示字符数只增不减（收口替换时不许「先短后长再回退」）；
 * 2. 以最终内容为准：可见文本永远是**当前全文**的前缀；
 * 3. 立刻收敛：结束 / 中断 / 卸载 / 减少动画 ⇒ 直接全文，不卡半截。
 *
 * 红证（修前红）：本文件所测的 `useTypewriter` 在本次改动前**不存在**
 * （全仓 `grep -rn "typewriter\|useTypewriter" frontend/admin-web/src` = 0 命中）
 * ⇒ import 即失败；把 hook 换成 `return text`（等效「无打字机」）⇒ 判据 UI-079-1 的
 * 「中途可见 < 全长」当场红。
 */

import { describe, it, expect, vi, afterEach } from 'vitest'
import { act, render } from '@testing-library/react'
import { useTypewriter, TYPEWRITER_INTERVAL_MS } from '@/hooks/use-typewriter'

/** 把 hook 的返回值渲染进一个可探测节点：`data-count` = 可见字符数 */
function Probe({ text, streaming = true, intervalMs }: {
  text: string
  streaming?: boolean
  intervalMs?: number
}) {
  const visible = useTypewriter(text, { streaming, intervalMs })
  return <span data-testid="tw" data-count={visible.length}>{visible}</span>
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
    render(<Probe text={text} />)

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

  it('UI-079-2 收口替换不卡：先短后长 ⇒ 最终是收口版，且揭示进度一次都没有回退', () => {
    vi.useFakeTimers()
    const first = '收到，正在查询…'
    const sealed = '收到，正在查询…订单 SO-2026-001 已发货，预计明天送达。'
    const { rerender } = render(<Probe text={first} />)

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
    const { rerender } = render(<Probe text={first} />)

    tick(TYPEWRITER_INTERVAL_MS * 5)
    expect(visibleCount()).toBe(5)

    rerender(<Probe text={sealed} />) // 收口后更短
    tick(TYPEWRITER_INTERVAL_MS)

    expect(visibleCount()).toBe(sealed.length)
    expect(visible()).toBe(sealed)
  })

  it('UI-079-3 流式结束 ⇒ 立刻等于全文（不追赶、不残留半截）', () => {
    vi.useFakeTimers()
    const text = '一二三四五六七八九十'
    const { rerender } = render(<Probe text={text} streaming />)
    tick(TYPEWRITER_INTERVAL_MS)
    expect(visibleCount()).toBe(1)

    rerender(<Probe text={text} streaming={false} />)
    expect(visible()).toBe(text)
  })

  it('UI-079-3 中断 / 已结束会话 ⇒ 立刻等于全文', () => {
    const text = '被中断前已经收下的文本'
    render(<Probe text={text} streaming={false} />)
    expect(visible()).toBe(text)
  })

  it('UI-079-3 组件卸载 ⇒ 定时器被清掉，不再有任何状态更新（无卡死/无泄漏）', () => {
    vi.useFakeTimers()
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const { unmount } = render(<Probe text={'一二三四五六七八九十'} />)
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
      render(<Probe text={text} />)
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

  it('UI-079 对照：历史回放（非流式）不分段揭示，首帧即全文', () => {
    const text = '历史消息一进来就是完整的'
    render(<Probe text={text} streaming={false} />)
    expect(visibleCount()).toBe(text.length)
  })
})
