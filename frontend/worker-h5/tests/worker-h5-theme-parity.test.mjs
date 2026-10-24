// case_ids: PG-018, BM-006, DF-017
//
// 工人端 H5 的调色板必须与**商家端（admin-web）**同一份 —— 类级判据（issue #7237）。
//
// ## 用户逐字（2026-10-18）
// 「我发现整个工人页面都是这样的问题，我觉得得和管理员登录的样式风格保持一致」
//
// ## 病灶
// 工人端 `src/styles.css` 自持一套 Tailwind 默认调色板（slate `#f1f5f9` / `#e2e8f0` / `#64748b` +
// teal `#0f766e` / `#115e59` / `#ccfbf1`），而商家端（`admin-web`）用的是「织物质感」暖中性调色板
// （primary 靛蓝 / neutral 米白 / accent 陶土 + 暖阴影 `rgba(36,31,24,…)`）—— 同一个产品在
// 工人手上长着另一张脸。2026-10-18 的 #7232 只补了「缺规则」，没有动调色板 ⇒ 补齐后仍然不像。
//
// ## 判据（为什么钉「逐值对账」而不是钉某几个类）
// 「配色一致」不可断言，但**调色板一致**可以：工人端的每个语义 token 都必须等于商家端
// `frontend/admin-web/tailwind.config.ts` 里对应那**一阶**的值。这样商家端改一阶而工人端没跟上 ⇒ 红；
// 工人端自己发明一个近似色（`#3a4e76` 之类）⇒ 也红。
//
// 三条判据（每条都能红）：
//   ① 语义 token 逐值对账（真值 = admin-web 的 tailwind 调色板 + 登录页/globals 的页面底）；
//   ② 旧调色板字面量**一个都不许留**（slate / teal 的那批 hex）—— 否则「只迁了一半」这种形态
//      在屏上仍是两套配色，而没有任何别的东西会红（本仓反复复发的「漂移的那一份不变红」）；
//   ③ 判别力自证（内存变异）：把 token 改成邻色 / 把旧 hex 塞回一段规则 ⇒ 各自判红；注释里的 hex 不算。
//
// 零依赖：`node --test` + 正则扫描（不引 postcss —— 最少代码阶梯）。

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8')

const CSS_SRC = read('../src/styles.css')
const TAILWIND_SRC = read('../../admin-web/tailwind.config.ts')

