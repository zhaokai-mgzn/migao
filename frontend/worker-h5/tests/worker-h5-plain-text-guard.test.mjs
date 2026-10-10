// case_ids: PG-065, BM-006, PG-018
//
// 工人端 H5 / 一体机机台页 —— 屏上不得出现未解析的 Markdown 强调记号（issue #6679）。
//
// 缺陷（合并后自证发现，PR #6675 / issue #6667 引入）：机台页 HTML 模板串里直接写了成对星号
// 包夹的「当前工人」⇒ 屏上字面显示两个星号（真 Chrome 1024×768 截图 + `body.innerText` 均已读到）。
// 病灶同 §31 P3/P4：书写记号上屏 = 现场观感「这系统是半成品」。
//
// 本文件 = 类级判据（不是只钉那一句）：
//   ①「屏上文本」= `renderScan` / `renderMachine` / `renderPage` 的真返回值去标签后的文本，
//      不含成对 Markdown 强调记号（双星号 / 双下划线）；
//   ②「用户可见字符串」= `frontend/worker-h5/**` 源码（`src/**/*.mjs` 的 HTML 模板串、`*.html`、
//      `src/styles.css`）去掉注释后不得含成对记号；
//   ③ 判别力自证（防恒真）：注入记号 ⇒ 必红；正常文案里的单个星号（`3*4` / `*必填`）、
//      以及本仓合法的双下划线命名（`wh5-machine__panel` / `__requestId`）⇒ 不误伤（都实跑）。
//
// 🔴 边界（有意接受，逐条写清，不是遗漏）：
//   - 注释里的记号不判红（仓库注释风格就是双星号强调；`src/machine.mjs` 的 JSDoc 里有几十处）
//     ⇒ 扫描前先剥注释；`machine.html` 的页头注释就是实证边界。
//   - 反引号代码段不判红：那是「文档在讲这个记号本身」（本文件注释即是），
//     真缺陷形态是没有反引号包裹的裸记号。
//   - 扫描面 = 文件名集合显式写死在下方 `SOURCE_FILES` / `HTML_FILES`（不放宽、不递归吞 tests/）；
//     新增文件须显式加入 —— 「扫到了什么」读得出来，不靠 glob 的隐式行为。
//
// 零依赖：`node --test` + 手写去标签（不引 jsdom —— 最少代码阶梯）。

import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import { initialState, renderPage } from '../src/render.mjs'
import { initialMachineState, renderMachine, renderScan } from '../src/machine.mjs'

const read = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8')

const TICK = String.fromCharCode(96) // 反引号（直接写进源码会打断模板串，故用码点）

// ══════════════════════════════════════════════════════════════════════════════
// 扫描器（本判据的全部判别力都在这两个函数里，故逐条自证 —— 见「判别力自证」用例）
// ══════════════════════════════════════════════════════════════════════════════

/**
 * 「用户可见字符串」抽取：**先剥注释、再去引号**（两遍正则），留下会进模板串的字符。
 *
 * 🔴 **顺序是判据的命门（实测踩过，记下来）**：注释里会出现英文引号 / 撇号
 * （本仓注释爱用「」夹英文撇号写中文），先剥字符串的话引号配对从此失衡 ⇒ 后面几百行代码
 * 被当成一个字符串吞掉 —— **真缺陷也被吞**，判据对着真缺陷不红（本包实测：`machine.mjs` 的
 * 命中消失）。注释先没了，那里的引号就不再是引号，只剩合法 JS 串、配对平衡。
 *
 * 🔴 **为什么不用单遍状态机**：同一份源码里「注释里的记号」（合法）与「字符串里的记号」（缺陷）
 * 必须分开，而单遍扫描下注释里的引号会把状态机带偏（本包实测同样吞掉真缺陷）。
 * 两遍正则反而**可预测**：面 = 「元字符的剩余集」，读得出来。
 *
 * 边界（如实登记）：正则不解析模板串里的 `${}` 嵌套，也不建模转义引号 —— 对**本判据要判的东西**
 * （成对记号）这些边界都不影响实测读数（下面 ① 的判别力自证逐条钉住了红/绿两个方向）。
 */
const TICK_RE = '[^' + TICK + ']*'
const STRING_PATTERNS = [
  new RegExp("'([^'\\n]*)'", 'g'),
  /"([^"\n]*)"/g,
  new RegExp(TICK + '(' + TICK_RE + ')' + TICK, 'g'),
]
const COMMENT_PATTERNS = [
  /\/\*[\s\S]*?\*\//g, // 块注释（含 JSDoc）
  /<!--[\s\S]*?-->/g, // HTML 注释
  /\/\/[^\n]*/g, // 行注释
]
const keepNewlines = (m) => m.replace(/[^\n]/g, '')

