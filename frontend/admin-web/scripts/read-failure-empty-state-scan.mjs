#!/usr/bin/env node
// case_ids: UI-011, CH-028, UI-046, UI-057, UI-058
/**
 * 「读面失败不得伪装成空态」判据**单一源**（issue #6663）。
 *
 * ## 为什么要有它
 *
 * 三维审计（2026-10-10）在配置与权限面抓到同一个病：**读接口失败时，catch 只把列表清空**
 * （`setRows([])` / `setRoles([])` / 读不到就保持 `false`）⇒ 页面**看起来像「本来就没有数据」**，
 * 商家据此做决定（「这个企业没有岗位」/「通知本来是关的」），而真相是**读不到**。
 * 这是本仓「状态必须真实（故障不得伪装成空态）」纪律的反面。
 *
 * 单个页面改一次不解决复发（同族：`dashboard/page.tsx` 的 #5792 失败/空态分离、
 * `stock-ledger/page.tsx` 的 `*-error` 行）⇒ 本文件是那条**类级收口**：
 * 判据（`swallowSites`）与台账（`LEDGER`）都只有这一份，守卫
 * `tests/unit/read-failure-empty-state-guard.test.ts` 与命令行**共用**它（不写第二份规则）。
 *
 * ## 🔴 本文件同时是 issue #6713 + #6714 的**同一把尺子**（2026-10-11 合并）
 *
 * #6713（`/chat`）与 #6714（`/employees` `/notifications` `/products` `/shipments`）
 * 是**同一个形态**：**读面失败被渲染成一句事实性断言**（「暂无会话 / 暂无数据 / 暂无通知」，
 * 或表头在、零行、无失败面）。两单各自立一把尺子会互相把对方判成僵尸条目、
 * 且同一份文件会被两份台账各记一次 ⇒ 按「一把尺子」合并到本文件。
 * `/production/remnants` 的遗留空态（失败横幅在、底下仍印「还没有余料记录」）同批纳入。
 *
 * ## 判的是哪个形态（口径）
 *
 * 一个 catch **算「读失败被吞」** ⇐ 同时满足：
 *   ① 它**清空/复位**了状态 —— 至少一次 `setX(...)` 的实参是「空字面量」
 *      （`[]` / `null` / `''` / `false`。`false` 的实例：通知开关读不到 ⇒ 保持「关闭」）；
 *   ② 它**没有**表达失败 —— 整个 catch（含其内层块）里没有任何
 *      `setX` 且 X 命中 `error|fail|problem`（如 `setError('…')` / `setFailedBlocks(…)`）。
 *
 * 🔴 **有意不判**的两种形态（实测区分过，别把它们当漏网）：
 *   - **空 catch + 注释「拦截器已提示」**：那是**写面**（过账 / 作废 / 提交）的 catch，
 *     `request.ts` 拦截器已经 toast 过，而**读面读数不变**（不产生假的空态）⇒ 不在本条纪律射程。
 *   - **catch 里赋一个「读不到」的哨兵值**（`return null` / `setX(undefined)` 之外的显式失败态）
 *     —— 那是**正确**形态，不该判红。
 *
 * ## 两级判据（缺一不可）
 *
 * - **扫描判据**：凡命中上面的形态 ⇒ 必须登记进 `LEDGER`，**未登记即红**。
 * - **正向核**：`FAILURE_ANCHORS` 里每一条「已改对的页面」必须**逐字**含失败态锚点
 *   （`data-testid` + 可行动文案）⇒ 锚点被删（页面退回空态）当场红。
 * - **台账只许缩短**：`LEDGER` 里**不再命中**的条目当场红（逼着删干净，不留僵尸豁免）。
 *
 * ⚠️ 边界（照实登记，issue #6663）：只扫**商家后台**(`src/app/(dashboard)`)，只认**源码文本形态**；
 * 「服务端下发的 message 里带字段名」不在本判据射程（那是展示字段分离，另单）。
 *
 * ## 台账现状（issue #6691，2026-10-10）
 *
 * `LEDGER` 已**归零**（空数组 = 目标形态）：#6663 立的账、#6664 修好 shipments 后删一条、
 * #6691 把剩下 6 条逐点修好并删条目、第 7 条（stock-ledger 灰区）裁定为「失败可见**已满足**」
 * 后删条目并补齐重试出口。此后新增命中一律**先修**（照 `dashboard/page.tsx` 范式），
 * 确需豁免再登记 —— 且登记后修好必须同批删。
 */
import { readdirSync, statSync, readFileSync } from 'node:fs'
import { join, relative } from 'node:path'
import ts from 'typescript'

/** 判据面：商家后台页面（官网 / 小程序各有自己的一套） */
export const SCOPE = 'src/app/(dashboard)'
const SKIP_DIRS = new Set(['node_modules', '.next', 'dist', 'coverage', '__pycache__'])

/** 状态变量「名中含失败语义」即算**表达了失败** */
const FAIL_NAME = /error|fail|problem/i

/**
 * 这些 setter **不算「清空读数」**（实测的假红面，逐条给理由——不许凭感觉加）：
 * - `setSearchHint('')`（`stock-ledger` 的商品搜索）：它清的是**提示语**，
 *   而同一个 catch 里紧接着就 `setSearchHint('商品搜索失败 —— 请稍后重试')` ⇒ 失败**有**出口；
 * - `setLoading(false)`（`finally`）与 `setXxxLoading` / `setXxxVisible` / `setXxxOpen`：
 *   它们是**过程量**，不是读面读数 —— 清掉它们不产生假的「空态」。
 *
 * ⇒ 判据只认「读数类」状态（列表 / 对象 / 记录 / 开关）。
 */
const NOT_READING_STATE = /(Hint|Loading|Visible|Open|Searching|Submitting|Saving|Printing|Deleting|Acting|Busy)$/

/** 台账（唯一真值在下面的 `LEDGER`）：命中点在这里逐条登记 */
const isReadingState = (name) => !NOT_READING_STATE.test(name.slice(3))

/** `setX(...)` 的实参是不是「空字面量」（= 清空 / 复位成空态） */
function isEmptyLiteral(node) {
  if (!node) return false
  if (node.kind === ts.SyntaxKind.NullKeyword) return true
  if (node.kind === ts.SyntaxKind.FalseKeyword) return true
  if (ts.isArrayLiteralExpression(node) && node.elements.length === 0) return true
  if (ts.isStringLiteral(node) && node.text === '') return true
  if (ts.isNoSubstitutionTemplateLiteral(node) && node.text === '') return true
  return false
}

