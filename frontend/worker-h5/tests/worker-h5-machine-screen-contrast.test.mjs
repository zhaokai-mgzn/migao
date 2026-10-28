// case_ids: PG-047
//
// 一体机机台屏（`/w/machine.html`）的**深底**是设计意图，不是可选主题：
// `src/styles.css` 里机台 token 的注释写明「机台仍是深底（车间反光/粉尘）」。
//
// 病灶（issue #7983，2026-10-28 真机实测）：2026-10-18 主题对齐把全局 `--wh5-bg` 从 `#0f172a`
// 改成 `#faf7f2`，而 `.wh5-machine-body` 取的是**全局页面底** ⇒ 机台屏底色跟着变米白，
// 文字色仍是机台的浅色 `--wh5-machine-ink` ⇒ 浅底浅字（真机 CDP 实测对比度 1.14:1，
// 「裁高计算（一体机）」/「请扫水洗唛」几乎不可见）。
//
// 三条判据（每条都能红）：
//   ① `.wh5-machine` 的文字色 vs `.wh5-machine-body` 的背景色，**解析到 hex 后**算 WCAG 对比度 ≥ 4.5:1；
//   ② 类级守卫：`.wh5-machine-body` 的背景**不得**引用全局页面底（`--wh5-bg` / `--wh5-bg-end`）——
//      机台屏自持深底，不跟全局漂移（挡的是「下次又有人把机台并回工人端页面底」）；
//   ③ 判别力自证（内存变异）：把 ② 改回 `var(--wh5-bg)` ⇒ ① 与 ② 各自判红（否则两条都是空断言）。
//
// 零依赖：`node --test` + 正则（不引 postcss —— 最少代码阶梯）。

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const CSS_SRC = readFileSync(new URL('../src/styles.css', import.meta.url), 'utf8')
const stripComments = (css) => css.replace(/\/\*[\s\S]*?\*\//g, '')

/** `:root` 里的 `--token: value;`（后定义覆盖先定义，与 CSS 层叠同向）。 */
const tokensOf = (css) => {
  const map = new Map()
  for (const m of css.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/gi)) map.set(m[1], m[2].trim())
  return map
}

/** 规则体（只匹配「选择器名后紧跟 `{`」，所以 `.wh5-machine` 不会误吞 `.wh5-machine-body`）。 */
const ruleBody = (css, selector) => {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const m = css.match(new RegExp('(?:^|\\n)\\s*' + escaped + '\\s*\\{([\\s\\S]*?)\\}'))
  return m ? m[1] : null
}

const prop = (body, name) => {
  const m = (body || '').match(new RegExp('(?:^|;|\\n)\\s*' + name + '\\s*:\\s*([^;]+)'))
  return m ? m[1].trim() : null
}

/** `var(--x)` → token 值，最多跟 5 层；取不到 ⇒ null（判据不许对 null 静默放行）。 */
const resolveValue = (tokens, value, depth = 0) => {
  if (value == null) return null
  const raw = String(value).trim()
  const m = raw.match(/^var\(\s*(--[a-z0-9-]+)\s*\)$/i)
  if (!m) return raw
  if (depth >= 5) return null
  return resolveValue(tokens, tokens.get(m[1]), depth + 1)
}

const toRgb = (hex) => {
  const h = String(hex).trim().replace(/^#/, '')
  const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h
  assert.match(full, /^[0-9a-f]{6}$/i, `取不到可解析的 hex：${hex}`)
  return [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16))
}

const luminance = (hex) => {
  const [r, g, b] = toRgb(hex).map((v) => {
    const c = v / 255
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)
  })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

const contrast = (fg, bg) => {
  const a = luminance(fg)
  const b = luminance(bg)
  const [hi, lo] = a > b ? [a, b] : [b, a]
  return (hi + 0.05) / (lo + 0.05)
}

