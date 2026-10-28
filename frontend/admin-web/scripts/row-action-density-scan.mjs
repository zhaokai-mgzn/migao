#!/usr/bin/env node
// case_ids: UI-057, UI-058, UI-130
/**
 * 「操作列行内动作密度 ≤ 2」判据**单一源**（issue #8038，依据 #8035 审计）。
 *
 * ## 为什么要有它（而不是逐页手修完就完）
 *
 * #8035 审计（2026-10-28，基线 `origin/main@1c335b202`）的系统性缺陷只有一类 ——
 * **操作列密度**：`≥3 个同级可点` 共 5 页（`products` 5 / `knowledge` 4 / `approvals` 3 /
 * `rework-orders` 3 / `employees` 3）。#8011 已在 `/orders` 落过「1 主行动 + ⋯ 菜单」的**实例判据**
 * （`tests/unit/pages/orders-list-row-actions.test.tsx` 的「每行可点 ≤ 2」），但那条判据**只看一页** ——
 * 于是同一形态在另外 5 页又长了一遍。本文件把那句判据抽成**类级扫描器**：
 * 判据（`actionSurfacesFromSource`）与台账（`row-action-density-ledger.json`）都只有这一份，
 * 守卫 `tests/unit/row-action-density-guard.test.ts` 与命令行**共用**它（不写第二份规则）。
 *
 * 成熟路径同构于 `read-failure-empty-state-scan.mjs` / `count-row-derived-scan.mjs`：
 * **扫描判据 + 豁免台账（只许缩短 / 未登记即红 / 空转即红）+ 正向锚点**。
 *
 * ## 判的是什么（口径）
 *
 * 一个「操作」列的行内动作面，**一行同时可点**的上限 = **2**：
 * `1 个主行动 + 1 个「⋯」触发器`（#8011 已验收的形态）。
 * 度量 = **该动作面在「一个分支里同时渲染」的可点元素数**：
 * - 平级 `<Button>` / `<button>` / `<RowActionLink>` / `<a>` 各计 1；
 * - 共享原语 `<RowActions>` 计 **1**（它内部恒渲染一个 ⋯ 触发器），其 `children`（主行动）照常计；
 * - 条件分支（`cond ? A : B` / `cond && A`）取**各分支最大值**（互斥 ⇒ 不叠加）；
 * - `.map()` 等回调里的 JSX 按其自身形态计（`items.map(p => <button/>)` = 1，符合「每行一个」语义）；
 * - 动作面把渲染委托给本文件的渲染函数（`{renderActions(order)}`）⇒ **跟随进函数体**再量
 *   （否则 `orders` 那类「表体调 renderActions」的形态会被读成 0 个 —— 那是假绿）。
 *
 * ## 判据（各自独立红）
 *
 * ① **未登记即红**：密度 > 2 且不在台账 ⇒ 红（附文件 + 读数 + 面数）；
 * ② **台账只许缩短**：条目数 > `frozen_count` ⇒ 红；条目**已不再是缺陷** ⇒ 僵尸红（逼着删）；
 * ③ **债务不许放大**：台账条目的当前密度 > 登记时冻结的读数 ⇒ 红（`frozen` 字段）；
 * ④ **正向锚**：已收口的三面（`orders` / `products` / `knowledge`）必须逐字含 `<RowActions` ——
 *    「把动作整列删掉」也能让密度变 0，这条把那种假绿堵掉。
 *
 * ## 边界（照实登记，`migao-dev-flow` §19.1）
 *
 * - **静态判据**：判不了「菜单展开后落点是否被裁」（真机视觉，集成侧截图复核），
 *   也判不了**运行时**是否真的收起态不进 DOM（那是原语自己的判据：
 *   `tests/unit/components/RowActions.test.tsx`）；
 * - **跨组件不可见**：动作面调用**别的文件**里的组件（`<SomeActionCell/>`）时，本扫描器看不进去 ⇒
 *   计 0。这是有意的取舍（不做跨文件调用图），代价是那种形态要自带实例判据；
 * - **同字段互斥分支仍会叠加**：`{status === 'a' && <B1/>}{status === 'b' && <B2/>}` 语法上是两个
 *   平级条件 ⇒ 计 2（真实同行 1 个）。判据只在「会误判成红」的方向上偏保守，**不会假绿**；
 *   要精确就按共享原语的形态写（主行动走 `children`、其余走 `items` 数据）。
 * - 只扫 `SCOPES`；只认源码文本 / AST。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

/** 判据面：商家后台页面 + 行内动作组件（`products` / `orders` 的表格在 `src/components`） */
export const SCOPES = ['src/app/(dashboard)', 'src/components']
const SKIP_DIRS = new Set(['node_modules', '.next', 'dist', 'coverage', '__pycache__'])

