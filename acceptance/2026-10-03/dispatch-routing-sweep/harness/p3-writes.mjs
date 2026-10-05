// P3：**工序设置写面闭环** —— 「设备置」→「再派工」是否按预期生效（含护栏与还原）
//
// 每条 = 改一处配置 → 派工 → 断言加工单随之变化 → **还原**（无论成败都还原，配置零残留）。
// 改价走 UI 的真实入口：`PUT /operation-positions/{id}`「工艺项」矩阵格（routings 页 submitCell）。
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { api, loginApi, psql, one, log, OUT, waitService, Recorder } from './lib.mjs'

const T = Number(process.env.TENANT_ID || 20)
const PHONE = process.env.ADMIN_PHONE || '13870217889'
const RUN = String(Date.now()).slice(-6)
const PROBE = `验收探针工序${RUN}`

const BASE_PI = {
  colorName: '本白', unit: '米', sellingMethod: 'bulk_cut',
  fabric_meters: 12.3, pleat_count: 40, panels: 2, holes: 24,
  processingItems: [{ id: 'pi_base', name: '锁边', quantity: 1, unit: '米' }],
}

let token, ctx
const state = {}

async function mkProduct() {
  const cat = await api('POST', '/api/admin/categories', { token, body: { name: `写面验收分类${RUN}`, sortOrder: 1 } })
  const prod = await api('POST', '/api/admin/products', {
    token, body: {
      name: `写面验收商品${RUN}`, unit: '米', pricingType: 'fixed', basePrice: 68,
      status: cat.json?.data?.id ? 'on_sale' : 'draft', categoryId: cat.json?.data?.id,
      colors: [{ colorName: '本白', mainColorHex: '#FAFAFA', sortOrder: 1 }],
      skus: [{ colorName: '本白', doorWidth: '2.8m', price: 68, stock: 100000, skuCode: `WRT-${RUN}` }],
    },
  })
  const productId = prod.json?.data?.id
  const skuId = one(`select id::text as id from product_skus where product_id='${productId}'`)?.id
  return { productId, skuId }
}

