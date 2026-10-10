// case_ids: UI-040, UI-053, UI-061, UI-062, UI-095
/**
 * 类级元守卫（issue #6720）：**纸面不得把「未知」印成 0**。
 *
 * ## 病灶（悬空尾巴：#6667 第 8 条移出本包后无人收口）
 *
 * `frontend/admin-web/src/components/orders/ShipmentDoc.tsx`（**客户拿到手的凭证**）里
 * `formatAmount = (amount ?? 0).toLocaleString(...)` / `formatQty = String(qty ?? 0)` ——
 * 缺值在纸面上印成 `0.00` / `0`。而该文件**自己**就写着同族判断（加工费一段）：
 * 「『本来就不收加工费』与『算不出来』长得一样，属**静默改钱的外观**」；
 * 同族的正确范式也早已在仓内：`SalesDoc` 的 `SALES_DOC_MISSING = '—'`、
 * `ProcessingDoc` 的 `MISSING = '—'`、发货单自己的「发货人缺 ⇒ `-`」。
 *
 * **可达性**：后端 `OrderDetailResponse.OrderItemResponse.amount` = 行 `unitPrice × quantity`，
 * 两者都为 null 时回落 `subtotal`；全局 Jackson `default-property-inclusion: non_null`
 * ⇒ 为 null 的键在响应里**整个缺席**，前端拿到的是 `undefined`（真形态，不是理论分支）。
 *
 * ## 四条判据（承载体 = 单一源 `frontend/admin-web/scripts/print-doc-zero-fallback-scan.mjs`）
 *
 * | # | 判什么 | 回归时会**怎么红** |
 * |---|---|---|
 * | 1 | **未登记即红**：`SCOPE`（打印单据族）里出现「`?? 0` / `|| 0` 落进印数值的形态」 | 报出 `文件::形态` 与可复制命令；修法 = 缺值印 `—`（真 0 仍印 `0.00`） |
 * | 2 | **台账只许缩短**：`LEDGER` 条目**不再命中** ⇒ 当场红 | 修好不同批删登记（僵尸豁免）⇒ 红 |
 * | 3 | **判别力自证**：坏形态在内存源码里逐形判红；好形态（缺值 ⇒ `—`、真 0、算术中性元、注释里的反例）**不**报 | 判据退化 / 被自己的文案喂红 ⇒ 红 |
 * | 4 | **实例不变量**：五份单据的测试都必须挂纸面判据（**未登记即红**），且 `SCOPE` 必须含五份单据 | 新单据的测试不调它 ⇒ 具名报出；`SCOPE` 被改小 ⇒ 红 |
 *
 * ## 边界（照实登记，§19.1）
 *
 * - **只扫 `SCOPE` 四份印数值的纸面单据 + 洗水码（当前不印数值）**；屏上组件、取数页、
 *   `/dashboard`、读失败面**不在本台账**（各由 `derived-zero-fallback-scan.mjs`（#6701）、
 *   `read-failure-copy-attribution-scan.mjs`（#6702）承担，两表不互重判）。
 * - 只认源码**文本形态**（去注释后），不判运行时；经中间变量 / 跨行 / 三元回退的 `?? 0`
 *   **判不出来** —— 那半边由各单据测试里的「缺值不印 0」**实例判据**（真渲染 + 读纸面文本）承担。
 * - 洗水码 `TaskCardPrint` 今天**不印任何金额 / 数量**（纸面只有文字与短码）⇒ 对本形态天然免疫；
 *   它一旦开印数值，本文件的静态判据与 `SCOPE` 注释**同时**红（死亡条件写在 `SCOPE` 注释里）。
 * - ⚠️ **本文件同时是 `src/lib/print-doc-paper.ts` 的单测**（判据面守的就是它导出的那几条函数）——
 *   文件名按 `.github/tech-stack.yml` 的 `src/(lib|store)/(.+)\.ts → tests/unit/{1}/{2}.test.ts`
 *   映射，**不要**改成别的名字（改了 ⇒ QA Growth Gate 判「缺测」）。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import {
  LEDGER,
  PRINT_FILL_PATTERNS,
  SCOPE,
  SCOPE_TARGETS,
  printDocZeroFillSites,
  printDocZeroFillSitesFromSource,
  stripTsComments,
} from '../../../scripts/print-doc-zero-fallback-scan.mjs'
import {
  PAPER_MISSING,
  assertNoPaperZeroFill,
  assertPaperKeepsMissingDistinct,
  paperNumberCells,
  paperNumericColumn,
  paperTextOf,
  paperZeroFills,
} from '@/lib/print-doc-paper'

const ROOT = process.cwd()

/** 在内存里跑判据（自证用）—— 不在测试里抄第二份正则 */
const probe = (source: string) => printDocZeroFillSitesFromSource(source, { file: 'probe.tsx' })
const probeLabels = (source: string) => probe(source).map((s) => s.label)

