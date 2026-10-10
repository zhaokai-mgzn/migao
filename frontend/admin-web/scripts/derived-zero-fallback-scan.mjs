#!/usr/bin/env node
// case_ids: DA-005, DA-006, UI-003
/**
 * 「读派生展示位不得 `?? 0` / `|| 0`」判据**单一源**（issue #6701）。
 *
 * ## 为什么要有它
 *
 * 商家电脑端工作台 `/dashboard` 在**经营数据读面失败**时，屏上**同时**出现两种信号：
 * 「数据加载失败：…（下方显示的仍是上次成功取到的值……）」**和** 金额卡上的 `¥0`
 * （「今日暂无新订单，销售额 ¥0」＋「本月销售额 ¥0」）。根因是
 * `frontend/admin-web/src/app/(dashboard)/dashboard/page.tsx` 把**没读到**的值折成了**真 0**
 * （`todaySales={stats?.todaySales ?? 0}`），于是
 *   ① 「今天销售额 ¥0」被读成「今天没卖出去」⇒ **错误经营判断**（涉钱 + 商家第一屏）；
 *   ② 同一屏两处信号互相打架（一个说失败、一个说 0）；
 *   ③ 还会**派生**假读数（客单价 `Math.round(todaySales / todayOrders)`）。
 *
 * 这是同族缺陷里最危险的一个：#6691 的「读面故障不得画成空态」管的是**列表/状态**，
 * 本条管的是**金额 / 数量 / 计数**（钱的读面）。
 * ⇒ 单个页面改一次不解决复发，所以本文件是那条**类级收口**：
 * 判据（`derivedZeroSites`）与台账（`LEDGER`）都只有这一份，守卫
 * `tests/unit/derived-zero-fallback-guard.test.ts` 与命令行（`node scripts/derived-zero-fallback-scan.mjs`）
 * **共用**它（不写第二份规则）。
 *
 * ## 判的是哪个形态（口径）
 *
 * 一个 `?? 0` / `|| 0` **算命中** ⇐ 它**直接**落在一个「读派生展示位」上：
 *   - **展示名属性**：JSX 属性 / 对象属性名命中 `DISPLAY_SLOT_RE`
 *     （`value` / `count` / `sales` / `revenue` / `amount` / `todaySales` / `pendingCount` …）；
 *   - **格式化调用实参**：调用表达式名命中 `METRIC_CALL_RE`（`fmtCurrency` / `formatYuan` /
 *     `toLocaleString` …），即「坏值被印成一个可读数字」那条路径。
 *
 * 🔴 **正确形态**：读不到 ⇒ 渲染 `--`（本仓既有形态：`TodayOverviewBar` 的洞察句、
 * 待处理卡、订单状态分布…），**真 0 仍显示 `0`**（口径同
 * `frontend/bmini-app/src/services/dashboardService.ts` 的 `formatYuan`
 * —— 只有 `null` / `undefined` / 非有限值才落 `DASHBOARD_EMPTY_VALUE`）。
 *
 * 🔴 **有意不判**（实测区分过，别把它们当漏网）：
 *   - `?? 0` **不落在**展示位上（`setX(s.f ?? 0)` 状态聚合、
 *     `(r.salesQty || 0) / max * 100` 进度条宽度、`getBoundingClientRect().width || 0`
 *     量宽度、`Number(x ?? 0)` 计算）—— 它们是计算面 / 布局面，不是「把坏值印成读数」；
 *   - `state.count ?? 0`（外层是成员访问）—— 由属性名规则看，那个名字是**对象自己**的字段名，
 *     不是展示位名。
 * ⚠️ 判据**有意宽松**（会漏）：经中间变量（`const v = stats?.x ?? 0; <Card value={v} />`）、
 * `{...props}` 展开、跨行变量传递都判不出来 —— 那半边由**实例判据**（本包
 * `tests/unit/pages/dashboard.test.tsx` 的 #6701 用例）承担，见守卫里的局限声明。
 *
 * ## 台账（`LEDGER`，**只许缩短**）
 *
 * 命中点必须登记：**未登记即红**。键 = `仓库相对路径::展示位名::表达式文本`
 * —— 故意**不带行号**（一行新增就会把台账顶失效，本仓 #4668 的教训），
 * 而在**同符号内改删行**下是稳定的。
 * 登记点**不再命中**（修好了 / 表达式改了）⇒ 当场红，逼着同批删干净、不留僵尸豁免。
 *
 * ## 边界（照实登记，§19.1）
 *
 * - 只扫**工作台文件族**（`SCOPE`）：`src/app/(dashboard)/dashboard/page.tsx` +
 *   `src/components/dashboard/**`。**全仓同类存量不在本台账内**（如实登记，不冒充已覆盖）：
 *   实测另有 4 处命中（`src/app/(dashboard)/finance/page.tsx` 的 `fmtMoney(value ?? 0)`、
 *   `src/app/(dashboard)/inbound-orders/new/page.tsx` ×2、`src/app/(dashboard)/orders/new/page.tsx` ×1）
 *   —— 它们属别的文件族（本单边界「只改工作台页及其金额/指标展示组件」），未修、未收编。
 * - 只认源码**文本/AST 形态**，不判运行时行为；「服务端下发的 message 里带假 0」不在射程。
 * - 与 `read-failure-empty-state-scan.mjs`（#6663 / #6691）**不互为副本**：那条判「catch 清空读数
 *   且不表达失败」，本条判「读派生的展示位被折成 0」；两表不互重判。
 */
