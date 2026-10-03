// P8：**F8 → 工资** 的受控端到端实验（本包最硬的一条证据）
//
// 为什么必须做这个（归因纪律 v1.10「机制级」需可复现因果链）：前几轮观测到的
// 「新单实例价 = 0.40/0.00」都可能是**并行包在飞配置**造成的（它改完即还原）⇒ 无法归因。
// 本实验把因果链钉死在**我自己的一次保存**上，且只碰自建对象：
//
//   ① 自建订单（不派工，避免共享路线/配置干扰）
//   ② `POST /orders/{id}/instantiate` **显式带 positions**（body 里的 unit_price=null
//      = 未定价）⇒ 建出一道「未定价」工序实例 —— 这是**契约支持**的形态（非注入式写库）
//   ③ 读数 X = 该实例单价（应 = NULL）
//   ④ **只做一次** `PUT /api/admin/production/operations/{id} {scope}`（与价格无关的普通保存）
//   ⑤ 再 instantiate 一次（同一显式 positions）⇒ 读数 Y = 新实例单价
//   ⑥ 该工序报工 + 计件读面 ⇒ 工资影响面
//
// 判据（全会红）：
//   F8X-01 X 必须 = NULL（前置成立）
//   F8X-02 一次普通保存**不得**新建任何价目行
//   F8X-03 Y 必须 = NULL（不得变成工序库价）
//   F8X-04 未定价工序的报工不得进入 per_operation 金额
import { writeFileSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { api, loginApi, psql, one, log, OUT, waitService, Recorder, guardedWrite, PROBE_PREFIX } from './lib.mjs'

const T = Number(process.env.TENANT_ID || 20)
const PHONE = process.env.ADMIN_PHONE || '13870217889'
const RUN = String(Date.now()).slice(-6)
const LOGICAL = process.env.F8X_LOGICAL || '定型'
const WORKER = `${PROBE_PREFIX}工人丁${RUN}`

const instOf = (orderId) => psql(`
  select o.id, o.operation_name, o.unit_price::text as unit_price, o.qty::text as qty, o.seq,
         o.processing_order_id, p.processing_order_no
  from processing_position_operations o join processing_orders p on p.id = o.processing_order_id
  where p.order_id='${orderId}' and coalesce(o.deleted,0)=0 order by o.seq`)
const activeRows = () => psql(`select id, position, unit_price::text as unit_price, applicable, coalesce(deleted,0) as deleted
  from production_operation_positions where tenant_id=${T} and logical_name='${LOGICAL}' and coalesce(deleted,0)=0 order by position`)

async function buildOrder(token, tag) {
  const cat = await api('POST', '/api/admin/categories', { token, body: { name: `${PROBE_PREFIX}分类${RUN}-${tag}`, sortOrder: 1 } })
  const prod = await api('POST', '/api/admin/products', {
    token, body: {
      name: `${PROBE_PREFIX}商品${RUN}-${tag}`, unit: '米', pricingType: 'fixed', basePrice: 68,
      status: cat.json?.data?.id ? 'on_shelf' : 'draft', categoryId: cat.json?.data?.id,
      colors: [{ colorName: '本白', mainColorHex: '#FAFAFA', sortOrder: 1 }],
      skus: [{ colorName: '本白', doorWidth: '2.8m', price: 68, stock: 100000, skuCode: `WAGE8-${RUN}-${tag}` }],
    },
  })
  const productId = prod.json?.data?.id
  const skuId = one(`select id::text as id from product_skus where product_id='${productId}'`)?.id
  const order = await api('POST', '/api/admin/orders', {
    token, body: {
      customerName: `${PROBE_PREFIX}客户${RUN}`, customerPhone: '13300000003', customerAddress: '杭州市余杭区工资路 5 号',
      logisticsType: 'express', logisticsCompany: '顺丰速运',
      items: [{
        productId, skuId, productName: `${PROBE_PREFIX}行${tag}`, quantity: 1, unitPrice: 68, subtotal: 68, width: 2.8, height: 2.6,
        processingInfo: {
          sku: null, colorName: '本白', unit: '米', sellingMethod: 'bulk_cut',
          fabric_meters: 12.3, pleat_count: 40, panels: 2, holes: 24, fullness: 2, fullness_actual: 2,
          curtainType: '布帘', craft: '罗马帘', processingItems: [{ id: `pi${tag}`, name: '锁边', quantity: 1, unit: '米' }],
        },
      }],
    },
  })
  const orderId = order.json?.data?.id
  if (!orderId) throw new Error(`建单失败: ${order.text.slice(0, 200)}`)
  await api('PUT', `/api/admin/orders/${orderId}/payment`, { token })
  return { tag, orderId, catId: cat.json?.data?.id, productId }
}

/** 显式 positions 实例化（**未定价**形态：unit_price:null）—— 契约支持，非注入写库。 */
const INSTANCE_PAYLOAD = {
  positions: [{
    position_name: '布帘',
    operations: [{
      seq: 1, operation: `${LOGICAL}-布`, group: '后道', unit: '米', qty: 10,
      unit_price: null, factor: 1, is_start_marker: false,
    }],
  }],
}

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  const R = new Recorder('p8-f8-controlled.json')
  const { token } = await loginApi(PHONE)
  const out = { at: new Date().toISOString(), run: RUN, logical: LOGICAL, worker: WORKER, payload: INSTANCE_PAYLOAD }

  const libRow = psql(`select id, name, unit_price::text as unit_price, scope, position, status
    from production_operations where tenant_id=${T} and name='${LOGICAL}-布'`)[0]
  out.libraryRow = libRow
  out.activeRowsBefore = activeRows()
  R[!!libRow ? 'pass' : 'fail']('F8X-00', `前置：工序库存在逻辑工序「${LOGICAL}-布」`,
    libRow ? `id=${libRow.id} 库价=${libRow.unit_price} scope=${libRow.scope}` : '不存在',
    [`SQL: production_operations where name='${LOGICAL}-布'`])
  if (!libRow) { writeFileSync(join(OUT, 'p8-f8-controlled.json'), JSON.stringify(out, null, 2)); return }

  const gen = (o) => api('POST', '/api/admin/processing-orders/generate', { token, body: { orderIds: [o.orderId] } })

  const A = await buildOrder(token, 'X')
  out.orderA = A
  out.genA = (await gen(A)).status
  const ins1 = await api('POST', `/api/admin/production/orders/${A.orderId}/instantiate`, { token, body: INSTANCE_PAYLOAD })
  out.instantiate1 = { http: ins1.status, body: ins1.text.slice(0, 400) }
  out.instA = instOf(A.orderId)
  const X = out.instA[0]?.unit_price ?? null
  out.X = X
  R[X === null && ins1.status === 200 && out.instA.length > 0 ? 'pass' : 'fail']('F8X-01',
    '前置②：显式 positions(unit_price=null) 实例化 ⇒ 实例价 = NULL（未定价）',
    `实例 ${out.instA[0]?.operation_name ?? '-'} unit_price=${X ?? 'NULL'}；instantiate HTTP ${ins1.status}；${ins1.status !== 200 ? ins1.text.slice(0, 160) : '实例行数 ' + out.instA.length}`,
    [`POST /orders/${A.orderId}/instantiate（body.positions[].operations[].unit_price=null）`,
     `SQL: processing_position_operations where processing_order_id='${out.instA[0]?.processing_order_id}'`])

  // ④ 一次普通保存（与价格无关）
  const put = await api('PUT', `/api/admin/production/operations/${libRow.id}`, { token, body: { scope: libRow.scope ?? 'position' } })
  out.put = { http: put.status, sentScope: libRow.scope ?? 'position', body: put.text.slice(0, 500) }
  out.activeRowsAfter = activeRows()
  const newRows = out.activeRowsAfter.filter((r) => !out.activeRowsBefore.some((p) => p.id === r.id))
  out.newPositionRows = newRows
  R[newRows.length === 0 ? 'pass' : 'fail']('F8X-02', '【F8 受控】一次普通保存不得新建任何价目行',
    `新行=${JSON.stringify(newRows.map((r) => [r.position, r.unit_price]))}；保存后活跃行=${JSON.stringify(out.activeRowsAfter.map((r) => [r.position, r.unit_price]))}`,
    [`PUT /operations/${libRow.id} {scope:'${libRow.scope ?? 'position'}'}`,
     `SQL: production_operation_positions where logical_name='${LOGICAL}'`])

  // ⑤ 再实例化 ⇒ Y
  const B = await buildOrder(token, 'Y')
  out.orderB = B
  out.genB = (await gen(B)).status
  const ins2 = await api('POST', `/api/admin/production/orders/${B.orderId}/instantiate`, { token, body: INSTANCE_PAYLOAD })
  out.instantiate2 = { http: ins2.status, body: ins2.text.slice(0, 400) }
  out.instB = instOf(B.orderId)
  const Y = out.instB[0]?.unit_price ?? null
  out.Y = Y
  R[Y === null && ins2.status === 200 && out.instB.length > 0 ? 'pass' : 'fail']('F8X-03',
    '【F8 受控·钱链】一次普通保存之后新建的实例单价**必须仍为未定价**（不得变成工序库价）',
    `保存前 X=${X ?? 'NULL'} → 保存后 Y=${Y ?? 'NULL'}；instantiate HTTP ${ins2.status}；工序库价=${libRow.unit_price}；保存后活跃行=${JSON.stringify(out.activeRowsAfter.map((r) => [r.position, r.unit_price]))}`,
    [`PUT /operations/${libRow.id}`, `POST /orders/${B.orderId}/instantiate`, 'SQL: 实例单价前后读数'])

  // ⑥ 工资面：未定价那一单报工后的读面
  const instA = out.instA[0]
  if (instA) {
    const rep = await api('POST', `/api/admin/production/orders/${A.orderId}/operations/${instA.id}/report`,
      { token, body: { worker_name: WORKER, qty: 3, qualified_qty: 3, work_type: 'normal' }, headers: { 'X-Client-Request-Id': `${RUN}-F8X` } })
    out.reportA = { http: rep.status, data: rep.json?.data ?? null }
    out.logA = one(`select operation_name, unit_price::text as unit_price, price_state, qualified_qty::text as qualified_qty
      from production_work_logs where processing_order_id='${instA.processing_order_id}' order by created_at desc limit 1`)
    out.pieceworkA = (await api('GET', `/api/admin/production/orders/${A.orderId}/piecework`, { token })).json?.data ?? null
    const lines = (out.pieceworkA?.per_operation ?? []).filter((r) => r.operation === instA.operation_name)
    R[lines.length === 0 ? 'pass' : 'fail']('F8X-04',
      '【F8 受控·钱链】未定价工序的报工不得进入 per_operation 金额（必须只在 unpriced 块）',
      `per_operation 命中=${JSON.stringify(lines)}；unpriced=${JSON.stringify(out.pieceworkA?.unpriced)}；合计=${out.pieceworkA?.total}`,
      [`GET /orders/${A.orderId}/piecework`])
  }
  // 保存后那一单：报工 ⇒ 快照价（影响面）
  const instB = out.instB[0]
  if (instB) {
    const repB = await api('POST', `/api/admin/production/orders/${B.orderId}/operations/${instB.id}/report`,
      { token, body: { worker_name: WORKER, qty: 2, qualified_qty: 2, work_type: 'normal' }, headers: { 'X-Client-Request-Id': `${RUN}-F8Y` } })
    out.reportB = { http: repB.status, data: repB.json?.data ?? null }
    out.logB = one(`select operation_name, unit_price::text as unit_price, price_state, qualified_qty::text as qualified_qty
      from production_work_logs where processing_order_id='${instB.processing_order_id}' order by created_at desc limit 1`)
    out.pieceworkB = (await api('GET', `/api/admin/production/orders/${B.orderId}/piecework`, { token })).json?.data ?? null
    out.wageImpact = {
      保存后实例单价: Y,
      保存后报工快照价: out.logB?.unit_price ?? null,
      保存后价态: out.logB?.price_state ?? null,
      保存后该工序计件金额: (out.pieceworkB?.per_operation ?? []).find((r) => r.operation === out.logB?.operation_name)?.amount ?? null,
      保存后未定价数量: out.pieceworkB?.unpriced?.qty ?? null,
    }
  }
  out.verdict = (X === null && Y === null && ins1.status === 200 && ins2.status === 200)
    ? '未复现：一次普通保存未改写取价来源（实例仍为未定价）'
    : `**已复现**：X=${X ?? 'NULL'} → Y=${Y ?? 'NULL'}（一次普通保存把「未定价」变成有价 ⇒ 工资口径被静默改写）`

  writeFileSync(join(OUT, 'p8-f8-controlled.json'), JSON.stringify(out, null, 2))
  const ctx = JSON.parse(readFileSync(join(OUT, 'probe-ctx.json'), 'utf8'))
  ctx.probes.push({ tag: 'X2', ...A }, { tag: 'Y2', ...B })
  writeFileSync(join(OUT, 'probe-ctx.json'), JSON.stringify(ctx, null, 2))
  log(`受控实验(${LOGICAL})：库价=${libRow.unit_price} X=${X ?? 'NULL'} Y=${Y ?? 'NULL'} 新建价目行=${JSON.stringify(newRows.map((r) => [r.position, r.unit_price]))}`)
  log(`工资影响=${JSON.stringify(out.wageImpact ?? null)}`)
  log(`verdict=${out.verdict}`)
  log(`summary=${JSON.stringify(R.summary())}`)
}
main().catch((e) => { console.error(e); process.exit(1) })
