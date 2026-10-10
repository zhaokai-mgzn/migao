// case_ids: BM-025
//
// 工人端 `/w/` 报工页的**页头入口栏**（issue #5052 实现 PR → 2026-10-10 改版 issue #6635）。
//
// 🔴 本文件现在的判据（用户 2026-10-10 逐字裁定后）：
//   ① 入口栏**只**由 `cut_calc` 决定：在页面集里 ⇒ 出现「裁高计算（一体机）」真链接
//      （`/w/machine.html`）；∉ ⇒ **整条入口栏不渲染**（不留空 `<nav>`）；
//   ② **两条跨应用入口（拍照入库 / 补打入库标签）不得再出现在本页**（用户逐字：「移除拍照入库和
//      补打入库标签」）—— 反向钉住：页头再出现 `/b/#/pages/worker/inbound|reprint` ⇒ 红。
//      可达性**没有丢**：那两页的动线由**工人工作台**承载
//      （frontend/bmini-app/src/pages/worker/home/index.tsx；入口台账 `PAGE_ENTRY_LEDGER` 的 `from`
//      就是它），跨仓那一条判据在 frontend/bmini-app/tests/page-entry-reachability.test.ts ——
//      两处合起来才闭合（本文件管「本页不许再有」，那边管「别处真的能走到」）。
//   ③ 未登录（login 屏）不出现入口 —— 身份未确立时不给"下一跳"的假承诺。
//
// 判定落在**渲染结果**上（不是"源码里有这行"）：**注释里的锚点不算入口**（#5052 验收 D2 的口径）。
//
// ⚠️ 改前的形态（已撤，不要改回去）：入口栏常驻「拍照入库」「补打入库标签」两条跨应用 `<a>`，
// 另有 `entryProblemsInRendered()` 那套「两条入口必须都在」的判据 —— 它现在**反了**，
// 换成下面的反向钉住（出现即红）。
import test from 'node:test'
import assert from 'node:assert/strict'

import { initialState, PAGE_CUT_CALC, PAGE_REPORT, renderPage } from '../src/render.mjs'

/** 裁高计算入口 —— 本页**唯一**的入口（2026-10-10 起；改前叫「机台模式」）。 */
const MACHINE_ENTRY = '/w/machine.html'

/** 已移出本页的两条跨应用入口（反向锚：渲染里出现即红）。 */
const REMOVED_ENTRIES = ['/b/#/pages/worker/inbound/index', '/b/#/pages/worker/reprint/index']

const WORKER = { workerName: '张师傅', workerNo: 'W-001', idleMinutes: 43200 }

/** 去 HTML 注释后的可见文本（注释里的锚点不是入口，D2）。 */
const visible = (html) => html.replace(/<!--[\s\S]*?-->/g, '')

/** 登录态（`pages` 直接落在 state 上：本文件只测渲染，不走装配层）。 */
const loggedIn = (pages, extra = {}) => ({ ...initialState(), worker: WORKER, mode: 'scan', pages, ...extra })

test('🔴 ① `cut_calc` ∈ pages ⇒ 页头有「裁高计算（一体机）」入口；∉ ⇒ 整条入口栏不渲染', () => {
  const on = visible(renderPage(loggedIn([PAGE_REPORT, PAGE_CUT_CALC])))
  assert.equal(on.includes(`href="${MACHINE_ENTRY}"`), true, '`cut_calc` 已开却没有入口（机台那台屏走不到裁高页）')
  assert.match(on, /id="wh5-worker-entries"/, '入口栏要有稳定 id（判据 / 排障都按它定位）')
  assert.match(on, /class="wh5-entry"/, '入口必须带 wh5-entry 类（尺寸由 styles.css 统一给）')
  assert.match(on, />裁高计算（一体机）<\/a>/, '入口文案必须是人话（改前的「机台模式」用户看不懂：issue #6635）')
  assert.ok(!/机台模式/.test(on), '「机台模式」这个内部叫法不得再上屏')

  const off = visible(renderPage(loggedIn([PAGE_REPORT])))
  assert.equal(off.includes(MACHINE_ENTRY), false, '`cut_calc` 没开却仍在渲染入口（开关形同虚设）')
  assert.ok(!off.includes('id="wh5-worker-entries"'), '没有可渲染的入口 ⇒ **不留空入口栏**（2026-10-10 改版）')
})

