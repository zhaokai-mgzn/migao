// case_ids: UI-027, OR-072
// @vitest-environment jsdom

import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react'

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

describe('打印机引导与本机登记（issue #7957）', () => {
  afterEach(() => {
    cleanup()
    localStorage.clear()
  })

  function renderWith(media: 'a4' | 'continuous-241x140' | 'label-50x140', extra: Record<string, unknown> = {}) {
    return render(
      <PrintDocPreview
        target="processing"
        title="加工单"
        media={media}
        onPrint={() => {}}
        onClose={() => {}}
        {...extra}
      >
        <div>单据</div>
      </PrintDocPreview>
    )
  }

  it('① 未登记 ⇒ 显示**纸型对应的通用打印机类型** + 「登记本机名称」入口（不编型号）', () => {
    renderWith('a4')
    const hint = screen.getByTestId('print-printer-hint')
    expect(hint).toHaveTextContent('打印机：A4 激光打印机')
    expect(screen.getByTestId('print-printer-edit')).toHaveTextContent('登记本机名称')
  })

  it('①b 连续纸 / 标签纸各给对应类型（不是同一句话）', () => {
    renderWith('continuous-241x140')
    expect(screen.getByTestId('print-printer-hint')).toHaveTextContent('针式打印机（连续纸）')
    cleanup()
    renderWith('label-50x140')
    expect(screen.getByTestId('print-printer-hint')).toHaveTextContent('标签打印机')
  })

  it('② 登记后显示「打印机：<名>」，且**再渲染一次仍在**（真持久化，不是内存态）', () => {
    const first = renderWith('a4')
    fireEvent.click(screen.getByTestId('print-printer-edit'))
    fireEvent.change(screen.getByTestId('print-printer-input'), { target: { value: ' HP LaserJet M404 ' } })
    fireEvent.click(screen.getByTestId('print-printer-save'))
    expect(screen.getByTestId('print-printer-hint')).toHaveTextContent('打印机：HP LaserJet M404')
    first.unmount()

    renderWith('a4')
    expect(screen.getByTestId('print-printer-hint')).toHaveTextContent('打印机：HP LaserJet M404')
    // 已登记 ⇒ 入口变成「更改」
    expect(screen.getByTestId('print-printer-edit')).toHaveTextContent('更改')
  })

  it('③ 空白名不保存（保存后仍是未登记态，入口仍是「登记本机名称」）', () => {
    renderWith('a4')
    fireEvent.click(screen.getByTestId('print-printer-edit'))
    fireEvent.change(screen.getByTestId('print-printer-input'), { target: { value: '   ' } })
    fireEvent.click(screen.getByTestId('print-printer-save'))
    expect(screen.getByTestId('print-printer-hint')).toHaveTextContent('打印机：A4 激光打印机')
    expect(screen.getByTestId('print-printer-edit')).toHaveTextContent('登记本机名称')
  })

  it('④ 联合打印**进度行**带当前纸型 + 该纸型的打印机（每张出纸前就知道该选哪台）', () => {
    const batch = {
      stage: 'running' as const,
      candidates: ['processing', 'labels'] as const,
      selected: ['processing', 'labels'] as const,
      index: 0,
      fired: false,
      current: 'processing' as const,
      batchId: 'b-1',
      openPanel: vi.fn(),
      closePanel: vi.fn(),
      toggle: vi.fn(),
      toggleAll: vi.fn(),
      start: vi.fn(),
      markFired: vi.fn(),
      next: vi.fn(),
      stop: vi.fn(),
    }
    renderWith('a4', { batch: batch as never, docs: ['processing', 'labels'], onSelect: () => {} })
    const progress = screen.getByTestId('print-batch-progress')
    expect(progress).toHaveTextContent('210×297mm')
    expect(progress).toHaveTextContent('A4 激光打印机')
  })
})

