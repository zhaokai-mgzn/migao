// case_ids: UI-001
/**
 * 类级元守卫（issue #6668 盲区①）：**「查表兜底 = 原始值」不许把机器值印上屏**。
 *
 * ## 病灶（为什么既有两张网都扫不到它）
 *
 * | 既有守卫 | 扫什么 | 为什么漏了这一族 |
 * |---|---|---|
 * | `frontend/admin-web/tests/unit/user-copy-jargon-guard.test.ts`（UI-093） | 源码**字面量** | `LABELS[x] \|\| x` 的左半边是变量，字面量抽取器看不见 |
 * | `frontend/admin-web/tests/unit/jsx-machine-key-guard.test.ts`（UI-094） | 文本位的**纯成员链** | 整个表达式是**二元运算**，不是成员链 ⇒ 不在面内 |
 *
 * ⇒ 服务端新增一个枚举值（财务加一种支付方式、生产加一种报废原因）时，前端查表查不到，
 * 兜底就把**原始标识**印上屏；而**没有任何东西会因此变红**。
 *
 * ## 判据（命中的判定本体 = 扫描器，不在这里写第二份规则）
 *
 * 1. **未登记即红**：`frontend/admin-web/scripts/enum-fallback-scan.mjs` 扫出的每一处，
 *    路径必须出现在台账 `enum-fallback-ledger.json` 的 `ledger` 里；
 * 2. **只许缩短**：台账里的路径在本次扫描里**不再命中** ⇒ 红（删掉它，不留僵尸豁免）；
 * 3. **分类必须显式**：`kind ∈ {risk, benign}`，`risk` 必须写出改法方向、`benign` 必须写出
 *    「为什么它不可能把机器值印上屏」（**空 reason 即红**）；
 * 4. **台账不许被清空**（fail-closed）：`risk`/`benign` 两侧为空 ⇒ 红；
 * 5. **下界冻结（只许缩短）**：`risk` 条数与 `benign` 条数各有一条**冻结基线**，
 *    现取读数**不得高于**它（把已知漏点搬进台账并不能让它变绿）；
 * 6. **判别力自证（注入式）**：把历史坏形态与好形态写进**内存**再扫 —— 坏形态各自判红、
 *    好形态不红 ⇒ 判据不是空断言。
 *
 * ## 出口（红时怎么办，二选一）
 *
 * - **首选**：改成 `displayEnum(LABELS, value)`（`frontend/admin-web/src/lib/enum-display.ts`）——
 *   已知值逐字不变，未知值走人话兜底（`其他`）⇒ 台账条目当场消失；
 * - 若确认兜底值不可能上屏（图标常量 / 前端自有人话表），把它登记为 `benign` 并**逐字写理由**；
 *   冻结基线需要**同时下调**（只许缩短 —— 下调即写进本文件的常量与 PR body）。
 *
 * ## 边界（照实登记，§19.1）
 *
 * - 判**源码文本形态**：`if (!L[x]) y = x` / 三元 / 兜底写在左侧（`x || L[x]`）**不在面内**；
 * - **判不了「这个值此刻是不是人话」** ⇒ `risk` 条目 = 「必须被处置」的清单，
 *   不等于"线上必有缺陷"；反向也不成立（`benign` 是**声明**，靠理由审阅，不是机器证明）；
 * - 不改业务语义、不改任何门禁的通过条件、不新增豁免。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { findFallbackSites, scanFallbackSites, SCOPE } from '../../scripts/enum-fallback-scan.mjs'

const ROOT = process.cwd()
const LEDGER_PATH = join(ROOT, 'tests/unit/enum-fallback-ledger.json')

interface LedgerEntry {
  kind: 'risk' | 'benign'
  reason: string
  /** **逐站点计数**（规则 id → 命中条数）：同一个文件里多写一处坏兜底也当场红 */
  sites: Record<string, number>
}
interface Ledger {
  why: string
  ledger: Record<string, LedgerEntry>
  syntax_benign?: Record<string, string>
  boundary: string
}

const ledger = JSON.parse(readFileSync(LEDGER_PATH, 'utf-8')) as Ledger

/**
 * 🔴 **冻结基线（只许缩短）**：现取读数 = `risk 21 / benign 5`。
 * 放宽这两条 = 把已知漏点合法化 ⇒ 必须同时在 PR body 说明并**下调**，不能上调。
 */
const FROZEN_RISK_MAX = 22
const FROZEN_BENIGN_MAX = 6

const { files, sites } = scanFallbackSites(ROOT)
const hitFiles = [...new Set(sites.map((s) => s.file))].sort()

/** 现取读数：文件 → （规则 id → 条数） */
const hitSites: Record<string, Record<string, number>> = {}
for (const s of sites) {
  hitSites[s.file] ??= {}
  hitSites[s.file][s.rule] = (hitSites[s.file][s.rule] ?? 0) + 1
}
for (const f of Object.keys(hitSites)) hitSites[f] = Object.fromEntries(Object.entries(hitSites[f]).sort())

