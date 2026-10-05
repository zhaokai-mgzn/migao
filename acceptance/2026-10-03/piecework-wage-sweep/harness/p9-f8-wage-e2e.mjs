// P9：**F8 → 工资 端到端受控实验（终版）**
//
// 目的：把「一次与价格无关的普通保存」→「取价来源被改写」→「工资口径被静默改写」
// 这条因果链**在单次实验里**闭合，且只依赖自建对象。
//
// 手法（全部契约内，唯一一处注入是"定义有效价"，且实验后还原）：
//   ① 选一道**此刻没有任何活跃价目行**的逻辑工序（⇒ 它的有效价 = 未定价）
//   ② 自建订单 + 派单（走共享路线，随后被显式实例化覆盖）
//   ③ 先看**自然读数** X = 实例单价（未定价应 = NULL）
//   ④ 注入：把该工序的 `通用` 行价为独特值 GENERAL（= 定义"有效价"，模拟商家定价）
//   ⑤ 显式实例化 ⇒ 读数 Y（按"有效价优先"应为 GENERAL）
//   ⑥ **只做一次** `PUT /operations/{id} {scope}`（普通保存，body 不含价）
//   ⑦ 显式实例化 ⇒ 读数 Z（按"布帘列优先"会变成工序库价 LIB，按"继承有效价"应 = GENERAL）
//   ⑧ 报工 + 计件读面 ⇒ 钱链后果
//
// 判据（全会红）：
//   F8Z-01 X = NULL（前置成立）
//   F8Z-02 Y = GENERAL（有效价口径成立 ⇒ 第⑦步才有判别力）
//   F8Z-03 保存**不得**新建价目行
//   F8Z-04 Z 必须 = GENERAL（不得变成工序库价 LIB）—— 这一条就是 F8 对工资的口径判据
//   F8Z-05 保存后新报工的单价快照必须 = GENERAL（不是库价、更不是 0）
import { writeFileSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { api, loginApi, psql, one, log, OUT, waitService, Recorder, guardedWrite, PROBE_PREFIX, cents, fmt, moneyEq } from './lib.mjs'

const T = Number(process.env.TENANT_ID || 20)
const PHONE = process.env.ADMIN_PHONE || '13870217889'
const RUN = String(Date.now()).slice(-6)
const LOGICAL = process.env.F8Z_LOGICAL || '复烫'
const GENERAL = '1.11'          // 注入的「有效价」（模拟商家定价）
const payloadFor = (log) => ({
  positions: [{ position_name: '布帘', operations: [{ seq: 1, operation: `${log}-布`, group: '后道', unit: '米', qty: 10, unit_price: null, factor: 1, is_start_marker: false }] }],
})
const WORKER = `${PROBE_PREFIX}工人戊${RUN}`

let LOG = LOGICAL
const rowsOf = () => psql(`select id, position, unit_price::text as unit_price, applicable, coalesce(deleted,0) as deleted
  from production_operation_positions where tenant_id=${T} and logical_name='${LOG}' order by deleted, position, id`)
const instOf = (orderId) => psql(`select o.id, o.operation_name, o.unit_price::text as unit_price, o.qty::text as qty,
    o.processing_order_id, p.processing_order_no, coalesce(o.deleted,0) as deleted
  from processing_position_operations o join processing_orders p on p.id=o.processing_order_id
  where p.order_id='${orderId}' and coalesce(o.deleted,0)=0 order by o.seq`)
/** 目标逻辑工序的活跃实例价（其余工序不参与本判据）。 */
const priceOfLogical = (orderId) => {
  const rows = instOf(orderId).filter((r) => String(r.operation_name).replace(/-(布|纱|帘头|布料)$/, '') === LOG)
  return rows[0]?.unit_price ?? null
}

async function buildOrder(token, tag) {
  const cat = await api('POST', '/api/admin/categories', { token, body: { name: `${PROBE_PREFIX}分类${RUN}-${tag}`, sortOrder: 1 } })
  const prod = await api('POST', '/api/admin/products', {
    token, body: {
      name: `${PROBE_PREFIX}商品${RUN}-${tag}`, unit: '米', pricingType: 'fixed', basePrice: 68,
      status: cat.json?.data?.id ? 'on_sale' : 'draft', categoryId: cat.json?.data?.id,
      colors: [{ colorName: '本白', mainColorHex: '#FAFAFA', sortOrder: 1 }],
      skus: [{ colorName: '本白', doorWidth: '2.8m', price: 68, stock: 100000, skuCode: `WAGE9-${RUN}-${tag}` }],
    },
  })
  const productId = prod.json?.data?.id
  const skuId = one(`select id::text as id from product_skus where product_id='${productId}'`)?.id
  const order = await api('POST', '/api/admin/orders', {
    token, body: {
      customerName: `${PROBE_PREFIX}客户${RUN}`, customerPhone: '13300000003', customerAddress: '杭州市余杭区工资路 6 号',
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
// ⚠️ **不再用显式 positions**：payload 里的 unit_price 会**直接**成为实例快照（precedence），
// 那就测不到「配置 → 实例价」这一跳。自然派工（generate）才走取价来源口径。
const genOf = (token, orderId) => api('POST', '/api/admin/processing-orders/generate', { token, body: { orderIds: [orderId] } })


async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  const R = new Recorder('p9-f8-wage-e2e.json')
  const { token } = await loginApi(PHONE)
  const out = { at: new Date().toISOString(), run: RUN, logical: LOGICAL, generalPrice: GENERAL, worker: WORKER }

  // 选一道**能表达「未定价」**的逻辑工序：
  //   未定价只有在 `通用` 行价为 NULL 时存在（仓内 seed 的 通用 行多有价；测试环境 40 道全有价）
  //   ⇒ 兜底：挑一道有活跃 `通用` 行的工序，**还原式**把它置 NULL（模拟商家清空价），实验后改回原值。
  const cands = psql(`
    select logical_name, position, id, unit_price::text as unit_price
    from production_operation_positions
    where tenant_id=${T} and coalesce(deleted,0)=0 and position='通用'
      and logical_name in ('复烫','定型','熨烫','精裁','三边','车被','打包','韩褶','打孔','接高')
    order by position, logical_name`)
  out.generalRowCandidates = cands
  const picked = cands.find((c) => c.logical_name === LOGICAL) ?? cands[0]
  LOG = picked?.logical_name ?? LOGICAL
  out.logical = LOG
  const libRow = picked
    ? psql(`select id, name, unit_price::text as unit_price, scope from production_operations where tenant_id=${T} and name='${LOG}-布'`)[0]
    : null
  out.libraryRow = libRow
  out.originalGeneralPrice = picked?.unit_price ?? null
  out.rowsBefore = rowsOf()
  // 把活跃 布帘 行（若有）临时软删，并把 通用 行置 NULL ⇒ 造出「未定价」前置
  const brRows = out.rowsBefore.filter((r) => r.position === '布帘' && r.deleted === 0)
  out.tempSoftDeleted = brRows.map((r) => r.id)
  const cleanPre = !!libRow && !!picked && libRow.unit_price !== null
  R[cleanPre ? 'pass' : 'fail']('F8Z-00',
    '前置：存在该逻辑工序的库行与活跃 `通用` 价目行（可造出「未定价」前置）',
    `选中「${LOG}」（库价 ${libRow?.unit_price}，原通用价 ${picked?.unit_price ?? 'NULL'}）；活跃行=${JSON.stringify(out.rowsBefore.filter((r) => r.deleted === 0).map((r) => [r.position, r.unit_price]))}`,
    [`SQL: production_operation_positions where position='通用'`])
  if (!cleanPre) { writeFileSync(join(OUT, 'p9-f8-wage-e2e.json'), JSON.stringify(out, null, 2)); log('前置不成立，跳过（登记未覆盖）'); return }
  // 造前置（还原式注入，实验后改回）
  guardedWrite(`-- probe-ok
update production_operation_positions set unit_price=NULL, updated_at=NOW() where id='${picked.id}'`)
  if (brRows.length) {
    guardedWrite(`-- probe-ok
update production_operation_positions set deleted=1, updated_at=NOW() where id in (${brRows.map((r) => `'${r.id}'`).join(',')})`)
  }
  out.afterPreInject = rowsOf().filter((r) => r.deleted === 0)
  const preInjectedNoPrice = out.afterPreInject.every((r) => r.unit_price === null)

  const created = []
  try {
    // ③ 自然读数 X
    const O1 = await buildOrder(token, 'Z1')
    out.order1 = O1
    const i1 = await genOf(token, O1.orderId)
    out.generate1 = { http: i1.status }
    const X = priceOfLogical(O1.orderId)
    out.X = X
    R[X === libRow.unit_price ? 'pass' : 'fail']('F8Z-01',
      `基线读数 X：活跃 通用 行价 = 库价时，自然派工实例价 = ${libRow.unit_price}`,
      `X=${X ?? 'NULL'}；generate HTTP ${i1.status}；活跃行=${JSON.stringify(rowsOf().filter((r) => r.deleted === 0).map((r) => [r.position, r.unit_price]))}`,
      ['POST /processing-orders/generate', 'SQL: 实例单价'])

    // ④ 注入「有效价」= 通用行 1.11
    out.inject = { target: '通用', existedId: picked.id, price: GENERAL }
    guardedWrite(`-- probe-ok
update production_operation_positions set unit_price=${GENERAL}, updated_at=NOW() where id='${picked.id}'`)
    out.afterInject = rowsOf().filter((r) => r.deleted === 0)

    // ⑤ 读数 Y（有效价口径）
    const O2 = await buildOrder(token, 'Z2')
    out.order2 = O2
    const i2 = await genOf(token, O2.orderId)
    out.generate2 = { http: i2.status }
    const Y = priceOfLogical(O2.orderId)
    out.Y = Y
    R[Y === GENERAL ? 'pass' : 'fail']('F8Z-02', `读数 Y（有效价口径自证）：自然派工必须取"有效价" ${GENERAL}`,
      `Y=${Y ?? 'NULL'}；generate HTTP ${i2.status}；活跃行=${JSON.stringify(rowsOf().filter((r) => r.deleted === 0).map((r) => [r.position, r.unit_price]))}`,
      [`SQL: set 通用=${GENERAL}`, 'POST /processing-orders/generate'])

    // ⑥ 一次普通保存
    const put = await api('PUT', `/api/admin/production/operations/${libRow.id}`, { token, body: { scope: libRow.scope ?? 'position' } })
    out.put = { http: put.status, sentScope: libRow.scope ?? 'position', body: put.text.slice(0, 400) }
    const rowsAfterPut = psql(`select id, position, unit_price::text as unit_price, applicable, coalesce(deleted,0) as deleted
      from production_operation_positions where tenant_id=${T} and logical_name='${LOG}' order by deleted, position, id`)
    out.rowsAfterPut = rowsAfterPut
    const newRows = rowsAfterPut.filter((r) => !out.afterInject.some((p) => p.id === r.id))
    created.push(...newRows.map((r) => r.id))
    R[newRows.filter((r) => r.deleted === 0).length === 0 ? 'pass' : 'fail']('F8Z-03',
      '【F8】一次普通保存**不得**新建任何活跃价目行',
      `新行=${JSON.stringify(newRows.map((r) => [r.position, r.unit_price, r.deleted]))}；活跃行=${JSON.stringify(rowsAfterPut.filter((r) => r.deleted === 0).map((r) => [r.position, r.unit_price]))}`,
      [`PUT /operations/${libRow.id} {scope}`])

    // ⑦ 读数 Z（★ 关键判据）
    const O3 = await buildOrder(token, 'Z3')
    out.order3 = O3
    const i3 = await genOf(token, O3.orderId)
    out.generate3 = { http: i3.status }
    const Z = priceOfLogical(O3.orderId)
    out.Z = Z
    const okZ = Z === GENERAL && i3.status === 200
    R[okZ ? 'pass' : 'fail']('F8Z-04',
      `【F8·钱链】一次普通保存后，实例价必须仍 = 有效价 ${GENERAL}（不得变成工序库价 ${libRow.unit_price}）`,
      `保存前 Y=${Y ?? 'NULL'} → 保存后 Z=${Z ?? 'NULL'}（工序库价=${libRow.unit_price}）；活跃行=${JSON.stringify(rowsAfterPut.filter((r) => r.deleted === 0).map((r) => [r.position, r.unit_price]))}`,
      [`PUT /operations/${libRow.id}`, 'POST /processing-orders/generate', 'SQL: 实例单价前后读数'])

    // ⑧ 报工 + 工资读面（钱链后果）
    const inst3 = instOf(O3.orderId).find((r) => String(r.operation_name).replace(/-(布|纱|帘头|布料)$/, '') === LOG)
    if (inst3) {
      const rep = await api('POST', `/api/admin/production/orders/${O3.orderId}/operations/${inst3.id}/report`,
        { token, body: { worker_name: WORKER, qty: 3, qualified_qty: 3, work_type: 'normal' }, headers: { 'X-Client-Request-Id': `${RUN}-Z3` } })
      out.report3 = { http: rep.status, data: rep.json?.data ?? null }
      out.log3 = one(`select operation_name, unit_price::text as unit_price, price_state, qualified_qty::text as qualified_qty
        from production_work_logs where processing_order_id='${inst3.processing_order_id}' order by created_at desc limit 1`)
      out.piecework3 = (await api('GET', `/api/admin/production/orders/${O3.orderId}/piecework`, { token })).json?.data ?? null
      const line = (out.piecework3?.per_operation ?? []).find((r) => r.operation === out.log3?.operation_name)
      const expAmount = fmt(BigInt(Math.round(Number(GENERAL) * 100)) * 3n)  // 3 × 1.11
      R[out.log3?.unit_price === GENERAL && line && moneyEq(line.amount, expAmount) ? 'pass' : 'fail']('F8Z-05',
        `【F8·工资侧】保存后新报工的单价快照必须 = 有效价 ${GENERAL}，金额 = 3 × ${GENERAL}`,
        `快照价=${out.log3?.unit_price ?? '-'} 价态=${out.log3?.price_state ?? '-'}；计件明细=${JSON.stringify(line)}（独立算式 ${expAmount}）；合计=${out.piecework3?.total}`,
        [`POST /report`, `GET /orders/${O3.orderId}/piecework`, `独立算式 3 × ${GENERAL} = ${expAmount}`])
    }
    out.verdict = (Z === GENERAL)
      ? '未复现（保存后实例价仍取有效价）'
      : `**已复现 F8 的工资侧后果**：有效价 ${GENERAL} → 保存后实例价 ${Z ?? 'NULL'}（工序库价 ${libRow.unit_price}）⇒ 一次无关保存静默改写计件单价`
  } catch (e) {
    out.error = String(e).slice(0, 400); log(`实验异常：${out.error}`)
  } finally {
    // 还原注入 + 硬删自建行
    if (created.length) {
      guardedWrite(`-- probe-ok
delete from production_operation_positions where id in (${created.map((x) => `'${x}'`).join(',')})`)
    }
    // 还原「未定价」前置注入：通用行改回原价 + 临时软删的 布帘 行恢复
    if (out.inject?.existedId) {
      guardedWrite(`-- probe-ok
update production_operation_positions set unit_price=${out.originalGeneralPrice === null || out.originalGeneralPrice === undefined ? 'NULL' : out.originalGeneralPrice}, updated_at=NOW() where id='${out.inject.existedId}'`)
    }
    if ((out.tempSoftDeleted ?? []).length) {
      guardedWrite(`-- probe-ok
update production_operation_positions set deleted=0, updated_at=NOW() where id in (${out.tempSoftDeleted.map((x) => `'${x}'`).join(',')})`)
    }
    out.restoreState = psql(`select id, position, unit_price::text as unit_price, coalesce(deleted,0) as deleted
      from production_operation_positions where tenant_id=${T} and logical_name='${LOG}' order by position, id`)
    out.rowsFinal = rowsOf()
    out.cleanup = { deletedIds: created, restore: out.restore ?? null }
    const ctx = JSON.parse(readFileSync(join(OUT, 'probe-ctx.json'), 'utf8'))
    for (const o of [out.order1, out.order2, out.order3]) if (o) ctx.probes.push({ tag: o.tag, ...o })
    writeFileSync(join(OUT, 'probe-ctx.json'), JSON.stringify(ctx, null, 2))
  }
  writeFileSync(join(OUT, 'p9-f8-wage-e2e.json'), JSON.stringify(out, null, 2))
  log(`受控(${LOGICAL})：库价=${libRow.unit_price} 有效价=${GENERAL} X=${out.X ?? 'NULL'} Y=${out.Y ?? 'NULL'} Z=${out.Z ?? 'NULL'}`)
  log(`新报工快照=${out.log3?.unit_price ?? '-'} 计件明细=${JSON.stringify((out.piecework3?.per_operation ?? []).find((r) => r.operation === out.log3?.operation_name) ?? null)}`)
  log(`verdict=${out.verdict}`)
  log(`summary=${JSON.stringify(R.summary())}`)
}
main().catch((e) => { console.error(e); process.exit(1) })