import { readdirSync, statSync, readFileSync } from 'node:fs'
import { join, relative } from 'node:path'
import ts from 'typescript'

/**
 * 判据面（工作台文件族）。目录名带括号，所以**逐个文件/目录**列，
 * 不用 `walk` 去猜一个通配（`(dashboard)` 在 shell / glob 里都是特殊字符）。
 */
export const SCOPE = [
  'src/app/(dashboard)/dashboard/page.tsx',
  'src/components/dashboard',
]

/**
 * 指标词（读派生的**金额 / 数量 / 计数 / 占比**）。命中 = 「坏值会被印成读数」的那一族。
 *
 * 🔴 判定用**分词**（camelCase / `_` / `-` / 数字边界切开）**逐词比对**，不是整名正则 ——
 * 实测：整名正则 `/^(value|count|…)$/` 会把 `pendingOrders`（尾词 `orders`）**判漏**
 * （改前 `count` 能中、`pendingOrders` 中不了，同一形态两种结果）；而前缀通配 `^[a-z]*orders$`
 * 又会把 `data-id` 一类吞进来。分词既覆盖「前缀 + 指标名」的写法，也不会跨边界误入。
 */
export const METRIC_WORDS = new Set([
  'value', 'count', 'sales', 'sale', 'revenue', 'amount', 'order', 'orders',
  'total', 'num', 'qty', 'quantity', 'rate', 'percent', 'pct', 'price', 'fee',
  'balance', 'deviation', 'stock', 'figure', 'change', 'money', 'yuan', 'sum', 'currency',
])

/** 命名分词：`pendingOrders` → `['pending','orders']`、`ai_session_rate` → `['ai','session','rate']` */
export function wordsOf(name) {
  return String(name)
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .split(/[^A-Za-z0-9]+/)
    .filter(Boolean)
    .map((w) => w.toLowerCase())
}

/** 这个名字是不是「读派生展示位」（属性名 / 格式化调用名都走它） */
export function isDisplayName(name) {
  return wordsOf(name).some((w) => METRIC_WORDS.has(w))
}

/**
 * 这些**不是展示位**，是写面 / 事件面（命中即假红，逐条给理由 —— 不许凭感觉加）：
 *   - `setX(...)` / `setXxxCount(...)`：**状态 setter**（`setLowStockCount(s.lowStockItems ?? 0)`
 *     是「读到了才写状态」，不产生屏上读数）；
 *   - `onX(...)` / `handleX(...)`：事件处理器（入参是事件对象，不是读数）；
 *   - 任何**成员调用**（`x.toFixed(...)` / `obj.formatSales(...)`）：判据面只认本文件里的裸函数名，
 *     成员调用的语义判不了（可能根本不是展示）。
 */
