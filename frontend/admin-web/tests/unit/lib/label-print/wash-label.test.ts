// case_ids: PP-011
// @vitest-environment jsdom
//
// PP-011（issue #6439 建版式 → #6656 与系统打印同一份纸面 → **2026-10-27 固定纸型 50×110**）：
// 免驱动直连通道的**位图版式**（`frontend/admin-web/src/lib/label-print/wash-label.ts`）。
//
// 用户 2026-10-26 逐字（issue #7816）：「水洗唛长度不足，设置为打印50*150」「字体还是太小，可以再大一点」
// 「二维码放到底部居中」「移除扫码报工和短码文字」「二维码可以放大一点」「移除加工单号」。
// 2026-10-27 逐字（issue #7948）：「把水洗唛的尺寸改成50*110，现在偏长了」「二维码不能直接沉底，
// 务必和底部留点距离」⇒ 纸长 119mm；二维码下沿与纸底（底部虚线）恒 ≥ 6mm（从纸边起算）。
//
// 逐条判据（都能判红）：
// ① **几何由机器自报值 + 介质矩阵推出**：`printerDPI` / `printerWidth` 一变，`dpmm` 与画布尺寸跟着变
//    —— **写死机型口径 ⇒ 必红**（「不做打印机定制功能」的落点：接别家机器不改码）；
//    兜底值转发介质矩阵（纸宽 50mm × 纸长 **119mm** 固定）；
// ② **纸面内容 = 行清单**（折行只插入断点、**不增删字**）—— 版式自己编字段 ⇒ 必红；
//    **issue #7833 起正文不设行数预算**（`WashLabelRow` 无 `maxLines`）：末行**不再**以省略号收尾；
// ③ **二维码在底部居中**，无码 ⇒ 虚线占位框（不画假码）；**不再有**加工单号 / 扫码报工 / 人可读短码；
// ④ **装不下只裁文字块**（底部码位置不动，与 `.task-card-label` 的 flex 口径一致）；
// ⑤ `paintWashLabel` 只做执行：白底铺满 + 有码才 `drawImage` + 文字用算好的字号（不再二次排版）。
import { describe, expect, it } from 'vitest'
import {
  LABEL_DPI_DEFAULT,
  LABEL_HEAD_DOTS_DEFAULT,
  WASH_LABEL_DEFAULT_LENGTH_MM,
  WASH_LABEL_DEFAULT_WIDTH_MM,
  WASH_LABEL_MEDIA,
  WashLabelLayoutError,
  ellipsize,
  layoutWashLabel,
  paintWashLabel,
  resolveLabelGeometry,
  wrapText,
  type WashLabelInput,
} from '@/lib/label-print/wash-label'
import type { WashLabelRow } from '@/lib/wash-label-content'
import { printDotGeometry, printPageBoxMm } from '@/lib/print-media'
import {
  WASH_LABEL_BODY_FONT_PT,
  WASH_LABEL_BOTTOM_CLEARANCE_MM,
  WASH_LABEL_COMPANY_FONT_PT,
  WASH_LABEL_COMPANY_SUBTITLE_FONT_PT,
  WASH_LABEL_LINE_HEIGHT,
  WASH_LABEL_QR_TEXT_GAP_LINES,
} from '@/lib/label-print/wash-label-metrics'

/** 正文行高（px）= 字号 × 行高倍数 —— 与 `layoutWashLabel` 里的 `lineStep` 同口径 */
const lineStepOf = (dpmm: number) =>
  Math.round(Math.round((WASH_LABEL_BODY_FONT_PT / 72) * 25.4 * dpmm) * WASH_LABEL_LINE_HEIGHT)

/** 介质矩阵里的口径（**唯一真值源**）—— 本文件的期望值从它取，不写第二份像素字面量 */
const MATRIX = printDotGeometry('label-50x119')
const BOX = printPageBoxMm('label-50x119')

/** 确定性「量字」替身：0.6em/字符（等宽近似）—— 真机走 canvas `measureText` */
const measure = (text: string, fontPx: number) => text.length * fontPx * 0.6

