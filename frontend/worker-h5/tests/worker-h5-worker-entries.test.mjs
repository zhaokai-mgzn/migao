// case_ids: BM-025
//
// 工人端 `/w/`（对外落点 `/b/report/`）报工页的**页头入口栏**（issue #5052 实现 PR → 2026-10-10
// 改版 issue #6635 → 2026-10-27 再收窄 issue #7934）。
//
// 🔴 本文件现在的判据（用户 2026-10-27 逐字「我的计件和发货…为什么做到报工详情页面？应该都作为
// 工人菜单页面上的菜单，工人页面有拍照发货了，可以把报工详情页面的发货功能移除掉」）：
//   ① 入口栏**只剩两条**：`cut_calc` ⇒「裁高计算（一体机）」、`rework` ⇒「返工记录」；
//      两条都没开 ⇒ **整条入口栏不渲染**（不留空 `<nav>`）；
//   ② **四条跨应用入口不得再出现在本页**（拍照入库 / 补打入库标签 / 我的计件 / 发货）——
//      反向钉住：页头再出现这四条里任何一条 ⇒ 红；即使对应页面键（`piecework` / `to_ship`）
//      是开着的，也一条都不许冒出来（它们已改由**工人菜单页**承载）。
//   ③ 未登录（login 屏）不出现入口 —— 身份未确立时不给"下一跳"的假承诺；
//   ④ **两张静态页本身仍在**（`piecework.html` / `shipment.html` + 各自的装配模块）：
//      「入口搬走」≠「页面下线」，直连仍可用（菜单显隐语义，不是访问拦截）。
//
// 判定落在**渲染结果**上（不是"源码里有这行"）：**注释里的锚点不算入口**（#5052 验收 D2 的口径）。
//
// ⚠️ 改前的形态（已撤，不要改回去）：入口栏里还有「我的计件」「发货」两条跨应用 `<a>`（issue #6767 /
// #7761 加的），并有「`piecework` ∈ pages ⇒ 出现入口」那组**正向**判据 —— 那个方向现在是**反的**
// （见 ②），本文件把正向断言换成反向钉住 + 页面存活断言。
import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  initialState,
  PAGE_CUT_CALC,
  PAGE_PIECEWORK,
  PAGE_REPORT,
  PAGE_REWORK,
  PAGE_TO_SHIP,
  renderPage,
} from '../src/render.mjs'

/** worker-h5 的仓内根（`frontend/worker-h5/`）——「页面还在不在」按它定位。 */
const H5_ROOT = fileURLToPath(new URL('..', import.meta.url))

/** 裁高计算入口 —— 2026-10-10 起就在本页；issue #7934 决定**暂留**（端内还没有裁高页）。 */
const MACHINE_ENTRY = './machine.html'

/** 返工记录入口（issue #7860）。 */
const REWORK_ENTRY = './rework.html'

/**
 * 已移出本页的四条跨应用入口（反向锚：渲染里出现即红）。
 * 前两条 = 2026-10-10（issue #6635）；后两条 = 2026-10-27（issue #7934）。
 */
const REMOVED_ENTRIES = [
  '/b/#/pages/worker/inbound/index',
  '/b/#/pages/worker/reprint/index',
  './piecework.html',
  './shipment.html',
]

const WORKER = { workerName: '张师傅', workerNo: 'W-001', idleMinutes: 43200 }

/** 去 HTML 注释后的可见文本（注释里的锚点不是入口，D2）。 */
const visible = (html) => html.replace(/<!--[\s\S]*?-->/g, '')

/** 登录态（`pages` 直接落在 state 上：本文件只测渲染，不走装配层）。 */
const loggedIn = (pages, extra = {}) => ({ ...initialState(), worker: WORKER, mode: 'scan', pages, ...extra })

