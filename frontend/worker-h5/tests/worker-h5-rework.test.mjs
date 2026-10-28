// case_ids: PG-098
//
// 工人端**返工记录 + 件级闭环**（issue #7860 起；2026-10-28 issue #7973 改判）。
//
// 用户逐字（2026-10-28）：
//   「报返工的操作记录没有体现在扫码报工页面上？」
//   「当前的返工（布料）那个区域的文案看的人云里雾里，改成显示返工记录」
//   「报了返工单后仍然能继续报返工…需要和返工单记录进行逻辑闭环」
//
// 🔴 本文件钉六条（每条能单独变红）：
//   ① 不按页面键门控：只有默认页（无 `rework` / 无 `inspect`）也出返工记录块（任一工序工人可报）；
//   ② 定位不到一件 / 旧后端没有 `rework_records` ⇒ 整块不渲染（不摆空壳、也不谎报「没有返工」）；
//   ③ 记录逐条上屏（工序×数量 / 时间 / 原因 / 单号·报工人·状态）；旧的整段说明文案不再出现；
//   ④ 空记录 ⇒ 一行空态（不是错误态）；
//   ⑤ 有未完结返工单（draft / in_progress）⇒ 页头收起【报返工】、改摆「返工处理中」，记录卡说
//      「处理完后才能再报」；已完结 / 已取消 ⇒ 入口恢复（闭环的出口）；
//   ⑥ 提交返工 ⇒ 表单收起、记录来自**重解析后的服务端视图**（不再消费一次性回执）。
//
// 边界：真栈改记 / 409 门禁由后端 `ProductionReworkServiceTest` 钉住；本文件只判**渲染与状态机**
// （零 DOM、零网络）。

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
  set_no: 'JG-20261028-0001-001',
  position: { order_item_id: 'item-1', position_name: '布艺遮光帘A 米白' },
  operation: { operation_id: 'op-1', logical_name: '车缝', qty: 2, unit: '套', unit_price: 1.5 },
  completed: false,
  rework_records: [],
}

/** 一条未完结的返工记录（服务端 `pieceRecords` 的形状）。 */
const OPEN = {
  rework_no: 'RG202610280002',
  logical_name: '布带',
  operation_name: '布带-布',
  qty: 2,
  reason: '布面污渍',
  status: 'draft',
  worker_name: '张师傅',
  created_at: '2026-10-28T09:15:00+08:00',
  position_name: '布艺遮光帘A 米白',
}

/** 一条已完成的返工记录。 */
const DONE = { ...OPEN, rework_no: 'RG202610280001', reason: '色差', status: 'done' }

/** 登录 + 页面集 + 解析结果（只在编排层之上判渲染）。 */
function open(pages = [PAGE_REPORT], view = VIEW) {
  let s = reduce(initialState(), { type: 'worker', worker: WORKER })
  s = reduce(s, { type: 'pages', pages })
  return reduce(s, { type: 'resolved', view })
}

test('① 档案只有默认页（没有 rework / inspect）⇒ 返工记录块照样出现（任一工序工人可报）', () => {
  const html = renderPage(open([PAGE_REPORT]))
  assert.match(html, /id="wh5-rework"/)
  // 空记录 = 一行空态（不是错误态，也不是整段说明）
  assert.match(html, /id="wh5-rework-empty"[^>]*>本件没有返工记录 · 布料\/来料有问题点页头「报返工」/)
  // 2026-10-27 上移：入口在页头动作栏（工人不用滑到底部找按钮）
  assert.match(html, /id="wh5-worker-entries"[\s\S]*id="wh5-rework-action"[^>]*>报返工</)
  // 对照：同一份页面集下质检区块**不**出现（它逐人开，与返工不是一把尺子）
  assert.doesNotMatch(html, /id="wh5-quality"/)
})

test('② 定位不到一件 / 旧后端没有 `rework_records` ⇒ 整块不渲染（不摆空壳、不谎报没有返工）', () => {
  // 没有件 ⇒ 没有件级记录，也没有可改记的账
  const noItem = { ...VIEW, position: { position_name: '布艺遮光帘A 米白' } }
  const html = renderPage(open([PAGE_REPORT], noItem))
  assert.doesNotMatch(html, /id="wh5-rework"/)
  assert.doesNotMatch(html, /id="wh5-rework-action"/)

  // 有件、但服务端没给 `rework_records`（旧后端 / 服务未接线）⇒ 不摆空壳（也不说「没有返工」）
  const { rework_records: _omit, ...oldBackend } = VIEW
  const noKey = renderPage(open([PAGE_REPORT], oldBackend))
  assert.doesNotMatch(noKey, /id="wh5-rework"/)
  assert.doesNotMatch(noKey, /本件没有返工记录/)
  // 入口仍在：入口只由「定位到件 + 没有未完结单」决定
  assert.match(noKey, /id="wh5-rework-action"/)
})

