// case_ids: PG-096
//
// 工人档案绑定一道工序 ⇒ 扫码后**自动选中**这道（issue #7749，用户 2026-10-25 逐字：
// 「工人要允许绑定一个工序，一个工人对应一个工序……工人扫码后直接报工，通过工人自动选择工序」）。
//
// 🔴 本文件钉四条（每条能单独变红）：
//   ① 有 `worker_operation` + 服务端选中 ⇒ 屏上出「你的工序：X」，**不出**工序选择器
//      （即使服务端误带了 alternatives —— 双保险：不让绑定工人改报别人的活）；
//   ② 有 `worker_operation` 但本件没有这道（`worker_operation_state=absent`）⇒ 说明「没有这道工序，不用报工」，
//      **不出**报工按钮；
//   ③ 有 `worker_operation` 且这道已做完（`done`）⇒ 说明「已经做完」；
//   ④ 未绑定（无该键）⇒ 行为与改前**逐字一致**：选择器照旧、不出现「你的工序」一行。
//
// 服务端选工序的真判据在 backend/admin-api 的 `ProductionScanServiceTest`（#7749 三条用例）；
// 本文件只判**渲染**（零 DOM、零网络）。

import test from 'node:test'
import assert from 'node:assert/strict'

import { initialState, reduce, renderPage } from '../src/render.mjs'

const WORKER = { workerName: '张师傅', workerNo: 'W-001', idleMinutes: 43200 }

const OP = { operation_id: 'op-2', logical_name: '韩褶', qty: 11, unit: '米', unit_price: 3.5 }

function view(extra = {}) {
  return {
    set_no: 1,
    position: { order_item_id: 'item-1', position_name: '布艺遮光帘A 米白' },
    completed: false,
    ...extra,
  }
}

function open(v) {
  let s = reduce(initialState(), { type: 'worker', worker: WORKER })
  s = reduce(s, { type: 'pages', pages: ['report'] })
  return reduce(s, { type: 'resolved', view: v })
}

test('① 绑定工人被服务端选中他的一道 ⇒ 出「你的工序」、不出选择器（即使服务端带了 alternatives）', () => {
  const html = renderPage(open(view({
    operation: { ...OP, determined_by: 'worker' },
    worker_operation: '韩褶',
    // 服务端按理不会给替代项；这里故意塞进去，验证端侧**也不**渲染选择器（双保险）
    alternatives: [{ operation_id: 'op-3', logical_name: '定型' }],
  })))
  assert.match(html, /id="wh5-worker-operation"[^>]*>你的工序：韩褶/)
  assert.equal(html.includes('id="wh5-op-picker"'), false)
  assert.match(html, /id="wh5-operation"[^>]*>韩褶/)
  assert.match(html, /id="wh5-report"[^>]*>报 工/)
})

test('② 绑定工人 + 本件没有这道（absent）⇒ 如实说明「没有这道工序，不用报工」，不出报工按钮', () => {
  const html = renderPage(open(view({
    operation: null,
    worker_operation: '打孔',
    worker_operation_state: 'absent',
    alternatives: [],
  })))
  assert.match(html, /id="wh5-no-operation"[^>]*>你的工序是「打孔」：本件没有这道工序，不用报工。/)
  assert.equal(html.includes('id="wh5-report"'), false)
  assert.equal(html.includes('id="wh5-op-picker"'), false)
  // 不能谎报「本套都报完了」
  assert.equal(html.includes('id="wh5-completed"'), false)
})

test('③ 绑定工人 + 这道已做完（done）⇒ 说明「已经做完」', () => {
  const html = renderPage(open(view({
    operation: null,
    worker_operation: '打孔',
    worker_operation_state: 'done',
    alternatives: [],
  })))
  assert.match(html, /id="wh5-no-operation"[^>]*>你的工序是「打孔」：本件的这道已经做完，不用报工。/)
  assert.equal(html.includes('id="wh5-report"'), false)
})

test('④ 对照：未绑定的工人 ⇒ 选择器照旧、且不出现「你的工序」一行（零回归）', () => {
  const html = renderPage(open(view({
    operation: { ...OP, determined_by: 'inferred' },
    alternatives: [{ operation_id: 'op-3', logical_name: '定型' }],
  })))
  assert.match(html, /id="wh5-op-picker"/)
  assert.match(html, /data-operation-id="op-3"/)
  assert.equal(html.includes('id="wh5-worker-operation"'), false)
})
