// case_ids: BM-012
/**
 * 入库标签 **30×40mm 版面**判据（issue #5052 P3 / CP-1；设计 §7.1，验收判据 6 / 8）
 *
 * | # | 判据 | 红证（怎么让它单独变红） |
 * |---|---|---|
 * | C1 | **缺码不画假码**：短码缺失 / 脏码 ⇒ 不画二维码 + 纸面可见标注 | 画一个占位二维码 ⇒ 红 |
 * | C2 | **长名截断必须可见**：超宽 ⇒ 省略号 + `truncated` + `warnings` | 静默裁切（不带省略号）⇒ 红 |
 * | C3 | 全部绘制在**版心**内（1:1 不缩放不裁切的前提） | 画到纸宽之外 ⇒ 红 |
 * | C4 | 二维码按**整数倍点阵**（非整数倍重采样会把码糊掉） | `cellPx` 取小数 ⇒ 红 |
 * | C5 | 缺字段不编造（品名缺失时给的是「未填品名」标注，不是编一个名字） | — |
 *
 * ⚠️ 本文件**不写 240 / 320 字面量**（那会让「单一真值」守卫多一处语料）：尺寸一律从
 * `inboundLabelGeometry()` 取。
 */
import { layoutInboundLabel, estimateTextWidth, fitTextVisible, MISSING_CODE_TEXT } from '../src/utils/inbound/labelLayout'
import { renderInboundLabel, paintInboundLabel, type LabelCanvasContextLike } from '../src/utils/inbound/labelCanvas'
import { inboundLabelGeometry } from '../src/utils/inbound/truth'

const GEOMETRY = inboundLabelGeometry()

const FULL_VIEW = {
  shortCode: 'ABCD2345',
  inboundNo: 'RK-20260926-0001',
  productCode: 'MG-1001',
  skuCode: 'MG-1001-01-28',
  productName: '遮光布',
  colorName: '米白',
  doorWidth: '280cm',
  quantity: '60.5',
  dyeLot: 'D2311',
  batchNo: 'PC-20260926-0001',
}

/** 假 2d 上下文（jsdom 没有真 canvas；判据只关心「画了什么」） */
function fakeContext() {
  const calls: { kind: 'rect' | 'text'; args: any[]; font?: string }[] = []
  const ctx: LabelCanvasContextLike = {
    fillStyle: '',
    font: '',
    textBaseline: '',
    fillRect: (x, y, w, h) => calls.push({ kind: 'rect', args: [x, y, w, h] }),
    fillText: (text, x, y) => calls.push({ kind: 'text', args: [text, x, y], font: ctx.font }),
    getImageData: (x, y, w, h) => ({ data: new Uint8ClampedArray(w * h * 4), width: w, height: h }),
  }
  return { ctx, calls }
}

function fakeCanvasFactory() {
  return (widthPx: number, heightPx: number) => {
    const { ctx, calls } = fakeContext()
    return {
      width: widthPx,
      height: heightPx,
      getContext: () => ctx,
      // 便于断言
      __calls: calls,
    } as any
  }
}

