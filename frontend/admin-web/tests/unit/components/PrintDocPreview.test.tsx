// case_ids: UI-027
// @vitest-environment jsdom

import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'

import PrintDocPreview, { measureSheets } from '@/components/orders/PrintDocPreview'
import { printPageBoxMm, printUsableBoxMm } from '@/lib/print-media'

/**
 * 打印前的**纸面自检层**（issue #5914）—— 判据三件事：
 *
 * ① **纸型与版心从介质矩阵读**（不是组件自带字面量）；
 * ② **溢出判定**看的是内容**真实高度**（销售单 `.sales-sheet` 固定 128mm + `overflow:hidden`，
 *    只有 `scrollHeight` 能反映被裁掉多少）—— 这正是「>6 行明细静默裁掉金额与收款码」的可见化；
 * ③ **预览副本不上纸**：显形规则必须包在 `@media screen` 里（否则同一份单据会出两张）。
 *
 * ⚠️ jsdom 没有排版 ⇒ 几何一律用**打桩读数**判（真几何由 Playwright 在真浏览器里量，
 * 见 `tests/e2e/specs/orders/print-preview.spec.ts`）。
 */

function stubSheet(scrollHeightPx: number, offsetHeightPx: number): HTMLElement {
  const sheet = document.createElement('div')
  sheet.setAttribute('data-print-sheet', '')
  Object.defineProperty(sheet, 'scrollHeight', { value: scrollHeightPx, configurable: true })
  Object.defineProperty(sheet, 'offsetHeight', { value: offsetHeightPx, configurable: true })
  return sheet
}

const MM_TO_PX = 96 / 25.4

describe('纸面自检层 PrintDocPreview（issue #5914）', () => {
  afterEach(cleanup)

  it('① 纸型与版心**从介质矩阵读**（三联纸 241×140、版心 217×128）', () => {
    render(
      <PrintDocPreview
        target="sales"
        title="销售单"
        media="continuous-241x140"
        onPrint={() => {}}
        onClose={() => {}}
      >
        <div>单据</div>
      </PrintDocPreview>
    )
    const paper = screen.getByTestId('print-preview-paper')
    const box = printPageBoxMm('continuous-241x140')
    const usable = printUsableBoxMm('continuous-241x140')
    expect(paper.style.width).toBe(`${box.widthMm}mm`)
    expect(paper.style.minHeight).toBe(`${box.heightMm}mm`)
    // 页边距 6mm 12mm ⇒ 版心 217 × 128
    expect(paper.style.padding).toBe('6mm 12mm')
    expect(usable).toEqual({ widthMm: 217, heightMm: 128 })
    expect(screen.getByTestId('print-preview-media').textContent).toContain('241mm × 140mm')
  })

  it('② 未打开（target=null）⇒ 整层不渲染，且 children **不挂载**', () => {
    render(
      <PrintDocPreview target={null} title="销售单" media="continuous-241x140" onPrint={() => {}} onClose={() => {}}>
        <div data-testid="child">单据</div>
      </PrintDocPreview>
    )
    expect(screen.queryByTestId('print-preview')).toBeNull()
    expect(screen.queryByTestId('child')).toBeNull()
  })

  it('③ 溢出判定：内容 129.4mm > 单联 128mm ⇒ 报溢出并给出可行动出口', () => {
    const stage = document.createElement('div')
    // 129.4mm ≈ 488.9px（#5914 实测的 7 行明细读数）；容器高 128mm
    stage.appendChild(stubSheet(129.4 * MM_TO_PX, 128 * MM_TO_PX))
    const check = measureSheets(stage, 128)
    if (check === null) throw new Error('纸面自检没有给出读数（没有量到 data-print-sheet）')
    expect(check.contentMm).toBeCloseTo(129.4, 1)
    expect(check!.limitMm).toBe(128)
    expect(check!.overflowMm).toBeCloseTo(1.4, 1)
  })

  it('③ 不溢出：内容 122.2mm ≤ 128mm（6 行明细）', () => {
    const stage = document.createElement('div')
    stage.appendChild(stubSheet(122.2 * MM_TO_PX, 128 * MM_TO_PX))
    const check = measureSheets(stage, 128)
    expect(check!.contentMm).toBeCloseTo(122.2, 1)
    expect(check!.overflowMm).toBeLessThanOrEqual(0)
  })

  it('③ 没有可量的纸（没有 data-print-sheet）⇒ 返回 null（不编一个「装得下」）', () => {
    expect(measureSheets(document.createElement('div'), 128)).toBeNull()
  })

  it('③ 多张纸（洗水码一部位一张）⇒ 计张数并取**最高**那张判溢出', () => {
    const stage = document.createElement('div')
    stage.appendChild(stubSheet(50 * MM_TO_PX, 60 * MM_TO_PX))
    stage.appendChild(stubSheet(64 * MM_TO_PX, 60 * MM_TO_PX))
    const check = measureSheets(stage, 60)
    expect(check!.sheets).toBe(2)
    expect(check!.contentMm).toBeCloseTo(64, 1)
    expect(check!.overflowMm).toBeCloseTo(4, 1)
  })

  it('④ 🔴 预览副本**不上纸**：显形规则必须包在 `@media screen` 里（否则会出两张）', () => {
    const { container } = render(
      <PrintDocPreview
        target="sales"
        title="销售单"
        media="continuous-241x140"
        onPrint={() => {}}
        onClose={() => {}}
      >
        <div className="sales-print-area print-doc">单据</div>
      </PrintDocPreview>
    )
    const style = container.querySelector('style')?.textContent || ''
    expect(style).toMatch(/@media screen\s*\{/)
    expect(style).toContain('.print-preview-doc > *')
    // 打印媒体下**没有**任何针对预览副本的显形规则（`@media print` 块一块都不许有）
    expect(style).not.toMatch(/@media print/)
  })

  it('⑤ 两个出口都在：`复制截图` 与 `打印`（截图不是可选装饰，是本次需求的一半）', () => {
    const onPrint = vi.fn()
    render(
      <PrintDocPreview
        target="sales"
        title="销售单"
        media="continuous-241x140"
        onPrint={onPrint}
        onClose={() => {}}
      >
        <div>单据</div>
      </PrintDocPreview>
    )
    expect(screen.getByTestId('print-preview-capture')).toBeTruthy()
    fireEvent.click(screen.getByTestId('print-preview-print'))
    expect(onPrint).toHaveBeenCalledTimes(1)
  })
})