const ROWS: WashLabelRow[] = [
  // issue #7833：单号 = 加工单号（17 位订单号退出纸面）；加工方式去前缀、去加工类型、并入加工费组合项
  { key: 'docNo', text: '单号: JG-20260921-8237' },
  { key: 'customer', text: '客户: 赵凯' },
  { key: 'setNo', text: '第 1 套 / 共 2 套' },
  { key: 'craft', text: '韩褶 · 超高 · 倒幅 · 双开 · 定型' },
  { key: 'pleats', text: '褶法: 韩褶公式 52折' },
]

const input = (over: Partial<WashLabelInput> = {}): WashLabelInput => ({
  qrValue: 'https://app.migaozn.com/s/7Q2M4K8P',
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
    // 纸长 119mm × 203dpi = 951.1 → 951 点（矩阵里的 952 = 119 × 8 dots/mm 的整点口径，差 1 点是 dpi 取整）
    expect(geo.heightPx).toBe(Math.round(BOX.heightMm * (MATRIX.dpi / 25.4)))
    expect(LABEL_DPI_DEFAULT).toBe(MATRIX.dpi)
  })

  it('🔴 两条通道**同一份介质**：纸长 / 纸宽都取自 `label-50x119`（写死 150mm / 70mm / 40mm ⇒ 必红）', () => {
    expect(WASH_LABEL_DEFAULT_WIDTH_MM).toBe(BOX.widthMm)
    expect(WASH_LABEL_DEFAULT_LENGTH_MM).toBe(BOX.heightMm)
    // 2026-10-27 用户裁定「客户要求小于120mm」⇒ 纸长 119mm（#7816 的 150mm 作废）
    expect(WASH_LABEL_DEFAULT_LENGTH_MM).toBe(119)
    expect(WASH_LABEL_MEDIA).toBe('label-50x119')
  })

  it('🔴 机器自报 300dpi / 576dot ⇒ 几何整体跟着变（写死兜底值 ⇒ 必红）', () => {
    const geo = resolveLabelGeometry({ printerDPI: 300, printerWidth: 576 })
    expect(geo.dpmm).toBeCloseTo(300 / 25.4, 3)
    expect(geo.widthPx).toBe(576)
    expect(geo.heightPx).toBe(Math.round(WASH_LABEL_DEFAULT_LENGTH_MM * (300 / 25.4)))
    expect(geo.widthPx).not.toBe(LABEL_HEAD_DOTS_DEFAULT)
  })

  it('给了纸宽（mm）⇒ 取「纸宽 × dpmm」与打印头宽度的较小者（不越纸、不越头）', () => {
    expect(resolveLabelGeometry({ printerDPI: 203, printerWidth: 576 }, 40).widthPx).toBe(
      Math.round(40 * (203 / 25.4)),
    )
    // 纸比头宽 ⇒ 仍受头宽限制
    expect(resolveLabelGeometry({ printerDPI: 203, printerWidth: 576 }, 80).widthPx).toBe(576)
    // 纸长**不吃入参**（issue #7816：纸型固定，画布高度恒 = 矩阵纸长 × dpmm）
    expect(resolveLabelGeometry({ printerDPI: 203, printerWidth: 576 }, 40).heightPx).toBe(
      Math.round(WASH_LABEL_DEFAULT_LENGTH_MM * (203 / 25.4)),
    )
  })
})