describe('入库标签版面（50×80mm，issue #7820）', () => {
  it('C1 正常短码 ⇒ 画出二维码，且码内容 = https://app.migaozn.com/i/<短码>', () => {
    const plan = layoutInboundLabel(FULL_VIEW)
    expect(plan.qr?.payload).toBe('https://app.migaozn.com/i/ABCD2345')
    expect((plan.qr?.matrix || []).filter((v) => v === 1).length).toBeGreaterThan(0)
    expect(plan.codeText).toBe('ABCD2345')
    expect(plan.warnings.filter((w) => w.includes('未绘制二维码'))).toEqual([])
  })

  it('C1 🔴 缺码不画假码：短码缺失 ⇒ qr=null + 纸面可见标注 + warning', () => {
    const plan = layoutInboundLabel({ ...FULL_VIEW, shortCode: null })
    expect(plan.qr).toBeNull()
    expect(plan.codeText).toBe(MISSING_CODE_TEXT)
    expect(plan.warnings.join('\n')).toContain('未绘制二维码')
    // 纸面上真的写了标注（不是只把字段置空）
    const texts = plan.ops.filter((op) => op.kind === 'text').map((op: any) => op.text)
    expect(texts).toContain(MISSING_CODE_TEXT)
  })

  it('C1 🔴 脏码（含 I/L/O/U 或长度不对）与缺失同处置 —— 不许拼出一个"能扫但错的"码', () => {
    for (const dirty of ['ABCDI234', 'ABCDO234', 'ABCD234', 'ABCD23456', '   ', '中文短码']) {
      const plan = layoutInboundLabel({ ...FULL_VIEW, shortCode: dirty })
      expect(plan.qr).toBeNull()
      expect(plan.codeText).toBe(MISSING_CODE_TEXT)
    }
  })

  it('C4 二维码按整数倍点阵画（重采样会把码糊掉）', () => {
    const plan = layoutInboundLabel(FULL_VIEW)
    const qr = plan.qr!
    expect(Number.isInteger(qr.cellPx)).toBe(true)
    expect(qr.cellPx).toBeGreaterThanOrEqual(1)
    expect(qr.sizePx).toBe(qr.moduleCount * qr.cellPx)
    expect(qr.matrix.length).toBe(qr.moduleCount * qr.moduleCount)
    // 点阵里确实有黑模块（防"画了个空的方框"）
    expect(qr.matrix.filter((v) => v === 1).length).toBeGreaterThan(0)
  })

  it('C2 🔴 色号不遮挡（用户 2026-10-26 裁定）：全宽 + 两行内放下 ⇒ 一字不截、不出省略号', () => {
    const longColor = '2659-04 绵绵奶咖 深灰蓝拼色'
    const plan = layoutInboundLabel({ ...FULL_VIEW, colorName: longColor })
    const colorOps: any[] = plan.ops.filter((op) => op.kind === 'text' && /^色号/.test(op.text))
    expect(colorOps.length).toBeGreaterThan(0)
    // 多行拼回来必须**一字不少**（旧形态：右列半版心 ⇒ `2659-04 绵绵奶咖…`）
    expect(colorOps.map((op) => op.text).join(' ')).toContain('绵绵奶咖')
    expect(colorOps.some((op) => op.text.endsWith('…'))).toBe(false)
    expect(plan.warnings.join('\n')).not.toContain('色号超宽')
    // 红证：把色号按旧的「半版心」宽度排（textLeftRatio 0.5）⇒ 这段文字必进省略号分支
  })

  it('C6 顶部不再印品名（用户 2026-10-26 逐字「移除顶部的商品名」）', () => {
    const plan = layoutInboundLabel({ ...FULL_VIEW, productName: '遮光布' })
    const texts = plan.ops.filter((op) => op.kind === 'text').map((op: any) => op.text)
    expect(texts.some((t: string) => t.includes('遮光布'))).toBe(false)
    expect(texts.some((t: string) => t.includes('品名'))).toBe(false)
    // 纸面第一行 = 货号（最能把这张纸对上实物的一行）
    expect(texts[0]).toContain('货号')
  })

  it('C7 增加入库日期（服务端 inboundDate 原样印；缺字段整行不画）', () => {
    const withDate = layoutInboundLabel({ ...FULL_VIEW, inboundDate: '2026-10-25' })
    const texts = withDate.ops.filter((op) => op.kind === 'text').map((op: any) => op.text)
    expect(texts).toContain('入库 2026-10-25')
    const noDate = layoutInboundLabel({ ...FULL_VIEW, inboundDate: null })
    const noTexts = noDate.ops.filter((op) => op.kind === 'text').map((op: any) => op.text)
    expect(noTexts.some((t: string) => t.startsWith('入库'))).toBe(false)
  })

  it('C8 二维码在**底部**、水平居中、下方不再印短码，且留 3mm 安全白边（用户 2026-10-26 / 2026-11-01 裁定）', () => {
    const plan = layoutInboundLabel(FULL_VIEW)
    const qr = plan.qr!
    expect(qr.y).toBeGreaterThan(plan.heightPx * 0.5)
    // 居中：左右留白差 ≤ 2px（取整误差）
    expect(Math.abs(qr.x - (plan.widthPx - qr.x - qr.sizePx))).toBeLessThanOrEqual(2)

    // 所有文字都在二维码**上方**（码区独占下半区）
    const textOps: any[] = plan.ops.filter((op) => op.kind === 'text')
    for (const op of textOps) expect(op.y).toBeLessThan(qr.y)

    // 🔴 2026-11-01 用户裁定：「移除二维码下面的短码」—— 纸面不再有那行字
    const codeOp = plan.ops.find((op) => op.kind === 'text' && op.text === plan.codeText)
    expect(codeOp).toBeUndefined()

    // 🔴 码侧白边 ≥ 10mm（介质矩阵 dotsPerMm × 10）：5mm 真机仍被切（2026-11-01 16:16 用户复看）
    const bottomGapPx = plan.heightPx - (qr.y + qr.sizePx)
    expect(bottomGapPx).toBeGreaterThanOrEqual(80)
    // 码不要占满版心宽（用户 2026-11-01：太大了、缩小再看）—— 上限 ≈40%（≈19mm）
    expect(qr.sizePx).toBeLessThanOrEqual(Math.round(plan.widthPx * 0.4))
  })

  it('C2 🔴 截断判定本身要能红：静默裁切（截了但不加省略号）不算数', () => {
    // 与「可见截断」同口径的判定器：截断了就必须带省略号
    const checker = (
      render: (text: string, maxPx: number, fontPx: number) => { text: string; truncated: boolean },
      text: string,
      maxPx: number,
      fontPx: number,
    ): boolean => {
      const out = render(text, maxPx, fontPx)
      if (!out.truncated) return estimateTextWidth(out.text, fontPx) <= maxPx
      return out.text.endsWith('…') && estimateTextWidth(out.text, fontPx) <= maxPx
    }
    const longName = '超长品名的遮光涂层印花布（工程单专用）'.repeat(3)
    expect(checker(fitTextVisible, longName, 200, 20)).toBe(true)
    // 注入：截断但不带省略号（静默裁切）⇒ 判定器必须判红
    const silent = (text: string, maxPx: number, fontPx: number) => {
      let out = ''
      for (const ch of String(text)) {
        if (estimateTextWidth(out + ch, fontPx) > maxPx) break
        out += ch
      }
      return { text: out, truncated: true }
    }
    expect(checker(silent, longName, 200, 20)).toBe(false)
  })

  it('C3 全部绘制落在版心内（1:1 不缩放不裁切）', () => {
    const plan = layoutInboundLabel({ ...FULL_VIEW, productName: '超长品名的遮光涂层印花布'.repeat(4) })
    expect(plan.widthPx).toBe(GEOMETRY.canvasWidthPx)
    expect(plan.heightPx).toBe(GEOMETRY.canvasHeightPx)
    const overflow: string[] = []
    for (const op of plan.ops) {
      if (op.kind === 'rect') {
        if (op.x < 0 || op.y < 0 || op.x + op.w > plan.widthPx || op.y + op.h > plan.heightPx) {
          overflow.push(`rect ${op.x},${op.y},${op.w},${op.h}`)
        }
        continue
      }
      if (op.x < 0 || op.y < 0 || op.y + op.fontPx > plan.heightPx) overflow.push(`text@${op.x},${op.y}`)
      if (estimateTextWidth(op.text, op.fontPx) > op.maxWidthPx + 0.01) overflow.push(`text 超宽：${op.text}`)
      if (op.x + estimateTextWidth(op.text, op.fontPx) > plan.widthPx) overflow.push(`text 越界：${op.text}`)
    }
    expect(overflow).toEqual([])
    if (plan.qr) {
      expect(plan.qr.x + plan.qr.sizePx).toBeLessThanOrEqual(plan.widthPx)
      expect(plan.qr.y + plan.qr.sizePx).toBeLessThanOrEqual(plan.heightPx)
    }
  })

  it('C5 缺字段不编造：整行不画（而不是印一个假值）', () => {
    const plan = layoutInboundLabel({ shortCode: 'ABCD2345', productName: '遮光布' })
    const texts = plan.ops.filter((op) => op.kind === 'text').map((op: any) => op.text)
    expect(texts.some((t: string) => t.includes('批次'))).toBe(false)
    expect(texts.some((t: string) => t.includes('米数'))).toBe(false)
    // 订单号 / 入库日期都没有时，这两行也不许出现（不编造）
    expect(texts.some((t: string) => t.startsWith('单号'))).toBe(false)
    expect(texts.some((t: string) => t.startsWith('入库'))).toBe(false)
  })

  it('渲染器把计划画到位图上，且位图与版心 1:1（不缩放）', () => {
    const rendered = renderInboundLabel(FULL_VIEW, fakeCanvasFactory())
    expect(rendered.widthPx).toBe(GEOMETRY.canvasWidthPx)
    expect(rendered.heightPx).toBe(GEOMETRY.canvasHeightPx)
    expect(rendered.image.width).toBe(GEOMETRY.canvasWidthPx)
    expect(rendered.image.height).toBe(GEOMETRY.canvasHeightPx)
    const calls: any[] = (rendered.canvas as any).__calls
    // 先铺底，再写文字，最后填二维码模块
    expect(calls[0].kind).toBe('rect')
    expect(calls.filter((c) => c.kind === 'text').length).toBeGreaterThan(3)
    if (rendered.plan.qr) {
      // -2 = 铺底 + 字段区/码区之间的分隔线（都不是二维码模块）
      const rects = calls.filter((c) => c.kind === 'rect').length - 2
      const black = rendered.plan.qr.matrix.filter((v) => v === 1).length
      expect(rects).toBe(black)
    }
  })

  it('画布拿不到 2d 上下文 ⇒ 显式抛错（不静默返回白图当"打出来了"）', () => {
    expect(() => renderInboundLabel(FULL_VIEW, (w, h) => ({ width: w, height: h, getContext: () => null }))).toThrow(
      /2d 上下文/,
    )
  })

  it('paintInboundLabel 对缺码计划不画任何二维码方块', () => {
    const { ctx, calls } = fakeContext()
    paintInboundLabel(ctx, layoutInboundLabel({ ...FULL_VIEW, shortCode: null }))
    const black = calls.filter((c) => c.kind === 'rect').length
    // 只有「铺底 + 缺码占位白框 + 分隔线」三次矩形，没有任何二维码模块
    expect(black).toBe(3)
  })

  it('C9 纸面「货号」印的是**商品货号**，不是 SKU 的规格编码（用户 2026-11-01 裁定）', () => {
    // 🔴 红证：把 `pushRow(\`货号 ${skuCode}\`)` 改回去 ⇒ 本判据必红
    const plan = layoutInboundLabel({ ...FULL_VIEW, productCode: '2659', skuCode: '2659-04-28' } as any)
    const texts = plan.ops.filter((op) => op.kind === 'text').map((op: any) => op.text)
    expect(texts).toContain('货号 2659')
    expect(texts.some((t: string) => t.includes('2659-04-28'))).toBe(false)
  })
})
