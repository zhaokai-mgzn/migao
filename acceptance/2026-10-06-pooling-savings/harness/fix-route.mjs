// 2026-10-06 补工序库 + 重试滞留单（用户裁定：补工序库，补完再试）
//
// 背景（#6420）：租户 25 的默认路线有 4 条 option 规则 + 2 条 processing_item 规则插入
// `花边`/`铅坠`/`接高`，而 `ProductionOperationQueryService::variantNameOf` 的解析口径是
//   ① 硬编码变体表 `VARIANT_NAMES` 命中（logicalName + position → 变体名）
//   ② 否则**裸名兜底**：`catalogByName.containsKey(logicalName)` ⇒ 返回裸名本身
// 该表里 `花边/铅坠/接高` 只有「布帘 / 帘头」条目（且被 V97 判据逐条冻结为 30 条字面量）
// ⇒ 「纱帘」在 ① 落空、② 也落空（工序库里只有 `花边-布`，没有裸名 `花边`）⇒ 实例化 fail-closed。
//
// ⇒ **配置面修法**：往工序库补三道**部位无关**的裸名行（与既有 `打包` 同形态，position 留空），
//    于是 ② 命中 ⇒ 任意部位（含纱帘）都能解析。**不改代码、不碰冻结表、不动已发布迁移 V97。**
//    价格口径：取布帘价（`COLLAPSE_PRICE_SOURCE_POSITION = 布帘` 是既有裁定）。
import { api, psql } from './lib.mjs'
import { login, T } from './steps.mjs'
import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const OUTDIR = fileURLToPath(new URL('../out/', import.meta.url)).replace(/\/$/, '')
const BATCH = process.env.DEMO_BATCH || 'SD07演示客814127'
const R = { at: new Date().toISOString(), batch: BATCH, steps: [] }
const log = (...a) => console.log('[fix]', ...a)

// 与布帘对照行同属性（价格取布帘价）；position 留空 = 部位无关
const OPS = [
  { name: '花边', group_name: '车位', unit: '米', unit_price: 0.60, sort_order: 16 },
  { name: '铅坠', group_name: '车位', unit: '米', unit_price: 0.30, sort_order: 17 },
  { name: '接高', group_name: '车位', unit: '幅', unit_price: 1.00, sort_order: 18 },
]

const token = await login()

// ── 1. 补工序库（幂等：已在库中则跳过）──
const catRes = await api('GET', '/api/admin/production/operations-catalog', { token })
const cat = catRes.json?.data || {}
const flat = cat.operations || cat.list || cat.items || []
const have = new Set(flat.map((o) => o.name))
log(`工序库现有 ${have.size} 道；缺 ${OPS.filter((o) => !have.has(o.name)).map((o) => o.name).join('/') || '（无）'}`)
for (const op of OPS) {
  if (have.has(op.name)) { R.steps.push({ op: op.name, action: 'skip(已存在)' }); continue }
  const r = await api('POST', '/api/admin/production/operations', { token, body: op })
  R.steps.push({ op: op.name, action: 'create', status: r.status, ok: r.json?.success === true, id: r.json?.data?.id, err: r.json?.success ? undefined : JSON.stringify(r.json?.error || r.json).slice(0, 200) })
  log(`建工序「${op.name}」⇒ HTTP ${r.status} ${r.json?.success ? 'OK' : JSON.stringify(r.json?.error || r.json).slice(0, 160)}`)
}
// 复读确认
const cat2 = (await api('GET', '/api/admin/production/operations-catalog', { token })).json?.data || {}
const have2 = new Set((cat2.operations || cat2.list || cat2.items || []).map((o) => o.name))
R.afterCreate = { total: have2.size, hasBare: OPS.filter((o) => have2.has(o.name)).map((o) => o.name) }

// ── 2. 取仍无加工单的演示单（SQL 直查，避开列表 LIMIT 100）──
const rows = psql(`select o.id::text as order_id, oi.id::text as item_id, o.order_no,
                          oi.processing_info->>'curtainType' as ct,
                          coalesce(oi.processing_info->'specialOptions'::text,'[]') as opts
                   from orders o join order_items oi on oi.order_id=o.id
                   where o.tenant_id=${T} and o.deleted=0 and o.customer_name like '${BATCH}%'
                     and not exists (select 1 from processing_orders po where po.order_id=o.id)
                   order by o.id`)
R.stuckBefore = { n: rows.length, sample: rows.slice(0, 3) }
log(`仍无加工单的演示单：${rows.length} 张`)

// ── 3. 重试派单（带逐行指派 + 池化）──
const call = async (os, rule, pooled) => (await api('POST', '/api/admin/production/pool/dispatch', {
  token, body: { orderIds: os.map((o) => o.order_id), batches: os.map((o) => ({ orderId: o.order_id, itemId: o.item_id })), assignmentRule: rule, pooled },
})).json
let ok = 0
const fails = []
for (let i = 0; i < rows.length; i += 10) {
  const chunk = rows.slice(i, i + 10)
  const r = await call(chunk, 'fifo', true)
  const res = Array.isArray(r?.data) ? r.data : []
  if (!res.length) { fails.push({ n: chunk.length, msg: JSON.stringify(r?.error || r).slice(0, 200) }); continue }
  res.filter((x) => x.success).forEach(() => ok++)
  res.filter((x) => !x.success).forEach((x) => fails.push({ orderRef: x.orderRef, msg: String(x.message || '').slice(0, 180) }))
}
log(`重试派单：成功 ${ok}/${rows.length}，失败 ${fails.length}`)
R.retry = { attempted: rows.length, ok, fail: fails.length, failSamples: fails.slice(0, 5) }

// ── 4. 复核（SQL 真值）──
R.after = psql(`select
  (select count(*) from orders where tenant_id=${T} and deleted=0 and customer_name like '${BATCH}%') as orders,
  (select count(*) from processing_orders po where po.tenant_id=${T} and po.deleted=0
     and po.order_id in (select id from orders where tenant_id=${T} and customer_name like '${BATCH}%')) as pos,
  (select count(*) from orders o where o.tenant_id=${T} and o.deleted=0 and o.customer_name like '${BATCH}%'
     and not exists (select 1 from processing_orders po where po.order_id=o.id)) as no_po`)[0]
R.statusDist = psql(`select status, count(*)::text as n from processing_orders where tenant_id=${T} and deleted=0 group by status order by 2 desc`)
log(`复核：订单 ${R.after.orders} / 加工单 ${R.after.pos} / 仍无加工单 ${R.after.no_po}`)
console.log(JSON.stringify(R, null, 1))
writeFileSync(`${OUTDIR}/evidence/fix-route.json`, JSON.stringify(R, null, 2))