test('🔴 ① `cut_calc` ∈ pages ⇒ 页头有「裁高计算（一体机）」入口；两条都没开 ⇒ 整条入口栏不渲染', () => {
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

test('🔴 ① `rework` ∈ pages ⇒ 页头有「返工记录」入口（issue #7860，是剩下两条之一）', () => {
  const on = visible(renderPage(loggedIn([PAGE_REPORT, PAGE_REWORK])))
  assert.match(on, /id="wh5-rework-entry"[^>]*href="\.\/rework\.html"/, '返工记录入口必须是真链接')
  assert.match(on, />返工记录<\/a>/, '入口文案必须是人话')

  const off = visible(renderPage(loggedIn([PAGE_REPORT, PAGE_CUT_CALC])))
  assert.equal(off.includes(REWORK_ENTRY), false, '`rework` 没开却仍在渲染返工入口')
})

test('🔴 ② 四条跨应用入口**不得**再出现在本页（含页面键开着的组合）', () => {
  const fixtures = [
    [PAGE_REPORT, PAGE_CUT_CALC],
    [PAGE_REPORT],
    [PAGE_CUT_CALC],
    // 🔴 issue #7934：这两条页面键**开着**也不许在本页冒出入口（它们改由工人菜单页承载）
    [PAGE_REPORT, PAGE_PIECEWORK],
    [PAGE_REPORT, PAGE_TO_SHIP],
    [PAGE_REPORT, PAGE_PIECEWORK, PAGE_TO_SHIP, PAGE_CUT_CALC, PAGE_REWORK],
    [],
  ]
  for (const pages of fixtures) {
    const html = visible(renderPage(loggedIn(pages)))
    for (const href of REMOVED_ENTRIES) {
      assert.equal(html.includes(href), false, `pages=${JSON.stringify(pages)} 时本页仍带着已移除的入口：${href}`)
    }
  }
})

test('🔴 ② 红证：把「我的计件」入口加回页头 ⇒ 本判据必红（反向钉住不是空断言）', () => {
  const html = visible(renderPage(loggedIn([PAGE_REPORT, PAGE_CUT_CALC, PAGE_PIECEWORK])))
  assert.deepEqual(REMOVED_ENTRIES.filter((h) => html.includes(h)), [], '对照：真渲染下这四条本来都不在')
  // 变异体：把裁高入口的 href 换成那条被移除的入口（= "入口又回到本页"这一形态）
  const reAdded = html.replace(`href="${MACHINE_ENTRY}"`, 'href="./piecework.html"')
  assert.ok(reAdded.includes('href="./piecework.html"'), '变异未生效（锚点漂移会让本红证退化成空断言）')
  assert.deepEqual(
    REMOVED_ENTRIES.filter((h) => reAdded.includes(h)),
    ['./piecework.html'],
    '变异体确实构造出了"已移除的入口又出现在本页"这一形态',
  )
  assert.notDeepEqual(
    REMOVED_ENTRIES.filter((h) => reAdded.includes(h)),
    REMOVED_ENTRIES.filter((h) => html.includes(h)),
    '加回入口后判定读数必须改变（否则本判据是空断言）',
  )
})

test('🔴 ① 红证：入口锚点被包进 HTML 注释 ⇒ 判定必红（注释里的链接不算入口，D2）', () => {
  // 为什么必须保住这条：改前 `/w/` 挂着多条跨应用锚点，D2 的红证挂在它们身上；那几条撤了之后
  // **剩下的这两条锚点**必须接过同一份覆盖（否则"注释里的链接被当成入口"这一类就没人拦了）。
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

test('🔴 ④ 两张静态页本身仍在（入口搬走 ≠ 页面下线）：piecework.html / shipment.html 可直连', () => {
  const pages = [
    ['piecework.html', 'src/piecework-app.mjs', 'piecework-root'],
    ['shipment.html', 'src/shipment-app.mjs', 'shipment-root'],
  ]
  for (const [pageRel, appRel, rootId] of pages) {
    const pageAbs = path.join(H5_ROOT, pageRel)
    assert.equal(existsSync(pageAbs), true, `${pageRel} 不见了 —— 那是把"入口搬走"做成了"页面下线"（issue #7934 的边界）`)
    const html = readFileSync(pageAbs, 'utf8')
    assert.ok(html.includes(`src="./${appRel}"`), `${pageRel} 的装配模块引用漂移了（期望 ./${appRel}）`)
    assert.ok(html.includes(`id="${rootId}"`), `${pageRel} 的根节点不见了（期望 id="${rootId}"）`)
    assert.equal(existsSync(path.join(H5_ROOT, appRel)), true, `${appRel} 不见了（页面引用了不存在的模块 ⇒ 直连白屏）`)
  }
})
