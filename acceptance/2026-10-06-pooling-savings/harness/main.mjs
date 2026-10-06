// 2026-10-06 智能派单省料验证 · 主实验（300 单 / 四臂单变量对照）
//
// 用户要求：模拟用户批量下 300 个订单，验证 ①智能派单是否真智能 ②生成的加工单工序与配置的工艺路线
// 是否匹配 ③是否真正节省生产原材料布料。
//
// 设计（单变量）：300 张几何完全相同的可并排订单，分 4 臂各 75 张，只有「派单方式」这一个变量不同。
//   A 臂 = 界面路径：POST /production/pool/dispatch，请求体逐字 = frontend/admin-web/src/lib/pool-board.ts
//          ::buildPoolRequest 产出的 {orderIds, batches:[], assignmentRule:null, pooled:true}
//   B 臂 = 直调池化：同端点 + 逐行指派（batchNo 留空、assignmentRule=fifo）+ pooled:true
//   C 臂 = 直调逐单：同指派 + pooled:false
//   D 臂 = 订单页路径：POST /processing-orders/generate（一次一张单 + 显式指派），复刻
//          frontend/admin-web/src/components/orders/ProcessingOrderBlock.tsx::confirmAssign
//
// 几何（#5142 类注释「定宽买高 P=1 窄窗互补」受益场景）：
//   窗宽 0.7 × 褶倍 2 = 1.4 米 ≤ 门幅 2.8 ⇒ 1 幅；窗高 1.1 + 卷边 0.3 = 1.4 米
//   ⇒ 每行占门幅 1.4 米、沿卷长 1.4 米；两行并排 = 1 行（领 1.4 米），分开 = 2 行（领 2.8 米）
import { api, psql, PROBE, OUT } from './lib.mjs'
import { login, setupProbe, createOrder, assign, consumptions, cleanup, expectedRoute, logicalOperation, T } from './steps.mjs'
import { writeFileSync, mkdirSync } from 'node:fs'

const N = Number(process.env.N || 300)
const PER_ARM = N / 4
const stamp = String(Date.now()).slice(-6)
const PREFIX = PROBE
const t0 = Date.now()
const R = { at: new Date().toISOString(), stamp, prefix: PREFIX, n: N, perArm: PER_ARM, arms: {}, checks: [], residue: {} }

const token = await login()
R.probe = await setupProbe(token, { stamp, meters: 6000, unitCost: 40 })

// ── 造 300 单（已确认支付）──
const orders = []
for (let i = 0; i < N; i++) {
  orders.push(await createOrder(token, { ...R.probe, seq: `${stamp}-${String(i).padStart(3, '0')}`, idx: i }))
}
R.ordersCreated = orders.length
R.orderIds = orders.map((o) => o.orderId)
console.log(`[${((Date.now() - t0) / 1000).toFixed(0)}s] 造单 ${orders.length}`)

const arms = { A: orders.slice(0, PER_ARM), B: orders.slice(PER_ARM, 2 * PER_ARM), C: orders.slice(2 * PER_ARM, 3 * PER_ARM), D: orders.slice(3 * PER_ARM) }
const uiBody = (ids) => ({ orderIds: ids, batches: [], assignmentRule: null, pooled: true })
const filledBody = (os, pooled) => ({ orderIds: os.map((o) => o.orderId), ...assign(os, 'fifo'), pooled })

// ── 派单前的池读数 + 成批预览（两条口径并排）──
const pool = await api('GET', '/api/admin/production/pool', { token })
R.pool = { status: pool.status, orderCount: pool.json?.data?.orderCount, poolingEnabled: pool.json?.data?.poolingEnabled, groups: (pool.json?.data?.groups || []).length }
const pvUi = await api('POST', '/api/admin/production/pool/preview', { token, body: uiBody(arms.B.map((o) => o.orderId)) })
R.previewUI = pvUi.json?.data
const pvFilled = await api('POST', '/api/admin/production/pool/preview', { token, body: filledBody(arms.B, true) })
R.previewFilled = pvFilled.json?.data
console.log('preview(UI体)  :', JSON.stringify(R.previewUI))
console.log('preview(带指派):', JSON.stringify(R.previewFilled))

