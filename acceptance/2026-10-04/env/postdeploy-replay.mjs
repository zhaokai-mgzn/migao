// 2026-10-04 集成侧「**修复后重放**」载体：部署把环境从 de614623d 升到 main 之后，
// 逐条复算三线报出的现象，产出 before/after 成对读数（期望值由**本脚本独立给出**，不读被测读面）。
//
// 用法（仓库根）：
//   API_BASE=https://api.migaozn.com TENANT_ID=25 ADMIN_PHONE=13800138000 SMS_CODE=123456 \
//   PHASE=postdeploy OUT_DIR=acceptance/2026-10-04/env/out \
//   node acceptance/2026-10-04/env/postdeploy-replay.mjs
//
// 覆盖的重放项（与 issue 对应）：
//   R1 #6293  .mjs MIME（/w/ 与 /w/machine.html 入口 + 对照 .css/.js）—— 期望 `application/javascript`
//   R2 #6220  同工单并发完结：状态码分布 + 台账行数 + 库存终值 —— 期望 [200,409,409,409] / 台账 1 行 / +2
//   R3 #6228  退款 0.001（小于最小可表示）—— 期望 **4xx 显式拒绝**（正对照 0.01 应 200 且逐字落库）
//   R4 #6222  列表 size=-5 —— 期望 **400 显式拒绝**（不得 total=0 却回整页）
//   R5 #6302  超长 skuCode（>30 字符）—— 期望 **4xx + 可行动文案**（不得 500 INTERNAL_ERROR）；
//             正对照 = 同脚本的 p/p2 夹具（正常长度 skuCode 建品 200）已成功建成
import { writeFileSync } from 'node:fs'
import {
  api, adminToken, psql, outPath, nowCST, raceStart, overlapEvidence, qtyEq,
  orderRow, ticketRow, skuStock, guardedWrite, createProbeProduct, createProbeOrder, TENANT_ID, PROBE_PREFIX,
} from '../../../acceptance/2026-10-03/aftersales-concurrency-sweep/harness/lib.mjs'

const PHASE = process.env.PHASE || 'postdeploy'
const TAG = `ZR${PHASE.slice(0, 6)}`
const out = { at: nowCST(), phase: PHASE, apiBase: process.env.API_BASE || 'https://api.migaozn.com', tenant: TENANT_ID, checks: [] }
const judge = (id, name, expect, actual, pass, evidence) => {
  out.checks.push({ id, name, expect, actual, verdict: pass ? 'pass' : 'fail', evidence })
  console.log(`${pass ? '✅' : '❌'} ${id} ${name}\n    期望: ${expect}\n    实测: ${actual}`)
}

// ── R1 静态 MIME（#6293）────────────────────────────────────────────────
{
  const urls = {
    '入口 app.mjs': 'https://app.migaozn.com/w/src/app.mjs',
    '入口 machine.mjs': 'https://app.migaozn.com/w/src/machine.mjs',
    '对照 styles.css': 'https://app.migaozn.com/w/src/styles.css',
    '对照 bmini app.js': 'https://app.migaozn.com/b/js/app.js',
    // #6306：入口的**依赖闭包**（render.mjs 静态 import 的共享模块）。迁移前它在站根 /shared/（未发布 ⇒ SPA 兜底 text/html），
    // 采纳的修法是树内迁移 ⇒ 发布后应在 /w/src/shared/ 且为 JS MIME。这一项把「入口 MIME 对 ≠ 页面能跑」补上。
    '闭包 src/shared/operation-display.mjs': 'https://app.migaozn.com/w/src/shared/operation-display.mjs',
  }
  const got = {}
  for (const [k, u] of Object.entries(urls)) {
    const r = await fetch(u, { method: 'HEAD' })
    got[k] = `${r.status} ${r.headers.get('content-type')}`
  }
  const jsOk = (v) => /application\/(java|ecma)script/i.test(v)
  const pass = jsOk(got['入口 app.mjs']) && jsOk(got['入口 machine.mjs']) &&
    /text\/css/.test(got['对照 styles.css']) && jsOk(got['对照 bmini app.js']) &&
    jsOk(got['闭包 src/shared/operation-display.mjs'])   // #6306：依赖闭包必须也取得到（且是 JS MIME）
  judge('R1', '.mjs 必须是 JS MIME（#6293）**且入口的依赖闭包取得到（#6306）**',
    '两个入口 .mjs = application/javascript；.css=text/css；对照 .js=JS MIME；闭包 src/shared/operation-display.mjs = 200 + JS MIME',
    JSON.stringify(got), pass,
    ['HEAD 实测；坏形态①`: application/octet-stream（浏览器拒绝执行 module script，= #6293）',
     '坏形态②：闭包内的依赖取不到（404→SPA 兜底 text/html），入口 MIME 再对页面也白屏（= #6306）'])
}