/** 一行同时可点上限：1 主行动 + 1 个「⋯」触发器 */
export const MAX_CLICKABLE_PER_ROW = 2

/** 共享原语（issue #8038）：它内部恒渲染一个 ⋯ 触发器 */
export const PRIMITIVE = 'RowActions'

/** 「可点动作」的既有形态（本仓行内动作只有这几种；`a` 兜住跳转链） */
const CLICKABLE = new Set(['Button', 'button', 'RowActionLink', 'a'])

/** 「操作」列表头文案（列定义式与原生 `<th>` 式共用这一个口径） */
const ACTION_HEADER = '操作'

const LEDGER_PATH = join(dirname(fileURLToPath(import.meta.url)), '../tests/unit/row-action-density-ledger.json')

function nameOf(nameNode) {
  if (!nameNode) return ''
  if (ts.isIdentifier(nameNode) || ts.isStringLiteral(nameNode)) return nameNode.text
  return ''
}

function tagNameOf(node) {
  const tag = ts.isJsxElement(node) ? node.openingElement.tagName : node.tagName
  if (ts.isIdentifier(tag)) return tag.text
  return tag.getText()
}

/** JSX 的纯文本内容（`<th>操作</th>` 的判定用） */
function jsxTextContent(node) {
  let out = ''
  const walkText = (n) => {
    if (ts.isJsxText(n)) {
      out += n.text
      return
    }
    if (ts.isJsxExpression(n) && n.expression) return
    ts.forEachChild(n, walkText)
  }
  walkText(node)
  return out
}

function attrText(node, attrName) {
  const attrs = ts.isJsxElement(node) ? node.openingElement.attributes : node.attributes
  for (const a of attrs.properties) {
    if (ts.isJsxAttribute(a) && a.name.getText() === attrName) {
      if (!a.initializer) return ''
      if (ts.isStringLiteral(a.initializer)) return a.initializer.text
      return a.initializer.getText()
    }
  }
  return ''
}

function walkAll(node, visit) {
  visit(node)
  ts.forEachChild(node, (c) => walkAll(c, visit))
}

/** 本文件里的具名渲染函数（`const f = (…) => …` / `function f(…) {}`），供「委托式」动作面跟随 */
function collectRenderFunctions(sf) {
  const fns = new Map()
  walkAll(sf, (node) => {
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer) {
      if (ts.isArrowFunction(node.initializer) || ts.isFunctionExpression(node.initializer)) {
        fns.set(node.name.text, node.initializer)
      }
    } else if (ts.isFunctionDeclaration(node) && node.name) {
      fns.set(node.name.text, node)
    }
  })
  return fns
}

/**
 * 一个表达式在「一个分支里同时渲染」的可点数。
 *
 * 分支取 max、平级取 sum —— 见文件头「度量」一节。
 */
function densityOf(node, ctx) {
  if (!node) return 0

  if (ts.isJsxElement(node) || ts.isJsxSelfClosingElement(node)) {
    const tag = tagNameOf(node)
    // 共享原语：内部恒渲染一个 ⋯ 触发器（+1）；它的 children = 主行动，照常量
    const self = CLICKABLE.has(tag) ? 1 : tag === PRIMITIVE ? 1 : 0
    if (ts.isJsxSelfClosingElement(node)) return self
    return self + densityOfChildren(node.children, ctx)
  }
  if (ts.isJsxFragment(node)) return densityOfChildren(node.children, ctx)
  if (ts.isJsxExpression(node)) return node.expression ? densityOf(node.expression, ctx) : 0

  // 条件分支：互斥 ⇒ 取最大，不叠加
  if (ts.isConditionalExpression(node)) {
    return Math.max(densityOf(node.whenTrue, ctx), densityOf(node.whenFalse, ctx))
  }
  if (ts.isBinaryExpression(node)) {
    const k = node.operatorToken.kind
    if (
      k === ts.SyntaxKind.AmpersandAmpersandToken ||
      k === ts.SyntaxKind.BarBarToken ||
      k === ts.SyntaxKind.QuestionQuestionToken
    ) {
      return Math.max(densityOf(node.left, ctx), densityOf(node.right, ctx))
    }
    return 0
  }
  if (ts.isParenthesizedExpression(node) || ts.isAsExpression(node) || ts.isNonNullExpression(node)) {
    return densityOf(node.expression, ctx)
  }
  // 函数体（箭头 / 函数表达式 / 方法）：量它的返回
  if (ts.isArrowFunction(node) || ts.isFunctionExpression(node) || ts.isFunctionDeclaration(node) || ts.isMethodDeclaration(node)) {
    return densityOf(node.body, ctx)
  }
  if (ts.isBlock(node)) {
    // 动作面的 render 常写成 `{ const x = …; return (<div>…) }`：取各分支 return 的最大值
    let max = 0
    const visitStmt = (stmt) => {
      if (ts.isReturnStatement(stmt)) {
        max = Math.max(max, densityOf(stmt.expression, ctx))
        return
      }
      ts.forEachChild(stmt, visitStmt)
    }
    node.statements.forEach(visitStmt)
    return max
  }
  // 委托式动作面：`{renderActions(order)}` ⇒ 跟随进本文件的渲染函数（否则读成 0 = 假绿）
  if (ts.isCallExpression(node)) {
    let inner = 0
    if (ts.isIdentifier(node.expression) && ctx.fns.has(node.expression.text) && !ctx.seen.has(node.expression.text)) {
      const name = node.expression.text
      if (ctx.depth < 4) {
        const next = { fns: ctx.fns, seen: new Set([...ctx.seen, name]), depth: ctx.depth + 1 }
        inner = densityOf(ctx.fns.get(name), next)
      }
    }
    // 回调里的 JSX（`.map(p => <button/>)`）按自身形态计
    const args = node.arguments.reduce((n, a) => n + densityOf(a, ctx), 0)
    return Math.max(inner, args)
  }
  return 0
}

