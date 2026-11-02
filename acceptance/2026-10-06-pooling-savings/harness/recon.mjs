// 2026-10-06 智能派单省料验证 · 环境侦察（**只读**）
//
// 目的：动手造 300 单之前，先把「被测环境里现在有什么」钉成事实：
//   商品 / SKU / 库存批次 / 工艺路线 / 待派池 / 既有订单与加工单计数。
// 纪律：本脚本**不写任何数据**（只 GET + 只读 SQL）。
import { api, loginApi, psql, scrub } from './lib.mjs'
import { writeFileSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { OUT } from './lib.mjs'

const ADMIN_PHONE = process.env.ADMIN_PHONE || '13800138000'
const out = { at: new Date().toISOString(), adminPhone: ADMIN_PHONE, reads: {}, psql: {} }

const { token } = await loginApi(ADMIN_PHONE)
out.reads.me = (await api('GET', '/api/auth/me', { token })).json?.data

async function get(key, path) {
  const r = await api('GET', path, { token })
  out.reads[key] = { status: r.status, data: r.json?.data ?? r.json ?? r.text?.slice(0, 300) }
  return out.reads[key]
}

await get('products', '/api/admin/products?page=1&pageSize=200')
await get('routings', '/api/admin/production/routings')
await get('pool', '/api/admin/production/pool')
await get('batches', '/api/admin/batch-stock/batches')
await get('inboundBatches', '/api/admin/inbound-orders/batches')
await get('orders', '/api/admin/orders?page=1&pageSize=5')

const q = (name, sql) => {
  try { out.psql[name] = psql(sql) } catch (e) { out.psql[name] = `ERR: ${String(e.message).slice(0, 400)}` }
}
q('counts', `select
   (select count(*) from orders where tenant_id=25) as orders,
   (select count(*) from order_items oi join orders o on o.id=oi.order_id where o.tenant_id=25) as order_items,
   (select count(*) from processing_orders where tenant_id=25) as processing_orders,
   (select count(*) from processing_position_operations where tenant_id=25) as generated_ops,
   (select count(*) from products where tenant_id=25) as products,
   (select count(*) from product_skus where tenant_id=25) as skus,
   (select count(*) from stock_batches where tenant_id=25) as stock_batches,
   (select count(*) from stock_batches where tenant_id=25 and quantity > 0) as stock_batches_avail,
   (select count(*) from production_routings where tenant_id=25) as routings,
   (select count(*) from production_route_templates where tenant_id=25) as route_templates,
   (select count(*) from production_route_rules where tenant_id=25) as route_rules,
   (select count(*) from production_operations where tenant_id=25) as operations,
   (select count(*) from stock_batch_consumptions where tenant_id=25) as batch_consumptions`)
q('routing_sample', `select id, curtain_type, craft, status, source, left(operations::text, 300) as ops
   from production_routings where tenant_id=25 order by id limit 10`)
q('route_template_sample', `select id, name, is_default, status, left(positions::text,400) as positions,
   left(mainline::text,300) as mainline from production_route_templates where tenant_id=25 order by id limit 5`)
q('batch_sample', `select id, batch_no, sku_id, sku_code, quantity, unit_cost, dye_lot, roll_length_m, received_date
   from stock_batches where tenant_id=25 and quantity > 0 order by id limit 20`)
q('sku_sample', `select s.id, p.name, s.color_name, s.door_width, s.stock, s.price, s.sku_code, s.latest_batch_no
   from product_skus s join products p on p.id=s.product_id where s.tenant_id=25 order by s.id limit 20`)
q('recent_orders', `select id, order_no, status, is_urgent, required_delivery_date, created_at
   from orders where tenant_id=25 order by id desc limit 10`)
q('consumption_sample', `select id, processing_order_id, order_item_id, batch_id, delta, formula_meters, planned_meters, unit_cost
   from stock_batch_consumptions where tenant_id=25 order by id desc limit 10`)

mkdirSync(join(OUT, 'evidence'), { recursive: true })
writeFileSync(join(OUT, 'recon.json'), JSON.stringify(scrub(out), null, 2))
console.log(JSON.stringify({
  me: out.reads.me && { tenantId: out.reads.me.tenantId, nickname: out.reads.me.nickname, role: out.reads.me.role },
  statuses: Object.fromEntries(Object.entries(out.reads).map(([k, v]) => [k, v.status])),
  counts: out.psql.counts,
  productsTotal: out.reads.products?.data?.total ?? out.reads.products?.data?.length,
  routingsTotal: out.reads.routings?.data?.routings?.length ?? out.reads.routings?.data?.length,
  batchesTotal: out.reads.batches?.data?.length,
}, null, 2))
