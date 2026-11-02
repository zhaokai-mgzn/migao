// P9：**改工序设置会不会静默改价？**（本轮复核中由 P6 的 PUT 触发后追查出来的缺陷）
//
// 机制假设（待本脚本证实）：
//   ①「工艺项」价目表的读面/取价走 `collapseToLogical`（**布帘列优先**）；
//   ② seed 期的价目行经 V104 塌缩后 position='通用'；
//   ③ `PUT /operations/{id}` 省略 `positions` 时，`attachPositions` 会**兜底新建** position='布帘'
//      的行，价 = **工序库价**；
//   ④ 该新行按「布帘列优先」盖住原「通用」行 ⇒ 原「未定价 / 商家改过的格价」被静默改成工序库价。
//
// 判据：一次**与价格无关**的保存（改作用域）之后，计件单价口径必须不变。
import { api, loginApi, psql, psqlWrite, one, log, waitService, Recorder } from './lib.mjs'

const T = Number(process.env.TENANT_ID || 20)
const PHONE = process.env.ADMIN_PHONE || '13870217889'
const RUN = String(Date.now()).slice(-6)
const OP = '打包'
const BASE_PI = {
  colorName: '本白', unit: '米', sellingMethod: 'bulk_cut', fabric_meters: 12.3, pleat_count: 40, panels: 2, holes: 24,
  processingItems: [{ id: 'pi_base', name: '锁边', quantity: 1, unit: '米' }],
}
let token, ctx

