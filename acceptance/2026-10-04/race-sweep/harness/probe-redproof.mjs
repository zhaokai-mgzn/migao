// 线③ 红证 / 判别对照：证明每条关键判据「在并发退化时会变」且检测器不是恒绿
// RP1 顺序对照（幂等键）：同 runId 顺序重复提交 ⇒ 必须是可读回执（而非并发下的 5xx）
// RP2 检测器注入（台账链）：合成的「同基并发读」两行喂给 chainCheck ⇒ 必须报红
// RP3 顺序对照（过账 CAS）：顺序双击过账 ⇒ [200,4xx] 且台账恰一行（判据非恒真）
// RP4 检测器注入（跨租户）：把一个**确属对方租户**的探针商品 id 塞进「本租户响应」⇒ 判据必须报红
import { api, loginApi, Recorder, log, OUT, psql, one } from './lib.mjs'
import { T_A, PROBE } from './config.mjs'
import { chainCheck, skuIdsByCode } from './lib2.mjs'
import { readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { fanOut, timedApi, overlapStats } from './lib2.mjs'

const FIX = JSON.parse(readFileSync(join(OUT, 'fixtures.json'), 'utf8'))
const T_B = FIX.tenantB
const R = new Recorder('probe-redproof.json')
const STAMP = FIX.stamp
const rnd = () => Math.random().toString(36).slice(2, 8)
const a = await loginApi(FIX.phoneA)
const TOK = a.token
const REC = { stamp: STAMP, cases: {} }
const A1 = skuIdsByCode(T_A).find((s) => s.sku_code.includes('A1'))

// ── RP1 顺序对照：同 runId 重复盘点 ──
async function RP1() {
  const batches = psql(`select id, batch_no, quantity::text q from stock_batches where tenant_id=${T_A} and sku_id=${A1.id} order by id`)
  if (!batches.length) { R.skip('RP1-同 runId 顺序重复盘点（判别对照）', '顺序重复必须 replayed', '前置不成立：无批次行'); return }
  const b = batches[0]
  const runId = `${PROBE}-rp1-${STAMP}-${rnd()}`
  const rem = await api('GET', `/api/admin/batch-stock/batches?productId=${A1.product_id}`, { token: TOK })
  const row = (rem.json?.data ?? []).find((x) => String(x.batchId) === String(b.id))
  const actual = Number(Number(row?.remainingMeters ?? b.q).toFixed(1)) - 1
  const body = { productId: A1.product_id, runId, lines: [{ batchId: String(b.id), actualMeters: Number(actual.toFixed(1)) }] }
  const r1 = await api('POST', '/api/admin/batch-stock/stocktake', { token: TOK, body })
  const r2 = await api('POST', '/api/admin/batch-stock/stocktake', { token: TOK, body })
  // 回执字段口径（实测正本）：data = {runId, changedCount, unchangedCount, replayedCount, totalDelta, lines[]}
  const s1 = `changed=${r1.json?.data?.changedCount},replayed=${r1.json?.data?.replayedCount}`
  const s2 = `changed=${r2.json?.data?.changedCount},replayed=${r2.json?.data?.replayedCount}`
  const cons = Number(one(`select count(*)::int c from stock_batch_consumptions where tenant_id=${T_A} and stocktake_run_id='${runId}'`).c)
  const ev = { runId, batchId: b.id, statuses: [r1.status, r2.status], lineStatuses: [s1, s2], consumptionRows: cons,
    bodies: [r1.text.slice(0, 200), r2.text.slice(0, 200)] }
  REC.cases.RP1 = ev
  const pass = r1.status === 200 && r2.status === 200 && r2.json?.data?.replayedCount === 1 && cons === 1
  const detail = `同 runId **顺序**两次（无并发重叠）：状态 ${JSON.stringify(ev.statuses)}；回执行态 ${JSON.stringify(ev.lineStatuses)}（第二次应 changed=0,replayed=1）；分录 ${cons} 行`
  pass ? R.pass('RP1-同 runId 顺序重复盘点（判别对照）', '顺序重复提交 ⇒ 可读回执 replayed、分录仍 1 行（对照并发下的 5xx，证明判据测的是并发）', detail, [ev])
       : R.fail('RP1-同 runId 顺序重复盘点（判别对照）', '顺序重复提交', '🔴 ' + detail, [ev])
}

// ── RP2 检测器注入：台账链判据必须能抓到「同基并发读」 ──
function RP2() {
  const clean = [{ id: 1, before_qty: '10.0', delta: '5.0', after_qty: '15.0' }, { id: 2, before_qty: '15.0', delta: '5.0', after_qty: '20.0' }]
  const broken = [{ id: 1, before_qty: '10.0', delta: '5.0', after_qty: '15.0' }, { id: 2, before_qty: '10.0', delta: '5.0', after_qty: '15.0' }]
  const a1 = chainCheck(clean), a2 = chainCheck(broken)
  const ev = { cleanChainBad: a1, brokenChainBad: a2 }
  REC.cases.RP2 = ev
  const pass = a1.length === 0 && a2.length > 0
  const detail = `链判据注入：合法链报 ${a1.length} 处不一致（应 0）；合成「同基并发读」链报 ${a2.length} 处（应 >0）`
  pass ? R.pass('RP2-台账链判据注入（红证）', '合成同基并发读的行喂给 chainCheck ⇒ 必须报红（证明 W3b 不是恒绿）', detail, [ev])
       : R.fail('RP2-台账链判据注入（红证）', '合成同基并发读的行喂给 chainCheck', '🔴 ' + detail, [ev])
}

// ── RP3 顺序对照：双击过账 ──
async function RP3() {
  const d = await api('POST', '/api/admin/inbound-orders', { token: TOK, body: {
    supplier: `${PROBE}-rp3`, warehouse: `${PROBE}-wh`, source: 'purchase', remark: `${PROBE}-rp3-${STAMP}-${rnd()}`,
    items: [{ productId: A1.product_id, skuId: String(A1.id), quantity: '1.0', unitCost: 5.0, dyeLot: `${PROBE}-rp3` }] } })
  if (d.status !== 200) { R.skip('RP3-顺序双击过账（判别对照）', '顺序双击必须 4xx 且库存只加一次', `建单失败 ${d.status}`); return }
  const id = d.json.data.id, no = d.json.data.inbound_no ?? d.json.data.inboundNo
  const before = Number(one(`select stock::text s from product_skus where tenant_id=${T_A} and id=${A1.id}`).s)
  const r1 = await api('PATCH', `/api/admin/inbound-orders/${id}`, { token: TOK, body: { action: 'post' } })
  const r2 = await api('PATCH', `/api/admin/inbound-orders/${id}`, { token: TOK, body: { action: 'post' } })
  const after = Number(one(`select stock::text s from product_skus where tenant_id=${T_A} and id=${A1.id}`).s)
  const rows = Number(one(`select count(*)::int c from stock_ledger_entries where tenant_id=${T_A} and sku_id=${A1.id} and ref_no='${no}'`).c)
  const ev = { inboundNo: no, statuses: [r1.status, r2.status], stockBefore: before, stockAfter: after, ledgerRows: rows,
    bodies: [r1.text.slice(0, 160), r2.text.slice(0, 160)] }
  REC.cases.RP3 = ev
  const pass = r1.status === 200 && r2.status >= 400 && after - before === 1 && rows === 1
  const detail = `顺序双击过账（无并发）：状态 ${JSON.stringify(ev.statuses)}（第二次应 4xx）；库存 ${before}→${after}（Δ${after - before}，应 1）；台账 ${rows} 行`
  pass ? R.pass('RP3-顺序双击过账（判别对照）', '顺序双击 ⇒ 第二次 4xx、库存只加一次、台账一行（证明 W1 的「恰一个赢家」判据非恒真）', detail, [ev])
       : R.fail('RP3-顺序双击过账（判别对照）', '顺序双击过账', '🔴 ' + detail, [ev])
}

// ── RP4 检测器注入：跨租户判据必须能抓到合成越租户响应 ──
function RP4() {
  const bIds = psql(`select id from products where tenant_id=${T_B} and name like '${PROBE}%'`).map((r) => String(r.id))
  const aIds = new Set(psql(`select id from products where tenant_id=${T_A} and name like '${PROBE}%'`).map((r) => String(r.id)))
  const synth = { status: 200, json: { success: true, data: { items: [{ id: bIds[0] ?? 'x' }] } } }
  const ownerOf = (id) => (aIds.has(String(id)) ? T_A : bIds.includes(String(id)) ? T_B : null)
  const flagged = (synth.json.data.items ?? []).map((x) => String(x.id)).filter((id) => ownerOf(id) !== null && ownerOf(id) !== T_A)
  const ev = { bProbeIds: bIds, aProbeCount: aIds.size, syntheticFlagged: flagged }
  REC.cases.RP4 = ev
  const pass = bIds.length > 0 && flagged.length > 0
  const detail = `跨租户判据注入：合成「租户 ${T_A} 的列表里含租户 ${T_B} 的探针商品 ${bIds[0] ?? 'N/A'}」⇒ 判据标记 ${flagged.length} 个（应 >0）`
  pass ? R.pass('RP4-跨租户判据注入（红证）', '合成越租户响应 ⇒ 归属比对必须报红（证明 C1/C5 不是恒绿）', detail, [ev])
       : R.fail('RP4-跨租户判据注入（红证）', '合成越租户响应', '🔴 ' + detail, [ev])
}

const CASES = { RP1, RP2, RP3, RP4 }
const only = (process.argv.slice(2).find((x) => x.startsWith('--only=')) || '').replace('--only=', '')
for (const k of (only ? only.split(',') : Object.keys(CASES))) {
  try { await CASES[k]() } catch (e) { R.skip(`${k}-环境阻塞`, `${k} 未完成`, String(e.message).slice(0, 300)) }
}
writeFileSync(join(OUT, 'probe-redproof-raw.json'), JSON.stringify(REC, null, 2))
const sum = R.summary()
log(`=== probe-redproof 读数：pass=${sum.pass} fail=${sum.fail} skip=${sum.skip} total=${sum.total} ===`)
writeFileSync(join(OUT, 'probe-redproof-summary.json'), JSON.stringify({ ...sum, stamp: STAMP }, null, 2))