test('🔴 ② 两条跨应用入口**不得**再出现在本页（2026-10-10 用户裁定移除）', () => {
  for (const pages of [[PAGE_REPORT, PAGE_CUT_CALC], [PAGE_REPORT], [PAGE_CUT_CALC], []]) {
    const html = visible(renderPage(loggedIn(pages)))
    for (const href of REMOVED_ENTRIES) {
      assert.equal(html.includes(href), false, `pages=${JSON.stringify(pages)} 时本页仍带着已移除的入口：${href}`)
    }
  }
})

test('🔴 ② 红证：把跨应用入口加回页头 ⇒ 本判据必红（反向钉住不是空断言）', () => {
  const html = visible(renderPage(loggedIn([PAGE_REPORT, PAGE_CUT_CALC])))
  assert.deepEqual(REMOVED_ENTRIES.filter((h) => html.includes(h)), [], '对照：真渲染下这两条本来就不在')
  // 变异体：把裁高入口的 href 换成那条被移除的入口（= "入口又回到本页"这一形态）
  const reAdded = html.replace(`href="${MACHINE_ENTRY}"`, `href="${REMOVED_ENTRIES[0]}"`)
  assert.deepEqual(
    REMOVED_ENTRIES.filter((h) => reAdded.includes(h)),
    [REMOVED_ENTRIES[0]],
    '变异体确实构造出了"已移除的入口又出现在本页"这一形态',
  )
  assert.notDeepEqual(
    REMOVED_ENTRIES.filter((h) => reAdded.includes(h)),
    REMOVED_ENTRIES.filter((h) => html.includes(h)),
    '加回入口后判定读数必须改变（否则本判据是空断言）',
  )
})

test('🔴 ① 红证：入口锚点被包进 HTML 注释 ⇒ 判定必红（注释里的链接不算入口，D2）', () => {
  // 为什么必须保住这条：改前 `/w/` 有两条跨应用锚点，D2 的红证挂在它们身上；那两条撤了之后
  // **剩下的这一条锚点**必须接过同一份覆盖（否则"注释里的链接被当成入口"这一类就没人拦了）。
  const html = visible(renderPage(loggedIn([PAGE_REPORT, PAGE_CUT_CALC])))
  assert.equal(html.includes(`href="${MACHINE_ENTRY}"`), true, '对照：真渲染下本判据判绿')
  const commented = html.replace(/(<a class="wh5-entry"[^>]*>[^<]*<\/a>)/, '<!--$1-->')
  assert.ok(commented.includes(`href="${MACHINE_ENTRY}"`), '变异体里锚点串仍在（按 includes 判的那种守卫照样绿）')
  assert.ok(commented.includes('<!--<a class="wh5-entry"'), '变异体确实是"锚点被注释掉"这一形态')
  assert.equal(visible(commented).includes(`href="${MACHINE_ENTRY}"`), false, '注释包裹后**本判据用的可见文本**里必须没有它')
})

test('🔴 入口出现在**每一个登录后视图**（页头是共用件：扫 / 选套 / 主屏都带它）', () => {
  const selecting = renderPage(loggedIn([PAGE_CUT_CALC], {
    mode: 'select',
    view: { needs_selection: [{}], selections: [] },
  }))
  assert.equal(selecting.includes(`href="${MACHINE_ENTRY}"`), true, '旧码选套屏丢了裁高计算入口')
  const main = renderPage(loggedIn([PAGE_CUT_CALC], {
    mode: 'main',
    view: { set_no: 1, position: { position_name: '布帘' }, operation: null },
  }))
  assert.equal(main.includes(`href="${MACHINE_ENTRY}"`), true, '主屏丢了裁高计算入口')
})

test('🔴 未登录（login 屏）不出现入口 —— 身份未确立时不给"下一跳"的假承诺', () => {
  const html = renderPage(initialState())
  assert.ok(!html.includes(MACHINE_ENTRY), '登录屏不该出现工人面入口（页头是登录后才有的）')
  assert.ok(!html.includes('/b/#/pages/worker/'), '登录屏也不该出现跨应用入口')
  assert.match(html, /id="wh5-login"/, '登录入口必须还在（不是把整页弄没了）')
})
