// case_ids: PP-011
// @vitest-environment jsdom
//
// PP-011（issue #6439）：免驱动直连通道打的**洗水码精简版位图**。
//
// 用户 2026-10-06 选定内容面 = **二维码 + 大字短码 + 件名/部位**（不是照搬浏览器打印的全字段面：
// 水洗唛是缝在布上的小标签，且直连机型多在 203dpi ⇒ 6pt 字打出来易糊）。
//
// 逐条判据（都能判红）：
// ① **几何由机器自报值推出**：`printerDPI` / `printerWidth` 一变，`dpmm` 与画布尺寸跟着变
//    —— **写死机型口径 ⇒ 必红**（「不做打印机定制功能」的落点：接别家机器不改码）；
//    兜底值本身也**不是**本模块的字面量，而是转发介质矩阵 `label-50x60.dotGeometry`（判据见下第一条）；
// ② **短码是功能件、永不被裁**：`x + measure(短码, fontPx) ≤ widthPx − margin`，窄纸靠**缩字号**活下来；
// ③ 窄到连最小字号都放不下 ⇒ **显式抛错**（fail-closed），**绝不静默裁掉短码**
//    —— 短码是设计里明写的手输降级入口（`docs/design/worker-h5-scan-and-report.md` §1.4「不是可选项」）；
// ④ 件名/部位放不下 ⇒ **显式省略号**（看得见的截断），不是静默切掉；
// ⑤ 无码（部位被撤销）⇒ 不画假码：`qr` 为 null，短码位置上移，其余照排；
// ⑥ `paintWashLabel` 只做执行：白底铺满 + 有码才 `drawImage` + 文字用算好的字号（不再二次排版）。
import { describe, expect, it } from 'vitest'
import {
  LABEL_DPI_DEFAULT,
  LABEL_HEAD_DOTS_DEFAULT,
  WASH_LABEL_DEFAULT_LENGTH_MM,
  WashLabelLayoutError,
  ellipsize,
  layoutWashLabel,
  paintWashLabel,
  resolveLabelGeometry,
  toWashLabelInputs,
  type WashLabelInput,
} from '@/lib/label-print/wash-label'
import { printDotGeometry } from '@/lib/print-media'

/** 介质矩阵里的点阵口径（**唯一真值源**）—— 本文件的期望值从它取，不写第二份像素字面量 */
const MATRIX = printDotGeometry('label-50x60')

/** 确定性「量字」替身：0.6em/字符（等宽近似）—— 真机走 canvas `measureText` */
const measure = (text: string, fontPx: number) => text.length * fontPx * 0.6

const input = (over: Partial<WashLabelInput> = {}): WashLabelInput => ({
  qrValue: 'https://app.migaozn.com/s/7Q2M4K8P',
  shortCode: '7Q2M4K8P',
  pieceName: '客厅窗帘A',
  positionKind: '布帘',
  ...over,
})

describe('resolveLabelGeometry — 几何取自机器自报值（issue #6439 判据 ①）', () => {
  it('未连接机器 ⇒ 兜底口径**取自介质矩阵**（模块只是转发，不写第二份字面量）', () => {
    const geo = resolveLabelGeometry(null)
    expect(geo.dpmm).toBeCloseTo(MATRIX.dpi / 25.4, 3)
    expect(geo.widthPx).toBe(MATRIX.headWidthPx)
    expect(geo.heightPx).toBe(Math.round(WASH_LABEL_DEFAULT_LENGTH_MM * geo.dpmm))
    expect(LABEL_DPI_DEFAULT).toBe(MATRIX.dpi)
    expect(LABEL_HEAD_DOTS_DEFAULT).toBe(MATRIX.headWidthPx)
  })

  it('🔴 机器自报 300dpi / 576dot ⇒ 几何整体跟着变（写死兜底值 ⇒ 必红）', () => {
    const geo = resolveLabelGeometry({ printerDPI: 300, printerWidth: 576 })
    expect(geo.dpmm).toBeCloseTo(300 / 25.4, 3)
    expect(geo.widthPx).toBe(576)
    expect(geo.heightPx).toBe(Math.round(WASH_LABEL_DEFAULT_LENGTH_MM * (300 / 25.4)))
    expect(geo.widthPx).not.toBe(LABEL_HEAD_DOTS_DEFAULT)
  })

  it('给了纸宽（mm）⇒ 取「纸宽 × dpmm」与打印头宽度的较小者（不越纸、不越头）', () => {
    expect(resolveLabelGeometry({ printerDPI: 203, printerWidth: 576 }, 40).widthPx).toBe(Math.round(40 * (203 / 25.4)))
    // 纸比头宽 ⇒ 仍受头宽限制
    expect(resolveLabelGeometry({ printerDPI: 203, printerWidth: 576 }, 80).widthPx).toBe(576)
  })
})

