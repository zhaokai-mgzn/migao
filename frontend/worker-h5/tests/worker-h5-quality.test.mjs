// case_ids: PG-082, PG-086, PG-099, MC-181
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

/**
 * 服务端下发的不合格**原因字典**（issue #7197 ①；`GET /api/worker/quality/latest` 的 `reasons`）。
 *
 * 🔴 来源是服务端：前端不另造一份会漂的表（那张表迟早与校验面漂开 —— 界面能点的项被服务端拒）。
 */
const DICTIONARY = [
  { code: 'fabric_stain', label: '布面污渍' },
  { code: 'fabric_hole', label: '布料破洞' },
  { code: 'color_diff', label: '色差' },
  { code: 'size_mismatch', label: '尺寸不符' },
  { code: 'stitching_defect', label: '走线不良' },
  { code: 'other', label: '其它' },
]

/** 登录 + 页面集 + 解析结果。 */
function open(pages = [PAGE_REPORT, PAGE_INSPECT], view = VIEW) {
  let s = reduce(initialState(), { type: 'worker', worker: WORKER })
  s = reduce(s, { type: 'pages', pages })
  return reduce(s, { type: 'resolved', view })
}

/** 读面返回（`records` 缺省为空；原因字典随读面一起回来 —— issue #7197 ①）。 */
function loaded(latest = null, records = [], pages = [PAGE_REPORT, PAGE_INSPECT], reasons = DICTIONARY) {
  return reduce(open(pages), { type: 'qualityLoaded', latest, records, reasons })
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
  // 只取质检 section 本体（页面下方「报工类型」里也有一个「正常」按钮，不是同一句话）
  const start = html.indexOf('id="wh5-quality"')
  const block = html.slice(start, html.indexOf('</section>', start))
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
  assert.match(html, /id="wh5-quality-pending"[^>]*>返工做好后在这里复检/)
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

test('⑤ 表单只有「返工 + 问题类型 + 补充说明」；提交中禁用；成功 ⇒ 质检已登记 + 表单收起', () => {
  const formOpen = reduce(loaded(), { type: 'qualityFormOpen' })
  const html = renderPage(formOpen)
  assert.match(html, /id="wh5-quality-form"/)
  // 🔴 只提供一个返工选项：不再有 pass / scrap 的判定按钮
  assert.equal(html.includes('data-quality-result'), false)
  assert.match(html, /id="wh5-quality-hint"[^>]*>这次记为「做工返工」/)
  // issue #7197 ①：原因 = **必选的字典项**（短语按钮）+ **可选的**自由补充
  assert.match(html, /问题类型（必选）/)
  assert.match(html, /补充说明（可不填）/)
  for (const item of DICTIONARY) {
    assert.match(html, new RegExp(`data-quality-reason="${item.code}"[^>]*>${item.label}<`))
  }
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
  const html = renderPage(reduce(loaded(), { type: 'qualityFormOpen', recheck: true }))
  assert.match(html, /id="wh5-quality-hint"[^>]*>这次复检记为「仍有问题」/)
  assert.match(html, /id="wh5-quality-submit"[^>]*>提交复检</)
  // 仍然只有一个动作 + 必选的问题类型
  assert.equal(html.includes('data-quality-result'), false)
  assert.match(html, /问题类型（必选）/)
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

// ── 质检员视角（2026-11-01 商米 V2s 真机验收）──────────────────────────────────
// 现场读数：只开 `inspect` 的质检员（周敏 W3001）扫水洗唛进报工页 —— 页头挂着红字
// 「本机菜单未开报工页（按管理员配置显隐）；本机报工仍可用 —— …或换一台设备 / 换一个工人」。
// 他本来就不报工，质检块才是他要用的面：这条警告对他是噪音，且读起来像「这台机器配错了」。
test('只开质检页（质检员）⇒ 不再挂「报工页没开」的红字，但质检块照旧在', () => {
  const html = renderPage(loaded(null, [], [PAGE_INSPECT]))
  assert.equal(html.includes('id="wh5-report-menu-closed"'), false, '质检员不该看到「报工页没开」警告')
  assert.equal(html.includes('id="wh5-quality-entry"'), true, '质检入口必须在（那是他要用的面）')
  // 反向：两个页面都没开 ⇒ 提示照旧（证明判据不是「把提示永远关掉」）
  const neither = renderPage(loaded(null, [], ['order']))
  assert.equal(neither.includes('id="wh5-report-menu-closed"'), true, '既没报工也没质检 ⇒ 提示照旧')
})

test('质检记录不再与块头结论重复同一句话（真机：「正常」印了两遍）', () => {
  const html = renderPage(loaded({ result: 'pass', result_label: '合格' }, [PASS_RECORD]))
  // 只取质检 section 本体（页面下方「报工类型」里也有一个「正常」按钮，不是同一句话）
  const start = html.indexOf('id="wh5-quality"')
  const block = html.slice(start, html.indexOf('</section>', start))
  const occurrences = (block.match(/>正常</g) ?? []).length
  assert.equal(occurrences, 1, `块头与记录行只该有一句「正常」，实测 ${occurrences} 句`)
  assert.match(block, /检验人 李质检/, '检验人照旧要印（去掉的是重复的结论标签，不是记录本身）')
})

// ══════════════════════════════════════════════════════════════════════════════
// 不合格原因字典（issue #7197 ①）—— 车间戴手套：点一项，少打字
// ══════════════════════════════════════════════════════════════════════════════

test('⑫ 原因项点选是**纯状态动作**：选中态 aria-pressed + 只选中一项（再点不取消）', () => {
  let s = reduce(loaded(), { type: 'qualityFormOpen' })
  let html = renderPage(s)
  // 默认不替人猜：一项都没选中（"默认选第一个"会把统计悄悄带偏）
  assert.match(html, /data-quality-reason="fabric_stain"[^>]*aria-pressed="false"/)

  s = reduce(s, { type: 'qualityReasonSelected', code: 'fabric_stain' })
  html = renderPage(s)
  assert.match(html, /class="wh5-q-reason-chip is-on" data-quality-reason="fabric_stain"[^>]*aria-pressed="true"/)
  // 其它项仍未被选中（单选语义）
  assert.match(html, /data-quality-reason="color_diff"[^>]*aria-pressed="false"/)

  // 再点同一项 ⇒ 仍是选中（不出现"点第二次反而清空"的坑：那要多点一次才能重选）
  s = reduce(s, { type: 'qualityReasonSelected', code: 'fabric_stain' })
  assert.match(renderPage(s), /data-quality-reason="fabric_stain"[^>]*aria-pressed="true"/)
})

test('⑬ 记录行原因 = 字典项中文名 + 补充；存量自由文本原样显示（未归类**不猜**）', () => {
  const withLabel = {
    ...REWORK_RECORD,
    reason_code: 'stitching_defect',
    reason_label: '走线不良',
    reason: '右帘下摆',
  }
  // 存量行：reason_code / reason_label 都是 null（老记录不清洗）
  const legacy = { ...REWORK_RECORD, reason_code: null, reason_label: null, reason: '脏 污渍' }
  const html = renderPage(loaded(withLabel, [withLabel, legacy]))

  assert.match(html, /走线不良（右帘下摆）/, '字典项 + 补充一并显示')
  assert.match(html, /脏 污渍/, '存量自由文本原样显示')
  // 存量行不得被凭空挂上某个字典项标签（把「脏」归成「布面污渍」= 静默失真）
  assert.equal(html.includes('布面污渍（脏'), false)
})

test('⑭ 字典没读到（读面没带 reasons）⇒ 不出任何原因项、不编假表，只说「读取中」', () => {
  const html = renderPage(reduce(open(), { type: 'qualityFormOpen' }))
  assert.equal(html.includes('data-quality-reason='), false, '没读到字典就不许凭空造项')
  assert.match(html, /id="wh5-quality-reasons-empty"[^>]*>问题类型读取中/)
  // 读面回来自带字典 ⇒ 占位消失、短语按钮出现（同一条渲染路径，不是第二份实现）
  assert.equal(renderPage(reduce(loaded(), { type: 'qualityFormOpen' })).includes('wh5-quality-reasons-empty'), false)
})