test('③ 记录逐条上屏：工序×数量 / 时间 / 原因 / 单号·报工人·状态；旧说明段落不再出现', () => {
  const html = renderPage(open([PAGE_REPORT], { ...VIEW, rework_records: [OPEN, DONE] }))
  assert.match(html, /id="wh5-rework-records"/)
  // 逐条：两道记录一个都不许少
  assert.match(html, /布带 ×2/)
  assert.match(html, /2026-10-28 09:15/)
  assert.match(html, /布面污渍/)
  assert.match(html, /返工单 RG202610280002 · 张师傅 · 待处理/)
  assert.match(html, /返工单 RG202610280001 · 张师傅 · 已完成/)
  // 空态不出现（有记录）
  assert.doesNotMatch(html, /id="wh5-rework-empty"/)
  // 🔴 用户逐字「文案看的人云里雾里」：整段说明已撤（记录替代它）
  assert.doesNotMatch(html, /布料\/来料有问题就报返工/)
  assert.doesNotMatch(html, /做工问题请走「质检」/)
})

test('④ 空记录 ⇒ 一行空态 + 入口可用（不是错误态、不摆死按钮）', () => {
  const html = renderPage(open([PAGE_REPORT], { ...VIEW, rework_records: [] }))
  assert.match(html, /id="wh5-rework-empty"/)
  assert.doesNotMatch(html, /wh5-record"/)
  assert.match(html, /id="wh5-rework-action"/)
})

test('⑤ 未完结返工单 ⇒ 入口收起 + 记录卡说「处理完后才能再报」；已完结/已取消 ⇒ 入口恢复', () => {
  const openHtml = renderPage(open([PAGE_REPORT], { ...VIEW, rework_records: [OPEN] }))
  // 不摆可点按钮（点也点不进去），改一句状态
  assert.doesNotMatch(openHtml, /id="wh5-rework-action"/)
  assert.match(openHtml, /id="wh5-rework-blocked"[^>]*aria-disabled="true"[^>]*>返工处理中</)
  assert.match(openHtml, /id="wh5-rework-state"[^>]*>待处理</)
  assert.match(openHtml, /id="wh5-rework-open"[^>]*>返工单 RG202610280002：处理完后才能再报/)
  // 处理中同样是「未完结」
  const inProgress = renderPage(open([PAGE_REPORT], { ...VIEW, rework_records: [{ ...OPEN, status: 'in_progress' }] }))
  assert.match(inProgress, /id="wh5-rework-state"[^>]*>处理中</)

  // 已完成 / 已取消 = 闭环出口 ⇒ 入口恢复（车间处理完/取消后工人能再报）
  for (const status of ['done', 'cancelled']) {
    const closed = renderPage(open([PAGE_REPORT], { ...VIEW, rework_records: [{ ...OPEN, status }] }))
    assert.match(closed, /id="wh5-rework-action"/, `${status} 后入口必须恢复`)
    assert.doesNotMatch(closed, /id="wh5-rework-blocked"/)
    assert.doesNotMatch(closed, /id="wh5-rework-state"/)
  }
})

test('⑥ 表单：只有提交返工 / 取消；提交中禁用；成功后表单收起、记录来自服务端视图', () => {
  const formOpen = reduce(open([PAGE_REPORT]), { type: 'reworkFormOpen' })
  const html = renderPage(formOpen)
  assert.match(html, /id="wh5-rework-form"/)
  assert.match(html, /id="wh5-rework-reason"/)
  assert.match(html, /问题说明（必填）/)
  assert.match(html, /id="wh5-rework-submit"[^>]*>提交返工</)
  assert.match(html, /id="wh5-rework-cancel"/)
  // 返工不是质检：整块不出现「合格」这个动作/状态
  assert.doesNotMatch(html, /合格/)

  const submitting = renderPage(reduce(formOpen, { type: 'reworkSubmitting' }))
  assert.match(submitting, /id="wh5-rework-submit"[^>]*disabled[^>]*>提交中…</)
  assert.match(submitting, /id="wh5-rework-cancel"[^>]*disabled/)

  const FRESH = { ...OPEN, rework_no: 'RG202610280003', reason: '缝线开裂' }
  const done = renderPage(reduce(formOpen, {
    type: 'reworkSubmitted',
    view: { ...VIEW, rework_records: [FRESH] },
    notice: '返工已登记',
  }))
  assert.doesNotMatch(done, /id="wh5-rework-form"/)
  assert.match(done, /id="wh5-notice"[^>]*>返工已登记/)
  // 回执不再单独渲染（记录就是回执）；新记录为未完结 ⇒ 入口已收起
  assert.doesNotMatch(done, /id="wh5-rework-done"/)
  assert.match(done, /id="wh5-rework-records"[\s\S]*RG202610280003/)
  assert.match(done, /id="wh5-rework-open"[^>]*>返工单 RG202610280003/)
  assert.doesNotMatch(done, /id="wh5-rework-action"/)
})

test('⑦ 返工记录入口（档案开了 rework）与块内记录互不影响：真链接仍在', () => {
  const opened = renderPage(open([PAGE_REPORT, PAGE_REWORK], { ...VIEW, rework_records: [OPEN] }))
  assert.match(opened, /id="wh5-rework-entry"[^>]*href="\.\/rework.html"[^>]*>返工记录</)
  // 未开 ⇒ 不出现（逐人开）
  const closed = renderPage(open([PAGE_REPORT, PAGE_INSPECT]))
  assert.doesNotMatch(closed, /id="wh5-rework-entry"/)
})