async function dispatch(tag) {
  const order = await api('POST', '/api/admin/orders', {
    token, body: {
      customerName: `改价漂移客户${RUN}`, customerPhone: '13300000009', customerAddress: '杭州市余杭区漂移路 1 号',
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
  const row = po ? one(`select unit_price::text as p from processing_position_operations
      where processing_order_id='${po.id}' and operation_name='${OP}'`) : null
  // 注意：`row.p` 为 null（未定价）与「行缺失」是两件事，**不得**用 `?? ` 混同
  const price = !po ? '无加工单' : !row ? '无该工序行' : (row.p === null ? 'NULL(未定价)' : row.p)
  return { ok: gen.json?.data?.[0]?.success === true, po, price }
}
/** 读面「工艺项」表里该逻辑工序的**有效价**（键缺失 = 未定价）。 */
async function facePrice() {
  const rows = (await api('GET', '/api/admin/production/operation-positions', { token })).json?.data || []
  const r = rows.find((x) => x.operation === OP)
  if (!r) return '无价目行'
  return r.unit_price == null ? 'NULL(未定价)' : String(r.unit_price)
}
const rowsOf = (alive = true) => psql(`select id, position, unit_price::text as p, coalesce(deleted,0) as del
    from production_operation_positions where tenant_id=${T} and logical_name='${OP}'${alive ? ' and coalesce(deleted,0)=0' : ''} order by position`)
const genericRow = () => one(`select id, unit_price::text as p from production_operation_positions
    where tenant_id=${T} and logical_name='${OP}' and position='通用' and coalesce(deleted,0)=0`)
const clothRow = () => one(`select id, unit_price::text as p from production_operation_positions
    where tenant_id=${T} and logical_name='${OP}' and position='布帘' and coalesce(deleted,0)=0`)

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  const R = new Recorder('p9-price-drift.json')
  token = (await loginApi(PHONE)).token
  const cat = await api('POST', '/api/admin/categories', { token, body: { name: `漂移验收分类${RUN}`, sortOrder: 1 } })
  const prod = await api('POST', '/api/admin/products', {
    token, body: {
      name: `漂移验收商品${RUN}`, unit: '米', pricingType: 'fixed', basePrice: 68,
      status: cat.json?.data?.id ? 'on_sale' : 'draft', categoryId: cat.json?.data?.id,
      colors: [{ colorName: '本白', mainColorHex: '#FAFAFA', sortOrder: 1 }],
      skus: [{ colorName: '本白', doorWidth: '2.8m', price: 68, stock: 100000, skuCode: `DRF-${RUN}` }],
    },
  })
  ctx = { productId: prod.json?.data?.id, skuId: one(`select id::text as id from product_skus where product_id='${prod.json?.data?.id}'`)?.id }
  const opRow = one(`select id, unit_price::text as p, scope from production_operations where tenant_id=${T} and name='${OP}' and coalesce(deleted,0)=0`)
  const generic0 = genericRow()
  log(`工序「${OP}」库价=${opRow.p} scope=${opRow.scope}；通用行=${JSON.stringify(generic0)}；起始存活行=${JSON.stringify(rowsOf())}`)

  const created = []
  try {
    // ① 清场：把我此前探针新建的「布帘」行软删 ⇒ 回到「通用行单行」的基线态（读回自证）
    for (const r of rowsOf()) {
      if (r.position === '布帘') { psqlWrite(`update production_operation_positions set deleted=1 where id='${r.id}'`); created.push(r.id) }
    }
    const face0 = await facePrice()
    const d0 = await dispatch('P9a')
    log(`清场后：读面=${face0}；派工实例价=${d0.price}`)

    // ② 复现形态 A：未定价 ⇒ 一次**与价格无关**的保存
    const put = await api('PUT', `/api/admin/production/operations/${opRow.id}`, { token, body: { scope: opRow.scope } })
    const faceA = await facePrice()
    const dA = await dispatch('P9b')
    const rowCreated = clothRow()
    const driftA = face0.startsWith('NULL') && !faceA.startsWith('NULL')
    driftA
      ? R.fail('P9-01', '「未定价」不得被一次与价格无关的保存静默改成价位',
          `保存前：读面=${face0}、派工实例价=${d0.price} ⇒ 保存（PUT /operations {scope}，HTTP ${put.status}）后：读面=${faceA}、派工实例价=${dA.price}` +
          `；新建价目行=${JSON.stringify(rowCreated)}（position=布帘，价=工序库价 ${opRow.p}）⇒ **未定价被静默顶成 ${faceA}**`,
          [`PUT /api/admin/production/operations/${opRow.id} {scope:'${opRow.scope}'}`,
           `SQL: select id,position,unit_price from production_operation_positions where logical_name='${OP}' and coalesce(deleted,0)=0`,
           `SQL: select unit_price from processing_position_operations where processing_order_id='${dA.po?.id}' and operation_name='${OP}'`])
      : R.pass('P9-01', '未定价未被与价格无关的保存改写', `读面 ${face0}→${faceA}；实例价 ${d0.price}→${dA.price}`)

    // ③ 复现形态 B（涉钱更直观）：商家在「工艺项」表把该工序改成 0.77 ⇒ 再保存一次设置 ⇒ 价是否被回退
    const g = genericRow()
    const setCell = await api('PUT', `/api/admin/production/operation-positions/${g.id}`, { token, body: { unit_price: 0.77 } })
    const faceB1 = await facePrice()
    const dB1 = await dispatch('P9c')
    // 把新冒出来的「布帘」行再清掉，让 0.77 的「通用」行成为有效行（模拟商家改价后的稳态）
    const stray = clothRow()
    if (stray) { psqlWrite(`update production_operation_positions set deleted=1 where id='${stray.id}'`); created.push(stray.id) }
    const faceB2 = await facePrice()
    const dB2 = await dispatch('P9d')
    // 触发：再来一次与价格无关的保存
    const put2 = await api('PUT', `/api/admin/production/operations/${opRow.id}`, { token, body: { scope: opRow.scope === 'set' ? 'position' : 'set' } })
    const faceB3 = await facePrice()
    const dB3 = await dispatch('P9e')
    await api('PUT', `/api/admin/production/operations/${opRow.id}`, { token, body: { scope: opRow.scope } })   // 还原作用域
    const driftB = faceB2 === '0.77' && faceB3 !== '0.77'
    driftB
      ? R.fail('P9-03', '商家在「工艺项」里改过的价不得被一次与价格无关的保存**回退**',
          `改价 0.77（HTTP ${setCell.status}）⇒ 读面=${faceB2}、实例价=${dB2.price}；` +
          `再保存一次设置（改作用域，HTTP ${put2.status}）⇒ 读面=${faceB3}、实例价=${dB3.price} —— **商家改过的价被静默回退成工序库价 ${opRow.p}**`,
          [`PUT /api/admin/production/operation-positions/${g.id} {unit_price:0.77}`,
           `PUT /api/admin/production/operations/${opRow.id} {scope}`,
           `SQL: select unit_price from processing_position_operations where processing_order_id='${dB3.po?.id}' and operation_name='${OP}'`])
      : R.pass('P9-03', '商家改过的价未被保存动作回退', `读面 ${faceB2}→${faceB3}；实例价 ${dB2.price}→${dB3.price}`)
  } catch (e) {
    R.fail('P9-01', '改价漂移探针', String(e).slice(0, 400))
  } finally {
    // ④ 还原：删掉所有「布帘」行 + 通用行价格回 NULL（回到最初基线），并派工复证
    try {
      for (const r of rowsOf()) if (r.position === '布帘') psqlWrite(`update production_operation_positions set deleted=1 where id='${r.id}'`)
      const g = genericRow()
      if (g && g.p !== null) psqlWrite(`update production_operation_positions set unit_price=null where id='${g.id}'`)
      await api('PUT', `/api/admin/production/operations/${opRow.id}`, { token, body: { scope: opRow.scope } })
      const rowsNow = rowsOf()
      for (const r of rowsNow) if (r.position === '布帘') psqlWrite(`update production_operation_positions set deleted=1 where id='${r.id}'`)
      const faceFinal = await facePrice()
      const dF = await dispatch('P9f')
      const ok = faceFinal.startsWith('NULL') && dF.price.startsWith('NULL')
      ok
        ? R.pass('P9-02', '还原：读面与派工都回到「未定价」，存活价目行只剩「通用」一行',
            `读面=${faceFinal}；加工单 ${dF.po?.processing_order_no} 实例价=${dF.price}；存活行=${JSON.stringify(rowsOf())}`)
        : R.fail('P9-02', '还原', `读面=${faceFinal}；实例价=${dF.price}；存活行=${JSON.stringify(rowsOf())}`)
    } catch (e) { R.fail('P9-02', '还原', String(e).slice(0, 300)) }
  }
  log(`summary=${JSON.stringify(R.summary())}`)
}

main().catch((e) => { console.error(e); process.exit(1) })