export function isNonDisplayCallee(calleeText) {
  const bare = calleeText.includes('.') ? '' : calleeText
  return bare === '' || /^(set|on|handle)/.test(bare)
}

/**
 * 回退到**字面量 0**（数字 `0` / 字符串 `'0'` / `"0"`）—— 两种写法是同一个病：
 * 「读不到」被印成「0」。（实测：`dashboard/page.tsx` 的 `stats?.todayOrders?.toLocaleString() || '0'`
 * 与 `?? 0` 在屏上长得一模一样。）
 */
const ZERO_FALLBACK_RE = /^(\?\?|\|\|)\s*(0|'0'|"0")$/

/**
 * 判据本体（**只吃一段源码**）。
 *
 * 🔴 抽出来是为了让守卫能用**内存里的假源码**做判别力自证（坏形态判红 / 好形态不红），
 *   而**不是**在测试里抄一份正则 —— 抄的那份会漂移，自证就成了自说自话。
 *
 * @param {string} source 源码文本
 * @param {{file?: string}} [opts] `file` 只用于台账键的前缀（自证传 `'probe.tsx'`）
 * @returns {Array<{file: string, line: number, slot: string, expression: string, key: string, within: string|null}>}
 */
export function derivedZeroSitesFromSource(source, { file = '<probe>.tsx' } = {}) {
  const sf = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  /** @type {Array<{file: string, line: number, slot: string, expression: string, key: string, within: string|null}>} */
  const out = []
  /** @param {import('typescript').Node} node */
  const visit = (node) => {
    if (ts.isBinaryExpression(node)) {
      const op = node.operatorToken.getText(sf)
      if ((op === '??' || op === '||') && ZERO_FALLBACK_RE.test(`${op} ${node.right.getText(sf).trim()}`)) {
        const slot = displaySlotOf(node, { tsModule: ts })
        if (slot) {
          const expression = node.getText(sf).replace(/\s+/g, ' ').trim()
          out.push({
            file,
            line: sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1,
            slot,
            expression,
            key: `${file}::${slot}::${expression}`,
            within: ownerOf(node, sf),
          })
        }
      }
    }
    ts.forEachChild(node, visit)
  }
  ts.forEachChild(sf, visit)
  return out
}

/**
 * 这个 `?? 0` / `|| 0` **直接**落在哪个展示位上？不在 ⇒ `null`（有意不判）。
 *
 * @param {import('typescript').Node} fb 回退表达式本体
 * @param {{tsModule?: typeof ts}} [opts]
 * @returns {string|null} 展示位名（或格式化的调用名）
 */
export function displaySlotOf(fb, { tsModule = ts } = {}) {
  let cur = fb
  let parent = fb.parent
  // 穿过「透明」节点：JSX 花括号表达式 / 括号 / 非空断言都不改变「这值被印在哪」
  // （实测：`<X value={a ?? 0} />` 里 `?? 0` 的直接父节点是 **JsxExpression** 而不是 JsxAttribute
  //   —— 只看直接父节点会把这一族**全判漏**。首版实现就是踩了这个坑。）
  while (
    parent &&
    (tsModule.isJsxExpression(parent) ||
      tsModule.isParenthesizedExpression(parent) ||
      tsModule.isNonNullExpression(parent))
  ) {
    cur = parent
    parent = parent.parent
  }
  if (!parent) return null
  // ① 展示名属性（JSX 属性 / 对象字面量属性）
  if (tsModule.isJsxAttribute(parent) || tsModule.isPropertyAssignment(parent)) {
    const name = parent.name
    // 短横线属性名（`data-x`）是字面量形态，判据面不认它
    if (name && tsModule.isIdentifier(name) && isDisplayName(name.text)) return name.text
    return null
  }
  // ② 「坏值被印成可读数字」的那条路径：格式化调用（`fmtCurrency(...)` / `toLocaleString()`）
  if (tsModule.isCallExpression(parent)) {
    // 只有这个回退值就是**整体入参**时才算落在格式化位上（`fmtCurrency(a ?? 0)` ✓ /
    // `toLocaleString(a, b ?? 0)` ✗ —— 后者是参数不是被印的值）
    if (!parent.arguments.some((a) => a === cur)) return null
    if (isNonDisplayCallee(parent.expression.getText())) return null
    const callee = tsModule.isPropertyAccessExpression(parent.expression)
      ? parent.expression.name.getText()
      : parent.expression.getText()
    if (isDisplayName(callee)) return callee
  }
  return null
}