function walk(dir, out = []) {
  for (const entry of readdirSync(dir)) {
    if (SKIP_DIRS.has(entry)) continue
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) walk(full, out)
    else if (/\.tsx?$/.test(entry)) out.push(full)
  }
  return out
}

/**
 * 最近的**具名承载体**（函数名 / 变量名 / 属性名）—— 台账的稳定锚。
 *
 * 🔴 有意**不用行号**（`SUBTITLE_EXEMPT` 的教训：一行新增就把台账顶失效）：
 * 符号 + 该符号内第几个 catch（`#1`）在「同函数内加删行」下是稳定的。
 */
function ownerOf(node, sf) {
  let cur = node.parent
  while (cur) {
    if (ts.isFunctionDeclaration(cur) || ts.isFunctionExpression(cur) || ts.isArrowFunction(cur)) {
      const parent = cur.parent
      if (parent && ts.isVariableDeclaration(parent) && ts.isIdentifier(parent.name)) return parent.name.text
      if (parent && ts.isPropertyAssignment(parent)) return parent.name.getText(sf)
      if (ts.isFunctionDeclaration(cur) && cur.name) return cur.name.text
    }
    cur = cur.parent
  }
  return '<module>'
}

/**
 * 判据本体（**只吃一段源码**）：返回这段源码里的命中点。
 *
 * 🔴 抽出来是为了让守卫能用**内存里的假源码**做判别力自证（坏形态各自判红 / 好形态不红），
 *   而**不是**在测试里抄一份正则 —— 抄的那份会漂移，自证就成了自说自话。
 *
 * @param {string} source 源码文本
 * @param {{file?: string, ts?: typeof ts}} [opts] `file` 只用于台账键的前缀（自证传 `'probe.tsx'`）
 */
export function swallowSitesFromSource(source, { file = '<probe>.tsx', tsModule = ts } = {}) {
  const sf = tsModule.createSourceFile(file, source, tsModule.ScriptTarget.Latest, true, tsModule.ScriptKind.TSX)
  const out = []
  const perSymbol = new Map()
  const visit = (node) => {
    if (tsModule.isCatchClause(node)) {
      const symbol = ownerOf(node, sf)
      const ordinal = (perSymbol.get(symbol) || 0) + 1
      perSymbol.set(symbol, ordinal)
      const cleared = []
      let hasFailure = false
      const dig = (n) => {
        if (tsModule.isCallExpression(n)) {
          const callee = n.expression
          // 失败出口的第二种合法形态：`toast.error(...)`（拦截器之外的本地失败提示）
          if (tsModule.isPropertyAccessExpression(callee) && callee.getText(sf).startsWith('toast.')) {
            if (callee.name.text === 'error') hasFailure = true
          }
          if (tsModule.isIdentifier(callee) && callee.text.startsWith('set')) {
            const name = callee.text
            if (FAIL_NAME.test(name.slice(3))) hasFailure = true
            else if (isReadingState(name) && n.arguments.length > 0 && isEmptyLiteral(n.arguments[0])) {
              cleared.push(name)
            }
          }
        }
        tsModule.forEachChild(n, dig)
      }
      tsModule.forEachChild(node.block, dig)
      if (!hasFailure && cleared.length > 0) {
        out.push({
          file,
          line: sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1,
          symbol,
          key: `${file}::${symbol}#${ordinal}`,
          cleared,
        })
      }
    }
    tsModule.forEachChild(node, visit)
  }
  tsModule.forEachChild(sf, visit)
  return out
}

/**
 * 命中清单（**单一源**）。
 * 每条 = `{ file, line, symbol, key, cleared, hasFailure }`，`key` = 台账锚
 * `仓库相对路径::符号#该符号内第几个 catch`。
 */
export function swallowSites(root) {
  const files = walk(join(root, SCOPE)).sort()
  const out = []
  for (const file of files) {
    const rel = relative(root, file)
    out.push(...swallowSitesFromSource(readFileSync(file, 'utf8'), { file: rel, tsModule: ts }))
  }
  return { files: files.map((f) => relative(root, f)), sites: out }
}

/**
 * 豁免台账（**只许缩短**）：登记「确有必要 / 属存量债」的命中点。
 *
 * 键 = `仓库相对路径::符号#序号`（见 `swallowSites` 的 `key`）。**失效即红**：
 * 该点改对之后必须**同批删掉**这一条（未删 ⇒ 守卫红 ⇒ 逼着删干净）。
 *
 * ⚠️ 本台账**有意收录本包文件族之外**的存量命中（products / shipments / inbound-orders /
 * categories）—— 它们由**并发包**（#6662 products 面 / #6664 chat·ship 面）拥有写面，
 * 本包不改它们的码；登记是**如实记账**（不收编成「已修」），归零靠后续包逐批删条目。
 */
export const LEDGER = [
  // ── 空数组是本台账的**目标形态**（issue #6663 立的规矩：只许缩短）──
  //
  // 归零沿革（逐批，条目**删除**而非注释掉）：
  //   · `shipments/page.tsx::ShipmentsPage#1` —— #6664（PR #6673）修好，同批删条目；
  //   · `roles` / `employees` / `settings` 三页 —— #6663 本包修好（本来就未登记）；
  //   · 其余 7 条（`inbound-orders` ×3 / `orders/[id]` / `orders/new` ×2 / `stock-ledger`）
  //     —— **#6691 本包**逐点修好（失败态可见 + 重试出口），同批删条目 ⇒ 台账清零。
  //
  // ⚠️ 第 7 条（`stock-ledger/page.tsx::StockLedgerPage#3`）的**灰区裁定**（issue #6691）：
  //   同一 `catch` 里**已经有** `setSearchHint('商品搜索失败 —— 请稍后重试')` —— 与「没有匹配的商品
  //   —— 换个关键词试试」**两句、两种语义** ⇒ 「失败**可见**」这一半本来就成立（不是「清空读数且
  //   不表达失败」）。裁定 = **满足**，据此删条目；同时补上缺的那一半（`role="alert"` + 「重试商品搜索」
  //   出口），判据 = `tests/unit/pages/read-failure-empty-state-instances.test.tsx` 的 ⑦ 组。
  //
  // 新增命中 ⇒ 先修（照 `dashboard/page.tsx` 失败/空态分离范式，首选），确需豁免再登记；
  // 已修的条目必须**同批删掉**（留着 ⇒ `staleLedger` 判红，逼着删干净）。
]

