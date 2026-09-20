// case_ids: PG-018, BM-006, DF-017
//
// 工人端 H5 报工页 —— **旧码降级不默认取第 1 套**（设计 #4716 §1.5 / W9；#4687 §2.6）。
//
// 🔴 本文件是「绝不默认取第 1 套」这条红线的**唯一**机械判据：
//   红证形态 = 让前端在 `granularity === 'order'` 时自己挑第一套（`selections[0]`）⇒ 本文件必红。
//
// 口径（逐字继承 #4687 §2.6）：旧码命中 ⇒ 服务端返回 `granularity:"order"` +
// `needs_selection:["set","position"]`，`set_no`/`position`/`operation` 一律 null（**不知道就是不知道**）。
// 页面必须**强制选套 + 选部位**，且**未选定前不得显示任何工序、不得可报工**。
import test from 'node:test'
import assert from 'node:assert/strict'

import { initialState, reduce, renderPage } from '../src/render.mjs'
import { createApi } from '../src/api.mjs'

/** 已登录态（未登录时 renderPage 一律回登录页 —— 那是正确行为，不是被测量的东西）。 */
const workerLoggedIn = () => reduce(initialState(), { type: 'worker', worker: { workerName: '张三', workerNo: 'A017' } })

/** 服务端旧码降级形态（逐字照 ProductionScanService.degradedView 的键）。 */
const DEGRADED = {
  granularity: 'order',
  order_id: 'o-1',
  processing_order_no: 'JG20260920001',
  set_no: null,
  set_index: null,
  position: null,
  operation: null,
  alternatives: [],
  set_progress: null,
  completed: null,
  completed_at: null,
  needs_selection: ['set', 'position'],
  selections: [
    { set_id: 'set-1', set_no: 1, set_index: 0, positions: [{ order_item_id: 'oi-1', position_name: '布帘' }] },
    { set_id: 'set-2', set_no: 2, set_index: 1, positions: [{ order_item_id: 'oi-2', position_name: '纱帘' }] },
  ],
}

test('🔴 旧码 ⇒ 进「选套/选部位」态，且**绝不默认第 1 套**', () => {
  const s = reduce(workerLoggedIn(), { type: 'resolved', view: DEGRADED })

  assert.equal(s.mode, 'select', '旧码必须进 select 态（不是 main）')
  assert.equal(s.selection.setId, null, '🔴 未选之前 setId 必须是 null —— 默认取第 1 套就是本单要治的病')
  assert.equal(s.selection.orderItemId, null, '🔴 未选之前 orderItemId 必须是 null')
  assert.equal(s.view.set_no, null, '服务端判不出套 ⇒ 页面不得自己填一个')

  const html = renderPage(s, DEGRADED)
  assert.ok(!/第\s*1\s*套\s*·/.test(html), '🔴 降级页不得出现「第 1 套 · 部位」这种默认结论')
  assert.ok(!/【\s*完\s*成\s*】|id="wh5-report"/.test(html), '🔴 未选定套/部位前不得出现报工按钮')
  assert.match(html, /选套/, '必须有显式选套入口')
  assert.match(html, /第 1 套/, '第 1 套只能作为**候选**出现（不是默认选中）')
  assert.match(html, /第 2 套/)
  // 🔴 部位按钮**只在选了套之后**才出现 —— 两跳都是工人的显式动作（不替工人猜）
  assert.ok(!html.includes('data-order-item-id'), '未选套之前不得出现部位按钮')
  const afterSet = renderPage(reduce(s, { type: 'pickSet', setId: 'set-1', setNo: 1 }), DEGRADED)
  assert.match(afterSet, /布帘/, '选了第 1 套 ⇒ 出现该套的部位')
  assert.ok(!/纱帘/.test(afterSet), '不得把别的套的部位混进来')
})

test('旧码：选定套 + 部位后进入可报工态（两跳都是工人显式动作）', () => {
  let s = reduce(workerLoggedIn(), { type: 'resolved', view: DEGRADED })
  s = reduce(s, { type: 'pickSet', setId: 'set-2' })
  assert.equal(s.selection.orderItemId, null, '选了套还没选部位 ⇒ 仍不可报工')
  s = reduce(s, { type: 'pickPosition', orderItemId: 'oi-2' })

  assert.equal(s.selection.setId, 'set-2')
  assert.equal(s.selection.orderItemId, 'oi-2')
  assert.match(s.notice ?? '', /第\s*2\s*套|纱帘/, '选定后必须显式告诉工人选了什么（不静默）')
})

test('🔴 工序未确定（operation 为空）⇒ 不得报工（防呆⑤：绝不允许工序未确定就记账）', () => {
  const s = reduce(workerLoggedIn(), { type: 'resolved', view: DEGRADED })
  assert.equal(s.view.operation, null)
  assert.ok(!/id="wh5-report"/.test(renderPage(s, DEGRADED)), '工序未确定不得出现报工按钮')
})

test('🔴 未登录时即使有解析结果也不得出现报工按钮（未登录不能报工）', () => {
  const s = reduce(initialState(), {
    type: 'resolved',
    view: {
      granularity: 'set_position', set_no: 3, position: { position_name: '布帘' },
      operation: { operation_id: 'op-1', logical_name: '定型', qty: 5, unit: '米' },
      alternatives: [], needs_selection: [], completed: false,
    },
  })
  assert.equal(s.worker, null)
  assert.ok(!/id="wh5-report"/.test(renderPage(s, s.view)), '未登录不得出现报工按钮')
})

test('🔴 未登录 + 有解析结果 ⇒ completeByScan() 仍被拒（页面闸不是唯一闸）', async () => {
  const calls = []
  const api = createApi({
    fetchImpl: async (url) => { calls.push(url); return { ok: true, status: 200, json: async () => ({ success: true, data: {} }) } },
    storage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
    baseUrl: '',
  })
  await assert.rejects(() => api.completeByScan({ token: 'tok-1' }), /登录/)
  assert.equal(calls.length, 0)
})

test('旧码：完成态为 null（未知）⇒ 页面不得显示「已完成」也不得显示「未完成」', () => {
  const s = reduce(workerLoggedIn(), { type: 'resolved', view: DEGRADED })
  const html = renderPage(s, DEGRADED)
  assert.ok(!/本套已完成/.test(html), 'completed=null（未知）不得渲染成「已完成」')
})