describe('layoutWashLabel — 版式是纯函数（#6439 → #6656 → #7816）', () => {
  const geo = resolveLabelGeometry(null)

  it('判据 ②：**纸面内容 = 行清单**（折行只插入断点，不增删字）；不再有加工单号/短码', () => {
    const layout = layoutWashLabel(input(), geo, measure)
    // 正文块逐行文本首尾相接 == 行清单逐行文本首尾相接（版式自己编字段 / 丢字 ⇒ 必红）
    expect(layout.lines.map((line) => line.text).join('')).toBe(ROWS.map((row) => row.text).join(''))
    // 🔴 加工单号（表头）与短码 / 「扫码报工」整块退场（2026-10-26 用户逐字）
    expect(Object.keys(layout)).not.toContain('header')
    expect(Object.keys(layout)).not.toContain('shortCode')
    expect(Object.keys(layout)).not.toContain('qrNote')
    // 行序自上而下（y 单调不减）
    expect(layout.lines.map((line) => line.y)).toEqual([...layout.lines.map((line) => line.y)].sort((a, b) => a - b))
    // 正文字号 = 11pt（31px @203dpi）—— 内容真值不含字号，字号只由 metrics 决定
    expect(layout.lines[0].fontPx).toBe(Math.round((WASH_LABEL_BODY_FONT_PT / 72) * 25.4 * geo.dpmm))
  })

  it('纸面抬头（2026-10-25）：位图通道也画「企业名 + 成品定制」两行居中，且在正文之上；缺企业名 ⇒ 整块不画', () => {
    const withCompany = layoutWashLabel(input({ companyName: '亿家纺织' }), geo, measure)
    // 两行、逐字：企业名（粗体侧、字号更大）+ 固定副标题
    expect(withCompany.company.map((line) => line.text)).toEqual(['亿家纺织', '成品定制'])
    expect(withCompany.company[0].fontPx).toBe(Math.round((WASH_LABEL_COMPANY_FONT_PT / 72) * 25.4 * geo.dpmm))
    expect(withCompany.company[1].fontPx).toBe(
      Math.round((WASH_LABEL_COMPANY_SUBTITLE_FONT_PT / 72) * 25.4 * geo.dpmm),
    )
    expect(withCompany.company[0].fontPx).toBeGreaterThan(withCompany.company[1].fontPx)
    // 居中：x = 纸宽的一半（与系统打印的 text-center 同口径）
    expect(withCompany.company.every((line) => line.x === Math.round(geo.widthPx / 2))).toBe(true)
    // 抬头在正文之上
    expect(withCompany.company[1].y).toBeLessThan(withCompany.lines[0].y)

    const noCompany = layoutWashLabel(input(), geo, measure)
    expect(noCompany.company).toEqual([])
    // 正反对照：没有抬头块 ⇒ 正文从内边距开始（不是空出两行）
    expect(noCompany.lines[0].y).toBe(noCompany.margin)
  })

  it('判据 ③：二维码**不沉底** —— 正文后隔两行、离纸底（虚线）留白（用户 2026-10-26 逐字「二维码不要沉底，跟文字隔两行即可，要离底部虚线留空」）', () => {
    const layout = layoutWashLabel(input(), geo, measure)
    const qr = layout.qr
    if (!qr) throw new Error('有码的输入却没算出二维码位 —— 判据无从取值')
    // 水平居中
    expect(qr.x).toBe(Math.round((geo.widthPx - qr.size) / 2))
    // 竖直：正文最后一行之下**恰好两行**（不是贴纸底）
    const lineStep = lineStepOf(geo.dpmm)
    const lastLine = layout.lines[layout.lines.length - 1]
    expect(qr.y).toBe(lastLine.y + lineStep * (1 + WASH_LABEL_QR_TEXT_GAP_LINES))
    // 离纸的下沿（底部虚线）至少留 WASH_LABEL_BOTTOM_CLEARANCE_MM（**从纸边起算**，与系统打印
    // 的 `padding-bottom: 6mm` 同口径；改回「贴底」或按旧的「内边距 + 6mm = 7.2mm」⇒ 必红）
    expect(qr.y + qr.size).toBeLessThanOrEqual(
      geo.heightPx - Math.round(WASH_LABEL_BOTTOM_CLEARANCE_MM * geo.dpmm),
    )
    // 不越界
    expect(qr.x).toBeGreaterThanOrEqual(0)
    expect(qr.x + qr.size).toBeLessThanOrEqual(geo.widthPx)
    // 80 CSS px = 21.17mm（旧值 45px = 11.9mm ⇒ 明显放大）
    expect(qr.size).toBe(Math.round((80 * 25.4) / 96 * geo.dpmm))
    expect(qr.size).toBeGreaterThan(45 * (25.4 / 96) * geo.dpmm)
  })

  it('无码 ⇒ 不画假码：底部出**同尺寸量级**的虚线占位框（居中）+ 占位文案', () => {
    const layout = layoutWashLabel(input({ qrValue: null, qrPlaceholderHint: '二维码已撤销' }), geo, measure)
    expect(layout.qr).toBeNull()
    const placeholder = layout.qrPlaceholder
    if (!placeholder) throw new Error('无码却没算出占位框 —— 判据无从取值')
    expect(placeholder.rect.x).toBe(Math.round((geo.widthPx - placeholder.rect.size) / 2))
    // 占位框同口径：跟在正文后两行、不贴纸底（与有码时同一套版式）
    const lineStep = lineStepOf(geo.dpmm)
    const lastLine = layout.lines[layout.lines.length - 1]
    expect(placeholder.rect.y).toBe(lastLine.y + lineStep * (1 + WASH_LABEL_QR_TEXT_GAP_LINES))
    expect(placeholder.rect.y + placeholder.rect.size).toBeLessThanOrEqual(
      geo.heightPx - Math.round(WASH_LABEL_BOTTOM_CLEARANCE_MM * geo.dpmm),
    )
    expect(placeholder.lines.map((line) => line.text).join('')).toContain('二维码已撤销')
    // 文案在框内居中（x = 框中心）
    expect(placeholder.lines.every((line) => line.x === placeholder.rect.x + Math.round(placeholder.rect.size / 2))).toBe(
      true,
    )
  })

  it('判据 ④：**装不下只裁文字块** —— 超长行清单被截断；码由正文长度定位但被纸底留白夹住', () => {
    const huge: WashLabelRow[] = Array.from({ length: 60 }, (_, i) => ({
      key: 'remark',
      text: `备注 第${i}行很长的补充说明文字，用来把文字块撑爆`,
    }))
    const layout = layoutWashLabel(input({ rows: huge }), geo, measure)
    const lineStep = lineStepOf(geo.dpmm)
    const bottomLimit = geo.heightPx - Math.round(WASH_LABEL_BOTTOM_CLEARANCE_MM * geo.dpmm)
    // 最后一行仍在二维码之上（没被挤出纸外），且码与末行之间仍有**两行**空位
    const lastLine = layout.lines[layout.lines.length - 1]
    expect(lastLine.y).toBeLessThan(layout.qr!.y)
    expect(layout.qr!.y - (lastLine.y + lineStep)).toBeGreaterThanOrEqual(lineStep * WASH_LABEL_QR_TEXT_GAP_LINES)
    // 大量行被裁 ⇒ 但也确实画了东西（不是空断言）
    expect(layout.lines.length).toBeGreaterThan(5)
    expect(layout.lines.length).toBeLessThan(huge.length)
    // 码永不被文字挤出纸底留白（改回「贴底」⇒ 必红）
    expect(layout.qr!.y + layout.qr!.size).toBeLessThanOrEqual(bottomLimit)
  })

  it('纸宽连内边距都放不下 ⇒ 显式抛错（fail-closed，不静默画一张错纸）', () => {
    expect(() => layoutWashLabel(input(), { dpmm: 8, widthPx: 2, heightPx: 952 }, measure)).toThrow(
      WashLabelLayoutError,
    )
  })
})

