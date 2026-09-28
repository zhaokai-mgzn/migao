// case_ids: BM-025
//
// 工人面两页的**入口**（issue #5052 实现 PR；设计 §5.4 路线 (a)）—— 由 `/w/` 报工页承载。
//
// 治的形态：拍照入库 / 拍照补打标签两页**都做完了、都合并了**，而工人**一步也走不到**
// （没有入口的功能按验收协议 v1.11「交付物可达性」三问之② **不算交付**）。
//
// 🔴 为什么入口在这一页：`/w/` 是工人在车间**手里唯一常开的那一页**（他一天扫几十次洗水码报工）；
// 把入口挂在他眼前那一页才叫动线。判据落在**渲染结果**上（不是"源码里有这行"）：
// 删掉 `workerEntriesBar()` 的调用 ⇒ 本文件当场红。
//
// 🔴 零依赖仍然成立（裁定 13「不重写 worker-h5」）：入口是**一行 `<a href>` + 一条 CSS**，
// 不引任何包、不加构建步骤（本文件用 `node --test` 直接钉渲染结果）。
import test from 'node:test'
import assert from 'node:assert/strict'

import { initialState, renderPage } from '../src/render.mjs'

/** 跨应用静态链接（同源同静态根：`/w/` 与 `/b/` 同一台 nginx）—— 目标 = bmini-app 的页面路由 */
const INBOUND_ENTRY = '/b/#/pages/worker/inbound/index'
const REPRINT_ENTRY = '/b/#/pages/worker/reprint/index'

const WORKER = { workerName: '张师傅', workerNo: 'W-001', idleMinutes: 15 }

/**
 * 入口判定：**判"真渲染输出里的锚点"**，不是"源文本里出现过这个串"。
 *
 * 🔴 治的形态（issue #5052 验收 D2）：把 `<a class="wh5-entry" href="…">` 整段包进
 * HTML 注释 `<!-- … -->` ⇒ 按 `html.includes(href)` 判的守卫**照样绿**，而工人**看不到**入口。
 * ⇒ 判定前先去掉 HTML 注释（`node --test` 与 jest 两个运行时的判定口径在这里各自实现一份，
 * 但**语义同一**：注释里的锚点不算入口）。
 */
function entryProblemsInRendered(html) {
  const visible = html.replace(/<!--[\s\S]*?-->/g, '')
  const problems = []
  for (const [label, href] of [['拍照入库', INBOUND_ENTRY], ['补打入库标签', REPRINT_ENTRY]]) {
    if (!visible.includes(`href="${href}"`)) {
      problems.push(`页头缺「${label}」入口（href=${href}）⇒ 工人走不到那一页`)
    }
    if (!visible.includes(`>${label}</a>`)) problems.push(`入口「${label}」的文案不在链接里`)
  }
  return problems
}

test('🔴 工人身份确立后，页头常驻两页入口（渲染结果，不是源码印象）', () => {
  const html = renderPage({ ...initialState(), worker: WORKER, mode: 'scan' })
  assert.deepEqual(entryProblemsInRendered(html), [], '页头入口缺失（判定按渲染结果，且**注释里的锚点不算**）')
  assert.match(html, /id="wh5-worker-entries"/, '入口区要有稳定 id（判据/排障都按它定位）')
  // 触控目标 ≥44px 是两断点的既有硬约束（裁定②）：入口不能比页头按钮更小
  assert.match(html, /class="wh5-entry"/, '入口必须带 wh5-entry 类（尺寸由 styles.css 统一给）')
})

test('🔴 红证：锚点被包进 HTML 注释 ⇒ 同一判定必红（注释里的链接不是入口）', () => {
  const html = renderPage({ ...initialState(), worker: WORKER, mode: 'scan' })
  const commented = html.replace(/(<a class="wh5-entry"[^>]*>[^<]*<\/a>)/g, '<!--$1-->')
  // 「变异真的被读到」的自证：变异体里锚点串**还在**（按"包含串"判的守卫照样绿）
  assert.ok(commented.includes(`href="${INBOUND_ENTRY}"`), '变异体里锚点串仍在')
  assert.ok(commented.includes('<!--<a class="wh5-entry"'), '变异体确实是"锚点被注释掉"这一形态')
  assert.deepEqual(entryProblemsInRendered(html), [], '对照：真渲染输出下本判定判绿')
  assert.notDeepEqual(entryProblemsInRendered(commented), [], '注释包裹后本判定必须判红')
})

test('入口出现在**每一个登录后视图**（页头是共用件：扫 / 选套 / 主屏都带它）', () => {
  const selecting = renderPage({
    ...initialState(),
    worker: WORKER,
    mode: 'select',
    view: { needs_selection: [{}], selections: [] },
  })
  assert.ok(selecting.includes(`href="${INBOUND_ENTRY}"`), '旧码选套屏丢了入口（工人此时同样需要入库）')
  const main = renderPage({
    ...initialState(),
    worker: WORKER,
    mode: 'main',
    view: { set_no: 1, position: { position_name: '布帘' }, operation: null },
  })
  assert.ok(main.includes(`href="${REPRINT_ENTRY}"`), '主屏丢了入口')
})

test('🔴 红证：`workerEntriesBar()` 定义但**调用被摘掉** ⇒ 判定必红（写了 ≠ 会被渲染）', () => {
  // 变异体在内存里构造：只把页头里那一处调用摘掉，函数与两个 href 都留着
  const html = renderPage({ ...initialState(), worker: WORKER, mode: 'scan' })
  const uncalled = html.replace(/<nav class="wh5-entries"[\s\S]*?<\/nav>/, '')
  assert.ok(uncalled.includes('wh5-header'), '对照：页头本身还在（摘掉的只是入口区）')
  assert.deepEqual(entryProblemsInRendered(html), [], '对照：真渲染输出下本判定判绿')
  assert.notDeepEqual(entryProblemsInRendered(uncalled), [], '入口区没了 ⇒ 本判定必须判红')
})

test('🔴 未登录（login 屏）不出现入口 —— 身份未确立时不给"下一跳"的假承诺', () => {
  const html = renderPage(initialState())
  assert.ok(!html.includes('/b/#/pages/worker/'), '登录屏不该出现工人面入口（页头是登录后才有的）')
  // 但登录屏本身仍然可用（不是把整页弄没了）
  assert.match(html, /id="wh5-login"/, '登录入口必须还在')
})

test('跨应用前缀就是 Taro h5 的 hash 路由形态（`/b/#` + 页面路由）', () => {
  // 前缀写死会让"换成 history 路由 / 换静态根"变成静默失效 ⇒ 这里明写它的语义，
  // 并把「路由段 == bmini 登记路由」的另一半钉在
  // frontend/bmini-app/tests/page-entry-reachability.test.ts 的 L5（改一边不改另一边 ⇒ 红）
  for (const href of [INBOUND_ENTRY, REPRINT_ENTRY]) {
    assert.match(href, /^\/b\/#\/pages\/worker\/[a-z]+\/index$/, `入口形态不是 /b/#<页面路由>：${href}`)
  }
})
