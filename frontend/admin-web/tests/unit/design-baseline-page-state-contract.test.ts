// case_ids: UI-058
/**
 * 类级元守卫（issue #6668 盲区④）：**四态齐备、失败 ≠ 空**（跨页面）。
 *
 * ## 病灶
 *
 * 本仓已有 `frontend/admin-web/tests/unit/read-failure-empty-state-guard.test.ts`（UI-057/058，issue #6663）
 * 治的是「**catch 只清空读数**」这一形态（扫 `catch` 块里的 setter）。
 * 它**看不见另一种**：页面**老老实实**渲染了一个空态文案，而读失败时**同一个空态照旧显示** ——
 * 「暂无数据」于是同时承担「真的没有」与「没读到」两种含义。实测现场 = `src/app/(dashboard)/finance/page.tsx`：
 * 三张表的读失败走 `toast.error`（一会儿就消失），**表体照旧印「暂无数据」** ⇒ 商家看到的是
 * 「这个月没有收支」而不是「没读到」。
 *
 * ## 判据（与 UI-057/058 分工，不重判它的面）
 *
 * 1. **有空态就必须有失败态锚点**：凡 `src/app/(dashboard)` 下**出现空态字面量**的页面，
 *    必须含一个**可靠的**失败态信号（`data-testid` 里带 `-error`，或失败态文案锚点）；
 * 2. **未登记即红**：不满足 ① 的页面必须进台账 `page-state-contract-ledger.json`（未登记 ⇒ 红）；
 * 3. **台账只许缩短**：修好之后忘删条目 ⇒ 红；
 * 4. **正向核**：台账里声明的失败态锚点必须**逐字**出现在该文件里（声明与事实不一致 ⇒ 红）；
 * 5. **失败 ≠ 空**：失败态锚点**不得**与空态字面量是同一个串（把「暂无数据」当失败态 = 没分离）；
 * 6. **每条必须有理由**（非空 reason），且**下界冻结**（只许缩短）；
 * 7. **判别力自证（注入式）**：只有空态 / 失败 ≠ 空 / 只有失败态三种形态各自判红或放行。
 *
 * ## 边界（照实登记，§19.1）
 *
 * - 只扫 `src/app/(dashboard)`（商家后台）—— 官网与两个 Taro app 各有自己的一套；
 * - **只认源码文本形态**：`EmptyState` 组件式空态（若将来引入）不在面内；
 * - 「四态」的**加载态**没有机械判据（`loading` 变量名五花八门，判它只会造一堆假红）⇒
 *   本判据只钉**失败态与空态必须可区分**（这正是用户看得见的那一半）；
 * - 不改任何门禁的通过条件、不新增 required check。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, sep } from 'node:path'

const ROOT = process.cwd()
const SCOPE = 'src/app/(dashboard)'
const LEDGER_PATH = join(ROOT, 'tests/unit/page-state-contract-ledger.json')

interface LedgerEntry {
  failure_anchor?: string
  kind: 'gap' | 'exempt'
  reason: string
}
interface Ledger {
  why: string
  scope: string
  ledger: Record<string, LedgerEntry>
  boundary: string
}
const ledger = JSON.parse(readFileSync(LEDGER_PATH, 'utf-8')) as Ledger

/** 台账下界（现取 = 3 条；只许缩短 —— 修好一个页面就删一条） */
const FROZEN_ENTRY_MAX = 3

/**
 * 空态**展示字面量**（判别力来自「它同时承担『真的没有』与『没读到』」）。
 * 有意不收「还没有」（实测在本仓是**计算不可用**的描述文案：`—（还没有可算的数据）`，
 * 不是空态）—— 收它只会制造假红。
 */
export const EMPTY_STATE_LITERALS = ['暂无数据', '暂无记录', '暂无订单', '暂无库存', '暂无发货单', '暂无标签', '暂无权限']

/** 失败态锚点：机器可判的两类（`data-testid*-error` / 失败态文案） */
export const FAILURE_ANCHOR_RE = /data-testid=\{?["'`][^"'`]*-error|加载失败|读取失败|获取失败|请求失败/

/** 从源码里抽出空态字面量命中（去注释，保行号） */
export function findEmptyStates(src: string): string[] {
  const stripped = src.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' ')).replace(/^\s*\/\/.*$/gm, '')
  return EMPTY_STATE_LITERALS.filter((lit) => stripped.includes(lit))
}

/** 该页有没有可用的失败态锚点 */
export function hasFailureAnchor(src: string): boolean {
  return FAILURE_ANCHOR_RE.test(src)
}

const SKIP_DIRS = new Set(['node_modules', '.next', 'dist', 'coverage', '__pycache__'])

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir).sort()) {
    if (SKIP_DIRS.has(name)) continue
    const full = join(dir, name)
    if (statSync(full).isDirectory()) walk(full, out)
    else if (name.endsWith('.tsx')) out.push(relative(ROOT, full).split(sep).join('/'))
  }
  return out
}

const files = walk(join(ROOT, SCOPE))
const text = new Map(files.map((f) => [f, readFileSync(join(ROOT, f), 'utf-8')]))

