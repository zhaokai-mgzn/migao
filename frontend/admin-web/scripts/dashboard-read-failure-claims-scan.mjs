#!/usr/bin/env node
// case_ids: DA-005, DA-006, UI-003
/**
 * 「读失败不得与 `0 / 暂无数据` 式断言同屏」判据**单一源**（issue #6715）。
 *
 * ## 为什么要有它
 *
 * 独立盲复核在 main `2adad8660` 上、**登录前**就注入 `**` 打头的 dashboard 接口 ⇒ 500
 * （全程**无一次成功加载**）⇒ 等 6s 读屏，抓到两条**界面说的话与事实不符**：
 *
 * - **N1 仍印「共 0 单」**：订单状态分布区块那行「共 {total} 单」（`SPAN.text-xs.text-neutral-400`）
 *   —— `total = data.reduce(…)`，而 data 只是 useState([]) 的初值 ⇒ **读不到**被印成「共 0 单」
 *   （健康基线是「共 308 单」）；
 * - **N2 失败横幅承诺了做不到的事**：横幅逐字写「下方显示的仍是上次成功取到的值（**不是 0，
 *   也不是「暂无数据」**）」，而同屏事实是四卡占位符 ＋ **5 处「暂无…」** ＋ N1 的「共 0 单」
 *   ⇒ 它否认的两种误读**同时都在屏上**。它是为「有过上次成功值」写的，冷启动形态下是**假话**。
 *
 * 两句都是**承诺 / 断言**，而**没有任何判据守着它们**（这正是病根：一句没人守的承诺）。
 * 只把这一页改一次 = 没修：下一行「共 {x} 单」或下一句「暂无…」可以原样写回来而**无人变红**。
 *
 * ## 判的是哪个形态（口径）
 *
 * 面 = **工作台文件族**（SCOPE）—— `src/app/(dashboard)/dashboard/page.tsx` 与
 * `src/components/dashboard/**`。逐行（**相邻两行合并成一个语句窗口**后）判两种**事实性断言**：
 *
 * - **形态 ①：读派生的计数断言** —— 一行里出现「共 … 单」（N1 的承载体）。
 *   它的数字来自一个**可能失败的读**（`data.reduce(…)` / state 初值）⇒ 读失败时印 0。
 * - **形态 ②：「暂无…」空态断言** —— 一行里出现「暂无」开头的短文案（趋势图 / 销售额 /
 *   近期订单 / 排行 / 活跃会话 …）。读失败时这些**全部会渲染**，与失败横幅同屏 ⇒ N2 的假话。
 *
 * 每一个命中点**必须**在同一语句窗口里有 **在场门（gate）** 之一，否则**未登记即红**：
 *
 * | 门 | 逐字形态 | 说明 |
 * |---|---|---|
 * | 1 | `blockEnabled(` 或 `blockFailed(` | 页面为每一块算出「这块这次到底读到没有」，UI 只吃布尔位 |
 * | 2 | `blockErrors` 且含 ` in ` | 仓内既有形态：`!(<name> in blockErrors)` ⇒ 这一块这次是成功的 |
 * | 3 | `EMPTY_VALUE` 或字面量 `'—'` | 该处改成「读不到 ⇒ 印 —」（不渲染数字 / 空态文案） |
 *
 * 🔴 **为什么门是「词表 + 台账」而不是「语义分析」**：本仓静态面判不了「这个布尔位真的由读成功算出」
 *   （那要数据流分析）⇒ 判据只裁**形态**：**要么给出显式门、要么登记进 LEDGER**。
 *   台账 LEDGER 是**豁免台账**（本包**目标形态 = 空数组**）：条目**只许缩短**，
 *   且每条**必须仍真命中**（改好 / 删掉 ⇒ 僵尸条目当场红）。
 *
 * ## 与 #6701 `derived-zero-fallback-scan.mjs` 的**边界与自证**（两份台账互不判僵尸）
 *
 * | 面 | 扫描器 | 判什么 | 台账 |
 * |---|---|---|---|
 * | #6701 | `frontend/admin-web/scripts/derived-zero-fallback-scan.mjs` | **金额 / 数量派生展示位的零值字面量回退**（`metricText(todaySalesState, …)` 那一族；AST 判据：零值回退直接落在展示位属性 / 格式化调用实参上） | 空数组（工作台文件族零命中） |
 * | **本单 #6715** | 本文件 | **读面失败时的「事实性断言」上屏**：「共 N 单」计数断言 与 「暂无…」空态断言（**文本形态**） | 空数组（同族零未门命中） |
 *
 * 两份台账**互不判僵尸**的**机械理由**（不是口头承诺）：本文件的候选必须**同时**满足
 * 「含『共 … 单』或『暂无…』文案」，而零值回退字面量**一个都不含** ⇒ 本文件的命中集
 * 与 `derived-zero-fallback-scan.mjs` 的命中集**在形态上不相交**。自证：
 * 守卫测试 `tests/unit/dashboard-read-failure-claims-guard.test.ts` 的判别力自证里，
 * 对「派生展示位的零值回退」这一类**必须不报**（两把尺子各自只裁自己的形态）。
 *
 * ## 边界（照实登记，`migao-dev-flow` §19.1）
 *
 * - **只扫工作台文件族**（SCOPE）：别的文件族（`/stock-ledger` #6707、`/chat` `/employees`
 *   `/notifications` `/products` `/shipments` `/production/remnants` #6713/#6714）**不在本台账内**
 *   —— 那是别的包的写面，本判据**不冒充已覆盖**；
 * - **只认源码文本形态**：经中间变量传递的文案判不出来；门是**词表**判定
 *   （`blockEnabled` / `blockErrors` / 占位符），**判不了「这个布尔位真的对吗」**
 *   —— 那半边由**实例判据**承担：
 *   `frontend/admin-web/tests/unit/pages/dashboard.test.tsx` 的 #6715 用例（注入全挂 ⇒ 屏上不得出现
 *   「共 0 单」/「暂无…」；真 0 / 真无数据 ⇒ 照旧显示）；
 * - **横幅那句承诺本身**不在本扫描器的射程（它是「按有无历史成功值分流」的文案，形态是一句话、
 *   不是断言上屏）⇒ 由**正向核**（POSITIVE_ANCHORS）与实例判据守着，见守卫测试；
 * - 只读：命令行跑只打印，本文件不写任何文件。
 */
