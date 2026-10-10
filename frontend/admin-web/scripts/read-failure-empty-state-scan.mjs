#!/usr/bin/env node
// case_ids: UI-057, UI-058
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
  // ── 本包（#6663）**已修**的三页：不再命中 ⇒ 条目为空（**空台账是目标**，不是漏登记）──
  //
  // ── 存量债：本包文件族**之外**（写面属并发包 ⇒ §17.2 零共享写路径，本包不改它们的码）──
  //    登记是**如实记账**（不收编成「已修」）；对应包落地后必须回来**删掉**这几条
  //    （失效即红 ⇒ 逼着删干净）。每条后面的「归属」是判定依据：文件路径落在谁的文件族里。
  //
  // #6664 的盘（chat / orders / shipments 面）：
  'src/app/(dashboard)/inbound-orders/page.tsx::InboundOrdersPage#1',      // 归属 #6664：读失败 setRows([]) ⇒ 画成「没有入库单」
  'src/app/(dashboard)/inbound-orders/new/page.tsx::NewInboundOrderPage#1', // 归属 #6664：商品搜索失败 setProductOptions([]) ⇒ 画成「搜不到」
  'src/app/(dashboard)/inbound-orders/new/page.tsx::pickProduct#1',        // 归属 #6664：明细读失败 setProductSkus([]) ⇒ 画成「这个商品没有规格」
  'src/app/(dashboard)/orders/[id]/OrderDetail.tsx::OrderDetailPage#1',   // 归属 #6664：发货明细读失败 setShipments(null)，渲染面对 null 另说
  'src/app/(dashboard)/orders/new/page.tsx::load#1',                       // 归属 #6664：加工项目录读失败 setProcessingCatalog([])
  'src/app/(dashboard)/orders/new/page.tsx::load#2',                       // 归属 #6664：算料配置读失败 setCalcConfig(null)
  // ✅ 已于 2026-10-10 删条目：`src/app/(dashboard)/shipments/page.tsx::ShipmentsPage#1`
  //    —— #6664 包（PR #6673）把发货单读失败改成「说真话」，该点不再命中 ⇒ 按「台账只许缩短」同批删掉。
  //    （删条目是本台账的**唯一**合法方向；守卫会逼着删，不会让人留着僵尸豁免。）
  // 归属待定（既不在本包、也不在上面两个包的文件族里 ⇒ 单独跟一条）：
  'src/app/(dashboard)/stock-ledger/page.tsx::StockLedgerPage#3',          // 商品搜索失败 setOptions([])（同一 catch 已有 setSearchHint 话术，属灰区，登记待裁）
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
  process.exit(offenders.length || stale.length ? 1 : 0)
}
