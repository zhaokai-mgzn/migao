// P1 试点：跑一条最小派工链路，摸清 payload / 响应 / 落库形状（不判定，只取真值）
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { api, loginApi, psql, one, log, OUT, waitService } from './lib.mjs'

const T = Number(process.env.TENANT_ID || 20)
const PHONE = process.env.ADMIN_PHONE || '13870217889'
const stamp = String(Date.now()).slice(-6)

async function mkProduct(token) {
  const cat = await api('POST', '/api/admin/categories', { token, body: { name: `工序验收分类${stamp}`, sortOrder: 1 } })
  const categoryId = cat.json?.data?.id
  const prod = await api('POST', '/api/admin/products', {
    token, body: {
      name: `工序验收商品${stamp}`, unit: '米', pricingType: 'fixed', basePrice: 68,
      status: categoryId ? 'on_sale' : 'draft', categoryId,
      colors: [{ colorName: '本白', mainColorHex: '#FAFAFA', sortOrder: 1 }],
      skus: [{ colorName: '本白', doorWidth: '2.8m', price: 68, stock: 1000, skuCode: `DISP-${stamp}` }],
    },
  })
  const productId = prod.json?.data?.id
  const skuId = one(`select id::text as id from product_skus where product_id='${productId}'`)?.id
  return { productId, skuId }
}

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  const { token } = await loginApi(PHONE)
  const { productId, skuId } = await mkProduct(token)
  log(`商品 ${productId} / SKU ${skuId}`)

  const pi = {
    sku: skuId, colorName: '本白', doorWidth: '2.8', unit: '米', sellingMethod: 'bulk_cut',
    curtainType: '布帘', craft: '韩褶', isShaped: true,
    specialOptions: ['拼1次'],
    processingItems: [{ id: 'proc_item_1', name: '锁边', quantity: 1, unit: '米' }],
    fabric_meters: 12.3, pleat_count: 40, panels: 2, holes: 0, fullness: 2, fullness_actual: 2,
  }
  const order = await api('POST', '/api/admin/orders', {
    token, body: {
      customerName: `工序验收客户${stamp}`, customerPhone: '13300000002', customerAddress: '杭州市余杭区工序路 9 号',
      logisticsType: 'express', logisticsCompany: '顺丰速运',
      items: [{
        productId, skuId, productName: `工序验收商品${stamp}`, quantity: 1, unitPrice: 68, subtotal: 68,
        width: 2.8, height: 2.6, processingInfo: pi,
      }],
    },
  })
  const orderId = order.json?.data?.id
  log(`订单 ${orderId} HTTP ${order.status} ${order.text.slice(0, 200)}`)
  const pay = await api('PUT', `/api/admin/orders/${orderId}/payment`, { token })
  log(`收款 HTTP ${pay.status}`)
  const rowItem = one(`select id, curtain_type, craft, is_shaped, width::text as w, height::text as h, processing_info::text as pi from order_items where order_id='${orderId}'`)
  log(`order_items: ${JSON.stringify(rowItem)}`)

  const gen = await api('POST', '/api/admin/processing-orders/generate', { token, body: { orderIds: [orderId] } })
  log(`generate HTTP ${gen.status} ${gen.text.slice(0, 600)}`)
  const po = one(`select id, processing_order_no, status, route_key, route_source from processing_orders where order_id='${orderId}' order by created_at desc limit 1`)
  log(`加工单: ${JSON.stringify(po)}`)

  const opsApi = await api('GET', `/api/admin/production/orders/${orderId}/operations`, { token })
  const rows = po ? psql(`select position_name, position_kind, seq, operation_name, group_name, unit, qty::text as qty, unit_price::text as unit_price, qty_source, scope_of.op_scope as scope, is_start_marker
      from processing_position_operations ppo
      left join (select id, name, scope as op_scope from production_operations where tenant_id=${T}) scope_of on scope_of.name = ppo.operation_name
      where ppo.processing_order_id='${po.id}' order by ppo.position_name, ppo.seq`) : []
  writeFileSync(join(OUT, 'pilot.json'), JSON.stringify({ orderId, po, opsApi: opsApi.json, rows, raw: { gen: gen.json, item: rowItem } }, null, 2))
  log(`工序实例 ${rows.length} 行：`)
  for (const r of rows) log(`  ${r.position_name} | seq=${r.seq} | ${r.operation_name} | ${r.group_name} | ${r.qty}${r.unit} @${r.unit_price} | src=${r.qty_source} | scope=${r.scope}`)
  log(`读面 positions=${(opsApi.json?.data?.positions || []).length} qr=${opsApi.json?.data?.qr_token}`)
}

main().catch((e) => { console.error(e); process.exit(1) })
