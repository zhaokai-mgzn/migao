// case_ids: PG-098
//
// 工人端**报返工**区块（issue #7860，用户 2026-10-26 裁定）。
//
// 用户逐字：
//   「质检不能绑定死打包工序，需要允许任一工序工人报返工，另外需要在工人手机端展示报返工的加工单列表」
//   「报返工的那个工序不能计件的，只报返工，生成返工单，pc端的 返工单列表要能看到这次的返工数据」
//   追问「刚自动记的那一笔怎么处理」⇒ 选「把刚自动记的那一笔改记为返工（回退进度与计件）」。
//
// 🔴 本文件钉五条（每条能单独变红）：
//   ① **不按页面键门控**：档案只有默认页（无 `rework` / 无 `inspect`）也出返工区块 —— 任一工序工人都能报；
//   ② 定位不到「一件」⇒ 整块不渲染（没有件 = 没有可改记的账，不摆空壳）；
//   ③ 表单只有一个动作（提交返工 / 取消）+ 问题说明必填；整块**不出现**「合格」；
//   ④ 提交中 ⇒ 按钮禁用 + 文案「提交中…」；
//   ⑤ 提交成功 ⇒ 返工单号 / 工序上屏 + 明说「已改记为返工，不计件」，表单收起、入口仍在页头动作栏。
//
// 边界：真栈改记（回退 done_qty / 生成返工单 / 403 页面键）由后端
// `ProductionReworkServiceTest` + `WorkerReworkEndpointsTest` 钉住；本文件只判**渲染与状态机**（零 DOM、零网络）。

import test from 'node:test'
import assert from 'node:assert/strict'

import {
  initialState,
  PAGE_INSPECT,
  PAGE_REPORT,
  PAGE_REWORK,
  reduce,
  renderPage,
} from '../src/render.mjs'

const WORKER = { workerName: '张师傅', workerNo: 'W-001', idleMinutes: 43200 }

const VIEW = {
  set_no: 1,
  position: { order_item_id: 'item-1', position_name: '布艺遮光帘A 米白' },
  operation: { operation_id: 'op-1', logical_name: '车缝', qty: 2, unit: '套', unit_price: 1.5 },
  completed: false,
}

/** 登录 + 页面集 + 解析结果（只在编排层之上判渲染）。 */
function open(pages = [PAGE_REPORT], view = VIEW) {
  let s = reduce(initialState(), { type: 'worker', worker: WORKER })
  s = reduce(s, { type: 'pages', pages })
  return reduce(s, { type: 'resolved', view })
}

test('① 档案只有默认页（没有 rework / inspect）⇒ 返工区块照样出现（任一工序工人可报）', () => {
  const html = renderPage(open([PAGE_REPORT]))
  assert.match(html, /id="wh5-rework"/)
  // 2026-10-27 上移：入口在页头动作栏（工人不用滑到底部找按钮）
  assert.match(html, /id="wh5-worker-entries"[\s\S]*id="wh5-rework-action"[^>]*>报返工</)
  // 对照：同一份页面集下质检区块**不**出现（它逐人开，与返工不是一把尺子）
  assert.doesNotMatch(html, /id="wh5-quality"/)
})

test('② 定位不到「一件」⇒ 返工区块整块不渲染（不摆空壳）', () => {
  const noItem = { ...VIEW, position: { position_name: '布艺遮光帘A 米白' } }
  const html = renderPage(open([PAGE_REPORT], noItem))
  assert.doesNotMatch(html, /id="wh5-rework"/)
  assert.doesNotMatch(html, /id="wh5-rework-action"/)
})

test('③ 展开表单 ⇒ 只有「提交返工 / 取消」+ 问题说明必填；不出现「合格」', () => {
  const html = renderPage(reduce(open([PAGE_REPORT]), { type: 'reworkFormOpen' }))
  assert.match(html, /id="wh5-rework-form"/)
  assert.match(html, /id="wh5-rework-reason"/)
  assert.match(html, /问题说明（必填）/)
  assert.match(html, /id="wh5-rework-submit"[^>]*>提交返工</)
  assert.match(html, /id="wh5-rework-cancel"/)
  // 返工不是质检：整块不出现「合格」这个动作/状态（issue #7749 的口径）
  assert.doesNotMatch(html, /合格/)
})

test('④ 提交中 ⇒ 两个按钮都禁用 + 文案「提交中…」', () => {
  const s = reduce(reduce(open([PAGE_REPORT]), { type: 'reworkFormOpen' }), { type: 'reworkSubmitting' })
  const html = renderPage(s)
  assert.match(html, /id="wh5-rework-submit"[^>]*disabled[^>]*>提交中…</)
  assert.match(html, /id="wh5-rework-cancel"[^>]*disabled/)
})

test('⑤ 提交成功 ⇒ 返工单号 + 工序上屏 + 「不计件」说明；表单收起、入口仍在页头动作栏', () => {
  const s = reduce(open([PAGE_REPORT]), {
    type: 'reworkSubmitted',
    rework: { reworkNo: 'RG202610260001', operationName: '车缝', qty: 2 },
    notice: '返工单 RG202610260001 已生成',
  })
  const html = renderPage(s)
  assert.match(html, /id="wh5-rework-done"[^>]*>[^<]*返工单 RG202610260001 已生成[^<]*工序 车缝/)
  assert.match(html, /已改记为返工，不计件/)
  assert.doesNotMatch(html, /id="wh5-rework-form"/)
  assert.match(html, /id="wh5-notice"[^>]*>返工单 RG202610260001 已生成/)
})

test('⑥ 返工记录入口：档案开了 rework ⇒ 有真链接；没开 ⇒ 不出现（逐人开）', () => {
  const opened = renderPage(open([PAGE_REPORT, PAGE_REWORK]))
  assert.match(opened, /id="wh5-rework-entry"[^>]*href="\.\/rework.html"[^>]*>返工记录</)
  const closed = renderPage(open([PAGE_REPORT, PAGE_INSPECT]))
  assert.doesNotMatch(closed, /id="wh5-rework-entry"/)
})