// ── 夹具（R2/R3 共用；自建，走真实 API）─────────────────────────────────
const { token, via } = await adminToken()
// 分类前置：新租户（或被各线清理后）可能 active 分类数=0 ⇒ 底座 createProbeProduct **不新建分类**（复用既有），
// 无分类时建品 422「分类ID不能为空」（= issue #6295 的现场）。本脚本自带分类并登记清理。
let catId = psql(`select id from categories where tenant_id=${TENANT_ID} and status='active' order by created_at limit 1`)[0]?.id
let catCreated = null
if (!catId) {
  const cr = await api('POST', '/api/admin/categories', { token, body: { name: `${PROBE_PREFIX}复现分类-${Date.now().toString(36)}`, status: 'active' } })
  catId = cr.json?.data?.id; catCreated = catId
  if (!catId) { console.error('夹具失败：无法建分类', String(cr.text).slice(0, 200)); process.exit(3) }
}
const p = await createProbeProduct(token, { allowRestock: true, stock: 100, price: 150, tag: TAG, categoryId: catId })
if (!p.ok) { console.error('夹具失败：探针商品未建成', JSON.stringify(p.body).slice(0, 300), String(p.resp?.text || '').slice(0, 300)); process.exit(3) }
const o = await createProbeOrder(token, {
  productId: p.productId, productName: p.name, skuId: p.skuId, skuCode: p.skuCode,
  colorId: p.colorId, qty: 2, unitPrice: 150, tag: TAG,
})
const orderNo = orderRow(o.orderId)?.order_no
// ⚠️ R3 必须用**独立订单**：R2 的并发完结会给 o 打上 300 元退款（副作用）⇒ 复用同一单时 R3 的
//「0.001 会被拒」是**污染读数**（首版即如此，已改）。判据间不得共享会被副作用改写的夹具。
const p2 = await createProbeProduct(token, { allowRestock: false, stock: 50, price: 100, tag: `${TAG}b`, categoryId: catId })
if (!p2.ok) { console.error('夹具失败：R3 探针商品未建成'); process.exit(3) }
const o2 = await createProbeOrder(token, { productId: p2.productId, productName: p2.name, skuId: p2.skuId, skuCode: p2.skuCode, colorId: p2.colorId, qty: 2, unitPrice: 100, tag: `${TAG}b` })
const orderNo2 = orderRow(o2.orderId)?.order_no
const clean = []
const guard = (sql) => guardedWrite(`-- probe-ok ${TAG}\n${sql}`)

