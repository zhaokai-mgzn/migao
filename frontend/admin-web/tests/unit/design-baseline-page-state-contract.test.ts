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
 *    走共享件 `ListLoadError` 的页面可判形态 = `testId="<页面>-load-error"` 这个 **prop**（issue #8057 补齐）；
 *    同族的**详情面**另有 ⑥：凡渲染「不存在 / 已被删除」这类**事实性断言**的页面，同样必须有失败态锚点
 *    （`docs/design/design-baseline.md` §5 ③：失败 ≠ 空，**失败也 ≠ 不存在**）；
 * 2. **未登记即红**：不满足 ① 的页面必须进台账 `page-state-contract-ledger.json`（未登记 ⇒ 红）；
 * 3. **台账只许缩短**：修好之后忘删条目 ⇒ 红；
 * 4. **正向核**：台账里声明的失败态锚点必须**逐字**出现在该文件里（声明与事实不一致 ⇒ 红）；
 * 5. **失败 ≠ 空**：失败态锚点**不得**与空态字面量是同一个串（把「暂无数据」当失败态 = 没分离）；
 * 6. **每条必须有理由**（非空 reason），且**下界冻结**（只许缩短）；
 * 7. **判别力自证（注入式）**：只有空态 / 失败 ≠ 空 / 只有失败态三种形态各自判红或放行。
 * 8. **台账已归零**（issue #8057）：最后一条在册缺口（`customers/[id]/CustomerDetail.tsx`）修好后
 *    `ledger` 为空、冻结上界降到 **0**。「防清空骗绿」由 ① / ⑥ 承担 —— 清空台账不会让真缺口变绿。
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

/**
 * 台账上界（现取 = **0**，即台账应为空；只许缩短）。
 * 沿革：issue #6703 把 finance / customers 两条删掉后由 3 降到 1；issue #8057 把最后一条
 * `customers/[id]/CustomerDetail.tsx` 修好并删条目 ⇒ **1 降到 0**（归零）。
 */
const FROZEN_ENTRY_MAX = 0

/**
 * 空态**展示字面量**（判别力来自「它同时承担『真的没有』与『没读到』」）。
 * 有意不收「还没有」（实测在本仓是**计算不可用**的描述文案：`—（还没有可算的数据）`，
 * 不是空态）—— 收它只会制造假红。
 */
export const EMPTY_STATE_LITERALS = ['暂无数据', '暂无记录', '暂无订单', '暂无库存', '暂无发货单', '暂无标签', '暂无权限']

/**
 * 「不存在」类**事实性断言**字面量（issue #8057，详情面）：
 * 与空态同一条纪律的另一半 —— 读失败时印「XX 不存在 / 已被删除」= 把故障画成「这张单没了」，
 * 比「暂无数据」更误导（商家可能据此重开一张单）。清单**有意收窄**到本仓真实出现过的三句。
 */
export const NOT_FOUND_LITERALS = ['不存在或已被删除', '客户不存在', '未找到该加工单']

/**
 * 失败态锚点：机器可判的两类（`data-testid*-error` / 失败态文案）。
 * 🔴 2026-10-29（issue #8057）补 `testId="…-load-error"` 分支：失败面走共享件 `ListLoadError` 的页面
 * 源码里没有 `data-testid` 字样（锚点由组件内部渲染），不认这个 **prop** 形态就会把已接线的页面判成缺口。
 */
export const FAILURE_ANCHOR_RE = /data-testid=\{?["'`][^"'`]*(?:-error|-failed)|testId=\{?["'`][^"'`]*(?:-error|-failed)|加载失败|读取失败|获取失败|请求失败/

/** 去注释（保行号）：判据只看**渲染出来的**文案，不看注释里的同形字串 */
function stripComments(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' ')).replace(/^\s*\/\/.*$/gm, '')
}

/** 从源码里抽出空态字面量命中（去注释，保行号） */
export function findEmptyStates(src: string): string[] {
  const stripped = stripComments(src)
  return EMPTY_STATE_LITERALS.filter((lit) => stripped.includes(lit))
}

