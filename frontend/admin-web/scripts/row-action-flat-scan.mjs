#!/usr/bin/env node
// case_ids: UI-057, UI-058, UI-130
/**
 * 「操作列按钮逐条平铺、不得收进「⋯」」判据**单一源**
 * （2026-11-09 用户裁定，取代 issue #8038 的「一行同时可点 ≤ 2」口径）。
 *
 * ## 为什么口径反转了
 *
 * #8035 审计（2026-10-28）把「操作列 ≥3 个同级可点」判成系统性缺陷，于是 #8011 / #8038 / #8039
 * 陆续把六页收成「1 主行动 + ⋯ 菜单」。2026-11-07 用户对销售订单列表**反向裁定**：
 * 「操作一列：把订单对应的可操作按钮直接展示出来，不要收在『...』里面」（issue #8837 / PR #8839）。
 * 2026-11-09 用户把同一裁定推广到商品管理列表与**观星台其余所有列表页**（issue #8849）。
 * ⇒ 密度上限作废（平铺本来就会让可点数变多）；本判据只判**形态**：
 * 「操作」列的动作面里**不许出现折叠原语**。
 *
 * ## 判的是什么（口径）
 *
 * ① **动作面**：列定义式 `title: '操作'` 所在对象的 `render`；或原生表头 `<th>操作</th>` 下
 *    同文件里右缘冻结（`className` 含 `right-0`）的表体格。两种在册形态与旧判据共用。
 * ② **折叠原语**（动作面内出现即红）：`<RowActions>`、`aria-label="更多操作"`、
 *    `aria-haspopup="menu"`、`<MoreHorizontal>`。前两个同时在全 `src/` 面禁（不止动作面）。
 * ③ **正向锚**：台账 `flat_surfaces` 的每一条必须逐字含 `<RowActionLink`，且仍被扫到 ——
 *    「把整列删掉」也能让折叠数变 0，这条堵掉那种假绿。
 * ④ AST 判据：注释里写 `<RowActions>` / 「更多操作」**不算**（`getText()` 会被注释骗，
 *    所以本扫描只看语法节点；判别力自证在守卫里有一组反例）。
 *
 * ## 边界（照实登记，`migao-dev-flow` §19.1）
 *
 * - **静态判据**：判不了真机观感（是否挤 / 是否被遮挡），那由 Playwright 截图 + 读图承担；
 * - **跨组件不可见**：动作面若渲染**别的文件**里的格子组件，本扫描器看不进去 ⇒ 计 0 个动作面；
 *   这种形态要自带实例判据（`FIXED` 式正向锚同理）；
 * - 只扫 `SCOPES`；只认源码文本 / AST。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

/** 判据面：商家后台页面 + 行内动作组件（`products` / `orders` 的表格在 `src/components`） */
export const SCOPES = ['src/app/(dashboard)', 'src/components']
const SKIP_DIRS = new Set(['node_modules', '.next', 'dist', 'coverage', '__pycache__'])

/** 「操作」列表头文案（列定义式与原生 `<th>` 式共用这一个口径） */
const ACTION_HEADER = '操作'

/** 折叠触发器的机器读数（`更多操作` 是旧原语 `RowActions` 的触发器 aria-label） */
export const MORE_LABEL = '更多操作'

/** 全局禁用（不止动作面）：折叠原语的名字 */
export const RETIRED_PRIMITIVE = 'RowActions'

/** 台账（**唯一真值**；`flat_surfaces` = 已收口面的正向锚） */
const LEDGER_PATH = join(
  dirname(fileURLToPath(import.meta.url)),
  '../tests/unit/row-action-flat-ledger.json',
)

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