function userVisibleSource(src) {
  let out = src
  for (const re of COMMENT_PATTERNS) out = out.replace(re, keepNewlines)
  // 🔴 注释**先**剥：注释里的引号（如「一律叫「裁高计算（一体机）」——「机台模式」是内部叫法」这类
  //    中文引号夹英文撇号）会打断「先剥字符串」的顺序 ⇒ 状态机/正则的引号配对从此失衡、
  //    把**后面几百行代码**当字符串吞掉（实测：真缺陷被吞、判据对着真缺陷也不红）。
  //    注释先没了 ⇒ 那里的引号不再是引号（只剩合法 JS 串，配对平衡）。
  //    字符串**内容留下**、只去掉引号：那是真会渲染进模板串的字符，正是本判据要抓的东西。
  for (const re of STRING_PATTERNS) out = out.replace(re, '$1')
  return out
}

/**
 * 找成对的 Markdown 强调记号（双星号 / 双下划线）。返回 `[{marker, line, text}]`
 * （空数组 = 没有）。
 *
 * 单个星号不成对就不算 ⇒ `3*4` / `*必填` 不误伤（有意：那是正常文案里的星号）。
 *
 * 🔴 双下划线一支必须按词边界判（实测踩过，记下来）：本仓的双下划线是合法命名惯例
 * （BEM 修饰符 `wh5-machine__panel`、双下划线私有属性 `__requestId`）⇒ 朴素
 * `/__[^_]+__/` 会拿它们当 Markdown 判红（误伤）。真 Markdown 的双下划线两侧是词边界，
 * 用前后 `[\w]` 断言即可与 BEM / 私有属性区分。
 */
function findEmphasisMarkers(text) {
  const hits = []
  const pair = (re, marker) => {
    for (const m of text.matchAll(re)) {
      const before = text.slice(0, m.index)
      hits.push({ marker, line: before.split('\n').length, text: m[0] })
    }
  }
  pair(/\*\*[^*\n]+\*\*/g, 'STAR')
  pair(/(?<![\w])__[^_\n]+__(?![\w])/g, 'UNDER')
  return hits
}

/** 「屏上文本」= 渲染出的 HTML 去标签 / 解实体 / 去注释（≈ `innerText` 的字符面）。 */
function renderedText(html) {
  return html
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/<[^>]*>/g, '')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, '&')
}

const describe = (hits) => hits.map((h) => `${h.marker}@L${h.line} ${JSON.stringify(h.text)}`).join(' | ')

// ══════════════════════════════════════════════════════════════════════════════
// 扫描面（显式文件名，不递归吞 tests/ —— 台账/扫描面不许隐式放宽）
// ══════════════════════════════════════════════════════════════════════════════

// 变更集里新增用户可见串的文件要显式加进来（reader 一眼看得出扫了什么）。
const SOURCE_FILES = [
  '../src/api.mjs',
  '../src/app.mjs',
  '../src/machine-app.mjs',
  '../src/machine.mjs',
  '../src/render.mjs',
  '../src/scan-input.mjs',
  '../src/shipment.mjs',
  '../src/shared/operation-display.mjs',
  '../src/styles.css',
]
const HTML_FILES = ['../index.html', '../machine.html']

// ══════════════════════════════════════════════════════════════════════════════
// ① 判别力自证（防恒真）：注入 ⇒ 必红 / 单星号与双下划线命名 ⇒ 不误伤
// ══════════════════════════════════════════════════════════════════════════════

test('#6679 判别力自证：成对记号判红，单个星号与合法双下划线命名不误伤', () => {
  // 红方向：把记号注入回去 ⇒ 必须命中（缺陷原形态就是这一句）
  assert.equal(
    findEmphasisMarkers('<p>这台屏上扫的活记在**当前工人**名下</p>').length,
    1,
    '注入的成对星号未被判红 ⇒ 判据没有判别力',
  )
  assert.equal(findEmphasisMarkers('<p>__重点__</p>').length, 1, '注入的双下划线未被判红')

  // 绿方向①：正常文案里的单个星号不许误伤
  assert.deepEqual(findEmphasisMarkers('<p>幅宽 3*4 米，*必填</p>'), [], '单个星号被误判成 Markdown 记号')
  assert.deepEqual(findEmphasisMarkers('<p>2 * 3 = 6，单价 ¥1.5</p>'), [], '乘号/单星号被误判')

  // 绿方向②（实测踩过的误伤，必须钉住）：本仓双下划线是合法命名惯例 ——
  // BEM 修饰符（`wh5-machine__panel`）/ 双下划线私有属性（`__requestId`）不是 Markdown。
  assert.deepEqual(
    findEmphasisMarkers('<p class="wh5-machine__hint">提示</p>'),
    [],
    'BEM 类名 wh5-machine__hint 被误判成双下划线记号（判据会被本仓 CSS 惯例喂红）',
  )
  assert.deepEqual(findEmphasisMarkers('const id = __requestId ?? makeId()'), [], '`__requestId` 被误判')
  assert.deepEqual(
    findEmphasisMarkers('.wh5-machine__cta, .wh5-machine__big { color: red }'),
    [],
    'CSS 选择器里的双下划线被误判',
  )

  // 边界：注释里的记号不是上屏缺陷（仓库注释风格）；剥注释后不该命中
  assert.deepEqual(
    findEmphasisMarkers(userVisibleSource('// 本页**不写机器**\n/**\n * 判据①**有线扫码枪**\n */\nconst x = 1\n')),
    [],
    '注释里的成对星号被当成上屏缺陷（判据会被仓库注释风格喂红）',
  )
  // 反向：同一句在字符串里（真上屏）剥注释后仍在 ⇒ 必红
  assert.equal(
    findEmphasisMarkers(userVisibleSource('const h = `<p>记在**当前工人**名下</p>`\n')).length,
    1,
    '字符串里的成对星号被剥没了 ⇒ 判据对着真缺陷也不会红',
  )
})