describe('layoutWashLabel — 版式是纯函数（issue #6439）', () => {
  const geo = resolveLabelGeometry(null)

  it('判据 ②：短码**永不被裁**（x + 实测宽度 ≤ 纸宽 − 边距）', () => {
    const layout = layoutWashLabel(input(), geo, measure)
    const right = layout.shortCode.x + measure(layout.shortCode.text, layout.shortCode.fontPx)
    expect(right).toBeLessThanOrEqual(geo.widthPx - layout.margin + 0.001)
    expect(layout.shortCode.fontPx).toBeGreaterThan(0)
  })

  it('判据 ②：窄纸靠缩字号活下来（字号随纸宽单调不增），短码本体一字不少', () => {
    const wide = layoutWashLabel(input(), resolveLabelGeometry({ printerDPI: 203, printerWidth: 576 }), measure)
    const narrow = layoutWashLabel(input(), resolveLabelGeometry({ printerDPI: 203, printerWidth: 200 }), measure)
    expect(narrow.shortCode.fontPx).toBeLessThan(wide.shortCode.fontPx)
    expect(narrow.shortCode.text).toBe('7Q2M4K8P')
    expect(
      narrow.shortCode.x + measure(narrow.shortCode.text, narrow.shortCode.fontPx),
    ).toBeLessThanOrEqual(200 - narrow.margin + 0.001)
  })

  it('判据 ③：窄到放不下 ⇒ 抛 WashLabelLayoutError（fail-closed，不静默裁）', () => {
    expect(() => layoutWashLabel(input(), resolveLabelGeometry({ printerDPI: 203, printerWidth: 120 }), measure)).toThrow(
      WashLabelLayoutError,
    )
  })

  it('判据 ④：件名放不下 ⇒ 显式省略号（看得见的截断）', () => {
    const source = '超长件名'.repeat(12)
    const long = layoutWashLabel(input({ pieceName: source }), geo, measure)
    // 内容级判据（不用 `not.toBeNull()` 那种不触业务数据的弱断言 —— 弱断言守卫对新增文件 fail-closed）
    // 版式把件名写成 `部位 · 件名`（部位在前）⇒ 断言从头到尾都是**真内容**，不是「非空」
    expect(long.pieceName!.text.startsWith('布帘 · 超长件名')).toBe(true)
    expect(long.pieceName!.text.endsWith('…')).toBe(true)
    expect(long.pieceName!.text.length).toBeLessThan(source.length)
    expect(
      long.pieceName!.x + measure(long.pieceName!.text, long.pieceName!.fontPx),
    ).toBeLessThanOrEqual(geo.widthPx - long.margin + 0.001)
  })

  it('判据 ⑤：无码 ⇒ qr 为 null、短码上移，其余照排（不画假码）', () => {
    const withQr = layoutWashLabel(input(), geo, measure)
    const noQr = layoutWashLabel(input({ qrValue: null }), geo, measure)
    expect(withQr.qr!.size).toBeGreaterThan(0)
    expect(withQr.qr!.x).toBeGreaterThanOrEqual(0)
    expect(noQr.qr).toBeNull()
    expect(noQr.shortCode.y).toBeLessThan(withQr.shortCode.y)
  })

  it('版式落在纸内：所有元素不越界（含二维码）', () => {
    const layout = layoutWashLabel(input(), geo, measure)
    expect(layout.qr!.x).toBeGreaterThanOrEqual(0)
    expect(layout.qr!.x + layout.qr!.size).toBeLessThanOrEqual(geo.widthPx)
    expect(layout.qr!.y + layout.qr!.size).toBeLessThanOrEqual(geo.heightPx)
  })
})

