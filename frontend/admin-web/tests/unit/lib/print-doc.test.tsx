// case_ids: UI-027
// @vitest-environment jsdom

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, fireEvent, cleanup } from '@testing-library/react'

import { PRINT_TARGETS, PRINT_TARGET_SPECS, usePrintDoc } from '@/lib/print-doc'
import { PRINT_MEDIA_IDS } from '@/lib/print-media'

/**
 * 打印入口（issue #5914）—— `lib/print-doc.ts` 的判据。
 *
 * 这里判的是**这条链路上曾经真出过事的那一点**：
 *
 * ```
 * const printDoc = (t) => { setPrintTarget(t); window.print() }   // 旧写法
 * at-call:TARGET_MISSING   beforeprint:TARGET_MISSING              // 实测读数
 * ```
 *
 * `window.print()` 与 `setState` 同 tick ⇒ print 触发时目标还没进 DOM ⇒ 目标单据拿不到
 * `visibility: visible` 防御 ⇒ **第一次点打印打出一张空白纸**（第二次才对）。
 * 下面的判据断言的正是「**print 被调用的那一刻，目标已经在 DOM 里**」。
 */

function Harness() {
  const { printTarget, previewTarget, requestPrint, openPreview, closePreview } = usePrintDoc()
  return (
    <div>
      <button onClick={() => requestPrint('sales')}>打印销售单</button>
      <button onClick={() => openPreview('quotation')}>预览报价单</button>
      <button onClick={closePreview}>关闭预览</button>
      <div data-testid="docs">
        {PRINT_TARGETS.map((target) => (
          <div
            key={target}
            data-doc={target}
            {...(printTarget === target ? { 'data-print-target': target } : {})}
          />
        ))}
      </div>
      <span data-testid="preview">{previewTarget ?? 'none'}</span>
      <span data-testid="print-target">{printTarget ?? 'none'}</span>
    </div>
  )
}

describe('打印入口 usePrintDoc（issue #5914）', () => {
  let seen: string[]
  let realPrint: typeof window.print

  beforeEach(() => {
    seen = []
    realPrint = window.print
    // 记下「print 被调用那一刻」DOM 里的打印目标 —— 这条读数就是判据本体
    window.print = vi.fn(() => {
      const marks = Array.from(document.querySelectorAll('[data-print-target]')).map((el) =>
        el.getAttribute('data-print-target')
      )
      seen.push(marks.join(',') || 'NONE')
    }) as unknown as typeof window.print
  })

  afterEach(() => {
    window.print = realPrint
    cleanup()
  })

  it('① 🔴 print 被调用时目标**已在 DOM**（同 tick 调 print 的旧写法会得到 NONE ⇒ 空白纸）', () => {
    const { getByText } = render(<Harness />)
    fireEvent.click(getByText('打印销售单'))
    expect(seen).toEqual(['sales'])
    // 反向对照：DOM 里确实只置位了**一个**目标（一次只放一份单据上纸）
    expect(document.querySelectorAll('[data-print-target]')).toHaveLength(1)
  })

  it('② 连点两次同一份单据 ⇒ 两次都开印（不是只认第一次的布尔开关）', () => {
    const { getByText } = render(<Harness />)
    fireEvent.click(getByText('打印销售单'))
    fireEvent.click(getByText('打印销售单'))
    expect(seen).toEqual(['sales', 'sales'])
  })

  it('③ 预览：置位目标 + 打开预览层；关闭预览**不撤目标**（Ctrl+P 仍印该单据）', () => {
    const { getByText, getByTestId } = render(<Harness />)
    fireEvent.click(getByText('预览报价单'))
    expect(getByTestId('preview').textContent).toBe('quotation')
    expect(getByTestId('print-target').textContent).toBe('quotation')
    expect(document.querySelectorAll('[data-print-target]')).toHaveLength(1)
    // 只是开了预览 ⇒ **不许**开印（纸是耗材，没点「打印」就不该出纸）
    expect(seen).toEqual([])
    fireEvent.click(getByText('关闭预览'))
    expect(getByTestId('preview').textContent).toBe('none')
    expect(getByTestId('print-target').textContent).toBe('quotation')
  })

  it('④ 目标位与介质 id 都在册：每个 target 有标题 + 一个**矩阵里真实存在**的介质', () => {
    expect([...PRINT_TARGETS].sort()).toEqual(Object.keys(PRINT_TARGET_SPECS).sort())
    for (const target of PRINT_TARGETS) {
      const spec = PRINT_TARGET_SPECS[target]
      expect(spec.title.trim().length).toBeGreaterThan(0)
      expect(PRINT_MEDIA_IDS).toContain(spec.media)
    }
  })
})
