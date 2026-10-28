// case_ids: PP-011
/**
 * 水洗唛**版面度量 × 组件 CSS** 一致性 + 固定纸型判据（issue #7776 建立 → **#7816 改判**）。
 *
 * 为什么要有这一条（实测形态，不是假想）：字号 / 内边距 / 二维码尺寸在**三个地方**各存在一份 ——
 * ① `lib/label-print/wash-label-metrics.ts`（TS：画布通道 + 打印通道读它）；
 * ② `components/production/TaskCardPrint.tsx` 里那段 CSS / Tailwind 字号（系统打印）；
 * ③ 介质矩阵 `label-50x140`（固定纸型 50mm × 140mm）。
 * 改一处不改另一处**不会报错**，只会让两条通道画得不一样。⇒ 本文件**解析组件源码**逐值比对。
 *
 * 2026-10-26（issue #7816）改判：纸长**不再按内容撑开**（作废 #7776 的动态纸长），
 * 正文 9pt → 12pt、二维码 45 → 80 CSS px、短码退场 ⇒ 本文件同步删掉动态纸长那几条判据，
 * 换成「固定纸型 + 新字号 + 二维码居中」的可红断言。
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { printDotGeometry, printPageBoxMm, printPageRule } from '@/lib/print-media'
import {
  WASH_LABEL_BODY_FONT_PT,
  WASH_LABEL_BOTTOM_CLEARANCE_MM,
  WASH_LABEL_COMPANY_FONT_PT,
  WASH_LABEL_COMPANY_SUBTITLE_FONT_PT,
  WASH_LABEL_BLOCK_GAP_MM,
  WASH_LABEL_EMPHASIS_ROW_KEYS,
  WASH_LABEL_LINE_HEIGHT,
  WASH_LABEL_PADDING_MM,
  WASH_LABEL_QR_CSS_PX,
  WASH_LABEL_QR_PLACEHOLDER_FONT_PT,
  WASH_LABEL_QR_PLACEHOLDER_MM,
  WASH_LABEL_TOP_BLANK_MM,
} from '@/lib/label-print/wash-label-metrics'

const COMPONENT = resolve(process.cwd(), 'src/components/production/TaskCardPrint.tsx')
const source = readFileSync(COMPONENT, 'utf-8')

/** 从组件源码里取 `.task-card-label { … }` 那段 CSS */
function labelCss(): string {
  const match = /\.task-card-label\s*\{([^}]*)\}/.exec(source)
  // 取不到就**抛**（不用 `not.toBeNull()` 这类弱断言：门禁会判凑数断言）；
  // 这段 CSS 是纸面几何的落点，取不到 = 判据无从取值，必须响而不是静默通过
  if (!match?.[1]) throw new Error('找不到 `.task-card-label { … }` —— 判据无从取值（不得静默通过）')
  return match[1]
}

const css = labelCss()