describe('联合打印面板（issue #7941：去重复 / 份·张分读 / 勾选行层次）', () => {
  afterEach(cleanup)

  /** 面板只依赖 `PrintBatchController` 的形状（不发起真打印）⇒ 直接给替身，逐条判形态 */
  function fakeBatch(over: Partial<Record<string, unknown>> = {}) {
    const candidates = ['quotation', 'sales', 'processing', 'labels'] as const
    return {
      stage: 'panel' as const,
      candidates: [...candidates],
      selected: ['sales', 'labels'] as ('quotation' | 'sales' | 'processing' | 'labels')[],
      index: 0,
      fired: false,
      current: 'sales' as const,
      batchId: 'b-1',
      openPanel: vi.fn(),
      closePanel: vi.fn(),
      toggle: vi.fn(),
      toggleAll: vi.fn(),
      start: vi.fn(),
      markFired: vi.fn(),
      next: vi.fn(),
      stop: vi.fn(),
      ...over,
    }
  }

  function renderPanel(batch: ReturnType<typeof fakeBatch>, target: 'quotation' | 'sales' | 'processing' | 'labels' = 'sales') {
    return render(
      <PrintDocPreview
        target={target}
        title="销售单"
        media="continuous-241x140"
        onPrint={() => {}}
        onClose={() => {}}
        docs={['quotation', 'sales', 'processing', 'labels']}
        onSelect={() => {}}
        batch={batch as never}
        sheetsOf={(doc) => (doc === 'labels' ? 4 : 1)}
      >
        <div>单据</div>
      </PrintDocPreview>
    )
  }

  it('⓪ 勾选项与单据标签**同一行**（issue #7949：横排，不另起竖排列表）', () => {
    renderPanel(fakeBatch())
    const row = screen.getByTestId('print-preview-docs')
    // 四个勾选项都是这一行的直接子级（= 同一行的 chip）
    for (const doc of ['quotation', 'sales', 'processing', 'labels']) {
      const chip = screen.getByTestId(`print-batch-doc-${doc}`)
      expect(chip.parentElement).toBe(row)
    }
    expect(row.className).toContain('flex-wrap')
    expect(row.className).not.toContain('flex-col')
    // 面板里**没有**竖排列表（改回`<ul><li>` ⇒ 红）
    expect(screen.getByTestId('print-batch-panel').querySelector('li')).toBeNull()
  })

  it('⓪b 联合打印面板只占**一行**：读数与三个动作全在同一行容器里', () => {
    renderPanel(fakeBatch())
    const panel = screen.getByTestId('print-batch-panel')
    for (const id of ['print-batch-summary', 'print-batch-toggle-all', 'print-batch-cancel', 'print-batch-start']) {
      expect(panel.contains(screen.getByTestId(id))).toBe(true)
    }
    // 勾选项**不在**面板里（它们在上一行，与标签同一行）
    expect(panel.contains(screen.getByTestId('print-batch-doc-sales'))).toBe(false)
  })

  it('⓪c 勾选 chip **保留序号数字**（用户 2026-10-27「数字仍然展示」）', () => {
    renderPanel(fakeBatch())
    const docs = ['quotation', 'sales', 'processing', 'labels']
    docs.forEach((doc, i) => {
      const chip = screen.getByTestId(`print-batch-doc-${doc}`)
      const text = chip.textContent ?? ''
      // 序号 = 真实出纸顺序，弱化成行内小字（仍可读、仍上屏）
      expect(text.trim().startsWith(String(i + 1))).toBe(true)
      // 张数也在（4 张 / 1 张）—— 两种数字都不丢
      expect(text).toMatch(/\d+ 张/)
    })
  })

  it('① 勾选行**不再重复纸型**（同一面板纸型只许出现在上方标签行）', () => {
    renderPanel(fakeBatch())
    const panel = screen.getByTestId('print-batch-panel')
    // 行内没有任何 `210×297mm` 这类纸型读数（标签行仍在，但它不在 panel 里）
    expect(panel.textContent).not.toMatch(/\d+×\d+mm/)
  })

  it('② 行右侧只留**张数**（水洗唛 4 张 / 单据 1 张），数字等宽', () => {
    renderPanel(fakeBatch())
    expect(screen.getByTestId('print-batch-doc-labels')).toHaveTextContent('4 张')
    expect(screen.getByTestId('print-batch-doc-sales')).toHaveTextContent('1 张')
  })

  it('③ 面板给出「已选 N 份 · M 张纸」汇总读数，主按钮只说动作（不再把份数写成「张」）', () => {
    renderPanel(fakeBatch())
    expect(screen.getByTestId('print-batch-summary')).toHaveTextContent('已选 2 份 · 5 张纸')
    const start = screen.getByTestId('print-batch-start')
    expect(start).toHaveTextContent('开始联合打印')
    expect(start.textContent).not.toMatch(/（\d+ 张）/)
  })

  it('④ 「全选」降为**文字按钮**（原生 button + aria-pressed，不是描边次级按钮）', () => {
    const batch = fakeBatch()
    renderPanel(batch)
    const toggleAll = screen.getByTestId('print-batch-toggle-all')
    expect(toggleAll.tagName).toBe('BUTTON')
    expect(toggleAll).toHaveAttribute('aria-pressed', 'false') // 4 选 2 ⇒ 未全选
    fireEvent.click(toggleAll)
    expect(batch.toggleAll).toHaveBeenCalledTimes(1)
  })

  it('④b 已全选时 aria-pressed=true（读数与视觉同源）', () => {
    renderPanel(fakeBatch({ selected: ['quotation', 'sales', 'processing', 'labels'] }))
    expect(screen.getByTestId('print-batch-toggle-all')).toHaveAttribute('aria-pressed', 'true')
  })

  it('⑤ 当前正在预览的那一份带「当前」徽标（勾选态与预览态是两件事）', () => {
    renderPanel(fakeBatch(), 'sales')
    expect(screen.getByTestId('print-batch-doc-sales')).toHaveTextContent('当前')
    expect(screen.getByTestId('print-batch-doc-quotation')).not.toHaveTextContent('当前')
  })

  it('⑥ 说明文案收敛为一句（17 字以内、无分号）', () => {
    renderPanel(fakeBatch())
    const text = screen.getByTestId('print-batch-panel').textContent ?? ''
    expect(text).toContain('按顺序逐张出纸')
    expect(text).not.toContain('；')
  })
})

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

  it('①b 水洗唛纸型**固定 50mm × 140mm**（issue #7979）：纸框 / 边距 / 正文字号全从介质矩阵读（旧 50×119 已作废）', () => {
    render(
      <PrintDocPreview target="labels" title="水洗唛" media="label-50x140" onPrint={() => {}} onClose={() => {}}>
        <div>单据</div>
      </PrintDocPreview>
    )
    const paper = screen.getByTestId('print-preview-paper')
    // 纸型 = 矩阵里的 `label-50x140`（固定 50mm × 140mm，不再是"按内容撑开"的动态长度）
    expect(printPageBoxMm('label-50x140')).toEqual({ widthMm: 50, heightMm: 140 })
    expect(paper.style.width).toBe('50mm')
    expect(paper.style.minHeight).toBe('140mm')
    // 热敏标签：`@page` 边距 0 且无版面内缩 ⇒ 纸框 padding 为 0（纸边即版心）
    expect(printContentInsetMm('label-50x140')).toEqual({ xMm: 0, yMm: 0 })
    // ⚠️ 读长写法而不是 shorthand：jsdom 会把 `0mm 0mm` 归一成 `0mm`（序列化细节，不是版面差异）
    expect(paper.style.paddingTop).toBe('0mm')
    expect(paper.style.paddingLeft).toBe('0mm')
    // 正文字号由介质矩阵给（minFontPt = 11pt）—— 9pt 时代随 #7816 退场
    expect(paper.style.fontSize).toBe('11pt')
    expect(printBodyFontPt('label-50x140')).toBe(11)
    const mediaText = screen.getByTestId('print-preview-media').textContent ?? ''
    expect(mediaText).toContain('50mm × 140mm')
    expect(mediaText).toContain('无边距')
    expect(mediaText).toContain('正文 11pt')
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

  it('🔴 每张按**自己的纸长**判溢出（issue #8107）：同一份出纸里 50×140 与 50×100 并存，不再用文档级单一 limit', () => {
    const stage = document.createElement('div')
    // 第 1 张 = 常规唛（140mm，自己声明），内容 60mm ⇒ 装得下
    const regular = stubSheet(60 * MM_TO_PX, 140 * MM_TO_PX)
    regular.setAttribute('data-sheet-paper-mm', '50x140')
    // 第 2 张 = 专属唛（100mm），内容 60mm ⇒ 装得下
    const optionFits = stubSheet(60 * MM_TO_PX, 100 * MM_TO_PX)
    optionFits.setAttribute('data-sheet-paper-mm', '50x100')
    // 第 3 张 = 专属唛，内容 105mm ⇒ 超过**自己的** 100mm（按文档级 140 判会**假绿**）
    const optionOver = stubSheet(105 * MM_TO_PX, 100 * MM_TO_PX)
    optionOver.setAttribute('data-sheet-paper-mm', '50x100')
    optionOver.setAttribute('data-sheet-note', '专属唛')
    stage.append(regular, optionFits, optionOver)

    // 文档级 limit = 140mm（水洗唛主纸型）—— 改前这一路会把 105mm 那批判成「装得下」
    const check = measureSheets(stage, 140)
    if (!check) throw new Error('量不到纸 ⇒ 判据无从取值')
    expect(check.sheets).toBe(3)
    expect(check.contentMm).toBeCloseTo(105, 1)
    expect(check.overflowSheets).toEqual([3])
    expect(check.overflowMm).toBeCloseTo(5, 1)
    // 纸型清单（按 DOM 顺序去重）—— 预览表头据此显示两种纸
    expect(check.papers).toEqual([
      { widthMm: 50, heightMm: 140 },
      { widthMm: 50, heightMm: 100, note: '专属唛' },
    ])
    // 反向对照：同一张 105mm 纸若不声明纸型（= 按文档级 140mm 判）⇒ 空 ——
    // 说明上一条真的靠「每张自己的纸」才红（否则它只是重复了旧的单一 limit 口径）
    const loose = document.createElement('div')
    loose.appendChild(stubSheet(105 * MM_TO_PX, 100 * MM_TO_PX))
    expect(measureSheets(loose, 140)?.overflowSheets).toEqual([])
  })

  it('🔴 表头纸型能反映**两种纸**（issue #8107）：常规唛 50mm × 140mm · 专属唛 50mm × 100mm', async () => {
    render(
      <PrintDocPreview target="labels" title="水洗唛" media="label-50x140" onPrint={() => {}} onClose={() => {}}>
        <div>
          <div data-print-sheet data-sheet-paper-mm="50x140" />
          <div data-print-sheet data-sheet-paper-mm="50x100" data-sheet-note="专属唛" />
        </div>
      </PrintDocPreview>
    )
    // 纸面自检异步量一次（重试窗口 1s）⇒ 等它落定，别断言首帧
    await waitFor(() => {
      expect(screen.getByTestId('print-preview-media').textContent).toContain('专属唛 50mm × 100mm')
    })
    const mediaText = screen.getByTestId('print-preview-media').textContent ?? ''
    // 主纸型仍是本单据的介质；额外那张由每张纸自己声明（不改写、不加第二种真值）
    expect(mediaText).toContain('50mm × 140mm')
    expect(mediaText).toContain('专属唛 50mm × 100mm')
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
        media="label-50x140"
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
        media="label-50x140"
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
  // 发货单自 issue #7902 起整体退场 ⇒ 目标位只剩三份（加工单/水洗唛在订单页按派单动态给）
  const DOCS = ['sales', 'processing', 'quotation'] as const

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

/* ==========================================================================
 * 打印流水入口（issue #7964，用户 2026-10-28「打印流水应该放到打印预览界面上…不要放到订单明细中」）
 * ==========================================================================*/
describe('打印流水入口：入口在表头、视图在本层内（issue #7964）', () => {
  afterEach(cleanup)

  function fakeBatch(over: Partial<Record<string, unknown>> = {}) {
    return {
      stage: 'running' as const,
      candidates: ['processing', 'labels'] as const,
      selected: ['processing', 'labels'] as const,
      index: 0,
      fired: false,
      current: 'processing' as const,
      batchId: 'b-1',
      openPanel: vi.fn(),
      closePanel: vi.fn(),
      toggle: vi.fn(),
      toggleAll: vi.fn(),
      start: vi.fn(),
      markFired: vi.fn(),
      next: vi.fn(),
      stop: vi.fn(),
      ...over,
    }
  }

  function renderWithLogs(extra: Record<string, unknown> = {}) {
    return render(
      <PrintDocPreview
        target="processing"
        title="加工单"
        media="a4"
        onPrint={() => {}}
        onClose={() => {}}
        logs={<div data-testid="fake-print-logs">流水</div>}
        {...extra}
      >
        <div>单据</div>
      </PrintDocPreview>,
    )
  }

  it('① 不传 logs ⇒ 表头没有入口（其它打印使用方零影响）', () => {
    render(
      <PrintDocPreview target="processing" title="加工单" media="a4" onPrint={() => {}} onClose={() => {}}>
        <div>单据</div>
      </PrintDocPreview>,
    )
    expect(screen.queryByTestId('print-preview-logs-entry')).toBeNull()
  })

  it('② 点入口 ⇒ 本层内看流水；纸面 / 自检 / 打印动作一并退场（流水不随纸印出）', () => {
    renderWithLogs()
    expect(screen.getByTestId('print-preview-paper')).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('print-preview-logs-entry'))

    const view = screen.getByTestId('print-preview-logs')
    expect(view).toHaveTextContent('打印流水')
    expect(view).toHaveTextContent('流水')
    // 🔴 流水块在纸框**之外** —— 它永远不会上纸
    expect(view.closest('[data-print-paper]')).toBeNull()
    expect(screen.queryByTestId('print-preview-paper')).toBeNull()
    expect(screen.queryByTestId('print-preview-check')).toBeNull()
    expect(screen.queryByTestId('print-preview-actions')).toBeNull()
    expect(screen.getByTestId('print-preview-logs-entry')).toHaveTextContent('返回预览')
    expect(screen.getByTestId('print-preview-logs-entry')).toHaveAttribute('aria-expanded', 'true')

    // 再点回到纸面
    fireEvent.click(screen.getByTestId('print-preview-logs-entry'))
    expect(screen.getByTestId('print-preview-paper')).toBeInTheDocument()
    expect(screen.queryByTestId('print-preview-logs')).toBeNull()
    expect(screen.getByTestId('print-preview-logs-entry')).toHaveTextContent('打印流水')
  })

  it('③ 联合打印逐张引导中 ⇒ 不出现入口（不打断正在换的那张纸）', () => {
    renderWithLogs({ batch: fakeBatch(), docs: ['processing', 'labels'], onSelect: () => {} })
    expect(screen.queryByTestId('print-preview-logs-entry')).toBeNull()
  })

  it('④ 关层再开 ⇒ 回到纸面（视图状态不跨次残留）', () => {
    const view = renderWithLogs()
    fireEvent.click(screen.getByTestId('print-preview-logs-entry'))
    expect(screen.getByTestId('print-preview-logs')).toBeInTheDocument()

    view.rerender(
      <PrintDocPreview target={null} title="加工单" media="a4" onPrint={() => {}} onClose={() => {}} logs={<div>流水</div>}>
        <div>单据</div>
      </PrintDocPreview>,
    )
    view.rerender(
      <PrintDocPreview target="processing" title="加工单" media="a4" onPrint={() => {}} onClose={() => {}} logs={<div>流水</div>}>
        <div>单据</div>
      </PrintDocPreview>,
    )
    expect(screen.getByTestId('print-preview-paper')).toBeInTheDocument()
    expect(screen.queryByTestId('print-preview-logs')).toBeNull()
  })
})