describe('表达式兜底：查表兜底不得回显原始机器值（类级元守卫，issue #6668 盲区①）', () => {
  it('扫描面非空（扫空气 ⇒ 磨砂绿，先钉死）', () => {
    expect(files.length, `${SCOPE} 下应有大量源文件`).toBeGreaterThanOrEqual(150)
    expect(sites.length, '现取命中数不得为 0（否则是规则坏了，不是"干净了"）').toBeGreaterThan(0)
  })

  it('① 未登记即红：每一处命中都必须进台账', () => {
    const unregistered = hitFiles.filter((f) => !(f in ledger.ledger))
    expect(
      unregistered,
      '这些文件里出现「查表兜底 = 原始值」而台账没登记 —— 未命中时会把服务端标识直接印上屏。\n'
        + '出口：① 首选改成 `displayEnum(LABELS, value)`（frontend/admin-web/src/lib/enum-display.ts）；'
        + '② 确认不可能上屏（图标常量 / 前端自有人话表）⇒ 登记进 frontend/admin-web/tests/unit/enum-fallback-ledger.json 的 ledger 并逐字写理由。',
    ).toEqual([])
  })

  it('①-b 逐站点计数：同一文件里多写一处坏兜底也当场红（防"文件已登记 ⇒ 随便加"）', () => {
    const drift = hitFiles
      .filter((f) => f in ledger.ledger)
      .map((f) => ({ file: f, now: hitSites[f], declared: ledger.ledger[f].sites }))
      .filter((d) => JSON.stringify(d.now) !== JSON.stringify(d.declared || {}))
    expect(
      drift,
      '这些文件的命中条数与台账声明不一致（新增了坏兜底 / 修掉了若干条但没改台账）：\n'
        + drift.map((d) => `  ${d.file}\n    现取 ${JSON.stringify(d.now)}\n    台账 ${JSON.stringify(d.declared)}`).join('\n')
        + '\n出口：修掉（首选 `displayEnum`）⇒ 把台账计数调低；确实新增了一处已评估的形态 ⇒ 把计数调高并在 PR body 说明。',
    ).toEqual([])
  })

  it('② 台账只许缩短：不再命中的条目当场红（不留僵尸豁免）', () => {
    const stale = Object.keys(ledger.ledger).filter((f) => !hitFiles.includes(f))
    expect(
      stale,
      '台账里这些文件已不再命中 ⇒ 条目必须删掉（台账只许缩短）：' + stale.join(', '),
    ).toEqual([])
  })

  it('③ 分类必须显式：kind ∈ {risk,benign} 且每条都有非空理由', () => {
    const bad = Object.entries(ledger.ledger)
      .filter(([, v]) => !['risk', 'benign'].includes(v?.kind) || typeof v.reason !== 'string' || v.reason.trim().length < 10)
      .map(([f]) => f)
    expect(bad, '这些台账条目缺 kind（risk/benign）或理由太短（理由必须能被人复核）').toEqual([])
  })

  it('④ 台账不许被清空（fail-closed）', () => {
    const kinds = Object.values(ledger.ledger).map((v) => v.kind)
    expect(kinds.filter((k) => k === 'risk').length, 'risk 侧为空 ⇒ 要么真修完了（那要下调冻结基线），要么台账被清空').toBeGreaterThan(0)
    expect(kinds.filter((k) => k === 'benign').length, 'benign 侧为空 ⇒ 同上').toBeGreaterThan(0)
  })

  it('⑤ 冻结基线只许缩短（现取读数不得高于基线）', () => {
    const kinds = Object.values(ledger.ledger).map((v) => v.kind)
    const risk = kinds.filter((k) => k === 'risk').length
    const benign = kinds.filter((k) => k === 'benign').length
    expect(risk, `risk 条目 ${risk} > 冻结基线 ${FROZEN_RISK_MAX}（把已知漏点搬进台账骗绿）`).toBeLessThanOrEqual(FROZEN_RISK_MAX)
    expect(benign, `benign 条目 ${benign} > 冻结基线 ${FROZEN_BENIGN_MAX}`).toBeLessThanOrEqual(FROZEN_BENIGN_MAX)
  })
})

describe('判别力自证：坏形态各自判红、好形态不红（注入式，不靠人记）', () => {
  const bad = [
    ['历史形态 · `||` 兜底回显', 'const a = <td>{KIND_LABEL[row.pieceKind] || row.pieceKind}</td>'],
    ['历史形态 · `??` 兜底回显', 'const b = <td>{KIND_LABEL[row.pieceKind] ?? row.pieceKind}</td>'],
    ['历史形态 · 内部引用键兜底（实机形态）', 'const c = <span>{orderNoById[r.orderRef] ?? r.orderRef}</span>'],
    ['历史形态 · 权限码兜底', 'const d = {codes.map(c => permissionLabelMap[c] || c)}'],
    ['历史形态 · 属性访问式查表', 'const e = <td>{FEE_SOURCE_LABELS[feeSource] ?? feeSource}</td>'],
  ] as const

  for (const [name, src] of bad) {
    it(`🔴 ${name} ⇒ 命中（判红）`, () => {
      const hits = findFallbackSites(src, 'src/injected-bad.tsx')
      expect(hits.length, '这一族必须被扫出来，否则本守卫是空断言').toBeGreaterThan(0)
    })
  }

  const good = [
    ['人话兜底（`displayEnum`）', 'const a = <td>{displayEnum(KIND_LABEL, row.pieceKind)}</td>'],
    ['字面量兜底', "const b = <td>{KIND_LABEL[row.pieceKind] || '其他'}</td>"],
    ['破折号兜底', "const c = <td>{LABELS[x] ?? '—'}</td>"],
    ['同表另一项兜底（样式/缺省）', 'const d = <td>{STATUS_TEXT[po.status] ?? STATUS_TEXT.pending}</td>'],
    ['数组兜底', 'const e = <td>{PENDING_COLORS[color] ?? []}</td>'],
  ] as const

  for (const [name, src] of good) {
    it(`✅ ${name} ⇒ 不命中`, () => {
      expect(findFallbackSites(src, 'src/injected-good.tsx')).toEqual([])
    })
  }

  it('对照读数：注释里的坏形态不判红（否则守卫被自己的文案喂红）', () => {
    expect(findFallbackSites('// 例如 KIND_LABEL[x] || x 这种写法\nconst a = 1')).toEqual([])
  })
})