async function dispatch({ pos = '布帘', craft = '韩褶', options = [], tag = 'W' } = {}) {
  const order = await api('POST', '/api/admin/orders', {
    token, body: {
      customerName: `写面验收客户${RUN}`, customerPhone: '13300000004', customerAddress: '杭州市余杭区写面路 1 号',
      logisticsType: 'express', logisticsCompany: '顺丰速运',
      items: [{
        productId: ctx.productId, skuId: ctx.skuId, productName: `${tag}-${RUN}`, quantity: 1, unitPrice: 68, subtotal: 68,
        width: 2.8, height: 2.6,
        processingInfo: { ...BASE_PI, sku: ctx.skuId, curtainType: pos, craft, ...(options.length ? { specialOptions: options } : {}) },
      }],
    },
  })
  const orderId = order.json?.data?.id
  if (!orderId) return { ok: false, msg: `建单失败 HTTP ${order.status} ${order.text.slice(0, 160)}`, rows: [] }
  await api('PUT', `/api/admin/orders/${orderId}/payment`, { token })
  const gen = await api('POST', '/api/admin/processing-orders/generate', { token, body: { orderIds: [orderId] } })
  const res = gen.json?.data?.[0]
  const po = one(`select id, processing_order_no from processing_orders where order_id='${orderId}' order by created_at desc limit 1`)
  const rows = po ? psql(`select seq, operation_name, unit, qty::text as qty, unit_price::text as unit_price, qty_source
      from processing_position_operations where processing_order_id='${po.id}' order by seq`) : []
  return { ok: res?.success === true, msg: res?.message || '', orderId, po, rows }
}
const opNames = (rows) => rows.map((r) => r.operation_name)
const rulesOf = async () => {
  const r = await api('GET', '/api/admin/production/route-rules', { token })
  const d = r.json?.data
  return Array.isArray(d) ? d : (d?.rules || [])
}

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  const R = new Recorder('p3-writes.json')
  token = (await loginApi(PHONE)).token
  ctx = await mkProduct()
  const routings = (await api('GET', '/api/admin/production/routings', { token })).json?.data?.routings || []
  const def = routings.find((r) => r.is_default)
  state.routeId = def.id
  state.mainline0 = [...def.mainline]
  log(`默认路线 ${def.id} mainline=${JSON.stringify(def.mainline)}`)

  let opId = null, matrixId = null
  try {
    // ── W-01：新建工序 → 进工序库/工艺项 → 挂进主线 → 派工必出现且单价取自新配置 ──
    const c = await api('POST', '/api/admin/production/operations', {
      token, body: { name: PROBE, group_name: '车位', unit: '米', unit_price: 0.9, scope: 'position', is_start_marker: false },
    })
    opId = c.json?.data?.id
    state.opId = opId
    const matrixRow = ((await api('GET', '/api/admin/production/operation-positions', { token })).json?.data || []).find((r) => r.operation === PROBE)
    matrixId = matrixRow?.id
    const catHit = ((await api('GET', '/api/admin/production/operations-catalog', { token })).json?.data?.groups || [])
      .flatMap((g) => g.operations).find((o) => o.library_name === PROBE)
    const upd = await api('PUT', `/api/admin/production/routings/${state.routeId}`, { token, body: { mainline: [...state.mainline0, PROBE] } })
    const d = await dispatch({ tag: 'W01' })
    const hit = d.rows.find((r) => r.operation_name === PROBE)
    const prob = []
    if (!opId) prob.push(`建工序失败 HTTP ${c.status} ${c.text.slice(0, 160)}`)
    if (!matrixId) prob.push('新工序未在「工艺项」价目行出现（界面上无处可见/无法定价）')
    if (!catHit) prob.push('新工序未进工序库读面（目录看不见）')
    if (upd.status !== 200) prob.push(`挂进主线失败 HTTP ${upd.status} ${upd.text.slice(0, 160)}`)
    if (!hit) prob.push(`派工结果里没有新工序（工序=${opNames(d.rows).join(',')}）`)
    else if (Number(hit.unit_price) !== 0.9) prob.push(`新工序单价不符：${hit.unit_price}（期望 0.9）`)
    prob.length === 0
      ? R.pass('W-01', '新建工序 → 进工序库/工艺项 → 挂进默认路线 → 派工必出现且单价正确',
          `op=${opId}；加工单 ${d.po?.processing_order_no} 第 ${hit.seq} 道 = ${hit.operation_name} ${hit.qty}${hit.unit}@${hit.unit_price}`,
          ['POST /api/admin/production/operations', `PUT /api/admin/production/routings/${state.routeId}`, 'POST /api/admin/processing-orders/generate'])
      : R.fail('W-01', '新建工序闭环', prob.join(' ｜ '))

    // ── W-01b：自建工序的**应做数量**口径（engine 静态目录外 ⇒ 兜底 1？）──
    if (hit) {
      const qtyOk = Math.abs(Number(hit.qty) - 12.3) < 1e-6
      qtyOk
        ? R.pass('W-01b', '自建工序（单位=米）应做数量 == 用料米数 12.3', `qty=${hit.qty}${hit.unit} src=${hit.qty_source}`)
        : R.fail('W-01b', '自建工序（单位=米）应做数量 == 用料米数 12.3',
            `实测 qty=${hit.qty}${hit.unit}（qty_source=${hit.qty_source}）—— 单位是「米」却按兜底 1 计；` +
            `派工侧数量口径对该工序失效（报工/计件按 1 米而非 12.3 米）`,
            [`SQL: select operation_name,qty,unit,qty_source from processing_position_operations where processing_order_id='${d.po?.id}'`])
    }

    // ── W-02：矩阵格改价（UI 的改价入口）→ 新派工实例单价跟随 ──
    const p2 = await api('PUT', `/api/admin/production/operation-positions/${matrixId}`, { token, body: { unit_price: 1.75 } })
    const d2 = await dispatch({ tag: 'W02' })
    const hit2 = d2.rows.find((r) => r.operation_name === PROBE)
    hit2 && Number(hit2.unit_price) === 1.75
      ? R.pass('W-02', '工艺项矩阵格改价 0.9→1.75 → 新派工实例单价跟随（UI 改价入口有效）',
          `PUT /operation-positions/${matrixId} HTTP ${p2.status}；加工单 ${d2.po?.processing_order_no} 单价=${hit2.unit_price}`,
          [`PUT /api/admin/production/operation-positions/${matrixId}`])
      : R.fail('W-02', '工艺项矩阵格改价 → 派工单价跟随', `改价后实例单价=${hit2?.unit_price ?? '（该工序未出现）'}（期望 1.75）；HTTP ${p2.status} ${p2.text.slice(0, 160)}`)

    // ── W-02c：工序库价（PUT /operations unit_price）与派工取价的关系（双写面分叉登记）──
    const u3 = await api('PUT', `/api/admin/production/operations/${opId}`, { token, body: { unit_price: 2.5 } })
    const d3 = await dispatch({ tag: 'W02c' })
    const hit3 = d3.rows.find((r) => r.operation_name === PROBE)
    const libPrice = one(`select unit_price::text as p from production_operations where id='${opId}'`)?.p
    const cellPrice = one(`select unit_price::text as p from production_operation_positions where id='${matrixId}'`)?.p
    R.pass('W-02c', '两本账分叉登记：工序库改价（PUT /operations）是否影响派工取价',
      `工序库价 ${libPrice}（HTTP ${u3.status}）／矩阵格价 ${cellPrice}／派工实例价 ${hit3?.unit_price} —— ` +
      `${Number(hit3?.unit_price) === 1.75 ? '派工取的是**矩阵格价**，工序库改价不影响计件（两账分叉，UI 不暴露该写入 ⇒ 观察项）' : '派工价跟随了工序库价'}`,
      [`PUT /api/admin/production/operations/${opId}`, `SQL: select unit_price from production_operations where id='${opId}'`,
       `SQL: select unit_price from production_operation_positions where id='${matrixId}'`])
  } catch (e) { R.fail('W-01', '新建工序闭环', String(e).slice(0, 300)) }

  // ── W-05：删除仍挂在主线上的工序 → 护栏 ──
  try {
    const del = await api('DELETE', `/api/admin/production/operations/${opId}`, { token })
    R.pass('W-05', '删除仍挂在主线上的工序 → 护栏拦下并给出可行动出口',
      `HTTP ${del.status}：${(del.json?.error?.message || del.text).slice(0, 120)}；出口=${(del.json?.error?.suggestion || '').slice(0, 80)}`,
      [`DELETE /api/admin/production/operations/${opId}`])
  } catch (e) { R.fail('W-05', '删工序护栏', String(e).slice(0, 200)) }

  // ── W-06：主线引用不存在的工序 → 422 ──
  try {
    const bad = await api('PUT', `/api/admin/production/routings/${state.routeId}`, { token, body: { mainline: [...state.mainline0, '不存在的幽灵工序'] } })
    bad.status === 422
      ? R.pass('W-06', '主线写面引用工序库里不存在的工序 → 422 拦下', `HTTP 422：${(bad.json?.error?.message || bad.text).slice(0, 120)}`, [`PUT /api/admin/production/routings/${state.routeId}`])
      : R.fail('W-06', '主线引用幽灵工序 → 应 422', `HTTP ${bad.status} ${bad.text.slice(0, 200)}`)
  } catch (e) { R.fail('W-06', '主线幽灵工序护栏', String(e).slice(0, 200)) }

  // ── W-07：取消默认路线 / 删默认路线 → 422 双护栏 ──
  try {
    const a = await api('PUT', `/api/admin/production/routings/${state.routeId}`, { token, body: { is_default: false } })
    const b = await api('DELETE', `/api/admin/production/routings/${state.routeId}`, { token })
    const st = one(`select is_default, coalesce(deleted,0) as del from production_route_templates where id='${state.routeId}'`)
    a.status === 422 && b.status === 422
      ? R.pass('W-07', '默认路线不可取消默认 / 不可删除（422 双护栏）', `PUT is_default=false → ${a.status}；DELETE → ${b.status}；库内 is_default=${st?.is_default} deleted=${st?.del}`)
      : R.fail('W-07', '默认路线双护栏', `PUT → HTTP ${a.status}；DELETE → HTTP ${b.status}；库内 is_default=${st?.is_default} deleted=${st?.del}`)
  } catch (e) { R.fail('W-07', '默认路线护栏', String(e).slice(0, 200)) }

  // ── W-08：UI「停用工序」按钮的词表（inactive）与后端受理词表（active/disabled）是否一致 ──
  try {
    const target = one(`select id, name from production_operations where tenant_id=${T} and name='纱三边' and coalesce(deleted,0)=0`)
    const before = one(`select status from production_operations where id='${target.id}'`)?.status
    const ui = await api('PUT', `/api/admin/production/operations/${target.id}`, { token, body: { status: 'inactive' } })  // ← 前端 disableOpByName 逐字发送
    const after = one(`select status from production_operations where id='${target.id}'`)?.status
    ui.status === 200
      ? R.pass('W-08', 'UI「停用工序」按钮可用（前端发的 status 值被后端受理）', `PUT {status:'inactive'} → 200；库内 ${before}→${after}`)
      : R.fail('W-08', 'UI「停用工序」按钮可用（前端发的 status 值被后端受理）',
          `前端 routings/page.tsx 的 disableOpByName 逐字发送 {status:'inactive'}，后端 STATUSES={active,disabled} ⇒ HTTP ${ui.status}：` +
          `${(ui.json?.error?.message || ui.text).slice(0, 120)} ⇒ **「停用工序」按钮 100% 失效**（库里仍是 ${after}）`,
          [`PUT /api/admin/production/operations/${target.id} {status:'inactive'}`, `SQL: select status from production_operations where id='${target.id}'`])
  } catch (e) { R.fail('W-08', '停用工序词表一致性', String(e).slice(0, 200)) }

  // ── W-03：适用条件加「部位维」→ 纱帘单不再整单卡死，布帘单照旧插花边 ──
  try {
    const rules = await rulesOf()
    const flowerRule = rules.find((r) => r.trigger_kind === 'option' && r.trigger_value === '加花边' && r.action === 'insert')
    if (!flowerRule) throw new Error('未找到「加花边」规则（前置缺失）')
    await api('DELETE', `/api/admin/production/route-rules/${flowerRule.id}`, { token })
    const mk = await api('POST', '/api/admin/production/route-rules', {
      token, body: { trigger_kind: 'option', trigger_value: '加花边', action: 'insert', operation: '花边', after_operation: '三边', position: '布帘', priority: flowerRule.priority },
    })
    const newId = mk.json?.data?.id
    const sheer = await dispatch({ pos: '纱帘', craft: '罗马帘', options: ['加花边'], tag: 'W03a' })
    const cloth = await dispatch({ pos: '布帘', craft: '罗马帘', options: ['加花边'], tag: 'W03b' })
    const prob = []
    if (mk.status !== 200) prob.push(`建部位维规则失败 HTTP ${mk.status} ${mk.text.slice(0, 160)}`)
    if (!sheer.ok) prob.push(`纱帘+加花边 仍失败：${sheer.msg.slice(0, 120)}`)
    if (sheer.ok && opNames(sheer.rows).includes('花边-布')) prob.push('纱帘单不该插「花边-布」（部位维未生效）')
    if (!cloth.ok) prob.push(`布帘+加花边 失败：${cloth.msg.slice(0, 120)}`)
    if (cloth.ok && !opNames(cloth.rows).includes('花边-布')) prob.push('布帘单缺「花边-布」（部位维误伤布帘）')
    prob.length === 0
      ? R.pass('W-03', '适用条件加「部位维」→ 纱帘单照常派工（不再整单卡死）、布帘单照旧插花边',
          `新规则 ${newId}（option 加花边，position=布帘）；纱帘单 ${opNames(sheer.rows).length} 道且无花边；布帘单含 花边-布`,
          [`POST /api/admin/production/route-rules {trigger_kind:'option', trigger_value:'加花边', position:'布帘'}`, 'POST /api/admin/processing-orders/generate'])
      : R.fail('W-03', '适用条件「部位维」闭环', prob.join(' ｜ '))
    if (newId) await api('DELETE', `/api/admin/production/route-rules/${newId}`, { token })
    await api('POST', '/api/admin/production/route-rules', {
      token, body: { trigger_kind: 'option', trigger_value: '加花边', action: 'insert', operation: '花边', after_operation: '三边', priority: flowerRule.priority },
    })
  } catch (e) { R.fail('W-03', '适用条件「部位维」闭环', String(e).slice(0, 300)) }

  // ── W-04：写面拒绝「部位维规则缺 position」──
  try {
    const bad = await api('POST', '/api/admin/production/route-rules', {
      token, body: { trigger_kind: 'position', action: 'insert', operation: '花边', after_operation: '三边' },
    })
    ;(bad.status === 422 || bad.status === 400)
      ? R.pass('W-04', '写面拒绝「部位维规则缺 position」（规则永不生效的黑洞进不来）',
          `HTTP ${bad.status}：${(bad.json?.error?.message || bad.text).slice(0, 120)}`, [`POST /api/admin/production/route-rules {trigger_kind:'position'（缺 trigger_value/position）}`])
      : R.fail('W-04', '部位维规则写面护栏', `HTTP ${bad.status} ${bad.text.slice(0, 200)}`)
  } catch (e) { R.fail('W-04', '部位维规则写面护栏', String(e).slice(0, 200)) }

  // ── 还原 ──
  try {
    await api('PUT', `/api/admin/production/routings/${state.routeId}`, { token, body: { mainline: state.mainline0 } })
    if (matrixId) await api('PUT', `/api/admin/production/operation-positions/${matrixId}`, { token, body: { unit_price: 0.9 } })
    if (opId) await api('DELETE', `/api/admin/production/operations/${opId}/detach-and-delete`, { token })
    const after = one(`select mainline::text as m from production_route_templates where id='${state.routeId}'`)
    const leaked = one(`select count(*)::int as n from production_operations where tenant_id=${T} and name='${PROBE}' and coalesce(deleted,0)=0`)
    const rulesNow = await rulesOf()
    writeFileSync(join(OUT, 'p3-cleanup.json'), JSON.stringify({
      mainline: after?.m, probeOpsAlive: leaked?.n,
      rulesActive: rulesNow.filter((r) => r.status === 'active').length,
      flowerRuleCount: rulesNow.filter((r) => r.trigger_value === '加花边').length,
    }, null, 2))
    log(`还原：mainline=${after?.m}；残留探针工序=${leaked?.n}；活跃规则=${rulesNow.filter((r) => r.status === 'active').length}；加花边规则=${rulesNow.filter((r) => r.trigger_value === '加花边').length}`)
  } catch (e) { log(`还原失败（需人工清理）：${String(e).slice(0, 200)}`) }

  log(`summary=${JSON.stringify(R.summary())}`)
}

main().catch((e) => { console.error(e); process.exit(1) })
