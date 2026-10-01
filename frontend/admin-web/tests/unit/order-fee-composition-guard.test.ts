// case_ids: UI-075
/**
 * 类级元守卫（issue #5843）——**加工费合计的每一处求和都必须显式登记**。
 *
 * 病根（实例判据见 tests/unit/pages/order-detail.test.tsx 与 tests/unit/lib/order-fee-display.test.ts）：
 * 订单详情页原先自己算了一套「商品金额」（`getItemAmount`，**不含** `processingFee`），
 * 而页脚用的是订单级总额（**含**加工费）⇒ 中间那笔加工费没有任何渲染点，商家看到两个数对不上
 * （245.14 与 368.74 之间差 123.60，2026-10-01 用户报障）。
 *
 * 只修那一个渲染点 = 没修：**下一个人照样能在别的页面再写一套「自己累加加工费」**，
 * 而那样写出来的数与订单金额静默不一致 —— 没有任何东西会红。本守卫让那个形态**未登记即红**：
 * ① 全 `src/**` 扫「逐行累加加工费」形态；命中而**不在**（**只许缩短**的）白名单里 ⇒ 红；
 * ② 白名单里每一条都必须是**真在累加**的活文件（豁免不许比代码活得久）；
 * ③ 订单详情页不得出现加工费字段名 —— 必须走共享层（`lib/order-fee-display.ts`）。
 *
 * 🔴 判据本身自证（防空断言）：末尾用**内存构造**的坏/好样本证明检测器真的会红、且不误报。
 */
import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

const SRC = path.resolve(__dirname, '../../src')
/** 订单详情页（本单的最小接线点）—— 相对 SRC 的路径 */
const DETAIL_PAGE = 'app/(dashboard)/orders/[id]/OrderDetail.tsx'
/** 共享层本尊 —— 费用构成的唯一实现 */
const SHARED_OWNER = 'lib/order-fee-display.ts'

/** 「逐行累加加工费」的形态（命中 = 有人在自己算这一笔，而不是调共享层） */
const SUMMATION_PATTERNS: Array<[string, RegExp]> = [
  ['reduce 累加', /reduce\([\s\S]{0,300}?processing_?fee/i],
  ['+= 累加', /\+=[\s\S]{0,80}?processing_?fee/i],
]

/**
 * 允许出现「逐行累加加工费」的文件（相对 `src/`）——**只许缩短**（条数现取，见 `FROZEN_MAX`）：
 *
 * 🔴 这四条是**存量渲染面的冻结快照**（2026-10-01 现取），本守卫**不为它们的正确性背书**、
 * 也不重判存量 —— 它只裁**新增**：多出一处求和 ⇒ 未登记即红（口径同仓内其它台账）。
 *
 * - `lib/order-fee-display.ts`：共享层本尊（`buildOrderFeeComposition`）
 * - `components/orders/OrderItemList.tsx`：明细行「合计区」（#4406 起就在，本单未改造它）
 * - `components/orders/ShipmentDoc.tsx`：纸质发货单的加工费合计（同一份行级口径的另一个渲染面）
 * - `app/(dashboard)/orders/new/page.tsx`：新增订单页的**试算预览**面（`feePreview`，不落库；
 *   详情页是**落库快照**面 —— 两个面本来就不同源，见 issue #5843 的裁定）
 *
 * 出口（**可行动**）：把该处改成调 `buildOrderFeeComposition`（或 `buildFeeDetailDisplay`）
 * ⇒ 从本表删掉那一行 ⇒ 守卫仍绿。**新增一行必须同时把 `FROZEN_MAX` 抬上去**，
 * 而抬这个数 = 明确宣告「又多了一套求和」，评审时一眼可见。
 */
const FROZEN_MAX = 4
const ALLOWED_SITES = [
  'lib/order-fee-display.ts',
  'components/orders/OrderItemList.tsx',
  'components/orders/ShipmentDoc.tsx',
  'app/(dashboard)/orders/new/page.tsx',
] as const

/** 递归收集 `src/**` 下的受控扩展名文件（与门禁同源：.ts/.tsx） */
function collectSourceFiles(dir: string): string[] {
  const out: string[] = []
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) out.push(...collectSourceFiles(full))
    else if (/\.tsx?$/.test(entry.name)) out.push(full)
  }
  return out
}