/**
 * **正向核**：本包已改对的页面 ⇒ 必须**逐字**含失败态锚点（`data-testid` + 可行动文案）。
 *
 * 为什么正向核不可省：`LEDGER` 删条目只证明「不再命中扫描形态」，
 * 而扫描判不了「失败态**真的渲染出来了**」—— 把 `catch` 改成 `setError('')` 也能绕过扫描。
 * 这条逐字锚住渲染面，删掉锚点 ⇒ 当场红。
 */
export const FAILURE_ANCHORS = [
  {
    name: '岗位清单读失败',
    file: 'src/app/(dashboard)/roles/page.tsx',
    anchors: ["data-testid=\"roles-load-error\"", '岗位加载失败', '重新加载'],
  },
  {
    name: '员工岗位下拉读失败',
    file: 'src/app/(dashboard)/employees/page.tsx',
    anchors: ["data-testid=\"employees-positions-error\"", '岗位清单读取失败'],
  },
  {
    name: '通知开关读失败（不得画成「关闭」）',
    file: 'src/app/(dashboard)/settings/page.tsx',
    anchors: ["data-testid=\"settings-notification-read-error\"", '通知设置读取失败'],
  },
  {
    name: '简报开关读失败',
    file: 'src/app/(dashboard)/settings/page.tsx',
    anchors: ["data-testid=\"settings-briefing-read-error\"", '简报设置读取失败'],
  },
  {
    name: '权限目录读失败（岗位页）',
    file: 'src/app/(dashboard)/roles/page.tsx',
    anchors: ["data-testid=\"roles-permissions-error\"", '权限目录读取失败'],
  },
  // ── issue #6691（#6664 的未收口余项）：这 6 条从 LEDGER 挪到**正向核** ──
  // 扫描判据只证明「不再命中清空形态」；把它们逐字锚在这里 ⇒ 删掉失败态（页面退回空态）当场红。
  {
    name: '入库单列表读失败（issue #6691）',
    file: 'src/app/(dashboard)/inbound-orders/page.tsx',
    anchors: ["data-testid=\"inbound-load-error\"", '入库单加载失败', "data-testid=\"inbound-load-retry\""],
  },
  {
    name: '入库单建单页 · 商品搜索读失败（issue #6691）',
    file: 'src/app/(dashboard)/inbound-orders/new/page.tsx',
    anchors: ["data-testid=\"inbound-product-search-error\"", '商品搜索失败', "data-testid=\"inbound-product-search-retry\""],
  },
  {
    name: '入库单建单页 · 规格明细读失败（issue #6691）',
    file: 'src/app/(dashboard)/inbound-orders/new/page.tsx',
    anchors: ["data-testid=\"inbound-sku-error\"", '规格读取失败', "data-testid=\"inbound-sku-retry\""],
  },
  {
    name: '订单详情 · 发货明细读失败（issue #6691）',
    file: 'src/app/(dashboard)/orders/[id]/OrderDetail.tsx',
    anchors: ["data-testid=\"order-shipments-read-error\"", '发货明细读取失败', "data-testid=\"order-shipments-retry\""],
  },
  {
    name: '新建订单 · 加工项目录读失败（issue #6691）',
    file: 'src/app/(dashboard)/orders/new/page.tsx',
    anchors: ["data-testid=\"orders-new-processing-catalog-error\"", '加工项目录加载失败', "data-testid=\"orders-new-processing-catalog-retry\""],
  },
  {
    name: '库存明细 · 商品搜索读失败（issue #6691，灰区裁定后补出口）',
    file: 'src/app/(dashboard)/stock-ledger/page.tsx',
    anchors: ["data-testid=\"stock-ledger-search-hint\"", '商品搜索失败', '重试商品搜索'],
  },
]

/** 命中清单（台账过滤后） */
export function findOffenders(root) {
  const { files, sites } = swallowSites(root)
  const offenders = sites.filter((s) => !LEDGER.includes(s.key))
  return { files, sites, offenders }
}

/** 台账「空转」检测：登记了但**不再命中**的条目（只许缩短 ⇒ 必须删） */
export function staleLedger(root) {
  const { sites } = swallowSites(root)
  const live = new Set(sites.map((s) => s.key))
  return LEDGER.filter((k) => !live.has(k))
}

// ═══════════════════════════════════════════════════════════════════════════════
// 第二条判据：**同一次读失败的重复信号**（issue #6669 未完成 1 / §31 P1 常驻面克制 · P2 信息不重复）
//
// ## 与第一条（读失败被吞）的区别 —— 同一个病的两级
//
// 第一条判「失败**看不见**（伪装成空态）」；本条判「失败**看见了好几遍**」。
// 两条都属「状态必须真实」，互为补集：一个 catch 既清空读数又不表达失败 ⇒ 第一条红；
// 一个 catch **表达了失败**却又用 toast 把同一句再说一遍 ⇒ 第二条红。
//
// ## 判的是哪个形态（口径）
//
// 同一个 catch 里**同时**有：
//   ① **内联**失败文案 —— `setX(<非空字符串字面量>)` 且 X 命中 `error|fail|problem`
//      （= 失败画在屏上，是常驻面）；
//   ② **toast** 播报 —— `toast.error(...)`。
// ⇒ 同一次故障在屏上报两遍（常驻内联 + 一次性 toast）。
//
// 🔴 为什么 ② 是**重复**而不是「双保险」：`frontend/admin-web/src/lib/request.ts` 的响应拦截器对
// **所有**失败分支（`success:false` 业务错 / 各 HTTP 状态 / 网络错 / 非 axios 错）都已
// `toast.error(...)` **且** `markErrorToastShown(error)` ⇒ 真 API 失败时页面那句 toast 是
// **死分支**（`isErrorToastShown(e)` 恒真）；它只在「错误不经拦截器抛出」时执行，而那种情形下
// ① 同屏也在 ⇒ 仍是两遍。
// ⇒ 处置 = **撤掉页面自己的那次播报**，**保留**内联那一处（撤的是重复，**不是可见性**：
// 失败仍看得见，且必须有重试出口 —— 出口那半由实例判据钉住：
// `tests/unit/components/CalcFormulaPanel.test.tsx` 判据 ③）。
//
// ## 射程（**照实登记的局限，不假装覆盖全站**）
//
// 只扫 `src/components/production-config`（本条的实测发生地 = `CalcFormulaPanel`，它只在
// `embedded` 形态下与页面的读面失败同屏；面板单独挂载时要靠内联那处兜底）。
// 实测：把扫描面换成整个 `src`，按本条形态也只命中这个目录里的 2 处
// （复算：`node scripts/read-failure-empty-state-scan.mjs`，读数见输出）。
// ⇒ 其它目录的同族形态（若有）**不会有东西变红**：本条**不声明**全站覆盖。
// ═══════════════════════════════════════════════════════════════════════════════