/**
 * 各单据测试文件里对**纸面判据**的登记：单据标识（`// 单据：<label>`）与判据调用
 * （`assertNoPaperZeroFill` / `assertPaperKeepsMissingDistinct`）在**同一行或相邻行**
 * （标识写在上/下一行注释里都算；本判据的调用**多行**是常态，故窗口 = 相邻行）。
 */
function registrations(source: string, label: string): string[] {
  const call = /assert(?:NoPaperZeroFill|PaperKeepsMissingDistinct)\s*\(/
  const marker = `单据：${label}`
  const lines = source.split('\n')
  for (let i = 0; i < lines.length; i += 1) {
    if (!call.test(lines[i])) continue
    for (const j of [i - 1, i, i + 1]) {
      if (j >= 0 && j < lines.length && lines[j].includes(marker)) return [label]
    }
  }
  return []
}

describe('打印单据族 · 「未知不得印成 0」类级判定面（issue #6720）', () => {
  it('判据面非空、含目标单据，且每个受管文件**真实存在**（扫空气 ⇒ 红）', () => {
    expect(SCOPE.length).toBeGreaterThanOrEqual(5)
    for (const anchor of [
      'src/components/orders/ShipmentDoc.tsx',
      'src/components/orders/QuotationDoc.tsx',
      'src/components/orders/SalesDoc.tsx',
      'src/components/orders/ProcessingDoc.tsx',
      'src/components/production/TaskCardPrint.tsx',
    ]) {
      expect(SCOPE, `${anchor} 必须在判据面内（SCOPE 被改小 / 文件被挪走都会在这里红）`).toContain(anchor)
    }
    for (const rel of SCOPE) {
      expect(readFileSync(join(ROOT, rel), 'utf-8').length, `${rel} 读不到内容`).toBeGreaterThan(0)
    }
    expect(SCOPE_TARGETS.length).toBeGreaterThanOrEqual(5)
  })

  it('🔴 未登记即红：受管单据里不得出现「`?? 0` / `|| 0` 落进印数值的形态」', () => {
    const sites = printDocZeroFillSites(ROOT)
    expect(
      sites.map((s) => `${s.key}  @${s.file}:${s.line}  「${s.text.trim()}」`),
      '纸面缺值必须印 `—`（范式：SalesDoc 的 SALES_DOC_MISSING），**真 0 仍印 `0.00`**；\n' +
        '确认过确属纸面外的算术中性元 / 非数值位，再登记进 ' +
        'frontend/admin-web/scripts/print-doc-zero-fallback-scan.mjs 的 LEDGER（并写明死亡条件）。\n' +
        '复算命令（在 frontend/admin-web 下）：npx vitest run tests/unit/lib/print-doc-paper.test.ts'
    ).toEqual([])
  })

  it('🔴 台账只许缩短：`LEDGER` 里不再命中的条目当场红（修好必须同批删）', () => {
    const sites = printDocZeroFillSites(ROOT)
    const stale = LEDGER.filter((key) => !sites.some((s) => s.key === key))
    expect(stale, '这些台账条目已经不再命中（多半是修好了）⇒ 必须同批删掉，不留僵尸豁免：').toEqual([])
  })

  it('🔴 实例不变量：五份单据的测试都必须挂纸面判据（未登记即红）', () => {
    const missing = SCOPE_TARGETS.filter((target) => {
      const source = readFileSync(join(ROOT, target.file), 'utf-8')
      return registrations(source, target.label).length === 0
    })
    expect(
      missing.map((t) => `${t.label}（${t.file}）`),
      '这些打印单据没有把「未知不得印成 0」挂进自己的测试 —— 同类缺陷换到它们的纸面上不会有任何东西变红'
    ).toEqual([])
  })

  it('🔴 实例不变量 ①：判据面里出现「整格 = 0 / 0.00」⇒ 抛错并点出单据与命中值', () => {
    expect(() =>
      assertNoPaperZeroFill(['—', '0.00', '1,250.00'], {
        label: '发货单 ShipmentDoc',
        presence: ['缺 amount'],
      })
    ).toThrow(/发货单 ShipmentDoc[\s\S]*0\.00/)
    // 反向对照：印 `—` 的纸面**不**报（否则「修好了还红」= 假红，会逼人回退）
    expect(
      assertNoPaperZeroFill(['—', '—'], { label: '报价单 QuotationDoc', presence: ['缺 amount'] })
    ).toBeUndefined()
    // 🔴 **真值里的 `0.00` 不许判红**（issue #6720 明令）：`100.00` / `1,250.00` 是整格真值
    expect(
      assertNoPaperZeroFill(['100.00', '1,250.00', '17.5'], { label: '发货单 ShipmentDoc' })
    ).toBeUndefined()
  })

  it('🔴 判据面选取：`paperNumericColumn` 只取**指定列**，且空集抛错（不许被读成通过）', () => {
    const host = document.createElement('div')
    host.innerHTML =
      '<table>' +
      '<tr><td>缺值布</td><td>—</td><td>—</td><td>—</td></tr>' +
      '<tr><td>真零布</td><td>0.00</td><td>0</td><td>0.00</td></tr>' +
      '</table>'
    // 金额列 = index 3：两行都取到（缺值行「—」+ 真 0 行「0.00」）
    expect(paperNumericColumn(host, { column: 3 })).toEqual(['—', '0.00'])
    expect(() => paperNumericColumn(host, { column: 9 })).toThrow(/检查范围为空/)
    expect(() => paperNumericColumn(null, { column: 1 })).toThrow(/空容器/)
  })

  it('🔴 实例不变量 ②：逐格「未知 vs 真 0」**双向**都要有（缺任一边 ⇒ 红）', () => {
    const ok = [PAPER_MISSING, '0.00', '0', '1,250.00']
    expect(
      assertPaperKeepsMissingDistinct(ok, { label: '发货单 ShipmentDoc', presence: ['缺值行 + 真 0 行'] })
    ).toBeUndefined()
    // 只有真 0、没有 `—` ⇒ 缺值那半没渲染（判据在空气上跑）⇒ 红
    expect(() =>
      assertPaperKeepsMissingDistinct(['0.00', '1,250.00'], { label: '发货单 ShipmentDoc' })
    ).toThrow(/缺值那半没渲染|「—」/)
    // 只有 `—`、没有真 0 ⇒ 没覆盖「真 0 仍印 0」的反向对照 ⇒ 红
    expect(() =>
      assertPaperKeepsMissingDistinct([PAPER_MISSING, '1,250.00'], { label: '发货单 ShipmentDoc' })
    ).toThrow(/反向对照|真 0/)
  })

  it('🔴 缺 label ⇒ 抛错（判据不许无名单据）', () => {
    expect(() => assertNoPaperZeroFill(['缺值布 —'])).toThrow(/label/)
    expect(() => assertPaperKeepsMissingDistinct([PAPER_MISSING, '0'])).toThrow(/label/)
  })

  it('🔴 逐格判据：纸面数值格里 `—`（未知）与 `0`（真 0）**可分**', () => {
    const host = document.createElement('div')
    host.innerHTML =
      '<table><tr><td>—</td><td>0</td><td>0.00</td><td>1,250.00</td><td>第1套/共1套</td><td>缺值布</td></tr></table>'
    expect(paperNumberCells(host)).toEqual([PAPER_MISSING, '0', '0.00', '1,250.00'])
  })

  it('判别力自证（坏形态逐形判红）', () => {
    // ① 格式化补位（本单病灶原形，逐字取自 main 上的 ShipmentDoc）
    expect(probeLabels('return (amount ?? 0).toLocaleString("zh-CN")')).toEqual(['格式化补位'])
    // ② 字符串化补位（`String(qty ?? 0)` ⇒ 纸面印 `0`）
    expect(probeLabels('return String(qty ?? 0)')).toEqual(['字符串化补位'])
    // ③ 数值化补位（`Number(x ?? 0)` ⇒ 再经金额格式化进纸面）
    expect(probeLabels('const n = Number(row.amount ?? 0)')).toEqual(['数值化补位'])
    // ④ 一行内的格式化函数实参补位（没有 `).` 的那种写法）
    expect(probeLabels('formatAmount(item.amount ?? 0)')).toEqual(['格式化函数实参补位'])
    // ⑤ `||` 是同一个病的另一种写法
    expect(probeLabels('const v = (x || 0).toFixed(2)')).toEqual(['格式化补位'])
    // ⑥ 括号包裹在**方法调用之外**
    expect(probeLabels('const v = ((a ?? 0).toLocaleString("zh-CN"))')).toEqual(['格式化补位'])
    // ⑦ 每个形态都必须在自己的样本上命中（判据面不许空转）——形态集合与样本键**双向**对账
    expect(Object.keys(BAD_SAMPLES).sort()).toEqual(PRINT_FILL_PATTERNS.map((p) => p.label).sort())
    for (const { label } of PRINT_FILL_PATTERNS) {
      const sample = BAD_SAMPLES[label] ?? ''
      expect(
        sample.length,
        `形态「${label}」在 BAD_SAMPLES 里没有样本 ⇒ 该形态可能永远不判红`
      ).toBeGreaterThan(0)
      expect(probeLabels(sample)).toContain(label)
    }
  })

  it('判别力自证（反向对照）：正确形态 / 算术中性元 / 注释里的反例都**不**报', () => {
    // ① 正确形态：缺值 ⇒ `—`（本单实现）
    expect(
      probeLabels(
        'function formatAmount(a?: number) { if (a === undefined) return MISSING; return a.toFixed(2) }'
      )
    ).toEqual([])
    // ② 真 0 的合法写法：值来自已判定「读到了」的数
    expect(probeLabels('const v = amount.toLocaleString("zh-CN")')).toEqual([])
    // ③ 🔴 算术中性元：累加器的 `|| 0` 不是「把坏值印成读数」（缺值语义由 `lineSubtotal` 的 `null` 承担）
    expect(probeLabels('return items.reduce((sum, it) => sum + (it.processingFee || 0), 0)')).toEqual([])
    expect(probeLabels('return (item.subtotal || 0) + (item.processingFee || 0)')).toEqual([])
    // ④ 注释里的反例（本仓三个文件的文件头都在解释旧写法）—— 判据只看去注释后的代码
    expect(
      probeLabels('// 旧写法 (amount ?? 0).toLocaleString(...) 会让纸面恒印 0.00\nconst v = 1')
    ).toEqual([])
    expect(stripTsComments('/* (a ?? 0).toLocaleString() */ const v = 1')).not.toContain('toLocaleString')
    // ⑤ 非纸面射程的取数 / 状态聚合
    expect(probeLabels('setTotal(rows.reduce((s, r) => s + (r.amount ?? 0), 0))')).toEqual([])
  })

  it('判别力自证（注入式）：把 main 上的旧写法注进真源码 ⇒ 判据当真判红（自证坐标：`SCOPE[0]`）', () => {
    const rel = SCOPE[0]
    const original = readFileSync(join(ROOT, rel), 'utf-8')
    const cleaned = stripTsComments(original)
    // 现取应为 0（本单已修）；先自证注入点存在且判据**不是**空判据
    expect(printDocZeroFillSites(ROOT)).toEqual([])
    expect(cleaned).not.toContain('(amount ?? 0).toLocaleString')
    // 注入点 = 该单据的 `formatAmount` 函数体开头（**按符号定位**，不写行号）
    const anchorRe = /export function formatAmount\([^)]*\): string \{/
    expect(anchorRe.test(original), `\`${rel}\` 里找不到 \`formatAmount\`（注入点已漂移）`).toBe(true)
    const injected = original.replace(anchorRe, (m) => `${m}\n  return (amount ?? 0).toLocaleString("zh-CN")`)
    expect(injected, `\`${rel}\` 里找不到注入点 ⇒ 本红证会**空跑**`).not.toBe(original)
    expect(
      printDocZeroFillSitesFromSource(injected, { file: rel }),
      '注入 main 上的旧写法后判据**没判红** ⇒ 守卫是空判据'
    ).not.toEqual([])
  })

  it('纸面禁出现的假读数固定为 `0.00`（裸 `0` **不**在此列：真 0 是合法读数）', () => {
    expect(paperZeroFills('合计 0.00')).toEqual(['0.00'])
    expect(paperZeroFills('合计 —')).toEqual([])
    // 🔴 反向对照（issue #6720 明令）：含 0 的真读数**不得**被判红
    expect(paperZeroFills('发货单 17.5 第1套/共1套')).toEqual([])
  })

  it('纸面正文取形：`<style>` / `<svg>` 不算「印给客户看的数字」（否则样式里的 100% 会假红）', () => {
    const host = document.createElement('div')
    host.innerHTML =
      '<style>.x { width: 100%; }</style><svg><path d="M0 0h10"/></svg><table><td>—</td></table>'
    expect(paperTextOf(host)).toBe('—')
  })
})

/** 坏形态样本（每个形态一条；与 `PRINT_FILL_PATTERNS` 的 label 一一对应） */
const BAD_SAMPLES: Record<string, string> = {
  格式化补位: 'return (amount ?? 0).toLocaleString("zh-CN")',
  字符串化补位: 'return String(qty ?? 0)',
  数值化补位: 'const n = Number(row.amount ?? 0)',
  格式化函数实参补位: 'formatAmount(item.amount ?? 0)',
}
