// case_ids: WH-007, WH-008
//
// 扫水洗唛 ⇒ 报工页「成品入库」卡片 + 入库标签（V197 / #7762 → issue #7845 语义改判）。
//
// 用户口径（2026-10-26 逐字）：「只有打包工序绑定了成品帘入库，如果是打包工人，那扫码后除了自动报工，
// 还需要生成成品入库单」「打包扫码报工时就需要确认质检结果和成品入库&打入库标签」。
// ⇒ 卡片从「成品出库」改为「成品入库」：质检结果 + 入库单号 + 仓位 + 打印入库标签；
//    **出库按钮撤下**（打包 = 入库；出库留给发货 / 商家侧，服务端写面保留）。
//
// 页面这一侧只负责**呈现与触发**，因此判据钉三件事：
//   ① 卡片内容**逐行来自服务端**（`label.rows` / `inbound_no` / `bin_code` / `quality`），前端不自拼业务字段；
//   ② 「打印入库标签」走**独立打印文档**（`@page 50mm 70mm`），不把报工页印上纸；
//   ③ 数据来自**报工回执** `finished_inbound`（不再多发一次读请求）；工人页**不再有出库**按钮 / API 调用。
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

const read = (p) => readFileSync(new URL(`../src/${p}`, import.meta.url), 'utf8')
const render = read('render.mjs')
const api = read('api.mjs')
const app = read('app.mjs')

test('成品入库卡片的每一行都来自服务端（label.rows / inbound_no / bin_code / quality），前端不拼订单字段', () => {
  const start = render.indexOf('function finishedInboundCard')
  assert.ok(start > 0, '缺少 finishedInboundCard')
  const card = render.slice(start, start + 2400)
  assert.match(card, /label\.rows/)
  assert.match(card, /data-label-key=/)
  assert.match(card, /w\.inbound_no/, '入库单号来自服务端（可对账）')
  assert.match(card, /w\.bin_code/, '仓位号来自服务端（与商家库存页同一口径）')
  assert.match(card, /w\.quality/, '质检结论来自服务端（打包工人要核对的那一项）')
  // 前端不得自己读这些业务字段拼标签（唯一来源是服务端 rows）
  assert.doesNotMatch(card, /order_no|customer_name|sku_code/)
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

test('数据来自报工回执 finished_inbound；工人页**不再有**出库按钮 / 出库请求', () => {
  // ① 回执 → 状态（api 映射 + 装配层两个入口）
  assert.match(api, /finishedInbound: data\.finished_inbound \?\? null/)
  assert.match(app, /finishedInbound: r\.finishedInbound/)
  assert.match(app, /finishedInbound: view\.finished_inbound \?\? null/)
  // ② 出库按钮 / 出库调用已撤（用户 2026-10-26 裁定：打包 = 入库）
  assert.doesNotMatch(render, /wh5-fl-out/)
  assert.doesNotMatch(api, /request\('\/api\/worker\/stock\/finished-outbound'/, '页面不再发这条出库请求（注释里保留端点说明不算）')
  assert.doesNotMatch(app, /issueWashLabel/)
  // ③ 打印按钮接在入库卡上（数据源 = finishedInbound.label）
  assert.match(app, /on\('wh5-fi-print', printWashLabel\)/)
  assert.match(app, /const w = state\.finishedInbound/)
})