/** 本条判据的扫描面（见上面「射程」：**有意只覆盖发生地所在目录**） */
export const DUP_SCOPE = 'src/components/production-config'

/**
 * 判据本体（**只吃一段源码**）。
 *
 * 与 `swallowSitesFromSource` 同口径的设计：抽出来是为了让守卫能用**内存里的假源码**做
 * 判别力自证（坏形态判红 / 好形态不红），而**不是**在测试里另抄一份正则（抄的那份会漂移）。
 *
 * @param {string} source 源码文本
 * @param {{file?: string, tsModule?: typeof ts}} [opts] `file` 只用于台账键的前缀（自证传 `'probe.tsx'`）
 */
export function duplicateSignalSitesFromSource(source, { file = '<probe>.tsx', tsModule = ts } = {}) {
  const sf = tsModule.createSourceFile(file, source, tsModule.ScriptTarget.Latest, true, tsModule.ScriptKind.TSX)
  const out = []
  const perSymbol = new Map()
  const visit = (node) => {
    if (tsModule.isCatchClause(node)) {
      const symbol = ownerOf(node, sf)
      const ordinal = (perSymbol.get(symbol) || 0) + 1
      perSymbol.set(symbol, ordinal)
      let inlineMsg = null
      let toastCount = 0
      const dig = (n) => {
        if (tsModule.isCallExpression(n)) {
          const callee = n.expression
          if (tsModule.isPropertyAccessExpression(callee) && callee.getText(sf) === 'toast.error') {
            toastCount += 1
          }
          if (tsModule.isIdentifier(callee) && callee.text.startsWith('set') && FAIL_NAME.test(callee.text.slice(3))) {
            const arg = n.arguments[0]
            if (arg && tsModule.isStringLiteral(arg) && arg.text !== '') inlineMsg = arg.text
          }
        }
        tsModule.forEachChild(n, dig)
      }
      tsModule.forEachChild(node.block, dig)
      if (inlineMsg !== null && toastCount > 0) {
        out.push({
          file,
          line: sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1,
          symbol,
          key: `${file}::${symbol}#${ordinal}`,
          inlineMsg,
          toastCount,
        })
      }
    }
    tsModule.forEachChild(node, visit)
  }
  tsModule.forEachChild(sf, visit)
  return out
}

/**
 * 命中清单（**单一源**）：扫 `DUP_SCOPE` 下的每个文件。
 * 每条 = `{ file, line, symbol, key, inlineMsg, toastCount }`。
 */
export function duplicateSignalSites(root) {
  const files = walk(join(root, DUP_SCOPE)).sort()
  const out = []
  for (const file of files) {
    const rel = relative(root, file)
    out.push(...duplicateSignalSitesFromSource(readFileSync(file, 'utf8'), { file: rel, tsModule: ts }))
  }
  return { files: files.map((f) => relative(root, f)), sites: out }
}

/**
 * 豁免台账（**只许缩短**）：登记「确需保留 toast」的命中点。
 *
 * 键与 `LEDGER` 同口径 = `仓库相对路径::符号#该符号内第几个 catch`。
 * **失效即红**（`dupStaleLedger`）：该点改对之后必须**同批删掉**这一条。
 *
 * 现状（2026-10-10 取数）：`CalcFormulaPanel` 已修（不再命中）；本台账剩下的这一条是
 * **兄弟挂载**——`ProcessConfigBoard`（`/production/routings` 页在跑的 v1 板子）的算料 tab
 * 有**逐字相同**的同族代码（同端点 / 同文案 / 同「toast + 内联」两处）。
 * 它**有意不在本包修**（如实记账，不收编成「已修」）：
 *   ① 板子是 v2 要拆掉的那一份（`frontend/admin-web/src/app/(dashboard)/settings/page.tsx`
 *      头注释「已知 v1 债务」）；
 *   ② 它属**另一页**（`/production/routings`）的用户可见面 —— 本包只对 `/settings` 的算料域取证。
 * v2 拆解或另包落地时**同批删条目**（`dupStaleLedger` 会逼着删）。
 */
export const DUP_LEDGER = [
  'src/components/production-config/ProcessConfigBoard.tsx::ProcessConfigBoard#1',
]

/** 命中清单（台账过滤后）：未登记即红 */
export function dupOffenders(root) {
  const { files, sites } = duplicateSignalSites(root)
  const offenders = sites.filter((s) => !DUP_LEDGER.includes(s.key))
  return { files, sites, offenders }
}

/** 台账「空转」检测：登记了但**不再命中**的条目（只许缩短 ⇒ 必须删） */
export function dupStaleLedger(root) {
  const { sites } = duplicateSignalSites(root)
  const live = new Set(sites.map((s) => s.key))
  return DUP_LEDGER.filter((k) => !live.has(k))
}


// ═══════════════════════════════════════════════════════════════════════════════
// 第三条判据：「**读面失败与空态同屏**」（issue #6713 + #6714，一把尺子）
//
// 病灶（真机注入 `/api/admin/**` ⇒ 500、每页等 6s 看持久面，main `2adad8660`）：
//   /chat          「暂无会话」
//   /employees     「暂无数据」+「共 0 条」
//   /notifications 「暂无通知」
//   /products      「暂无数据」
//   /shipments     表头在、零行、无失败面（与「没有发货单」不可区分）
//   /production/remnants  失败横幅在，底下仍印「还没有余料记录（…）」
// ⇒ 读不到 = 被说成「没有」。同族 #6691/#6702/#6703 各扫各的，这几页**不在任何尺子的面里**。
// ═══════════════════════════════════════════════════════════════════════════════

/** 「读面失败 ⇄ 空态同屏」条的判据面（与第一条同面 + chat 组件族） */
export const SYNC_SCOPES = ['src/app/(dashboard)', 'src/components/chat']