// ── 四臂派单 ──
const post = async (path, body) => { const r = await api('POST', path, { token, body }); return { status: r.status, data: r.json?.data, msg: (r.json?.error?.message || r.json?.message || '').slice(0, 200) } }
R.arms.A = { body: 'UI体 {batches:[], assignmentRule:null, pooled:true}', res: await post('/api/admin/production/pool/dispatch', uiBody(arms.A.map((o) => o.orderId))) }
R.arms.B = { body: '直调 {逐行指派(no batchNo), fifo, pooled:true}', res: await post('/api/admin/production/pool/dispatch', filledBody(arms.B, true)) }
R.arms.C = { body: '直调 {逐行指派(no batchNo), fifo, pooled:false}', res: await post('/api/admin/production/pool/dispatch', filledBody(arms.C, false)) }
const dRes = []
for (const o of arms.D) dRes.push(await post('/api/admin/processing-orders/generate', { orderIds: [o.orderId], batches: [{ orderId: o.orderId, itemId: o.itemId, batchNo: R.probe.batchNo }] }))
R.arms.D = { body: '订单页 {一次一张 + 显式 batchNo}', res: { status: dRes[0]?.status, ok: dRes.filter((r) => r.data?.[0]?.success).length, fail: dRes.filter((r) => !r.data?.[0]?.success).length, sample: dRes[0]?.data?.[0], failSample: dRes.find((r) => !r.data?.[0]?.success)?.data?.[0] } }
for (const k of ['A', 'B', 'C', 'D']) {
  const r = R.arms[k].res
  const list = k === 'D' ? [] : (r.data || [])
  R.arms[k].ok = k === 'D' ? r.ok : list.filter((x) => x.success).length
  R.arms[k].fail = k === 'D' ? r.fail : list.filter((x) => !x.success).length
  R.arms[k].sample = k === 'D' ? r.sample : list[0]
}
console.log(`[${((Date.now() - t0) / 1000).toFixed(0)}s] 四臂派单完成`, JSON.stringify(Object.fromEntries(Object.entries(R.arms).map(([k, v]) => [k, `${v.ok}ok/${v.fail}fail`]))))

// ── 省料读数（逐臂）──
const armOfItem = {}
for (const [k, os] of Object.entries(arms)) for (const o of os) armOfItem[o.itemId] = k
const cons = consumptions()
R.consRows = cons.length
const agg = {}
for (const c of cons) {
  const k = armOfItem[c.order_item_id] ?? '?'
  agg[k] ??= { rows: 0, formula: 0, planned: 0, saved: 0 }
  agg[k].rows++; agg[k].formula += Number(c.formula); agg[k].planned += Number(c.planned); agg[k].saved += Number(c.saved)
}
for (const k of ['A', 'B', 'C', 'D']) { agg[k] ??= { rows: 0, formula: 0, planned: 0, saved: 0 }; R.arms[k].ledger = agg[k] }
R.ledgerByArm = agg

// ── 加工单 + 工序 × 工艺路线 判据 ──
const pos = psql(`select po.id::text as po_id, po.processing_order_no, po.order_id::text as order_id, po.route_key, po.route_requested_key, po.route_source, o.customer_name
  from processing_orders po join orders o on o.id=po.order_id
  where po.tenant_id=${T} and o.customer_name like '${PREFIX}%' order by po.id`)
R.poCount = pos.length
const templates = psql(`select name, is_default, positions::text as positions, mainline::text as mainline from production_route_templates where tenant_id=${T} and status='active' and deleted=0`)
R.templates = templates
const rules = psql(`select trigger_kind, trigger_value, coalesce(position,'') as position, action, operation, coalesce(after_operation,'') as after_operation, priority\n  from production_route_rules where tenant_id=${T} and deleted=0 and status='active' order by priority, id`)
R.rulesCount = rules.length
const catalog = psql(`select name, group_name, unit from production_operations where tenant_id=${T} and status='active' and deleted=0`)
R.catalogSize = catalog.length
const ops = psql(`select ppo.processing_order_id::text as po_id, ppo.position_name, ppo.seq, ppo.operation_name, ppo.group_name, ppo.unit, ppo.qty::text as qty, ppo.qty_source
  from processing_position_operations ppo where ppo.tenant_id=${T} and ppo.processing_order_id in (
    select po.id from processing_orders po join orders o on o.id=po.order_id where o.tenant_id=${T} and o.customer_name like '${PREFIX}%')
  order by ppo.processing_order_id, ppo.position_name, ppo.seq`)
const catByName = new Map(catalog.map((c) => [c.name, c]))
const byPo = new Map()
for (const r of ops) { if (!byPo.has(r.po_id)) byPo.set(r.po_id, []); byPo.get(r.po_id).push(r) }

const defaultTpl = templates.find((t) => t.is_default) || templates[0]
const mainline = JSON.parse(defaultTpl?.mainline || '[]')
/**
 * 判据：一张加工单的工序行与「**配置的默认工艺路线**」是否匹配（会红）。
 * 期望序列由 `steps.mjs::expectedRoute`（模板主线 + 命中的条件工序规则，含锚点位置）算出——
 * 它是对**配置**的展开，不是对**实得结果**的复述。
 */
