// case_ids: PP-011
// @vitest-environment jsdom
//
// PP-011（issue #6439 建版式 → **issue #6656 改判：与系统打印同一份纸面**）：
// 免驱动直连通道的**位图版式**（`frontend/admin-web/src/lib/label-print/wash-label.ts`）。
//
// 用户 2026-10-10 逐字：「直连打印机打印的样式和水洗唛预览打印的样式完全不一样，能不能做成一样的」
// ⇒ 内容面改读唯一真值 `washLabelRows`（判据见 `tests/unit/lib/wash-label-content.test.ts`），
// **几何**改读**同一份介质** `label-50x60`（预览的 `@page` 也指它）。
//
// 逐条判据（都能判红）：
// ① **几何由机器自报值 + 介质矩阵推出**：`printerDPI` / `printerWidth` 一变，`dpmm` 与画布尺寸跟着变
//    —— **写死机型口径 ⇒ 必红**（「不做打印机定制功能」的落点：接别家机器不改码）；
//    兜底值本身**不是**本模块的字面量，而是转发介质矩阵（含**纸长 60mm**：用户 2026-10-10 裁定按 60mm 卷做）；
// ② **短码是功能件、永不被裁**：`x + measure(短码, fontPx) ≤ widthPx − margin`，窄纸靠**缩字号**活下来；
// ③ 窄到连最小字号都放不下 ⇒ **显式抛错**（fail-closed），**绝不静默裁掉短码**
//    —— 短码是设计里明写的手输降级入口（`docs/design/worker-h5-scan-and-report.md` §1.4「不是可选项」）；
// ④ **纸面内容 = 行清单**（折行只插入断点、**不增删字**）—— 版式自己编字段 ⇒ 必红；
// ⑤ **装不下只裁文字块**：表头与底部「二维码 + 扫码报工 + 短码」位置不动（与 `.task-card-label` 的
//    flex 口径一致）；无码 ⇒ 不画假码，出**虚线占位框** + 占位文案；
// ⑥ `paintWashLabel` 只做执行：白底铺满 + 有码才 `drawImage` + 文字用算好的字号（不再二次排版）。
import { describe, expect, it } from 'vitest'
import {
  LABEL_DPI_DEFAULT,
  LABEL_HEAD_DOTS_DEFAULT,
  WASH_LABEL_DEFAULT_LENGTH_MM,
  WASH_LABEL_DEFAULT_WIDTH_MM,
  WASH_LABEL_MEDIA,
  WashLabelLayoutError,
  ellipsize,
  fitFontSize,
  layoutWashLabel,
  paintWashLabel,
  resolveLabelGeometry,
  wrapText,
  type WashLabelInput,
} from '@/lib/label-print/wash-label'
import type { WashLabelRow } from '@/lib/wash-label-content'
import { printDotGeometry, printPageBoxMm } from '@/lib/print-media'

/** 介质矩阵里的口径（**唯一真值源**）—— 本文件的期望值从它取，不写第二份像素字面量 */
const MATRIX = printDotGeometry('label-50x60')
const BOX = printPageBoxMm('label-50x60')

/** 确定性「量字」替身：0.6em/字符（等宽近似）—— 真机走 canvas `measureText` */
const measure = (text: string, fontPx: number) => text.length * fontPx * 0.6

const ROWS: WashLabelRow[] = [
  { key: 'customer', text: '客户 赵凯', maxLines: 1 },
  { key: 'setNo', text: '第 1 套 / 共 2 套', maxLines: 1 },
  { key: 'pieceName', text: '布艺遮光帘A', maxLines: 2 },
]

const input = (over: Partial<WashLabelInput> = {}): WashLabelInput => ({
  qrValue: 'https://app.migaozn.com/s/7Q2M4K8P',
  shortCode: '7Q2M4K8P',
  processingOrderNo: 'JG-20260921-8237',
  rows: ROWS,
  ...over,
})

