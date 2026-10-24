// case_ids: PG-018, BM-006, DF-017
//
// 工人端 H5「上屏的类必须有样式」—— 实例判据（「我的计件」三态）+ **类级判据**（issue #7232）。
//
// ## 病灶（线上实测，2026-10-18 用户逐字）
// 「我的计件页面没有样式吗？另外右上角的返回报工按钮样式有问题，整体页面都是白色的，和小程序的风格不一样」
//
// 读码归因（零成本复算）：
//   ① `src/piecework.mjs` 下发 `wh5-piecework-summary / -lines / -line / -line-name / -line-qty /
//      -line-amount / -unpriced / -unpriced-title / -unpriced-detail / -unpriced-list / -empty / -nav`
//      —— **12 个类在 `src/styles.css` 里一条规则都没有** ⇒ 合计 / 件数 / 逐笔 / 未定价 / 月份切换
//      全部落回浏览器默认样式（`<dl>` 缩进 + `<li>` 圆点 + 默认外边距）＝ 用户看到的「整页白、没样式」。
//   ② 右上角「返回报工」是**唯一一处**用 `class="wh5-ghost"` 的 `<a>`（其余 9 处都是 `<button>`）；
//      `.wh5-ghost` 没有 `display` ⇒ `<button>` 的文字天然居中，`<a>` 的文字顶格贴在 44px 白框上沿
//      ⇒ 用户看到的「按钮样式有问题」。对照：同页 `.wh5-entry` 是 `display:flex + align-items:center`（对的写法）。
//
// ## 为什么钉在「类」上而不是钉这一页
// 漏一个类的形态**不会让任何既有测试变红**（不崩、不报错，只是难看），但用户看到的是一整个**没样式的页面**；
// 而「新页面 / 新块忘了配样式」会随每次加页复发。⇒ 判据对象 = `src/**/*.mjs` 里**静态出现**的每一个
// `wh5-*` 类，逐个要求在 `styles.css` 有选择器（豁免表**显式**且只许缩短，见 `STYLE_FREE_ALLOW`）。
//
// ## 判别力自证（内存变异，不落仓库）
//   ① 删掉一条 `.wh5-piecework-*` 规则 ⇒ 用例①红；② 在源串里新增一个未定义的 `wh5-*` 类 ⇒ 用例①红；
//   ③ 只在**注释**里写选择器 ⇒ 仍红（扫描前先剥注释，用例⑤钉住这一点）。
//
// 零依赖：`node --test` + 正则扫描（不引 jsdom / postcss —— 最少代码阶梯）。

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

import { renderPiecework } from '../src/piecework.mjs'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const SRC_DIR = path.join(HERE, '..', 'src')
const read = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8')

/** 去注释（顺序是命门：注释里的 `{` `}` `:` `.wh5-x` 会把扫描带偏）。 */
const stripCssComments = (css) => css.replace(/\/\*[\s\S]*?\*\//g, '')

/** `styles.css` 里**真定义**的类名集合（剥注释后取 `.xxx` 记号）。 */
export function definedClasses(css) {
  const found = new Set()
  for (const m of stripCssComments(css).matchAll(/\.([a-zA-Z][\w-]*)/g)) found.add(m[1])
  return found
}

/**
 * 一段源串里**静态出现**的 `wh5-*` 类名。
 *
 * 只认静态部分：`class="wh5-op-choice${on ? ' is-on' : ''}"` ⇒ `wh5-op-choice`
 * （`${…}` 里的动态值不参与判断；`is-on` 这类状态类不是 `wh5-` 前缀，天然不入集）。
 */
export function emittedClasses(src) {
  const found = new Set()
  for (const m of src.matchAll(/class="([^"]*)"/g)) {
    for (const token of m[1].replace(/\$\{[^}]*\}/g, ' ').split(/\s+/)) {
      if (/^wh5-[a-z0-9-]+$/.test(token)) found.add(token)
    }
  }
  return found
}

/** `src/` 下全部 `.mjs`（递归；本仓没有别的层级，但别写死清单）。 */
function sourceFiles(dir = SRC_DIR) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) return sourceFiles(full)
    return entry.name.endsWith('.mjs') ? [full] : []
  })
}

/** 全仓 `src/` 下静态出现的 `wh5-*` 类（文件名 → 类集）。 */
export function classesByFile() {
  const byFile = new Map()
  for (const file of sourceFiles()) {
    const classes = emittedClasses(readFileSync(file, 'utf8'))
    if (classes.size > 0) byFile.set(path.relative(SRC_DIR, file), classes)
  }
  return byFile
}

/**
 * **显式豁免**：故意不配样式的类（每条都必须带理由，且**只许缩短**）。
 *
 * ⚠️ 豁免 ≠ 「允许没样式」：它只承认真实存在的**非视觉**类（纯 JS 钩子 / 语义标记）。
 * 目前为空 —— 一个都不需要（本页所有类都是视觉面）。新增条目要在 PR body 里写明理由。
 */
const STYLE_FREE_ALLOW = new Set([])

/** `.wh5-x` 的声明块（无 ⇒ null）。带边界，避免 `wh5-line` 命中 `wh5-lines`。 */
export function declarationsOf(css, className) {
  const stripped = stripCssComments(css)
  const re = new RegExp(`\\.${className.replace(/-/g, '\\-')}(?![\\w-])\\s*\\{([^}]*)\\}`, 'g')
  const chunks = [...stripped.matchAll(re)].map((m) => m[1])
  if (chunks.length === 0) return null
  const decls = {}
  for (const chunk of chunks) {
    for (const part of chunk.split(';')) {
      const at = part.indexOf(':')
      if (at < 0) continue
      decls[part.slice(0, at).trim().toLowerCase()] = part.slice(at + 1).trim().replace(/\s+/g, ' ')
    }
  }
  return decls
}

