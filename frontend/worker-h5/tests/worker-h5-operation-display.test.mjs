// case_ids: PG-018, BM-006
//
// 工人端 H5 报工页 —— **工序显示名统一口径**（issue #4963）。
//
// 病根（实测）：`src/render.mjs` 自拼 `${op.logical_name} · ${op.position ?? 部位名}`，
// 与 admin-web 的唯一口径 `frontend/admin-web/src/lib/operation-display.ts` 在三种输入下渲染不同：
//   ① 缺 `logical_name` ⇒ 只显示部位（如「布帘」）而不是退回快照名原文；
//   ② 键值带空白不 trim；
//   ③ 全缺 ⇒ 拼出一个孤零零的 ` · ` 分隔符（web 给空串）。
// 另有一处**独立缺陷**：`doneNotice` 的「下一道：」只拼 `logical_name` ⇒ **丢部位**
// （`打卷 · 布帘` 显示成 `打卷`），而回执的 `next_operation` 本来就带 `position`。
//
// 判据：本文件直接**执行**共享模块 `frontend/shared/operation-display.mjs`（worker-h5 的
// `render.mjs` import 的就是它）+ 端到端断言渲染出来的 HTML。

import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { operationDisplayName } from '../../shared/operation-display.mjs'
import { doneNotice, initialState, reduce, renderPage } from '../src/render.mjs'

/** 一屏（主屏）夹具：布帘的「定型」，部位由 `position` 给出。 */
const CLOTH_VIEW = {
  granularity: 'set_position',
  order_id: 'o-1',
  processing_order_no: 'JG20260920001',
  set_no: 14,
  set_index: 13,
  position: { order_item_id: 'oi-cloth', position_kind: '布帘', position_name: '布帘' },
  operation: { operation_id: 'op-cloth', logical_name: '定型', position: '布帘', unit: '米', qty: 11, unit_price: 3.5 },
  alternatives: [
    { operation_id: 'op-cloth-2', logical_name: '打卷', position: '布帘', seq: 2, qty: 11, unit: '米' },
  ],
  set_progress: { total: 3, done: 1, percent: 33 },
  completed: false,
  needs_selection: [],
}

const loggedIn = () =>
  reduce(initialState(), { type: 'worker', worker: { worker_name: '张三', worker_no: 'A017' } })

// ── ① 共享模块本身（唯一口径的边界三条）─────────────────────────────────────

test('共享模块 operationDisplayName：逻辑名 · 部位 / 缺键退回快照名 / trim / 全缺给空串', () => {
  assert.equal(
    operationDisplayName({ operation: '精裁-布', logical_name: '精裁', position: '布帘' }),
    '精裁 · 布帘',
    '有逻辑名 + 部位 ⇒ 「逻辑名 · 部位」',
  )
  assert.equal(
    operationDisplayName({ operation: '外帘装袋', logical_name: '外帘装袋' }),
    '外帘装袋',
    '部位无关工序 ⇒ 只显示逻辑名（不拼孤立的 ` · `）',
  )
  assert.equal(
    operationDisplayName({ operation: '定型-布' }),
    '定型-布',
    '缺 logical_name（老数据）⇒ 退回快照名原文（**不显示空白**、不编占位名）',
  )
  assert.equal(operationDisplayName({}), '', '两个键都缺 ⇒ 空串（调用方按空态渲染）')
  assert.equal(operationDisplayName(null), '', 'null ⇒ 空串（不抛）')
  assert.equal(
    operationDisplayName({ operation: 'x', logical_name: ' 精裁 ', position: ' 布帘 ' }),
    '精裁 · 布帘',
    '键值带空白必须 trim（改前不 trim ⇒ 原样上屏）',
  )
})

// ── ② 一屏渲染：显示名带部位（红证：改前不 trim / 缺逻辑名只显示部位）────────

