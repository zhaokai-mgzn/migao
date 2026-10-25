// case_ids: PG-082, PG-086
//
// 工人端**质检区块**（issue #7162；2026-10-25 按 issue #7749 改判）。
//
// 用户逐字（2026-10-17）：「工人不能进入观星台，维持这个设计，现在只需要在小程序端扫码进入报工页后
// 有入口进行质检即可」「因为工人主要通过扫水洗唛进入质检流程」「质检等同发货工序一样，打包发货完成后
// 生成发货单，质检完成后生成质检单，一样的意思」。
//
// 🔴 2026-10-25 改判（issue #7749，用户逐字：「质检不要显示合格，默认都合格，只有出现问题时允许直接
// 选择返工，只提供一个返工选项，加一些备注说明即可」「这样也不需要质检按钮，尽量少一些动作」）：
//   ① 没有「合格 / 报废」选项 —— **合格是默认态**，屏上不出现「合格」这个动作；
//   ② 唯一动作 =【返工】+ 问题说明（必填），提交后生成质检单；
//   ③ 没有记录 = 「正常」（不写「未检」，也不写「合格」）。
//
// 本文件钉五条（每条能单独变红）：
//   ① `inspect` ∉ 页面集 ⇒ **不渲染**质检区块；
//   ② `inspect` ∈ 页面集、无记录 ⇒ 出现「质检」区块 + 「正常」+「有问题，记返工」；
//   ③ 有返工记录 ⇒ 显示「已记返工」/ 原因 / 检验人 / 时刻；
//   ④ 展开表单 ⇒ **只有一个**返工动作 + 问题说明必填；提交成功 ⇒「质检单已生成」+ 表单收起；
//   ⑤ 当前工序 = 质检 ⇒ 不出报工按钮 / 报工三态，只说「默认没问题…」。
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

test('② 开了「质检」页、无记录 ⇒ 质检区块「正常」+「有问题，记返工」（不出现「合格」）', () => {
  const html = renderPage(open())
  assert.match(html, /id="wh5-quality"/)
  assert.match(html, /id="wh5-quality-state"[^>]*>正常</)
  assert.match(html, /id="wh5-quality-open"[^>]*>有问题，记返工</)
  // 🔴 用户逐字「质检不要显示合格」：整块（含状态/按钮/说明）不得出现「合格」
  const block = html.slice(html.indexOf('id="wh5-quality"'))
  assert.equal(block.includes('合格'), false)
})

test('③ 有返工记录 ⇒ 显示「已记返工」/ 原因 / 检验人；默认态仍是「正常」', () => {
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
  assert.match(html, /id="wh5-quality-state"[^>]*>已记返工</)
  assert.match(html, /原因：缝线开裂/)
  assert.match(html, /检验人 张师傅/)
  assert.match(html, /id="wh5-quality-open"[^>]*>再记一次返工</)

  // 服务端若给的是 pass（观星台录的），工人屏也只说「正常」——不显示「合格」
  const passed = reduce(open(), {
    type: 'qualityLoaded',
    latest: { result: 'pass', inspector_name: '李质检', inspected_at: '2026-10-17T10:30:00+08:00' },
  })
  assert.match(renderPage(passed), /id="wh5-quality-state"[^>]*>正常</)
})

test('④ 表单只有一个返工动作 + 问题说明必填；提交中禁用；成功 ⇒ 质检单已生成', () => {
  const formOpen = reduce(open(), { type: 'qualityFormOpen' })
  const html = renderPage(formOpen)
  assert.match(html, /id="wh5-quality-form"/)
  // 🔴 只提供一个返工选项：不再有 pass / scrap 的判定按钮
  assert.equal(html.includes('data-quality-result'), false)
  assert.match(html, /id="wh5-quality-hint"[^>]*>这次记为「返工」/)
  assert.match(html, /问题说明（必填）/)
  assert.match(html, /id="wh5-quality-submit"[^>]*>提交返工</)

  const submitting = renderPage(reduce(formOpen, { type: 'qualitySubmitting' }))
  assert.match(submitting, /id="wh5-quality-submit"[^>]*disabled[^>]*>提交中…</)

  const s = reduce(formOpen, { type: 'qualitySubmitted', latest: { result: 'rework', inspector_name: '张师傅' } })
  const done = renderPage(s)
  assert.match(done, /质检单已生成/)
  assert.match(done, /id="wh5-quality-state"[^>]*>已记返工</)
  assert.equal(done.includes('id="wh5-quality-form"'), false)
})

test('⑤ 服务端拒绝 ⇒ 表单内具名报错（不关表单、不丢已填说明）', () => {
  let s = reduce(open(), { type: 'qualityFormOpen' })
  s = reduce(s, { type: 'qualityFormError', error: '记返工要写明问题（例如：布面污渍 / 尺寸偏差）' })
  const html = renderPage(s)
  assert.match(html, /id="wh5-quality-form-error"[^>]*>记返工要写明问题/)
  assert.match(html, /id="wh5-quality-form"/)
  assert.match(html, /id="wh5-quality-reason"/)
})

// ── issue #7186 / #7749：质检工序**没有报工动作**，且不需要「质检按钮」 ────────────────
//
// 用户 2026-10-18：「质检员不需要报工这个动作，只需要有一个质检动作」；
// 2026-10-25 追加：「这样也不需要质检按钮，尽量少一些动作，如果工序没有完成随时可以进入质检判定就好」
// ⇒ 当前工序 = 质检时，本屏**不得**出现报工按钮 / 报工三态；只有一句「默认没问题」的说明 +
// 可按需展开的返工记录。服务端那条真闸（422）由 `ProductionReportQualityGuardTest` +
// `ProductionScanCompleteServiceTest` 钉住 —— 藏按钮**不是**授权。

function openWithOperation(operation, pages = [PAGE_REPORT, PAGE_INSPECT]) {
  let s = reduce(initialState(), { type: 'worker', worker: WORKER })
  s = reduce(s, { type: 'pages', pages })
  return reduce(s, { type: 'resolved', view: { ...VIEW, operation: { ...VIEW.operation, ...operation } } })
}

test('⑥ 当前工序 = 质检 ⇒ 不出报工按钮 / 报工三态，只说「默认没问题、有问题记返工」', () => {
  const html = renderPage(openWithOperation({ logical_name: '质检' }))
  assert.equal(html.includes('id="wh5-report"'), false)
  assert.equal(html.includes('id="wh5-work-type"'), false)
  assert.match(html, /id="wh5-quality-only"[^>]*>本道是质检工序：默认没问题/)
  // 质检区块仍在 —— 出问题时随时可记返工
  assert.match(html, /id="wh5-quality"/)
})

test('⑦ 对照：非质检工序 ⇒ 报工按钮照旧出现（守卫不得误伤）', () => {
  const html = renderPage(openWithOperation({ logical_name: '精裁' }))
  assert.match(html, /id="wh5-report"[^>]*>报 工</)
  assert.match(html, /id="wh5-work-type"/)
  assert.equal(html.includes('id="wh5-quality-only"'), false)
})

test('⑧ 质检工序 + 未开通「质检」页 ⇒ 无报工按钮，且如实说「要记返工需开通」', () => {
  const html = renderPage(openWithOperation({ logical_name: '质检' }, [PAGE_REPORT]))
  assert.equal(html.includes('id="wh5-report"'), false)
  assert.equal(html.includes('id="wh5-quality"'), false)
  assert.match(html, /id="wh5-quality-only"[^>]*>本道是质检工序：默认没问题；要记返工需开通「质检」页/)
})