describe('ellipsize — 看得见的截断（issue #6439 判据 ④）', () => {
  it('放得下 ⇒ 原样返回', () => {
    expect(ellipsize('短', 999, 20, measure)).toBe('短')
  })
  it('放不下 ⇒ 以省略号收尾且宽度受控', () => {
    const out = ellipsize('这是一个很长的件名需要被截断', 100, 20, measure)
    expect(out.endsWith('…')).toBe(true)
    expect(measure(out, 20)).toBeLessThanOrEqual(100)
  })
})

describe('paintWashLabel — 执行层只照单绘制（issue #6439 判据 ⑥）', () => {
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

  it('🔴 有码才 drawImage；无码时不画（不画假码）', () => {
    const ctx = fakeCtx()
    const geo = resolveLabelGeometry(null)
    paintWashLabel(ctx, layoutWashLabel(input(), geo, measure), {} as unknown as CanvasImageSource)
    expect(ctx.calls.some((c) => c.startsWith('drawImage'))).toBe(true)

    const ctx2 = fakeCtx()
    paintWashLabel(ctx2, layoutWashLabel(input({ qrValue: null }), geo, measure), null)
    expect(ctx2.calls.some((c) => c.startsWith('drawImage'))).toBe(false)
  })

  it('文字按版式算好的字号绘制（不在执行层二次排版）', () => {
    const ctx = fakeCtx()
    const geo = resolveLabelGeometry(null)
    const layout = layoutWashLabel(input(), geo, measure)
    paintWashLabel(ctx, layout, null)
    expect(ctx.calls.some((c) => c.includes(`fillText:${layout.shortCode.text}`))).toBe(true)
  })
})

describe('toWashLabelInputs — 部位 ⇒ 洗水码数据的**单一处**映射（issue #6439）', () => {
  it('码 = scan_url ?? part_token；两者都没有 ⇒ null（不画假码）', () => {
    const [withScan, withToken, noCode] = toWashLabelInputs([
      { scan_url: 'https://x/s/AAAAAAAA', part_token: 'tok-1', part_short_code: 'AAAAAAAA' },
      { scan_url: null, part_token: 'tok-2', part_short_code: 'BBBBBBBB' },
      { scan_url: null, part_token: null, part_short_code: 'CCCCCCCC' },
    ])
    expect(withScan.qrValue).toBe('https://x/s/AAAAAAAA')
    expect(withToken.qrValue).toBe('tok-2')
    expect(noCode.qrValue).toBeNull()
  })

  it('短码缺失 ⇒ 如实「—」（不编造）；件名部位名优先、退回商品名', () => {
    const [row] = toWashLabelInputs([
      { part_short_code: null, position_name: '', product_name: '客厅窗帘', position_kind: '布帘' },
    ])
    expect(row.shortCode).toBe('—')
    expect(row.pieceName).toBe('客厅窗帘')
    expect(row.positionKind).toBe('布帘')
  })

  it('空输入 ⇒ 空数组（不造占位：直连入口据此禁用，不是打一张空白纸）', () => {
    expect(toWashLabelInputs(null)).toEqual([])
    expect(toWashLabelInputs([])).toEqual([])
  })
})
