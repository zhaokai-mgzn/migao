// P4：**红证**（判别力自证）—— 「把被测行为改坏，它会红吗？」
//  ⓐ 判据层：同一份实得序列，故意错配期望 ⇒ 必须红（证明不是恒真/子集比较）
//  ⓑ 注入层：临时改**真实配置**（默认主线去掉一道 / 矩阵格改价）⇒ 派工结果随之变 ⇒ 断言必须红
//  ⓒ 还原层：注入还原后断言回到绿（证明红是注入造成的，不是长期红灯）
import { api, loginApi, psql, one, log, waitService, Recorder } from './lib.mjs'

const T = Number(process.env.TENANT_ID || 20)
const PHONE = process.env.ADMIN_PHONE || '13870217889'
const RUN = String(Date.now()).slice(-6)
const PROBE = '定型'   // 注入对象：默认主线里的「定型」（布帘 → 定型-布）
const BASE_PI = {
  colorName: '本白', unit: '米', sellingMethod: 'bulk_cut',
  fabric_meters: 12.3, pleat_count: 40, panels: 2, holes: 24,
  processingItems: [{ id: 'pi_base', name: '锁边', quantity: 1, unit: '米' }],
}
let token, ctx

async function dispatch(tag) {
  const order = await api('POST', '/api/admin/orders', {
    token, body: {
      customerName: `红证客户${RUN}`, customerPhone: '13300000005', customerAddress: '杭州市余杭区红证路 1 号',
      logisticsType: 'express', logisticsCompany: '顺丰速运',
      items: [{
        productId: ctx.productId, skuId: ctx.skuId, productName: `${tag}-${RUN}`, quantity: 1, unitPrice: 68, subtotal: 68,
        width: 2.8, height: 2.6,
        processingInfo: { ...BASE_PI, sku: ctx.skuId, curtainType: '布帘', craft: '罗马帘' },
      }],
    },
  })
  const orderId = order.json?.data?.id
  await api('PUT', `/api/admin/orders/${orderId}/payment`, { token })
  const gen = await api('POST', '/api/admin/processing-orders/generate', { token, body: { orderIds: [orderId] } })
  const po = one(`select id, processing_order_no from processing_orders where order_id='${orderId}' order by created_at desc limit 1`)
  const rows = po ? psql(`select seq, operation_name, qty::text as qty, unit_price::text as unit_price
      from processing_position_operations where processing_order_id='${po.id}' order by seq`) : []
  return { ok: gen.json?.data?.[0]?.success === true, orderId, po, rows, msg: gen.json?.data?.[0]?.message || '' }
}
const names = (r) => r.rows.map((x) => x.operation_name)