// ══════════════════════════════════════════════════════════════════════════════
// ② 源码面：frontend/worker-h5/** 的用户可见字符串零成对记号
// ══════════════════════════════════════════════════════════════════════════════

test('#6679 worker-h5 源码（用户可见字符串）不含成对 Markdown 强调记号', () => {
  const offenders = []
  for (const rel of [...SOURCE_FILES, ...HTML_FILES]) {
    const hits = findEmphasisMarkers(userVisibleSource(read(rel)))
    if (hits.length > 0) offenders.push(`${rel}: ${describe(hits)}`)
  }
  assert.deepEqual(offenders, [], `屏上会出现字面 Markdown 记号：\n${offenders.join('\n')}`)
})

// ══════════════════════════════════════════════════════════════════════════════
// ③ 屏上面：真渲染函数吐出的文本零记号（源码非字符串来源也覆盖）
// ══════════════════════════════════════════════════════════════════════════════

test('#6679 机台页真渲染文本不含成对 Markdown 强调记号（扫/详情/裁高/错误四态）', () => {
  const position = { position_name: '主帘', fabric_meters: 2, rows: [] }
  const states = {
    扫: initialMachineState(),
    未登录: { ...initialMachineState(), worker: null },
    '已登录（提示含「当前工人」那句）': { ...initialMachineState(), worker: { workerName: '张三' } },
    详情: { ...initialMachineState(), worker: { workerName: '张三' }, mode: 'detail', token: 't', data: { positions: [position] } },
    裁高: { ...initialMachineState(), worker: { workerName: '张三' }, mode: 'calc', token: 't', data: { positions: [position] } },
    错误: { ...initialMachineState(), worker: { workerName: '张三' }, mode: 'error', error: '网络不给力，请重扫' },
  }
  const offenders = []
  for (const [name, state] of Object.entries(states)) {
    const hits = findEmphasisMarkers(renderedText(renderMachine(state)))
    if (hits.length > 0) offenders.push(`${name}: ${describe(hits)}`)
  }
  assert.deepEqual(offenders, [], `机台屏上会出现字面 Markdown 记号：\n${offenders.join('\n')}`)
})

test('#6679 报工页真渲染文本不含成对 Markdown 强调记号（未登录/扫码/主屏）', () => {
  const view = { positions: [], needs_selection: [], order: { order_no: 'A1' } }
  const states = {
    未登录: initialState(),
    待扫码: { ...initialState(), worker: { workerName: '张三' } },
    主屏: { ...initialState(), worker: { workerName: '张三' }, view, mode: 'main' },
  }
  const offenders = []
  for (const [name, state] of Object.entries(states)) {
    const hits = findEmphasisMarkers(renderedText(renderPage(state, state.view)))
    if (hits.length > 0) offenders.push(`${name}: ${describe(hits)}`)
  }
  assert.deepEqual(offenders, [], `报工页屏上会出现字面 Markdown 记号：\n${offenders.join('\n')}`)
})

// ══════════════════════════════════════════════════════════════════════════════
// ④ 反向对照（防「判据自己恒绿」）：未登录那句提示确实渲染出来了
//    —— 若渲染态没覆盖到那一行，上面几条会「因为没渲染」而假绿
// ══════════════════════════════════════════════════════════════════════════════

test('#6679 反向对照：未登录机台页确实渲染出「当前工人」那句提示', () => {
  const text = renderedText(renderScan({ ...initialMachineState(), worker: null }))
  assert.match(text, /这台屏上扫的活记在当前工人名下/, '这句提示没渲染出来 ⇒ 上面「零记号」是空跑（假绿）')
})
