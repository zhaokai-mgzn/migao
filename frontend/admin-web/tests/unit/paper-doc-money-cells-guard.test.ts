// case_ids: UI-053
/**
 * 类级元守卫（issue #7716）：**纸面同一行内，同一个金额表达式不得占两个金额格**。
 *
 * ## 病理（用户 2026-10-25 截图）
 *
 * 报价单加工费行印成 `数量 7.3 / 单价 51.10 / 小计 51.10` —— 「单价」格里塞的是**总额**
 * （`formatAmount(processingFee)` 在 `QuotationDoc` 的同一个 `<tr>` 里连写两遍，自 6e12b2878a 起）。
 * 客户/商家照纸面核账时，单价那一格是**没被任何人读过的数**：它既不是组合价（7.00 元/米），
 * 也不满足「单价 × 数量 = 小计」。同类形态（任何「总额冒充单价」）在其它单据上一样看不见。
 *
 * ## 判据（两条，都在本文件里现取）
 *
 * | # | 判什么 | 回归时会**怎么红** |
 * |---|---|---|
 * | 1 | **现取为 0**：`SCOPE`（打印单据族，复用 `scripts/print-doc-zero-fallback-scan.mjs` 的同一份清单）里每份单据的每个 `<tr>`，`formatAmount(...)` / `formatMoney(...)` 的实参不得重复 | 报出 `文件::第 N 个 <tr>::表达式` + 可复制命令；修法 = 单价格换成真正的单价来源 |
 * | 2 | **判别力自证**（注入式，内存源码）：坏形态（同一行两个 `formatAmount(processingFee)`）必红；好形态（单价 / 小计各取各的式子）不红；**注释里的反例**不红 | 判据退化 / 被自己的文档喂红 ⇒ 红 |
 *
 * ## 边界（照实登记，别读成「全覆盖」）
 *
 * - 只认**纸面金额格式化入口**（`formatAmount` / `formatMoney`）的实参；裸表达式
 *   （`{processingFee}`、`¥{x}`、`toLocaleString()` 直调）不在射程 —— 那半边由各单据的
 *   **实例判据**（真渲染 + 读纸面格子，如 `QuotationDoc.test.tsx` 的 `feeRowCells()`）承担。
 * - 判的是**源码文本形态**，不是运行值：单价与小计**恰好相等**（数量 = 1）是合法形态，
 *   本判据不会因此误红（好形态对照里钉住了这一点）。
 * - 它判「两个格子印了同一个数」，**判不了**「单价取的字段在业务上对不对」——
 *   后者属取价侧（`processingFeeDetail` / `ProcessingFeeCalculator`）的口径。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { SCOPE, stripTsComments } from '../../scripts/print-doc-zero-fallback-scan.mjs'

/** 纸面金额格式化入口（与各单据实际用的那两把尺子一致） */
const MONEY_CALL = /format(?:Amount|Money)\s*\(/g

/**
 * 一个 `<tr>` 源码里各**金额格**的表达式（按出现顺序，已归一空白）。
 *
 * 实参用**括号配对**截取，不用正则偷懒：`formatAmount(paperLineSubtotal(item))` 这类嵌套实参
 * 用 `[^)]*` 会截成 `paperLineSubtotal(item`（两处不同实参被截成同一个 ⇒ 假红）。
 */
export function moneyCellExpressions(rowSource: string): string[] {
  const exprs: string[] = []
  MONEY_CALL.lastIndex = 0
  let match = MONEY_CALL.exec(rowSource)
  while (match) {
    const open = match.index + match[0].length - 1
    let depth = 1
    let cursor = open + 1
    while (cursor < rowSource.length && depth > 0) {
      const ch = rowSource[cursor]
      if (ch === '(') depth += 1
      else if (ch === ')') depth -= 1
      cursor += 1
    }
    if (depth !== 0) throw new Error('源码里的 formatAmount( / formatMoney( 括号不配对 —— 判据拒绝在半截输入上给结论')
    exprs.push(rowSource.slice(open + 1, cursor - 1).replace(/\s+/g, ' ').trim())
    match = MONEY_CALL.exec(rowSource)
  }
  return exprs
}

export interface DuplicateMoneyCell {
  /** 第几个 `<tr>`（1 起，按源码出现顺序） */
  row: number
  /** 被印进两个格子的那个表达式 */
  expression: string
}

/**
 * 逐 `<tr>` 找「同一个金额表达式占两格」。命中即具名返回；无命中 ⇒ `[]`（纯函数，内存可注入）。
 * 注释先剥离（文档里要能引用反例，不许被自己的文案喂红）。
 */
export function duplicateMoneyCells(source: string): DuplicateMoneyCell[] {
  const body = stripTsComments(source)
  const hits: DuplicateMoneyCell[] = []
  const rows = body.match(/<tr\b[\s\S]*?<\/tr>/g) ?? []
  rows.forEach((rowSource, index) => {
    const seen = new Set<string>()
    for (const expression of moneyCellExpressions(rowSource)) {
      if (seen.has(expression)) hits.push({ row: index + 1, expression })
      seen.add(expression)
    }
  })
  return hits
}

const ROOT = process.cwd()

/** 现取：按 `SCOPE` 读文件并跑判据（文件不存在 ⇒ 抛错，不得静默跳过） */
export function duplicateMoneyCellsInScope(root = ROOT): { file: string; hits: DuplicateMoneyCell[] }[] {
  return SCOPE.map((file) => ({
    file,
    hits: duplicateMoneyCells(readFileSync(join(root, file), 'utf-8')),
  })).filter((entry) => entry.hits.length > 0)
}

/** 可复制命令（判红时打印，出口必须真可行动 —— `migao-dev-flow` §23 G3） */
const RERUN = 'cd frontend/admin-web && npx vitest run tests/unit/paper-doc-money-cells-guard.test.ts'

describe('纸面金额格不变量 · 判别力自证（issue #7716）', () => {
  it('🔴 坏形态：同一行把 `formatAmount(processingFee)` 印进两格（= 总额冒充单价）⇒ 必红', () => {
    const bad =
      '<tr><td>加工费</td><td>{formatAmount(processingFee)}</td><td>{formatAmount(processingFee)}</td></tr>'
    expect(duplicateMoneyCells(bad)).toEqual([{ row: 1, expression: 'processingFee' }])
  })

  it('✅ 好形态：单价取 `feeUnitPrice`、小计取 `processingFee` ⇒ 不红', () => {
    const good =
      '<tr><td>加工费</td><td>{formatAmount(feeUnitPrice)}</td><td>{formatAmount(processingFee)}</td></tr>'
    expect(duplicateMoneyCells(good)).toEqual([])
  })

  it('嵌套实参按括号配对截取：`paperLineSubtotal(item)` 与 `item.subtotal` 不同 ⇒ 不红（假红对照）', () => {
    const nested =
      '<tr><td>{formatAmount(paperLineSubtotal(item))}</td><td>{formatAmount(item.subtotal)}</td></tr>'
    expect(duplicateMoneyCells(nested)).toEqual([])
  })

  it('注释里的反例不算命中（文档要能引用这个形态）', () => {
    const source = [
      '<tr>',
      '  {/* 反例：<td>{formatAmount(processingFee)}</td><td>{formatAmount(processingFee)}</td> */}',
      '  <td>{formatAmount(feeUnitPrice)}</td>',
      '  <td>{formatAmount(processingFee)}</td>',
      '</tr>',
    ].join('\n')
    expect(duplicateMoneyCells(source)).toEqual([])
  })

  it('判据拒绝在半截输入上给结论（括号不配对 ⇒ 抛错，不许静默返回 []）', () => {
    expect(() => moneyCellExpressions('<td>{formatAmount(processingFee}</td>')).toThrow(/括号不配对/)
  })
})

describe('纸面金额格不变量 · 现取（五份打印单据，issue #7716）', () => {
  it('普查面非空且覆盖打印单据族（扫描面漂了 ⇒ 先红，而不是静默空跑）', () => {
    expect(SCOPE.length, '打印单据清单被清空 ⇒ 判据在扫空气').toBeGreaterThanOrEqual(4)
    expect(SCOPE).toContain('src/components/orders/QuotationDoc.tsx')
    // 现取：报价单确实有数据行可扫（扫到 0 行 ⇒ 说明点号/标签形态漂了，判据在扫空气）
    const quotation = readFileSync(join(ROOT, 'src/components/orders/QuotationDoc.tsx'), 'utf-8')
    expect((quotation.match(/<tr\b/g) ?? []).length, '报价单里认不出 <tr> ⇒ 坐标系已漂移').toBeGreaterThanOrEqual(3)
  })

  it('同一行内没有「同一个金额表达式占两格」（总额冒充单价）', () => {
    const offenders = duplicateMoneyCellsInScope()
    expect(
      offenders,
      offenders.length === 0
        ? ''
        : `纸面把同一个金额表达式印进了两个格子（典型 = 单价拿总额充数）：\n` +
          offenders
            .map(
              ({ file, hits }) =>
                `  · ${file} :: 第 ${hits.map((h) => h.row).join(' / ')} 个 <tr> :: \`${hits[0].expression}\``
            )
            .join('\n') +
          `\n复算：${RERUN}`,
    ).toEqual([])
  })
})