function densityOfChildren(children, ctx) {
  let total = 0
  for (const child of children) {
    if (ts.isJsxText(child)) continue
    if (ts.isJsxExpression(child)) {
      total += child.expression ? densityOf(child.expression, ctx) : 0
      continue
    }
    total += densityOf(child, ctx)
  }
  return total
}

/**
 * 源码 → 该文件里**每个「操作」动作面**的读数（**纯函数**：守卫用它做判别力自证）。
 *
 * 两种在册形态：
 * ① **列定义式**（共享 `ui/Table` 或自带列对象）：`title: '操作'` 所在对象里的 `render`；
 * ② **原生表头式**：`<th>操作</th>` ⇒ 同文件里 `sticky right-0` 的表体格（本仓右缘冻结约定）。
 */
export function actionSurfacesFromSource(source, { file = '<probe>.tsx' } = {}) {
  const sf = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const ctx = { fns: collectRenderFunctions(sf), seen: new Set(), depth: 0 }
  const surfaces = []

  // ① 列定义式
  walkAll(sf, (node) => {
    if (!ts.isPropertyAssignment(node) || nameOf(node.name) !== 'title') return
    if (!ts.isStringLiteral(node.initializer) || node.initializer.text !== ACTION_HEADER) return
    const obj = node.parent
    if (!obj || !ts.isObjectLiteralExpression(obj)) return
    const render = obj.properties.find((p) => ts.isPropertyAssignment(p) && nameOf(p.name) === 'render')
    surfaces.push({
      kind: 'column',
      density: render ? densityOf(render.initializer, ctx) : 0,
    })
  })

  // ② 原生表头式：表头里真含「操作」⇒ 同文件的右缘冻结格就是它的表体
  const rawHeader = []
  walkAll(sf, (node) => {
    if (ts.isJsxElement(node) && tagNameOf(node) === 'th' && jsxTextContent(node).includes(ACTION_HEADER)) {
      rawHeader.push(node)
    }
  })
  if (rawHeader.length > 0) {
    let density = 0
    let cells = 0
    walkAll(sf, (node) => {
      if (!ts.isJsxElement(node) || tagNameOf(node) !== 'td') return
      if (!attrText(node, 'className').includes('right-0')) return
      cells += 1
      density = Math.max(density, densityOfChildren(node.children, ctx))
    })
    surfaces.push({ kind: 'cell', density, cells })
  }

  return surfaces
}

function walkFiles(dir, out = []) {
  let entries
  try {
    entries = readdirSync(dir)
  } catch {
    return out
  }
  for (const entry of entries) {
    if (SKIP_DIRS.has(entry)) continue
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) walkFiles(full, out)
    else if (/\.tsx$/.test(entry)) out.push(full)
  }
  return out
}

/** 命中清单（**单一源**）：扫 `SCOPES` 下每个文件，按文件取最大密度 */
export function rowActionSites(root) {
  const files = []
  for (const scope of SCOPES) files.push(...walkFiles(join(root, scope)))
  const sites = []
  for (const abs of files.map((f) => relative(root, f)).sort()) {
    const surfaces = actionSurfacesFromSource(readFileSync(join(root, abs), 'utf8'), { file: abs })
    if (surfaces.length === 0) continue
    sites.push({
      file: abs,
      key: abs,
      surfaces: surfaces.length,
      density: Math.max(...surfaces.map((s) => s.density)),
    })
  }
  return { files: files.length, sites }
}