describe('水洗唛版面度量：TS 单一真值 ⇄ 组件 CSS（改一处不改另一处 ⇒ 红）', () => {
  it('内边距 / 顶部留白 / 行高 / 正文字号：CSS 与 metrics 逐值一致', () => {
    // 🔴 上内边距 = 顶部留白（2026-10-28「顶部需要让最顶端的字体上面留白15」）、
    //    下内边距 = 码与底部虚线的净空（同批「多的30要添加到顶部和底部虚线下处各15」）
    //    —— 与画布通道读**同一组**常量，两条通道不会各写一份
    expect(css).toContain(
      `padding: ${WASH_LABEL_TOP_BLANK_MM}mm ${WASH_LABEL_PADDING_MM}mm ${WASH_LABEL_BOTTOM_CLEARANCE_MM}mm`,
    )
    // 两个 15mm 是**同一批裁定**的两个 15：改一个不改另一个 ⇒ 必红
    expect(WASH_LABEL_TOP_BLANK_MM).toBe(15)
    expect(WASH_LABEL_BOTTOM_CLEARANCE_MM).toBe(15)
    expect(css).toContain(`line-height: ${WASH_LABEL_LINE_HEIGHT}`)
    expect(css).toContain(`font-size: ${WASH_LABEL_BODY_FONT_PT}pt`)
    // 正向锚：字体确实比上一版（9pt）大 —— 用户 2026-10-26「字体还是太小，可以再大一点」
    expect(WASH_LABEL_BODY_FONT_PT).toBeGreaterThan(9)
  })

  it('固定纸型 50mm × 140mm：CSS 与介质矩阵逐值一致（issue #7960）', () => {
    expect(css).toContain('width: 50mm')
    // 纸长**写死**在 CSS 里（不再有行内 style 覆盖）—— 纸型是固定的，不是按内容撑开
    expect(css).toContain('height: 140mm')
    expect(source).not.toContain('style={{ height:')
    // 唯一纸型写法：printPageRule('label-50x140')，不许自写 @page 字面量
    expect(source).toContain("printPageRule('label-50x140')")
    expect(source).not.toMatch(/@page\s*\{\s*size:/)
    expect(printPageRule('label-50x140')).toBe('@page { size: 50mm 140mm; margin: 0; }')
    expect(printPageBoxMm('label-50x140')).toEqual({ widthMm: 50, heightMm: 140 })
    // 点阵侧同一份纸：140mm × 8 dots/mm = 1120px（直连通道的画布高度）
    expect(printDotGeometry('label-50x140').heightPx).toBe(1120)
  })

  it('🔴 加工项 = **加黑加粗**（两条通道同读一份常量；一方加粗一方不加 ⇒ 红；issue #7987）', () => {
    expect(WASH_LABEL_EMPHASIS_ROW_KEYS).toEqual(['craft'])
    // 系统打印：组件按该常量加 `font-bold`（写死行名 = 第二份真值 ⇒ 下面这条必红）
    expect(source).toContain("WASH_LABEL_EMPHASIS_ROW_KEYS.includes(row.key) && 'font-bold'")
    // 位图通道：同读该常量，绘制时加 `bold ` 字体前缀
    const bitmap = readFileSync(resolve(process.cwd(), 'src/lib/label-print/wash-label.ts'), 'utf-8')
    expect(bitmap).toContain('LABEL_EMPHASIS_ROW_KEYS')
    expect(bitmap).toContain("line.bold ? 'bold ' : ''")
  })

  it('抬头 / 二维码 / 占位框的字号与边长逐值一致', () => {
    expect(source).toContain(`text-[${WASH_LABEL_COMPANY_FONT_PT}pt] font-bold`)
    expect(source).toContain(`text-[${WASH_LABEL_COMPANY_SUBTITLE_FONT_PT}pt]`)
    expect(source).toContain(`size={${WASH_LABEL_QR_CSS_PX}}`)
    expect(source).toContain(`h-[${WASH_LABEL_QR_PLACEHOLDER_MM}mm] w-[${WASH_LABEL_QR_PLACEHOLDER_MM}mm]`)
    expect(source).toContain(`text-[${WASH_LABEL_QR_PLACEHOLDER_FONT_PT}pt]`)
    // 二维码 80 CSS px = 21.17mm（用户「二维码可以放大一点」；旧值 45px）
    expect(WASH_LABEL_QR_CSS_PX).toBe(80)
  })

  it('二维码**紧挨正文**（只隔一个块距）且**不沉底**（离底部虚线 15mm）；「扫码报工」与短码文字已退场', () => {
    // 二维码行 = `mt-[<一个块距 mm>] … justify-center` —— 2026-10-28「二维码紧挨文字排版，当前留白太多」
    // （旧口径是「隔两行 9.31mm」，那 ≈9mm 正是纸长能从 150mm 收到 140mm 的来源）
    const gapMm = Number(WASH_LABEL_BLOCK_GAP_MM.toFixed(2))
    const qrRow = `mt-[${gapMm}mm] flex shrink-0 items-center justify-center`
    if (!source.includes(qrRow)) throw new Error(`找不到「二维码行 = ${qrRow}」—— 判据无从取值`)
    // 🔴 反向护栏：正文块**不得**再 `flex-1`（那会把码顶到纸底 = 用户说的「二维码沉底」）
    expect(source).not.toMatch(/min-h-0 flex-1 overflow-hidden/)
    // 🔴 反向护栏：不得再出现「两行」那个 9.31mm 的间距（改回去 ⇒ 纸长又得变长）
    expect(source).not.toContain('mt-[9.31mm]')
    // 纸底（底部虚线）之上必须留白 —— 2026-10-28 由 6mm 抬到 15mm（「底部…各15」）
    expect(WASH_LABEL_BOTTOM_CLEARANCE_MM).toBe(15)
    // 断言打在 **JSX 文本节点**上（文件头注释里会提到这个词，用裸子串会假红）
    expect(source).not.toMatch(/>\s*扫码报工\s*</)
    expect(source).not.toContain('task-card-label-short-code')
  })
})
