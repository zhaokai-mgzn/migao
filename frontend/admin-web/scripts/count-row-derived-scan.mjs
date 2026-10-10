#!/usr/bin/env node
// case_ids: UI-057, UI-058
/**
 * 「**计数行不得从一个可能失败的读派生数字**」判据**单一源**（issue #6703）。
 *
 * ## 为什么要有它
 *
 * 后端整体不可用（注入 `/api/admin/**` → 500）时，失败**只由瞬时 toast 宣告**（≈4s 消失），
 * 而**永久面**上仍留着事实性断言：列表页尾那行「**共 0 条**」/ Pagination 的「**共 0 条记录**」。
 * 商家看一眼 toast 回到屏幕，只看到零 ⇒ 会被读成「今天没有订单 / 没有客户」——
 * 与 #6691（读面故障不得画成空态）同族，只是**承载体从「列表」换成了「计数行」**：
 * `total` 的初值是 0，读失败时**没人**告诉它这个 0 不可信。
 *
 * 本仓**已有更严的标准**（#6691）：`inbound-orders` / `stock-ledger` 等页已落**持久**失败锚点。
 * 本判据把那条标准**类级化**到计数行：**只修这一处 = 没修**。
 *
 * ## 判的是哪个形态（口径）
 *
 * 一条「计数行」= 屏上印着**读面派生数字**的那一行。三种承载体：
 *   - 本仓三种形态：① 字面量 `共 … 条` / `共 … 条记录`（含 JSX 里的模板串）；
 *     ② 共享 `Pagination`（它内部就印「共 N 条记录」）；
 *     ③ **派生计数格**（issue #6721）：`value={sessions.length}` 一类**格子里的计数**
 *        —— 集合来自 `useXxxStore()` 的一次**可能失败的读**（见下面第三种的完整口径）。
 *   前两种：文件同时**存在计数行** 且 **有 `total` 类读数状态**（`setTotal` / `setXxxTotal`）时，
 *   该计数行印的就是**可能失败的读**派生来的数字。
 *   门槛（实测校准，防假红）：只有 `setXxxTotal`（`Xxx` 非空）而**没有**字面量 `共` 的页面
 *   不算命中 —— 例如 `/production/remnants` 的「共 N 块」由 `data?.page?.total` **内联**读，
 *   没有 `total` state（那一页归 **#6702**，见本文末尾的边界声明）。
 *
 * 命中后**必须**满足下面任一条，否则判红：
 *   - **有读面失败标记**：该文件出现读面失败锚（见 `FAILURE_MARKERS`）——
 *     即失败在**本文件的屏上**看得见（锚点 / 失败 state / 重试出口）；
 *   - **登记进 `LEDGER`**（只许缩短）—— 存量债如实记账（本包文件族之外的页面）。
 *
 * 🔴 **为什么「有失败标记」够了**：计数行与失败面**同屏** ⇒ 商家读到的不是孤零零的 0，
 * 而是「读不到 ⇒ 这行数不可信」。这正是 #6691 已立的口径；本判据只把它**扩到计数行**。
 *
 * ## 边界（照实登记，不许含糊）
 *
 * - **射程** = `frontend/admin-web/src/app/(dashboard)` + `frontend/admin-web/src/components`，
 *   只认**源码文本形态**（判不了「失败面渲染得够不够显眼」——那是 §15.7 读图的面）；
 * - 与并发包的**扫描面边界**（各扫各的，不互判）：
 *   · **#6701** = 工作台**金额面**（`scripts/derived-zero-fallback-scan.mjs`）；
 *   · **#6702** = 余料页（`/production/remnants`）的读失败文案 / 计数 —— 另建；
 *   · **#6713/#6714** = 「读失败不得画成**空态**（`暂无…` 文案）」—— `scripts/read-failure-empty-state-scan.mjs`
 *     （判据面 = **空态文案**有没有在场门；本页**没有任何空态文案** ⇒ 本页属本判据，不挂那支）；
 *   · **本判据（#6703 + #6721）** = **列表页计数行 + 共享 `Pagination` + 派生计数格**；
 * - 集成侧的同族普查（A 涉钱展示位 4 / B 图表 3 / C 分页计数 8 / D 正例 1 = `piecework` 的
 *   `!error` 守卫，**不许判红**）记在 **#6701** 的评论里，本文件**不重复**那份清单；
 * - **有意不判**「屏上印的是服务端返回的**行数**（`rows.length` / `items.length`）」——
 *   行数在失败时是 0，但它是**读数本身**、不是**另一个读**派生出来的断言（列表现状由 #6691 覆盖）；
 * - 「Pagination 的 `totalReliable` 有没有被传」**判不了**（要类型系统 / 运行时才知道），
 *   本判据只判「文件里存在失败标记」这一半 —— **未固化项照实登记**。
 */