function attrNameOf(node) {
  return ts.isJsxAttribute(node) ? node.name.getText() : ''
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

/** 一个 `<td>` 里有没有**可点动作**（宽松回退用：识别动作格，不看表头列序） */
function hasActionish(node) {
  let found = false
  walkAll(node, (n) => {
    if (found) return
    if (ts.isJsxElement(n) || ts.isJsxSelfClosingElement(n)) {
      const tag = tagNameOf(n)
      if (['Button', 'button', 'RowActionLink', 'a'].includes(tag)) found = true
      else if (tag === 'MoreHorizontal') found = true
    }
    if (ts.isJsxAttribute(n) && n.name.getText() === 'aria-haspopup') found = true
  })
  return found
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
 * 一个动作面里的**折叠原语**（AST 口径：注释不算）。
 *
 * @returns {string[]} 命中的锚点名字（去重、稳定顺序）
 */
export function foldedAnchorsInNode(node) {
  const found = new Set()
  if (!node) return []
  walkAll(node, (n) => {
    if (ts.isJsxElement(n) || ts.isJsxSelfClosingElement(n)) {
      const tag = tagNameOf(n)
      // 旧原语：<RowActions …>
      if (tag === RETIRED_PRIMITIVE) found.add(RETIRED_PRIMITIVE)
      // 纯图标「⋯」触发器（不依赖具体原语）
      if (tag === 'MoreHorizontal') found.add('MoreHorizontal')
      if (ts.isJsxElement(n)) {
        // 触发器文案（`<Button aria-label="更多操作">`）
        for (const a of n.openingElement.attributes.properties) {
          if (!ts.isJsxAttribute(a)) continue
          if (attrNameOf(a) === 'aria-haspopup') found.add('aria-haspopup')
          if (
            attrNameOf(a) === 'aria-label' &&
            ts.isStringLiteral(a.initializer) &&
            a.initializer.text === MORE_LABEL
          ) {
            found.add(MORE_LABEL)
          }
        }
        // 按钮 / 菜单文字里的「更多操作」
        for (const child of n.children) {
          if (ts.isJsxText(child) && child.text.includes(MORE_LABEL)) found.add(MORE_LABEL)
        }
      }
    }
    if (ts.isJsxSelfClosingElement(n)) {
      for (const a of n.attributes.properties) {
        if (!ts.isJsxAttribute(a)) continue
        if (attrNameOf(a) === 'aria-haspopup') found.add('aria-haspopup')
        if (
          attrNameOf(a) === 'aria-label' &&
          ts.isStringLiteral(a.initializer) &&
          a.initializer.text === MORE_LABEL
        ) {
          found.add(MORE_LABEL)
        }
      }
    }
  })
  return [...found].sort()
}

/** 源码 → 该文件里的「操作」动作面节点（供判据 / 判别力自证共用，**纯函数**） */
export function actionSurfacesFromSource(source, { file = '<probe>.tsx' } = {}) {
  const sf = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const fns = collectRenderFunctions(sf)
  const surfaces = []

  // ① 列定义式：`title: '操作'` 所在对象的 `render`
  walkAll(sf, (node) => {
    if (!ts.isPropertyAssignment(node) || nameOf(node.name) !== 'title') return
    if (!ts.isStringLiteral(node.initializer) || node.initializer.text !== ACTION_HEADER) return
    const obj = node.parent
    if (!obj || !ts.isObjectLiteralExpression(obj)) return
    const render = obj.properties.find(
      (p) => ts.isPropertyAssignment(p) && nameOf(p.name) === 'render',
    )
    // 委托式动作面：`render: renderActions` ⇒ 跟随进本文件的渲染函数（否则读成空面）
    let nodeForSurface = render ? render.initializer : null
    if (nodeForSurface && ts.isIdentifier(nodeForSurface) && fns.has(nodeForSurface.text)) {
      nodeForSurface = fns.get(nodeForSurface.text)
    }
    surfaces.push({ kind: 'column', node: nodeForSurface })
  })

  // ② 原生表头式：表头**以**「操作」结尾（`分组 · 单位 · 操作` 算，`操作人` 不算）
  //    ⇒ 右缘冻结格（`className` 含 `right-0`）是它的表体；没有该约定时退化为「同文件带可点元素的格」。
  let hasRawHeader = false
  walkAll(sf, (node) => {
    if (
      ts.isJsxElement(node) &&
      tagNameOf(node) === 'th' &&
      jsxTextContent(node).trim().endsWith(ACTION_HEADER)
    ) {
      hasRawHeader = true
    }
  })
  if (hasRawHeader) {
    const frozen = []
    const actionish = []
    walkAll(sf, (node) => {
      if (!ts.isJsxElement(node) || tagNameOf(node) !== 'td') return
      if (attrText(node, 'className').includes('right-0')) frozen.push(node)
      else if (hasActionish(node)) actionish.push(node)
    })
    // 🟡 宽松回退（照实登记边界）：不是每张表都遵守右缘冻结约定；这些页的动作格仍要能判折叠，
    //    否则「没有 right-0 ⇒ 计 0 面」会把折叠菜单放过去（旧判据 24 面里 8 面就是这么假绿的）。
    const cells = frozen.length > 0 ? frozen : actionish
    if (cells.length > 0) surfaces.push({ kind: 'cell', node: cells[0], nodes: cells })
  }

  return surfaces
}

/** 源码 → 该文件动作面的**折叠违规**（判别力自证 + 守卫共用） */
export function foldedViolationsFromSource(source, { file = '<probe>.tsx' } = {}) {
  return actionSurfacesFromSource(source, { file })
    .map((surface) => ({
      kind: surface.kind,
      anchors: (surface.nodes || [surface.node]).flatMap((n) => foldedAnchorsInNode(n)),
    }))
    .filter((v) => v.anchors.length > 0)
}

/**
 * 源码 → 文件级**退役原语**用法（全局面：`RowActions` 组件 / 「更多操作」文案）。
 *
 * 与 `foldedViolationsFromSource` 的分工：这里判「有没有再用退役原语」，不看动作面归属；
 * 动作面内的 `aria-haspopup` / `MoreHorizontal` 由前者判（其它合法下拉不误伤）。
 */
export function retiredUsagesFromSource(source) {
  const sf = ts.createSourceFile('<probe>.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const found = new Set()
  walkAll(sf, (node) => {
    // import { RowActions } from '@/components/ui'
    if (ts.isImportDeclaration(node) && node.importClause?.namedBindings) {
      const bindings = node.importClause.namedBindings
      if (ts.isNamedImports(bindings)) {
        for (const el of bindings.elements) {
          if (el.name.text === RETIRED_PRIMITIVE) found.add(RETIRED_PRIMITIVE)
        }
      }
    }
    if (ts.isJsxElement(node) || ts.isJsxSelfClosingElement(node)) {
      if (tagNameOf(node) === RETIRED_PRIMITIVE) found.add(RETIRED_PRIMITIVE)
      const attrs = ts.isJsxElement(node) ? node.openingElement.attributes : node.attributes
      for (const a of attrs.properties) {
        if (!ts.isJsxAttribute(a)) continue
        if (
          attrNameOf(a) === 'aria-label' &&
          ts.isStringLiteral(a.initializer) &&
          a.initializer.text === MORE_LABEL
        ) {
          found.add(MORE_LABEL)
        }
      }
    }
  })
  return [...found].sort()
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

function scopeFiles(root) {
  const files = []
  for (const scope of SCOPES) files.push(...walkFiles(join(root, scope)))
  return files.map((f) => relative(root, f)).sort()
}

/** 命中清单：每个文件里**每个**动作面的折叠读数（未登记即红） */
export function rowActionSites(root) {
  const files = scopeFiles(root)
  const sites = []
  for (const abs of files) {
    const source = readFileSync(join(root, abs), 'utf8')
    const surfaces = actionSurfacesFromSource(source, { file: abs })
    if (surfaces.length === 0) continue
    const folded = surfaces
      .flatMap((surface) => (surface.nodes || [surface.node]).flatMap((n) => foldedAnchorsInNode(n)))
      .filter((v, i, all) => all.indexOf(v) === i)
      .sort()
    sites.push({ file: abs, key: abs, surfaces: surfaces.length, folded })
  }
  return { files: files.length, sites }
}

/** 动作面折叠违规：`[{file, spaces:[{kind, anchors}]}]` */
export function foldedSurfaces(root) {
  return rowActionSites(root)
    .sites.filter((s) => s.folded.length > 0)
    .map((s) => ({ file: s.key, anchors: s.folded }))
}

/** 全局面：仍在用退役原语 / 「更多操作」的文件 */
export function retiredUsages(root) {
  const violations = []
  for (const abs of scopeFiles(root)) {
    const anchors = retiredUsagesFromSource(readFileSync(join(root, abs), 'utf8'))
    if (anchors.length > 0) violations.push({ file: abs, anchors })
  }
  return violations
}

/** 台账（**唯一真值 = tests/unit/row-action-flat-ledger.json**） */
export function loadLedger() {
  return JSON.parse(readFileSync(LEDGER_PATH, 'utf8'))
}

/** 用户裁定的平铺面（`flat_surfaces`）：已收口面的正向锚 */
export function flatSurfaceEntries() {
  return loadLedger().flat_surfaces || []
}

export function flatSurfaceFiles() {
  return new Set(flatSurfaceEntries().map((e) => e.file))
}

/**
 * 正向锚：登记了 `flat_surfaces` 就**必须仍是平铺**。
 *
 * - 缺文件 / 缺 `<RowActionLink` 锚点 ⇒ 红（用户要的平铺形态被删掉了 / 整列被搬走了）；
 * - 文件里又出现折叠原语（`RowActions` / `更多操作`）⇒ 红（又收回「⋯」菜单了）。
 *
 * 注释不算：折叠原语用 AST 判（`retiredUsagesFromSource`），文本只用于**平铺**锚点。
 */
export function flatAnchorViolationsFrom(root, entries) {
  const violations = []
  for (const entry of entries) {
    let src = ''
    try {
      src = readFileSync(join(root, entry.file), 'utf8')
    } catch {
      violations.push(`${entry.name}（文件不可读：${entry.file}）`)
      continue
    }
    for (const anchor of entry.requires || []) {
      if (!src.includes(anchor)) violations.push(`${entry.name}（${entry.file} 里找不到平铺锚点 ${anchor}）`)
    }
    const retired = retiredUsagesFromSource(src)
    if (retired.length > 0) {
      violations.push(`${entry.name}（${entry.file} 里又出现折叠原语 ${retired.join(' / ')}）`)
    }
  }
  return violations
}

export function flatAnchorViolations(root) {
  return flatAnchorViolationsFrom(root, flatSurfaceEntries())
}

const isMain = process.argv[1] && import.meta.url.endsWith(process.argv[1].split('/').pop())
if (isMain) {
  const root = process.env.MIGAO_SCAN_ROOT || join(dirname(fileURLToPath(import.meta.url)), '..')
  const { files, sites } = rowActionSites(root)
  const folded = foldedSurfaces(root)
  const retired = retiredUsages(root)
  const flat = flatSurfaceFiles()
  console.log(
    `扫描 ${files} 个 tsx 文件 · 命中「操作列动作面」${sites.length} 处 ` +
      `（已登记平铺 ${flat.size} / 折叠面 ${folded.length} / 退役原语 ${retired.length}）\n`,
  )
  for (const s of sites) {
    const mark = s.folded.length ? `❌ 折叠（${s.folded.join(' / ')}）` : '✅ 平铺'
    console.log(`  ${mark}  ${s.key}（面 ${s.surfaces}）`)
  }
  const anchorViolations = flatAnchorViolations(root)
  if (retired.length) {
    console.log(`\n❌ 仍在用退役原语：${retired.map((v) => `${v.file}（${v.anchors.join(' / ')}）`).join('、')}`)
  }
  if (folded.length) {
    console.log(`\n❌ 「操作」列仍在折叠：${folded.map((v) => `${v.file}（${v.anchors.join(' / ')}）`).join('、')}`)
  }
  if (anchorViolations.length) {
    console.log(`\n❌ 平铺面已变形：${anchorViolations.join('、')}`)
  }
  process.exit(retired.length || folded.length || anchorViolations.length ? 1 : 0)
}