/** 有「页面级」空态的文件（含 route 文件与同目录的组件文件） */
const emptyFiles = files.filter((f) => findEmptyStates(text.get(f) ?? '').length > 0)
const gapFiles = emptyFiles.filter((f) => !hasFailureAnchor(text.get(f) ?? ''))
const gapKeys = [...gapFiles].sort()

describe('四态齐备、失败 ≠ 空（跨页面元守卫，issue #6668 盲区④）', () => {
  it('扫描面活着：页面够多、且现取存在「有空态但无失败态」的对象（否则是空扫）', () => {
    expect(files.length, `${SCOPE} 下应有大量 tsx`).toBeGreaterThanOrEqual(30)
    expect(emptyFiles.length, '带空态字面量的文件数不得为 0（规则坏了 ≠ 干净了）').toBeGreaterThan(0)
    expect(findEmptyStates('<td>暂无数据</td>')).toEqual(['暂无数据'])
    expect(hasFailureAnchor('<div data-testid="x-error">加载失败</div>')).toBe(true)
    expect(hasFailureAnchor('<td>暂无数据</td>')).toBe(false)
  })

  it('① 有空态就必须有失败态锚点，未登记即红', () => {
    const unregistered = gapKeys.filter((k) => !(k in ledger.ledger))
    expect(
      unregistered,
      '这些页面渲染空态文案，但没有失败态锚点 —— 读失败时商家看到的是「暂无数据」（故障伪装成空态）。\n'
        + '出口（首选）：照抄 `frontend/admin-web/src/app/(dashboard)/dashboard/page.tsx` 的失败/空态分离'
        + '（失败态 = `data-testid` + 可行动文案 + 重试）；'
        + '确实不适用 ⇒ 登记进 frontend/admin-web/tests/unit/page-state-contract-ledger.json 并逐字写理由。',
    ).toEqual([])
  })

  it('② 台账只许缩短：已修好的条目必须删掉', () => {
    const fixed = Object.entries(ledger.ledger)
      .filter(([file, e]) => e.kind === 'gap' && !gapKeys.includes(file))
      .map(([file]) => file)
    expect(fixed, '这些页面已有失败态锚点 ⇒ 台账条目必须删掉（只许缩短）：' + fixed.join(', ')).toEqual([])
  })

  it('③ 正向核：台账里声明的失败态锚点必须逐字出现在该文件里', () => {
    const missing: string[] = []
    for (const [file, entry] of Object.entries(ledger.ledger)) {
      if (!entry.failure_anchor) continue
      const src = text.get(file) ?? readFileSync(join(ROOT, file), 'utf-8')
      if (!src.includes(entry.failure_anchor)) missing.push(`${file} :: ${entry.failure_anchor}`)
    }
    expect(missing, '台账声称该文件含这个失败态锚点，实际找不到（声明与事实不一致）').toEqual([])
  })

  it('④ 失败 ≠ 空：失败态锚点不得就是空态字面量本身', () => {
    const bad: string[] = []
    for (const [file, entry] of Object.entries(ledger.ledger)) {
      if (entry.failure_anchor && EMPTY_STATE_LITERALS.includes(entry.failure_anchor)) bad.push(file)
    }
    expect(bad, '把空态文案当失败态锚点 = 两者没有分离').toEqual([])
  })

  it('⑤ 每条必须有非空理由 + 下界冻结（只许缩短）', () => {
    const thin = Object.entries(ledger.ledger)
      .filter(([, e]) => typeof e.reason !== 'string' || e.reason.trim().length < 10)
      .map(([f]) => f)
    expect(thin, '这些条目缺理由').toEqual([])
    expect(Object.keys(ledger.ledger).length, '台账为空 ⇒ 要么真修完（下调冻结基线并说明），要么被清空骗绿').toBeGreaterThan(0)
    expect(Object.keys(ledger.ledger).length).toBeLessThanOrEqual(FROZEN_ENTRY_MAX)
  })
})

describe('判别力自证（注入式）：坏形态判红、好形态放行', () => {
  it('🔴 只有空态 ⇒ 判红（这就是 finance 的现场形态）', () => {
    const src = '<tbody><tr><td colSpan={4}>暂无数据</td></tr></tbody>'
    expect(findEmptyStates(src).length).toBe(1)
    expect(hasFailureAnchor(src)).toBe(false)
  })

  it('✅ 空态 + 失败态锚点 ⇒ 放行', () => {
    const src = '<div data-testid="finance-load-error">加载收支汇总失败</div><tbody><tr><td>暂无数据</td></tr></tbody>'
    expect(findEmptyStates(src).length).toBe(1)
    expect(hasFailureAnchor(src)).toBe(true)
  })

  it('✅ 只有失败态、没有空态 ⇒ 不在本判据面内（不是"必须有空态"）', () => {
    const src = '<div data-testid="x-error">读取失败</div>'
    expect(findEmptyStates(src)).toEqual([])
  })

  it('✅ 对照读数：`—（还没有可算的数据）`（计算不可用的描述）不判红 —— 它不是列表空态', () => {
    expect(findEmptyStates("'{summary.recoveryRate === null ? '—（还没有可算的数据）' : x}'")).toEqual([])
  })

  it('✅ 对照读数：注释里的空态字面量不判红（防守卫被自己的文案喂红）', () => {
    expect(findEmptyStates('// 空态说「暂无数据」，失败态说「加载失败」\nconst a = 1')).toEqual([])
  })
})
