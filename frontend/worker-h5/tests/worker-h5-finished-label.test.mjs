// case_ids: WH-007, WH-008
//
// 扫水洗唛 ⇒ 报工页「成品出库」卡片（V197 / issue #7762）：页面侧的类级判据。
//
// 用户口径（2026-10-25 逐字）：「允许工人扫码水洗唛进行成品出库打标签操作」「只有关联打包工序的
// 工人扫码后才能操作出库」。页面这一侧只负责**呈现与触发**，因此判据钉的是：
//   ① 卡片只在服务端下发 `washLabel` 时出现，内容**逐行来自服务端**（`label.rows`），前端不自拼业务字段；
//   ② 「打印标签」走**独立打印文档**（`@page 50mm 70mm`），不把报工页印上纸；
//   ③ 「出库」调的是 `POST /api/worker/stock/finished-outbound`，且服务端说不能出库时按钮 disabled
//      —— 隐藏按钮不是授权（拒绝仍由服务端判）。
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

const read = (p) => readFileSync(new URL(`../src/${p}`, import.meta.url), 'utf8')
const render = read('render.mjs')
const api = read('api.mjs')
const app = read('app.mjs')

test('标签卡片的每一行都来自服务端 label.rows（前端不拼订单字段）', () => {
  const card = render.slice(render.indexOf('function washLabelCard'))
  assert.match(card, /label\.rows/)
  assert.match(card, /data-label-key=/)
  // 前端不得自己读这些业务字段拼标签（唯一来源是服务端 rows）
  assert.doesNotMatch(card, /order_no|customer_name|sku_code/)
  // 服务端说不能出库 ⇒ 按钮 disabled（不是只靠藏按钮）
  assert.match(card, /allowed \? '' : ' disabled'/)
})

test('打印走独立文档：@page 50mm × 70mm，且只含标签行与短码', () => {
  const start = render.indexOf('export function washLabelPrintHtml')
  assert.ok(start > 0, '缺少 washLabelPrintHtml')
  const body = render.slice(start, render.indexOf('export function renderPage'))
  assert.match(body, /@page \{ size: 50mm 70mm; margin: 0; \}/)
  assert.match(body, /label\.rows/)
  assert.match(body, /label\.short_code/)
  // 打印文档里不得出现报工页的容器（否则会把整页印上纸）
  assert.doesNotMatch(body, /worker-h5-root|wh5-card/)
})

test('出库视图随扫码响应下发（不再多发一次 GET），出库调 POST /api/worker/stock/finished-outbound', () => {
  assert.match(app, /washLabel: view\.finished_outbound \?\? null/)
  assert.match(api, /\/api\/worker\/stock\/finished-outbound/)
  assert.match(api, /method: 'POST'/)
  // 读面只有一条（服务端随视图给）：页面不得自己再拉一次 wash-label
  assert.doesNotMatch(api, /wash-label/)
})
