// case_ids: UI-110
/**
 * 类级元守卫（issue #7065，#7007 的 P3）：**商家后台的页面头只有一个来源**。
 *
 * ## 病灶（P0/P1/P2 只做了「逐页迁移」，没有拦住「下一个」）
 *
 * #7012 把订单页那套打磨提炼成 `PageHeader` / `PageCard` / `SearchPanel` 三个原语，
 * 并**逐页迁移**了 14 个页面。但**没有任何东西**阻止「下一个新页面再手写一个 `<h1>` 回去」——
 * 而手写形态的默认结局就是那个已被诊断过的坏形态：
 *
 * ```
 * <h1 className="text-xl font-semibold text-neutral-900">生产看板</h1>
 * ```
 *
 * `frontend/admin-web/src/lib/design-tokens.ts` 的 `TYPE_SCALE` 规定 **h1 = `text-2xl`**、
 * h2 = `text-xl` ⇒ 手写 `text-xl` 的页面标题与**页内区块标题同档**，视觉层级读不出来。
 * 这正是用户 2026-10-16 说的「只有订单管理精美」的三条根因之一
 * （另两条：内层容器缺 `shadow-card` ⇒ 边框套边框；筛选区形态不一）。
 *
 * ## 本判据锁什么
 *
 * 射程 = `frontend/admin-web/src/app/(dashboard)/**` 下：
 *   · 每个 `page.tsx`，以及
 *   · 「细则类页面组件」（路径形如 `*/` + 动态段 + `/*.tsx` —— 它们才是真正的页头承载者，
 *     路由 `page.tsx` 只是薄壳）。
 *
 * 两条判据，各自能单独变红：
 *
 * | # | 判据 | 怎么红 |
 * |---|---|---|
 * | 1 | 射程内每个文件的**页头必须来自 `PageHeader`**；仍在手写 `<h1>` 的 ⇒ 必须在**冻结快照**里 | 注入：把某页 `<PageHeader>` 换回手写 `<h1>` ⇒ 红（未登记） |
 * | 2 | **快照只许缩短**（迁移一项销一项）+ 不许有**陈旧条目**（已迁完还留在快照里）+ 快照不许增长 | 把已迁完的一项留在快照 / 往快照里加项 ⇒ 红 |
 *
 * 外加**判别力自证**与 **fail-closed**（扫描面取空 ⇒ 红，不许静默空跑成绿）。
 *
 * ## 射程外（有意，逐条给理由）
 *
 * - `src/app/(corporate)/**` —— 官网子树，`warm-token-palette-guard.test.ts` 已把它列进
 *   `EXCLUDED_PREFIXES`（自有对外口径，不是「商家后台」这条射程）；
 * - `login` / `register` / `change-password` —— auth 页有**自己的**守卫
 *   `auth-pages-warm-token-guard.test.ts` 与自成一套的版式；
 * - 本判据**只判「页头唯一来源」**，**不判**页面是否真的更精美（那是 §15.7 读图 + 人裁定）；
 *   也**不判**内层容器是否都上了 `shadow-card`、筛选区是否都统一（#7012 的另两条根因）。
 *
 * ## 未固化项（照实登记，§19.1）
 *
 * 「`PageHeader` 被用了、但**传参**是否合理（标题是否与侧边栏同名 / 副标题是否重复标题）」判不了 ——
 * 那是文案与信息架构判断，不是形态判据。
 */

import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, sep } from 'node:path'
import { describe, expect, it } from 'vitest'

const APP_DIR = 'src/app'
const DASHBOARD_DIR = join(APP_DIR, '(dashboard)')
/** 官网子树在射程之外（与 `warm-token-palette-guard.test.ts` 同口径）。 */
const EXCLUDED_PREFIXES = [join(APP_DIR, '(corporate)')]

/**
 * 🔴 **存量债务快照 —— 只许缩短**（issue #7065）。
 *
 * 逐条 = 「有 `<h1>` 但没用 `PageHeader`」的文件。**迁移一项就从此处销一项**（销账会红，防止留陈旧条目）。
 * 新增页面**不得**往这里加（判据 2 会拦）。
 */
