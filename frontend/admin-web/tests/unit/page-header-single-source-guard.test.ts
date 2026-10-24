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
 * <h1 className="text-xl font-semibold text-neutral-900">作业看板</h1>
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
  'src/app/(dashboard)/orders/[id]/OrderDetail.tsx',
  'src/app/(dashboard)/orders/[id]/ship/ShipOrder.tsx',
  'src/app/(dashboard)/processing-orders/[id]/production/page.tsx',
  'src/app/(dashboard)/products/[id]/ProductDetail.tsx',
]

/** 快照的**上界**：只许缩短 ⇒ 现取长度不得大于它（新增不得借快照吸收）。 */
const SNAPSHOT_UPPER_BOUND = LEGACY_PAGE_HEADER_SNAPSHOT.length  // 现取，随销账自动收紧

/** 「有意不迁」条目的**独立冻结上界**（现取 8；只许缩短，见判据 2 的最后一条）。 */
const PARKED_UPPER_BOUND = 7

/**
 * **有意不迁**的文件 + 逐条理由（issue #7065）。
 *
 * 这些文件的页头**不是**「标题 + 副标题 + 动作区」那种通用形态，而是与**自定义布局咬合**的：
 * 强行套 `PageHeader`（`text-2xl` + 自带外边距 + 两行结构）会把版式改坏 —— 那是**改版**，不是本单的「接原语」。
 *
 * ⚠️ 本清单不是「豁免台账」：每条都必须给出**为什么**，且守卫会断言「射程内未用原语的文件 = 快照 ∪ 本清单」
 * ⇒ **两边都不许有漏项**（既不能偷偷加一个手写 h1，也不能把文件挪进本清单了事而无理由）。
 * 重启条件：真要做这些页面的版式统一时，先给它们定「紧凑型页头」的形态，再逐条迁出本清单。
 */
const PARKED_WITH_REASON: ReadonlyArray<readonly [string, string]> = [
  ['src/app/(dashboard)/agent-workspace/sessions/page.tsx',
   '固定高度工具条（`h-14` + `border-b`）嵌在 `h-[calc(100vh-…)]` 的全高工作区里，标题是 `text-base`；PageHeader 的 text-2xl + 外边距会撑破该布局'],
  ['src/app/(dashboard)/agent-workspace/human-sessions/page.tsx',
   '同上（在线接待工作台，同族同布局）'],
  ['src/app/(dashboard)/orders/[id]/OrderDetail.tsx',
   '标题行右侧是**页面级唯一的「打印」入口**（issue #7544：打印与订单状态解耦，故不能落进任何状态分支）；且该页首屏还有发货明细读失败告警区，改页头要连带重排版式'],
  ['src/app/(dashboard)/orders/[id]/ship/ShipOrder.tsx',
   '标题行内含 `Zap` 图标，右侧是「打印发货单」+ 确认发货两个动作，与运单号表单是一体的'],
  ['src/app/(dashboard)/processing-orders/[id]/production/page.tsx',
   '加工单号是标题块的一部分（`加工单号 <span data-testid=…>`）+ 左侧返回按钮，属带上下文的详情页头'],
  ['src/app/(dashboard)/after-sales/[id]/AfterSalesDetail.tsx',
   '标题行内联状态徽标（`<Badge>`）+ 返回按钮，徽标属标题语义'],
  ['src/app/(dashboard)/products/[id]/ProductDetail.tsx',
   '标题是商品名 + 内联状态徽标；且用的是 `font-bold`（与 TYPE_SCALE 的 `font-semibold` 不一致，需单独裁定）'],
]

/** 「未用原语的射程内文件」必须**恰好**等于「快照 ∪ 有意不迁」。 */
export function unaccountedFiles(files: string[] = inScopeFiles()): string[] {
  const known = new Set([
    ...LEGACY_PAGE_HEADER_SNAPSHOT,
    ...PARKED_WITH_REASON.map(([f]) => f),
  ])
  return legacyHeaderFiles(files).filter((p) => !known.has(p))
}

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
  it('未用原语的文件必须**全部有交代**（冻结快照 ∪ 逐条给出理由的有意不迁）', () => {
    const files = inScopeFiles()
    expect(files.length).toBeGreaterThan(20) // 反空跑：射程塌了要出声
    const unaccounted = unaccountedFiles(files)
    expect(
      unaccounted,
      `这些文件手写了 <h1>、既不在冻结快照里、也没有说明为什么有意不迁（issue #7065）：\n  ${unaccounted.join('\n  ')}\n` +
        `改用 frontend/admin-web/src/components/ui/PageHeader.tsx（h1 = text-2xl 档）；` +
        `若确实是自定义版式 ⇒ 加进 PARKED_WITH_REASON 并**逐条写明理由**（不许只挪清单）。`,
    ).toEqual([])
  })

  it('🔴 「有意不迁」里不许留**陈旧项**（已迁原语的必须挪出清单）', () => {
    // 这一条是**补洞**：本判据第一版只查了「理由非空 + 在射程内」，
    // ⇒ `orders/new/page.tsx` **被迁移之后仍留在清单里**而**没有任何东西会红**
    //   （实测：它在清单里，但它其实已经用了 `<PageHeader>`）。
    // 快照那一侧有「陈旧条目 ⇒ 红」，清单这一侧当时**没有对偶的检查** —— 这就是那个缺口。
    const stillLegacy = new Set(legacyHeaderFiles())
    const stale = PARKED_WITH_REASON.map(([f]) => f).filter((f) => !stillLegacy.has(f))
    expect(
      stale,
      `这些文件已经用上原语（或不再手写 <h1>），必须从 PARKED_WITH_REASON 里挪出去：\n  ${stale.join('\n  ')}`,
    ).toEqual([])
  })

  it('有意不迁的每一条都必须带非空理由', () => {
    expect(PARKED_WITH_REASON.length).toBeGreaterThan(0)
    for (const [f, why] of PARKED_WITH_REASON) {
      expect(why.length, `${f} 的理由太短 / 为空（不许只挪清单）`).toBeGreaterThan(15)
      expect(inScope(f), `${f} 不在射程内 —— 清单里的路径错了`).toBe(true)
    }
  })

  it('但「有意不迁」也不许悄悄涨价：条目数有独立冻结上界', () => {
    // 与快照无关的**独立**上界：快照已清零，不能让它顺带变成「有意不迁可以无限长」。
    // 迁移一条出本清单 ⇒ 这里会红，必须**显式**改小这个数（= 一次有意识的决定）。
    expect(PARKED_WITH_REASON.length).toBeLessThanOrEqual(PARKED_UPPER_BOUND)
    expect(PARKED_WITH_REASON.length).toBeGreaterThan(0)
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
    expect(hasHandWrittenH1('<h1 className="text-xl font-semibold text-neutral-900">作业看板</h1>')).toBe(true)
    expect(hasHandWrittenH1('<h2 className="text-xl font-semibold">区块</h2>')).toBe(false)
    expect(usesPageHeader("<PageHeader title=\"作业看板\" />")).toBe(true)
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
