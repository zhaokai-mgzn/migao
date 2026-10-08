// P6：**工序级设置项**闭环（作用域 scope / 标记生产开始 is_start_marker）——改一处 → 派工必须随之变
//
// 这两项是「工序设置」页可直接改的档位（#4384 A1），直接影响「一樘里落几次」与「谁触发开工」。
import { api, loginApi, psql, one, log, waitService, Recorder } from './lib.mjs'

const T = Number(process.env.TENANT_ID || 20)
const PHONE = process.env.ADMIN_PHONE || '13870217889'
const RUN = String(Date.now()).slice(-6)
const BASE_PI = {
  colorName: '本白', unit: '米', sellingMethod: 'bulk_cut',
  fabric_meters: 12.3, pleat_count: 40, panels: 2, holes: 24,
  processingItems: [{ id: 'pi_base', name: '锁边', quantity: 1, unit: '米' }],
}
let token, ctx

async function mkProduct() {
  const cat = await api('POST', '/api/admin/categories', { token, body: { name: `设置验收分类${RUN}`, sortOrder: 1 } })
  const prod = await api('POST', '/api/admin/products', {
    token, body: {
      name: `设置验收商品${RUN}`, unit: '米', pricingType: 'fixed', basePrice: 68,
      status: cat.json?.data?.id ? 'on_sale' : 'draft', categoryId: cat.json?.data?.id,
      colors: [{ colorName: '本白', mainColorHex: '#FAFAFA', sortOrder: 1 }],
      skus: [{ colorName: '本白', doorWidth: '2.8m', price: 68, stock: 100000, skuCode: `SET-${RUN}` }],
    },
  })
  const productId = prod.json?.data?.id
  return { productId, skuId: one(`select id::text as id from product_skus where product_id='${productId}'`)?.id }
}

/** 一樘「布+纱」（craftLineId 同组）派工；返回工序行。 */
async function dispatchClothSheer(tag) {
  const mk = (pos, i, role) => ({
    productId: ctx.productId, skuId: ctx.skuId, productName: `${tag}-${i}`, quantity: 1, unitPrice: 68, subtotal: 68,
    width: 2.8, height: 2.6,
    processingInfo: { ...BASE_PI, sku: ctx.skuId, curtainType: pos, craft: '罗马帘', craftLineId: `W-${tag}`,
      ...(role ? { componentRole: role } : {}) },
  })
  const order = await api('POST', '/api/admin/orders', {
    token, body: {
      customerName: `设置验收客户${RUN}`, customerPhone: '13300000006', customerAddress: '杭州市余杭区设置路 1 号',
      logisticsType: 'express', logisticsCompany: '顺丰速运', items: [mk('布帘', 0, null), mk('纱帘', 1, '纱')],
    },
  })
  const orderId = order.json?.data?.id
  if (!orderId) return { ok: false, rows: [], msg: `建单失败 HTTP ${order.status}` }
  await api('PUT', `/api/admin/orders/${orderId}/payment`, { token })
  const gen = await api('POST', '/api/admin/processing-orders/generate', { token, body: { orderIds: [orderId] } })
  const po = one(`select id, processing_order_no from processing_orders where order_id='${orderId}' order by created_at desc limit 1`)
  const rows = po ? psql(`select position_name, seq, operation_name, set_id, is_start_marker
      from processing_position_operations where processing_order_id='${po.id}' order by position_name, seq`) : []
  return { ok: gen.json?.data?.[0]?.success === true, po, rows, msg: gen.json?.data?.[0]?.message || '' }
}

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  const R = new Recorder('p6-settings.json')
  token = (await loginApi(PHONE)).token
  ctx = await mkProduct()

  // 目标 = 部位无关的套级工序「打包」：scope 改 position 后，一樘布+纱必须落 **2 行**（双付风险面）
  const pack = one(`select id, name, scope from production_operations where tenant_id=${T} and name='打包' and coalesce(deleted,0)=0`)
  const before = await dispatchClothSheer('S0')
  const n0 = before.rows.filter((r) => r.operation_name === '打包').length

  try {
    const up = await api('PUT', `/api/admin/production/operations/${pack.id}`, { token, body: { scope: 'position' } })
    const after = await dispatchClothSheer('S1')
    const n1 = after.rows.filter((r) => r.operation_name === '打包').length
    // 还原
    await api('PUT', `/api/admin/production/operations/${pack.id}`, { token, body: { scope: pack.scope } })
    const back = await dispatchClothSheer('S2')
    const n2 = back.rows.filter((r) => r.operation_name === '打包').length
    n0 === 1 && n1 === 2 && n2 === 1 && up.status === 200
      ? R.pass('W-09', '作用域改配（set→position）双向生效：一樘布+纱从 1 行变 2 行，还原回 1 行',
          `打包 scope=${pack.scope} ⇒ ${n0} 行；改 position ⇒ ${n1} 行；还原 ⇒ ${n2} 行（加工单 ${after.po?.processing_order_no}）`,
          [`PUT /api/admin/production/operations/${pack.id} {scope:'position'}`,
           `SQL: select operation_name,position_name,set_id from processing_position_operations where processing_order_id='${after.po?.id}'`])
      : R.fail('W-09', '作用域改配双向生效', `改前 ${n0} 行 / 改后 ${n1} 行 / 还原后 ${n2} 行（期望 1/2/1）；PUT HTTP ${up.status}`)
  } catch (e) {
    await api('PUT', `/api/admin/production/operations/${pack.id}`, { token, body: { scope: pack.scope } }).catch(() => {})
    R.fail('W-09', '作用域改配双向生效', String(e).slice(0, 300))
  }

  // 「标记生产开始」改配：把 打包 设为 start marker ⇒ 实例 is_start_marker 必须跟着变
  try {
    const up = await api('PUT', `/api/admin/production/operations/${pack.id}`, { token, body: { is_start_marker: true } })
    const d = await dispatchClothSheer('S3')
    const rows = d.rows.filter((r) => r.operation_name === '打包')
    await api('PUT', `/api/admin/production/operations/${pack.id}`, { token, body: { is_start_marker: false } })
    const allMarked = rows.length > 0 && rows.every((r) => r.is_start_marker === true)
    up.status === 200 && allMarked
      ? R.pass('W-10', '「标记生产开始」改配 → 实例 is_start_marker 跟随（开工触发点可配）',
          `打包 is_start_marker=true ⇒ 实例 ${rows.map((r) => r.is_start_marker).join('/')}（${rows.length} 行）`,
          [`PUT /api/admin/production/operations/${pack.id} {is_start_marker:true}`])
      : R.fail('W-10', '「标记生产开始」改配 → 实例跟随', `PUT HTTP ${up.status}；实例 is_start_marker=${rows.map((r) => r.is_start_marker).join('/') || '（无行）'}`)
  } catch (e) {
    await api('PUT', `/api/admin/production/operations/${pack.id}`, { token, body: { is_start_marker: false } }).catch(() => {})
    R.fail('W-10', '「标记生产开始」改配', String(e).slice(0, 300))
  }

  const fin = one(`select scope, is_start_marker, status from production_operations where id='${pack.id}'`)
  log(`收尾核对：打包 scope=${fin?.scope} is_start_marker=${fin?.is_start_marker} status=${fin?.status}（应与基线 scope=${pack.scope} / false 一致）`)
  log(`summary=${JSON.stringify(R.summary())}`)
}

main().catch((e) => { console.error(e); process.exit(1) })