import { readdirSync, statSync, readFileSync } from 'node:fs'
import { join, relative } from 'node:path'

/** 判据面（见「边界」：与 #6701 / #6702 各扫各的） */
export const SCOPES = ['src/app/(dashboard)', 'src/components']
const SKIP_DIRS = new Set(['node_modules', '.next', 'dist', 'coverage', '__pycache__'])

/**
 * 「这行印了一个可能失败的读派生来的数字」的两种承载体。
 * ⚠️ 字符串里同时含「共」与「条」才算（`共 N 行` / `共 N 套` 那是**本地数组长度**，不是读面派生——实测区分过）。
 */
const LITERAL_COUNT = /共[^\n]{0,60}条/
const SHARED_PAGINATION = /\bPagination\b/

/** `total` 类**读数状态**：`setTotal(` / `setTxnTotal(` / `setCandidatesTotal(` … */
const TOTAL_SETTER = /set([A-Za-z]*)Total\s*\(/g

/**
 * **读面失败标记**（判定「失败在本文件屏上看得见」）—— 逐条给理由，不许凭感觉加：
 * - `load-error` / `-load-failed`：既有失败态锚点（`data-testid`，本仓命名规范）；
 * - `-error` / `-retry`：失败态 / 重试出口的 testid（如 `stock-ledger-error` / `inbound-load-retry`）；
 * - `setXxxError(` / `setXxxFailed(`：失败 state（`loadFailed` / `summaryError` 一族）；
 * - `totalReliable`：本包给共享 `Pagination` 加的「不可信」标志；
 * - `role="alert"`：失败态被读屏器播报的形态。
 */
/** 列表读面的失败锚点：`data-testid="…-load-error"` / `testId="…-load-error"` / `totalReliable` */
// ⚠️ 两种写法**大小写不同**（实测踩过）：JSX 属性 = `testId`；HTML 属性 = `data-testid`（全小写 i）
const LIST_FAILURE_ANCHOR = /[Tt]est[Ii]d=["']?[A-Za-z0-9_-]*load-(error|failed|retry)|[Tt]est[Ii]d=["']?(stock-ledger-error|ledger-total-error)["']|totalReliable/

/**
 * 计数行是否已带「失败在本文件屏上看得见」的出口。
 *
 * 🔴 **口径的诚实边界**（实测校准，不许含糊）：本条**只认规范化锚点**
 * （`*-load-error` / `*-load-failed` / `*-load-retry` 的 testid，或 `totalReliable`）。
 * 为什么不用更宽的 `-error"` / `setXxxError(`：实测它们把**同一次误报**喂成绿 ——
 * `employees/page.tsx` 里另有**岗位下拉**的 `employees-positions-error`，
 * 而员工**列表**的 `共 0 条` 依旧没修（`setTotal(data?.total || 0)` + catch 只 toast）。
 * 宁可漏判（未修的被判绿）也不假绿：**漏判那一半由实例判据兜底**
 * （`tests/unit/pages/list-count-failure-instances.test.tsx`：注入读失败 ⇒ 屏上零「共 0 条」）。
 */
export function isGuarded(source) {
  return LIST_FAILURE_ANCHOR.test(stripComments(source))
}

function walk(dir, out = []) {
  let entries
  try {
    entries = readdirSync(dir)
  } catch {
    return out
  }
  for (const entry of entries) {
    if (SKIP_DIRS.has(entry)) continue
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) walk(full, out)
    else if (/\.tsx?$/.test(entry)) out.push(full)
  }
  return out
}

/**
 * 去注释（**只认屏上形态**：注释里写「共 0 条」不是计数行 —— 实测 `finance/page.tsx`
 * 的说明注释里就有这个串，直接匹配会假红）。
 */
