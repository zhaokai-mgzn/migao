// P6：**取价口径判别性实验** —— 被测构建到底跑的是「已修」还是「未修」？
//
// 背景：本轮运行时（进程 02:50 起）的 HEAD = 402be478b，F8 的修复 1d1fe5e55（08:01）**不是它的祖先**
// ⇒ 按构建点应为「未修」。但我的普通保存实验里实例价没有漂，与「未修」不符
// ⇒ 必须做**判别性**实验，而不是拿推理下结论（migao-acceptance 归因纪律）。
//
// 实验设计（三段，全部只碰自建对象 + 一条**自建价目行**，实验后按 id 硬删）：
//   ① 基线：探针单的未定价工序实例价 = NULL（有效价 = NULL）
//   ② 注入：为该逻辑工序**显式**补一条 `position='布帘'`、价 = 3.33 的价目行
//      （旧 collapse 规则「布帘列优先」⇒ 有效价变 3.33；新修法「继承已有行有效价」⇒ 仍 NULL）
//   ③ 新单实例化 ⇒ 新实例单价读数即判别值：3.33 = 未修（F8 可达）；NULL = 已修
import { writeFileSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { api, loginApi, psql, one, log, OUT, waitService, Recorder, guardedWrite, PROBE_PREFIX } from './lib.mjs'

const T = Number(process.env.TENANT_ID || 20)
const PHONE = process.env.ADMIN_PHONE || '13870217889'
const RUN = String(Date.now()).slice(-6)
const PROBE = '打包'
const INJECT_PRICE = '3.33'
const CTX = join(OUT, 'probe-ctx.json')

async function newProbeOrder(token, tag) {
  const cat = await api('POST', '/api/admin/categories', { token, body: { name: `${PROBE_PREFIX}分类${RUN}-${tag}`, sortOrder: 1 } })
  const catId = cat.json?.data?.id
  const prod = await api('POST', '/api/admin/products', {
    token, body: {
      name: `${PROBE_PREFIX}商品${RUN}-${tag}`, unit: '米', pricingType: 'fixed', basePrice: 68,
      status: catId ? 'on_sale' : 'draft', categoryId: catId,
      colors: [{ colorName: '本白', mainColorHex: '#FAFAFA', sortOrder: 1 }],
      skus: [{ colorName: '本白', doorWidth: '2.8m', price: 68, stock: 100000, skuCode: `WAGE6-${RUN}-${tag}` }],
    },
  })
  const productId = prod.json?.data?.id
  const skuId = one(`select id::text as id from product_skus where product_id='${productId}'`)?.id
  const order = await api('POST', '/api/admin/orders', {
    token, body: {
      customerName: `${PROBE_PREFIX}客户${RUN}`, customerPhone: '13300000003', customerAddress: '杭州市余杭区工资路 2 号',
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
  return { tag, catId, productId, skuId, orderId, poId: po.id, poNo: po.processing_order_no }
}

const activeRows = () => psql(`select id, position, unit_price::text as unit_price, applicable, coalesce(deleted,0) as deleted
  from production_operation_positions where tenant_id=${T} and logical_name='${PROBE}' and coalesce(deleted,0)=0 order by position, id`)
const instOf = (poId) => psql(`select id, operation_name, unit_price::text as unit_price, qty::text as qty
  from processing_position_operations where processing_order_id='${poId}' and operation_name like '${PROBE}%' and coalesce(deleted,0)=0`)

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  const R = new Recorder('p6-price-source.json')
  const { token } = await loginApi(PHONE)
  const out = { at: new Date().toISOString(), run: RUN, probe: PROBE, injectedPrice: INJECT_PRICE }

  out.activeRowsBefore = activeRows()
  out.beforeVerdict = one(`select (select count(*) from production_operation_positions
     where tenant_id=${T} and logical_name='${PROBE}' and position='布帘' and coalesce(deleted,0)=0)::int as br,
     (select count(*) from production_operation_positions
     where tenant_id=${T} and logical_name='${PROBE}' and coalesce(deleted,0)=0)::int as total`)
  R.pass('E-00', `判别性实验前置：逻辑工序「${PROBE}」的活跃价目行读数`,
    `布帘行=${out.beforeVerdict.br} 活跃行总数=${out.beforeVerdict.total}；行明细=${JSON.stringify(out.activeRowsBefore.map((r) => [r.position, r.unit_price]))}`,
    [`SQL: production_operation_positions where logical_name='${PROBE}' and deleted=0`])

  // ② 注入：把该逻辑工序**既有活跃 `布帘` 行**的价改成独特值（该表有唯一索引
  //    uk(tenant_id, logical_name, position) ⇒ 不能另插一行；这里改值、用后还原）
  const brRow = out.activeRowsBefore.find((r) => r.position === '布帘')
  const genRow = out.activeRowsBefore.find((r) => r.position === '通用')
  out.baselinePrices = { 布帘: brRow?.unit_price ?? null, 通用: genRow?.unit_price ?? null, 布帘RowId: brRow?.id ?? null }
  try {
    if (!brRow) throw new Error('该逻辑工序没有活跃的 布帘 行 ⇒ 判别实验不适用（登记未覆盖）')
    guardedWrite(`-- probe-ok
update production_operation_positions set unit_price=${INJECT_PRICE}, updated_at=NOW() where id='${brRow.id}'`)
    out.injected = psql(`select id, position, unit_price::text as unit_price from production_operation_positions where id='${brRow.id}'`)[0]
    const lp1 = await api('GET', '/api/admin/production/operation-layers', { token })
    out.readFaceAfterInject = (lp1.json?.data?.operations ?? []).filter((o) => o.operation === PROBE)

    // ③ 新单实例化 ⇒ 判别值
    const P = await newProbeOrder(token, 'E')
    out.probeOrder = P
    out.newInstance = instOf(P.poId)
    const got = out.newInstance[0]?.unit_price ?? null
    out.verdict = got === null ? '已修（有效价=未定价，未继承 布帘 列价）'
      : (got === INJECT_PRICE ? '未修（布帘列优先 ⇒ F8 取价口径可达）' : `其它口径：${got}（既非未定价亦非布帘列价）`)
    R[got === null ? 'pass' : 'fail']('E-01',
      `【判别性】把活跃 布帘 行价改为 ${INJECT_PRICE} 后，**新实例**不得取该列价（既有有效价=未定价 ⇒ 必须 NULL）`,
      `新实例单价=${got ?? 'NULL'}；基线价 布帘=${out.baselinePrices.布帘 ?? 'NULL'} 通用=${out.baselinePrices.通用 ?? 'NULL'}`,
      [`SQL: update production_operation_positions set unit_price=${INJECT_PRICE} where id='${brRow.id}'`,
       'POST /api/admin/orders → generate', `SQL: processing_position_operations where processing_order_id='${P.poId}'`])
    out.verdictAt = new Date().toISOString()
  } catch (e) {
    out.experimentError = String(e).slice(0, 300)
    R.skip('E-01', '【判别性】取价来源实验', `不可执行：${out.experimentError}`)
  } finally {
    // 还原原值（只碰这一行的价，改回原读数）
    if (brRow) {
      guardedWrite(`-- probe-ok
update production_operation_positions set unit_price=${out.baselinePrices.布帘 === null ? 'NULL' : out.baselinePrices.布帘}, updated_at=NOW() where id='${brRow.id}'`)
    }
    out.restoredRows = psql(`select id, position, unit_price::text as unit_price from production_operation_positions where id='${brRow?.id ?? 'x'}'`)
    out.activeRowsAfter = activeRows()
    const ctx = JSON.parse(readFileSync(CTX, 'utf8'))
    if (out.probeOrder) { ctx.probes.push(out.probeOrder); writeFileSync(CTX, JSON.stringify(ctx, null, 2)) }
  }
  const restoredOk = JSON.stringify((out.restoredRows ?? []).map((r) => [r.position, r.unit_price])) ===
                     JSON.stringify(brRow ? [[brRow.position, brRow.unit_price]] : [])
  R[restoredOk ? 'pass' : 'fail']('E-02', '实验注入已还原为原读数（零残留）',
    `还原后行=${JSON.stringify((out.restoredRows ?? []).map((r) => [r.position, r.unit_price]))}；活跃行=${JSON.stringify((out.activeRowsAfter ?? []).map((r) => [r.position, r.unit_price]))}`,
    [`SQL: update production_operation_positions set unit_price=<原值> where id='${out.baselinePrices?.布帘RowId}'`])

  writeFileSync(join(OUT, 'p6-price-source.json'), JSON.stringify(out, null, 2))
  log(`判别结论: ${out.verdict}`)
  log(`summary=${JSON.stringify(R.summary())}`)
}
main().catch((e) => { console.error(e); process.exit(1) })