describe('resolveLabelGeometry — 几何取自机器自报值 + 介质矩阵（判据 ①）', () => {
  it('未连接机器 ⇒ 兜底口径**取自介质矩阵**（模块只是转发，不写第二份字面量）', () => {
    const geo = resolveLabelGeometry(null)
    expect(geo.dpmm).toBeCloseTo(MATRIX.dpi / 25.4, 3)
    // 纸宽 50mm 换来的 400px 被**打印头 384 点**截住 ⇒ 出图必须按有效打印宽（越头的像素会被静默丢掉）
    expect(geo.widthPx).toBe(MATRIX.effectiveWidthPx)
    expect(geo.widthPx).toBe(LABEL_HEAD_DOTS_DEFAULT)
    expect(geo.heightPx).toBe(Math.round(WASH_LABEL_DEFAULT_LENGTH_MM * geo.dpmm))
    expect(LABEL_DPI_DEFAULT).toBe(MATRIX.dpi)
  })

  it('🔴 两条通道**同一份介质**：纸长 / 纸宽都取自 `label-50x60`（写死 40mm ⇒ 必红）', () => {
    expect(WASH_LABEL_DEFAULT_WIDTH_MM).toBe(BOX.widthMm)
    expect(WASH_LABEL_DEFAULT_LENGTH_MM).toBe(BOX.heightMm)
    // 用户 2026-10-10 裁定「按 60mm 卷做」⇒ 兜底纸长 = 介质纸长（不是 #6439 那版的 40mm）
    expect(WASH_LABEL_DEFAULT_LENGTH_MM).toBe(60)
    expect(WASH_LABEL_MEDIA).toBe('label-50x60')
  })

  it('🔴 机器自报 300dpi / 576dot ⇒ 几何整体跟着变（写死兜底值 ⇒ 必红）', () => {
    const geo = resolveLabelGeometry({ printerDPI: 300, printerWidth: 576 })
    expect(geo.dpmm).toBeCloseTo(300 / 25.4, 3)
    expect(geo.widthPx).toBe(576)
    expect(geo.heightPx).toBe(Math.round(WASH_LABEL_DEFAULT_LENGTH_MM * (300 / 25.4)))
    expect(geo.widthPx).not.toBe(LABEL_HEAD_DOTS_DEFAULT)
  })

  it('给了纸宽（mm）⇒ 取「纸宽 × dpmm」与打印头宽度的较小者（不越纸、不越头）', () => {
    expect(resolveLabelGeometry({ printerDPI: 203, printerWidth: 576 }, 40, 30).widthPx).toBe(
      Math.round(40 * (203 / 25.4)),
    )
    // 纸比头宽 ⇒ 仍受头宽限制
    expect(resolveLabelGeometry({ printerDPI: 203, printerWidth: 576 }, 80).widthPx).toBe(576)
    // 纸长是入参（缺省 = 介质纸长）
    expect(resolveLabelGeometry(null, null, 30).heightPx).toBe(Math.round(30 * (203 / 25.4)))
  })
})

