// case_ids: PG-065, BM-006
//
// 工人端 H5 页头（`.wh5-header`）控件不得被 flex 压缩到折行 —— 类级判据（issue #6763）。
//
// 缺陷（线上 2026-10-12 实测，360/390/430 三视口全现）：报工页登录后页头
// `当前工人：<名字>（工号 X）` 一长，两个按钮被压到 50~55px，小于内容宽度
// （2 字 × 15px + 左右 padding 14px×2 = 58px）⇒ 浏览器在字符间断行，按钮里出现「切 / 换」「登 / 出」两行。
//
// 🔴 **病根不是「按钮少写了一条样式」，而是「没有谁显式声明这块空间怎么分」**：
// `.wh5-header` 是 flex 行，`.wh5-ghost` 走浏览器默认的 `flex: 0 1 auto`（**可收缩**）
// ⇒ 换一个更长的名字、或再加一个按钮，同一个缺陷就能再来一次。
// 所以本判据钉的是**类**（页头的每个直接子元素都要显式声明伸缩性），不是那一行取巧的值。
//
// 三条判据（每条都能红）：
//   ① 页头**每个直接子元素**（tag + class 从 `src/render.mjs` 的页头模板**现取**，不写死清单）
//      在 `src/styles.css` 里必须显式声明 `flex` / `flex-shrink` / `flex-grow` / `flex-basis` 之一；
//   ② 其中的 `<button>` 还必须声明 `white-space: nowrap`（空间不够时不许把文字拆两行）；
//   ③ 页头按钮必须**不可收缩**（`flex-shrink: 0`，或 `flex` 简写的收缩位为 0 / `flex: none`）。
// 判别力自证（**内存变异，不落仓库**）：抽掉 flex / 抽掉 nowrap / 新增未声明的页头按钮 ⇒ 各自判红；
//   只有注释里写着这些声明 ⇒ 仍判红（先剥注释）；改**非页头**类 ⇒ 判定不变（对照读数）。
//
// 零依赖：`node --test` + 手写 CSS 规则扫描（不引 jsdom / postcss —— 最少代码阶梯）。
// 🔴 **几何读数不在本文件**：Node 里没有布局引擎 ⇒「文字到底几行」由
//    `scripts/probe-worker-h5-touch.mjs`（本机 Chrome + CDP）在 360/390/430 三视口读**行盒数**。
//    同处记了一条实测教训：高度与 `scrollWidth` **都不是**判别量。

import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8')

const RENDER_SRC = read('../src/render.mjs')
const CSS_SRC = read('../src/styles.css')

// ══════════════════════════════════════════════════════════════════════════════
// 扫描器（本判据的全部判别力都在这里 —— 故逐条自证，见「判别力自证」用例）
// ══════════════════════════════════════════════════════════════════════════════

/** 去注释。顺序是命门：注释里的 `{` / `}` / `:` 会带偏后面的块解析（本仓注释里这两种字符都有）。 */
export function stripCssComments(css) {
  return css.replace(/\/\*[\s\S]*?\*\//g, '')
}

/** CSS 声明块 → `{ 属性: 值 }`（小写属性名；值里连续空白归一）。 */
function parseDecls(body) {
  const decls = {}
  for (const chunk of body.split(';')) {
    const at = chunk.indexOf(':')
    if (at < 0) continue
    const key = chunk.slice(0, at).trim().toLowerCase()
    const value = chunk.slice(at + 1).trim().replace(/\s+/g, ' ')
    if (key) decls[key] = value
  }
  return decls
}

/**
 * 解析出所有**普通规则** `[{ selector, decls }]`。
 * `@media` 等容器**递归展开**（本判据只问「有没有声明」，不问层叠优先级 ⇒ 展开就够）。
 */
export function parseRules(css) {
  const src = stripCssComments(css)
  const out = []
  let buf = ''
  let i = 0
  while (i < src.length) {
    const ch = src[i]
    if (ch === '{') {
      let depth = 1
      let j = i + 1
      while (j < src.length && depth > 0) {
        if (src[j] === '{') depth += 1
        else if (src[j] === '}') depth -= 1
        j += 1
      }
      const body = src.slice(i + 1, j - 1)
      const selector = buf.trim().replace(/\s+/g, ' ')
      if (selector.startsWith('@')) out.push(...parseRules(body))
      else if (selector) out.push({ selector, decls: parseDecls(body) })
      buf = ''
      i = j
      continue
    }
    if (ch === '}') {
      buf = ''
      i += 1
      continue
    }
    buf += ch
    i += 1
  }
  return out
}

/** 某个**类名**下所有规则的声明合并（源码顺序，后者覆盖前者）。带伪类的规则（`.x:active`）不算。 */
export function declsOf(rules, className) {
  const target = `.${className}`
  const merged = {}
  for (const rule of rules) {
    if (rule.selector.split(',').some((s) => s.trim() === target)) Object.assign(merged, rule.decls)
  }
  return merged
}

/** 从页头模板**现取**直接子元素（tag + 首个 class）。取不到 ⇒ 抛（空跑 = 假绿，不许静默）。 */
export function headerChildren(renderSrc) {
  const m = renderSrc.match(/<header class="wh5-header">([\s\S]*?)<\/header>/)
  assert.ok(m, 'render.mjs 里找不到 `<header class="wh5-header">…</header>` —— 判据会空跑，视为红')
  const children = [...m[1].matchAll(/<([a-zA-Z][\w-]*)\b[^>]*\bclass="([^"]+)"/g)].map(([, tag, cls]) => ({
    tag: tag.toLowerCase(),
    cls: cls.trim().split(/\s+/)[0],
  }))
  assert.ok(children.length >= 2, `页头直接子元素只解析出 ${children.length} 个 —— 解析器坏了（空跑 = 假绿）`)
  return children
}

