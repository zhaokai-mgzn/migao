// case_ids: PG-082, PG-086, PG-099
//
// 工人端**质检记录 + 待复检闭环**（issue #7162 起；2026-10-28 issue #7973 改判）。
//
// 用户逐字（2026-10-28）：
//   「报了质检单后仍然能继续报…需要和返工单记录进行逻辑闭环，还有质检单也一样」
//   「按最佳实践来设计整个逻辑闭环和操作细节以及页面细节」
//
// 🔴 本文件钉七条（每条能单独变红）：
//   ① `inspect` ∉ 页面集 ⇒ 质检区块一个字节都不出现；页头也不出「质检」入口；
//   ② 有页面集、无记录 ⇒ 状态「正常」+ 空态一行 + 页头「质检」入口（默认合格、不摆「合格」按钮）；
//   ③ 记录逐条上屏（判定 / 时间 / 原因 / 检验人）；最新 = 返工 ⇒ 状态「待复检」，
//      页头「质检」入口收起，只给【复检通过】/【复检仍有问题】；
//   ④ 复检通过 ⇒ 提交中禁用 + 成功后状态回「正常」+ 通知；
//   ⑤ 普通「记返工」表单只有一个动作 + 问题说明必填（不出现「合格」/「报废」动作）；
//   ⑥ 复检仍有问题 ⇒ 同一个表单带 `recheck` 语义（文案「复检」、提交「提交复检」）；
//   ⑦ 读面失败 ⇒ 状态「未读到」+ 人话错误；**不**冒充「正常」，也不冒充「本件还没有质检记录」。
//
// 边界：真栈写入（403 / 409 待复检门禁 / 件级 set_no）由后端
// `WorkerQualityControllerTest` + `QualityCheckServiceTest` 钉住；本文件只判**渲染与状态机**。

import test from 'node:test'
import assert from 'node:assert/strict'

import {
  effectivePages,
  initialState,
  PAGE_INSPECT,
  PAGE_REPORT,
  reduce,
  renderPage,
} from '../src/render.mjs'

const WORKER = { workerName: '张师傅', workerNo: 'W-001', idleMinutes: 43200 }

const VIEW = {
  set_no: 'JG-20261028-0001-001',
  position: { order_item_id: 'item-1', position_name: '布艺遮光帘A 米白' },
  operation: { operation_id: 'op-1', logical_name: '裁剪', qty: 2, unit: '套', unit_price: 1.5 },
  completed: false,
  rework_records: [],
}

const PASS_RECORD = {
  result: 'pass',
  result_label: '合格',
  reason: null,
  inspector_name: '李质检',
  inspector_kind: 'worker',
  inspected_at: '2026-10-27T10:00:00+08:00',
}

const REWORK_RECORD = {
  result: 'rework',
  result_label: '返工',
  reason: '缝线开裂',
  inspector_name: '张师傅',
  inspector_kind: 'worker',
  inspected_at: '2026-10-28T09:20:00+08:00',
}

/** 登录 + 页面集 + 解析结果。 */
function open(pages = [PAGE_REPORT, PAGE_INSPECT], view = VIEW) {
  let s = reduce(initialState(), { type: 'worker', worker: WORKER })
  s = reduce(s, { type: 'pages', pages })
  return reduce(s, { type: 'resolved', view })
}

/** 读面返回（`records` 缺省为空）。 */
function loaded(latest = null, records = [], pages = [PAGE_REPORT, PAGE_INSPECT]) {
  return reduce(open(pages), { type: 'qualityLoaded', latest, records })
}

test('① 没开「质检」页 ⇒ 质检区块 / 入口一个字节都不出现（默认页不含 inspect）', () => {
  const html = renderPage(open([PAGE_REPORT]))
  assert.equal(html.includes('wh5-quality'), false)
  assert.equal(html.includes('id="wh5-quality-entry"'), false)
  assert.equal(effectivePages({ pages: [PAGE_REPORT] }).opened.has(PAGE_INSPECT), false)
})