// ── R2 并发完结（#6220）──────────────────────────────────────────────────
{
  const c = await api('POST', '/api/admin/after-sales', {
    token, body: { orderId: o.orderId, ticketType: 'return', description: `${TAG}-并发重放`, refundAmount: '300.00' },
  })
  const tid = c.json?.data?.id, tno = c.json?.data?.ticketNo
  await api('PUT', `/api/admin/after-sales/${tid}/status`, { token, body: { status: 'processing', remark: TAG } })
  const skuBefore = skuStock(p.skuId)?.stock
  const race = await raceStart(4, () => api('PUT', `/api/admin/after-sales/${tid}/status`, { token, body: { status: 'resolved', remark: TAG } }))
  const codes = race.results.map((r) => r.out?.status)
  const ledger = psql(`select id from stock_ledger_entries where tenant_id=${TENANT_ID} and ref_no='${tno}'`)
  const skuAfter = skuStock(p.skuId)?.stock
  const okCount = codes.filter((x) => x === 200).length
  const losersAll409 = codes.filter((x) => x !== 200).every((x) => x === 409)
  const pass = okCount === 1 && losersAll409 && ledger.length === 1 && qtyEq(skuAfter, '100.00')
  judge('R2', '并发完结：恰 1 个赢家 + 台账 1 行（#6220）',
    '成功数=1（其余 409「状态已被他人变更」）；台账恰 1 行；库存 98→100',
    `codes=${JSON.stringify(codes)} okCount=${okCount} 台账=${ledger.length} 行 库存 ${skuBefore}→${skuAfter} 工单终态=${ticketRow(tid)?.status}`,
    pass, [`重叠证据: ${JSON.stringify(overlapEvidence(race)).slice(0, 160)}`, `工单 ${tno}`])
  clean.push(`delete from ticket_timeline where tenant_id=${TENANT_ID} and ticket_id='${tid}';`,
    `delete from after_sales_tickets where tenant_id=${TENANT_ID} and id='${tid}';`)
}

// ── R3 退款精度（#6228）：0.001 应拒 / 0.01 应受 ────────────────────────
{
  const r1 = await api('PUT', `/api/admin/orders/${o2.orderId}/refund`, { token, body: { refund_reason: TAG, refund_amount: '0.001' } })
  const after1 = orderRow(o2.orderId)?.refund_amount
  const r2 = await api('PUT', `/api/admin/orders/${o2.orderId}/refund`, { token, body: { refund_reason: TAG, refund_amount: '0.01' } })
  const after2 = orderRow(o2.orderId)?.refund_amount
  const unchanged = String(after1) === '0.00' || String(after1) === '0'   // 0.001 被拒后库内必须不留痕
  const pass = r1.status >= 400 && r1.status < 500 && unchanged && r2.status === 200 && String(after2) === '0.01'
  judge('R3', '退款精度准入（#6228）', '0.001 ⇒ 4xx 且库内不变；0.01 ⇒ 200 且 refund_amount 逐字 = 0.01',
    `0.001→${r1.status}（refund_amount=${after1}）｜0.01→${r2.status}（refund_amount=${after2}）`,
    pass, [`响应原文(0.001): ${String(r1.text || '').slice(0, 200)}`, `响应原文(0.01): ${String(r2.text || '').slice(0, 160)}`])
}

// ── R4 分页下限（#6222）────────────────────────────────────────────────
{
  const r = await api('GET', '/api/admin/orders?page=1&size=-5', { token })
  let body = {}; try { body = JSON.parse(r.text) } catch { /* 非 JSON */ }
  const total = body?.data?.total, rows = (body?.data?.items || body?.data?.records || []).length
  const msg = String(r.text || '')
  const actionable = /size/.test(msg) && /(不能为负|不合法|请传)/.test(msg)   // 「可行动文案」也要断言
  const pass = r.status === 400 && actionable
  judge('R4', 'size<0 必须显式拒绝（#6222）', '400（可行动文案）；不得 200 且 total=0 却回整页',
    `${r.status} total=${total} rows=${rows} body=${String(r.text || '').slice(0, 160)}`, pass,
    ['坏形态：200 + total=0 + rows>0（总数与行数不自洽）'])
}