/** 台账（**唯一真值 = tests/unit/row-action-density-ledger.json**；条目只许缩短） */
export function loadLedger() {
  return JSON.parse(readFileSync(LEDGER_PATH, 'utf8'))
}

/**
 * 正向核：本单已收口的**五面**必须逐字含共享原语（防「删掉整列 ⇒ 密度 0」的假绿）。
 *
 * 前三面 = #8038 的主面（#8011 起 orders 已是该形态）；后两面 = 本单收口的两块面板
 * （集成侧裁定「别留无主债务」，与三页同批收口 ⇒ 同批进正向锚）。
 */
export const FIXED_SURFACES = [
  { name: '销售订单列表', file: 'src/components/orders/OrderTable.tsx' },
  { name: '商品列表', file: 'src/components/products/ProductTable.tsx' },
  { name: '知识库', file: 'src/app/(dashboard)/knowledge/page.tsx' },
  { name: '工人档案面板', file: 'src/components/employees/WorkerProfilesPanel.tsx' },
  { name: '成品仓仓位面板', file: 'src/components/stock/WarehouseLocationPanel.tsx' },
]

export function missingFixedAnchors(root) {
  const missing = []
  for (const s of FIXED_SURFACES) {
    let src = ''
    try {
      src = readFileSync(join(root, s.file), 'utf8')
    } catch {
      missing.push(`${s.name}（文件不可读：${s.file}）`)
      continue
    }
    if (!src.includes(`<${PRIMITIVE}`)) missing.push(`${s.name}（${s.file} 里找不到 <${PRIMITIVE}）`)
  }
  return missing
}

/** 命中清单（台账过滤后）：**未登记即红** */
export function offendersOf(root) {
  const ledger = loadLedger().ledger || {}
  const { files, sites } = rowActionSites(root)
  const offenders = sites.filter((s) => s.density > MAX_CLICKABLE_PER_ROW && !(s.key in ledger))
  return { files, sites, offenders }
}

/** 台账「空转」检测：登记了但**已不再是缺陷**的条目（只许缩短 ⇒ 必须删） */
export function staleLedger(root) {
  const ledger = loadLedger().ledger || {}
  const { sites } = rowActionSites(root)
  const dense = new Set(sites.filter((s) => s.density > MAX_CLICKABLE_PER_ROW).map((s) => s.key))
  return Object.keys(ledger).filter((k) => !dense.has(k))
}

/** 台账「债务放大」检测：当前密度 > 登记时冻结的读数 ⇒ 红 */
export function grownLedger(root) {
  const ledger = loadLedger().ledger || {}
  const { sites } = rowActionSites(root)
  const byKey = new Map(sites.map((s) => [s.key, s]))
  const grown = []
  for (const [key, entry] of Object.entries(ledger)) {
    const site = byKey.get(key)
    if (!site) continue
    if (typeof entry.frozen === 'number' && site.density > entry.frozen) {
      grown.push({ key, frozen: entry.frozen, now: site.density })
    }
  }
  return grown
}

const isMain = process.argv[1] && import.meta.url.endsWith(process.argv[1].split('/').pop())
if (isMain) {
  const root = process.env.MIGAO_SCAN_ROOT || join(dirname(fileURLToPath(import.meta.url)), '..')
  const ledger = loadLedger()
  const { files, sites, offenders } = offendersOf(root)
  console.log(
    `扫描 ${files} 个 tsx 文件 · 命中「操作列动作面」${sites.length} 处 ` +
      `（台账 ${Object.keys(ledger.ledger || {}).length} / 未登记红 ${offenders.length}）\n`,
  )
  for (const s of sites) {
    const mark = s.density <= MAX_CLICKABLE_PER_ROW ? '✅ 达标' : s.key in (ledger.ledger || {}) ? '📒 已登记（存量债）' : '❌ 未登记'
    console.log(`  ${mark}  密度 ${s.density}  ${s.key}（面 ${s.surfaces}）`)
  }
  const stale = staleLedger(root)
  const grown = grownLedger(root)
  if (stale.length) console.log(`\n❌ 僵尸台账条目（已不再是缺陷，请删掉）：${stale.join('、')}`)
  if (grown.length) console.log(`\n❌ 债务放大：${grown.map((g) => `${g.key} 冻结 ${g.frozen} → 现 ${g.now}`).join('、')}`)
  const missing = missingFixedAnchors(root)
  if (missing.length) console.log(`\n❌ 正向锚缺失：${missing.join('、')}`)
  process.exit(offenders.length || stale.length || grown.length || missing.length ? 1 : 0)
}