const FLEX_KEYS = ['flex', 'flex-shrink', 'flex-grow', 'flex-basis']
const flexExplicit = (d) => FLEX_KEYS.some((k) => k in d)

/** 不可收缩：`flex-shrink: 0`，或 `flex` 简写里收缩位为 0（`none` ≡ `0 0 auto`）。 */
function shrinkZero(d) {
  if (d['flex-shrink'] !== undefined) return Number.parseFloat(d['flex-shrink']) === 0
  if (d.flex !== undefined) {
    const parts = d.flex.trim().split(/\s+/)
    if (parts.length === 1 && (parts[0] === 'none' || parts[0] === '0')) return true
    if (parts.length >= 2) return Number.parseFloat(parts[1]) === 0
  }
  return false
}

/** 判据本体（纯函数：吃源码文本 ⇒ 可对**内存变异**跑，故判别力能自证）。 */
export function auditHeaderFlex(renderSrc, cssSrc) {
  const rules = parseRules(cssSrc)
  const errors = new Set()
  for (const child of headerChildren(renderSrc)) {
    const d = declsOf(rules, child.cls)
    if (!flexExplicit(d)) {
      errors.add(
        `页头子元素 <${child.tag} class="${child.cls}"> 没有显式声明伸缩性（flex / flex-shrink / flex-grow / flex-basis）` +
          ' —— 靠浏览器默认 `flex: 0 1 auto` 正是本次缺陷的形态',
      )
      continue
    }
    if (child.tag === 'button') {
      if (d['white-space'] !== 'nowrap') {
        errors.add(`页头按钮 .${child.cls} 没有 ` + '`white-space: nowrap`' + ' ⇒ 空间不够时文字会折成两行')
      }
      if (!shrinkZero(d)) {
        errors.add(`页头按钮 .${child.cls} 可被压缩（flex-shrink ≠ 0）⇒ 长名字会把按钮压到小于内容宽度而折行`)
      }
    }
  }
  return [...errors]
}

// ══════════════════════════════════════════════════════════════════════════════
// 判据
// ══════════════════════════════════════════════════════════════════════════════

test('页头每个直接子元素都显式声明了伸缩性，按钮不折行且不可压缩（issue #6763）', () => {
  assert.deepEqual(auditHeaderFlex(RENDER_SRC, CSS_SRC), [])
})

test('判别力自证：抽掉 flex / 抽掉 nowrap / 新增未声明的页头按钮 ⇒ 各自判红', () => {
  // ① 抽掉 `flex: 0 0 auto`（先自证注入生效 —— 注入没生效的「红」是假红）
  const noFlex = CSS_SRC.replace('  flex: 0 0 auto;\n', '')
  assert.notEqual(noFlex, CSS_SRC, '注入未生效：CSS 里找不到 `  flex: 0 0 auto;`')
  assert.ok(
    auditHeaderFlex(RENDER_SRC, noFlex).some((e) => e.includes('没有显式声明伸缩性')),
    '抽掉 flex 后判据没红 —— 判据是空断言',
  )

  // ② 抽掉 `white-space: nowrap`
  const noNowrap = CSS_SRC.replace('  white-space: nowrap;\n', '')
  assert.notEqual(noNowrap, CSS_SRC, '注入未生效：CSS 里找不到 `  white-space: nowrap;`')
  assert.ok(
    auditHeaderFlex(RENDER_SRC, noNowrap).some((e) => e.includes('white-space: nowrap')),
    '抽掉 nowrap 后判据没红 —— 判据是空断言',
  )

  // ③ 页头新增一个**没有声明伸缩性**的按钮（这就是「同类再来一次」的形态）
  const extraButton = RENDER_SRC.replace(
    '<button id="wh5-switch"',
    '<button id="wh5-probe-new" class="wh5-newbtn" type="button">新</button><button id="wh5-switch"',
  )
  assert.notEqual(extraButton, RENDER_SRC, '注入未生效：render.mjs 里找不到 `<button id="wh5-switch"`')
  assert.ok(
    auditHeaderFlex(extraButton, CSS_SRC).some((e) => e.includes('wh5-newbtn') && e.includes('没有显式声明伸缩性')),
    '新增未声明的页头按钮后判据没红 —— 类级判据没覆盖「新按钮」这条路径',
  )
})

test('对照读数：注释里的声明不算声明；改非页头类不改变判定', () => {
  // ① 把真声明删掉、只在注释里写上 ⇒ 仍须判红（证明先剥注释这一步真的在起作用）
  const onlyComment =
    CSS_SRC.replace('  flex: 0 0 auto;\n', '').replace(
      '  white-space: nowrap;\n',
      '  /* flex: 0 0 auto; white-space: nowrap; */\n',
    )
  assert.ok(
    auditHeaderFlex(RENDER_SRC, onlyComment).length > 0,
    '只在注释里写声明竟被当成声明 —— 判据会被「写句注释」骗过',
  )

  // ② 负控：改**非页头**的类（这里给 `.wh5-entry` 加一条 flex）⇒ 判定逐字不变
  const otherClass = CSS_SRC.replace('.wh5-entry {\n  flex: 1 1 0;', '.wh5-entry {\n  flex: 1 1 0;\n  flex-shrink: 1;')
  assert.notEqual(otherClass, CSS_SRC, '注入未生效：找不到 `.wh5-entry` 的 flex 行')
  assert.deepEqual(auditHeaderFlex(RENDER_SRC, otherClass), [], '判据射程越界：改了非页头类它却变红/变绿')
})
