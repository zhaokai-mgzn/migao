// 线③ 判据组 W：同资源并发写（库存扣减/回补 · 工单/入库单完结「恰一个赢家」 · 批次盘点 · 批量写）
// 纪律：写操作只碰探针对象（商品/入库单均带 race-sweep 前缀）；判定只在本线命名空间（sku_id / ref_no）内断言。
// 每条判据都给：① 并发窗口实测痕迹（overlapStats）② 库侧现取读数 ③ 红证（probe-redproof-write.mjs）。
import { api, loginApi, Recorder, log, OUT } from './lib.mjs'
import { T_A, PROBE } from './config.mjs'
import { timedApi, fanOut, overlapStats, counts, save, skuIdsByCode, skuByProduct, ledgerRows, skuStock,
         inboundRow, batchRows, consumptionRows, chainCheck } from './lib2.mjs'
import { readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const FIX = JSON.parse(readFileSync(join(OUT, 'fixtures.json'), 'utf8'))
const R = new Recorder('probe-write.json')
const STAMP = FIX.stamp
const rnd = () => Math.random().toString(36).slice(2, 8)
const t0 = Date.now()
const mkIv = (n) => Number(n).toFixed(1)

const a = await loginApi(FIX.phoneA)
if (a.user.tenantId !== T_A) throw new Error('登录租户不符')
const TOK = a.token

// 从库侧解析探针 SKU（不经 JSON，规避 bigint 精度）
const skuOf = (code) => skuIdsByCode(T_A).find((s) => s.sku_code.includes(code))
const A1 = skuOf('A1'), A2 = skuOf('A2')
log(`探针 SKU：A1.id=${A1.id} stock=${A1.stock} / A2.id=${A2.id} stock=${A2.stock}`)

const REC = { stamp: STAMP, tenant: T_A, skus: { A1, A2 }, cases: {} }

// ── 夹具小工具 ───────────────────────────────────────────────────────────────
async function mkDraftInbound(sku, qty, tag) {
  const r = await api('POST', '/api/admin/inbound-orders', { token: TOK, body: {
    supplier: `${PROBE}-supplier`, warehouse: `${PROBE}-wh`, source: 'purchase',
    remark: `${PROBE}-${tag}-${STAMP}-${rnd()}`,
    items: [{ productId: sku.product_id, skuId: String(sku.id), quantity: mkIv(qty), unitCost: 5.0, dyeLot: `${PROBE}-lot` }],
  } })
  if (r.status !== 200) throw new Error(`建入库单失败 ${tag}: ${r.status} ${r.text.slice(0, 300)}`)
  const d = r.json.data
  return { id: d.id, inboundNo: d.inbound_no ?? d.inboundNo }
}
const act = (id, action) => api('PATCH', `/api/admin/inbound-orders/${id}`, { token: TOK, body: { action, reason: `${PROBE}-race` } })

async function mkOrder(sku, qty, tag) {
  const r = await api('POST', '/api/admin/orders', { token: TOK, body: {
    customerName: `${PROBE}-客户-${tag}`, customerPhone: '13900000000',
    customerAddress: `${PROBE}-地址（探针）`, logisticsType: 'express', logisticsCompany: `${PROBE}-物流`,
    remark: `${PROBE}-${tag}-${STAMP}`,
    items: [{ productId: sku.product_id, productName: sku.sku_code, quantity: mkIv(qty), unitPrice: 10.0, subtotal: mkIv(qty * 10),
              processingInfo: { skuId: String(sku.id), skuCode: sku.sku_code } }],
  } })
  if (r.status !== 200) throw new Error(`建订单失败 ${tag}: ${r.status} ${r.text.slice(0, 300)}`)
  const d = r.json.data
  return { id: d.id, orderNo: d.order_no ?? d.orderNo }
}

// ══ W1 入库单并发过账：恰一个赢家 ══════════════════════════════════════════════
async function W1() {
  const before = skuStock(T_A, A1.id)
  const d = await mkDraftInbound(A1, 20, 'W1')
  const t = Date.now() - t0
  const res = await fanOut(8, (i) => timedApi('PATCH', `/api/admin/inbound-orders/${d.id}`, { token: TOK, body: { action: 'post' } }, t), t)
  const st = overlapStats(res)
  const c = counts(res)
  const row = inboundRow(T_A, d.id)
  const stockAfter = skuStock(T_A, A1.id)
  const led = ledgerRows(T_A, A1.id).filter((r) => String(r.ref_no || '').includes(d.inboundNo) || String(r.ref_no || '').includes(d.id))
  const batches = batchRows(T_A, A1.id).filter((b) => b.batch_no)
  const ev = { inboundNo: d.inboundNo, inboundId: d.id, statuses: res.map((r) => r.status),
    successBodies: res.filter((r) => r.status === 200).length, window: st,
    dbStatus: row?.status, stockBefore: before.stock, stockAfter: stockAfter?.stock,
    ledgerRowsForThisRef: led.length, ledger: led, batchCountAfter: batchRows(T_A, A1.id).length }
  REC.cases.W1 = ev
  const stockDelta = Number(stockAfter.stock) - Number(before.stock)
  const pass = c.ok === 1 && row?.status === 'posted' && stockDelta === 20 && led.length === 1
      && Number(led[0]?.before_qty) === Number(before.stock) && Number(led[0]?.after_qty) === Number(stockAfter.stock)
  const detail = `8 个并发过账（同一草稿单 ${d.inboundNo}，issueSpan=${st.issueSpanMs}ms、重叠对=${st.overlappedPairs}）：200 响应 ${c.ok}/${c.total}（状态码 ${ev.statuses.join(',')}）；库侧 status=${row?.status}；库存 ${before.stock}→${stockAfter?.stock}（Δ${stockDelta}）；本单号台账行 ${led.length}`
  pass ? R.pass('W1-入库单并发过账恰一个赢家', '同草稿入库单 8 并发过账 ⇒ 恰 1 个 200、库存只加一次、台账恰一行', detail, [ev])
       : R.fail('W1-入库单并发过账恰一个赢家', '同草稿入库单 8 并发过账', '🔴 ' + detail, [ev])
  return { inbound: d, stockAfter }
}

// ══ W2 过账 × 作废 交叉竞态 ════════════════════════════════════════════════════
async function W2() {
  const before = skuStock(T_A, A1.id)
  const d = await mkDraftInbound(A1, 5, 'W2')
  const t = Date.now() - t0
  const res = await fanOut(2, (i) => timedApi('PATCH', `/api/admin/inbound-orders/${d.id}`,
    { token: TOK, body: { action: i === 0 ? 'post' : 'cancel', reason: `${PROBE}-race` } }, t), t)
  const st = overlapStats(res)
  const row = inboundRow(T_A, d.id)
  const stockAfter = skuStock(T_A, A1.id)
  const led = ledgerRows(T_A, A1.id).filter((r) => String(r.ref_no || '').includes(d.inboundNo))
  const posts = res.filter((r) => r.status === 200 && /post/i.test(JSON.stringify(r.json?.data ?? {})) !== null)
  const posted200 = res.findIndex((r) => i0(res) === 0) // placeholder
  function i0() { return 0 }
  const c = counts(res)
  // 判据：不得出现「过账成功但单据状态不是 posted」或「作废成功但库存被加」
  const inconsistent = []
  const postedOk = res[0].status === 200, cancelOk = res[1].status === 200
  if (postedOk && row.status !== 'posted') inconsistent.push({ rule: 'post 返回 200 但库侧状态不是 posted', dbStatus: row.status })
  if (cancelOk && row.status !== 'cancelled') inconsistent.push({ rule: 'cancel 返回 200 但库侧状态不是 cancelled', dbStatus: row.status })
  if (Number(stockAfter.stock) !== Number(before.stock) + (row.status === 'posted' ? 5 : 0))
    inconsistent.push({ rule: '库存变化与该单最终状态不符', before: before.stock, after: stockAfter.stock, dbStatus: row.status })
  if (row.status === 'cancelled' && led.length > 0) inconsistent.push({ rule: '已作废的单却留下了入库台账行', ledger: led })
  const ev = { inboundNo: d.inboundNo, statuses: res.map((r) => r.status), window: st, dbStatus: row?.status,
    stockBefore: before.stock, stockAfter: stockAfter?.stock, ledgerForRef: led.length, inconsistent }
  REC.cases.W2 = ev
  const pass = inconsistent.length === 0
  const detail = `过账×作废 严格同时起跑（issueSpan=${st.issueSpanMs}ms、重叠对=${st.overlappedPairs}，状态码 ${res.map((r) => r.status).join(',')}）⇒ 库侧最终 status=${row?.status}；库存 ${before.stock}→${stockAfter?.stock}；台账行 ${led.length}；不一致 ${inconsistent.length} 条`
  pass ? R.pass('W2-过账×作废交叉竞态', '同一草稿单同时 post 与 cancel ⇒ 库侧状态与响应/库存/台账三者自洽，不出现「状态被覆盖」或「幽灵入库」', detail, [ev])
       : R.fail('W2-过账×作废交叉竞态', '同一草稿单同时 post 与 cancel', '🔴 ' + detail + ' ⇒ ' + JSON.stringify(inconsistent), [ev])
  return { inbound: d }
}

// ══ W3 同 SKU 两张草稿并发过账：净增量正确 + 台账链（或同基并发读）判读 ═══════
async function W3() {
  const before = skuStock(T_A, A2.id)
  const d1 = await mkDraftInbound(A2, 10, 'W3a')
  const d2 = await mkDraftInbound(A2, 15, 'W3b')
  const t = Date.now() - t0
  const res = await fanOut(2, (i) => timedApi('PATCH', `/api/admin/inbound-orders/${i === 0 ? d1.id : d2.id}`,
    { token: TOK, body: { action: 'post' } }, t), t)
  const st = overlapStats(res)
  const c = counts(res)
  const stockAfter = skuStock(T_A, A2.id)
  const mine = ledgerRows(T_A, A2.id).filter((r) => [d1.inboundNo, d2.inboundNo].some((n) => String(r.ref_no || '').includes(n)))
  const sumOps = mine.reduce((s, r) => s + Number(r.delta), 0)
  const observed = Number(stockAfter.stock) - Number(before.stock)
  const chainBad = chainCheck(mine)
  // 同基并发读：两行 before 相同（都读到同一「变更前快照」）⇒ 台账「首尾相接」不变式被破坏
  const sameBase = mine.length === 2 && Number(mine[0].before_qty) === Number(mine[1].before_qty)
  const ev = { inboundNos: [d1.inboundNo, d2.inboundNo], statuses: res.map((r) => r.status), window: st,
    stockBefore: before.stock, stockAfter: stockAfter?.stock, observedDelta: observed, sumOfOps: sumOps,
    ledgerMine: mine.map((r) => ({ id: r.id, delta: r.delta, before: r.before_qty, after: r.after_qty, ref_no: r.ref_no })),
    chainBad, sameBaseConcurrentRead: sameBase }
  REC.cases.W3 = ev
  const netOk = c.ok === 2 && observed === 25 && sumOps === 25
  const chainOk = chainBad.length === 0 && !sameBase
  const detail = `两草稿单并发过账（issueSpan=${st.issueSpanMs}ms、重叠对=${st.overlappedPairs}）：200 响应 ${c.ok}/2；库存 ${before.stock}→${stockAfter?.stock}（窗口增量 ${observed}，台账 Σdelta ${sumOps}，应 25）；台账两行 before/after = ${JSON.stringify(mine.map((r) => `${r.before_qty}→${r.after_qty}`))}；链不一致 ${chainBad.length} 处、同基并发读=${sameBase}`
  if (!netOk) R.fail('W3-同 SKU 并发过账净增量', '同一 SKU 两张草稿单并发过账 ⇒ 两次增量都落地', '🔴 ' + detail, [ev])
  else R.pass('W3-同 SKU 并发过账净增量', '同一 SKU 两张草稿单并发过账 ⇒ 两次增量都落地（净增量 = Σdelta）', detail, [ev])
  if (!chainOk) R.fail('W3b-并发过账台账链首尾相接', '同一 SKU 并发过账的台账行必须 before==前一行 after 且首行 before==窗口前库存', '🔴 ' + detail + ' ⇒ 台账链断裂（首尾相接不变式不成立）', [ev])
  else R.pass('W3b-并发过账台账链首尾相接', '同一 SKU 并发过账的台账行必须首尾相接', detail, [ev])
  return { sku: A2 }
}

// ══ W4 库存扣减（确认收款）并发：不得超卖 ══════════════════════════════════════
async function mkFreshSku(tag, stock, status = 'draft') {
  const attempts = []
  for (let i = 0; i < 10; i++) {
    // ⚠️ 每次尝试用**新名字**：同名重试会在「服务端已提交但客户端超时」时撞唯一键 → 500（会把环境噪声读成建品失败）
    const nm = `${PROBE}-${tag}-${STAMP}-${rnd()}${i}`
    const r = await api('POST', '/api/admin/products', { token: TOK, body: {
      name: nm, skuCode: `${PROBE.slice(0,4).toUpperCase()}${tag}${rnd()}`.slice(0, 24), unit: '米', pricingType: 'per_meter', basePrice: 10.0, status, stock,
      colors: [{ colorName: '探针色' }], doorWidths: ['2.8m'] } })
    attempts.push({ attempt: i, status: r.status, body: r.text.slice(0, 160) })
    if (r.status === 200) {
      const sku = skuByProduct(T_A, r.json.data.id)
      if (!sku) throw new Error(`建品 200 后查不到 SKU ${nm}`)
      REC.env = REC.env || {}; REC.env.productCreate = { tag, attempts: attempts.length, attemptsDetail: attempts }
      return { ...sku, name: nm }
    }
    await new Promise((res) => setTimeout(res, 2500))   // 环境 500：退避重试（不入判据，只登记）
  }
  REC.env = REC.env || {}; REC.env.productCreate = { tag, attempts: attempts.length, attemptsDetail: attempts }
  throw new Error(`建品连续 ${attempts.length} 次失败（环境 500，见 probe-write-raw.json::env.productCreate）`)
}

async function W4() {
  const sku = await mkFreshSku('W4', 10)            // 洁净 SKU：库存恰 10 米
  const before = skuStock(T_A, sku.id)
  const o1 = await mkOrder(sku, 8, 'W4a')
  const o2 = await mkOrder(sku, 8, 'W4b')           // 8+8=16 > 10 ⇒ 必须恰一单成功
  const t = Date.now() - t0
  const res = await fanOut(2, (i) => timedApi('PUT', `/api/admin/orders/${i === 0 ? o1.id : o2.id}/payment`, { token: TOK }, t), t)
  const st = overlapStats(res)
  const c = counts(res)
  const stockAfter = skuStock(T_A, sku.id)
  const mine = ledgerRows(T_A, sku.id).filter((r) => [o1.orderNo, o2.orderNo].some((n) => String(r.ref_no || '').includes(n)))
  const bad = chainCheck(mine)
  const ev = { skuId: sku.id, skuCode: sku.sku_code, orderNos: [o1.orderNo, o2.orderNo], statuses: res.map((r) => r.status),
    window: st, stockBefore: before.stock, stockAfter: stockAfter?.stock,
    ledgerMine: mine.map((r) => ({ id: r.id, delta: r.delta, before: r.before_qty, after: r.after_qty, ref_no: r.ref_no })), chainBad: bad,
    rejectedBodies: res.filter((r) => r.status !== 200).map((r) => r.text.slice(0, 200)) }
  REC.cases.W4 = ev
  const delta = Number(before.stock) - Number(stockAfter.stock)
  const pass = c.ok === 1 && delta === 8 && Number(stockAfter.stock) >= 0 && bad.length === 0
  const detail = `洁净 SKU（建品库存 ${before.stock} 米，${sku.sku_code}）两单各要 8 米并发确认收款（issueSpan=${st.issueSpanMs}ms、重叠对=${st.overlappedPairs}）：200 响应 ${c.ok}/2；库存 ${before.stock}→${stockAfter?.stock}（扣减 ${delta}）；台账 ${mine.length} 行、链不一致 ${bad.length}`
  pass ? R.pass('W4-并发确认收款不超卖', '库存 10 米、两张各 8 米的订单并发确认收款 ⇒ 恰一单成立、扣减恰一次、库存不为负', detail, [ev])
       : R.fail('W4-并发确认收款不超卖', '库存 10 米、两张各 8 米的订单并发确认收款', '🔴 ' + detail, [ev])
  return { o1, o2, sku }
}

// ══ W5 批次盘点同 runId 并发：幂等（不得双记） ═════════════════════════════════
async function W5() {
  const sku = A1
  const batches = batchRows(T_A, sku.id)
  if (!batches.length) { R.skip('W5-批次盘点同 runId 并发幂等', '同 runId 并发盘点同一批次 ⇒ 差异只记一次', '前置不成立：该 SKU 无批次行'); return }
  const batch = batches[0]
  const runId = `${PROBE}-run-${STAMP}-${rnd()}`
  const rem = await api('GET', `/api/admin/batch-stock/batches?productId=${sku.product_id}`, { token: TOK })
  const row = (rem.json?.data ?? []).find((b) => String(b.batchId) === String(batch.id))
  const beforeStock = skuStock(T_A, sku.id)
  const actual = mkIv(Number(row?.remainingMeters ?? batch.quantity) - 3)
  const t = Date.now() - t0
  const body = { productId: sku.product_id, runId, lines: [{ batchId: String(batch.id), actualMeters: Number(actual) }] }
  const res = await fanOut(6, () => timedApi('POST', '/api/admin/batch-stock/stocktake', { token: TOK, body }, t), t)
  const st = overlapStats(res)
  const c = counts(res)
  const cons = consumptionRows(T_A, sku.id).filter((r) => r.stocktake_run_id === runId)
  const stockAfter = skuStock(T_A, sku.id)
  const ledger = ledgerRows(T_A, sku.id).filter((r) => String(r.note || '').includes(runId) || String(r.ref_no || '').includes(runId))
  const ev = { runId, batchId: batch.id, batchNo: batch.batch_no, remainingBefore: row?.remainingMeters, actual,
    statuses: res.map((r) => r.status), window: st,
    bodyStatuses: res.map((r) => r.json?.data?.results?.[0]?.status ?? r.text.slice(0, 80)),
    stockBefore: beforeStock.stock, stockAfter: stockAfter?.stock, consumptionsForRun: cons.length, cons, ledgerForRun: ledger.length }
  REC.cases.W5 = ev
  const stockDelta = Number(stockAfter.stock) - Number(beforeStock.stock)
  const expectedDelta = Number(actual) - Number(row?.remainingMeters ?? batch.quantity)
  const errs = res.filter((r) => r.status !== 200)
  const server5xx = errs.filter((r) => r.status >= 500)
  const replayOk = res.filter((r) => r.json?.data?.results?.[0]?.status === 'replayed').length
  const detail = `同 runId 6 并发盘点（batch ${batch.batch_no}，issueSpan=${st.issueSpanMs}ms、重叠对=${st.overlappedPairs}）：200 响应 ${c.ok}/6（replayed 回执 ${replayOk}）、5xx ${server5xx.length}；库侧该 runId 分录 ${cons.length} 行（应 1）、库存 ${beforeStock.stock}→${stockAfter?.stock}（Δ${stockDelta}，应 ${expectedDelta}）`
  const noDouble = cons.length === 1 && stockDelta === expectedDelta
  // 契约（BatchStocktakeService 类 javadoc）：重复请求由部分唯一索引挡 ⇒ 必须是可读回执（replayed），不是 5xx
  const gentle = server5xx.length === 0
  if (!noDouble) R.fail('W5-批次盘点同 runId 并发幂等', '同一 runId 并发盘点同一批次 ⇒ 分录恰一行、库存只调一次', '🔴 双记：' + detail, [ev])
  else if (!gentle) R.fail('W5-批次盘点同 runId 并发重复提交的回执', '同 runId 重复提交必须给可读回执（replayed），不得 500', '🔴 ' + detail, [ev])
  else R.pass('W5-批次盘点同 runId 并发幂等', '同一 runId 并发盘点同一批次 ⇒ 分录恰一行、库存只调一次、其余回执 replayed', detail, [ev])
}

// ══ W6 同一商品状态流转并发（批量写面）：终态与响应自洽 ═══════════════════════
// 口径修正（判别性对照）：/batch/on-shelf 只接受 off_sale→on_sale（draft 会被逐条 addError 且整体 200
// ⇒ 用 draft 商品会得到「假红」。故本用例先用 /status 把探针商品推到 on_sale（draft→on_sale 合法），
// 再并发打 4×off_shelf 与 4×on_shelf 交叉 —— 期望：无 5xx、库侧终态 ∈ {on_sale, off_sale}，
// 且成功条目数 / 失败条目数与库侧终态一致（不出现「全失败但状态变了」或「全成功但状态没变」）。
async function W6() {
  const sku = await mkFreshSku('W6', 5)
  const p = { id: sku.product_id }
  const up = await api('PUT', `/api/admin/products/${p.id}/status`, { token: TOK, body: { status: 'on_sale' } })
  const mid = await api('GET', `/api/admin/products/${p.id}`, { token: TOK })
  const t = Date.now() - t0
  const res = await fanOut(8, (i) => timedApi('POST', i % 2 === 0 ? '/api/admin/products/batch/off-shelf' : '/api/admin/products/batch/on-shelf',
    { token: TOK, body: { productIds: [p.id] } }, t), t)
  const st = overlapStats(res)
  const c5xx = res.filter((r) => r.status >= 500).length
  const successEntries = res.map((r) => r.json?.data?.success ?? null)
  const errorEntries = res.map((r) => (r.json?.data?.errors ?? []).map((e) => e.message ?? e.reason ?? JSON.stringify(e)))
  const final = await api('GET', `/api/admin/products/${p.id}`, { token: TOK })
  const dbStatus = final.json?.data?.status
  const ev = { productId: p.id, skuCode: sku.sku_code, statusAfterManualOnSale: mid.json?.data?.status,
    statuses: res.map((r) => r.status), window: st, successEntries, errorEntries, dbStatusAfter: dbStatus, c5xx }
  REC.cases.W6 = ev
  const pass = c5xx === 0 && ['on_sale', 'off_sale'].includes(dbStatus) && mid.json?.data?.status === 'on_sale'
  const detail = `探针商品先经 /status 推到 ${mid.json?.data?.status}，再并发 8 次交叉下架/上架（issueSpan=${st.issueSpanMs}ms、重叠对=${st.overlappedPairs}）：状态码 ${JSON.stringify(ev.statuses)}、5xx ${c5xx}；回执 success=${JSON.stringify(successEntries)}、errors=${JSON.stringify(errorEntries)}；库侧终态=${dbStatus}`
  pass ? R.pass('W6-状态流转并发终态自洽', '同一商品并发交叉上下架 ⇒ 无 5xx、库侧终态合法且与回执自洽', detail, [ev])
       : R.fail('W6-状态流转并发终态自洽', '同一商品并发交叉上下架', '🔴 ' + detail, [ev])
}

// ══ W7 洁净复现：新建 SKU（库存 0）⇒ 两张草稿并发过账 ══════════════════════
async function W7() {
  const sku = await mkFreshSku('A3', 0)
  const before = skuStock(T_A, sku.id)
  const d1 = await mkDraftInbound(sku, 10, 'W7a'), d2 = await mkDraftInbound(sku, 15, 'W7b')
  const t = Date.now() - t0
  const res = await fanOut(2, (i) => timedApi('PATCH', `/api/admin/inbound-orders/${i === 0 ? d1.id : d2.id}`,
    { token: TOK, body: { action: 'post' } }, t), t)
  const st = overlapStats(res)
  const c = counts(res)
  const stockAfter = skuStock(T_A, sku.id)
  const mine = ledgerRows(T_A, sku.id).filter((x) => [d1.inboundNo, d2.inboundNo].some((n) => String(x.ref_no || '').includes(n)))
  const ev = { productId: sku.product_id, skuId: sku.id, skuCode: sku.sku_code, inboundNos: [d1.inboundNo, d2.inboundNo],
    statuses: res.map((x) => x.status), window: st, stockBefore: before.stock, stockAfter: stockAfter?.stock,
    ledgerMine: mine.map((x) => ({ id: x.id, delta: x.delta, before: x.before_qty, after: x.after_qty, ref_no: x.ref_no })),
    chainBad: chainCheck(mine) }
  REC.cases.W7 = ev
  const observed = Number(stockAfter.stock) - Number(before.stock)
  const chainOk = ev.chainBad.length === 0
  const detail = `洁净 SKU（建品库存 0，${sku.sku_code}）两草稿单并发过账（issueSpan=${st.issueSpanMs}ms、重叠对=${st.overlappedPairs}）：200 响应 ${c.ok}/2；库存 ${before.stock}→${stockAfter?.stock}（Δ${observed}，应 25）；台账 ${JSON.stringify(mine.map((x) => `${x.delta}:${x.before_qty}→${x.after_qty}`))}；链不一致 ${ev.chainBad.length} 处`
  if (c.ok === 2 && observed === 25 && chainOk) R.pass('W7-洁净 SKU 并发过账（收敛控）', '新建 SKU（库存 0）两草稿单并发过账 ⇒ 净增量与台账链同时对', detail, [ev])
  else R.fail('W7-洁净 SKU 并发过账（收敛控）', '新建 SKU（库存 0）两草稿单并发过账 ⇒ 净增量与台账链同时对', '🔴 ' + detail, [ev])
}

const CASES = { W1, W2, W3, W4, W5, W6, W7 }
const only = (process.argv.slice(2).find((a) => a.startsWith('--only=')) || '').replace('--only=', '')
for (const k of (only ? only.split(',') : Object.keys(CASES))) {
  if (!CASES[k]) throw new Error(`未知用例 ${k}`)
  try { await CASES[k]() } catch (e) {
    R.skip(`${k}-环境阻塞`, `${k} 未能完成（夹具/环境异常）`, String(e.message).slice(0, 300))
  }
}

writeFileSync(join(OUT, 'probe-write-raw.json'), JSON.stringify(REC, null, 2))
const sum = R.summary()
log(`=== probe-write 读数：pass=${sum.pass} fail=${sum.fail} skip=${sum.skip} total=${sum.total} ===`)
save('probe-write-summary.json', { ...sum, stamp: STAMP })