describe('layoutWashLabel — 版式是纯函数（issue #6439 → #6656）', () => {
  const geo = resolveLabelGeometry(null)

  it('判据 ④：**纸面内容 = 行清单**（折行只插入断点，不增删字）', () => {
    const layout = layoutWashLabel(input(), geo, measure)
    // 正文块逐行文本首尾相接 == 行清单逐行文本首尾相接（版式自己编字段 / 丢字 ⇒ 必红）
    expect(layout.lines.map((line) => line.text).join('')).toBe(ROWS.map((row) => row.text).join(''))
    expect(layout.header?.text).toBe('JG-20260921-8237')
    expect(layout.shortCode.text).toBe('7Q2M4K8P')
    expect(layout.qrNote.text).toBe('扫码报工')
    // 行序自上而下（y 单调不减）
    expect(layout.lines.map((line) => line.y)).toEqual([...layout.lines.map((line) => line.y)].sort((a, b) => a - b))
  })

  it('判据 ②：短码**永不被裁**（x + 实测宽度 ≤ 纸宽 − 边距）', () => {
    const layout = layoutWashLabel(input(), geo, measure)
    const right = layout.shortCode.x + measure(layout.shortCode.text, layout.shortCode.fontPx)
    expect(right).toBeLessThanOrEqual(geo.widthPx - layout.margin + 0.001)
    expect(layout.shortCode.fontPx).toBeGreaterThan(0)
  })

  it('判据 ②：窄纸靠缩字号活下来（字号随纸宽单调不增），短码本体一字不少', () => {
    const wide = layoutWashLabel(input(), resolveLabelGeometry({ printerDPI: 203, printerWidth: 576 }), measure)
    const narrow = layoutWashLabel(input(), resolveLabelGeometry({ printerDPI: 203, printerWidth: 220 }), measure)
    expect(narrow.shortCode.fontPx).toBeLessThan(wide.shortCode.fontPx)
    expect(narrow.shortCode.text).toBe('7Q2M4K8P')
    expect(narrow.shortCode.x + measure(narrow.shortCode.text, narrow.shortCode.fontPx)).toBeLessThanOrEqual(
      220 - narrow.margin + 0.001,
    )
  })

  it('判据 ③：窄到放不下 ⇒ 抛 WashLabelLayoutError（fail-closed，不静默裁）', () => {
    expect(() =>
      layoutWashLabel(input(), resolveLabelGeometry({ printerDPI: 203, printerWidth: 120 }), measure),
    ).toThrow(WashLabelLayoutError)
  })

  it('判据 ⑤：文字块装不下 ⇒ **只裁文字块**（表头与底部码/短码位置不动）', () => {
    const long: WashLabelRow[] = Array.from({ length: 40 }, (_, index) => ({
      key: 'remark',
      text: `备注 第${index}行 这是一段会被挤出纸外的补充文字`,
      maxLines: 2,
    }))
    const clipped = layoutWashLabel(input({ rows: long }), geo, measure)
    const whole = layoutWashLabel(input(), geo, measure)

    // 正反对照：确实被裁了（否则「没越界」是空断言）
    expect(clipped.lines.length).toBeGreaterThan(0)
    expect(clipped.lines.length).toBeLessThan(40)
    // 每行都不越过正文块下沿（= 底部行上沿；越界 = 压到二维码/短码上）
    const blockBottom = clipped.qr!.y
    clipped.lines.forEach((line) =>
      expect(line.y + Math.round(line.fontPx * 1.2)).toBeLessThanOrEqual(blockBottom),
    )
    // 底部功能件（码与短码）位置一字不动 —— 空间不够时被裁的只能是补充文字
    expect(clipped.qr).toEqual(whole.qr)
    expect(clipped.shortCode).toEqual(whole.shortCode)
    expect(clipped.header).toEqual(whole.header)
  })

  it('判据 ⑤：无码 ⇒ 不画假码（`qr` 为 null），出占位框 + 占位文案，短码仍在', () => {
    const withQr = layoutWashLabel(input(), geo, measure)
    const noQr = layoutWashLabel(input({ qrValue: null }), geo, measure)

    expect(withQr.qr!.size).toBeGreaterThan(0)
    expect(withQr.qrPlaceholder).toBeNull()
    expect(noQr.qr).toBeNull()
    expect(noQr.qrPlaceholder!.rect.size).toBeGreaterThan(0)
    expect(noQr.qrPlaceholder!.lines.map((line) => line.text).join('')).toContain('待生成')
    expect(noQr.shortCode.text).toBe('7Q2M4K8P')
  })

  it('判据 ⑤：占位文案可覆盖（撤销后传「已撤销」，不谎称「待生成」）', () => {
    const revoked = layoutWashLabel(input({ qrValue: null, qrPlaceholderHint: '已撤销' }), geo, measure)
    expect(revoked.qrPlaceholder!.lines.map((line) => line.text).join('')).toContain('已撤销')
    expect(revoked.qrPlaceholder!.lines.map((line) => line.text).join('')).not.toContain('待生成')
  })

  it('版式落在纸内：所有元素不越界（含二维码与占位框）', () => {
    const layout = layoutWashLabel(input(), geo, measure)
    expect(layout.qr!.x).toBeGreaterThanOrEqual(0)
    expect(layout.qr!.x + layout.qr!.size).toBeLessThanOrEqual(geo.widthPx)
    expect(layout.qr!.y + layout.qr!.size).toBeLessThanOrEqual(geo.heightPx)

    const noQr = layoutWashLabel(input({ qrValue: null }), geo, measure)
    const box = noQr.qrPlaceholder!.rect
    expect(box.x + box.size).toBeLessThanOrEqual(geo.widthPx)
    expect(box.y + box.size).toBeLessThanOrEqual(geo.heightPx)
    expect(noQr.shortCode.x + measure(noQr.shortCode.text, noQr.shortCode.fontPx)).toBeLessThanOrEqual(
      geo.widthPx - noQr.margin + 0.001,
    )
  })

  it('缺表头（无加工单号）⇒ 正文块上移，不留空洞', () => {
    const withHeader = layoutWashLabel(input(), geo, measure)
    const without = layoutWashLabel(input({ processingOrderNo: '' }), geo, measure)
    expect(without.header).toBeNull()
    expect(without.lines[0].y).toBeLessThan(withHeader.lines[0].y)
  })
})