const LEGACY_PAGE_HEADER_SNAPSHOT: readonly string[] = [
  'src/app/(dashboard)/after-sales/[id]/AfterSalesDetail.tsx',
  'src/app/(dashboard)/agent-workspace/human-sessions/page.tsx',
  'src/app/(dashboard)/agent-workspace/sessions/page.tsx',
  'src/app/(dashboard)/knowledge/page.tsx',
  'src/app/(dashboard)/orders/[id]/OrderDetail.tsx',
  'src/app/(dashboard)/orders/[id]/ship/ShipOrder.tsx',
  'src/app/(dashboard)/orders/new/page.tsx',
  'src/app/(dashboard)/orders/page.tsx',
  'src/app/(dashboard)/processing-orders/[id]/production/page.tsx',
  'src/app/(dashboard)/production/page.tsx',
  'src/app/(dashboard)/production/piecework/page.tsx',
  'src/app/(dashboard)/production/pool/page.tsx',
  'src/app/(dashboard)/production/remnants/page.tsx',
  'src/app/(dashboard)/production/saving-board/page.tsx',
  'src/app/(dashboard)/products/[id]/ProductDetail.tsx',
  'src/app/(dashboard)/settings/page.tsx',
]

/** 快照的**上界**：只许缩短 ⇒ 现取长度不得大于它（新增不得借快照吸收）。 */
const SNAPSHOT_UPPER_BOUND = LEGACY_PAGE_HEADER_SNAPSHOT.length

/** 旧形态的指纹：手写 `text-xl`（h2 档）+ `font-semibold` 的标题类。 */
const LEGACY_H1_RE = /className="[^"]*text-xl font-semibold/

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (p.endsWith('.tsx')) out.push(p)
  }
  return out
}

/**
 * 该路径是否在射程内（**纯函数，便于自证**）。
 *
 * 判定 = 「是 `page.tsx`」**或**「位于动态路由段（路径含方括号）之下」：
 *   · 后者覆盖细则类页面组件 —— 它们才是真正的页头承载者，而路由 `page.tsx` 只是薄壳；
 *   · ⚠️ 用「路径含方括号」而不是「`/<段>/<文件>.tsx` 一层」：实测
 *     `orders/[id]/ship/ShipOrder.tsx` 是**两层**（`/[id]/ship/`），一层正则会把**已有页头**的它漏出射程，
 *     从而让「陈旧条目」判据把它误报成「已迁好」。
 *   · 有意排除 `layout.tsx`（外壳，页头不属于它）与 `error.tsx`（错误边界，无页头语义）。
 */
export function inScope(rel: string): boolean {
  if (EXCLUDED_PREFIXES.some((ex) => rel.startsWith(ex))) return false
  if (rel.endsWith('/layout.tsx') || rel.endsWith('/error.tsx')) return false
  return rel.endsWith('/page.tsx') || rel.includes('[')
}

/** 射程内的文件（相对 `frontend/admin-web` 的仓库内相对路径）。 */
export function inScopeFiles(): string[] {
  return walk(DASHBOARD_DIR)
    .map((p) => p.split(sep).join('/'))
    .filter(inScope)
    .sort()
}

/** 该文件是否手写 `<h1>`（未走原语）。 */
export function hasHandWrittenH1(text: string): boolean {
  return /<h1[\s>]/.test(text)
}

/**
 * 该文件是否**真的把 `PageHeader` 用作组件**（`<PageHeader …>`）。
 *
 * 🔴 必须是「JSX 里用到了」，**不是**「文件里出现过 `PageHeader` 这个词」——
 * 后者会被**残留的 import** 满足：把 `<PageHeader title="x" />` 换回手写 `<h1>` 而**忘了删 import** 时，
 * 「出现过」仍为真 ⇒ 判据**放行**。本判据的第一版就是这么写的，红证① 当场把它抓出来（7 passed 而应红）。
 * ⇒ 判据形态必须锚在**使用点**上。
 */
function usesPageHeader(text: string): boolean {
  return /<PageHeader[\s/>]/.test(text)
}

/** → 现取「有 h1 但没用 PageHeader」的文件（射程内）。 */
export function legacyHeaderFiles(files: string[] = inScopeFiles()): string[] {
  return files
    .filter((rel) => {
      const text = readFileSync(rel, 'utf8')
      return hasHandWrittenH1(text) && !usesPageHeader(text)
    })
    .sort()
}