test('② 开了「质检」页、无记录 ⇒ 状态「正常」+ 空态 + 页头入口（不出现「合格」）', () => {
  const html = renderPage(loaded(null, []))
  assert.match(html, /id="wh5-quality"/)
  assert.match(html, /id="wh5-quality-state"[^>]*>正常</)
  assert.match(html, /id="wh5-quality-empty"[^>]*>本件还没有质检记录（默认没问题；做工有问题才记）</)
  // 2026-10-27：入口上移到页头动作栏（只对开了 inspect 的工人可见）
  assert.match(html, /id="wh5-worker-entries"[\s\S]*id="wh5-quality-entry"[^>]*>质检</)
  // 🔴 用户逐字「质检不要显示合格」：整块（含状态/按钮/说明）不得出现「合格」**字样**
  const block = html.slice(html.indexOf('id="wh5-quality"'))
  assert.equal(block.includes('合格'), false)
})

test('③ 记录逐条上屏；最新 = 返工 ⇒ 「待复检」+ 页头入口收起 + 两个复检动作', () => {
  const html = renderPage(loaded(REWORK_RECORD, [REWORK_RECORD, PASS_RECORD]))
  // 记录：最新在前，逐条给判定 / 时间 / 原因 / 检验人
  assert.match(html, /id="wh5-quality-records"[\s\S]*已记做工返工/)
  assert.match(html, /2026-10-28 09:20/)
  assert.match(html, /缝线开裂/)
  assert.match(html, /检验人 张师傅/)
  assert.match(html, /2026-10-27 10:00/)
  assert.match(html, /检验人 李质检/)
  // 状态 = 待复检（不是「已记」就完事：下一步必须复检）
  assert.match(html, /id="wh5-quality-state"[^>]*>待复检</)
  assert.match(html, /id="wh5-quality-pending"[^>]*>已记做工返工：返工做好后在这里复检/)
  // 页头入口收起（动作在记录卡里：通过 / 仍有问题）
  assert.doesNotMatch(html, /id="wh5-quality-entry"/)
  assert.match(html, /id="wh5-quality-recheck-pass"[^>]*>复检通过</)
  assert.match(html, /id="wh5-quality-recheck-open"[^>]*>复检仍有问题</)
  // 待复检时不再给普通「记返工」表单入口
  assert.doesNotMatch(html, /id="wh5-quality-form"/)
  // 仍然不出现「合格」这个动作/状态
  assert.equal(html.slice(html.indexOf('id="wh5-quality"')).includes('合格'), false)
})

test('④ 复检通过：提交中两个按钮禁用；成功后状态回「正常」+ 通知（闭环出口）', () => {
  const pending = loaded(REWORK_RECORD, [REWORK_RECORD])
  const submitting = renderPage(reduce(pending, { type: 'qualityRecheckStart' }))
  assert.match(submitting, /id="wh5-quality-recheck-pass"[^>]*disabled[^>]*>提交中…</)
  assert.match(submitting, /id="wh5-quality-recheck-open"[^>]*disabled/)

  const done = reduce(pending, {
    type: 'qualitySubmitted',
    latest: { ...PASS_RECORD, inspected_at: '2026-10-28T10:00:00+08:00' },
    notice: '复检通过：本件回到「正常」',
  })
  const html = renderPage(done)
  assert.match(html, /id="wh5-quality-state"[^>]*>正常</)
  assert.match(html, /id="wh5-notice"[^>]*>复检通过/)
  assert.doesNotMatch(html, /id="wh5-quality-recheck"/)
  // 闭环后页头入口恢复（可以记下一次问题）
  assert.match(html, /id="wh5-quality-entry"/)
})

test('⑤ 表单只有「返工 + 问题说明」；提交中禁用；成功 ⇒ 质检已登记 + 表单收起', () => {
  const formOpen = reduce(open(), { type: 'qualityFormOpen' })
  const html = renderPage(formOpen)
  assert.match(html, /id="wh5-quality-form"/)
  // 🔴 只提供一个返工选项：不再有 pass / scrap 的判定按钮
  assert.equal(html.includes('data-quality-result'), false)
  assert.match(html, /id="wh5-quality-hint"[^>]*>这次记为「做工返工」/)
  assert.match(html, /问题说明（必填）/)
  assert.match(html, /id="wh5-quality-submit"[^>]*>提交质检</)

  const submitting = renderPage(reduce(formOpen, { type: 'qualitySubmitting' }))
  assert.match(submitting, /id="wh5-quality-submit"[^>]*disabled[^>]*>提交中…</)

  const s = reduce(formOpen, { type: 'qualitySubmitted', latest: REWORK_RECORD, notice: '质检已登记' })
  const done = renderPage(s)
  assert.match(done, /id="wh5-notice"[^>]*>质检已登记/)
  assert.match(done, /id="wh5-quality-state"[^>]*>待复检</)
  assert.equal(done.includes('id="wh5-quality-form"'), false)
})

