// case_ids: MC-206
//
// 类级守卫：**用户可见的入口 / 页面标题里不许出现端名**（`一体机` / `手持机`）。
//
// 病灶（issue #8683）：裁高页的入口与屏上标题一直叫「裁高计算（一体机）」—— 那是这页**只有一体机
// 能进**时的叫法（2026-09-29 母单 #5161）。2026-11-04 终端仓（migao-terminal #56 / #57）把同一个入口
// 开到**手持标签机**上之后，端名就从「多余」变成了**错误陈述**：同一个入口两端都在用，写死一端
// 就是在告诉另一端的工人「这不是给你的」，而点在手上又确实能进 ⇒ 用户看到的是自相矛盾的界面。
//
// 为什么是**类级**而不是只钉这一处（铁律 8「修一个缺陷只修这一处 = 没修」）：
// 同类会随能力表继续长（今天是裁高页，明天是打印入库标签 / 质检 …）—— 判据写成
// 「**所有**渲染出来的用户可见面都不许出现端名」，新增任何入口 / 标题带端名都会红，
// 不需要有人记得回来加断言。
//
// 判据（每条都能红）：
//   ① `/w/` 页头裁高入口文案 = 「裁高计算」（不带端名）—— 改回带端名的写法 ⇒ 红；
//   ② 机台屏 `<h1>` = 「裁高计算」—— 改回带端名 ⇒ 红（入口一个词、点进去两个词，落差更显眼）；
//   ③ `machine.html` 的 `<title>` = 「裁高计算」—— 改回带端名 ⇒ 红（浏览器标签页 / kiosk 标题栏）；
//   ④ 🔴 **类级**：所有用户可见面（`/w/` 主屏 / 机台屏 / **现取**的全部静态页 `<title>`）
//      出现端名（`一体机` / `手持机`；`安卓一体机` 含前者的子串 ⇒ 同一条覆盖）⇒ 红，
//      并**具名**报出「哪一面 :: 命中片段」；
//   ⑤ 判据 ④ 的**负向对照**：把端名写回机台屏 ⇒ 类级扫描当场命中（否则 ④ 是空断言）。
//
// 判定口径（三条，都照着本仓既有裁决写）：
//   · **注释不算**：先剥 HTML 注释（#5052 的既有口径 —— 注释里的锚点不是入口，也不是文案）；
//   · 只扫**可见文本**：剥掉标签后的正文（`class` / `id` / `href` 是标识符，不是给工人看的字）；
//   · 静态页清单**现取**（`readdirSync` 的 `*.html`），不是手写名单 —— 新增静态页自动进射程，
//     不会因为「忘了登记」而静默放行。
//
// 红证（注入式，实跑读数见 PR body）：把 machine.mjs 的 `<h1>` 改回「裁高计算（一体机）」⇒ ② 与 ④
// 各自具名红；还原后逐字节相等、全绿。entry 侧同理（render.mjs 的入口文案）。
import test from 'node:test'
import assert from 'node:assert/strict'
import { readdirSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { initialState, renderPage } from '../src/render.mjs'
import { initialMachineState, renderScan } from '../src/machine.mjs'

/** worker-h5 的仓内根（`frontend/worker-h5/`）：静态页就在这一层。 */
const H5_ROOT = fileURLToPath(new URL('..', import.meta.url))

/** 端名清单：写死任何一端 = 对另一端的工人说错话。`安卓一体机` 含 `一体机` ⇒ 被同一条覆盖。 */
const DEVICE_NAMES = ['一体机', '手持机']

const WORKER = { workerName: '张师傅', workerNo: 'W-001', idleMinutes: 43200 }

/**
 * 第三轴（**本机能力**，issue #8609）固定为「安卓一体机」（有裁高机链路）——
 * 本文件判的是**文案**，第三轴不能当隐藏变量（没有 `cut.link` 时入口本来就不渲染）。
 */
const ALL_IN_ONE = {
  capabilities: { 'scan.hid': true, 'scan.camera': true, 'cut.link': 'serial:COM3', 'print.label': null, 'update.channel': 'apk' },
}

/** `/w/` 主屏（工人报工页；页面集走 fail-open 全开 ⇒ 裁高入口在）。 */
const workerScreen = () => renderPage({ ...initialState(), worker: WORKER, mode: 'scan', terminal: ALL_IN_ONE })

/** 机台屏「等扫码那一屏」（屏上标题就在这一屏）。 */
const machineScreen = () => renderScan(initialMachineState())

/** 剥 HTML 注释（纯字符串操作；注释里的历史说明不是文案）。 */
function stripHtmlComments(html) {
  let out = ''
  let rest = html
  for (;;) {
    const start = rest.indexOf('<!--')
    if (start < 0) return out + rest
    out += rest.slice(0, start)
    const end = rest.indexOf('-->', start + 4)
    if (end < 0) return out
    rest = rest.slice(end + 3)
  }
}

/** 剥一段被某个开标签包住的块（script / style 的正文不是给工人看的字）。 */
function stripBlock(src, open, close) {
  let out = ''
  let rest = src
  for (;;) {
    const start = rest.indexOf(open)
    if (start < 0) return out + rest
    out += rest.slice(0, start)
    const end = rest.indexOf(close, start + open.length)
    if (end < 0) return out
    rest = rest.slice(end + close.length)
  }
}

/** 可见文本：剥注释 / script / style 之后，再把标签本身剥掉。 */
function visibleText(html) {
  const body = stripBlock(stripBlock(stripHtmlComments(html), '<script', '</script>'), '<style', '</style>')
  let text = ''
  let rest = body
  for (;;) {
    const lt = rest.indexOf('<')
    if (lt < 0) return text + rest
    text += rest.slice(0, lt)
    const gt = rest.indexOf('>', lt + 1)
    if (gt < 0) return text
    rest = rest.slice(gt + 1)
  }
}

/** 静态页清单**现取**（不手写名单：新增页自动进射程）。 */
const staticPages = () =>
  readdirSync(H5_ROOT)
    .filter((f) => f.endsWith('.html'))
    .sort()

/** 某个静态页的 `<title>`（可见文案：浏览器标签页 / kiosk 标题栏都念它）。 */
function pageTitle(file) {
  const html = readFileSync(path.join(H5_ROOT, file), 'utf8')
  const open = html.indexOf('<title>')
  assert.ok(open >= 0, `${file} 里没有 <title>：静态页标题是可见文案，判据必须能取到它`)
  const start = open + '<title>'.length
  const close = html.indexOf('</title>', start)
  assert.ok(close > start, `${file} 的 <title> 没有闭合`)
  return html.slice(start, close).trim()
}

/** 所有用户可见面（类级判据 ④ 的射程）。 */
function userVisibleSurfaces() {
  const surfaces = [
    { name: '/w/ 主屏（工人报工页）', text: visibleText(workerScreen()) },
    { name: '机台屏（等扫码那一屏）', text: visibleText(machineScreen()) },
  ]
  for (const file of staticPages()) surfaces.push({ name: `${file} 的 <title>`, text: pageTitle(file) })
  return surfaces
}

/** 端名命中（含前后各 12 字的上下文，便于具名归因）。 */
function deviceNameHits(text) {
  const hits = []
  for (const name of DEVICE_NAMES) {
    let from = 0
    for (;;) {
      const at = text.indexOf(name, from)
      if (at < 0) break
      const snippet = text.slice(Math.max(0, at - 12), at + name.length + 12).replace(/\s+/g, ' ')
      hits.push(`${name} ⟵ …${snippet}…`)
      from = at + name.length
    }
  }
  return hits
}

test('🔴 ① `/w/` 页头裁高入口文案 = 「裁高计算」（不带端名）', () => {
  const html = stripHtmlComments(workerScreen())
  const at = html.indexOf('id="wh5-machine-entry"')
  assert.ok(at >= 0, '/w/ 主屏没有裁高入口（`cut_calc` 默认开 ⇒ 入口必须渲染）')
  const open = html.indexOf('>', at)
  const close = html.indexOf('</a>', open)
  assert.ok(open > at && close > open, '裁高入口的链接标签不完整（判据取不到链接文字）')
  assert.equal(html.slice(open + 1, close), '裁高计算',
    '入口文案必须是人话、且不按端分叉（issue #8683：手持标签机也能进这页，端名即错误陈述）')
})

test('🔴 ② 机台屏 `<h1>` = 「裁高计算」（不带端名）', () => {
  const html = stripHtmlComments(machineScreen())
  const at = html.indexOf('<h1>')
  assert.ok(at >= 0, '机台屏没有 <h1>：屏上标题是工人在车间看到的第一个词，判据必须能取到它')
  const start = at + '<h1>'.length
  const close = html.indexOf('</h1>', start)
  assert.ok(close > start, '机台屏的 <h1> 没有闭合')
  assert.equal(html.slice(start, close), '裁高计算',
    '屏上标题必须与入口同一句话（否则点之前一个词、点之后两个词，落差更显眼 —— issue #8683）')
})

test('🔴 ③ `machine.html` 的 `<title>` = 「裁高计算」（不带端名）', () => {
  assert.equal(pageTitle('machine.html'), '裁高计算',
    '静态页标题同样是用户可见文案（浏览器标签页 / kiosk 标题栏），不许带端名（issue #8683）')
})

test('🔴 ④ 类级：所有用户可见面都不许出现端名（一体机 / 手持机）', () => {
  const offenders = []
  for (const { name, text } of userVisibleSurfaces()) {
    for (const hit of deviceNameHits(text)) offenders.push(`${name} :: ${hit}`)
  }
  assert.deepEqual(offenders, [],
    '用户可见的入口 / 页面标题里出现端名：同一个入口两端都在用 ⇒ 写死一端就是错误陈述，'
    + '且会随能力表继续腐烂（issue #8683）。命中清单：\n' + offenders.join('\n'))
})

test('🔴 ⑤ 负向对照：把端名写回机台屏 ⇒ 类级扫描当场命中（否则 ④ 是空断言）', () => {
  const mutated = machineScreen().replace('<h1>裁高计算</h1>', '<h1>裁高计算（一体机）</h1>')
  assert.notEqual(mutated, machineScreen(), '变异没生效（锚点漂移）：注入式对照必须真改到渲染产物')
  assert.deepEqual(deviceNameHits(visibleText(mutated)).map((h) => h.split(' ⟵ ')[0]), ['一体机'],
    '把端名写回屏上标题后，类级扫描必须命中（否则判据 ④ 没有牙）')
  assert.deepEqual(deviceNameHits(visibleText(machineScreen())), [], '对照：未注入时不该命中（同一把尺子）')
})