/**
 * **空态断言**文案形态（**有意收窄**，只认三种措辞：见文件头「边界」）。
 * 🔴 **失败文案不算**空态断言 —— 本判据治的是「把读不到说成没有」，不是「把读不到说出来」。
 */
export const EMPTY_TEXT_RE = /暂无|没有匹配的|还没有[^\n]{0,24}(记录|数据|内容)/
/** 行内字段占位（不是列表体空态）：`暂无消息` 一类，判它 = 假红 */
const INLINE_PLACEHOLDER_RE = /暂无(消息|物流轨迹|生产进度|订单数据|标签)/
/** 失败文案（读不到被**正确**说出来的形态）—— 从「空态断言」里排除 */
const FAILURE_COPY_RE = /加载失败|读取失败|不可用|不可信/
/**
 * **读面失败锚**：`data-testid="<读面>-load-failed"` / `"-load-error"`（本仓命名规范）
 * 及其重试出口。取自共享件 `frontend/admin-web/src/components/common/ListLoadError.tsx`
 * 的约定（`testId` + `${testId}-retry`）与既有页面（`orders-load-error` 一族）。
 */
export const FAILURE_ANCHOR_RE = /data-testid=\{?["'`][A-Za-z0-9_-]*(?:-(?:error|failed|retry)|load-(?:error|failed))["'`]\}?/

/**
 * **修复登记册**（本包改对的读面）。
 *
 * ⚠️ 键是**可读名**（不是判据），机器核的对象是 `file` / `anchor` / `emptyTestId` / `failureKey`：
 *   · `anchor` / `emptyTestId` ⇒ 判据 2 的逐字接线锚（缺一即红并**具名**报出缺哪条）；
 *   · `failureKey` ⇒ 「这次读失败了」的**前端读数**（必须是 store/state 里真的存在的那个 key）。
 */
export const READ_SURFACES = {
  'chat-sessions': {
    issue: '#6713',
    file: 'src/components/chat/SessionList.tsx',
    anchor: 'chat-sessions-load-failed',
    emptyTestId: 'chat-sessions-empty',
    failureKey: 'sessionsLoadFailed',
    // 失败读数**产生**在 store（其余读面的失败态是页面本地 state）⇒ 判据 4 才核它
    failureFrom: { file: 'src/store/chat.ts' },
  },
  'shipments-list': {
    issue: '#6714',
    file: 'src/app/(dashboard)/shipments/page.tsx',
    anchor: 'shipments-load-failed',
    emptyTestId: 'shipments-empty',
    failureKey: 'loadError',
  },
  'remnant-ledger': {
    issue: '#6714',
    file: 'src/app/(dashboard)/production/remnants/page.tsx',
    anchor: 'remnant-ledger-load-failed',
    // 该页的重试出口沿用 #6702 已立的 testid（既有名字不改造）
    retryAnchor: 'remnant-ledger-retry',
    emptyTestId: 'remnant-empty',
    failureKey: 'error',
  },
  'employees-list': {
    issue: '#6714',
    file: 'src/app/(dashboard)/employees/page.tsx',
    anchor: 'employees-load-failed',
    emptyTestId: 'employees-empty',
    failureKey: 'loadFailed',
  },
  'notifications-list': {
    issue: '#6714',
    file: 'src/app/(dashboard)/notifications/page.tsx',
    anchor: 'notifications-load-failed',
    emptyTestId: 'notifications-empty',
    failureKey: 'loadFailed',
  },
  'products-list': {
    issue: '#6714',
    file: 'src/app/(dashboard)/products/page.tsx',
    anchor: 'products-load-failed',
    emptyTestId: 'products-empty',
    failureKey: 'loadFailed',
  },
}

/**
 * **正向核**：每条登记读面必须逐字含这些接线（**单一源**：由 `READ_SURFACES` 派生，不写第二份）。
 * 删掉任一处（把失败分支的守卫摘了、把锚点换回空态）⇒ 当场红。
 */
export const POSITIVE_ANCHORS = /** @type {Record<string, string[]>} */ ({})
for (const [name, surf] of Object.entries(READ_SURFACES)) {
  POSITIVE_ANCHORS[name] = [
    `data-testid="${surf.anchor}"`,
    `data-testid="${surf.retryAnchor || `${surf.anchor}-retry`}"`,
    `data-testid="${surf.emptyTestId}"`,
    // 「失败 key 参与空态那一支的判据」由 `renderGuardsFromSource` 判（形态无关，见其注释）
    surf.failureKey,
  ]
}

/**
 * **未判 / 待另单 / 已判为非缺陷**（普查到、本包不动）：登记在这里，**不许**静默放行。
 * 每条必须给 `observed`（用户可见面名）+ `evidence`（为什么现在不判 / 归谁）。
 */
export const PENDING_AUDIT = {
  'agent-workspace': {
    observed: '/agent-workspace（180 字壳页）',
    evidence: '极小的壳页（无表格 / 无表单控件、未观察到数据区）⇒ 本次**不判**它是不是缺陷（需先知道它的预期形态）。登记口径 = 「未分类」，**不是**放行（#6714 的普查表同款）。',
  },
  briefing: {
    observed: '/briefing（204 字壳页）',
    evidence: '同 `/agent-workspace`：无数据区可观察 ⇒ 登记为「未分类 / 待判」，既不判红也不放行。',
  },
  categories: {
    observed: '/categories（153 字壳页）',
    evidence: '同 `/agent-workspace`：无数据区可观察 ⇒ 登记为「未分类 / 待判」，既不判红也不放行。',
  },
  'customers-detail-sessions': {
    observed: 'src/app/(dashboard)/customers/[id]/CustomerDetail.tsx 的「暂无订单记录 / 暂无会话记录」',
    evidence: '明细页内嵌的两个列表空态（读面失败只 toast ⇒ 两个列表同时印空态）。**存量债**：票据未点名，是否按同范式修由后续单裁定 ⇒ 登记待另单。',
  },
  'after-sales-detail-records': {
    observed: 'src/app/(dashboard)/after-sales/[id]/AfterSalesDetail.tsx 的「暂无处理记录」',
    evidence: '同 `customers-detail-sessions`：明细页内嵌列表空态，票据未点名 ⇒ 登记待另单。',
  },
  'products-detail-images': {
    observed: 'src/app/(dashboard)/products/[id]/ProductDetail.tsx 的「暂无图片」',
    evidence: '商品图集随商品载荷下发（**没有独立读接口**）⇒ 不产生「读不到 vs 真是空」的分歧，本形态不成立；归零判据 = 该区接入独立读接口时同批修。',
  },
  'chat-insight-panels': {
    observed: 'src/components/chat/SessionInsight.tsx 的「暂无待办 / 本会话还没有记录」',
    evidence: '洞察抽屉的待办与消息区来自**当前会话消息里的载荷**（无独立读接口）⇒ 无分歧面；归零判据 = 接入独立读接口时同批修。',
  },
  'chat-customer-panel': {
    observed: 'src/components/chat/CustomerPanel.tsx 的「暂无」（电话 / 注册天数）',
    evidence: '客户信息随当前会话载荷下发（`customerInfo`），无独立读接口 ⇒ 行内缺失占位，非列表体空态。',
  },
  'finance-fund-flow-rows': {
    observed: 'src/app/(dashboard)/finance/page.tsx 的「暂无资金流水 / 暂无数据 / 暂无对账数据」',
    evidence: '该页已有 `finance-summary-load-error` 一族失败锚（#6703 已修），但**表体空态**与失败态是否同屏**未复核**（本包不碰 finance 面）⇒ 登记待复核单。',
  },
  'knowledge-cards': {
    observed: 'src/app/(dashboard)/knowledge/page.tsx 的「暂无知识卡片 / 暂无待确认候选 / 暂无可用模板」',
    evidence: '该页已有 `knowledge-load-error` + 逐区失败文案（#6703 已修）；表体空态的互斥性**未复核** ⇒ 登记待复核单。',
  },
  'ship-order-items': {
    observed: 'src/app/(dashboard)/orders/[id]/ship/ShipOrder.tsx 的「暂无商品」',
    evidence: '发货页明细随订单载荷下发（无独立读接口）⇒ 无分歧面。',
  },
}

/**
 * **有主 / 有意不动**（超范围）：每条必须给 `owner`（哪个单的面）+ `evidence`。
 * 🔴 这是**如实声明边界**，不是「判过了」。
 */
export const OUT_OF_SCOPE = {
  'stock-ledger': {
    owner: '#6707',
    evidence: '该页的**权限归因**属 #6707 的面（本包明确不碰，避免撞写面）。',
  },
  'dashboard-amounts': {
    owner: '#6715',
    evidence: '工作台金额 / 图表口径属 #6715 的面（本包明确不碰）。',
  },
  'shared-table-default-empty': {
    owner: '#6714（本包，有意不改）',
    evidence: '共享 `frontend/admin-web/src/components/ui/Table.tsx` 的**默认** `emptyText = 暂无数据` 不在本包射程（改默认值会波及全站所有调用方）⇒ 本包改的是**页面级失败面**（见 `READ_SURFACES`）。',
  },
}

/**
 * 票据点名的读面（**未登记即红**）：必须在 `READ_SURFACES` / `PENDING_AUDIT` / `OUT_OF_SCOPE`
 * **三张表之一**出现。
 */
export const REQUIRED_SURFACES = [
  { key: 'chat-sessions', issue: '#6713', required: true },
  { key: 'employees-list', issue: '#6714', required: true },
  { key: 'notifications-list', issue: '#6714', required: true },
  { key: 'products-list', issue: '#6714', required: true },
  { key: 'shipments-list', issue: '#6714', required: true },
  { key: 'remnant-ledger', issue: '#6714', required: true },
]

/**
 * 台账：**已判为非缺陷 / 待另单**的空态文案（**只许缩短**）。
 * 键 = `仓库相对路径::文案`（**不写行号**：活跃文件的裸行号几分钟就失效）。
 * 条目一旦不再命中其声明的文案 ⇒ `emptyStateStale` 判红 ⇒ 逼着删干净。
 */
export const EMPTY_STATE_LEDGER = [
  'src/app/(dashboard)/customers/[id]/CustomerDetail.tsx::暂无订单记录',
  'src/app/(dashboard)/customers/[id]/CustomerDetail.tsx::暂无会话记录',
  'src/app/(dashboard)/after-sales/[id]/AfterSalesDetail.tsx::暂无处理记录',
  'src/app/(dashboard)/products/[id]/ProductDetail.tsx::暂无图片',
  'src/components/chat/SessionInsight.tsx::暂无待办',
  'src/components/chat/SessionInsight.tsx::本会话还没有记录',
  'src/components/chat/CustomerPanel.tsx::暂无',
  'src/app/(dashboard)/finance/page.tsx::暂无资金流水',
  'src/app/(dashboard)/finance/page.tsx::暂无数据',
  'src/app/(dashboard)/finance/page.tsx::暂无对账数据',
  'src/app/(dashboard)/knowledge/page.tsx::暂无知识卡片，点击「新建知识卡片」或从行业模板一键套用',
  'src/app/(dashboard)/knowledge/page.tsx::暂无待确认候选。人工客服会话结束后将自动提炼知识；也可通过「文档提炼」从资料中提炼。',
  'src/app/(dashboard)/knowledge/page.tsx::暂无可用模板',
  'src/app/(dashboard)/orders/[id]/ship/ShipOrder.tsx::暂无商品',
  'src/app/(dashboard)/after-sales/page.tsx::暂无售后工单',
  'src/app/(dashboard)/agent-workspace/human-sessions/page.tsx::暂无转人工会话',
]

/** 台账冻结基线（**只许缩短**；`EMPTY_STATE_LEDGER.length > EMPTY_STATE_LEDGER_FLOOR` ⇒ 红） */
export const EMPTY_STATE_LEDGER_FLOOR = 16

/** 判据 1：票据点名的读面三张表都没登记的（**未登记即红**） */
export function unregisteredSurfaces(surfaces = READ_SURFACES, pending = PENDING_AUDIT, outOfScope = OUT_OF_SCOPE) {
  const known = new Set([...Object.keys(surfaces), ...Object.keys(pending), ...Object.keys(outOfScope)])
  return REQUIRED_SURFACES.filter((x) => x.required && !known.has(x.key))
}

/** 判据 2：登记读面缺哪条接线（返回 `{ key, file, missing }`；`missing` 空 = 通过） */
export function missingWiring(root, surfaces = READ_SURFACES, positive = POSITIVE_ANCHORS) {
  const out = []
  for (const [key, surf] of Object.entries(surfaces)) {
    let source = ''
    try {
      source = readFileSync(join(root, surf.file), 'utf8')
    } catch {
      out.push({ key, file: surf.file, missing: [`文件不存在：${surf.file}`] })
      continue
    }
    out.push({ key, file: surf.file, missing: (positive[key] || []).filter((needle) => !source.includes(needle)) })
  }
  return out
}

/**
 * 一段**渲染源码**是否把失败态与空态分开了（判据 2 的判别力自证夹具 / 页面实例判据的共用口径）。
 *
 * 五条同时成立才算分开：
 *   ① 有读面失败锚；② 有重试出口；③ **失败 key 参与空态那一支的判据**
 *   （`!k && …` / `k ? … :` / `k && …`）；④ 空态锚那个元素里**不夹失败文案**（互斥位）；
 *   ⑤ 失败 key 进了共享失败件的 props（`readFailed={k}` / `error={k}` 一族）。
 *
 * @param {string} source 渲染源码（**只吃文本**：守卫用内存假源码做自证）
 * @param {{failureKey: string, anchorTestId: string, emptyTestId: string}} opts
 */
export function renderGuardsFromSource(source, { failureKey, anchorTestId, emptyTestId }) {
  const checks = {
    anchor: source.includes(`data-testid="${anchorTestId}"`),
    retry: source.includes(`data-testid="${anchorTestId}-retry"`),
    emptyGuarded: new RegExp(`(!\\s*${failureKey}\\b)|(\\b${failureKey}\\s*\\?)|(\\b${failureKey}\\s*&&)`).test(source),
    emptyAnchorClean: (() => {
      const i = source.indexOf(`data-testid="${emptyTestId}"`)
      if (i < 0) return false
      return !/加载失败|读取失败|不可信/.test(source.slice(i, i + 400))
    })(),
  }
  return { ...checks, ok: Object.values(checks).every(Boolean) }
}

/** 台账键 = `仓库相对路径::文案` */
export function emptyStateKey(site) {
  return `${site.file}::${site.text.replace(/\s+/g, ' ')}`
}

/**
 * 一段源码里的**空态断言**出现位置（行号 + 文案）。
 *
 * 取两种承载：① JSX 文本节点；② JSX 属性值 / 三元里的字符串字面量
 * （`{loading ? … : loadFailed ? … : '暂无会话'}`、`emptyText: '暂无通知'`）。
 * 注释天然不在内（AST 无注释节点）—— 不会被本文件自己的文案喂红。
 *
 * @param {string} source
 * @param {{file?: string, tsModule?: typeof ts}} [opts]
 */
export function emptyStateSitesFromSource(source, { file = '<probe>.tsx', tsModule = ts } = {}) {
  const sf = tsModule.createSourceFile(file, source, tsModule.ScriptTarget.Latest, true, tsModule.ScriptKind.TSX)
  const out = []
  const ok = (t) => Boolean(t) && !INLINE_PLACEHOLDER_RE.test(t) && !FAILURE_COPY_RE.test(t) && EMPTY_TEXT_RE.test(t)
  const visit = (node) => {
    if (tsModule.isJsxText(node) && ok(node.text.trim())) {
      out.push({ file, line: sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1, text: node.text.trim() })
    } else if (
      tsModule.isJsxAttribute(node) &&
      node.initializer &&
      tsModule.isStringLiteral(node.initializer) &&
      ok(node.initializer.text)
    ) {
      out.push({ file, line: sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1, text: node.initializer.text })
    } else if (tsModule.isStringLiteral(node) && ok(node.text)) {
      const parent = node.parent
      if (
        parent &&
        (tsModule.isConditionalExpression(parent) ||
          tsModule.isBinaryExpression(parent) ||
          tsModule.isParenthesizedExpression(parent) ||
          tsModule.isPropertyAssignment(parent) ||
          tsModule.isArrayLiteralExpression(parent))
      ) {
        out.push({ file, line: sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1, text: node.text })
      }
    }
    tsModule.forEachChild(node, visit)
  }
  tsModule.forEachChild(sf, visit)
  return out
}

/** 该文件是否带**读面失败锚** */
export function hasFailureAnchor(source) {
  return FAILURE_ANCHOR_RE.test(source)
}

/** 命中清单（**单一源**）：面内每个文件的空态断言 + 该文件有没有失败锚 */
export function emptyStateSites(root, scopes = SYNC_SCOPES) {
  const files = []
  for (const scope of scopes) {
    for (const f of walk(join(root, scope))) {
      const rel = relative(root, f).split('\\').join('/')
      if (/\.test\.tsx?$/.test(rel)) continue
      files.push(rel)
    }
  }
  files.sort()
  const sites = []
  for (const file of files) {
    const source = readFileSync(join(root, file), 'utf8')
    const guarded = hasFailureAnchor(source)
    for (const m of emptyStateSitesFromSource(source, { file })) {
      sites.push({ ...m, guarded, key: emptyStateKey({ file, text: m.text }) })
    }
  }
  return { files, sites }
}

/**
 * **store 文件面**（`read*` / `fetch*` 动作所在）：判据 4 的扫描对象。
 * 为什么单列：`SessionList` 只是**消费**失败读数，**产生**它的是 `store/chat.ts` 的
 * `fetchSessions` —— 只核消费方会让「store 又改回只 console.error」静默通过。
 */
export const STORE_FILES = ['src/store/chat.ts']

/** 取一段源码里全部 `fetch*` / `load*` 动作的 `{ name, line, body }` */
export function storeActionsFromSource(source, { tsModule = ts } = {}) {
  const sf = tsModule.createSourceFile('store.ts', source, tsModule.ScriptTarget.Latest, true, tsModule.ScriptKind.TS)
  const out = []
  const visit = (node) => {
    if (ts.isPropertyAssignment(node) && node.name && ts.isIdentifier(node.name) && /^(fetch|load)[A-Z]/.test(node.name.text)) {
      const init = node.initializer
      if (ts.isArrowFunction(init) || ts.isFunctionExpression(init)) {
        out.push({
          name: node.name.text,
          line: sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1,
          body: init.getText(sf),
        })
      }
    }
    tsModule.forEachChild(node, visit)
  }
  tsModule.forEachChild(sf, visit)
  return out
}

/**
 * 判据 4：登记读面的 `failureKey` 必须**在 store 里真的被写成 true**（在同一动作体内）。
 *
 * 🔴 这是「**有消费点**」的反面保证：`#6664` 删掉的那个 `error` 字段之所以是**假承诺**，
 * 就因为全仓没有消费点；本判据同时核两半 —— **产生**（store 写入）与**消费**
 * （`POSITIVE_ANCHORS` 的接线）—— 只留一半就会重新长出「假承诺」。
 */
export function storeFailureKeyOffenders(root, surfaces = READ_SURFACES, storeSources = /** @type {{file: string, source: string}[] | null} */ (null)) {
  // `storeSources` 可注入（判别力自证用**内存变异**，不必碰真文件 —— 见守卫判据 ④）
  const sources = storeSources || STORE_FILES.map((file) => ({ file, source: readFileSync(join(root, file), 'utf8') }))
  const allActions = sources.flatMap((s) => storeActionsFromSource(s.source).map((a) => ({ file: s.file, ...a })))
  const fullSource = sources.map((s) => s.source).join('\n')
  const out = []
  for (const [key, surf] of Object.entries(surfaces)) {
    // 只有「失败读数产生在 store」的读面才走这条（其余读面的失败态是页面本地 state，
    // 由 `POSITIVE_ANCHORS` 的正向核 + 页面实例判据承担）
    if (!surf.failureFrom) continue
    if (!new RegExp(`\\b${surf.failureKey}\\b`).test(fullSource)) {
      out.push({ key, file: surf.file, reason: `store 里没有声明 failureKey「${surf.failureKey}」（消费方读不到东西）` })
      continue
    }
    const producer = allActions.find((a) => new RegExp(`${surf.failureKey}\\s*:\\s*true`).test(a.body))
    if (!producer) {
      out.push({
        key,
        file: surf.file,
        reason: `没有任何 store 动作把「${surf.failureKey}」置 true ⇒ 失败时消费方永远看不到（假承诺）`,
      })
    }
  }
  return out
}

/** 判据 3 的判红面（未登记即红）+ 台账空转 */
export function emptyStateOffenders(root, ledger = EMPTY_STATE_LEDGER) {
  const { files, sites } = emptyStateSites(root)
  const keys = new Set(ledger)
  const unregistered = sites.filter((s) => !s.guarded && !keys.has(s.key))
  const live = new Set(sites.map((s) => s.key))
  const stale = ledger.filter((k) => !live.has(k))
  return { files, sites, unregistered, stale }
}

const isMain = process.argv[1] && import.meta.url.endsWith(process.argv[1].split('/').pop())
if (isMain) {
  const root = process.env.MIGAO_SCAN_ROOT || join(process.cwd())
  const { files, sites, offenders } = findOffenders(root)
  console.log(`扫描 ${files.length} 个 (dashboard) 文件 · 命中「读失败被吞」${sites.length} 处 · 台账豁免 ${LEDGER.length} 条\n`)
  for (const s of sites) {
    const mark = offenders.includes(s) ? '❌ 未登记' : '✅ 已登记'
    console.log(`  ${mark} ${s.key}  (L${s.line} 清空 ${s.cleared.join('/')})`)
  }
  const stale = staleLedger(root)
  if (stale.length) {
    console.log(`\n台账里这些条目**不再命中**，请删掉：\n  ${stale.join('\n  ')}`)
  }
  console.log(`\n未登记命中 ${offenders.length} 条 · 僵尸条目 ${stale.length} 条`)

  // ── 第三条判据：读面失败 ⇄ 空态同屏（issue #6713 + #6714） ──
  const empty = emptyStateOffenders(root)
  const missingSurfaces = unregisteredSurfaces()
  const wiring = missingWiring(root).filter((w) => w.missing.length > 0)
  console.log(
    `\n扫描 ${empty.files.length} 个文件（${SYNC_SCOPES.join(' + ')}）· ` +
      `命中「空态断言」${empty.sites.length} 处 · 台账豁免 ${EMPTY_STATE_LEDGER.length} 条（基线 ${EMPTY_STATE_LEDGER_FLOOR}）\n`,
  )
  for (const e of empty.sites) {
    const mark = e.guarded ? '✅ 有失败锚' : EMPTY_STATE_LEDGER.includes(e.key) ? '📝 已登记' : '❌ 未登记'
    console.log(`  ${mark} [${e.file}] 第 ${e.line} 行「${e.text}」`)
  }
  for (const k of empty.stale) console.log(`  🔴 僵尸台账条目（不再命中，必须删）：${k}`)
  for (const x of missingSurfaces) console.log(`  🔴 票据点名的读面未登记：${x.key}（${x.issue}）`)
  for (const w of wiring) console.log(`  🔴 接线缺失 ${w.key}（${w.file}）：${w.missing.join(' / ')}`)
  const storeBad = storeFailureKeyOffenders(root)
  for (const x of storeBad) console.log(`  🔴 失败读数未落地 ${x.key}（${x.file}）：${x.reason}`)
  const badSync =
    empty.unregistered.length > 0 ||
    empty.stale.length > 0 ||
    missingSurfaces.length > 0 ||
    wiring.length > 0 ||
    storeBad.length > 0 ||
    EMPTY_STATE_LEDGER.length > EMPTY_STATE_LEDGER_FLOOR
  console.log(badSync ? '  🔴 判红：未登记空态 / 僵尸条目 / 读面未登记 / 接线缺失 / 台账超基线' : '  ✅ 空态与读面失败互斥、读面已登记、台账未超基线')

  // ── 第二条判据：同一次读失败的重复信号（issue #6669） ──
  const dup = dupOffenders(root)
  console.log(`\n扫描 ${dup.files.length} 个 (${DUP_SCOPE}) 文件 · 命中「同一次读失败多处信号」${dup.sites.length} 处 · 台账豁免 ${DUP_LEDGER.length} 条\n`)
  for (const s of dup.sites) {
    const mark = dup.offenders.includes(s) ? '❌ 未登记' : '✅ 已登记'
    console.log(`  ${mark} ${s.key}  (L${s.line} 内联「${s.inlineMsg}」+ toast×${s.toastCount})`)
  }
  const dupStale = dupStaleLedger(root)
  if (dupStale.length) {
    console.log(`\n重复信号台账里这些条目**不再命中**，请删掉：\n  ${dupStale.join('\n  ')}`)
  }
  console.log(`\n未登记命中 ${dup.offenders.length} 条 · 僵尸条目 ${dupStale.length} 条`)
  process.exit(
    offenders.length || stale.length || badSync || dup.offenders.length || dupStale.length ? 1 : 0,
  )
}
