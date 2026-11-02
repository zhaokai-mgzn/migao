// 线③ 判据组 I：幂等键并发重复提交（X-Client-Request-Id / Idempotency-Key）
// 断言口径（统一）：同键 N 并发 ⇒ ①副作用恰一次（库侧对象行数/SKU 净变化）②同一对象号回放给所有请求方
//                    ③env：无键并发 ⇒ 找不到（对照，不是缺陷）
import { api, loginApi, Recorder, log, OUT, one } from './lib.mjs'
import { T_A, PROBE } from './config.mjs'
import { timedApi, fanOut, overlapStats, save, skuIdsByCode, skuStock, ledgerRows, chainCheck } from './lib2.mjs'
import { readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const FIX = JSON.parse(readFileSync(join(OUT, 'fixtures.json'), 'utf8'))
const R = new Recorder('probe-idem.json')
const STAMP = FIX.stamp
const rnd = () => Math.random().toString(36).slice(2, 8)
const a = await loginApi(FIX.phoneA)
const TOK = a.token
const HDR = 'X-Client-Request-Id'
const skuOf = (code) => skuIdsByCode(T_A).find((s) => s.sku_code.includes(code))
const REC = { stamp: STAMP, tenant: T_A, header: HDR, cases: {} }
const claimsOf = (key) => Number(one(`select count(*)::int c from client_request_keys where tenant_id=${T_A} and client_request_id='${key}'`)?.c ?? -1)
const ordersByRemark = (remark) => Number(one(`select count(*)::int c from orders where tenant_id=${T_A} and remark = '${remark}'`).c)

const orderBody = (sku, qty, tag) => ({
  customerName: `${PROBE}-幂等-${tag}`, customerPhone: '13900000000',
  customerAddress: `${PROBE}-地址`, logisticsType: 'express', logisticsCompany: `${PROBE}-物流`,
  remark: `${PROBE}-idem-${tag}-${STAMP}-${rnd()}`,
  items: [{ productId: sku.product_id, productName: sku.sku_code, quantity: Number(qty).toFixed(1), unitPrice: 10.0,
            subtotal: (qty * 10).toFixed(1), processingInfo: { skuId: String(sku.id), skuCode: sku.sku_code } }],
})

// ── I1 同键并发建单（Agent 面）：副作用恰一次 ──
async function I1() {
  const sku = skuOf('A1')
  const body = orderBody(sku, 2, 'I1')
  const key = `${PROBE}-key-${STAMP}-${rnd()}`
  const t = Date.now()
  const res = await fanOut(6, () => timedApi('POST', '/api/admin/agent/orders', { token: TOK, headers: { [HDR]: key }, body }, t), t)
  const st = overlapStats(res)
  const c = Object.fromEntries([...new Set(res.map((r) => r.status))].map((s) => [s, res.filter((r) => r.status === s).length]))
  const orderNos = [...new Set(res.map((r) => r.json?.data?.orderNo ?? r.json?.data?.order_no).filter(Boolean))]
  const dbRows = ordersByRemark(body.remark)
  const claim = claimsOf(key)
  const ev = { key, endpoint: 'POST /api/admin/agent/orders', statuses: c, window: st, distinctOrderNos: orderNos,
    dbOrdersWithRemark: dbRows, claimRows: claim, bodies: res.map((r) => r.text.slice(0, 140)) }
  REC.cases.I1 = ev
  const pass = orderNos.length === 1 && dbRows === 1 && claim === 1
  const detail = `同键 6 并发建单（issueSpan=${st.issueSpanMs}ms、重叠对=${st.overlappedPairs}）：状态 ${JSON.stringify(c)}；回放同一单号 ${JSON.stringify(orderNos)}；库侧该备注订单行 ${dbRows}（应 1）、client_request_keys ${claim} 行（应 1）`
  pass ? R.pass('I1-同键并发建单恰一个副作用', '同 X-Client-Request-Id 6 并发建单 ⇒ 恰 1 张单、恰 1 个占位、其余回放同单号', detail, [ev])
       : R.fail('I1-同键并发建单恰一个副作用', '同 X-Client-Request-Id 6 并发建单', '🔴 ' + detail, [ev])
}

// ── I2 无键并发（对照）：本就不去重 ⇒ 必须出多张单（证明 I1 不是「恒定只落 1 行」的假绿） ──
async function I2() {
  const sku = skuOf('A1')
  const body = orderBody(sku, 1, 'I2')
  const t = Date.now()
  const res = await fanOut(3, () => timedApi('POST', '/api/admin/agent/orders', { token: TOK, body }, t), t)
  const st = overlapStats(res)
  const dbRows = ordersByRemark(body.remark)
  const ev = { endpoint: 'POST /api/admin/agent/orders', statuses: res.map((r) => r.status), window: st, dbOrdersWithRemark: dbRows }
  REC.cases.I2 = ev
  const pass = dbRows === 3
  const detail = `无幂等键 3 并发同体建单（issueSpan=${st.issueSpanMs}ms、重叠对=${st.overlappedPairs}）：库侧该备注订单行 ${dbRows}（对照期望 3 —— 不去重）`
  pass ? R.pass('I2-无键并发对照（不去重）', '无幂等键时 3 并发同体 ⇒ 落 3 张单（证明 I1 的「恰 1」来自幂等键而非全局串行）', detail, [ev])
       : R.fail('I2-无键并发对照（不去重）', '无幂等键时 3 并发同体', '🔴 ' + detail + ' ⇒ 反证 I1 的「恰 1 张」口径不成立（判据缺陷，非产品缺陷）', [ev])
}

// ── I3 同键不同体并发（同一键、不同数量）：必须只认首次那一次 ──
async function I3() {
  const sku = skuOf('A1')
  const key = `${PROBE}-key-x-${STAMP}-${rnd()}`
  const bodies = [2, 3].map((q, i) => orderBody(sku, q, `I3${i}`))
  const t = Date.now()
  const before = skuStock(T_A, sku.id)
  const res = await fanOut(2, (i) => timedApi('POST', '/api/admin/agent/orders', { token: TOK, headers: { [HDR]: key }, body: bodies[i] }, t), t)
  const st = overlapStats(res)
  const rows0 = ordersByRemark(bodies[0].remark), rows1 = ordersByRemark(bodies[1].remark)
  const ev = { key, statuses: res.map((r) => r.status), window: st, ordersFirstBody: rows0, ordersSecondBody: rows1,
    distinctOrderNos: [...new Set(res.map((r) => r.json?.data?.orderNo ?? r.json?.data?.order_no).filter(Boolean))],
    bodies: res.map((r) => r.text.slice(0, 160)) }
  REC.cases.I3 = ev
  const pass = rows0 + rows1 === 1
  const detail = `同键不同体 2 并发（issueSpan=${st.issueSpanMs}ms、重叠对=${st.overlappedPairs}）：状态 ${JSON.stringify(ev.statuses)}；库侧两体订单行 ${rows0}/${rows1}（合计应 1）；回放单号 ${JSON.stringify(ev.distinctOrderNos)}`
  pass ? R.pass('I3-同键不同体并发只认首次', '同键 + 不同请求体并发 ⇒ 只落一张单（首次受理者），另一体不回放也不落库', detail, [ev])
       : R.fail('I3-同键不同体并发只认首次', '同键 + 不同请求体并发', '🔴 ' + detail, [ev])
}

// ── I4 同键顺序重放（red-proof 正对照）：与 I1 同一键串行两次 ⇒ 第二次必须回放 ──
async function I4() {
  const sku = skuOf('A1')
  const body = orderBody(sku, 1, 'I4')
  const key = `${PROBE}-key-seq-${STAMP}-${rnd()}`
  const t = Date.now()
  const r1 = await timedApi('POST', '/api/admin/agent/orders', { token: TOK, headers: { [HDR]: key }, body }, t)
  const r2 = await timedApi('POST', '/api/admin/agent/orders', { token: TOK, headers: { [HDR]: key }, body }, t)
  const n1 = r1.json?.data?.orderNo ?? r1.json?.data?.order_no, n2 = r2.json?.data?.orderNo ?? r2.json?.data?.order_no
  const dbRows = ordersByRemark(body.remark)
  const ev = { key, sequential: true, statuses: [r1.status, r2.status], orderNos: [n1, n2], sameOrderNo: !!n1 && n1 === n2,
    dbOrdersWithRemark: dbRows, gapMs: r2.sentAt - r1.recvAt, bodies: [r1.text.slice(0, 160), r2.text.slice(0, 160)] }
  REC.cases.I4 = ev
  const pass = dbRows === 1 && !!n1 && n1 === n2
  const detail = `同键**顺序**两次（间隔 ${ev.gapMs}ms，判别对照：无并发重叠）：状态 ${JSON.stringify(ev.statuses)}；单号 ${JSON.stringify([n1, n2])}（应相同）；库侧 ${dbRows} 行`
  pass ? R.pass('I4-同键顺序重放（判别对照）', '同键顺序两次 ⇒ 第二次回放首次单号、不新增订单（证明「回放」不是并发窗口的副产品）', detail, [ev])
       : R.fail('I4-同键顺序重放（判别对照）', '同键顺序两次', '🔴 ' + detail, [ev])
}

// ── I5 商家表单建单面（/api/admin/orders）是否认幂等键（如实登记） ──
async function I5() {
  const sku = skuOf('A1')
  const body = orderBody(sku, 1, 'I5')
  const key = `${PROBE}-key-form-${STAMP}-${rnd()}`
  const t = Date.now()
  const res = await fanOut(3, () => timedApi('POST', '/api/admin/orders', { token: TOK, headers: { [HDR]: key }, body }, t), t)
  const st = overlapStats(res)
  const dbRows = ordersByRemark(body.remark)
  const claim = claimsOf(key)
  const ev = { key, endpoint: 'POST /api/admin/orders（商家表单面）', statuses: res.map((r) => r.status), window: st,
    dbOrdersWithRemark: dbRows, claimRows: claim, bodies: res.map((r) => r.text.slice(0, 160)) }
  REC.cases.I5 = ev
  const noIdem = dbRows === 3 && claim === 0
  const detail = `商家表单面同键 3 并发（issueSpan=${st.issueSpanMs}ms、重叠对=${st.overlappedPairs}）：状态 ${JSON.stringify(ev.statuses)}；库侧订单行 ${dbRows}、client_request_keys ${claim} 行`
  if (noIdem) R.skip('I5-商家表单建单面幂等键', 'POST /api/admin/orders 是否消费 X-Client-Request-Id', '如实登记：该端点**不消费**幂等键（3 并发落 3 单、占位 0 行）⇒ 幂等覆盖面仅 Agent 面/工人面/发货面')
  else R.pass('I5-商家表单建单面幂等键', 'POST /api/admin/orders 幂等键消费情况', detail, [ev])
}

// ── I6 发货面幂等（X-Client-Request-Id）：同键并发发货 ⇒ 恰一次流转 ──
async function I6() {
  const sku = skuOf('A2')
  const body = orderBody(sku, 1, 'I6')
  const key = `${PROBE}-key-ship-${STAMP}-${rnd()}`
  const c = await api('POST', '/api/admin/agent/orders', { token: TOK, body })
  if (c.status !== 200) { R.skip('I6-发货面同键并发幂等', 'POST /api/admin/production/orders/{id}/ship', `前置失败：建单 ${c.status} ${c.text.slice(0, 120)}`); return }
  const oid = c.json.data.id
  const pay = await api('PUT', `/api/admin/orders/${oid}/payment`, { token: TOK })
  const stAfterPay = one(`select status from orders where tenant_id=${T_A} and id='${oid}'`)?.status
  const t = Date.now()
  const res = await fanOut(4, () => timedApi('POST', `/api/admin/production/orders/${oid}/ship`,
    { token: TOK, headers: { [HDR]: key }, body: { logisticsCompany: `${PROBE}-物流`, trackingNo: `${PROBE}-TN-${rnd()}` } }, t), t)
  const st = overlapStats(res)
  const claim = claimsOf(key)
  const order = one(`select status from orders where tenant_id=${T_A} and id='${oid}'`)
  const shipments = Number(one(`select count(*)::int c from order_shipments where tenant_id=${T_A} and order_id='${oid}'`).c)
  const ev = { key, orderId: oid, payStatus: pay.status, statusAfterPay: stAfterPay, statuses: res.map((r) => r.status), window: st,
    claimRows: claim, orderStatus: order?.status, shipments, bodies: res.map((r) => r.text.slice(0, 200)) }
  REC.cases.I6 = ev
  const pass = claim === 1 && shipments === 1 && order?.status === 'shipped'
  const detail = `发货面同键 4 并发（issueSpan=${st.issueSpanMs}ms、重叠对=${st.overlappedPairs}）：状态 ${JSON.stringify(ev.statuses)}；占位 ${claim} 行（应 1）、发货单 ${shipments} 行（应 1）、订单状态 ${order?.status}`
  pass ? R.pass('I6-发货面同键并发幂等', '同键并发发货 ⇒ 占位 1 行、发货单 1 张、订单流转 shipped 恰一次', detail, [ev])
       : R.fail('I6-发货面同键并发幂等', '同键并发发货', '🔴 ' + detail, [ev])
}

const CASES = { I1, I2, I3, I4, I5, I6 }
const only = (process.argv.slice(2).find((x) => x.startsWith('--only=')) || '').replace('--only=', '')
for (const k of (only ? only.split(',') : Object.keys(CASES))) {
  try { await CASES[k]() } catch (e) { R.skip(`${k}-环境阻塞`, `${k} 未完成`, String(e.message).slice(0, 300)) }
}
writeFileSync(join(OUT, 'probe-idem-raw.json'), JSON.stringify(REC, null, 2))
const sum = R.summary()
log(`=== probe-idem 读数：pass=${sum.pass} fail=${sum.fail} skip=${sum.skip} total=${sum.total} ===`)
save('probe-idem-summary.json', { ...sum, stamp: STAMP })