// ── R5 超长 skuCode 准入（#6302）──────────────────────────────────────
{
  // skuCode = `${ID_PREFIX}-${tag}-${uniq}`：把 tag 撑长即可造出 >30 字符的 skuCode（#6302 的现场）
  const longTag = 'L'.repeat(28)
  const r5 = await createProbeProduct(token, { tag: longTag, categoryId: catId, stock: 1, price: 10 })
  const code = String(r5.body?.skuCode || '')
  const status = r5.resp?.status
  const msg = String(r5.resp?.text || '')
  const admission = typeof status === 'number' && status >= 400 && status < 500
  const actionable = /SKU|sku|编码|长度|字符/.test(msg)
  const pass = !r5.ok && code.length > 30 && admission && actionable
  judge('R5', '超长 skuCode 必须 4xx 而非 500（#6302）',
    '长度>30 的 skuCode ⇒ 4xx + 可行动文案（不得 500 INTERNAL_ERROR）；正对照 = 同脚本正常长度夹具建品成功',
    `skuCode.len=${code.length} ⇒ HTTP ${status}：${msg.slice(0, 130)}`, pass,
    [`坏形态：500 INTERNAL_ERROR（value too long for type character varying(30)）`,
     `正对照：p/p2 夹具（正常长度）已建成 ⇒ ok=${p.ok}/${p2.ok}`])
}

// ── 清理（本脚本自建对象；FK 拓扑序）──────────────────────────────────
const cleanup = () => {
  clean.push(
    `delete from stock_ledger_entries where tenant_id=${TENANT_ID} and (product_id='${p.productId}' or sku_id=${p.skuId} or ref_no='${orderNo}');`,
    `delete from finance_transactions where tenant_id=${TENANT_ID} and order_id='${o.orderId}';`,
    `delete from order_items where tenant_id=${TENANT_ID} and order_id='${o.orderId}';`,
    `delete from orders where tenant_id=${TENANT_ID} and id='${o.orderId}';`,
    `delete from product_skus where tenant_id=${TENANT_ID} and id=${p.skuId};`,
    `delete from products where tenant_id=${TENANT_ID} and id='${p.productId}';`,
    `delete from stock_ledger_entries where tenant_id=${TENANT_ID} and (product_id='${p2.productId}' or sku_id=${p2.skuId} or ref_no='${orderNo2}');`,
    `delete from finance_transactions where tenant_id=${TENANT_ID} and order_id='${o2.orderId}';`,
    `delete from order_items where tenant_id=${TENANT_ID} and order_id='${o2.orderId}';`,
    `delete from orders where tenant_id=${TENANT_ID} and id='${o2.orderId}';`,
    `delete from product_skus where tenant_id=${TENANT_ID} and id=${p2.skuId};`,
    `delete from products where tenant_id=${TENANT_ID} and id='${p2.productId}';`)
  if (catCreated) clean.push(`delete from categories where tenant_id=${TENANT_ID} and id='${catCreated}';`)
  const errs = []
  for (const sql of clean) { try { guard(sql) } catch (e) { errs.push(String(e.message).slice(0, 120)) } }
  return errs
}
const errs = cleanup()
out.cleanup = { errors: errs, residue: {
  orders: psql(`select count(*) c from orders where tenant_id=${TENANT_ID} and id in ('${o.orderId}','${o2.orderId}')`)[0]?.c,
  products: psql(`select count(*) c from products where tenant_id=${TENANT_ID} and id in ('${p.productId}','${p2.productId}')`)[0]?.c,
  categories: catCreated ? psql(`select count(*) c from categories where tenant_id=${TENANT_ID} and id='${catCreated}'`)[0]?.c : 0,
  tickets: psql(`select count(*) c from after_sales_tickets where tenant_id=${TENANT_ID} and order_id in ('${o.orderId}','${o2.orderId}')`)[0]?.c,
} }
out.counts = out.checks.reduce((a, c) => { a[c.verdict] = (a[c.verdict] || 0) + 1; return a }, {})
writeFileSync(outPath(`replay-${PHASE}.json`), JSON.stringify(out, null, 2))
console.log(`\n汇总: ${JSON.stringify(out.counts)} · 清理错误=${errs.length} · 残留=${JSON.stringify(out.cleanup.residue)}`)
console.log(`→ acceptance/2026-10-04/env/out/replay-${PHASE}.json`)