/** 机台屏的「文字色 / 底色」配对（解析到 hex）；任一侧解析不出 ⇒ 抛错，不静默。 */
const machinePair = (rawCss) => {
  const css = stripComments(rawCss)
  const tokens = tokensOf(css)
  const container = ruleBody(css, '.wh5-machine')
  const body = ruleBody(css, '.wh5-machine-body')
  assert.ok(container, '`src/styles.css` 里找不到 `.wh5-machine` 规则 —— 选择器改名了，先修判据')
  assert.ok(body, '`src/styles.css` 里找不到 `.wh5-machine-body` 规则 —— 选择器改名了，先修判据')
  const fgRaw = prop(container, 'color')
  const bgRaw = prop(body, 'background') ?? prop(body, 'background-color')
  assert.ok(fgRaw, '`.wh5-machine` 没有 color —— 判据无从判定，先修判据')
  assert.ok(bgRaw, '`.wh5-machine-body` 没有 background —— 判据无从判定，先修判据')
  const fg = resolveValue(tokens, fgRaw)
  const bg = resolveValue(tokens, bgRaw)
  assert.ok(fg && /^#[0-9a-f]{3,6}$/i.test(fg), `机台文字色解析不出 hex：${fgRaw} ⇒ ${fg}`)
  assert.ok(bg && /^#[0-9a-f]{3,6}$/i.test(bg), `机台底色解析不出 hex：${bgRaw} ⇒ ${bg}`)
  return { fg, bg, fgRaw, bgRaw, tokens }
}

const GLOBAL_PAGE_BG = /var\(\s*--wh5-bg(?:-end)?\s*\)/

test('① 机台屏「文字色 / 底色」对比度 ≥ 4.5:1（会红：修复前 1.14:1）', () => {
  const { fg, bg, fgRaw, bgRaw } = machinePair(CSS_SRC)
  const ratio = contrast(fg, bg)
  assert.ok(
    ratio >= 4.5,
    `机台屏浅底浅字：文字 ${fgRaw}（${fg}）压在底色 ${bgRaw}（${bg}）上，对比度 ${ratio.toFixed(2)}:1 < 4.5:1\n` +
      '  机台屏的深底是设计意图（styles.css 机台 token 注释「机台仍是深底（车间反光/粉尘）」）——' +
      ' 别让它的底色跟着工人端全局页面底走（issue #7983）。'
  )
})

test('② 类级守卫：机台屏底色不得引用全局页面底（--wh5-bg / --wh5-bg-end）', () => {
  const css = stripComments(CSS_SRC)
  const body = ruleBody(css, '.wh5-machine-body')
  assert.ok(body, '找不到 `.wh5-machine-body` 规则')
  const bgRaw = prop(body, 'background') ?? prop(body, 'background-color')
  assert.ok(bgRaw, '`.wh5-machine-body` 没有 background')
  assert.equal(
    GLOBAL_PAGE_BG.test(bgRaw),
    false,
    `机台屏底色取的是全局页面底（${bgRaw}）⇒ 全局换肤时机台屏会被一起改色而文字色不跟：` +
      '机台屏必须自持 `var(--wh5-machine-bg)`（issue #7983）。'
  )
  const tokens = tokensOf(css)
  assert.equal(
    resolveValue(tokens, bgRaw),
    resolveValue(tokens, 'var(--wh5-machine-bg)'),
    `机台屏底色已不是机台深底 token：${bgRaw} ⇒ ${resolveValue(tokens, bgRaw)}（真值 = --wh5-machine-bg）`
  )
})

test('③ 判别力自证：修复态必须过、改回 var(--wh5-bg) 必须红（否则 ① ② 都是空断言）', () => {
  const bodyBg = /(\.wh5-machine-body\s*\{[^}]*?background\s*:\s*)([^;]+)/

  // 自证不依赖仓库当前处于哪一态：先合成「修复态」，再把它打坏
  assert.ok(bodyBg.test(CSS_SRC), '取不到 `.wh5-machine-body` 的 background ⇒ 变异无从注入，先修判据')
  const fixed = CSS_SRC.replace(bodyBg, '$1var(--wh5-machine-bg)')
  const fixedPair = machinePair(fixed)
  assert.ok(
    contrast(fixedPair.fg, fixedPair.bg) >= 4.5,
    `修复态（${fixedPair.fg} on ${fixedPair.bg}）仍 < 4.5:1 ⇒ 判据 ① 的阈值或解析写错了（修好之后也会被判红）`
  )
  assert.equal(
    GLOBAL_PAGE_BG.test(prop(ruleBody(stripComments(fixed), '.wh5-machine-body'), 'background')),
    false,
    '修复态仍被判「引用全局页面底」⇒ 判据 ② 写错了（修好之后也会被判红）'
  )

  const broken = fixed.replace(bodyBg, '$1var(--wh5-bg)')
  assert.notEqual(broken, fixed, '反向变异没生效')
  const brokenPair = machinePair(broken)
  assert.ok(
    contrast(brokenPair.fg, brokenPair.bg) < 4.5,
    '注入浅底后对比度仍 ≥ 4.5:1 ⇒ 判据 ① 是空断言（它没在看解析后的真实配对）'
  )
  assert.ok(
    GLOBAL_PAGE_BG.test(prop(ruleBody(stripComments(broken), '.wh5-machine-body'), 'background')),
    '注入 var(--wh5-bg) 后判据 ② 没命中 ⇒ ② 是空断言'
  )
})