describe('wrapText / ellipsize — 折行（正文印全文，issue #7833）', () => {
  it('🔴 缺省**不设行数预算** ⇒ 折行印全文（末行不省略）—— 正文通道走的就是这条', () => {
    // 6 字、行预算 12px（2 字/行）⇒ 3 行**全部**折出，末行不得出现省略号
    expect(wrapText('一二三四五六', 12, 10, measure)).toEqual(['一二', '三四', '五六'])
    expect(wrapText('一二三四五六', 12, 10, measure).join('')).toBe('一二三四五六')
    expect(wrapText('一二三四五六', 12, 10, measure).some((line) => line.includes('…'))).toBe(false)
  })

  it('显式给预算（只用于占位框文案这类非正文用途）⇒ 末行以省略号收尾', () => {
    expect(wrapText('一二三四', 100, 10, measure, 3)).toEqual(['一二三四'])
    // 4 字 × 6px = 24px/行预算 12px ⇒ 每行 2 字
    expect(wrapText('一二三四', 12, 10, measure, 3)).toEqual(['一二', '三四'])
    // 预算 2 行 ⇒ 余下的进最后一行并以省略号收尾（看得见的截断，不静默吞字）
    expect(wrapText('一二三四五六', 12, 10, measure, 2)).toEqual(['一二', '三…'])
    expect(wrapText('   ', 12, 10, measure, 2)).toEqual([])
  })

  it('ellipsize：放得下就原样返回；放不下逐字退到省略号', () => {
    expect(ellipsize('一二', 100, 10, measure)).toBe('一二')
    expect(ellipsize('一二三四', 12, 10, measure)).toBe('一…')
  })
})