/**
 * 最近的**具名承载体**（组件 / 函数 / 变量）—— 只用于**报告时定位**，不进台账键
 * （台账键刻意不用行号，见文件头）。
 *
 * @param {import('typescript').Node} node
 * @param {import('typescript').SourceFile} sf
 */
function ownerOf(node, sf) {
  let cur = node.parent
  while (cur) {
    if (ts.isFunctionDeclaration(cur) && cur.name) return cur.name.text
    if ((ts.isArrowFunction(cur) || ts.isFunctionExpression(cur)) && cur.parent) {
      const p = cur.parent
      if (ts.isVariableDeclaration(p) && ts.isIdentifier(p.name)) return p.name.text
      if (ts.isPropertyAssignment(p)) return p.name.getText(sf)
    }
    cur = cur.parent
  }
  return '<module>'
}

/** 收集判据面里的文件（**按 `SCOPE` 显式列**，不递归猜目录名）。 */
export function scopeFiles(root) {
  /** @type {string[]} */
  const out = []
  /** @param {string} p */
  const push = (p) => {
    const st = statSync(p)
    if (st.isDirectory()) {
      for (const entry of readdirSync(p)) {
        const full = join(p, entry)
        if (statSync(full).isDirectory()) push(full)
        else if (/\.tsx?$/.test(entry)) out.push(full)
      }
    } else if (/\.tsx?$/.test(p)) out.push(p)
  }
  for (const rel of SCOPE) push(join(root, rel))
  return out.sort()
}

/**
 * 命中清单（**单一源**）。
 *
 * @param {string} root 仓库内 `frontend/admin-web` 的绝对路径
 * @returns {{files: string[], sites: ReturnType<typeof derivedZeroSitesFromSource>}}
 */
export function derivedZeroSites(root) {
  const files = scopeFiles(root)
  /** @type {ReturnType<typeof derivedZeroSitesFromSource>} */
  const sites = []
  for (const file of files) {
    const rel = relative(root, file)
    sites.push(...derivedZeroSitesFromSource(readFileSync(file, 'utf8'), { file: rel }))
  }
  return { files: files.map((f) => relative(root, f)), sites }
}

/**
 * 豁免台账（**只许缩短**）：登记「确有必要 / 属别的文件族存量债」的命中点。
 *
 * 键 = `仓库相对路径::展示位名::表达式文本`（见 `derivedZeroSitesFromSource` 的 `key`）。
 * **失效即红**：该点改对之后必须**同批删掉**这一条。
 *
 * ⚠️ 只登记**本文件族内**的点。本包的**目标形态 = 空数组**（工作台文件族零命中），
 * 见守卫的双向相等断言。
 *
 * @type {string[]}
 */
export const LEDGER = []

/** 命令行：`node scripts/derived-zero-fallback-scan.mjs`（只读、报告型；有命中 ⇒ exit 1）。 */
if (process.argv[1] && import.meta.url.endsWith(process.argv[1].split('/').pop() ?? '')) {
  const { files, sites } = derivedZeroSites(process.cwd())
  console.log(`判据面：${files.length} 个文件（${SCOPE.join(' + ')}）`)
  for (const s of sites) console.log(`  命中 ${s.key}  （${s.file}:${s.line} @ ${s.within}）`)
  const unregistered = sites.filter((s) => !LEDGER.includes(s.key))
  const stale = LEDGER.filter((k) => !sites.some((s) => s.key === k))
  if (unregistered.length) console.log(`未登记：${unregistered.length} 条（未登记即红）`)
  if (stale.length) console.log(`台账失效：${stale.length} 条（只许缩短，修好即删）`)
  process.exit(unregistered.length || stale.length ? 1 : 0)
}