describe('wrapText / ellipsize / fitFontSize — 看得见的截断（判据 ④）', () => {
  it('放得下 ⇒ 单行原样返回', () => {
    expect(wrapText('客户 赵凯', 999, 20, measure, 1)).toEqual(['客户 赵凯'])
    expect(ellipsize('短', 999, 20, measure)).toBe('短')
  })

  it('按**字**折行：不改字、不改序，行行不超宽', () => {
    const lines = wrapText('客户 一个很长的客户名称需要折行', 120, 20, measure, 4)
    expect(lines.join('')).toBe('客户 一个很长的客户名称需要折行')
    lines.forEach((line) => expect(measure(line, 20)).toBeLessThanOrEqual(120))
  })

  it('行数预算用完 ⇒ 最后一行以省略号收尾（不静默吞字）', () => {
    const source = '一个很长的件名需要被折成很多行否则就该省略号收尾处理掉多余的字'
    const lines = wrapText(source, 100, 20, measure, 2)
    expect(lines).toHaveLength(2)
    expect(lines[1].endsWith('…')).toBe(true)
    // 保留的字数确实少于原文（截断真的发生了，不是「本来就只有两行」）
    expect(lines.join('').replace('…', '').length).toBeLessThan(source.length)
    lines.forEach((line) => expect(measure(line, 20)).toBeLessThanOrEqual(100))
  })

  it('fitFontSize：缩到最小字号仍放不下 ⇒ `fits: false`（由调用方 fail-closed）', () => {
    expect(fitFontSize('7Q2M4K8P', 999, 23, 20, measure)).toEqual({ fontPx: 23, fits: true })
    // 缩到最小字号才勉强放下 ⇒ fontPx = 下限、仍算放得下（96 ≤ 100）
    expect(fitFontSize('7Q2M4K8P', 100, 23, 20, measure)).toEqual({ fontPx: 20, fits: true })
    // 连最小字号都放不下 ⇒ `fits: false`（由调用方 fail-closed 抛错）
    expect(fitFontSize('7Q2M4K8P', 90, 23, 20, measure).fontPx).toBe(20)
    expect(fitFontSize('7Q2M4K8P', 90, 23, 20, measure).fits).toBe(false)
  })
})

describe('paintWashLabel — 执行层只照单绘制（判据 ⑥）', () => {
  /** 最小 2D 上下文替身：jsdom 没有 canvas，执行层用假 ctx 测调用面 */
  const fakeCtx = () => {
    const calls: string[] = []
    return {
      calls,
      fillStyle: '',
      strokeStyle: '',
      font: '',
      textAlign: '' as CanvasTextAlign,
      textBaseline: '' as CanvasTextBaseline,
      lineWidth: 1,
      fillRect: (...a: unknown[]) => calls.push(`fillRect:${a.join(',')}`),
      fillText: (...a: unknown[]) => calls.push(`fillText:${a.join(',')}`),
      strokeRect: () => calls.push('strokeRect'),
      setLineDash: () => calls.push('setLineDash'),
      drawImage: (...a: unknown[]) => calls.push(`drawImage:${a.length}`),
      measureText: (t: string) => ({ width: measure(t, 16) }) as TextMetrics,
    }
  }

  it('白底铺满整幅（热敏纸：不铺白 = 打出黑底的反色废纸）', () => {
    const ctx = fakeCtx()
    const geo = resolveLabelGeometry(null)
    paintWashLabel(ctx, layoutWashLabel(input(), geo, measure), null)
    expect(ctx.calls.some((c) => c === `fillRect:0,0,${geo.widthPx},${geo.heightPx}`)).toBe(true)
  })

  it('🔴 有码才 drawImage；无码时不画假码、改画虚线占位框', () => {
    const geo = resolveLabelGeometry(null)

    const ctx = fakeCtx()
    paintWashLabel(ctx, layoutWashLabel(input(), geo, measure), {} as unknown as CanvasImageSource)
    expect(ctx.calls.filter((c) => c.startsWith('drawImage'))).toHaveLength(1)
    expect(ctx.calls).not.toContain('strokeRect')

    const ctx2 = fakeCtx()
    paintWashLabel(ctx2, layoutWashLabel(input({ qrValue: null }), geo, measure), null)
    expect(ctx2.calls.some((c) => c.startsWith('drawImage'))).toBe(false)
    expect(ctx2.calls).toContain('strokeRect')
    expect(ctx2.calls.some((c) => c.startsWith('fillText:待生成'))).toBe(true)
  })

  it('文字按版式算好的字号绘制（不在执行层二次排版）', () => {
    const ctx = fakeCtx()
    const geo = resolveLabelGeometry(null)
    const layout = layoutWashLabel(input(), geo, measure)
    paintWashLabel(ctx, layout, null)
    expect(ctx.calls.some((c) => c.includes(`fillText:${layout.shortCode.text},${layout.shortCode.x}`))).toBe(true)
    expect(ctx.calls.some((c) => c.includes(`fillText:${layout.header!.text},${layout.header!.x}`))).toBe(true)
    expect(ctx.calls.some((c) => c.includes('fillText:客户 赵凯'))).toBe(true)
  })
})