test('一屏：工序显示名 = 「逻辑名 · 部位」（不得直接拼 logical_name + position）', () => {
  const html = renderPage(loggedIn(), CLOTH_VIEW)
  assert.match(html, /id="wh5-operation">定型 · 布帘</, '一屏工序必须显示「逻辑名 · 部位」')
  // 缺 `position` 时**不得**拼出孤立的 ` · `（改前是 `${logical_name} · ${position ?? 部位名}`，
  // 两者都缺 ⇒ 屏上出现 `定型 · `）
  const noPosition = renderPage(loggedIn(), { ...CLOTH_VIEW, operation: { ...CLOTH_VIEW.operation, position: null } })
  assert.match(noPosition, /id="wh5-operation">定型</, '缺 position ⇒ 只显示逻辑名')
  assert.ok(!/id="wh5-operation">定型 · </.test(noPosition), '缺 position 不得拼出孤立的 ` · `')
})

test('一屏：缺 logical_name（老数据）⇒ 退回快照名原文，不显示部位、不显示空白', () => {
  const html = renderPage(loggedIn(), {
    ...CLOTH_VIEW,
    operation: { operation_id: 'op-x', operation: '定型-布', unit: '米', qty: 11 },
  })
  assert.match(html, /id="wh5-operation">定型-布</, '缺 logical_name ⇒ 退回快照名原文')
})

test('「不是这道？」备选按钮：只显示逻辑名（部位已由同屏「第 N 套 · 部位」给出）', () => {
  // 为什么备选按钮**不**拼 `· 部位`（与主屏不同口径，是有意的）：
  //   ① 备选恒与本次扫码**同一部位**（服务端 422 跨部位），逐条重复部位是噪声；
  //   ② 本页假 DOM 的标签扫描器对文本节点里的 ` · ` 会截断（`.wh5-alt` 的 data-operation-id
  //      读成 `op-cloth-2"` ⇒ 一键改把工序 id 拼坏）。生产浏览器不受影响，但为了不把
  //      测试基础设施的坑带进判据，备选保持逻辑名（与改前逐字一致）。
  const html = renderPage(loggedIn(), CLOTH_VIEW)
  assert.match(html, /data-operation-id="op-cloth-2"[^>]*>打卷</, '备选按钮显示逻辑名')
  assert.match(html, /id="wh5-set">第 14 套 · 布帘</, '部位由同屏「第 N 套 · 部位」给出')
})

// ── ③ 「下一道」丢部位（独立缺陷，issue #4963）─────────────────────────────

test('🔴 回执「下一道」必须带部位（改前只拼 logical_name ⇒ 丢部位）', () => {
  // ⚠️ 文案语义 = 「已领活」（扫码 = 开工/领活，issue #4967 用户逐字裁定）—— 本单只补部位，
  // **不得**改回「已报工」（那会静默回退已合并的 #4967）。
  assert.equal(
    doneNotice({ nextOperation: { operation_id: 'op-2', logical_name: '打卷', position: '布帘' } }),
    '已领活 · 下一道：打卷 · 布帘',
    '跨部位时「下一道」缺部位 = 屏上少一半信息（回执本来就带 position）',
  )
  // 部位无关的下一道 ⇒ 不拼孤立的 ` · `
  assert.equal(
    doneNotice({ nextOperation: { operation_id: 'op-3', logical_name: '外帘装袋' } }),
    '已领活 · 下一道：外帘装袋',
  )
  // 回执没给下一道（推断失败）⇒ 保持既有兜底文案，不编工序名
  assert.equal(doneNotice({}), '已领活')
  assert.equal(doneNotice({ setCompleted: true }), '已领活 · 本套工序都领完了 🎉')
})

// ── ④ 反空跑锚点：render.mjs 必须**引用**共享模块（不许自拼一份回来）─────────

test('render.mjs 引用共享模块（自拼一份回来 ⇒ 本判据必红）', () => {
  const src = readFileSync(fileURLToPath(new URL('../src/render.mjs', import.meta.url)), 'utf8')
  assert.match(
    src,
    /from '\.\.\/\.\.\/shared\/operation-display\.mjs'/,
    '工序显示名必须 import 共享模块（各拼一份必然漂移，而漂移的那一份不会变红）',
  )
  // 红证形态：自拼 `${...logical_name} · ${...position...}` 会命中这条
  assert.ok(
    !/\$\{[^}]*\.logical_name\}\s*·\s*\$\{/.test(src),
    'render.mjs 里不得再自拼「逻辑名 · 部位」（改回自拼 ⇒ 与 web 面口径漂移）',
  )
})
