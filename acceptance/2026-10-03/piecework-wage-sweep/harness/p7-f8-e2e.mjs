// P7：**F8 对工资的端到端判别**（本包里最硬的一条）
//
// 前置条件必须**当场验证**（migao-acceptance：假绿形态「重放未复现缺陷的前置条件」）：
//   ① 目标逻辑工序此刻**没有活跃的 `布帘` 价目行**（= 有效价未被布帘列覆盖）
//      —— 若已有（并行包的在飞注入）⇒ 记为「疑似并发干扰」，本判据本轮**不作数**
//   ② 探针单该工序实例价为 NULL（未定价）
// 动作：一次**与价格无关的普通保存** `PUT /api/admin/production/operations/{id} {scope}`
// 读数：保存后 ①活跃价目行 ②探针实例价 ③**该工序下一笔报工的单价快照** ④工资读面
//
// 判据（都带红证性质：跑的是真断言）：
//   F8E-01 保存后实例价必须仍为 NULL（未定价不得被静默定价）
//   F8E-02 保存后**新报工**的单价快照必须仍为 NULL 且 price_state='unpriced'
//   F8E-03 该工序的报工**不得**以 0 元/库价进入计件金额（钱链红线）
import { writeFileSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { api, loginApi, psql, one, log, OUT, waitService, Recorder, guardedWrite, PROBE_PREFIX, moneyEq, cents, fmt } from './lib.mjs'

const T = Number(process.env.TENANT_ID || 20)
const PHONE = process.env.ADMIN_PHONE || '13870217889'
const RUN = String(Date.now()).slice(-6)

function decMul(a, b) {
  const [ai, af = ''] = String(a).split('.'); const [bi, bf = ''] = String(b).split('.')
  const av = BigInt(ai + af), bv = BigInt(bi + bf); const scale = af.length + bf.length
  const prod = (av * bv).toString().padStart(scale + 1, '0')
  const int = prod.slice(0, prod.length - scale) || '0'
  const frac = scale ? prod.slice(prod.length - scale) : ''
  return frac ? `${int}.${frac}` : int
}
function toCentsHalfUp(s0) {
  const neg = String(s0).startsWith('-'); const s = neg ? String(s0).slice(1) : String(s0)
  const [i, f = ''] = s.split('.'); const t = (f + '000').slice(0, 3)
  let c = BigInt(i) * 100n + BigInt(t.slice(0, 2)); if (Number(t[2]) >= 5) c += 1n
  return neg ? -c : c
}

async function buildOrder(token, tag) {
  const cat = await api('POST', '/api/admin/categories', { token, body: { name: `${PROBE_PREFIX}分类${RUN}-${tag}`, sortOrder: 1 } })
  const prod = await api('POST', '/api/admin/products', {
    token, body: {
      name: `${PROBE_PREFIX}商品${RUN}-${tag}`, unit: '米', pricingType: 'fixed', basePrice: 68,
      status: cat.json?.data?.id ? 'on_sale' : 'draft', categoryId: cat.json?.data?.id,
      colors: [{ colorName: '本白', mainColorHex: '#FAFAFA', sortOrder: 1 }],
      skus: [{ colorName: '本白', doorWidth: '2.8m', price: 68, stock: 100000, skuCode: `WAGE7-${RUN}-${tag}` }],
    },
  })
  const productId = prod.json?.data?.id
  const skuId = one(`select id::text as id from product_skus where product_id='${productId}'`)?.id
  const order = await api('POST', '/api/admin/orders', {
    token, body: {
      customerName: `${PROBE_PREFIX}客户${RUN}`, customerPhone: '13300000003', customerAddress: '杭州市余杭区工资路 3 号',
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
  await api('POST', '/api/admin/processing-orders/generate', { token, body: { orderIds: [orderId] } })
  const po = one(`select id, processing_order_no from processing_orders where order_id='${orderId}' and tenant_id=${T} order by created_at desc limit 1`)
  return { tag, orderId, poId: po.id, poNo: po.processing_order_no }
}

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  const R = new Recorder('p7-f8-e2e.json')
  const { token } = await loginApi(PHONE)
  const out = { at: new Date().toISOString(), run: RUN }

  // ── 选目标：一个有活跃 `通用` 行、且当前**没有活跃 `布帘` 行**的逻辑工序 ──
  const candidates = psql(`
    select logical_name,
      count(*) filter (where position='布帘')::int as br,
      count(*) filter (where position='通用')::int as gen,
      coalesce(max(unit_price) filter (where position='通用'), null)::text as gen_price
    from production_operation_positions
    where tenant_id=${T} and coalesce(deleted,0)=0 and status='active' and applicable
    group by logical_name
    having count(*) filter (where position='布帘') = 0 and count(*) filter (where position='通用') > 0
    order by logical_name`)
  out.candidates = candidates
  R[candidates.length > 0 ? 'pass' : 'fail']('F8E-00', '前置：存在「有 通用 行、无活跃 布帘 行」的逻辑工序（F8 可复现的前提）',
    `${candidates.length} 道：${candidates.map((c) => c.logical_name).join(',')}`,
    [`SQL: production_operation_positions group by logical_name having 布帘=0 and 通用>0`])
  if (!candidates.length) { writeFileSync(join(OUT, 'p7-f8-e2e.json'), JSON.stringify(out, null, 2)); return }
  // ── 探针单：在该逻辑工序的**未定价**实例上做（实例名可能是部位变体名）──
  const P = await buildOrder(token, 'F')
  out.probeOrder = P
  const insts = psql(`select id, operation_name, unit_price::text as unit_price, qty::text as qty
    from processing_position_operations
    where processing_order_id='${P.poId}' and coalesce(deleted,0)=0 order by seq`)
  out.instances = insts
  // 目标 = 候选集合 ∩ 探针单实例（按逻辑名归一：去掉 -布/-纱/部位后缀），且实例**未定价**
  const cand = new Set(candidates.map((c) => c.logical_name))
  const norm = (n) => String(n).replace(/-(布|纱|帘头|布料)$/, '')
  // 🔴 必须挑**未定价**的实例（前置②的可满足性由报文自身决定，不能靠"以为"）
  const pickable = insts.filter((i) => cand.has(norm(i.operation_name)) && i.unit_price === null)
  const target = candidates.find((c) => pickable.some((i) => norm(i.operation_name) === c.logical_name))
    ?? candidates[0]
  out.target = target
  const inst = pickable.find((i) => norm(i.operation_name) === target.logical_name) ?? null
  out.instance = inst
  if (!inst) {
    R.skip('F8E-01', '前置②：探针单该工序实例为**未定价**（NULL）',
      `探针单没有「${target.logical_name}」的实例；实例=${insts.map((i) => i.operation_name).join(',')}（登记为未覆盖）`)
    writeFileSync(join(OUT, 'p7-f8-e2e.json'), JSON.stringify(out, null, 2))
    log('未找到可注入实例 ⇒ 跳过 F8 端到端判据')
    return
  }
  const preOk = inst.unit_price === null
  R[preOk ? 'pass' : 'fail']('F8E-01', '前置②：探针单该工序实例为**未定价**（NULL）',
    `实例 ${inst.operation_name} unit_price=${inst.unit_price ?? 'NULL'}`,
    [`SQL: processing_position_operations where processing_order_id='${P.poId}'`])

  const libPrice = one(`select min(unit_price)::text as p from production_operations
    where tenant_id=${T} and name like '${target.logical_name}%'`)?.p
  out.libraryPrice = libPrice
  const posRows = () => psql(`select id, position, unit_price::text as unit_price, coalesce(deleted,0) as deleted
    from production_operation_positions where tenant_id=${T} and logical_name='${target.logical_name}' order by deleted, position, id`)
  out.before = { positionRows: posRows(), instance: inst }

  // ── 动作：与价格无关的普通保存 ──
  const opRow = one(`select id, name, scope from production_operations where tenant_id=${T} and name='${inst.operation_name}'`)
  out.action = { opId: opRow?.id, name: opRow?.name, body: { scope: opRow?.scope ?? 'position' } }
  const put = await api('PUT', `/api/admin/production/operations/${opRow.id}`, { token, body: out.action.body })
  out.action.http = put.status
  out.action.body_text = put.text.slice(0, 400)

  out.after = { positionRows: posRows(), instance: one(`select id, operation_name, unit_price::text as unit_price from processing_position_operations where id='${inst.id}'`) }
  const newBr = out.after.positionRows.filter((r) => r.position === '布帘' && r.deleted === 0)
  out.newBulianRow = newBr

  // ① 实例价
  const instAfter = out.after.instance?.unit_price ?? null
  R[instAfter === null ? 'pass' : 'fail']('F8E-02',
    '【F8·钱链】一次与价格无关的保存后，原「未定价」实例价必须仍为 NULL',
    `保存前 ${inst.unit_price ?? 'NULL'} → 保存后 ${instAfter ?? 'NULL'}；新出现活跃 布帘 行=${JSON.stringify(newBr.map((r) => r.unit_price))}；工序库价=${libPrice}`,
    [`PUT /api/admin/production/operations/${opRow.id} {scope:'${out.action.body.scope}'}`,
     `SQL: processing_position_operations.id='${inst.id}'`])

  // ② 新报工的单价快照 + price_state
  const rep = await api('POST', `/api/admin/production/orders/${P.orderId}/operations/${inst.id}/report`,
    { token, body: { worker_name: `${PROBE_PREFIX}工人丙${RUN}`, qty: 3, qualified_qty: 3, work_type: 'normal' }, headers: { 'X-Client-Request-Id': `${RUN}-F8E` } })
  out.report = { http: rep.status, data: rep.json?.data ?? null }
  const newLog = one(`select id, operation_name, unit_price::text as unit_price, price_state, qualified_qty::text as qualified_qty
    from production_work_logs where processing_order_id='${P.poId}' and operation_id='${inst.id}' order by created_at desc limit 1`)
  out.newWorkLog = newLog
  const snapOk = newLog && newLog.unit_price === null && newLog.price_state === 'unpriced'
  R[snapOk ? 'pass' : 'fail']('F8E-03',
    '【F8·钱链】保存后**新报工**的单价快照必须仍为 NULL 且 price_state=unpriced（未定价不得被静默定价）',
    `快照 unit_price=${newLog?.unit_price ?? '-'} price_state=${newLog?.price_state ?? '-'}；读数=${JSON.stringify(newLog)}`,
    [`POST …/operations/${inst.id}/report`, `SQL: production_work_logs 最新一行`])

  // ③ 工资读面：该工序不得以 0 元/库价计件
  const pw = await api('GET', `/api/admin/production/orders/${P.orderId}/piecework`, { token })
  const pwData = pw.json?.data ?? null
  out.piecework = pwData
  const zeroLine = (pwData?.per_operation ?? []).filter((r) => r.operation === inst.operation_name)
  const unpricedHas = (pwData?.unpriced?.operations ?? []).some((o) => o.operation === inst.operation_name)
  out.wageVerdict = { zeroLine, unpricedHas, total: pwData?.total, unpricedQty: pwData?.unpriced?.qty }
  const wageOk = zeroLine.length === 0
  R[wageOk ? 'pass' : 'fail']('F8E-04',
    '【F8·钱链红线】该工序的报工不得以「0 元/库价」进入计件金额（必须走 unpriced 维度）',
    `per_operation 中 ${inst.operation_name} 的行=${JSON.stringify(zeroLine)}；在 unpriced 清单=${unpricedHas}；工资合计=${pwData?.total}`,
    [`GET /api/admin/production/orders/${P.orderId}/piecework`])

  // ④ 未定价可见性（缺失≠0 的 UI 承接面）
  R[unpricedHas ? 'pass' : 'fail']('F8E-05',
    '【缺失≠0】该未定价工序必须在 unpriced 块列出（商家可据此定价，而不是看到 0 元）',
    `unpriced.operations=${JSON.stringify(pwData?.unpriced?.operations ?? [])}`,
    [`GET /orders/{id}/piecework → .unpriced`])

  writeFileSync(join(OUT, 'p7-f8-e2e.json'), JSON.stringify(out, null, 2))
  const ctx = JSON.parse(readFileSync(join(OUT, 'probe-ctx.json'), 'utf8'))
  ctx.probes.push(P); writeFileSync(join(OUT, 'probe-ctx.json'), JSON.stringify(ctx, null, 2))
  log(`目标=${target.logical_name} 库价=${libPrice} 保存后实例价=${instAfter ?? 'NULL'} 新报工快照=${newLog?.unit_price ?? 'NULL'}/${newLog?.price_state} 新增布帘行=${JSON.stringify(newBr.map((r) => r.unit_price))}`)
  log(`summary=${JSON.stringify(R.summary())}`)
}
main().catch((e) => { console.error(e); process.exit(1) })