// ────────────────────────────── 判据 1 ──────────────────────────────

describe('判据 1：射程内页头必须来自共享原语', () => {
  it('有 <h1> 却没用 PageHeader 的文件必须全部在冻结快照里', () => {
    const files = inScopeFiles()
    expect(files.length).toBeGreaterThan(20) // 反空跑：射程塌了要出声
    const legacy = legacyHeaderFiles(files)
    const snapshot = new Set(LEGACY_PAGE_HEADER_SNAPSHOT)
    const unregistered = legacy.filter((p) => !snapshot.has(p))
    expect(unregistered, `这些文件手写了 <h1> 却没用 PageHeader（issue #7065）：\n  ${unregistered.join('\n  ')}\n改用 frontend/admin-web/src/components/ui/PageHeader.tsx（h1 = text-2xl 档）`).toEqual([])
  })
})

// ────────────────────── 判据 2：快照只许缩短 ──────────────────────

describe('判据 2：存量快照只许缩短（销账是必须动作）', () => {
  it('已迁完的项必须从快照销账（陈旧条目 ⇒ 红）', () => {
    const legacy = new Set(legacyHeaderFiles())
    const stale = LEGACY_PAGE_HEADER_SNAPSHOT.filter((p) => !legacy.has(p))
    expect(stale, `这些文件已经迁好了，必须从 LEGACY_PAGE_HEADER_SNAPSHOT 里删掉（只许缩短）：\n  ${stale.join('\n  ')}`).toEqual([])
  })

  it('快照长度不得超过上界（新增不得借快照吸收）', () => {
    expect(LEGACY_PAGE_HEADER_SNAPSHOT.length).toBeLessThanOrEqual(SNAPSHOT_UPPER_BOUND)
  })

  it('快照项必须去重且都是真实存在、仍在射程内的文件', () => {
    expect(new Set(LEGACY_PAGE_HEADER_SNAPSHOT).size).toBe(LEGACY_PAGE_HEADER_SNAPSHOT.length)
    const inScopeSet = new Set(inScopeFiles())
    for (const p of LEGACY_PAGE_HEADER_SNAPSHOT) {
      expect(inScopeSet.has(p), `快照项 ${p} 不在射程内（路径错了 / 已被删除）`).toBe(true)
    }
  })
})

// ──────────────────── 判别力自证 + fail-closed ────────────────────

describe('判别力自证与 fail-closed', () => {
  it('坏形态判红、好形态放行（纯函数级）', () => {
    expect(hasHandWrittenH1('<h1 className="text-xl font-semibold text-neutral-900">生产看板</h1>')).toBe(true)
    expect(hasHandWrittenH1('<h2 className="text-xl font-semibold">区块</h2>')).toBe(false)
    expect(usesPageHeader("<PageHeader title=\"生产看板\" />")).toBe(true)
    expect(usesPageHeader('<div>no header primitive here</div>')).toBe(false)
    // 🔴 关键反例：**只剩 import**（用点被换回手写 h1 但忘了删 import）⇒ 不算「用过」
    expect(usesPageHeader("import { PageHeader } from '@/components/ui'\n<h1>手写</h1>")).toBe(false)
    // 旧类指纹与「手写 h1」是两件事：h2 用 text-xl 是**合法**的（TYPE_SCALE 的 h2 档）
    expect(LEGACY_H1_RE.test('<h2 className="text-xl font-semibold">区块</h2>')).toBe(true)
    expect(hasHandWrittenH1('<h2 className="text-xl font-semibold">区块</h2>')).toBe(false)
  })

  it('fail-closed：射程目录取不到 / 取空 ⇒ 抛（不许静默空跑成绿）', () => {
    expect(() => inScopeFiles.call(null)).not.toThrow() // 正常调用不抛
    expect(() => walk('src/app/__no_such_dir__')).toThrow()
  })

  it('射程里的文件都真实存在且非空', () => {
    for (const p of inScopeFiles()) {
      const text = readFileSync(p, 'utf8')
      expect(text.length, `${p} 是空文件`).toBeGreaterThan(0)
    }
  })
})