const CSS = read('../src/styles.css')

// ══════════════════════════════════════════════════════════════════════════════
// ① 类级：src 里出现的每个 wh5-* 类都必须有样式（漏样式即红）
// ══════════════════════════════════════════════════════════════════════════════

test('① 类级：`src/**/*.mjs` 静态出现的每个 wh5-* 类，`styles.css` 里都有选择器', () => {
  const defined = definedClasses(CSS)
  const missing = []
  for (const [file, classes] of classesByFile()) {
    for (const cls of classes) {
      if (STYLE_FREE_ALLOW.has(cls)) continue
      if (!defined.has(cls)) missing.push(`${cls}（来自 src/${file}）`)
    }
  }
  assert.deepEqual(
    missing.sort(),
    [],
    `这些类上屏了但没有样式 ⇒ 用户看到「整页没样式」。\n漏的类（含来源文件）：\n  ${missing.sort().join('\n  ')}`,
  )
})

// ══════════════════════════════════════════════════════════════════════════════
// ② 实例：「我的计件」三态（常规 / 未定价 / 空月）下发的类，一个都不许裸奔
// ══════════════════════════════════════════════════════════════════════════════

const PIECEWORK_VIEW = {
  worker_name: '张三',
  period: '2026-10',
  amount_total: 7.2,
  qty_total: 30,
  lines: [
    { operation: '精裁-布', logical_name: '精裁', position: '布帘', qty: 10, amount: 1.2 },
    { operation: '质检', logical_name: '质检', position: null, qty: 10, amount: 2.4 },
  ],
  unpriced: { qty: 5, operations: [{ operation: '车被-布', logical_name: '车被', qty: 5 }] },
  can_prev: true,
  prev_period: '2026-09',
  can_next: false,
  next_period: null,
}

test('② 实例：「我的计件」常规 / 未定价 / 空月三态的每个类都有样式', () => {
  const defined = definedClasses(CSS)
  const states = {
    常规: renderPiecework(PIECEWORK_VIEW),
    空月: renderPiecework({ ...PIECEWORK_VIEW, amount_total: 0, qty_total: 0, lines: [], unpriced: { qty: 0, operations: [] } }),
    无上月: renderPiecework({ ...PIECEWORK_VIEW, can_prev: false, prev_period: null, can_next: true, next_period: '2026-11' }),
  }
  const missing = []
  for (const [name, html] of Object.entries(states)) {
    for (const cls of emittedClasses(html)) {
      if (!defined.has(cls)) missing.push(`${cls}（${name}态）`)
    }
  }
  assert.deepEqual(missing.sort(), [], `「我的计件」三态里裸奔的类：\n  ${missing.sort().join('\n  ')}`)
  // 空态与未定价必须真被渲染到（否则本用例会在「什么都没渲染」时空转通过）
  assert.match(states.空月, /wh5-piecework-empty/, '空月态必须渲染空态块（不然上面的断言空转）')
  assert.match(states.常规, /wh5-piecework-unpriced/, '未定价态必须渲染未定价块（不然上面的断言空转）')
})

// ══════════════════════════════════════════════════════════════════════════════
// ③ 页头「返回报工」：`.wh5-ghost` 必须对 <a> 与 <button> 都给垂直居中
// ══════════════════════════════════════════════════════════════════════════════

test('③ `.wh5-ghost` 对 <a> / <button> 同构：display 为 flex 系 + align-items:center', () => {
  const decls = declarationsOf(CSS, 'wh5-ghost')
  assert.ok(decls, '`.wh5-ghost` 规则不见了')
  assert.match(
    decls.display ?? '',
    /^(inline-)?flex$/,
    `\`<a class="wh5-ghost">\` 不是 flex 容器 ⇒ 文字顶格贴在上沿（用户看到的「按钮样式有问题」）。实际 display=${decls.display}`,
  )
  assert.equal(decls['align-items'], 'center', `\`.wh5-ghost\` 缺 \`align-items: center\` ⇒ <a> 的文字不居中`)
  assert.equal(decls['justify-content'], 'center', `\`.wh5-ghost\` 缺 \`justify-content: center\` ⇒ <a> 的文字不居中`)
})

test('③-b 「返回报工」确实是 `<a class="wh5-ghost">`（本判据的对象是真的那个控件）', () => {
  const app = read('../src/piecework-app.mjs')
  assert.match(app, /<a class="wh5-ghost" id="wh5-piecework-back"[^>]*>返回报工<\/a>/,
    '页头返回控件必须是 <a class="wh5-ghost">（改了形态 ⇒ 同步改本判据，不许静默放宽）')
})

// ══════════════════════════════════════════════════════════════════════════════
// ⑤ 扫描器自证（判别力）：剥注释 / 只认静态类 / 边界不串味
// ══════════════════════════════════════════════════════════════════════════════

test('⑤ 判别力自证：注释里的选择器不算定义；动态段不入集；`-line` 不命中 `-lines`', () => {
  assert.deepEqual([...definedClasses('/* .wh5-ghost { display: flex } */')], [], '注释里的选择器不得当定义（否则判据可被注释骗绿）')
  assert.deepEqual([...emittedClasses('<div class="wh5-a${on ? \' b\' : \'\'}"></div>')], ['wh5-a'], '动态段不得入集')
  assert.equal(declarationsOf('.wh5-lines { display: flex }', 'wh5-line'), null, '`wh5-line` 不得命中 `wh5-lines` 的声明')
})