function judge(po, rows, expectSeq, catByName) {
  const kv = []
  kv.push(rows.length > 0 ? null : '无工序行')
  const seq = rows.map((r) => Number(r.seq))
  kv.push(seq.every((v, i) => v === i + 1) ? null : `seq 不连续 ${seq.join(',')}`)
  const unknown = rows.filter((r) => !catByName.has(r.operation_name)).map((r) => r.operation_name)
  kv.push(unknown.length === 0 ? null : `工序不在工序库：${unknown.join(',')}`)
  const mismatch = rows.filter((r) => { const c = catByName.get(r.operation_name); return c && (c.group_name !== r.group_name || c.unit !== r.unit) }).map((r) => r.operation_name)
  kv.push(mismatch.length === 0 ? null : `分组/单位与工序库不符：${mismatch.join(',')}`)
  const actualLogical = rows.map((r) => logicalOperation(r.operation_name))
  const sameOrder = JSON.stringify(actualLogical) === JSON.stringify(expectSeq)
  kv.push(sameOrder ? null : `与配置路线不匹配：期望 [${expectSeq.join('>')}] 实得 [${actualLogical.join('>')}]`)
  return kv.filter(Boolean)
}
const expectSeq = expectedRoute(mainline, rules, { craft: '韩褶', position: '布帘' })
R.expectedRoute = expectSeq
const judged = pos.map((po) => ({ po, rows: byPo.get(po.po_id) || [], bad: judge(po, byPo.get(po.po_id) || [], expectSeq, catByName) }))
R.routeKeySet = [...new Set(pos.map((p) => p.route_key))]
R.routeSourceSet = [...new Set(pos.map((p) => p.route_source))]
R.seqSignatureSet = [...new Set(judged.map((j) => j.rows.map((r) => `${r.seq}:${r.operation_name}`).join('>')))]
R.judge = { expected: expectSeq.join('>'), pcs: judged.length, pass: judged.filter((j) => j.bad.length === 0).length, fail: judged.filter((j) => j.bad.length > 0).length, failSamples: judged.filter((j) => j.bad.length > 0).slice(0, 3).map((j) => ({ no: j.po.processing_order_no, bad: j.bad })) }
// 红证（判据层判别力自证）：故意用一份「缺一道工序」的模板 ⇒ 同一判据必须报红
const redExpect = expectedRoute(mainline.filter((m) => m !== '打包'), rules, { craft: '韩褶', position: '布帘' })
const redProof = judged.map((j) => judge(j.po, j.rows, redExpect, catByName))
R.redProof = { injectedMissing: '打包', poFlagged: redProof.filter((x) => x.length > 0).length, total: redProof.length }
R.opsSample = ops.filter((r) => r.po_id === judged[0]?.po.po_id)
R.poOpsTotal = ops.length
R.rowInvariants = { rows: cons.length, plannedLEformula: cons.every((c) => Number(c.planned) <= Number(c.formula) + 1e-9), plannedPositive: cons.every((c) => Number(c.planned) > 0), minSaved: Math.min(...cons.map((c) => Number(c.saved))), savedAmountTotal: Number(cons.reduce((a, c) => a + Number(c.saved) * Number(c.unit_cost), 0).toFixed(2)) }
R.poPerArm = Object.fromEntries(['A', 'B', 'C', 'D'].map((k) => [k, pos.filter((p) => (arms[k] || []).some((o) => o.orderId === p.order_id)).length]))

// ── 清理 + 残留现取读数 ──
R.cleanupOut = String(cleanup(PREFIX)).trim().split('\n').slice(-3).join(' | ')
R.residue = psql(`select
  (select count(*) from orders where tenant_id=${T} and customer_name like '${PREFIX}%') orders,
  (select count(*) from processing_orders po join orders o on o.id=po.order_id where o.customer_name like '${PREFIX}%') pos,
  (select count(*) from stock_batch_consumptions where tenant_id=${T}) cons_total,
  (select count(*) from product_skus where tenant_id=${T} and sku_code like '${PREFIX}%') skus,
  (select count(*) from stock_batches where tenant_id=${T} and sku_code like '${PREFIX}%') batches,
  (select count(*) from products where tenant_id=${T} and name like '${PREFIX}%') products,
  (select count(*) from categories where tenant_id=${T} and name like '${PREFIX}%') cats,
  (select count(*) from processing_position_operations where tenant_id=${T}) ops_total`)[0]

mkdirSync(`${OUT}/evidence`, { recursive: true })
writeFileSync(`${OUT}/main.json`, JSON.stringify(R, null, 2))
console.log(`[${((Date.now() - t0) / 1000).toFixed(0)}s] 完成`)
console.log('四臂台账:', JSON.stringify(agg))
console.log('工序判据:', JSON.stringify(R.judge), 'route_key=', JSON.stringify(R.routeKeySet), 'route_source=', JSON.stringify(R.routeSourceSet))
console.log('红证:', JSON.stringify(R.redProof))
console.log('残留:', JSON.stringify(R.residue))
