// case_ids: PP-011
/**
 * 水洗唛**版面度量 × 组件 CSS** 一致性 + 纸长（内容驱动）判据（issue #7776）——
 * 用户 2026-10-25 逐字「字体太小了，可以把长度延长些，因为长度可以无限长，宁愿长点也要把字体和信息
 * 都呈现出来……打印预览的时候我就发现上下两头留白太多了」。
 *
 * 为什么要有这一条（实测形态，不是假想）：字号与纸长的**标称值**在三个地方各存在一份 ——
 * ① `lib/label-print/wash-label-metrics.ts`（TS：画布通道 + 纸长计算 + 打印通道读它）；
 * ② `components/production/TaskCardPrint.tsx` 里那段 CSS / Tailwind 字号（系统打印）；
 * ③ 介质矩阵 `label-50x70`（最短纸长）。
 * 改一处不改另一处**不会报错**，只会让两边画得不一样 / 纸长算错。⇒ 本文件**解析组件源码**逐值比对：
 * 谁单方面改字号/内边距/二维码/最短纸长 ⇒ 必红。
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { printLengthRangeMm, printPageRuleForLength } from '@/lib/print-media'
import {
  WASH_LABEL_BODY_FONT_PT,
  WASH_LABEL_COMPANY_FONT_PT,
  WASH_LABEL_COMPANY_SUBTITLE_FONT_PT,
  WASH_LABEL_HEADER_FONT_PT,
  WASH_LABEL_LINE_HEIGHT,
  WASH_LABEL_MAX_LENGTH_MM,
  WASH_LABEL_MIN_LENGTH_MM,
  WASH_LABEL_PADDING_MM,
  WASH_LABEL_QR_CSS_PX,
  WASH_LABEL_QR_PLACEHOLDER_MM,
  WASH_LABEL_SHORT_CODE_FONT_PT,
  estimateLineCount,
  washLabelBatchLengthMm,
  washLabelContentHeightMm,
  washLabelLengthMm,
} from '@/lib/label-print/wash-label-metrics'

const COMPONENT = resolve(process.cwd(), 'src/components/production/TaskCardPrint.tsx')
const source = readFileSync(COMPONENT, 'utf-8')

/** 从组件源码里取 `.task-card-label { … }` 那段 CSS */
function labelCss(): string {
  const match = /\.task-card-label\s*\{([^}]*)\}/.exec(source)
  expect(match, '找不到 `.task-card-label { … }` —— 判据无从取值（不得静默通过）').not.toBeNull()
  return match![1]
}

const css = labelCss()

describe('水洗唛版面度量：TS 单一真值 ⇄ 组件 CSS（改一处不改另一处 ⇒ 红）', () => {
  it('内边距 / 行高 / 正文字号：CSS 与 metrics 逐值一致', () => {
    expect(css).toContain(`padding: ${WASH_LABEL_PADDING_MM}mm`)
    expect(css).toContain(`line-height: ${WASH_LABEL_LINE_HEIGHT}`)
    expect(css).toContain(`font-size: ${WASH_LABEL_BODY_FONT_PT}pt`)
  })

  it('纸宽固定 50mm（宽度不是"可调项"）；纸型尺寸由介质矩阵给', () => {
    expect(css).toContain('width: 50mm')
    // 高度不写死在 CSS 里当"实际纸长"：CSS 的 70mm 只是**最短**纸长，实际高度由行内 style 给
    expect(css).toContain(`height: ${WASH_LABEL_MIN_LENGTH_MM}mm`)
    expect(source).toContain('style={{ height: `${labelLengthMm}mm` }}')
  })

  it('抬头 / 加工单号 / 短码 / 二维码的字号与边长逐值一致', () => {
    expect(source).toContain(`text-[${WASH_LABEL_COMPANY_FONT_PT}pt] font-bold`)
    expect(source).toContain(`text-[${WASH_LABEL_COMPANY_SUBTITLE_FONT_PT}pt]`)
    expect(source).toContain(`text-[${WASH_LABEL_HEADER_FONT_PT}pt] font-bold`)
    expect(source).toContain(`text-[${WASH_LABEL_SHORT_CODE_FONT_PT}pt] font-bold`)
    expect(source).toContain(`size={${WASH_LABEL_QR_CSS_PX}}`)
    expect(source).toContain(`h-[${WASH_LABEL_QR_PLACEHOLDER_MM}mm] w-[${WASH_LABEL_QR_PLACEHOLDER_MM}mm]`)
  })

  it('最短纸长 == 介质矩阵的 pageBoxMm.heightMm（不写第二份纸型）', () => {
    expect(printLengthRangeMm('label-50x70')).toEqual({
      minMm: WASH_LABEL_MIN_LENGTH_MM,
      maxMm: WASH_LABEL_MAX_LENGTH_MM,
    })
    expect(printPageRuleForLength('label-50x70', 82)).toBe('@page { size: 50mm 82mm; margin: 0; }')
    // 夹在区间内：低于下限 / 高于上限都不许把纸打成别的尺寸
    expect(printPageRuleForLength('label-50x70', 10)).toBe('@page { size: 50mm 70mm; margin: 0; }')
    expect(printPageRuleForLength('label-50x70', 999)).toBe('@page { size: 50mm 150mm; margin: 0; }')
  })

  it('固定纸型的介质不许用动态纸长（fail-closed，不静默忽略）', () => {
    expect(() => printPageRuleForLength('a4', 100)).toThrow(/没有登记 lengthMm/)
  })
})