/** 命中「逐行累加加工费」的行号（1-based）+ 形态名 */
function summationHits(source: string): Array<{ kind: string; line: number }> {
  const hits: Array<{ kind: string; line: number }> = []
  for (const [kind, pattern] of SUMMATION_PATTERNS) {
    const matched = pattern.exec(source)
    if (matched) {
      hits.push({ kind, line: source.slice(0, matched.index).split('\n').length })
    }
  }
  return hits
}

describe('订单级加工费合计单一实现（issue #5843 · 类级元守卫）', () => {
  const files = collectSourceFiles(SRC)

  it('检测器自证：坏样本会红、好样本不误报（不是空断言）', () => {
    const bad = "const sum = items.reduce((s, it) => s + (it.processingFee || 0), 0)\n"
    const badPlusEquals = 'let total = 0\nfor (const it of items) total += it.processing_fee\n'
    const good = 'const composition = buildOrderFeeComposition(items, { goodsTotal, orderTotal })\n'

    expect(summationHits(bad)).toHaveLength(1)
    expect(summationHits(badPlusEquals)).not.toHaveLength(0)
    expect(summationHits(good)).toHaveLength(0)
    // 扫描面非空（路径写错 / 目录改名 ⇒ 这里就红，而不是静默「零命中即通过」）
    expect(files.length).toBeGreaterThan(100)
  })

  it('全仓只有白名单内的文件在累加加工费（未登记即红）', () => {
    const offenders: string[] = []
    for (const file of files) {
      const rel = path.relative(SRC, file)
      const hits = summationHits(fs.readFileSync(file, 'utf-8'))
      if (hits.length === 0) continue
      if (!(ALLOWED_SITES as readonly string[]).includes(rel)) {
        offenders.push(`${rel}（${hits.map((h) => `${h.kind}@${h.line}`).join(', ')}）`)
      }
    }
    expect(
      offenders,
      `以下文件在自己累加加工费 ⇒ 会与订单金额静默不一致。出口：改调 ` +
        `src/lib/order-fee-display.ts::buildOrderFeeComposition，或（确需保留）登记进 ` +
        `tests/unit/order-fee-composition-guard.test.ts 的 ALLOWED_SITES 并抬 FROZEN_MAX`
    ).toEqual([])
  })

  it('白名单只许缩短：条数不超过冻结上限，且每一条都仍是活代码', () => {
    expect(ALLOWED_SITES.length).toBeLessThanOrEqual(FROZEN_MAX)
    for (const rel of ALLOWED_SITES) {
      const file = path.join(SRC, rel)
      expect(fs.existsSync(file), `白名单里的 ${rel} 已不存在 ⇒ 请从 ALLOWED_SITES 删掉它`).toBe(true)
      expect(
        summationHits(fs.readFileSync(file, 'utf-8')).length,
        `白名单里的 ${rel} 已不再累加加工费 ⇒ 豁免不许比代码活得久，请删掉它`
      ).toBeGreaterThan(0)
    }
  })

  it('共享层是唯一实现：订单详情页走它、页面内不出现加工费字段名', () => {
    const shared = fs.readFileSync(path.join(SRC, SHARED_OWNER), 'utf-8')
    expect(shared).toMatch(/export function buildOrderFeeComposition/)

    const page = fs.readFileSync(path.join(SRC, DETAIL_PAGE), 'utf-8')
    expect(page).toMatch(/OrderFeeBreakdown/)
    expect(
      page.match(/processing_?fee/gi) ?? [],
      '详情页出现了加工费字段名 ⇒ 有人在页面里自己取价/求和（#5843 的病根形态）；' +
        '展示一律走共享层 src/lib/order-fee-display.ts'
    ).toEqual([])
  })
})
