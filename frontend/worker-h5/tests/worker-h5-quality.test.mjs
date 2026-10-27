// case_ids: PG-082, PG-086, PG-099
//
// 工人端报工页 —— **质检并入返工**的反向判据（issue #7919）。
//
// 用户逐字（2026-10-27 18:13 +08）：
//   「报工页面的质检和返工要合并成一个功能，现在是两个独立的，移除质检，保留返工，当前系统返工=质检」
// 追问裁定（同轮）：删掉质检区块后，返工报工**要**继续产生质检记录（`quality_inspections`），
// 否则质检单 / 质量成本报表断档 —— 后端承载体 = `ProductionReworkQualityRecordTest`。
//
// 🔴 本文件是 PG-082 / PG-086 的**反向**形态：改前它钉「质检区块怎么显示」（`inspect` 页开了才渲染、
//   只有一个返工动作、提交后「质检单已生成」），改后钉「它不再出现、而返工那条路一字未动」。
//   六条，每条都能单独变红：
//   ① 行为面：档案**开了** `inspect`（改前渲染质检区块的唯一条件）⇒ 屏上仍然没有质检区块、没有「记返工」按钮；
//   ② 状态机面：质检动作**不再被消费**（`reduce` 原样返回、不留 `qualityForm` 键）——「界面删了、动作还在」
//      是半删，会让下一个读码人以为质检面还在；
//   ③ 结构守卫：`src/**`（.mjs / .css）与根 `*.html` 里零 `wh5-quality` / `qualityForm` / 质检写读端点字面量；
//   ④ 三态选择器仍在：正常 / 返工 / 报废三选一，选「返工」⇒ `view.work_type='rework'` 且选中态可见；
//      提交路径仍把 `workType` 交给 `completeByScan`（`api.mjs` 才是把它写成 `work_type` 键的地方）；
//      逐值的行为判据（真实装配层发出的请求体）= `worker-h5-report-work-type.test.mjs` ③ + `worker-h5-api.test.mjs`；
//   ⑤ 返工记录页仍可达：入口常量 / 屏上真链接 / `rework.html` 文件本身在；
//   ⑥ 质检工序只剩一句话：文案指向【返工】，不再有「要开通质检页」那种死路提示。
//
// 边界：真栈写入（`quality_inspections` 恰好一行、幂等重放不重复落）由后端
// `ProductionReworkQualityRecordTest` 钉住；本文件只判**渲染 / 状态机 / 源码结构**（零 DOM、零网络）。

import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  initialState,
  PAGE_INSPECT,
  PAGE_REPORT,
  PAGE_REWORK,
  REWORK_ENTRY_HREF,
  reduce,
  renderPage,
} from '../src/render.mjs'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.join(HERE, '..')
const read = (rel) => readFileSync(path.join(ROOT, rel), 'utf8')

const WORKER = { workerName: '张师傅', workerNo: 'W-001', idleMinutes: 43200 }

const VIEW = {
  set_no: 1,
  position: { order_item_id: 'item-1', position_name: '布艺遮光帘A 米白' },
  operation: { operation_id: 'op-1', logical_name: '裁剪', qty: 2, unit: '套', unit_price: 1.5 },
  completed: false,
}

/** 登录 + 页面集 + 解析结果（只在编排层之上判渲染）。 */
function open(pages = [PAGE_REPORT, PAGE_INSPECT], view = VIEW) {
  let s = reduce(initialState(), { type: 'worker', worker: WORKER })
  s = reduce(s, { type: 'pages', pages })
  return reduce(s, { type: 'resolved', view })
}

// ══════════════════════════════════════════════════════════════════════════════
// ① 行为面：`inspect` 已经**不再是**渲染条件 —— 质检区块整块消失
// ══════════════════════════════════════════════════════════════════════════════

