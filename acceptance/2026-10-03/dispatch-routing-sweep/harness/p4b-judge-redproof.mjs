// P4b：**判据同源红证** —— 直接用 p2 矩阵自己的 `judge()`（而非另写一套比较器）证明每道门都会红
//
// 为什么单列（独立复核 AI 2026-10-03 指出）：原 p4 的红证用的是**另一份** dispatch/seqEquals，
// 推不出「p2 的 44 条断言都有判别力」。本文件把 p2 的 judge 当被测对象：
// 同一份**真实实得结果**，只改「期望」或「实得行」，逐门验证会红。
import { api, loginApi, one, log, waitService, Recorder } from './lib.mjs'
import { judge, CAT, PRICE } from './p2-matrix.mjs'

const T = Number(process.env.TENANT_ID || 20)
const PHONE = process.env.ADMIN_PHONE || '13870217889'
const RUN = String(Date.now()).slice(-6)
const BASE_PI = {
  colorName: '本白', unit: '米', sellingMethod: 'bulk_cut',
  fabric_meters: 12.3, pleat_count: 40, panels: 2, holes: 24,
  processingItems: [{ id: 'pi_base', name: '锁边', quantity: 1, unit: '米' }],
}
let token, ctx

const EXPECTED = ['精裁-布', '布三边', '熨烫-布', '定型-布', '复烫-布', '布帘车被', '外帘打卷', '打包', '外帘装袋', '外帘发货']
const SCEN = { id: 'RX', title: '红证场景（布帘 × 罗马帘 主线十道）', pos: '布帘', craft: '罗马帘', expect: EXPECTED }