const stripCssComments = (css) => css.replace(/\/\*[\s\S]*?\*\//g, '')

/**
 * admin-web `tailwind.config.ts` 里一组色阶 → `{ 阶: '#hex' }`。
 *
 * 只解析 `primary: { 50: '#…', … }` 这一形态（本仓的写法）；解析不到就**抛错**（不静默空跑 ——
 * 「真值取不到」与「真值一致」是两件事）。
 */
export function scaleOf(tailwindSrc, name) {
  const body = new RegExp(`\\b${name}:\\s*\\{([\\s\\S]*?)\\}`).exec(tailwindSrc)
  assert.ok(body, `admin-web 的 tailwind.config.ts 里取不到色阶 \`${name}\` —— 本判据的真值源变了，先修取值再谈通过`)
  const scale = {}
  for (const m of body[1].matchAll(/(\d+):\s*'(#[0-9a-fA-F]{6})'/g)) scale[m[1]] = m[2].toLowerCase()
  assert.ok(Object.keys(scale).length >= 5, `色阶 \`${name}\` 只解析出 ${Object.keys(scale).length} 阶，取值形态可能变了`)
  return scale
}

/** worker `:root` 里的自定义属性 → `{ '--wh5-x': '#hex' | 其它原值 }`。 */
export function rootTokens(css) {
  const root = /:root\s*\{([\s\S]*?)\}/.exec(stripCssComments(css))
  assert.ok(root, '`src/styles.css` 里找不到 `:root` 调色板')
  const tokens = {}
  for (const part of root[1].split(';')) {
    const at = part.indexOf(':')
    if (at < 0) continue
    const key = part.slice(0, at).trim()
    if (!key.startsWith('--')) continue
    tokens[key] = part.slice(at + 1).trim().replace(/\s+/g, ' ')
  }
  return tokens
}

const TOKENS = rootTokens(CSS_SRC)
const PRIMARY = scaleOf(TAILWIND_SRC, 'primary')
const NEUTRAL = scaleOf(TAILWIND_SRC, 'neutral')
const ACCENT = scaleOf(TAILWIND_SRC, 'accent')

/**
 * 语义 token → 商家端色阶的哪一阶（**唯一一份映射表**）。
 *
 * ⚠️ 这张表就是「两个端是同一个产品」的契约：新增语义 token 时先想清楚它对应 admin 的哪一阶，
 * 不对应就别加 token（直接用字面量之前先问一句「admin 那边这是什么」）。
 */
const PARITY = {
  '--wh5-bg': NEUTRAL[50],
  '--wh5-surface': NEUTRAL[100],
  '--wh5-surface-soft': NEUTRAL[50],
  '--wh5-ink': NEUTRAL[900],
  '--wh5-ink-soft': NEUTRAL[800],
  '--wh5-muted': NEUTRAL[600],
  '--wh5-line': NEUTRAL[200],
  '--wh5-line-strong': NEUTRAL[300],
  '--wh5-disabled': NEUTRAL[400],
  '--wh5-brand': PRIMARY[600],
  '--wh5-brand-strong': PRIMARY[700],
  '--wh5-brand-deep': PRIMARY[800],
  '--wh5-brand-soft': PRIMARY[50],
  '--wh5-warn': ACCENT[600],
  '--wh5-warn-soft': ACCENT[50],
  '--wh5-warn-line': ACCENT[200],
}

/** 旧调色板（本仓迁移前的那一套）—— 一个都不许留在 `src/styles.css` 的任何规则里。 */
const LEGACY = [
  '#0f766e', '#115e59', '#134e4a', '#14b8a6', '#5eead4', // teal
  '#f1f5f9', '#e2e8f0', '#ccfbf1', '#64748b', '#1e293b', // slate / teal-100
  '#334155', '#475569', '#94a3b8', '#f8fafc', '#0f172a', '#cbd5e1', // slate 余下
]

// ══════════════════════════════════════════════════════════════════════════════
// ① 语义 token 逐值对账（真值 = admin-web 的调色板）
// ══════════════════════════════════════════════════════════════════════════════

test('① 工人端每个语义 token 都等于商家端调色板对应那一阶', () => {
  const wrong = []
  for (const [token, expected] of Object.entries(PARITY)) {
    assert.ok(expected, `映射表里的 ${token} 没有对应的 admin 色阶（判据自身写错了）`)
    const actual = TOKENS[token]
    if (actual === undefined) wrong.push(`${token} 缺失（应为 ${expected}）`)
    else if (actual.toLowerCase() !== expected.toLowerCase()) {
      wrong.push(`${token} = ${actual}，商家端是 ${expected}`)
    }
  }
  assert.deepEqual(wrong, [], `工人端与商家端配色不一致（用户 2026-10-18「整个工人页面…得和管理员登录的样式风格保持一致」）：\n  ${wrong.join('\n  ')}`)
})

test('② 旧调色板（slate / teal）字面量一个都不许留', () => {
  const css = stripCssComments(CSS_SRC).toLowerCase()
  const leftovers = LEGACY.filter((hex) => css.includes(hex))
  assert.deepEqual(leftovers, [], `这些旧调色板 hex 还留在 styles.css 里 ⇒ 屏上仍是两套配色（只迁了一半）：\n  ${leftovers.join(' ')}`)
})

test('③ 判别力自证：邻色 / 回填旧 hex / 注释里的 hex', () => {
  // 邻色：把 brand 改成相邻的一阶 ⇒ ① 必红（不是「有值就算过」）
  const mutated = CSS_SRC.replace(TOKENS['--wh5-brand'], PRIMARY[500])
  assert.ok(mutated !== CSS_SRC, '变异注入没生效（真值都取不到 ⇒ 后面两条断言是空跑）')
  const mutatedTokens = rootTokens(mutated)
  assert.notEqual(mutatedTokens['--wh5-brand'], PRIMARY[600], '改了 token 却仍判等 ⇒ 判据是空断言')
  // 回填旧 hex 到一条规则里 ⇒ ② 必红
  assert.ok(stripCssComments('.x { color: #64748b }').includes('#64748b'), '旧 hex 检测必须能命中规则体')
  // 注释里的 hex 不算（否则说明性注释会把判据骗红 —— 与 `worker-h5-plain-text-guard` 同口径：先剥注释）
  assert.equal(stripCssComments('/* #64748b */ .x { color: #312c26 }').includes('#64748b'), false)
})