/** 判据函数（与 p2 同口径：逐字全序比较）—— 用于离线判别力自证。 */
const seqEquals = (actual, expected) => JSON.stringify(actual) === JSON.stringify(expected)

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  const R = new Recorder('p4-redproof.json')
  token = (await loginApi(PHONE)).token
  const cat = await api('POST', '/api/admin/categories', { token, body: { name: `红证分类${RUN}`, sortOrder: 1 } })
  const prod = await api('POST', '/api/admin/products', {
    token, body: {
      name: `红证商品${RUN}`, unit: '米', pricingType: 'fixed', basePrice: 68, status: cat.json?.data?.id ? 'on_sale' : 'draft',
      categoryId: cat.json?.data?.id, colors: [{ colorName: '本白', mainColorHex: '#FAFAFA', sortOrder: 1 }],
      skus: [{ colorName: '本白', doorWidth: '2.8m', price: 68, stock: 100000, skuCode: `RED-${RUN}` }],
    },
  })
  ctx = { productId: prod.json?.data?.id, skuId: null }
  ctx.skuId = one(`select id::text as id from product_skus where product_id='${ctx.productId}'`)?.id

  const routings = (await api('GET', '/api/admin/production/routings', { token })).json?.data?.routings || []
  const def = routings.find((r) => r.is_default)
  const MAIN0 = [...def.mainline]
  const EXPECTED = ['精裁-布', '布三边', '熨烫-布', '定型-布', '复烫-布', '布帘车被', '外帘打卷', '打包', '外帘装袋', '外帘发货']

  // ⓐ 判据层判别力：同一份实得序列 —— 原样必绿 / 错配必红
  try {
    const d = await dispatch('R0')
    const actual = names(d)
    const green = seqEquals(actual, EXPECTED)
    const swapped = [...EXPECTED]; [swapped[2], swapped[3]] = [swapped[3], swapped[2]]
    const redOnSwap = !seqEquals(actual, swapped)
    const redOnShort = !seqEquals(actual, EXPECTED.slice(0, 9))
    green && redOnSwap && redOnShort
      ? R.pass('R-01', '判据判别力自证：原样绿 / 换位红 / 少一道红（非恒真、非子集比较）',
          `实得 ${actual.length} 道；换位 2 与 3 ⇒ 红 ✅；少最后一道 ⇒ 红 ✅`,
          [`加工单 ${d.po?.processing_order_no}`, `SQL: select operation_name from processing_position_operations where processing_order_id='${d.po?.id}' order by seq`])
      : R.fail('R-01', '判据判别力自证', `原样绿=${green} 换位红=${redOnSwap} 少一道红=${redOnShort}；实得=${actual.join(',')}`)
  } catch (e) { R.fail('R-01', '判据判别力自证', String(e).slice(0, 300)) }

  // ⓑ 注入层：真实配置去掉「定型」⇒ 派工必须少一道 ⇒ 原期望断言必须红
  let injected = false
  try {
    const inj = await api('PUT', `/api/admin/production/routings/${def.id}`, { token, body: { mainline: MAIN0.filter((x) => x !== PROBE) } })
    const back = one(`select mainline::text as m from production_route_templates where id='${def.id}'`)?.m || ''
    injected = inj.status === 200 && !back.includes(PROBE)
    const d = await dispatch('R1')
    const actual = names(d)
    const differs = !seqEquals(actual, EXPECTED)
    const lacks = !actual.includes('定型-布')
    injected && differs && lacks
      ? R.pass('R-02', `注入「默认主线去掉${PROBE}」⇒ 派工确实少一道、断言判红（判别性红证）`,
          `注入后 mainline=${back}；派工 ${actual.join(' → ')}（共 ${actual.length} 道，无 定型-布）⇒ 与基线期望不符 = 红`,
          [`PUT /api/admin/production/routings/${def.id} {mainline 去掉 定型}`, `SQL: select mainline from production_route_templates where id='${def.id}'`])
      : R.fail('R-02', '注入式红证（主线去工序）', `注入生效=${injected}（mainline=${back}）差异=${differs} 缺定型=${lacks}`)
  } catch (e) { R.fail('R-02', '注入式红证（主线去工序）', String(e).slice(0, 300)) }
  finally {
    if (injected) await api('PUT', `/api/admin/production/routings/${def.id}`, { token, body: { mainline: MAIN0 } })
  }

  // ⓒ 还原层：注入还原后必须回到绿
  try {
    const back = one(`select mainline::text as m from production_route_templates where id='${def.id}'`)?.m || ''
    const d = await dispatch('R2')
    const actual = names(d)
    seqEquals(actual, EXPECTED) && back.includes(PROBE)
      ? R.pass('R-03', '还原后回到绿（红是注入造成的，不是长期红灯）',
          `mainline 还原=${back}；派工 ${actual.length} 道与基线期望逐字相同`, [`PUT /api/admin/production/routings/${def.id} {mainline 还原}`])
      : R.fail('R-03', '还原后回到绿', `mainline=${back}；派工=${actual.join(',')}`)
  } catch (e) { R.fail('R-03', '还原后回到绿', String(e).slice(0, 300)) }

  // ⓓ 价格断言判别力：矩阵格改价 0.99 ⇒ 原期望（0.40）断言必须红 ⇒ 还原后回绿
  try {
    const row = one(`select id, unit_price::text as p from production_operation_positions where tenant_id=${T} and logical_name='熨烫' and coalesce(deleted,0)=0`)
    const orig = row?.p
    await api('PUT', `/api/admin/production/operation-positions/${row.id}`, { token, body: { unit_price: 0.99 } })
    const d1 = await dispatch('R3')
    const hit1 = d1.rows.find((r) => r.operation_name === '熨烫-布')
    const redOnPrice = hit1 && Number(hit1.unit_price) !== Number(orig)
    await api('PUT', `/api/admin/production/operation-positions/${row.id}`, { token, body: { unit_price: Number(orig) } })
    const d2 = await dispatch('R4')
    const hit2 = d2.rows.find((r) => r.operation_name === '熨烫-布')
    const greenBack = hit2 && Number(hit2.unit_price) === Number(orig)
    redOnPrice && greenBack
      ? R.pass('R-04', '价格断言判别力：注入新价 ⇒ 旧期望判红；还原 ⇒ 回绿',
          `熨烫-布 原价 ${orig} → 注入 0.99 ⇒ 派工读 ${hit1?.unit_price}（≠原期望 = 红）；还原 ⇒ ${hit2?.unit_price}（=原期望 = 绿）`,
          [`PUT /api/admin/production/operation-positions/${row.id} {unit_price:0.99}`, `PUT … {unit_price:${orig}}`])
      : R.fail('R-04', '价格断言判别力', `注入后=${hit1?.unit_price}（原 ${orig}）红=${redOnPrice}；还原后=${hit2?.unit_price} 绿=${greenBack}`)
  } catch (e) { R.fail('R-04', '价格断言判别力', String(e).slice(0, 300)) }

  const finalMain = one(`select mainline::text as m from production_route_templates where id='${def.id}'`)?.m
  log(`收尾核对：mainline=${finalMain}（应与基线逐字相同）`)
  log(`summary=${JSON.stringify(R.summary())}`)
}

main().catch((e) => { console.error(e); process.exit(1) })