async function dispatch() {
  const order = await api('POST', '/api/admin/orders', {
    token, body: {
      customerName: `判据红证客户${RUN}`, customerPhone: '13300000008', customerAddress: '杭州市余杭区判据路 1 号',
      logisticsType: 'express', logisticsCompany: '顺丰速运',
      items: [{
        productId: ctx.productId, skuId: ctx.skuId, productName: `RX-${RUN}`, quantity: 1, unitPrice: 68, subtotal: 68,
        width: 2.8, height: 2.6,
        processingInfo: { ...BASE_PI, sku: ctx.skuId, curtainType: '布帘', craft: '罗马帘' },
      }],
    },
  })
  const orderId = order.json?.data?.id
  await api('PUT', `/api/admin/orders/${orderId}/payment`, { token })
  const gen = await api('POST', '/api/admin/processing-orders/generate', { token, body: { orderIds: [orderId] } })
  const po = one(`select id, processing_order_no from processing_orders where order_id='${orderId}' order by created_at desc limit 1`)
  const rows = po ? await api('GET', `/api/admin/production/orders/${orderId}/operations`, { token }) : null
  const dbRows = po ? (await import('./lib.mjs')).psql(`select seq, position_name, operation_name, group_name, unit,
      qty::text as qty, unit_price::text as unit_price, qty_source from processing_position_operations
      where processing_order_id='${po.id}' order by seq`) : []
  return { orderId, po, gen, res: gen.json?.data?.[0], rows: dbRows, readFace: rows?.json?.data }
}

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  const R = new Recorder('p4b-judge-redproof.json')
  token = (await loginApi(PHONE)).token
  const cat = await api('POST', '/api/admin/categories', { token, body: { name: `判据红证分类${RUN}`, sortOrder: 1 } })
  const prod = await api('POST', '/api/admin/products', {
    token, body: {
      name: `判据红证商品${RUN}`, unit: '米', pricingType: 'fixed', basePrice: 68,
      status: cat.json?.data?.id ? 'on_sale' : 'draft', categoryId: cat.json?.data?.id,
      colors: [{ colorName: '本白', mainColorHex: '#FAFAFA', sortOrder: 1 }],
      skus: [{ colorName: '本白', doorWidth: '2.8m', price: 68, stock: 100000, skuCode: `JDG-${RUN}` }],
    },
  })
  ctx = { productId: prod.json?.data?.id, skuId: one(`select id::text as id from product_skus where product_id='${prod.json?.data?.id}'`)?.id }

  // 填 p2 的判据表（与 p2 同一读面：工序库 + 工艺项价目）
  for (const g of (await api('GET', '/api/admin/production/operations-catalog', { token })).json?.data?.groups || []) {
    for (const o of g.operations) CAT.set(o.library_name, { unit: o.unit, scope: o.scope, group: o.group, name: o.name })
  }
  for (const row of (await api('GET', '/api/admin/production/operation-positions', { token })).json?.data || []) {
    PRICE.set(row.operation, row.unit_price == null ? null : row.unit_price)
  }
  log(`判据表：工序 ${CAT.size} / 价目 ${PRICE.size} 行`)

  const out = await dispatch()
  const clone = () => ({ ...out, rows: out.rows.map((r) => ({ ...r })) })
  const problems = (sc, o) => judge(sc, o, []).problems
  const results = {}
  try {
    // ① 基线：真实结果 × 正确期望 ⇒ 必须绿
    results.greenBaseline = judge(SCEN, clone(), []).pass === true
    // ② 期望换序 ⇒ 红
    const swapped = [...EXPECTED]; [swapped[2], swapped[3]] = [swapped[3], swapped[2]]
    results.redOnSwap = judge({ ...SCEN, expect: swapped }, clone(), []).pass === false
    // ③ 期望少一道 ⇒ 红（漏工序必须可见）
    results.redOnShort = judge({ ...SCEN, expect: EXPECTED.slice(0, 9) }, clone(), []).pass === false
    // ④ **实得行漏一道**（模拟产品漏生成工序）⇒ 红
    const dropped = clone(); dropped.rows = dropped.rows.filter((r) => r.operation_name !== '定型-布')
    dropped.rows.forEach((r, i) => { r.seq = i + 1 })
    results.redOnDroppedRow = judge(SCEN, dropped, []).pass === false
    // ⑤ **单价门**：把实例单价篡改成 0（期望 0.35）⇒ 必须红（审计指出的「静默门」）
    const priced = clone(); priced.rows.find((r) => r.operation_name === '熨烫-布').unit_price = '0.00'
    results.redOnPrice0 = judge(SCEN, priced, []).pass === false
    const rolled = clone(); rolled.rows.find((r) => r.operation_name === '打包').unit_price = '0.00'  // 打包 未定价(null) ⇒ 回落 0 必须红
    results.redOnUnpricedFallback = judge(SCEN, rolled, []).pass === false
    // ⑥ **数量门**：数量改成 0 ⇒ 红
    const zero = clone(); zero.rows[0].qty = '0.00'
    results.redOnQtyZero = judge(SCEN, zero, []).pass === false
    // ⑦ **未知单位门**：把某行单位改成值域外的值 ⇒ 红
    const unit = clone(); unit.rows[0].unit = '打'
    results.redOnUnknownUnit = judge(SCEN, unit, []).pass === false
    // ⑧ **空结果门**：0 行 ⇒ 红
    results.redOnEmpty = judge(SCEN, { ...clone(), rows: [] }, []).pass === false
    // ⑨ **价目行缺失门**：删掉价目表里该逻辑工序 ⇒ 单价断言不得静默跳过，必须红
    const saved = PRICE.get('熨烫'); PRICE.delete('熨烫')
    results.redOnMissingPriceRow = judge(SCEN, clone(), []).pass === false
    if (saved !== undefined) PRICE.set('熨烫', saved)
    // ⑩ 取路失败门（正向签名）：只认「引用的工序…不存在」；无加工项这类无关失败必须红
    const failSc = { id: 'RF', title: '取路失败签名', pos: '纱帘', craft: '罗马帘', options: ['拼1次'], expectFail: true, expectFailNames: ['拼1次'] }
    results.greenOnRealRouteFailure = judge(failSc, { res: { success: false, message: '工艺路线「X」（产品形态「纱帘」）引用的工序 [拼1次] 在工序库中不存在，无法实例化工序' }, po: null, rows: [] }, []).pass === true
    results.redOnUnrelatedFailure = judge(failSc, { res: { success: false, message: '订单 X 无加工项，无需生成加工单' }, po: null, rows: [] }, []).pass === false
  } catch (e) {
    R.fail('JDG-00', '判据红证执行', String(e).slice(0, 300))
  }

  const bad = Object.entries(results).filter(([k, v]) => k.startsWith('red') && !v).map(([k]) => k)
  const badGreen = Object.entries(results).filter(([k, v]) => k.startsWith('green') && !v).map(([k]) => k)
  bad.length === 0 && badGreen.length === 0
    ? R.pass('JDG-01', 'p2 矩阵 judge() 同源红证：9 道门全部会红、2 道正向必绿',
        `加工单 ${out.po?.processing_order_no}；读数 ${JSON.stringify(results)}`,
        [`import { judge } from './p2-matrix.mjs'`, `SQL: select operation_name,qty,unit,unit_price from processing_position_operations where processing_order_id='${out.po?.id}'`])
    : R.fail('JDG-01', 'p2 矩阵 judge() 同源红证', `该红未红：${bad.join(',') || '无'}；该绿未绿：${badGreen.join(',') || '无'}；读数 ${JSON.stringify(results)}`)

  // 读面与落库（顺带复核，与 P7 同口径）
  const dbByPos = {}
  for (const r of out.rows) (dbByPos[r.position_name] ||= []).push(r.operation_name)
  const apiByPos = {}
  for (const p of out.readFace?.positions || []) apiByPos[p.position_name] = (p.operations || []).map((o) => o.operation)
  JSON.stringify(dbByPos) === JSON.stringify(apiByPos)
    ? R.pass('JDG-02', '本单读面 == 落库（按部位逐道）', `${Object.keys(dbByPos).join('/')}；共 ${out.rows.length} 道`)
    : R.fail('JDG-02', '本单读面 == 落库', JSON.stringify(apiByPos))

  log(`summary=${JSON.stringify(R.summary())}`)
}

main().catch((e) => { console.error(e); process.exit(1) })
