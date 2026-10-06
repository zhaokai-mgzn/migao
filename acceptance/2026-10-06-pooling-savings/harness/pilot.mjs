// 2026-10-06 智能派单省料验证 · 试跑（pilot）
//
// 目的：在造 300 单之前，先用 6 张单把三件事钉死：
//   ① 界面路径的请求体（`{orderIds, batches:[], assignmentRule:null, pooled:true}`）能不能省料？
//   ② 直调路径（带指派 + fifo + pooled:true）能不能省料？省多少？
//   ③ 生成的加工单工序长什么样（供 300 单那轮写「与工艺路线比对」的判据）。
import { api } from './lib.mjs'
import { login, setupProbe, createOrder, assign, consumptions, cleanup, ordersByNoPrefix, T } from './steps.mjs'
import { psql } from './lib.mjs'
import { writeFileSync, mkdirSync } from 'node:fs'
import { OUT } from './lib.mjs'

const stamp = String(Date.now()).slice(-6)
const PREFIX = `${process.env.PROBE_PREFIX || 'SD06省料'}`
const out = { at: new Date().toISOString(), stamp, prefix: PREFIX, steps: [] }
const rec = (k, v) => { out.steps.push({ k, v }); console.log('▶', k, JSON.stringify(v)?.slice(0, 600)) }

const token = await login()
const probe = await setupProbe(token, { stamp, meters: 4000, unitCost: 40 })
rec('probe', probe)

const orders = []
for (let i = 0; i < 6; i++) orders.push(await createOrder(token, { ...probe, seq: `${stamp}${i}` }))
rec('orders', orders)

// ① 界面路径的请求体（逐字来自 frontend/admin-web/src/lib/pool-board.ts::buildPoolRequest）
const uiBody = (ids) => ({ orderIds: ids, batches: [], assignmentRule: null, pooled: true })
const filledBody = (os, pooled) => ({ orderIds: os.map((o) => o.orderId), ...assign(os, 'fifo'), pooled })

const pvUi = await api('POST', '/api/admin/production/pool/preview', { token, body: uiBody(orders.map((o) => o.orderId)) })
rec('preview_ui_body', { status: pvUi.status, data: pvUi.json?.data ?? pvUi.json })
const pvFilled = await api('POST', '/api/admin/production/pool/preview', { token, body: filledBody(orders, true) })
rec('preview_filled_body', { status: pvFilled.status, data: pvFilled.json?.data ?? pvFilled.json })

const pool = await api('GET', '/api/admin/production/pool', { token })
rec('pool', { status: pool.status, orderCount: pool.json?.data?.orderCount, groups: (pool.json?.data?.groups || []).map((g) => ({ material: g.materialLabel ?? g.productName, lines: (g.lines || []).length })) })

// ② 界面路径派单（2 单）——期望：建加工单，但零批次扣减
const dUi = await api('POST', '/api/admin/production/pool/dispatch', { token, body: uiBody(orders.slice(0, 2).map((o) => o.orderId)) })
rec('dispatch_ui_body', { status: dUi.status, results: dUi.json?.data ?? dUi.json })

// ③ 直调池化派单（4 单，带指派 + fifo）——期望：省料 > 0
const dFilled = await api('POST', '/api/admin/production/pool/dispatch', { token, body: filledBody(orders.slice(2), true) })
rec('dispatch_filled_pooled', { status: dFilled.status, results: dFilled.json?.data ?? dFilled.json })

const poRows = psql(`select po.id, po.processing_order_no, po.order_id::text as order_id, po.route_key, po.route_source, o.order_no
                     from processing_orders po join orders o on o.id=po.order_id
                     where po.tenant_id=${T} and o.customer_name like '${PREFIX}%' order by po.id`)
rec('processing_orders', poRows)
rec('consumptions', consumptions(`order_item_id in (select oi.id::text from order_items oi join orders o on o.id=oi.order_id where o.tenant_id=${T} and o.customer_name like '${PREFIX}%')`))
rec('ops_sample', psql(`select ppo.processing_order_id, ppo.position_name, ppo.seq, ppo.operation_name, ppo.group_name, ppo.unit, ppo.qty::text as qty, ppo.qty_source
                        from processing_position_operations ppo where ppo.tenant_id=${T} and ppo.processing_order_id in (
                          select po.id from processing_orders po join orders o on o.id=po.order_id where o.tenant_id=${T} and o.customer_name like '${PREFIX}%')
                        order by ppo.processing_order_id, ppo.position_name, ppo.seq limit 60`))

mkdirSync(`${OUT}/evidence`, { recursive: true })
writeFileSync(`${OUT}/pilot.json`, JSON.stringify(out, null, 2))
console.log('\n== 汇总 ==')
console.log('preview(UI体)   :', JSON.stringify(pvUi.json?.data))
console.log('preview(带指派) :', JSON.stringify(pvFilled.json?.data))
console.log('consumptions 行数:', consumptions(`order_item_id in (select oi.id::text from order_items oi join orders o on o.id=oi.order_id where o.tenant_id=${T} and o.customer_name like '${PREFIX}%')`).length)
console.log('清理：', String(cleanup(PREFIX)).slice(0, 200))
console.log('残留订单:', ordersByNoPrefix(PREFIX).length)
