// 2026-10-06 演示数据批量落地（**保留**，不清理）—— 用户 14:01 +08 要求：
//   ① 重造一批，数字全随机 ② 仍在租户 25 ③ 加工单保留 ④ 300 单覆盖全部加工状态与不同进度
//   ⑤ 顺带把 **报工链路** 与 **计件链路** 也跑一批并验证
//
// 🔴 本脚本**只走 admin-api HTTP**（不依赖 psql —— 云 dev RDS 公网/内网端口本机当前均不可达）。
// 🔴 数据**刻意保留**（前缀 `SD07演示`）；清理口径见文末 CLEANUP 提示。
import { api } from './lib.mjs'
import { login, T } from './steps.mjs'
import { writeFileSync, mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const OUTDIR = fileURLToPath(new URL('../out/', import.meta.url)).replace(/\/$/, '')
const PREFIX = process.env.DEMO_PREFIX || 'SD07演示'
const N = Number(process.env.N || 300)
const t0 = Date.now()
const R = { at: new Date().toISOString(), prefix: PREFIX, n: N, phases: {}, errors: [] }
const log = (...a) => console.log(`[${((Date.now() - t0) / 1000).toFixed(0)}s]`, ...a)

// ── 随机数（**确定性种子** ⇒ 同一次运行可复现；不同运行 stamp 不同）──
let seed = Number(process.env.SEED || Date.now() % 1000000)
const rnd = () => ((seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff)
const pick = (a) => a[Math.floor(rnd() * a.length)]
const rint = (lo, hi) => lo + Math.floor(rnd() * (hi - lo + 1))
const rdec = (lo, hi, d = 1) => Number((lo + rnd() * (hi - lo)).toFixed(d))
R.seed = seed

const token = await login()
R.phases.login = true

// ══════════ 阶段 A：探针商品 / SKU / 入库批次（走 API）══════════
const stamp = String(Date.now()).slice(-6)
const cat = await api('POST', '/api/admin/categories', { token, body: { name: `${PREFIX}类${stamp}`, sortOrder: 1 } })
const categoryId = cat.json?.data?.id
if (!categoryId) throw new Error(`分类创建失败 HTTP ${cat.status} ${JSON.stringify(cat.json).slice(0, 200)}`)

const COLOR = ['雾霾蓝', '奶油白', '燕麦色', '墨绿', '莫兰迪灰', '咖色', '米白', '奶茶色']
const DOORS = ['2.8', '3.0', '3.2']
const skus = []
for (let i = 0; i < 4; i++) {
  const color = COLOR[i]
  const door = DOORS[i % DOORS.length]
  const doorText = `${door}m`   // 🔴 下单时必须逐字回传（含 m）：实测写 "3" ⇒ 422「无法定位到 SKU（下单）」
  const code = `${PREFIX}-${door}-${stamp}${i}`
  const prod = await api('POST', '/api/admin/products', {
    token, body: {
      name: `${PREFIX}布${stamp}-${i}`, unit: '米', pricingType: 'fixed',
      basePrice: rdec(45, 160, 0), status: 'on_sale', categoryId,
      colors: [{ colorName: color, mainColorHex: '#EDEDED', sortOrder: 1 }],
      skus: [{ colorName: color, doorWidth: doorText, price: rdec(45, 160, 0), stock: 0, skuCode: code }],
    },
  })
  const productId = prod.json?.data?.id
  if (!productId) { R.errors.push({ stage: 'product', i, msg: JSON.stringify(prod.json).slice(0, 200) }); continue }
  const list = await api('GET', `/api/admin/products/${productId}`, { token })
  const skuId = (list.json?.data?.skus || [])[0]?.id
  if (!skuId) { R.errors.push({ stage: 'sku', productId, msg: 'SKU 未返回' }); continue }
  const meters = rint(2500, 6000)
  const unitCost = rdec(25, 80, 2)
  const inb = await api('POST', '/api/admin/inbound-orders', {
    token, body: {
      supplier: `${PREFIX}供应商${i}`, warehouse: '主仓',
      inboundDate: new Date(Date.now() - rint(0, 20) * 86400000).toISOString().slice(0, 10),
      remark: `${PREFIX}入库${stamp}-${i}`,
      items: [{ productId, skuId: String(skuId), quantity: meters, unitCost, dyeLot: `DYE-${stamp}-${i}` }],
    },
  })
  const inboundId = inb.json?.data?.id
  if (!inboundId) { R.errors.push({ stage: 'inbound', i, msg: JSON.stringify(inb.json).slice(0, 200) }); continue }
  const post = await api('PATCH', `/api/admin/inbound-orders/${inboundId}`, { token, body: { action: 'post' } })
  const detail = (await api('GET', `/api/admin/products/${productId}`, { token })).json?.data
  const realSku = (detail?.skus || [])[0] || {}
  skus.push({ productId, skuId: String(skuId), skuCode: realSku.skuCode || code, color: realSku.colorName || color, door: Number(door), doorText: realSku.doorWidth || doorText, meters, unitCost, posted: post.json?.success === true })
}
R.phases.skus = skus.map((s) => ({ skuCode: s.skuCode, door: s.door, meters: s.meters, unitCost: s.unitCost, posted: s.posted }))
log(`阶段A：${skus.length} 个 SKU + 入库过账完成`)
if (!skus.length) throw new Error('没有任何可用 SKU，终止')

// ══════════ 阶段 B：300 张**随机数**订单（含随机几何/工艺/到货日/加急）══════════
const CRAFTS = ['韩褶', '打孔', '穿杆', '平幔']
const createOrder = async (i) => {
  const sku = pick(skus)
  const width = rdec(1.0, 3.0, 1)
  const height = rdec(1.0, 2.6, 1)
  const fullness = rdec(1.5, 2.5, 1)
  const cuttingMode = pick(['定宽买高', '定高买宽'])
  let quantity, panels = null
  if (cuttingMode === '定宽买高') {
    panels = Math.max(1, Math.ceil((width * fullness) / sku.door))
    quantity = Number((panels * (height + 0.3)).toFixed(1))
  } else {
    quantity = Number(Math.max(1, width * fullness).toFixed(1))
  }
  const craft = pick(CRAFTS)
  const curtainType = pick(['布帘', '布帘', '布帘', '纱帘'])
  const unitPrice = rdec(45, 160, 0)
  const urgent = rnd() < 0.08
  const dDay = rint(-6, 14)
  const requiredDeliveryDate = rnd() < 0.75 ? new Date(Date.now() + dDay * 86400000).toISOString().slice(0, 10) : null
  const body = {
    customerName: `${PREFIX}客${stamp}-${String(i).padStart(3, '0')}`,
    customerPhone: `133${String(10000000 + i).slice(-8)}`,
    customerAddress: `${PREFIX}地址${rint(1, 999)}号`,
    logisticsType: 'express', logisticsCompany: '顺丰速运', isUrgent: urgent,
    ...(requiredDeliveryDate ? { requiredDeliveryDate } : {}),
    items: [{
      productId: String(sku.productId), skuId: sku.skuId, productName: `${PREFIX}布${stamp}`,
      quantity, unitPrice, subtotal: Number((quantity * unitPrice).toFixed(2)),
      width, height,
      processingInfo: {
        sku: sku.skuCode, skuCode: sku.skuCode, colorName: sku.color, doorWidth: sku.doorText, unit: '米',
        sellingMethod: 'bulk_cut', curtainType, craft,
        cuttingMode, ...(panels ? { panels } : {}), height, fabric_meters: quantity, fullness,
        specialOptions: rnd() < 0.3 ? [pick(['加花边', '加铅块', '接高', '布绑带'])] : [],
        processingItems: [{ id: 'pi1', name: '锁边', quantity, unit: '米' }],
      },
    }],
  }
  const r = await api('POST', '/api/admin/orders', { token, body })
  const id = r.json?.data?.id
  if (!id) { R.errors.push({ stage: 'order', i, msg: JSON.stringify(r.json?.error || r.json).slice(0, 160) }); return null }
  const pay = await api('PUT', `/api/admin/orders/${id}/payment`, { token })
  if (pay.json?.success !== true) { R.errors.push({ stage: 'pay', i, msg: JSON.stringify(pay.json?.error || pay.json).slice(0, 160) }) }
  return { orderId: String(id), orderNo: r.json?.data?.orderNo, urgent, quantity, cuttingMode, panels, craft, skuCode: sku.skuCode, batchNo: null, requiredDeliveryDate }
}
const orders = []
let consecFail = 0
for (let i = 0; i < N; i++) {
  const o = await createOrder(i)
  if (o) { orders.push(o); consecFail = 0; if (orders.length % 25 === 0) log(`  建单进度 ${orders.length}/${N}`) } else if (++consecFail >= 15) { R.errors.push({ stage: 'abort', msg: `连续 3 单建单失败，提前终止（前 ${i + 1} 单）` }); break }
}
R.phases.orders = { created: orders.length, failed: R.errors.filter((e) => e.stage === 'order').length, urgent: orders.filter((o) => o.urgent).length }
log(`阶段B：订单 ${orders.length}/${N}（加急 ${R.phases.orders.urgent}）`)
if (R.errors.length) console.log('前几条错误样本:', JSON.stringify(R.errors.slice(0, 4), null, 1))

// 取每单的 order_item id（派工指派需要 itemId）
const itemOf = {}
for (const o of orders) {
  const d = await api('GET', `/api/admin/orders/${o.orderId}`, { token })
  const it = (d.json?.data?.items || [])[0]
  if (it?.id) itemOf[o.orderId] = String(it.id)
}
// 记下本 SKU 对应的批次号（用批次候选读面）
const batchOf = {}
for (const s of skus) {
  const c = await api('GET', `/api/admin/batch-stock/candidates?skuId=${s.skuId}&meters=1&assignmentRule=fifo`, { token })
  const b = (c.json?.data?.candidates || [])[0]
  batchOf[s.skuCode] = b?.batchNo ?? null
}
log(`阶段B：itemId ${Object.keys(itemOf).length} 个；批次 ${JSON.stringify(batchOf)}`)

// ══════════ 阶段 C：派单（保留加工单）—— 三种路径混合 ══════════
const assignOf = (os, rule) => ({ batches: os.map((o) => ({ orderId: o.orderId, itemId: itemOf[o.orderId] })).filter((b) => b.itemId), assignmentRule: rule, pooled: true })
const dispatch = async (os, body) => (await api('POST', '/api/admin/production/pool/dispatch', { token, body })).json?.data || []
const normal = orders.filter((o) => !o.urgent)
const urgent = orders.filter((o) => o.urgent)
const uiArm = normal.slice(0, 40)                 // 界面真实请求体：不指派批次（= 无省料）
const poolArm = normal.slice(40)                  // 带指派 + 池化（= 有省料）
R.phases.dispatch = { uiArm: 0, poolArm: 0, urgent: 0, failed: [] }
for (const o of uiArm) {
  const r = await dispatch([o.orderId], { orderIds: [o.orderId], batches: [], assignmentRule: null, pooled: true })
  r[0]?.success ? R.phases.dispatch.uiArm++ : R.phases.dispatch.failed.push({ o: o.orderNo, m: r[0]?.message })
}
for (let i = 0; i < poolArm.length; ) {
  const sz = rint(8, 15)
  const chunk = poolArm.slice(i, i + sz)
  i += sz
  const r = await dispatch(chunk.map((o) => o.orderId), assignOf(chunk, pick(['fifo', 'best_fit'])))
  R.phases.dispatch.poolArm += r.filter((x) => x.success).length
  r.filter((x) => !x.success).forEach((x) => R.phases.dispatch.failed.push({ o: x.orderRef, m: x.message }))
}
for (const o of urgent) {
  const r = await dispatch([o.orderId], { orderIds: [o.orderId], ...assignOf([o], 'fifo'), pooled: false })
  r[0]?.success ? R.phases.dispatch.urgent++ : R.phases.dispatch.failed.push({ o: o.orderNo, m: r[0]?.message })
}
log(`阶段C：派单完成 UI臂 ${R.phases.dispatch.uiArm} / 池化臂 ${R.phases.dispatch.poolArm} / 加急 ${R.phases.dispatch.urgent} / 失败 ${R.phases.dispatch.failed.length}`)

// ══════════ 阶段 D：状态覆盖（generated/issued/in_processing/completed/cancelled）══════════
const posList = (await api('GET', '/api/admin/processing-orders', { token })).json?.data || []
const minePos = posList.filter((p) => orders.some((o) => o.orderId === String(p.orderId)))
R.phases.posTotal = minePos.length
const byStatus = (s) => minePos.filter((p) => p.status === s)
const wanted = {
  generated: Math.round(minePos.length * 0.20),
  issued: Math.round(minePos.length * 0.20),
  in_processing: Math.round(minePos.length * 0.25),
  completed: Math.round(minePos.length * 0.25),
  cancelled: minePos.length - Math.round(minePos.length * 0.90),
}
const act = async (po, action, reason) => {
  const r = await api('PATCH', `/api/admin/processing-orders/${po.id}`, { token, body: { action, ...(reason ? { reason } : {}) } })
  if (r.json?.success !== true) R.errors.push({ stage: `po-${action}`, po: po.processingOrderNo, msg: JSON.stringify(r.json?.error || r.json).slice(0, 160) })
  return r.json?.success === true
}
let cursor = 0
const take = (k) => { const s = minePos.slice(cursor, cursor + wanted[k]); cursor += s.length; return s }
for (const po of take('issued')) await act(po, 'issue', null)
for (const po of take('in_processing')) { await act(po, 'issue', null); await act(po, 'start', null) }
const completedPos = take('completed')
for (const po of completedPos) { await act(po, 'issue', null); await act(po, 'start', null); await act(po, 'complete', null) }
for (const po of take('cancelled')) await act(po, 'cancel', `${PREFIX}演示：随机取消样本`)
log(`阶段D：状态推进完成（加工单 ${minePos.length} 张）`)

// ══════════ 阶段 E：工人 + 报工链路 + 计件链路 ══════════
const workers = []
for (let i = 0; i < 6; i++) {
  const workerNo = `${PREFIX}W${stamp}${i}`
  const pin = String(rint(100000, 999999))
  const w = await api('POST', '/api/admin/workers', { token, body: { workerNo, name: `${PREFIX}工人${i}`, pin } })
  if (w.json?.success === true) workers.push({ workerNo, pin, name: `${PREFIX}工人${i}`, id: w.json?.data?.id })
  else R.errors.push({ stage: 'worker', workerNo, msg: JSON.stringify(w.json?.error || w.json).slice(0, 160) })
}
const sessions = []
for (const w of workers) {
  const r = await api('POST', '/api/worker/login', { body: { workerNo: w.workerNo, pin: w.pin, deviceLabel: `${PREFIX}-PAD`, tenantId: T } })
  const sid = r.json?.data?.session_id || r.json?.data?.sessionId
  if (sid) sessions.push({ ...w, sid })
  else R.errors.push({ stage: 'worker-login', workerNo: w.workerNo, msg: JSON.stringify(r.json?.error || r.json).slice(0, 160) })
}
R.phases.workers = { created: workers.length, sessions: sessions.length }
log(`阶段E：工人 ${workers.length} 个，登录 ${sessions.length} 个`)

// 报工：in_processing 的报一部分（部分进度），completed 的报满
const reportable = [...byStatus('in_processing'), ...completedPos].slice(0, 60)
let reported = 0, opsReported = 0
for (const po of reportable) {
  const wk = pick(sessions); if (!wk) break
  const opsRes = await api('GET', `/api/admin/production/orders/${po.orderId}/operations`, { token })
  const positions = opsRes.json?.data?.positions || []
  const flat = positions.flatMap((p) => (p.operations || []).map((o) => ({ ...o, position_name: p.position_name })))
  if (!flat.length) continue
  const count = Math.min(po.status === 'completed' ? flat.length : rint(1, 4), 6)
  for (const op of flat.slice(0, count)) {
    const id = op.id ?? op.operation_id ?? op.operationId
    if (!id) continue
    const need = Number(op.qty ?? 1)
    const qty = po.status === 'completed' ? need : rdec(0.3, Math.max(0.4, need * 0.6), 2)
    const r = await api('POST', `/api/worker/production/orders/${po.orderId}/operations/${id}/report`, {
      body: { qty, qualified_qty: qty, work_type: rnd() < 0.12 ? 'rework' : 'normal' },
      headers: { 'X-Worker-Session-Id': wk.sid },
    })
    if (r.json?.success === true) { opsReported++ } else R.errors.push({ stage: 'report', po: po.processingOrderNo, op: String(id), msg: JSON.stringify(r.json?.error || r.json).slice(0, 140) })
  }
  reported++
}
R.phases.report = { posReported: reported, opsReported }
log(`阶段E：报工完成 ${reported} 张单 / ${opsReported} 道工序`)

// 计件读面
const period = new Date().toISOString().slice(0, 7)
const pw = await api('GET', `/api/admin/production/piecework/summary?period=${period}`, { token })
R.phases.piecework = { status: pw.status, period, data: pw.json?.data }
log(`阶段E：计件汇总 total=${JSON.stringify(pw.json?.data?.total)}`)

// ══════════ 阶段 F：验收读数（全部走 API）══════════
const statusCount = {}
for (const p of (await api('GET', '/api/admin/processing-orders', { token })).json?.data || []) {
  if (orders.some((o) => o.orderId === String(p.orderId))) statusCount[p.status] = (statusCount[p.status] || 0) + 1
}
R.phases.statusCoverage = statusCount
R.phases.poolAfter = (await api('GET', '/api/admin/production/pool', { token })).json?.data?.orderCount
R.phases.savingBoard = (await api('GET', `/api/admin/batch-stock/saving-board?granularity=month`, { token })).json?.data?.total
const cons = await api('GET', `/api/admin/batch-stock/consumptions?page=1&size=1`, { token })
R.phases.consumptionTotal = cons.json?.data?.total
writeFileSync(`${OUTDIR}/evidence/seed-demo.json`, JSON.stringify(R, null, 2))
console.log('\n===== 汇总 =====')
console.log(JSON.stringify({ orders: R.phases.orders, dispatch: R.phases.dispatch, pos: R.phases.posTotal, status: R.phases.statusCoverage, workers: R.phases.workers, report: R.phases.report, pieceworkTotal: R.phases.piecework.data?.total, saving: R.phases.savingBoard, consTotal: R.phases.consumptionTotal, errors: R.errors.length }, null, 1))
console.log('CLEANUP（需 psql）: 按前缀删 orders/PO/工序/消耗/工人/商品/批次，见 steps.mjs::cleanup 形态')