test('⑥ 复检仍有问题：同一个表单带 recheck 语义（文案「复检」、提交「提交复检」）', () => {
  const html = renderPage(reduce(open(), { type: 'qualityFormOpen', recheck: true }))
  assert.match(html, /id="wh5-quality-hint"[^>]*>这次复检记为「仍有问题」/)
  assert.match(html, /id="wh5-quality-submit"[^>]*>提交复检</)
  // 仍然只有一个动作 + 必填说明
  assert.equal(html.includes('data-quality-result'), false)
  assert.match(html, /问题说明（必填）/)
})

test('⑦ 读面失败 ⇒ 「未读到」+ 人话错误；不冒充「正常」，也不冒充「没有质检记录」', () => {
  const failed = reduce(open(), { type: 'qualityFailed', error: '质检状态读不到' })
  const html = renderPage(failed)
  assert.match(html, /id="wh5-quality-state"[^>]*>未读到</)
  assert.match(html, /id="wh5-quality-error"[^>]*>质检状态读不到/)
  assert.doesNotMatch(html, /id="wh5-quality-empty"/)
  // 读面失败时入口**保留**（fail-open：不知道有没有待复检，就让服务端 409 兜底，不把活挡死）
  assert.match(html, /id="wh5-quality-entry"/)
})

test('⑧ 服务端拒绝（表单内）⇒ 具名报错，不关表单、不丢已填说明', () => {
  let s = reduce(open(), { type: 'qualityFormOpen' })
  s = reduce(s, { type: 'qualityFormError', error: '这一件已记「做工返工」，正在等复检' })
  const html = renderPage(s)
  assert.match(html, /id="wh5-quality-form-error"[^>]*>这一件已记「做工返工」/)
  assert.match(html, /id="wh5-quality-form"/)
  assert.match(html, /id="wh5-quality-reason"/)
})

// ── issue #7186 / #7749：质检工序**没有报工动作**，默认没问题 ────────────────
//
// 用户 2026-10-18：「质检员不需要报工这个动作，只需要有一个质检动作」；
// 2026-10-25 追加：「这样也不需要质检按钮，尽量少一些动作，如果工序没有完成随时可以进入质检判定就好」
// ⇒ 当前工序 = 质检时，本屏**不得**出现报工按钮 / 报工三态；只有一句「默认没问题」的说明 +
// 可选的返工记录。服务端那条真闸（422）由 `ProductionReportQualityGuardTest` 钉住 —— 藏按钮**不是**授权。

function openWithOperation(operation, pages = [PAGE_REPORT, PAGE_INSPECT]) {
  let s = reduce(initialState(), { type: 'worker', worker: WORKER })
  s = reduce(s, { type: 'pages', pages })
  return reduce(s, {
    type: 'resolved',
    view: { ...VIEW, operation: { ...VIEW.operation, ...operation } },
  })
}

test('⑨ 当前工序 = 质检 ⇒ 不出报工按钮 / 报工三态，只说「默认没问题、有问题记返工」', () => {
  const html = renderPage(openWithOperation({ logical_name: '质检' }))
  assert.equal(html.includes('id="wh5-report"'), false)
  assert.equal(html.includes('id="wh5-work-type"'), false)
  assert.match(html, /id="wh5-quality-only"[^>]*>本道是质检工序：默认没问题/)
  // 质检区块仍在 —— 出问题时随时可记返工
  assert.match(html, /id="wh5-quality"/)
})

test('⑩ 对照：非质检工序 ⇒ 报工按钮照旧出现（守卫不得误伤）', () => {
  const html = renderPage(openWithOperation({ logical_name: '精裁' }))
  assert.match(html, /id="wh5-report"[^>]*>报 工</)
  assert.match(html, /id="wh5-work-type"/)
  assert.equal(html.includes('id="wh5-quality-only"'), false)
})

test('⑪ 质检工序 + 未开通「质检」页 ⇒ 无报工按钮，且如实说「要记返工需开通」', () => {
  const html = renderPage(openWithOperation({ logical_name: '质检' }, [PAGE_REPORT]))
  assert.equal(html.includes('id="wh5-report"'), false)
  assert.equal(html.includes('id="wh5-quality"'), false)
  assert.match(html, /id="wh5-quality-only"[^>]*>本道是质检工序：默认没问题；要记返工需开通「质检」页/)
})