/** 记录调用面的假 ctx（真 canvas 在 jsdom 里没有） */
function fakeContext() {
  const calls: string[] = []
  const ctx = {
    fillStyle: '',
    strokeStyle: '',
    font: '',
    textAlign: 'left' as CanvasTextAlign,
    textBaseline: 'top' as CanvasTextBaseline,
    lineWidth: 1,
    fillRect: (x: number, y: number, w: number, h: number) => calls.push(`fillRect:${x},${y},${w},${h}`),
    strokeRect: (x: number, y: number, w: number, h: number) => calls.push(`strokeRect:${x},${y},${w},${h}`),
    fillText: (text: string, x: number, y: number) => calls.push(`fillText:${text}@${x},${y}`),
    drawImage: (_image: CanvasImageSource, x: number, y: number, w: number, h: number) =>
      calls.push(`drawImage:${x},${y},${w},${h}`),
    setLineDash: (segments: number[]) => calls.push(`setLineDash:${segments.join(',')}`),
  }
  return { ctx, calls }
}

describe('paintWashLabel — 只照单绘制（判据 ⑤）', () => {
  const geo = resolveLabelGeometry(null)

  it('先铺白底（不铺 = 整幅反色废纸），再把二维码画在算好的位置上', () => {
    const layout = layoutWashLabel(input(), geo, measure)
    const { ctx, calls } = fakeContext()
    paintWashLabel(ctx, layout, {} as CanvasImageSource)
    expect(calls[0]).toBe(`fillRect:0,0,${geo.widthPx},${geo.heightPx}`)
    expect(calls).toContain(`drawImage:${layout.qr!.x},${layout.qr!.y},${layout.qr!.size},${layout.qr!.size}`)
    // 文字都画了
    const painted = calls.filter((call) => call.startsWith('fillText:')).join('|')
    for (const row of ROWS) expect(painted).toContain(row.text.slice(0, 4))
    // 不再画短码 / 「扫码报工」
    expect(painted).not.toContain('扫码报工')
    expect(painted).not.toContain('7Q2M4K8P')
    // 🔴 底部虚线（issue #7833「头尾加下虚线」→ issue #7839「顶部虚线移除掉」）：
    // 只在纸的**下沿**画一串短划（fillRect 段）；顶部除整幅白底外**没有**短划
    const dashCalls = calls.filter((call) => call.startsWith('fillRect:') && call.endsWith(',2'))
    expect(dashCalls.length).toBeGreaterThan(10)
    // 逐段都在**下沿**（y = 纸高 − 线粗）；最后一段因取整可能窄于划长，故按 y 判而不按宽度判
    const dashYs = dashCalls.map((call) => Number(call.split(',')[1]))
    expect(dashYs.every((y) => y === geo.heightPx - 2)).toBe(true)
    const topCalls = calls.filter((call) => call.startsWith('fillRect:') && call.split(',')[1] === '0')
    expect(topCalls).toEqual([`fillRect:0,0,${geo.widthPx},${geo.heightPx}`])
  })

  it('无码位图 ⇒ 画虚线占位框（不静默留白，也不画假码）', () => {
    const layout = layoutWashLabel(input({ qrValue: null }), geo, measure)
    const { ctx, calls } = fakeContext()
    paintWashLabel(ctx, layout, null)
    expect(calls).toContain('setLineDash:2,2')
    expect(calls.some((call) => call.startsWith('strokeRect:'))).toBe(true)
    expect(calls.some((call) => call.startsWith('drawImage:'))).toBe(false)
  })
})
