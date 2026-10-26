// case_ids: UI-027
// @vitest-environment jsdom

import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'

import PrintDocPreview, { measureSheets } from '@/components/orders/PrintDocPreview'
import { printBodyFontPt, printContentInsetMm, printPageBoxMm, printUsableBoxMm } from '@/lib/print-media'

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

  it('①b 水洗唛纸型**固定 50mm × 150mm**（issue #7816）：纸框 / 边距 / 正文字号全从介质矩阵读（旧 50×70 已作废）', () => {
    render(
      <PrintDocPreview target="labels" title="水洗唛" media="label-50x150" onPrint={() => {}} onClose={() => {}}>
        <div>单据</div>
      </PrintDocPreview>
    )
    const paper = screen.getByTestId('print-preview-paper')
    // 纸型 = 矩阵里的 `label-50x150`（固定 50mm × 150mm，不再是"按内容撑开"的动态长度）
    expect(printPageBoxMm('label-50x150')).toEqual({ widthMm: 50, heightMm: 150 })
    expect(paper.style.width).toBe('50mm')
    expect(paper.style.minHeight).toBe('150mm')
    // 热敏标签：`@page` 边距 0 且无版面内缩 ⇒ 纸框 padding 为 0（纸边即版心）
    expect(printContentInsetMm('label-50x150')).toEqual({ xMm: 0, yMm: 0 })
    // ⚠️ 读长写法而不是 shorthand：jsdom 会把 `0mm 0mm` 归一成 `0mm`（序列化细节，不是版面差异）
    expect(paper.style.paddingTop).toBe('0mm')
    expect(paper.style.paddingLeft).toBe('0mm')
    // 正文字号由介质矩阵给（minFontPt = 12pt）—— 9pt 时代随 #7816 退场
    expect(paper.style.fontSize).toBe('12pt')
    expect(printBodyFontPt('label-50x150')).toBe(12)
    const mediaText = screen.getByTestId('print-preview-media').textContent ?? ''
    expect(mediaText).toContain('50mm × 150mm')
    expect(mediaText).toContain('无边距')
    expect(mediaText).toContain('正文 12pt')
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

  it('🔴 溢出逐张具名（issue #7833）：多张（水洗唛按开数出纸）时点名第几张超出 —— 只报总高度不可行动', () => {
    const stage = document.createElement('div')
    // 3 张：第 1 张 60px（装得下）、第 2 张 400px（超 60mm 的可用高）、第 3 张 120px
    stage.appendChild(stubSheet(60, 60))
    stage.appendChild(stubSheet(400, 400))
    stage.appendChild(stubSheet(120, 120))
    const check = measureSheets(stage, 60)
    if (!check) throw new Error('量不到纸 ⇒ 判据无从取值')
    // 1mm = 3.7795px；400px = 105.8mm > 60mm
    expect(check.overflowSheets).toEqual([2])
    expect(check.sheets).toBe(3)
    expect(check.overflowMm).toBeCloseTo(400 / MM_TO_PX - 60, 1)

    // 全部装得下 ⇒ 空数组（不是恒有值 —— 空断言会被这条打回）
    const fits = document.createElement('div')
    fits.appendChild(stubSheet(100, 100))
    expect(measureSheets(fits, 60)?.overflowSheets).toEqual([])
  })

  it('③ 多张纸（洗水码一部位一张）⇒ 计张数并取**最高**那张判溢出', () => {
    const stage = document.createElement('div')
    stage.appendChild(stubSheet(50 * MM_TO_PX, 60 * MM_TO_PX))
    stage.appendChild(stubSheet(64 * MM_TO_PX, 60 * MM_TO_PX))
    const check = measureSheets(stage, 60)
    expect(check!.sheets).toBe(2)
    expect(check!.contentMm).toBeCloseTo(64, 1)
    expect(check!.overflowMm).toBeCloseTo(4, 1)
    // issue #7833：只有第 2 张超（第 1 张 50mm）—— 逐张具名，不只报总高度
    expect(check!.overflowSheets).toEqual([2])
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

  it('⑥ 单据级附加动作槽 `actions`（issue #7288）：渲在页脚**同一动作行**、「复制截图」**之前**；不传 ⇒ 槽位不渲染', () => {
    const { rerender } = render(
      <PrintDocPreview
        target="labels"
        title="水洗唛"
        media="label-50x150"
        onPrint={() => {}}
        onClose={() => {}}
        actions={<button data-testid="extra-action">蓝牙无线打印</button>}
      >
        <div>单据</div>
      </PrintDocPreview>
    )
    const extra = screen.getByTestId('extra-action')
    const capture = screen.getByTestId('print-preview-capture')
    const row = screen.getByTestId('print-preview-actions')
    // 同一动作行 = 页脚动作行（否则「右下角」这个位置会被下次改版悄悄搬走）
    expect(extra.parentElement).toBe(row)
    expect(row.contains(capture)).toBe(true)
    expect(row.contains(screen.getByTestId('print-preview-print'))).toBe(true)
    // 在「复制截图」之前 ⇒ 主操作「打印」永远在最右（一屏至多一个 primary）
    expect(extra.compareDocumentPosition(capture) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()

    // 不传（销售单 / 发货单等其它单据）⇒ 槽位不渲染，页脚与改前一致
    rerender(
      <PrintDocPreview
        target="labels"
        title="水洗唛"
        media="label-50x150"
        onPrint={() => {}}
        onClose={() => {}}
      >
        <div>单据</div>
      </PrintDocPreview>
    )
    expect(screen.queryByTestId('extra-action')).toBeNull()
  })
})

/**
 * 单据选择器（issue #7544）—— 订单详情页把「4 个打印按钮」收成一个「打印」入口之后，
 * **选哪一份**这件事搬到了本层。这里判三件事：
 *
 * ① 给了 `docs` ⇒ 一单一签、文案取 `PRINT_TARGET_SPECS`、纸型读介质矩阵（不另写一份字面量）；
 * ② 点标签 = **换单据**（回调拿到 target），**不触发打印** —— 换一份看看不是出纸；
 * ③ 不传 `docs` ⇒ 没有选择器（发货页 / 加工单生产页各只有一份单据，形态必须与改前逐字一致）。
 */
describe('打印层的单据选择器（issue #7544）', () => {
  const DOCS = ['sales', 'processing', 'quotation', 'shipment'] as const

  function open(
    docs: readonly (typeof DOCS)[number][] | undefined,
    onSelect: (t: string) => void = () => {},
  ) {
    return render(
      <PrintDocPreview
        target="sales"
        title="销售单"
        media="continuous-241x140"
        docs={docs}
        onSelect={onSelect}
        onPrint={() => {}}
        onClose={() => {}}
      >
        <div>单据</div>
      </PrintDocPreview>,
    )
  }

  it('① 一单一签，标题 + 纸型都来自真值源（A4 / 三联纸）', () => {
    open(DOCS)
    expect(screen.getByTestId('print-preview-docs')).toBeInTheDocument()
    expect(screen.getByTestId('print-preview-doc-sales')).toHaveTextContent('销售单')
    expect(screen.getByTestId('print-preview-doc-sales')).toHaveTextContent('241×140')
    expect(screen.getByTestId('print-preview-doc-processing')).toHaveTextContent('加工单')
    expect(screen.getByTestId('print-preview-doc-processing')).toHaveTextContent('210×297')
    expect(screen.getByTestId('print-preview-doc-quotation')).toHaveTextContent('报价单')
    expect(screen.getByTestId('print-preview-doc-shipment')).toHaveTextContent('发货单')
    // 当前单据 = 唯一选中项
    expect(screen.getByTestId('print-preview-doc-sales')).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByTestId('print-preview-doc-processing')).toHaveAttribute('aria-pressed', 'false')
  })

  it('② 点标签只换单据（回调拿到 target），不触发打印', () => {
    const onSelect = vi.fn()
    const onPrint = vi.fn()
    render(
      <PrintDocPreview
        target="sales"
        title="销售单"
        media="continuous-241x140"
        docs={DOCS}
        onSelect={onSelect}
        onPrint={onPrint}
        onClose={() => {}}
      >
        <div>单据</div>
      </PrintDocPreview>,
    )
    fireEvent.click(screen.getByTestId('print-preview-doc-processing'))
    expect(onSelect).toHaveBeenCalledWith('processing')
    expect(onPrint).not.toHaveBeenCalled()
  })

  it('③ 不传 docs ⇒ 没有选择器（单份单据页的形态不变）', () => {
    open(undefined)
    expect(screen.queryByTestId('print-preview-docs')).toBeNull()
  })
})