/** 从源码里抽出「不存在」类断言命中（去注释） */
export function findNotFoundStates(src: string): string[] {
  const stripped = stripComments(src)
  return NOT_FOUND_LITERALS.filter((lit) => stripped.includes(lit))
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

/** 渲染「不存在 / 已被删除」类事实性断言的文件（详情面；issue #8057 的 ⑥ 判据面） */
const notFoundFiles = files.filter((f) => findNotFoundStates(text.get(f) ?? '').length > 0)

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
    const entries = Object.keys(ledger.ledger)
    const thin = Object.entries(ledger.ledger)
      .filter(([, e]) => typeof e.reason !== 'string' || e.reason.trim().length < 10)
      .map(([f]) => f)
    expect(thin, '这些条目缺理由').toEqual([])
    // 🔴 归零（issue #8057）：`customers/[id]/CustomerDetail.tsx` 修好后条目清零，冻结上界随之降到 0。
    // 「被清空骗绿」不缺人守：它由 ①（未登记即红）与 ⑥（不存在类）承担 —— 清空台账不会让一条真缺口变绿，
    // 只会让它当场**具名**报出来。这里只钉上界：条目数只许减、不许加（加 ⇒ 必须显式上调本常量 = 一次评审）。
    expect(entries.length, `台账条目数只许减、不许加（冻结上界 = ${FROZEN_ENTRY_MAX}）`).toBeLessThanOrEqual(
      FROZEN_ENTRY_MAX,
    )
  })

  /**
   * ⑥ 详情面「失败 ≠ 不存在」（issue #8057）。
   *
   * 病灶形态（本单修前）：`catch` 里只有 `toast.xxx`（≈4s 后消失），`order`/`ticket` 留在 `null`
   * ⇒ 页面印「订单不存在或已被删除 / 工单不存在或已被删除 / 客户不存在」——**故障画成事实性断言**。
   * 判据与 ① 同构：这类字面量出现 ⇒ 该文件必须有失败态锚点（否则登记台账并写理由）。
   */
  it('⑥ 渲染「不存在 / 已被删除」的详情面必须有失败态锚点（失败 ≠ 不存在）', () => {
    // 面自证：判据必须真的扫到了对象（否则改个文案就「静默全绿」）
    expect(notFoundFiles.length, '「不存在」类字面量的文件数不得为 0（规则坏了 ≠ 干净了）').toBeGreaterThan(0)
    expect(findNotFoundStates('<p>订单不存在或已被删除</p>')).toEqual(['不存在或已被删除'])
    expect(findNotFoundStates('// 修前这里印「订单不存在或已被删除」\nconst a = 1')).toEqual([])

    const unanchored = notFoundFiles.filter(
      (f) => !hasFailureAnchor(text.get(f) ?? '') && !(f in ledger.ledger),
    )
    expect(
      unanchored,
      '这些详情页会把「读不到」画成「不存在 / 已被删除」（比空态更误导：商家可能据此重开一张单）。\n'
        + '出口：失败分支与「真不存在」分支**分开** —— 失败侧用共享件 `ListLoadError`'
        + '（`testId="<页面>-load-error"` + 重试），只有服务端明确返回空时才印「不存在」；'
        + '确实不适用 ⇒ 登记进 frontend/admin-web/tests/unit/page-state-contract-ledger.json 并逐字写理由。',
    ).toEqual([])
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

  // ── ⑥（issue #8057）：详情面「失败 ≠ 不存在」 ──────────────────────────────
  it('🔴 详情面读失败画成「不存在」⇒ 判红（本单修前的现场形态）', () => {
    const src = '<p className="text-neutral-500 mb-4">订单不存在或已被删除</p>'
    expect(findNotFoundStates(src)).toEqual(['不存在或已被删除'])
    expect(hasFailureAnchor(src)).toBe(false)
  })

  it('✅ 「不存在」字面量 + 共享件 `ListLoadError` 的 testId prop ⇒ 放行', () => {
    const src = [
      '<ListLoadError testId="order-detail-load-error" message="订单详情加载失败" onRetry={f} />',
      '<p>订单不存在或已被删除</p>',
    ].join('\n')
    expect(findNotFoundStates(src).length).toBe(1)
    expect(hasFailureAnchor(src)).toBe(true)
  })

  it('✅ 对照读数：`data-testid` 形态的失败锚点照旧被认（不因新增 testId 分支而退化）', () => {
    expect(hasFailureAnchor('<div data-testid="production-error">加载加工单失败，请稍后重试</div>')).toBe(true)
    expect(hasFailureAnchor('<p>客户不存在</p>')).toBe(false)
  })
})
