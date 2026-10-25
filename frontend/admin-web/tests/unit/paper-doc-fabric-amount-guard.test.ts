// case_ids: UI-053
/**
 * 类级元守卫（issue #7724）：**纸面 / 明细行的钱不许直接读 `subtotal`**（语义二义的字段）。
 *
 * ## 病理（用户 2026-10-25 同一张报价单截图）
 *
 * 一张纸上同时印着「本套金额 **327.04**」与「本单总金额 / 本单应收 **275.94**」——
 * `327.04 = 275.94 + 51.10`，加工费被算了**两遍**。根因是 `order_items.subtotal` 的语义**二义**：
 * 「新增订单」页建单时落的是 `面料 + 加工费`（`subtotal: productSub + lineFee`），
 * 而 agent / 开放接口路径落的是面料金额；展示层（`lib/order-amount.ts` 的行小计、
 * `QuotationDoc` 的面料行小计、`OrderItemList` 的合计）当时都直读 `subtotal` 再 + 加工费。
 *
 * 真值：`amount`（后端 `unitPrice × quantity`，`OrderService.convertToItemResponse`）才是**确定**的
 * 面料金额 ⇒ 一律经 `lib/order-amount.ts::fabricSubtotal(item)` 取（它只在 `amount` 缺席时回落 `subtotal`）。
 *
 * ## 判据（两条，都在本文件里现取）
 *
 * | # | 判什么 | 回归时会**怎么红** |
 * |---|---|---|
 * | 1 | **现取为 0**：`SCOPE`（四份印金额的纸面单据 + 屏幕明细行 `OrderItemList`）里不得出现「把 `.subtotal` 直接交给金额格式化 / 直接印进单元格」 | 报出 `文件:行: 片段` + 可复制命令；修法 = 改走 `fabricSubtotal(...)` |
 * | 2 | **判别力自证**（注入式，内存源码）：坏形态（`formatAmount(item.subtotal)` / `{item.subtotal}`）必红；好形态（`formatAmount(fabricSubtotal(item))`）不红；**注释里的反例**不红 | 判据退化 / 被自己的文档喂红 ⇒ 红 |
 *
 * ## 边界（照实登记，别读成「全覆盖」）
 *
 * - 只认**两种真形态**（金额格式化入口 / JSX 文本格）；算术用法（`item.subtotal * 2`）与
 *   变量中转（`const s = item.subtotal`）不在射程 —— 那半边由 `order-amount.test.ts` 的
 *   取数口判据与两份组件实例判据承担。
 * - `SCOPE` 之外的读面（`OrderTable` / `OrderDetail` 的 `getItemAmount`）**不在本台账**：
 *   它们本来就 `amount` 优先，且第三个兜底 `unitPrice × quantity` 属列表/详情页既有口径。
 * - 本判据判「有没有绕过取数口」，**判不了**「`subtotal` 里到底含不含加工费」（那是数据口径，
 *   issue #7724 的选项 B，尚未执行）。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { SCOPE, stripTsComments } from '../../scripts/print-doc-zero-fallback-scan.mjs'

/** 判据面 = 四份印金额的纸面单据（复用同一份清单）+ 屏幕明细行 */
const GUARD_SCOPE = [...SCOPE, 'src/components/orders/OrderItemList.tsx']

/** 把二义字段 `subtotal` 直接当钱印：① 金额格式化入口 ② 直接进 JSX 文本格 */
const BANNED = [
  /format(?:Amount|Money)\(\s*[\w$?.]*\.subtotal\s*\)/g,
  /\{\s*[\w$?.]*\.subtotal\s*\}/g,
]

export interface SubtotalRead {
  /** 1 起的行号 */
  line: number
  /** 命中的源码片段（trim 过） */
  snippet: string
}

/** 逐行找「绕过 `fabricSubtotal` 直接印 `subtotal`」。注释先剥离（文档要能引用反例）。 */
export function directSubtotalReads(source: string): SubtotalRead[] {
  const hits: SubtotalRead[] = []
  stripTsComments(source)
    .split('\n')
    .forEach((text, index) => {
      BANNED.forEach((pattern) => {
        pattern.lastIndex = 0
        if (pattern.test(text)) hits.push({ line: index + 1, snippet: text.trim() })
      })
    })
  return hits
}

const ROOT = process.cwd()

/** 现取：按 `GUARD_SCOPE` 读文件并跑判据（文件不存在 ⇒ 抛错，不得静默跳过） */
export function directSubtotalReadsInScope(root = ROOT): { file: string; hits: SubtotalRead[] }[] {
  return GUARD_SCOPE.map((file) => ({
    file,
    hits: directSubtotalReads(readFileSync(join(root, file), 'utf-8')),
  })).filter((entry) => entry.hits.length > 0)
}

/** 可复制命令（判红时打印，出口必须真可行动 —— `migao-dev-flow` §23 G3） */
const RERUN = 'cd frontend/admin-web && npx vitest run tests/unit/paper-doc-fabric-amount-guard.test.ts'

describe('纸面面料金额取数口 · 判别力自证（issue #7724）', () => {
  it('🔴 坏形态：`formatAmount(item.subtotal)`（跳过面料金额取数口）⇒ 必红', () => {
    expect(directSubtotalReads('<DocTd>{formatAmount(item.subtotal)}</DocTd>')).toEqual([
      { line: 1, snippet: '<DocTd>{formatAmount(item.subtotal)}</DocTd>' },
    ])
  })

  it('🔴 坏形态：`{item.subtotal}` 直接进单元格 ⇒ 必红', () => {
    expect(directSubtotalReads('<td>{item.subtotal}</td>')).toHaveLength(1)
  })

  it('✅ 好形态：`formatAmount(fabricSubtotal(item))` ⇒ 不红', () => {
    expect(directSubtotalReads('<DocTd>{formatAmount(fabricSubtotal(item))}</DocTd>')).toEqual([])
  })

  it('注释里的反例不算命中（文档要能引用这个形态）', () => {
    const source = ['// 反例：formatAmount(item.subtotal) 会被判红', 'const x = fabricSubtotal(item)'].join('\n')
    expect(directSubtotalReads(source)).toEqual([])
  })
})

describe('纸面面料金额取数口 · 现取（issue #7724）', () => {
  it('普查面非空且覆盖纸面 + 明细行（扫描面漂了 ⇒ 先红，而不是静默空跑）', () => {
    expect(GUARD_SCOPE.length, '判据面被清空 ⇒ 在扫空气').toBeGreaterThanOrEqual(5)
    expect(GUARD_SCOPE).toContain('src/components/orders/QuotationDoc.tsx')
    expect(GUARD_SCOPE).toContain('src/components/orders/OrderItemList.tsx')
  })

  it('没有「绕过 `fabricSubtotal` 直接印 `subtotal`」的站点', () => {
    const offenders = directSubtotalReadsInScope()
    expect(
      offenders,
      offenders.length === 0
        ? ''
        : `纸面 / 明细行把二义字段 \`subtotal\` 直接当钱印（该走 \`fabricSubtotal(item)\`）：\n` +
          offenders
            .map(({ file, hits }) => `  · ${file}:${hits.map((h) => h.line).join(',')} :: ${hits[0].snippet}`)
            .join('\n') +
          `\n复算：${RERUN}`,
    ).toEqual([])
  })
})
