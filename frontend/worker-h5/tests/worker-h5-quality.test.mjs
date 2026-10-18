// case_ids: PG-082, PG-086
//
// 工人端**质检区块**（issue #7162）：扫水洗唛进报工页后录判定、生成质检单。
//
// 用户逐字（2026-10-17）：「工人不能进入观星台，维持这个设计，现在只需要在小程序端扫码进入报工页后
// 有入口进行质检即可」「因为工人主要通过扫水洗唛进入质检流程」「质检等同发货工序一样，打包发货完成后
// 生成发货单，质检完成后生成质检单，一样的意思」。
//
// 🔴 本文件钉四条（每条能单独变红）：
//   ① `inspect` ∉ 页面集 ⇒ **不渲染**质检区块（逐人开；默认页不含 inspect）；
//   ② `inspect` ∈ 页面集 ⇒ 出现「质检」区块：**未检**（🔴 不是「合格」）+「录入质检判定」按钮；
//   ③ 有记录 ⇒ 显示服务端判定 / 原因 / 检验人 / 时刻；未检不折成合格；
//   ④ 展开表单 ⇒ 三态 + 原因 +「提交质检单」；提交成功 ⇒「质检单已生成」+ 判定换成回执。
//
// 边界：真栈写入（403 / 原因必填 422 / 落库 inspector_kind）由后端
// `WorkerQualityControllerTest` + `QualityCheckServiceTest` 钉住；本文件只判**渲染与状态机**
// （零 DOM、零网络）。

import test from 'node:test'
import assert from 'node:assert/strict'

import {
  effectivePages,
  initialState,
  PAGE_INSPECT,
  PAGE_REPORT,
  QUALITY_RESULTS,
  reduce,
  renderPage,
} from '../src/render.mjs'

const WORKER = { workerName: '张师傅', workerNo: 'W-001', idleMinutes: 43200 }

const VIEW = {
  set_no: 1,
  position: { order_item_id: 'item-1', position_name: '布艺遮光帘A 米白' },
  operation: { operation_id: 'op-1', logical_name: '裁剪', qty: 2, unit: '套', unit_price: 1.5 },
  completed: false,
}

function open(pages = [PAGE_REPORT, PAGE_INSPECT]) {
  let s = reduce(initialState(), { type: 'worker', worker: WORKER })
  s = reduce(s, { type: 'pages', pages })
  return reduce(s, { type: 'resolved', view: VIEW })
}

test('① 没开「质检」页 ⇒ 质检区块一个字节都不出现（默认页不含 inspect）', () => {
  const html = renderPage(open([PAGE_REPORT]))
  assert.equal(html.includes('wh5-quality'), false)
  assert.equal(effectivePages({ pages: [PAGE_REPORT] }).opened.has(PAGE_INSPECT), false)
})

test('② 开了「质检」页 ⇒ 出现质检区块：未检（不是「合格」）+ 录入口', () => {
  const html = renderPage(open())
  assert.match(html, /id="wh5-quality"/)
  assert.match(html, /id="wh5-quality-state"[^>]*>未检</)
  assert.match(html, /id="wh5-quality-open"[^>]*>录入质检判定</)
  // 未检 ≠ 合格：这一屏在拿到记录前不得出现「合格」
  assert.equal(/id="wh5-quality-state"[^>]*>合格/.test(html), false)
})

test('③ 有记录 ⇒ 显示服务端判定 / 原因 / 检验人；反向：无记录时不得渲染成「合格」', () => {
  let s = open()
  s = reduce(s, {
    type: 'qualityLoaded',
    latest: {
      result: 'rework',
      result_label: '返工',
      reason: '缝线开裂',
      inspector_name: '张师傅',
      inspector_kind: 'worker',
      inspected_at: '2026-10-17T10:30:00+08:00',
    },
  })
  const html = renderPage(s)
  assert.match(html, /id="wh5-quality-state"[^>]*>返工</)
  assert.match(html, /原因：缝线开裂/)
  assert.match(html, /检验人 张师傅/)
  assert.equal(/id="wh5-quality-state"[^>]*>未检/.test(html), false)

  // 同一屏的初始态（未加载到记录）仍是「未检」
  const without = renderPage(open())
  assert.equal(/id="wh5-quality-state"[^>]*>合格/.test(without), false)
})