export function stripComments(source) {
  let out = ''
  let i = 0
  let quote = null // `'` / `"` / `` ` `` —— 字符串里的 `//` 不是注释（实测踩过：`'—'` 把该行后半段吃掉了）
  while (i < source.length) {
    const c = source[i]
    if (quote) {
      if (c === '\\') {
        out += source.slice(i, i + 2)
        i += 2
        continue
      }
      if (c === quote) quote = null
      out += c
      i += 1
      continue
    }
    if (c === "'" || c === '"' || c === '`') {
      quote = c
      out += c
      i += 1
      continue
    }
    if (c === '/' && source[i + 1] === '/') {
      while (i < source.length && source[i] !== '\n') i += 1
      continue
    }
    if (c === '/' && source[i + 1] === '*') {
      // 正则字面量里的 `/*` 极罕见；注释块里本来也不该有计数行
      const end = source.indexOf('*/', i + 2)
      out += ' '
      if (end === -1) break
      i = end + 2
      continue
    }
    out += c
    i += 1
  }
  return out
}

// ═══════════════════════════════════════════════════════════════════════════════
// 第三种承载体：**派生计数格**（issue **#6721**，`/agent-workspace/sessions` 顶部监控统计条）
//
// 与上面两种的关系：① `共 N 条` 文本、② 共享 `Pagination` —— 都靠**一个 `setXxxTotal` 读数**判定。
// 本页两样都没有：它把「活跃 / 已结束 / 共 N」**直接**从 `store.sessions` 派生（`过滤 .length` / `.length`）
// 印在**格子里** ⇒ 上面两种字形都判不到它 —— 这正是它当初漏网的原因（#6718 的修复包如实报了「未改、未登记」）。
// ⇒ 本判据补第三种字形，**不新立第三把尺子**（issue #6721 的口径：挂已有的那一支）。
//
// 🔴 **口径与实测校准**（全仓实测，不是凭感觉）：
//   · **认**两种字形：「JSX 属性值 = 集合的 `.length`」**或**「文件里有一个统计条锚」
//     （`data-testid="…stats-bar"`）—— 后者是「这一族页面把多个读数并排印出来」的稳定结构锚；
//   · **集合必须来自 `useXxxStore()` 的解构**（`const { sessions } = useChatStore()`）——
//     这一条同时排掉两类假红：① 组件 props 里的数组（它的失败由调用方自己的读面负责）；
//     ② 页面本地 `useState([])`（没有外部读面，`.length` 是读数本身）。
//   · 实测射程：全仓命中 **1 个文件**（就是本页）。
//     两个「邻格」的实测对照（都在射程外，**不许**把它们判红）：
//     · `components/chat/SessionInsight.tsx` 的 `value={String(messageCount)}` 是**中转表达式**
//       （读不到时印 `''` 而不是 `0`，形态不同类）⇒ 有意不认；
//     · `components/products/SkuMatrix.tsx` 等 4 处 `rows.length` 来自**组件 props** ⇒ 有意不认。
// ═══════════════════════════════════════════════════════════════════════════════