import { readdirSync, statSync, readFileSync } from 'node:fs'
import { join, relative } from 'node:path'

/**
 * 判据面 = **工作台文件族**。目录名带括号 ⇒ 逐个文件 / 目录显式列，
 * 不用 `walk` 去猜一个通配（`(dashboard)` 在 shell / glob 里都是特殊字符）。
 */
export const SCOPE = [
  'src/app/(dashboard)/dashboard/page.tsx',
  'src/components/dashboard',
]

/** 形态 ①：读派生的**计数断言**（N1 的承载体：「共 {total} 单」） */
const COUNT_CLAIM_RE = /共[^\n]{0,40}单/

/** 形态 ②：**空态断言**文案「暂无…」（到引号 / 尖括号 / 括号 / 换行 / 标点为止） */
const EMPTY_CLAIM_RE = /暂无[^\n"'`<>()（），。；、]{1,12}/

/**
 * **在场门词表**（命中任一 ⇒ 该断言「有据可依」；逐条给理由 —— 不许凭感觉加）：
 * - `blockEnabled(` / `blockFailed(`：本包新增的**显式门**（页面按块算出「这次读到没有」）；
 * - `blockErrors` + ` in `：仓内既有形态（`!(<name> in blockErrors)` = 这一块这次成功了）；
 * - `EMPTY_VALUE` / `'—'` / `"—"`：把该处改成「读不到 ⇒ 印 —」（不再印数字 / 空态文案）；
 * - `!<读面门标识>`：**取反的读面门**（本包四个组件的形态），标识受控（见 GATE_IDENT_RE）；
 * - `?? <非 0 字面量>`：该处消费的是**可空**读数（`null` = 读不到 ⇒ 已落到另一分支）。
 */
const GATE_IDENT_RE = '(?:readFailed|loadFailed|blockEnabled|hasBlockValue|hasHistoricalValue|hasValue)'
const GATE_RES = [
  /blockEnabled\s*\(/,
  /blockFailed\s*\(/,
  /(?:!|!\()\s*\(?\s*['"]?[A-Za-z_$][\w$]*['"]?\s+in\s+blockErrors/,
  /EMPTY_VALUE/,
  /['"]—['"]/,
  /**
   * 显式布尔取反：`{!readFailed && <span>共 {total} 单</span>}`（本包四个组件的形态）。
   * ⚠️ 判据**故意只认受控词表里的读面门标识**（`readFailed` / `loadFailed` / `blockEnabled` …）
   * —— 不是「行内有 `!` 就算」，否则 `!=` / 非空断言会被当成门（那是假绿）。
   */
  new RegExp(`!\\s*${GATE_IDENT_RE}`),
  /**
   * `?? <非 0 字面量>`：该处消费的是**可空**读数（`null` = 读不到 ⇒ 已落到另一分支）。
   * 本仓洞察句即此形态（`todayOrders <= 0 && todaySales <= 0` 只在两侧**都读到了**时才成立；
   * 两边都是 `null` 时上面那条「没读到」分支已先返回）。
   */
  /\?\?\s*(?!\s*[0'"])[A-Za-z_$]/,
]

/**
 * 语句窗口：把**相邻两行**拼起来看（JSX 跨行很常见：门在上一行、断言在下一行），
 * 并压掉空白 —— 但**只压窗口内**，不跨空行（空行是**作用域边界**：跨过它就可能是另一个块了，
 * 那会造成假绿）。行号按窗口的**最后一行**记（断言所在行）。
 */
function windowsOf(lines) {
  /** @type {Array<{line: number, text: string}>} */
  const out = []
  for (let i = 0; i < lines.length; i++) {
    const prev = i > 0 && lines[i - 1].trim() !== '' ? lines[i - 1] : ''
    out.push({ line: i + 1, text: `${prev}\n${lines[i]}`.replace(/\s+/g, ' ') })
  }
  return out
}

/**
 * 这一行是不是注释行（注释里的同形态**不算证据** —— 本仓注释惯例会引用这些串）。
 *
 * 三种形态都要认（实测：只认前两种时，**JSX 块注释**里引用的「暂无数据」会被判成证据）：
 * ① `//` 行注释；② `*` 或 `/*` 开头的块注释续行；③ JSX 块注释（`{` + `/*` 开头 / 单独的收尾花括号行）。
 */
function isCommentLine(line) {
  const t = line.trim()
  return (
    t.startsWith('//') ||
    t.startsWith('*') ||
    t.startsWith('/*') ||
    t.startsWith('{/*') ||
    /^\}\s*$/.test(t) ||
    /^\*\/\s*$/.test(t)
  )
}

/**
 * 把注释行**抹成空行**（不是「跳过」）—— 这一步是**判别力**的关键：
 * 只跳过的话，注释行仍留在**语句窗口**里（窗口 = 相邻两行的拼接）⇒ 一句注释里的
 * 「暂无…」会被它**上一行**的门「救活」（**假绿**：注释里引用的串被当成已门断言）。
 * 抹空后窗口在注释处断开 —— 与「空行是作用域边界」同一口径。
 *
 * 🔴 **块注释要有状态**（实测踩过两遍）：本仓的 JSX 注释常常**跨多行**——
 *   `{/* 第一行 …` / ` * 第二行…` / ` *\/}` —— 只按「行首形态」逐行判，
 *   中间那些行（行首是「（」「`」等普通字符）会被当成**证据**，而注释里引用的
 *   「共 0 单」「暂无数据」正好全在里面（判据被自己的文案喂红）。
 *   ⇒ 维护一个 inBlockComment 状态，直到遇到块注释结束行。
 *
 * @param {string[]} lines
 */
function blankCommentLines(lines) {
  let inBlock = false
  return lines.map((l) => {
    const t = l.trim()
    if (inBlock) {
      if (/(\*\/|\*\/\s*\})/.test(t) || /^\*\/\s*\}$/.test(t)) inBlock = false
      return ''
    }
    if (t.startsWith('//')) return ''
    if (t.startsWith('/*') || t.startsWith('{/*')) {
      // 单行块注释（`/* … */` 同行收尾）⇒ 不必进状态
      if (!/.*\*\/|\*\/\s*\}$/.test(t)) inBlock = true
      return ''
    }
    if (/^\*\//.test(t) || /^\}\s*$/.test(t)) return ''
    return l
  })
}

/**
 * 判据本体（**只吃一段源码**）。
 *
 * 🔴 抽出来是为了让守卫能用**内存里的假源码**做判别力自证（坏形态判红 / 好形态不红），
 *   而**不是**在测试里抄一份正则 —— 抄的那份会漂移，自证就成了自说自话。
 *
 * **在场门 = 行内**（本行命中 GATE_RES，或**上一非空非注释行**命中 —— 相邻两行才算同一条件）。
 * 跨多行的 JSX 三元（`… : !blockEnabled('trend') ? (…) : data.length > 0 ? (<图/>) : (<空态/>)`）
 * 的断言行**拿不到行内门** ⇒ 由 `PINNED_GATE_LINES` **逐点钉住**（每点要写清门外在哪儿、
 * 它凭什么算门、以及**运行时的第二重判据**）—— 这比放宽窗口更诚实：
 * 「文本上隔着 5 行」判不出「这 5 行里没有别的分支」，硬算门就是**假绿**。
 *
 * @param {string} source 源码文本
 * @param {{file?: string}} [opts] `file` 只用于台账键的前缀（自证传 `'probe.tsx'`）
 * @returns {{counts: Array<object>, empties: Array<object>}}
 */
export function claimSitesFromSource(source, { file = '<probe>.tsx' } = {}) {
  const rawLines = source.split('\n')
  const lines = blankCommentLines(rawLines)
  /** 上一非空行（注释已抹空） */
  const prevNonBlank = (ln) => {
    for (let i = ln - 2; i >= 0; i--) {
      if (lines[i].trim() !== '') return lines[i]
    }
    return ''
  }

  /** @type {Array<object>} */
  const counts = []
  /** @type {Array<object>} */
  const empties = []
  for (const { line, text } of windowsOf(lines)) {
    const raw = lines[line - 1]
    if (raw.trim() === '') continue
    const gated = GATE_RES.some((re) => re.test(text)) || GATE_RES.some((re) => re.test(prevNonBlank(line)))
    if (COUNT_CLAIM_RE.test(raw)) {
      const claim = raw.trim().replace(/\s+/g, ' ')
      counts.push({ file, line, claim, gated, key: `${file}::count::${claim}` })
    }
    const em = raw.match(EMPTY_CLAIM_RE)
    if (em) {
      const claim = em[0]
      empties.push({ file, line, claim, gated, key: `${file}::empty::${claim}` })
    }
  }
  return { counts, empties }
}

/** 收集判据面里的文件（**按 SCOPE 显式列**，不递归猜目录名）。 */
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
        else if (/\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry)) out.push(full)
      }
    } else if (/\.tsx?$/.test(p)) out.push(p)
  }
  for (const rel of SCOPE) push(join(root, rel))
  return out.sort()
}

/**
 * 命中清单（**单一源**）：`{files, counts, empties}`，路径为仓库相对（相对 `frontend/admin-web`）。
 *
 * @param {string} root `frontend/admin-web` 的绝对路径
 */
export function claimSites(root) {
  const files = scopeFiles(root)
  /** @type {Array<object>} */
  const counts = []
  /** @type {Array<object>} */
  const empties = []
  for (const file of files) {
    const rel = relative(root, file)
    const r = claimSitesFromSource(readFileSync(file, 'utf8'), { file: rel })
    counts.push(...r.counts)
    empties.push(...r.empties)
  }
  return { files: files.map((f) => relative(root, f)), counts, empties }
}

/**
 * 豁免台账（**只许缩短**）：登记「确有必要 / 属别的文件族存量债」的命中点。
 *
 * 键 = 仓库相对路径 + `::count::`（或 `::empty::`）+ 该行逐字
 * —— 故意**不带行号**（一行新增就会把台账顶失效，本仓 #4668 的教训），
 * 而在**同符号内改删行**下是稳定的。
 *
 * 本包**目标形态 = 空数组**（工作台文件族零未门命中）⇒ 任何新增未门断言**当场红**。
 *
 * @type {string[]}
 */
export const LEDGER = []

/**
 * **在场门台账**（issue #6715）：登记「**行内看不出门、但确有门**」的断言点。
 *
 * 为什么需要它：本仓的 JSX 三元很长，断言行离门有 4~5 行
 * （`… : !blockEnabled('trend') ? (…) : data.length > 0 ? (<图/>) : (<空态/>)`）
 * ⇒ 行内判据判不出来。硬把窗口放宽 = **假绿**（「隔着 5 行」证明不了「这 5 行里没有别的分支」）；
 * 所以**逐点钉住**，每条写清三样，且**三条判据都机器核**：
 *
 * - `claim`：该点的逐字断言（必须仍在文件里 → 点被删/改名 ⇒ 红）；
 * - `gate`：**它外面那句话有没有门** —— 逐字短语必须仍在文件里（门被摘 ⇒ 红）；
 * - `runtime`：**运行时的第二重判据**（`data-testid`）所属文件的**逐字锚**必须仍在
 *   （出口被删 ⇒ 红；出口本身由 `tests/unit/pages/dashboard.test.tsx` 的 #6715 用例跑）。
 *
 * **新增未门点即红**：未门且未登记 ⇒ 判据 2 当场红（逼着要么补门、要么在这里写清三重理由）。
 *
 * @type {Array<{key: string, claim: string, gate: string, gateIn: string, gateWhy: string, runtime: string, runtimeIn: string, runtimeWhy: string}>}
 */
export const PINNED_GATE_LINES = [
  {
    key: 'src/app/(dashboard)/dashboard/page.tsx::empty::暂无订单数据',
    claim: '暂无订单数据',
    gate: "!hasBlockValue('trend')",
    gateIn: 'src/app/(dashboard)/dashboard/page.tsx',
    gateWhy: '同一条件链上的前一分支：`loading ? … : !hasBlockValue(\'trend\') ? <订单趋势没读到> : trendData.length > 0 ? <图/> : <空态>` —— 读失败时走不到这一支',
    runtime: 'trend-read-failed',
    runtimeIn: 'src/app/(dashboard)/dashboard/page.tsx',
    runtimeWhy: '实例判据（#6715「冷启动全挂」/「单块失败」）按这个 testid 判「读失败时该块只印『没读到』、一处『暂无』都没有」',
  },
  {
    key: 'src/app/(dashboard)/dashboard/page.tsx::empty::暂无销售额数据',
    claim: '暂无销售额数据',
    gate: "!hasBlockValue('trend')",
    gateIn: 'src/app/(dashboard)/dashboard/page.tsx',
    gateWhy: '与订单趋势同一条链（同一 `trend` 块）：失败时走「销售额趋势没读到」那一支',
    runtime: 'sales-trend-read-failed',
    runtimeIn: 'src/app/(dashboard)/dashboard/page.tsx',
    runtimeWhy: '同上的实例判据锚点',
  },
  {
    key: 'src/app/(dashboard)/dashboard/page.tsx::empty::暂无排行数据',
    claim: '暂无排行数据',
    gate: "!hasBlockValue('ranking')",
    gateIn: 'src/app/(dashboard)/dashboard/page.tsx',
    gateWhy: '同一条件链上的前一分支：`loading ? … : !hasBlockValue(\'ranking\') ? <排行没读到> : ranking.length === 0 ? <空态>`',
    runtime: 'ranking-read-failed',
    runtimeIn: 'src/app/(dashboard)/dashboard/page.tsx',
    runtimeWhy: '实例判据按这个 testid 判「排行块失败时不印空态」',
  },
  {
    key: 'src/components/dashboard/OrderTrendChart.tsx::empty::暂无数据',
    claim: '暂无数据',
    gate: 'readFailed ? (',
    gateIn: 'src/components/dashboard/OrderTrendChart.tsx',
    gateWhy: '组件内**同一条三元链**：`loading ? … : readFailed ? <没读到> : data.length === 0 ? <暂无数据>`',
    runtime: 'order-trend-read-failed',
    runtimeIn: 'src/components/dashboard/OrderTrendChart.tsx',
    runtimeWhy: '失败分支的稳定锚（组件单测 / 页面实例判据都用它）',
  },
  {
    key: 'src/components/dashboard/ActiveSessions.tsx::empty::暂无活跃会话',
    claim: '暂无活跃会话',
    gate: 'readFailed ? (',
    gateIn: 'src/components/dashboard/ActiveSessions.tsx',
    gateWhy: '组件内同一条三元链：`loading ? … : readFailed ? <没读到> : sessions.length === 0 ? <空态>`',
    runtime: 'active-sessions-read-failed',
    runtimeIn: 'src/components/dashboard/ActiveSessions.tsx',
    runtimeWhy: '失败分支的稳定锚',
  },
  {
    key: 'src/components/dashboard/RecentOrders.tsx::empty::暂无订单数据',
    claim: '暂无订单数据',
    gate: 'readFailed ? (',
    gateIn: 'src/components/dashboard/RecentOrders.tsx',
    gateWhy: '组件内同一条三元链：`loading ? … : readFailed ? <没读到> : orders.length === 0 ? <空态>`（该文案是 prop 默认值，同一支）',
    runtime: 'recent-orders-read-failed',
    runtimeIn: 'src/components/dashboard/RecentOrders.tsx',
    runtimeWhy: '失败分支的稳定锚',
  },
  {
    key: 'src/components/dashboard/TodayOverviewBar.tsx::empty::暂无新订单',
    claim: '今日暂无新订单，销售额 ¥0',
    gate: 'if (todayOrders === null || todaySales === null) {',
    gateIn: 'src/components/dashboard/TodayOverviewBar.tsx',
    gateWhy: '**同一函数内的先返回守卫**：任一侧 `null`（读不到）⇒ 上一条分支已 return「…没读到…」；这句只在两侧**都读到了**时才成立',
    runtime: 'today-overview-sentence',
    runtimeIn: 'src/components/dashboard/TodayOverviewBar.tsx',
    runtimeWhy: '实例判据（#6701 / #6715）在洞察句上判「读不到 ⇒ 说『没读到』、不出现『今日暂无新订单』」',
  },
]

/**
 * **正向核**：本包改对的形态必须**逐字**仍在（锚被删 / 被改回 ⇒ 当场红）。
 * 为什么不可省：LEDGER 为空只证明「当前没有未门命中」，证明不了「门真的写着」。
 *
 * @type {Array<{file: string, must: string[], why: string}>}
 */
export const POSITIVE_ANCHORS = [
  {
    file: 'src/app/(dashboard)/dashboard/page.tsx',
    must: ['hasBlockValue'],
    why: '页面必须为每一块算出「这次读到没有」的布尔门（否则「暂无…」无法与读失败分开）',
  },
  {
    file: 'src/app/(dashboard)/dashboard/page.tsx',
    must: ['没有取到数据'],
    why: '冷启动失败（无任何历史成功值）时横幅必须说「没有取到数据」，不得声称「仍是上次成功取到的值」',
  },
  {
    file: 'src/components/dashboard/OrderStatusChart.tsx',
    must: ['readFailed', 'order-status-count'],
    why: '订单状态分布的计数位必须有显式门 + 稳定锚点（N1：读失败时不得印「共 0 单」）',
  },
  {
    file: 'src/app/(dashboard)/dashboard/page.tsx',
    must: ['trend-read-failed', 'sales-trend-read-failed', 'ranking-read-failed', 'dashboard-no-data-yet'],
    why: '失败分支的稳定锚（实例判据按它们判「失败时不印空态」）；删掉 ⇒ 这里红',
  },
]

/** 命令行：`node scripts/dashboard-read-failure-claims-scan.mjs`（只读、报告型；有未门 / 僵尸 / 未钉 ⇒ exit 1）。 */
if (process.argv[1] && import.meta.url.endsWith(process.argv[1].split('/').pop() ?? '')) {
  const { files, counts, empties } = claimSites(process.cwd())
  const all = [...counts, ...empties]
  const ungated = all.filter((s) => !s.gated)
  const live = new Set(all.map((s) => s.key))
  const pinnedKeys = new Set(PINNED_GATE_LINES.map((p) => p.key))
  const unregistered = ungated.filter((s) => !LEDGER.includes(s.key) && !pinnedKeys.has(s.key))
  // 台账两向都只许缩短：豁免条目 / 钉住条目不再命中 ⇒ 僵尸，当场红
  const stale = [
    ...LEDGER.filter((k) => !live.has(k)),
    ...PINNED_GATE_LINES.filter((p) => !live.has(p.key)).map((p) => p.key),
  ]
  // 钉住条目的**三重理由**必须逐字仍在（点 / 门 / 运行时出口任一被删 ⇒ 红）
  const brokenPins = PINNED_GATE_LINES.filter((p) => {
    const text = readFileSync(join(process.cwd(), p.runtimeIn), 'utf8')
    const gateFile = (p.gateIn || p.runtimeIn) === p.runtimeIn ? text : readFileSync(join(process.cwd(), p.gateIn), 'utf8')
    return !text.includes(p.claim) || !gateFile.includes(p.gate) || !text.includes(p.runtime)
  })
  console.log(`判据面：${files.length} 个文件（${SCOPE.join(' + ')}）`)
  console.log(`命中：计数断言 ${counts.length} 处 · 空态断言 ${empties.length} 处 · 行内带门 ${all.filter((s) => s.gated).length} 处 · 钉住 ${PINNED_GATE_LINES.length} 处`)
  for (const s of unregistered) console.log(`  ❌ 未门未钉住 ${s.key}  （${s.file}:${s.line}）`)
  for (const k of stale) console.log(`  📒 台账失效 ${k}（只许缩短，改好即删）`)
  for (const p of brokenPins) console.log(`  🔒 钉住条目理由不成立 ${p.key}（点 / 门 / 运行时出口 逐字锚之一不见了）`)
  process.exit(unregistered.length || stale.length || brokenPins.length ? 1 : 0)
}