test('④ 展开表单 ⇒ 三态 + 原因必填提示 +「提交质检单」；提交中禁用', () => {
  const formOpen = reduce(open(), { type: 'qualityFormOpen' })
  const html = renderPage(formOpen)
  assert.match(html, /id="wh5-quality-form"/)
  for (const option of QUALITY_RESULTS) {
    assert.match(html, new RegExp(`data-quality-result="${option.value}"`))
  }
  assert.match(html, /不合格原因（判定为返工 \/ 报废时必填）/)
  assert.match(html, /id="wh5-quality-submit"[^>]*>提交质检单</)

  const submitting = renderPage(reduce(formOpen, { type: 'qualitySubmitting' }))
  assert.match(submitting, /id="wh5-quality-submit"[^>]*disabled[^>]*>提交中…</)
})

test('⑤ 提交成功 ⇒ 「质检单已生成」+ 判定换成回执（表单收起）', () => {
  let s = reduce(open(), { type: 'qualityFormOpen' })
  s = reduce(s, { type: 'qualitySubmitted', latest: { result: 'pass', inspector_name: '张师傅' } })
  const html = renderPage(s)
  assert.match(html, /质检单已生成/)
  assert.match(html, /id="wh5-quality-state"[^>]*>合格</)
  assert.equal(html.includes('id="wh5-quality-form"'), false)
  // 再录一次 = 复检（同一件可以返工后再检）
  assert.match(html, /id="wh5-quality-open"[^>]*>再录一次判定</)
})

test('⑥ 服务端拒绝原因 ⇒ 表单内具名报错（不关表单、不清已填判定）', () => {
  let s = reduce(open(), { type: 'qualityFormOpen' })
  s = reduce(s, { type: 'qualityResult', result: 'scrap' })
  s = reduce(s, { type: 'qualityFormError', error: '判定为「报废」时必须填写不合格原因' })
  const html = renderPage(s)
  assert.match(html, /id="wh5-quality-form-error"[^>]*>判定为「报废」时必须填写不合格原因</)
  assert.match(html, /data-quality-result="scrap"[^>]*aria-pressed="true"/)
})

// ── issue #7186：质检工序**没有报工动作**（判定即报工） ─────────────────────────────
//
// 用户 2026-10-18 逐字：「质检员不需要报工这个动作，只需要有一个质检动作，完成判定后自动报工，
// 然后自动生成质检流水」⇒ 当前工序 = 质检时，本屏**不得**出现报工按钮 / 报工三态；
// 质检区块即唯一动作。服务端那条真闸（422）由 `ProductionReportQualityGuardTest` +
// `ProductionScanCompleteServiceTest` 钉住 —— 藏按钮**不是**授权。

function openWithOperation(operation, pages = [PAGE_REPORT, PAGE_INSPECT]) {
  let s = reduce(initialState(), { type: 'worker', worker: WORKER })
  s = reduce(s, { type: 'pages', pages })
  return reduce(s, { type: 'resolved', view: { ...VIEW, operation: { ...VIEW.operation, ...operation } } })
}

test('⑦ 当前工序 = 质检 ⇒ 不出报工按钮 / 报工三态，只说「录入判定即完成报工」', () => {
  const html = renderPage(openWithOperation({ logical_name: '质检' }))
  assert.equal(html.includes('id="wh5-report"'), false)
  assert.equal(html.includes('id="wh5-work-type"'), false)
  assert.match(html, /id="wh5-quality-only"[^>]*>本道是质检工序：录入判定即完成报工并生成质检单/)
  // 质检区块仍在 —— 它是本屏**唯一的动作**
  assert.match(html, /id="wh5-quality"/)
})

test('⑧ 对照：非质检工序 ⇒ 报工按钮照旧出现（守卫不得误伤）', () => {
  const html = renderPage(openWithOperation({ logical_name: '精裁' }))
  assert.match(html, /id="wh5-report"[^>]*>报 工</)
  assert.match(html, /id="wh5-work-type"/)
  assert.equal(html.includes('id="wh5-quality-only"'), false)
})

test('⑨ 质检工序 + 未开通「质检」页 ⇒ 无报工按钮，且如实说「要谁来录」（不留死页面）', () => {
  const html = renderPage(openWithOperation({ logical_name: '质检' }, [PAGE_REPORT]))
  assert.equal(html.includes('id="wh5-report"'), false)
  assert.equal(html.includes('id="wh5-quality"'), false)
  assert.match(html, /id="wh5-quality-only"[^>]*>本道是质检工序：需由质检员录入判定（当前账号未开通「质检」页）/)
})