test('🔴 ① 档案开了「质检」页也不再有质检区块：无 id="wh5-quality"、无「记返工」按钮；返工区块照旧', () => {
  const html = renderPage(open())
  assert.equal(html.includes('wh5-quality'), false, '质检区块（含它的子元素 id）必须一个字节都不剩')
  assert.doesNotMatch(html, /有问题，记返工/, '「有问题，记返工」是质检区块的入口按钮，已随区块撤下')
  assert.doesNotMatch(html, /再记一次返工/, '「再记一次返工」是质检区块的复录按钮，已随区块撤下')
  // 对照（否则本用例会在「整页都没渲染」时空转通过）：返工区块仍在，且它的入口不是质检那个文案
  assert.match(html, /id="wh5-rework"/)
  assert.match(html, /id="wh5-rework-open"[^>]*>这一件有问题，报返工/)
})

// ══════════════════════════════════════════════════════════════════════════════
// ② 状态机面：质检动作不再被消费（半删会让状态机与屏面各说一套）
// ══════════════════════════════════════════════════════════════════════════════

test('② 质检动作不再被 reduce 消费：原样返回（同一对象）+ 状态里没有 quality* 键', () => {
  const before = open()
  for (const type of ['qualityFormOpen', 'qualityFormClose', 'qualitySubmitting', 'qualityLoading', 'qualitySubmitted']) {
    assert.equal(reduce(before, { type }), before, `动作 ${type} 仍被消费 ⇒ 状态机里还留着质检面`)
  }
  const keys = Object.keys(reduce(before, { type: 'qualityFormOpen' })).filter((k) => /quality/i.test(k))
  assert.deepEqual(keys, [], `状态里仍有质检键：${keys.join(' / ')}`)
})

// ══════════════════════════════════════════════════════════════════════════════
// ③ 结构守卫（类级）：源码 / 样式 / 静态页里不再有质检面的任何标识
// ══════════════════════════════════════════════════════════════════════════════

test('🔴 ③ 结构守卫：src/**（.mjs/.css）与根 *.html 里零质检面标识，且零质检写读端点字面量', () => {
  const files = []
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name)
      if (entry.isDirectory()) walk(full)
      else if (/\.(mjs|css|html)$/.test(entry.name)) files.push(full)
    }
  }
  walk(path.join(ROOT, 'src'))
  for (const entry of readdirSync(ROOT, { withFileTypes: true })) {
    if (entry.isFile() && entry.name.endsWith('.html')) files.push(path.join(ROOT, entry.name))
  }
  // 判别力自证：扫描面必须真的覆盖到（否则「零命中」可能只是没扫到文件）
  assert.ok(files.some((f) => f.endsWith(path.join('src', 'render.mjs'))), '扫描面漏了 src/render.mjs')
  assert.ok(files.some((f) => f.endsWith(path.join('src', 'styles.css'))), '扫描面漏了 src/styles.css')
  assert.ok(files.some((f) => f.endsWith('.html')), '扫描面漏了静态页')

  const FORBIDDEN = ['wh5-quality', 'qualityForm', '/api/worker/quality']
  const hits = []
  for (const file of files) {
    const text = readFileSync(file, 'utf8')
    for (const token of FORBIDDEN) {
      if (text.includes(token)) hits.push(`${path.relative(ROOT, file)} → ${token}`)
    }
  }
  assert.deepEqual(hits.sort(), [], `工人端已无质检面，这些标识必须一并删干净（残留 = 半删）：\n  ${hits.sort().join('\n  ')}`)
})

// ══════════════════════════════════════════════════════════════════════════════
// ④ 保留的那一半：报工三态选择器（正常 / 返工 / 报废），且「返工」仍可选、可提交
// ══════════════════════════════════════════════════════════════════════════════