describe('纸长 = 内容高度（用户：「上下两头留白太多了」）', () => {
  /** 一张常规洗水唛（12 行正文、其中 3 行会折成 2 行） */
  const typical = [
    { text: '客户 王丽娜', maxLines: 1 },
    { text: '第 1 套 / 共 2 套', maxLines: 1 },
    { text: '部位 布帘', maxLines: 1 },
    { text: '颜色 米白', maxLines: 1 },
    { text: '门幅 2.8米', maxLines: 1 },
    { text: '用料 6.3米', maxLines: 1 },
    { text: '宽高 3×2.75米', maxLines: 1 },
    { text: '加工方式 单开 · 韩褶 · 定宽买高 · 定型', maxLines: 2 },
    { text: '订单 DD-20261025-0071', maxLines: 1 },
    { text: '交期 2026-11-05', maxLines: 1 },
    { text: '特殊选项 加logo条、防翘扣', maxLines: 2 },
    { text: '备注 客户要求上门安装，提前一天联系', maxLines: 2 },
  ]

  it('折行估算：CJK 1em / ASCII 0.6em，逐字贪心填行（与浏览器断行同量级）', () => {
    // 版心 47.6mm、9pt ⇒ 每字 3.175mm ⇒ 14 个汉字一行
    expect(estimateLineCount('客'.repeat(14), 47.6, 9, 2)).toBe(1)
    expect(estimateLineCount('客'.repeat(15), 47.6, 9, 2)).toBe(2)
    // 行数预算封顶（CSS `line-clamp-N`）
    expect(estimateLineCount('客'.repeat(60), 47.6, 9, 2)).toBe(2)
  })

  it('纸长 ≥ 内容高（绝不裁内容），且随内容单调增长', () => {
    const content = washLabelContentHeightMm({ rows: typical, hasCompany: true, hasQr: true })
    const length = washLabelLengthMm({ rows: typical, hasCompany: true, hasQr: true })
    expect(length).toBeGreaterThanOrEqual(Math.ceil(content))
    expect(length).toBeGreaterThan(WASH_LABEL_MIN_LENGTH_MM)

    const more = washLabelLengthMm({
      rows: [...typical, { text: '备注 再加一行很长的补充说明，用来验证纸长会跟着内容一起长', maxLines: 2 }],
      hasCompany: true,
      hasQr: true,
    })
    expect(more).toBeGreaterThanOrEqual(length)
  })

  it('短内容单不短于下限；超长内容单夹在上限（纸不可能无限长）', () => {
    expect(washLabelLengthMm({ rows: [{ text: '客户 王', maxLines: 1 }], hasCompany: false, hasQr: true })).toBe(
      WASH_LABEL_MIN_LENGTH_MM,
    )
    const huge = Array.from({ length: 80 }, (_, i) => ({ text: `备注 第${i}行很长的补充说明文字`, maxLines: 2 }))
    expect(washLabelLengthMm({ rows: huge, hasCompany: true, hasQr: true })).toBe(WASH_LABEL_MAX_LENGTH_MM)
  })

  it('一批标签：统一纸长 = 该批最大值（一次打印任务每页必须同高）', () => {
    const short = { rows: [{ text: '客户 王', maxLines: 1 }], hasCompany: false, hasQr: true }
    const long = { rows: typical, hasCompany: true, hasQr: true }
    expect(washLabelBatchLengthMm([short, long])).toBe(washLabelLengthMm(long))
    expect(washLabelBatchLengthMm([short])).toBe(WASH_LABEL_MIN_LENGTH_MM)
    // 空批（0 个部位）⇒ 不炸，给下限
    expect(washLabelBatchLengthMm([])).toBe(WASH_LABEL_MIN_LENGTH_MM)
  })
})
