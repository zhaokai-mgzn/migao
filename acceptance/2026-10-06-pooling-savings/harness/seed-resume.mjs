// 2026-10-06 续跑：复用已造的 300 单，补齐**池化派单（带指派）**、状态覆盖、报工与计件。
// 为什么要续跑：首跑时池化臂的请求体漏了 `orderIds`（只 spread 了 batches/assignmentRule）⇒
// 池化臂 0 单、242 单没有加工单；而**已付款订单无法删除**，所以只能续跑而不是重造。
import { api } from './lib.mjs'
import { login, T } from './steps.mjs'
import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const OUTDIR = fileURLToPath(new URL('../out/', import.meta.url)).replace(/\/$/, '')
const PREFIX = process.env.DEMO_PREFIX || 'SD07演示'
const t0 = Date.now()
const R = { at: new Date().toISOString(), prefix: PREFIX, mode: 'resume', errors: [], runErrors: [] }
const log = (...a) => console.log(`[${((Date.now() - t0) / 1000).toFixed(0)}s]`, ...a)
let seed = 20261006
const rnd = () => ((seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff)
const pick = (a) => a[Math.floor(rnd() * a.length)]
const rint = (lo, hi) => lo + Math.floor(rnd() * (hi - lo + 1))
const rdec = (lo, hi, d = 2) => Number((lo + rnd() * (hi - lo)).toFixed(d))

const token = await login()

// ── 1. 收齐本轮 300 单（分页） ──
const allOrders = []
for (let page = 1; page <= 5; page++) {
  const d = (await api('GET', `/api/admin/orders?page=${page}&size=100`, { token })).json?.data
  const arr = d?.list || d?.records || d?.items || []
  if (!arr.length) break
  allOrders.push(...arr)
  if (arr.length < 100) break
}
const mine = allOrders.filter((o) => String(o.customerName || '').startsWith(PREFIX))
// 每单的 order_item id（派工指派需要）
const itemOf = {}
for (const o of mine) {
  const d = (await api('GET', `/api/admin/orders/${o.id}`, { token })).json?.data
  const it = (d?.items || [])[0]
  if (it?.id) itemOf[o.id] = String(it.id)
}
log(`取到 ${PREFIX} 订单 ${mine.length} 张；有 itemId ${Object.keys(itemOf).length} 张`)

// ── 2. 已有加工单的订单（跳过） ──
const posAll = (await api('GET', '/api/admin/processing-orders', { token })).json?.data || []
const hasPo = new Set(posAll.map((p) => String(p.orderId)))
const needDispatch = mine.filter((o) => !hasPo.has(String(o.id)))
log(`已有加工单 ${hasPo.size} 张；待派单 ${needDispatch.length} 张`)

// ── 3. 池化派单（**带上 orderIds** + 逐行指派 ⇒ 跨订单并排） ──
const body = (os, rule, pooled) => ({
  orderIds: os.map((o) => o.id),
  batches: os.map((o) => ({ orderId: o.id, itemId: itemOf[o.id] })).filter((b) => b.itemId),
  assignmentRule: rule, pooled,
})
const call = async (os, rule, pooled) => (await api('POST', '/api/admin/production/pool/dispatch', { token, body: body(os, rule, pooled) })).json
let pooledOk = 0, singleOk = 0
const urgentNeed = needDispatch.filter((o) => o.isUrgent)
const normalNeed = needDispatch.filter((o) => !o.isUrgent)
for (const o of urgentNeed) {
  const r = await call([o], 'fifo', false)
  const res = Array.isArray(r?.data) ? r.data : []
  if (res[0]?.success) singleOk++
  else R.runErrors.push({ kind: 'urgent', orderNo: o.orderNo, msg: res[0]?.message || JSON.stringify(r?.error || r).slice(0, 160) })
}
for (let i = 0; i < normalNeed.length; ) {
  const sz = rint(8, 15)
  const chunk = normalNeed.slice(i, i + sz); i += sz
  const r = await call(chunk, pick(['fifo', 'best_fit']), true)
  const res = Array.isArray(r?.data) ? r.data : []
  if (!res.length) { R.runErrors.push({ kind: 'pooled-batch', n: chunk.length, msg: JSON.stringify(r?.error || r).slice(0, 200) }); continue }
  pooledOk += res.filter((x) => x.success).length
  res.filter((x) => !x.success).forEach((x) => R.runErrors.push({ kind: 'pooled', orderRef: x.orderRef, msg: String(x.message || '').slice(0, 160) }))
}
log(`派单：池化成功 ${pooledOk} / 加急逐单 ${singleOk} / 异常 ${R.runErrors.length}`)
R.dispatch = { pooledOk, singleOk, runErrors: R.runErrors.slice(0, 12), runErrorCount: R.runErrors.length }

// ── 4. 状态覆盖：全量加工单按比例推进 ──
const pos2 = ((await api('GET', '/api/admin/processing-orders', { token })).json?.data || []).filter((p) => mine.some((o) => String(o.id) === String(p.orderId)))
const act = async (po, action, reason) => {
  const r = await api('PATCH', `/api/admin/processing-orders/${po.id}`, { token, body: { action, ...(reason ? { reason } : {}) } })
  if (r.json?.success !== true) R.errors.push({ stage: `po-${action}`, no: po.processingOrderNo, status: po.status, msg: JSON.stringify(r.json?.error || r.json).slice(0, 140) })
  return r.json?.success === true
}
R.posTotal = pos2.length
const gen = () => pos2.filter((p) => p.status === 'generated')
const nIssued = Math.round(pos2.length * 0.20), nInProc = Math.round(pos2.length * 0.25),
  nDone = Math.round(pos2.length * 0.25), nCancel = Math.round(pos2.length * 0.10)
let pool = gen()
const take = (k) => pool.splice(0, k)
for (const po of take(nIssued)) await act(po, 'issue')
const inProcPos = take(nInProc)
for (const po of inProcPos) { await act(po, 'issue'); await act(po, 'start') }
const donePos = take(nDone)
for (const po of donePos) { await act(po, 'issue'); await act(po, 'start'); await act(po, 'complete') }
for (const po of take(nCancel)) await act(po, 'cancel', `${PREFIX}演示：随机取消样本`)
log(`状态推进完成（加工单 ${pos2.length} 张）`)

// ── 5. 工人 + 报工链路 ──
const workers = []
for (let i = 0; i < 6; i++) {
  const workerNo = `${PREFIX}W${String(Date.now()).slice(-6)}${i}`
  const pin = String(rint(100000, 999999))
  const w = await api('POST', '/api/admin/workers', { token, body: { workerNo, name: `${PREFIX}工人${i}`, pin } })
  if (w.json?.success === true) workers.push({ workerNo, pin })
  else R.errors.push({ stage: 'worker', workerNo, msg: JSON.stringify(w.json?.error || w.json).slice(0, 140) })
}
const sessions = []
for (const w of workers) {
  const r = await api('POST', '/api/worker/login', { body: { workerNo: w.workerNo, pin: w.pin, deviceLabel: `${PREFIX}-PAD`, tenantId: T } })
  const sid = r.json?.data?.session_id || r.json?.data?.sessionId
  if (sid) sessions.push({ ...w, sid })
  else R.errors.push({ stage: 'worker-login', workerNo: w.workerNo, msg: JSON.stringify(r.json?.error || r.json).slice(0, 140) })
}
const rerun = ((await api('GET', '/api/admin/processing-orders', { token })).json?.data || []).filter((p) => mine.some((o) => String(o.id) === String(p.orderId)))
const reportable = [...rerun.filter((p) => p.status === 'in_processing'), ...rerun.filter((p) => p.status === 'completed')].slice(0, 80)
let posReported = 0, opsReported = 0, reportFail = 0
for (const po of reportable) {
  const wk = pick(sessions); if (!wk) break
  const opsRes = await api('GET', `/api/admin/production/orders/${po.orderId}/operations`, { token })
  const flat = (opsRes.json?.data?.positions || []).flatMap((p) => (p.operations || []).map((o) => ({ ...o })))
  if (!flat.length) continue
  const count = Math.min(po.status === 'completed' ? flat.length : rint(1, 4), 6)
  for (const op of flat.slice(0, count)) {
    const id = op.id ?? op.operation_id ?? op.operationId
    if (!id) continue
    const need = Number(op.qty ?? op.planned_qty ?? 1)
    const qty = po.status === 'completed' ? need : rdec(0.3, Math.max(0.4, need * 0.6), 2)
    const r = await api('POST', `/api/worker/production/orders/${po.orderId}/operations/${id}/report`, {
      body: { qty, qualified_qty: qty, work_type: rnd() < 0.12 ? 'rework' : 'normal' },
      headers: { 'X-Worker-Session-Id': wk.sid },
    })
    if (r.json?.success === true) opsReported++
    else { reportFail++; if (reportFail <= 5) R.errors.push({ stage: 'report', po: po.processingOrderNo, msg: JSON.stringify(r.json?.error || r.json).slice(0, 140) }) }
  }
  posReported++
}
log(`报工：${posReported} 张单 / ${opsReported} 道工序（失败 ${reportFail}）`)
R.workers = { created: workers.length, sessions: sessions.length }
R.report = { posReported, opsReported, reportFail }

// ── 6. 验收读数（全走 API） ──
const finalPos = ((await api('GET', '/api/admin/processing-orders', { token })).json?.data || []).filter((p) => mine.some((o) => String(o.id) === String(p.orderId)))
const statusCount = {}
for (const p of finalPos) statusCount[p.status] = (statusCount[p.status] || 0) + 1
const period = new Date().toISOString().slice(0, 7)
const pw = (await api('GET', `/api/admin/production/piecework/summary?period=${period}`, { token })).json?.data
const board = (await api('GET', '/api/admin/batch-stock/saving-board?granularity=month', { token })).json?.data?.total
const cons1 = (await api('GET', '/api/admin/batch-stock/consumptions?page=1&size=1', { token })).json?.data
const poolLeft = (await api('GET', '/api/admin/production/pool', { token })).json?.data
R.final = {
  orders: mine.length, pos: finalPos.length, statusCount,
  piecework: { total: pw?.total, perWorker: (pw?.per_worker || []).length, perOperation: (pw?.per_operation || []).length },
  savingBoard: board, consumptionRows: cons1?.total, poolLeft: poolLeft?.orderCount,
}
writeFileSync(`${OUTDIR}/evidence/seed-demo.json`, JSON.stringify(R, null, 2))
console.log('\n===== 最终读数 =====')
console.log(JSON.stringify(R.final, null, 1))
console.log('errors:', R.errors.length, 'runErrors:', R.runErrors.length)