/** 「JSX 属性 = 集合的 `.length`」字形 */
const VALUE_LENGTH = /\b(?:value|count|total)=\{\s*([A-Za-z_$][\w$]*)\.length\s*\}/g
/** 集合名来自一个**可能失败的读**（store hook 的返回物：`const { sessions } = useChatStore()`） */
const STORE_DESTRUCT = /\{([^}]*)\}\s*=\s*use[A-Za-z]*Store\s*\(/g
/** 统计条结构锚：`data-testid/TestId="…stats-bar"`（JSX 属性两种写法大小写不同） */
const STATS_BAR_ANCHOR = /[Tt]est[Ii]d=["'`][A-Za-z0-9_-]*stats-bar["'`]/

/**
 * 该文件是否「把某个集合的**派生计数**印在屏上」。
 *
 * 成立条件（两条同时）：
 *   ① 文件从 store hook 解构出集合（`useXxxStore()`）—— 集合来自一次**可能失败的读**；
 *   ② 屏上印了这个集合的派生计数（`value={X.length}`，或文件有统计条锚）；
 * 另有 `isGuarded` 那条出口（见 `countRowSitesFromSource`）：**有**规范化失败锚 ⇒ 该读数已有可信度信号
 * ⇒ 不判红。缺锚 ⇒ 判红（本页病灶原形：读失败时把「读不到」印成 `0`）。
 */
export function hasUnguardedDerivedCountCell(source) {
  const code = stripComments(source)
  const storeNames = new Set()
  for (const m of code.matchAll(STORE_DESTRUCT)) {
    for (const p of m[1].split(',')) {
      // `const { sessions, fetchSessions } = useChatStore()` / `const { sessions: rows } = …`
      const name = p.split(':').pop()?.trim()
      if (name) storeNames.add(name)
    }
  }
  if (!storeNames.size) return false
  // ② 「属性 = 集合的 .length」或「有统计条锚」都算「印了派生计数」
  const directCount = [...code.matchAll(VALUE_LENGTH)].some((m) => storeNames.has(m[1]))
  return directCount || STATS_BAR_ANCHOR.test(code)
}

/** 源码文本 → 命中点（**只吃一段源码**：守卫用它做判别力自证，不抄第二份正则） */
export function countRowSitesFromSource(source, { file = '<probe>.tsx' } = {}) {
  const code = stripComments(source)
  const totals = new Set()
  for (const m of code.matchAll(TOTAL_SETTER)) {
    // `setTotal(` / `setTxnTotal(` / `setCandidatesTotal(` —— 后两个取全名（`momentTotal` 与
    // `txnTotal` 是**两个**读数，各判各的）；裸 `setTotal` 记作它自己
    totals.add(m[0].slice(0, -1).replace(/^set/, '') || 'total')
  }
  const prints = []
  if (LITERAL_COUNT.test(code) && totals.size > 0) prints.push('literal-count')
  if (SHARED_PAGINATION.test(code) && totals.size > 0) prints.push('shared-pagination')
  // issue #6721：第三种承载体 —— 派生计数**格**（`value={sessions.length}`，无「共 N 条」文本、无 Pagination）
  if (hasUnguardedDerivedCountCell(source)) prints.push('derived-count-cell')
  // 判据：印了「共 N 条」**且**这个 N 来自 `setXxxTotal`（= 一个可能失败的读）；
  // 或印了「派生计数格」且该读数**没有**可信度信号（见 `hasUnguardedDerivedCountCell`）
  if (prints.length === 0) return []

  const guarded = isGuarded(source)
  return [
    {
      file,
      key: file,
      prints,
      totals: [...totals].sort(),
      guarded,
    },
  ]
}

/** 命中清单（**单一源**）：扫 `SCOPES` 下每个文件 */
export function countRowSites(root) {
  const files = []
  for (const scope of SCOPES) files.push(...walk(join(root, scope)))
  const rel = files.map((f) => relative(root, f)).sort()
  const out = []
  for (const r of rel) {
    out.push(...countRowSitesFromSource(readFileSync(join(root, r), 'utf8'), { file: r }))
  }
  return { files: rel, sites: out }
}

/**
 * 豁免台账（**只许缩短**）：登记「计数行由可能失败的读派生、但本包**有意不修**」的页面。
 *
 * 键 = **仓库相对路径**（不做符号线 —— 一个文件内的行号会漂）。
 * **失效即红**（`staleLedger`）：该文件改对之后必须**同批删掉**这一条。
 *
 * 本台账里的每一页都**同族、同病**（`/orders` 的病灶原形，issue #6703）：
 * 列表读失败 ⇒ `total` 停在 0 ⇒ 尾行照旧印「共 0 条记录」/ `0 条`。
 * 它们是本包文件族之外的**存量债**（本包 = `/orders` `/finance` `/customers` `/after-sales`
 * `/knowledge` `/stock-ledger` + 共享 `Pagination`），归零靠后续包逐批删条目 ——
 * **不是**「已修」，也**不是**「不算缺陷」。
 */
export const LEDGER = [
  // ── 存量债（`setXxxTotal` 由读响应赋值；文件里无读面失败标记）──
  //
  // 归零沿革（**只许缩短**，条目**删除**而非注释掉）：
  //   · `employees/page.tsx` / `notifications/page.tsx` —— **issue #6714 本包**补上
  //     `employees-load-failed` / `notifications-load-failed` 失败锚 + 重试出口
  //     （`totalReliable={!loadFailed}` 同步标「计数不可信」）⇒ 两条**同批删掉**；
  'src/components/employees/WorkerProfilesPanel.tsx', // 工人档案面板：同上
]

/**
 * 正向核：本包已改对的页面 ⇒ 必须**逐字**含失败态锚点（`data-testid` + 重试出口）。
 *
 * 为什么正向核不可省：扫描判据只证明「文件里**有**失败标记」——
 * 把 `loadError` 那句删掉、只留一个 `-error` 字符串注释也能绕过。
 * 这条锚住**渲染面**：删掉锚点 / 重试出口 ⇒ 当场红。
 */
export const FAILURE_ANCHORS = [
  { name: '订单列表计数行读失败', file: 'src/app/(dashboard)/orders/page.tsx', anchors: ['testId="orders-load-error"'] },
  { name: '资金流水计数行读失败', file: 'src/app/(dashboard)/finance/page.tsx', anchors: ['testId="finance-load-error"'] },
  { name: '应收对账计数行读失败', file: 'src/app/(dashboard)/finance/page.tsx', anchors: ['testId="finance-reconciliation-load-error"'] },
  { name: '客户列表计数行读失败', file: 'src/app/(dashboard)/customers/page.tsx', anchors: ['testId="customers-load-error"'] },
  { name: '售后工单计数行读失败', file: 'src/app/(dashboard)/after-sales/page.tsx', anchors: ['testId="after-sales-load-error"'] },
  { name: '知识卡片计数行读失败', file: 'src/app/(dashboard)/knowledge/page.tsx', anchors: ['testId="knowledge-load-error"'] },
  { name: '库存明细计数行读失败', file: 'src/app/(dashboard)/stock-ledger/page.tsx', anchors: ['testId="stock-ledger-error"'] },
  { name: '共享分页的「不可信」标志', file: 'src/components/ui/Pagination.tsx', anchors: ['totalReliable'] },
  // ── issue #6721：派生计数**格**（第三种承载体）──────
  { name: '会话监控统计条派生计数格读失败', file: 'src/app/(dashboard)/agent-workspace/sessions/page.tsx', anchors: ['data-testid="agent-sessions-load-failed"', 'data-testid="agent-sessions-load-failed-retry"', 'sessionsLoadFailed'] },
]

/** 命中清单（台账过滤后）：**未登记即红** */
export function offendersOf(root) {
  const { files, sites } = countRowSites(root)
  const offenders = sites.filter((s) => !s.guarded && !LEDGER.includes(s.key))
  return { files, sites, offenders }
}

/** 台账「空转」检测：登记了但**已不再命中 / 已不再需要**的条目（只许缩短 ⇒ 必须删） */
export function staleLedger(root) {
  const { sites } = countRowSites(root)
  const live = new Set(sites.filter((s) => !s.guarded).map((s) => s.key))
  return LEDGER.filter((k) => !live.has(k))
}

const isMain = process.argv[1] && import.meta.url.endsWith(process.argv[1].split('/').pop())
if (isMain) {
  const root = process.env.MIGAO_SCAN_ROOT || process.cwd()
  const { files, sites, offenders } = offendersOf(root)
  console.log(
    `扫描 ${files.length} 个文件 · 命中「计数行由可能失败的读派生」${sites.length} 处 ` +
      `（其中已带失败标记 ${sites.filter((s) => s.guarded).length} · 台账豁免 ${LEDGER.length}）\n`,
  )
  for (const s of sites) {
    const mark = s.guarded ? '✅ 有失败标记' : LEDGER.includes(s.key) ? '📒 已登记（存量债）' : '❌ 未登记'
    console.log(`  ${mark} ${s.key}  [${s.prints.join('/')}] total=${s.totals.join(',') || '—'}`)
  }
  const stale = staleLedger(root)
  if (stale.length) {
    console.log(`\n台账里这些条目**不再命中 / 已改对**，请删掉：\n  ${stale.join('\n  ')}`)
  }
  console.log(`\n未登记命中 ${offenders.length} 条 · 僵尸条目 ${stale.length} 条`)
  process.exit(offenders.length || stale.length ? 1 : 0)
}