test('🔴 ④ 三态选择器仍在：选「返工」⇒ work_type=rework 且选中态可见；提交路径仍送 workType', () => {
  const html = renderPage(open([PAGE_REPORT]))
  assert.match(html, /id="wh5-work-type"/)
  for (const [value, label] of [['normal', '正常'], ['rework', '返工'], ['scrap', '报废']]) {
    assert.match(html, new RegExp(`data-work-type="${value}"`), `三态里丢了「${label}」这一档`)
  }
  // 默认仍是「正常」选中（返工不会被动成为缺省）
  assert.match(html, /data-work-type="normal"[^>]*aria-pressed="true"/)
  assert.match(html, /data-work-type="rework"[^>]*aria-pressed="false"/)

  const picked = reduce(open([PAGE_REPORT]), { type: 'workType', workType: 'rework' })
  assert.equal(picked.view.work_type, 'rework')
  const after = renderPage(picked)
  assert.match(after, /data-work-type="rework"[^>]*is-on/, '选中的「返工」必须看得见（is-on）')
  assert.match(after, /data-work-type="rework"[^>]*aria-pressed="true"/)
  assert.doesNotMatch(after, /data-work-type="normal"[^>]*is-on/)

  // 「提交带 work_type=rework」的两个承重点（行为逐值判据：report-work-type ③ / worker-h5-api.test.mjs）：
  // 装配层把选中的 workType 交给 api，api 才是写 `work_type` 这个键的地方。
  assert.match(read('src/app.mjs'), /workType:/, '装配层不再把 workType 交给 api.completeByScan ⇒ 返工报工退化成正常')
  assert.match(read('src/api.mjs'), /body\.work_type = workType/, 'api 层不再写 work_type 键 ⇒ 服务端收不到返工')
})

// ══════════════════════════════════════════════════════════════════════════════
// ⑤ 返工记录页仍可达（它不在本单的删除半径里）
// ══════════════════════════════════════════════════════════════════════════════

test('⑤ 返工记录仍可达：入口常量 = ./rework.html、屏上有真链接、页面文件在', () => {
  assert.equal(REWORK_ENTRY_HREF, './rework.html')
  assert.ok(existsSync(path.join(ROOT, 'rework.html')), 'rework.html 被误删 —— 返工记录页还在交付面里')
  const html = renderPage(open([PAGE_REPORT, PAGE_REWORK]))
  assert.match(html, /id="wh5-rework-entry"[^>]*href="\.\/rework\.html"[^>]*>返工记录/)
  // 页面键没开 ⇒ 不出现（逐人开的既有口径不变）
  assert.doesNotMatch(renderPage(open([PAGE_REPORT])), /id="wh5-rework-entry"/)
})

// ══════════════════════════════════════════════════════════════════════════════
// ⑥ 质检工序那一屏：只剩「有问题走返工」一条出口（不再有「开通质检页」的死路提示）
// ══════════════════════════════════════════════════════════════════════════════

test('🔴 ⑥ 当前工序 = 质检 ⇒ 无报工按钮 / 无三态；只说「有问题走返工」，且不再按 inspect 页两套文案', () => {
  const qualityView = { ...VIEW, operation: { ...VIEW.operation, logical_name: '质检' } }
  const opened = renderPage(open([PAGE_REPORT, PAGE_INSPECT], qualityView))
  assert.equal(opened.includes('id="wh5-report"'), false, '质检工序不该出报工按钮')
  assert.equal(opened.includes('id="wh5-work-type"'), false, '质检工序不该出报工三态')
  assert.match(opened, /id="wh5-inspect-only"[^>]*>本道是质检工序：默认没问题[^<]*有问题走返工/)
  assert.doesNotMatch(opened, /开通「质检」页/, '「要记返工需开通质检页」是改前的死路提示，已随质检区块撤下')
  // 未开 inspect 的那一屏同一句话（文案不再分叉：出口只有返工，而返工不看页面键）
  const closed = renderPage(open([PAGE_REPORT], qualityView))
  assert.match(closed, /id="wh5-inspect-only"[^>]*>本道是质检工序：默认没问题[^<]*有问题走返工/)
})
