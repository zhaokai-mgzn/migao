// P1+P2：计件工资链「钱的链路」判据矩阵
//
// 🔴 判据的**唯一期望来源** = 我们自己的算式（独立算式）：
//      金额 = Σ_笔 HALF_UP(合格数量 × **报工自己的 unit_price 快照** × factor 快照)
//    口径来源与行号见 REPORT §「口径来源」。**绝不**拿被测系统自己的读面当期望 ——
//    上一轮 F8 就是靠「期望跟着被改坏的读面漂」藏住的（44 条场景全绿）。
//
// 探针对象全部自建（前缀「工资验收」）：分类 → 商品 → 订单 → 加工单 → 工序实例 → 报工。
// 实例单价用**定点 SQL** 写死（只改本探针订单自己的实例行）⇒ 把工资口径从共享配置里解耦，
// 不依赖也不修改并行包正在改写的工序库/价目表。
//
// 用法：node harness/p1-p2-matrix.mjs
import { writeFileSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import {
  api, loginApi, psql, one, log, OUT, waitService, Recorder,
  cents, fmt, moneyEq, PROBE_PREFIX, guardedWrite,
} from './lib.mjs'

const T = Number(process.env.TENANT_ID || 20)
const PHONE = process.env.ADMIN_PHONE || '13870217889'
const RUN = String(Date.now()).slice(-6)
const PERIOD = process.env.PERIOD || new Date().toISOString().slice(0, 7)
const CTX_FILE = join(OUT, 'probe-ctx.json')
const PROBE_CATEGORY = `${PROBE_PREFIX}分类${RUN}`
const PROBE_PRODUCT = `${PROBE_PREFIX}商品${RUN}`
const PROBE_CUSTOMER = `${PROBE_PREFIX}客户${RUN}`
const WORKER_A = `${PROBE_PREFIX}工人甲${RUN}`
const WORKER_B = `${PROBE_PREFIX}工人乙${RUN}`
const RATED = 0.4     // 探针定价（元/单位）
const RATED2 = 1.25   // 第二档价（用于跨单/改价判据）

// ══════════════════════ 判据函数（可被红证复用 —— 红证跑的就是这些真函数） ══════════════════════

/** M7-02：未定价工序不得以「0 元」混进 per_operation 金额。 */
export const predUnpricedNotZeroInDetail = (perOpRows, opUnpriced) => {
  const hit = (perOpRows || []).filter((r) => r.operation === opUnpriced)
  return hit.length === 0
}
/** M1-01：明细逐分 == 独立算式。 */
export const predDetailEqualsOwnMath = (perOpRows, expByOp) => {
  const diffs = []
  const seen = new Set()
  for (const row of perOpRows || []) {
    seen.add(row.operation)
    const e = expByOp.get(row.operation) ?? 0n
    if (cents(row.amount) !== e) diffs.push(`${row.operation}: 读面 ${row.amount} ≠ 独立算式 ${fmt(e)}`)
  }
  for (const [k, v] of expByOp) if (!seen.has(k)) diffs.push(`${k}: 独立算式 ${fmt(v)}，读面缺该行`)
  return diffs
}
/** M2-01 / M5-01：总额逐分 == 独立算式。 */
export const predTotalEqualsOwnMath = (readTotal, expTotal) => cents(readTotal) === expTotal
/** M4/M5：某一维合计 == total。 */
export const predDimSumEqualsTotal = (rows, total) =>
  (rows || []).reduce((a, v) => a + (cents(v.amount) ?? 0n), 0n) === cents(total)
/** M7-01：未定价块显式可见且数量正确。 */
export const predUnpricedVisibleWithQty = (unpricedBlock, opUnpriced, expQty) => {
  const ops = unpricedBlock?.operations ?? []
  const sum = ops.reduce((a, v) => a + (cents(v.qty) ?? 0n), 0n)
  return ops.some((o) => o.operation === opUnpriced) && sum === expQty
}

// ══════════════════════ 建探针对象 ══════════════════════

async function buildProbe(token, { tag }) {
  const cat = await api('POST', '/api/admin/categories', { token, body: { name: `${PROBE_CATEGORY}-${tag}`, sortOrder: 1 } })
  const catId = cat.json?.data?.id
  const prod = await api('POST', '/api/admin/products', {
    token, body: {
      name: `${PROBE_PRODUCT}-${tag}`, unit: '米', pricingType: 'fixed', basePrice: 68,
      status: catId ? 'on_sale' : 'draft', categoryId: catId,
      colors: [{ colorName: '本白', mainColorHex: '#FAFAFA', sortOrder: 1 }],
      skus: [{ colorName: '本白', doorWidth: '2.8m', price: 68, stock: 100000, skuCode: `WAGE-${RUN}-${tag}` }],
    },
  })
  const productId = prod.json?.data?.id
  const skuId = one(`select id::text as id from product_skus where product_id='${productId}'`)?.id
  if (!productId || !skuId) throw new Error(`探针商品创建失败 ${prod.status}: ${prod.text.slice(0, 200)}`)

  const items = [{
    productId, skuId, productName: `${PROBE_PREFIX}行-${tag}`, quantity: 1, unitPrice: 68, subtotal: 68,
    width: 2.8, height: 2.6,
    processingInfo: {
      sku: null, colorName: '本白', unit: '米', sellingMethod: 'bulk_cut',
      fabric_meters: 12.3, pleat_count: 40, panels: 2, holes: 24, fullness: 2, fullness_actual: 2,
      curtainType: '布帘', craft: '罗马帘',
      processingItems: [{ id: `pi_${tag}`, name: '锁边', quantity: 1, unit: '米' }],
    },
  }]
  const order = await api('POST', '/api/admin/orders', {
    token, body: {
      customerName: PROBE_CUSTOMER, customerPhone: '13300000003', customerAddress: '杭州市余杭区工资路 1 号',
      logisticsType: 'express', logisticsCompany: '顺丰速运', items,
    },
  })
  const orderId = order.json?.data?.id
  if (!orderId) throw new Error(`探针建单失败 ${order.status}: ${order.text.slice(0, 300)}`)
  await api('PUT', `/api/admin/orders/${orderId}/payment`, { token })
  const gen = await api('POST', '/api/admin/processing-orders/generate', { token, body: { orderIds: [orderId] } })
  const po = one(`select id, processing_order_no from processing_orders where order_id='${orderId}' and tenant_id=${T} order by created_at desc limit 1`)
  if (!po) throw new Error(`探针派工失败：${gen.text.slice(0, 300)}`)
  return { tag, catId, productId, skuId, orderId, poId: po.id, poNo: po.processing_order_no }
}

function setInstancePrices(poId, map) {
  const sets = Object.entries(map).map(([name, { price, qty }]) => {
    const p = price === null ? 'NULL' : String(price)
    const q = qty === undefined ? '' : `, qty=${qty}`
    return `-- probe-ok\nupdate processing_position_operations set unit_price=${p}${q}, updated_at=NOW()
            where processing_order_id='${poId}' and operation_name='${name}'`
  }).join(';\n')
  guardedWrite(sets)
}

const instRows = (poId) => psql(`
  select id, operation_name, position_name, seq, unit, qty::text as qty, done_qty::text as done_qty,
         unit_price::text as unit_price, factor::text as factor, status
  from processing_position_operations
  where processing_order_id='${poId}' and coalesce(deleted,0)=0 order by position_name, seq`)

const logRows = (poIds) => psql(`
  select l.id, l.operation_id, l.operation_name, l.worker_name, l.qualified_qty::text as qualified_qty,
         l.qty::text as qty, l.unit_price::text as unit_price, l.factor::text as factor,
         l.price_state, l.work_type, l.work_date::text as work_date, l.processing_order_id,
         po.processing_order_no
  from production_work_logs l join processing_orders po on po.id = l.processing_order_id
  where l.tenant_id=${T} and coalesce(l.deleted,0)=0 and l.processing_order_id in (${poIds.map((x) => `'${x}'`).join(',')})
  order by l.created_at`)

// ── 十进制精确乘法 + HALF_UP 取整到分（全程 BigInt/字符串，零浮点） ──
function decMul(a, b) {
  const [ai, af = ''] = String(a).split('.')
  const [bi, bf = ''] = String(b).split('.')
  const av = BigInt(ai + af), bv = BigInt(bi + bf)
  const scale = af.length + bf.length
  const prod = (av * bv).toString().padStart(scale + 1, '0')
  const int = prod.slice(0, prod.length - scale) || '0'
  const frac = scale ? prod.slice(prod.length - scale) : ''
  return frac ? `${int}.${frac}` : int
}
function toCentsHalfUp(decStr) {
  const neg = String(decStr).startsWith('-')
  const s = neg ? String(decStr).slice(1) : String(decStr)
  const [i, f = ''] = s.split('.')
  const t = (f + '000').slice(0, 3)
  let c = BigInt(i) * 100n + BigInt(t.slice(0, 2))
  if (Number(t[2]) >= 5) c += 1n
  return neg ? -c : c
}

/**
 * 独立算式（唯一期望来源）。口径来源见 REPORT §3「口径来源（文件:行号）」：
 *  · 金额 = Σ 逐笔 HALF_UP(qualifiedQty × unitPrice快照 × factor快照)
 *      ProductionService.java:1633-1638
 *  · 未定价（price_state='unpriced'）不进金额  :1621-1626
 *  · 返工/报废不计件（work_type != 'normal'）  :1584-1586
 */
function expectedCents(rows, { worker = null } = {}) {
  let total = 0n
  const perWorker = new Map(), perOp = new Map(), unpricedQty = new Map()
  let dropped = 0
  for (const r of rows) {
    if (r.work_type !== 'normal') { dropped++; continue }
    if (worker && r.worker_name !== worker) continue
    if (r.price_state === 'unpriced') {
      unpricedQty.set(r.operation_name, (unpricedQty.get(r.operation_name) || 0n) + toCentsHalfUp(r.qualified_qty))
      continue
    }
    if (r.unit_price === null) throw new Error(`探针报工行缺单价快照（不应出现）: ${r.id}`)
    const factor = r.factor === null ? '1' : r.factor
    const amt = toCentsHalfUp(decMul(decMul(r.qualified_qty, r.unit_price), factor))
    total += amt
    const k = r.worker_name ?? '未分配'
    perWorker.set(k, (perWorker.get(k) || 0n) + amt)
    perOp.set(r.operation_name, (perOp.get(r.operation_name) || 0n) + amt)
  }
  return { total, perWorker, perOp, unpricedQty, dropped }
}

// ══════════════════════ 主流程 ══════════════════════
async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  const R = new Recorder('p1p2-matrix.json')
  const redproof = { at: new Date().toISOString(), steps: [] }
  const saveRed = () => writeFileSync(join(OUT, 'redproof.json'), JSON.stringify(redproof, null, 2))
  const red = (id, name, predicateName, injected, ranOnInjected, controlOnClean) => {
    const ok = ranOnInjected === false && controlOnClean === true
    redproof.steps.push({ id, name, predicate: predicateName, injectedReading: injected, verdictOnInjected: ranOnInjected ? 'GREEN' : 'RED', controlOnCleanReading: controlOnClean, verdict: ok ? 'RED-证成立' : '红证失败（判据太弱/恒红）', at: new Date().toISOString() })
    saveRed()
    return ok
  }

  const { token } = await loginApi(PHONE)
  const ctx = { meta: { at: new Date().toISOString(), run: RUN, period: PERIOD, prefix: PROBE_PREFIX, tenantId: T }, probes: [] }
  const save = () => writeFileSync(CTX_FILE, JSON.stringify(ctx, null, 2))

  // ── P1：自建两个探针单 ──
  const A = await buildProbe(token, { tag: 'A' })
  ctx.probes.push(A); save()
  R.pass('P1-01', '探针单 A 自建（分类/商品/订单/加工单）',
    `order=${A.orderId.slice(0, 8)}… po=${A.poNo}`, [`POST /api/admin/orders`, `POST /api/admin/processing-orders/generate`, `SQL: processing_orders.id='${A.poId}'`])

  let rowsA = instRows(A.poId)
  R[rowsA.length > 0 ? 'pass' : 'fail']('P1-02', '探针单 A 已实例化工序',
    `${rowsA.length} 道：${rowsA.map((r) => r.operation_name).join(' → ')}`,
    [`SQL: processing_position_operations where processing_order_id='${A.poId}'`])
  if (!rowsA.length) throw new Error('探针单无工序实例，后续判据不可执行')

  const names = rowsA.map((r) => r.operation_name)
  const opRated1 = names[0], opRated2 = names[1], opZero = names[2], opUnpriced = names[3]
  setInstancePrices(A.poId, {
    [opRated1]: { price: RATED, qty: 20 },
    [opRated2]: { price: RATED, qty: 20 },
    [opZero]: { price: 0, qty: 20 },        // 显式定价 0 元（≠ 未定价）
    [opUnpriced]: { price: null, qty: 20 }, // 未定价
  })
  rowsA = instRows(A.poId)
  const priceOf = (n) => (rowsA.find((r) => r.operation_name === n)?.unit_price ?? null)
  const pricingOk = priceOf(opRated1) === '0.40' && priceOf(opZero) === '0.00' && priceOf(opUnpriced) === null
  R[pricingOk ? 'pass' : 'fail']('P1-03', '探针定型：有价 0.40 / 显式 0 元 / 未定价(NULL) 三态可区分',
    `${opRated1}=${priceOf(opRated1)} · ${opZero}=${priceOf(opZero)} · ${opUnpriced}=${priceOf(opUnpriced)}`,
    [`SQL: update processing_position_operations … where processing_order_id='${A.poId}'`])

  const instId = (n) => rowsA.find((r) => r.operation_name === n).id
  const report = (p, id, body, key) => api('POST',
    `/api/admin/production/orders/${p.orderId}/operations/${id}/report`,
    { token, body, headers: key ? { 'X-Client-Request-Id': key } : {} })

  // ── 报工（正常路径 + 边界形态） ──
  const r1 = await report(A, instId(opRated1), { worker_name: WORKER_A, qty: 8, qualified_qty: 8, work_type: 'normal' }, `${RUN}-A1`)   // 部分报工
  const r2 = await report(A, instId(opRated2), { worker_name: WORKER_A, qty: 20, qualified_qty: 20, work_type: 'normal' }, `${RUN}-A2`) // 报满
  const r3 = await report(A, instId(opZero), { worker_name: WORKER_A, qty: 20, qualified_qty: 20, work_type: 'normal' }, `${RUN}-A3`)    // 显式 0 元
  const r4 = await report(A, instId(opUnpriced), { worker_name: WORKER_A, qty: 5, qualified_qty: 5, work_type: 'normal' }, `${RUN}-A4`) // 未定价
  const r5 = await report(A, instId(opRated1), { worker_name: WORKER_A, qty: 3, qualified_qty: 3, work_type: 'rework' }, `${RUN}-A5`)   // 返工
  const reports = { r1: r1.status, r2: r2.status, r3: r3.status, r4: r4.status, r5: r5.status }
  R[Object.values(reports).every((s) => s === 200) ? 'pass' : 'fail']('P1-04',
    '报工落库（部分报工 / 报满 / 显式 0 元 / 未定价 / 返工）', JSON.stringify(reports),
    [`POST /api/admin/production/orders/{orderId}/operations/{operationId}/report ×5`])
  if (!Object.values(reports).every((s) => s === 200)) {
    writeFileSync(join(OUT, 'p1p2-fail.json'), JSON.stringify({ reports, bodies: { r1: r1.text.slice(0, 300), r2: r2.text.slice(0, 300), r3: r3.text.slice(0, 300), r4: r4.text.slice(0, 300), r5: r5.text.slice(0, 300) } }, null, 2))
  }

  // ── P2 判据 ──
  const logsA = logRows([A.poId])
  const expA = expectedCents(logsA)
  const expByOp = expA.perOp
  ctx.p2 = { logsA, expA: { total: fmt(expA.total), perOp: [...expByOp].map(([k, v]) => [k, fmt(v)]) } }

  const pw = await api('GET', `/api/admin/production/orders/${A.orderId}/piecework`, { token })
  const pwData = pw.json?.data ?? null
  const detailRows = pwData?.per_operation ?? []
  const pwTotal = cents(pwData?.total)

  const diffs = predDetailEqualsOwnMath(detailRows, expByOp)
  R[diffs.length === 0 ? 'pass' : 'fail']('M1-01', '【逐分】per_operation 明细 == 独立算式（数量 × 快照单价，逐笔取整）',
    diffs.length === 0 ? `${detailRows.length} 道逐分相符` : diffs.join(' | '),
    [`GET /api/admin/production/orders/${A.orderId}/piecework`, `独立算式: ${[...expByOp].map(([k, v]) => k + '=' + fmt(v)).join(', ')}`])

  R[predTotalEqualsOwnMath(pwData?.total, expA.total) ? 'pass' : 'fail']('M2-01',
    '【逐分】per-order total == 独立算式合计', `读面 ${pwData?.total} vs 独立算式 ${fmt(expA.total)}`,
    [`GET /api/admin/production/orders/${A.orderId}/piecework`])

  const pwWorkerSum = Object.values(pwData?.per_worker ?? {}).reduce((a, v) => a + (cents(v) ?? 0n), 0n)
  R[pwWorkerSum === pwTotal ? 'pass' : 'fail']('M3-01', '【逐分】per_worker 之和 == total（无二次兜底）',
    `Σ=${fmt(pwWorkerSum)} total=${pwData?.total}`, [`GET …/piecework → .per_worker`])

  for (const dim of ['per_position', 'per_set']) {
    R[predDimSumEqualsTotal(pwData?.[dim], pwData?.total) ? 'pass' : 'fail'](`M4-${dim}`,
      `【逐分】${dim} 合计 == total`,
      `Σ=${fmt((pwData?.[dim] ?? []).reduce((a, v) => a + (cents(v.amount) ?? 0n), 0n))} total=${pwData?.total}`,
      [`GET …/piecework → .${dim}`])
  }

  const sum = await api('GET', `/api/admin/production/piecework/summary?period=${PERIOD}&worker_name=${encodeURIComponent(WORKER_A)}`, { token })
  const sumData = sum.json?.data ?? null
  ctx.p2.sumData = sumData
  R[predTotalEqualsOwnMath(sumData?.total, expA.total) ? 'pass' : 'fail']('M5-01',
    '【逐分】期间报表（按探针工人下钻）total == 独立算式合计',
    `报表 ${sumData?.total} vs 独立算式 ${fmt(expA.total)}`,
    [`GET /api/admin/production/piecework/summary?period=${PERIOD}&worker_name=${WORKER_A}`])
  const sumPW = (sumData?.per_worker ?? []).reduce((a, v) => a + (cents(v.amount) ?? 0n), 0n)
  R[sumPW === cents(sumData?.total) ? 'pass' : 'fail']('M5-02', '【逐分】报表 per_worker 合计 == 报表 total',
    `Σ=${fmt(sumPW)} total=${sumData?.total}`, [`GET …/piecework/summary → .per_worker`])
  const sumPO = (sumData?.per_operation ?? []).reduce((a, v) => a + (cents(v.amount) ?? 0n), 0n)
  R[sumPO === cents(sumData?.total) ? 'pass' : 'fail']('M5-03', '【逐分】报表 per_operation 合计 == 报表 total',
    `Σ=${fmt(sumPO)} total=${sumData?.total}`, [`GET …/piecework/summary → .per_operation`])
  for (const dim of ['per_position', 'per_set']) {
    R[predDimSumEqualsTotal(sumData?.[dim], sumData?.total) ? 'pass' : 'fail'](`M5-${dim}`,
      `【逐分】报表 ${dim} 合计 == total`,
      `Σ=${fmt((sumData?.[dim] ?? []).reduce((a, v) => a + (cents(v.amount) ?? 0n), 0n))} total=${sumData?.total}`,
      [`GET …/piecework/summary → .${dim}`])
  }

  // 三端点同源恒等
  const wl = await api('GET', `/api/admin/agent/production/worklog?order_no=${A.poNo}`, { token })
  const wlAmt = wl.json?.data?.totals?.piecework_amount ?? null
  R[moneyEq(wlAmt, pwData?.total) && moneyEq(sumData?.total, pwData?.total) ? 'pass' : 'fail']('M6-01',
    '三端点同源恒等：per-order == 报表(同人) == agent worklog',
    `per-order=${pwData?.total} 报表=${sumData?.total} worklog=${wlAmt}`,
    [`GET /orders/{id}/piecework`, `GET /piecework/summary`, `GET /agent/production/worklog?order_no=${A.poNo}`])
  ctx.p2.worklog = wl.json?.data ?? null

  // 缺失 ≠ 0（三态）
  const expUnpQty = [...expA.unpricedQty.values()].reduce((a, v) => a + v, 0n)
  R[predUnpricedVisibleWithQty(pwData?.unpriced, opUnpriced, expUnpQty) ? 'pass' : 'fail']('M7-01',
    '【缺失≠0】未定价工序在 unpriced 块显式可见且数量正确',
    `unpriced=${JSON.stringify(pwData?.unpriced?.operations)}；独立算式未定价数量=${fmt(expUnpQty)}`,
    [`GET /orders/{id}/piecework → .unpriced`])
  R[predUnpricedNotZeroInDetail(detailRows, opUnpriced) ? 'pass' : 'fail']('M7-02',
    '【缺失≠0】未定价工序不得以「0 元」混进 per_operation 金额',
    `per_operation 中 ${opUnpriced} 的读数: ${JSON.stringify(detailRows.filter((r) => r.operation === opUnpriced))}`,
    [`GET /orders/{id}/piecework → .per_operation`])
  const zeroRow = detailRows.find((r) => r.operation === opZero)
  const zeroNotUnpriced = !(pwData?.unpriced?.operations ?? []).some((o) => o.operation === opZero)
  R[!!zeroRow && cents(zeroRow.amount) === 0n && zeroNotUnpriced ? 'pass' : 'fail']('M7-03',
    '【三态】显式定价 0 元 ≠ 未定价（0 元进金额、不进 unpriced 清单）',
    `${opZero}: per_operation=${JSON.stringify(zeroRow)}；在 unpriced 清单=${!zeroNotUnpriced}`,
    [`GET /orders/{id}/piecework`])

  // 双付：幂等键重放
  const key = `${RUN}-IDEM`
  await report(A, instId(opRated2), { worker_name: WORKER_A, qty: 1, qualified_qty: 1, work_type: 'normal' }, key)
  const before = logRows([A.poId]).length
  const replay = await report(A, instId(opRated2), { worker_name: WORKER_A, qty: 1, qualified_qty: 1, work_type: 'normal' }, key)
  const after = logRows([A.poId]).length
  R[before === after && replay.json?.data?.replayed === true ? 'pass' : 'fail']('M8-01',
    '【双付】同 X-Client-Request-Id 重放：报工行数不增 + replayed=true',
    `行数 ${before}→${after}；replayed=${replay.json?.data?.replayed}；HTTP ${replay.status}`,
    [`POST …/report 带 X-Client-Request-Id=${key} ×2`])

  // 超报拒绝
  const over = await report(A, instId(opRated1), { worker_name: WORKER_A, qty: 5, qualified_qty: 5, work_type: 'normal' }, `${RUN}-OVER`)
  R[over.status === 422 && /超上限/.test(over.json?.error?.message || '') ? 'pass' : 'fail']('M9-01',
    '【边界】超应做数量 ⇒ 422 拒绝（不得静默截断/丢明细）',
    `HTTP ${over.status} ${(over.json?.error?.message || '').slice(0, 90)}`,
    [`POST …/report qty=5（opRated1 已报 8+3 返工 / 应做 20，剩余 12）`])

  // 改价后重算口径
  const expBefore = expectedCents(logRows([A.poId]))
  guardedWrite(`-- probe-ok
update processing_position_operations set unit_price=9.99, updated_at=NOW()
                where processing_order_id='${A.poId}' and operation_name='${opRated2}'`)
  const pwAfter = await api('GET', `/api/admin/production/orders/${A.orderId}/piecework`, { token })
  const snapKept = predTotalEqualsOwnMath(pwAfter.json?.data?.total, expBefore.total)
  R[snapKept ? 'pass' : 'fail']('M10-01',
    '【改价口径】实例改价后历史报工仍按**报工快照价**（不追溯）',
    `改价前独立算式 ${fmt(expBefore.total)}；改价后读面 ${pwAfter.json?.data?.total}`,
    [`SQL: update processing_position_operations set unit_price=9.99`, `GET /orders/{A.orderId}/piecework`])
  guardedWrite(`-- probe-ok
update processing_position_operations set unit_price=${RATED}, updated_at=NOW()
                where processing_order_id='${A.poId}' and operation_name='${opRated2}'`)
  // 反向：改价后的**新**报工必须按新价
  const rNew = await report(A, instId(opRated2), { worker_name: WORKER_A, qty: 1, qualified_qty: 1, work_type: 'normal' }, `${RUN}-NEWPRICE`)
  await api('GET', `/api/admin/production/orders/${A.orderId}/piecework`, { token })
  const expAfterNew = expectedCents(logRows([A.poId]))
  const newLog = logRows([A.poId]).slice(-1)[0]
  R[rNew.status === 200 && newLog.unit_price === '0.40' && predTotalEqualsOwnMath(fmt(expAfterNew.total), expAfterNew.total) ? 'pass' : 'fail']('M10-02',
    '【改价口径·反向】还原价后新报工按还原价快照（逐笔可追溯）',
    `新报工快照 unit_price=${newLog?.unit_price}（期望 0.40）；独立算式 ${fmt(expAfterNew.total)}`,
    [`POST …/report`, `SQL: 最新 production_work_logs 行`])

  // 跨单汇总
  const B = await buildProbe(token, { tag: 'B' })
  ctx.probes.push(B); save()
  let rowsB = instRows(B.poId)
  setInstancePrices(B.poId, { [rowsB[0].operation_name]: { price: RATED2, qty: 20 } })
  rowsB = instRows(B.poId)
  const opB1 = rowsB[0].operation_name
  await report(B, rowsB[0].id, { worker_name: WORKER_A, qty: 6, qualified_qty: 6, work_type: 'normal' }, `${RUN}-B1`)
  await report(B, rowsB[0].id, { worker_name: WORKER_B, qty: 4, qualified_qty: 4, work_type: 'normal' }, `${RUN}-B2`)
  const logsAB = logRows([A.poId, B.poId])
  const expAOnly = expectedCents(logsAB, { worker: WORKER_A })
  const sumAB = await api('GET', `/api/admin/production/piecework/summary?period=${PERIOD}&worker_name=${encodeURIComponent(WORKER_A)}`, { token })
  R[predTotalEqualsOwnMath(sumAB.json?.data?.total, expAOnly.total) ? 'pass' : 'fail']('M11-01',
    '【跨单】同一工人多张单 ⇒ 报表合计 == 该工人两单独立算式之和',
    `报表 ${sumAB.json?.data?.total} vs 独立算式 ${fmt(expAOnly.total)}`,
    [`GET /piecework/summary?period=${PERIOD}&worker_name=${WORKER_A}`])
  // 另一工人独立成行（不得并错人）
  const expBOnly = expectedCents(logsAB, { worker: WORKER_B })
  const sumB = await api('GET', `/api/admin/production/piecework/summary?period=${PERIOD}&worker_name=${encodeURIComponent(WORKER_B)}`, { token })
  R[predTotalEqualsOwnMath(sumB.json?.data?.total, expBOnly.total) ? 'pass' : 'fail']('M11-02',
    '【按人隔离】换一个工人 ⇒ 报表合计只含该工人的报工',
    `报表 ${sumB.json?.data?.total} vs 独立算式 ${fmt(expBOnly.total)}`,
    [`GET /piecework/summary?period=${PERIOD}&worker_name=${WORKER_B}`])

  // 返工不计件
  const reworkRows = logsAB.filter((r) => r.work_type === 'rework')
  R[reworkRows.length > 0 && predTotalEqualsOwnMath(sumAB.json?.data?.total, expAOnly.total) ? 'pass' : 'fail']('M12-01',
    '【口径】返工不计件（独立算式排除后与读数逐分一致）',
    `返工行 ${reworkRows.length} 条；报表 ${sumAB.json?.data?.total} == 独立算式 ${fmt(expAOnly.total)}`,
    [`SQL: work_type='rework' 的行`, `GET /piecework/summary`])

  // 日期边界（+08）
  const movable = logsAB.find((r) => r.processing_order_id === B.poId)
  guardedWrite(`-- probe-ok
update production_work_logs set work_date = date_trunc('month', work_date) - interval '1 day'
                where id='${movable.id}'`)
  const sumMoved = await api('GET', `/api/admin/production/piecework/summary?period=${PERIOD}&worker_name=${encodeURIComponent(WORKER_A)}`, { token })
  const expMoved = expectedCents(logRows([A.poId, B.poId]).filter((r) => r.work_date.startsWith(PERIOD)), { worker: WORKER_A })
  R[predTotalEqualsOwnMath(sumMoved.json?.data?.total, expMoved.total) ? 'pass' : 'fail']('M13-01',
    '【日期边界】work_date 移出本期 ⇒ 报表按 work_date 区间精确过滤（+08 业务时钟落本地日）',
    `移出后报表 ${sumMoved.json?.data?.total} vs 独立算式（仅本期行）${fmt(expMoved.total)}；被移行原 date=${movable.work_date}`,
    [`SQL: update production_work_logs set work_date = 上月最后一天`, `GET /piecework/summary?period=${PERIOD}`])
  guardedWrite(`-- probe-ok
update production_work_logs set work_date='${movable.work_date}' where id='${movable.id}'`)

  // qty=0
  const z = await report(A, instId(opZero), { worker_name: WORKER_A, qty: 0, qualified_qty: 0, work_type: 'normal' }, `${RUN}-Z0`)
  const zRows = psql(`select count(*)::int as n from production_work_logs where processing_order_id='${A.poId}' and qty=0`)[0].n
  R[z.status === 422 && zRows === 0 ? 'pass' : 'fail']('M14-01',
    '【边界】qty=0 报工被拒且不落 0 元行', `HTTP ${z.status}；库里 qty=0 行数 ${zRows}`, [`POST …/report qty=0`])

  // 软删报工行
  const victim = logRows([A.poId])[0]
  guardedWrite(`-- probe-ok
update production_work_logs set deleted=1 where id='${victim.id}'`)
  const pwDel = await api('GET', `/api/admin/production/orders/${A.orderId}/piecework`, { token })
  const expDel = expectedCents(logRows([A.poId]))
  R[predTotalEqualsOwnMath(pwDel.json?.data?.total, expDel.total) ? 'pass' : 'fail']('M15-01',
    '【作废】软删的报工行不计件（读面 == 剩余行独立算式）',
    `软删 1 行后读面 ${pwDel.json?.data?.total} vs 独立算式 ${fmt(expDel.total)}`,
    [`SQL: update production_work_logs set deleted=1 where id='${victim.id}'`, `GET /orders/{id}/piecework`])
  guardedWrite(`-- probe-ok
update production_work_logs set deleted=0 where id='${victim.id}'`)

  // ══════════ 红证（跑的是上面**真判据函数**，喂注入读数） ══════════
  const injDetail = [...detailRows, { operation: opUnpriced, amount: 0, qty: 1, logical_name: opUnpriced }]
  const red1 = red('RED-01', '注入式：把未定价工序按「0 元」混进 per_operation 明细', 'predUnpricedNotZeroInDetail()',
    `per_operation 追加 {operation:'${opUnpriced}', amount:0}`,
    predUnpricedNotZeroInDetail(injDetail, opUnpriced), predUnpricedNotZeroInDetail(detailRows, opUnpriced))
  R[red1 ? 'pass' : 'fail']('RED-01', '【红证·注入式】未定价混进明细 ⇒ M7-02 判据必红',
    `注入读数下判据=${predUnpricedNotZeroInDetail(injDetail, opUnpriced)}（期望 false）；干净读数下=${predUnpricedNotZeroInDetail(detailRows, opUnpriced)}（期望 true）`,
    ['out/redproof.json #RED-01'])
  const red2 = red('RED-02', '注入式：total 少/多一分', 'predTotalEqualsOwnMath()',
    `total='${fmt(expA.total + 1n)}'（真实 ${fmt(expA.total)}）`,
    predTotalEqualsOwnMath(fmt(expA.total + 1n), expA.total), predTotalEqualsOwnMath(fmt(expA.total), expA.total))
  R[red2 ? 'pass' : 'fail']('RED-02', '【红证·注入式】差一分 ⇒ M2-01 逐分判据必红',
    `差一分读数下判据=${predTotalEqualsOwnMath(fmt(expA.total + 1n), expA.total)}（期望 false）`,
    ['out/redproof.json #RED-02'])
  const red3 = red('RED-03', '注入式：明细行少一道', 'predDetailEqualsOwnMath()',
    `去掉 ${opRated1} 的明细行`,
    predDetailEqualsOwnMath(detailRows.filter((r) => r.operation !== opRated1), expByOp).length === 0,
    predDetailEqualsOwnMath(detailRows, expByOp).length === 0)
  R[red3 ? 'pass' : 'fail']('RED-03', '【红证·注入式】漏一道工序明细 ⇒ M1-01 必红',
    `漏行读数下 diffs=${JSON.stringify(predDetailEqualsOwnMath(detailRows.filter((r) => r.operation !== opRated1), expByOp))}`,
    ['out/redproof.json #RED-03'])

  // ══════════ 已知缺陷 F8 正对照（在本轮被测构建上复现其工资侧影响） ══════════
  const opCatalog = await api('GET', '/api/admin/production/operations-catalog', { token })
  const unpricedLogical = String(opUnpriced).replace(/-(布|纱|帘头)$/, '')
  const catalogArr = opCatalog.json?.data?.operations ?? opCatalog.json?.data ?? []
  const catalogRow = (Array.isArray(catalogArr) ? catalogArr : []).find((o) => o.name === unpricedLogical)
  const f8 = { attempted: false, at: new Date().toISOString(), unpricedOp: opUnpriced, unpricedLogical }
  if (catalogRow?.id) {
    f8.attempted = true
    f8.opId = catalogRow.id
    f8.beforeLibPrice = psql(`select unit_price::text as p from production_operations where id='${catalogRow.id}'`)[0]?.p
    f8.beforeProbeInstancePrice = priceOf(opUnpriced)
    f8.beforePositionRows = psql(`select position, unit_price::text as p, coalesce(deleted,0) as deleted
      from production_operation_positions where tenant_id=${T} and logical_name='${catalogRow.name}' order by position, id`)
    // 与上一轮 F8 **同一动作**：一次普通设置保存（body 只带 scope），HTTP 200
    const put = await api('PUT', `/api/admin/production/operations/${catalogRow.id}`, { token, body: { scope: catalogRow.scope ?? 'position' } })
    f8.putHttp = put.status
    f8.putBody = put.text.slice(0, 400)
    f8.afterPositionRows = psql(`select position, unit_price::text as p, coalesce(deleted,0) as deleted
      from production_operation_positions where tenant_id=${T} and logical_name='${catalogRow.name}' order by position, id`)
    f8.afterLibPrice = psql(`select unit_price::text as p from production_operations where id='${catalogRow.id}'`)[0]?.p
    // F8 的**工资侧后果**探查：① 实例价是否被顶掉 ② 新报工快照价 ③ 读面工资
    const rF8 = await report(A, instId(opUnpriced), { worker_name: WORKER_A, qty: 2, qualified_qty: 2, work_type: 'normal' }, `${RUN}-F8`)
    f8.reportHttp = rF8.status
    f8.newLogs = logRows([A.poId]).filter((r) => r.operation_name === opUnpriced)
    const pwF8 = await api('GET', `/api/admin/production/orders/${A.orderId}/piecework`, { token })
    f8.pieceworkTotal = pwF8.json?.data?.total
    f8.unpricedBlock = pwF8.json?.data?.unpriced
    f8.perOperation = pwF8.json?.data?.per_operation
    const expF8 = expectedCents(logRows([A.poId]))
    f8.expectedTotal = fmt(expF8.total)
    f8.faceMatchesOwnMath = predTotalEqualsOwnMath(pwF8.json?.data?.total, expF8.total)
    // 🔴 判据 M16：一次与价格无关的设置保存之后，工资侧「读面 == 独立算式」必须仍成立。
    R[f8.faceMatchesOwnMath ? 'pass' : 'fail']('M16-01',
      '【F8 正对照】一次普通工序设置保存后，工资读面仍须与独立算式逐分一致',
      `保存后读面 ${pwF8.json?.data?.total} vs 独立算式 ${fmt(expF8.total)}；unpriced.qty=${pwF8.json?.data?.unpriced?.qty}`,
      [`PUT /api/admin/production/operations/${catalogRow.id} {scope}`,
       `GET /orders/{A.orderId}/piecework`, `独立算式（报工快照）`])
    // 判据 M16-02：未定价工序**不得**因保存而静默变成 0 元工资
    const unpricedAfter = (pwF8.json?.data?.unpriced?.operations ?? []).map((o) => o.operation)
    const zeroInDetail = (pwF8.json?.data?.per_operation ?? []).filter((r) => r.operation === opUnpriced && cents(r.amount) === 0n)
    R[zeroInDetail.length === 0 ? 'pass' : 'fail']('M16-02',
      '【F8 正对照】保存后未定价工序不得静默变 0 元工资',
      `unpriced 清单=${JSON.stringify(unpricedAfter)}；per_operation 里 ${opUnpriced} 的 0 元行=${JSON.stringify(zeroInDetail)}`,
      [`GET /orders/{A.orderId}/piecework → .unpriced / .per_operation`])
  } else {
    R.skip('M16-01', '【F8 正对照】', `工序库读面找不到逻辑工序「${unpricedLogical}」⇒ 无法执行该注入（登记为未覆盖）`)
    R.skip('M16-02', '【F8 正对照】', '同上')
  }
  ctx.f8 = f8

  // ══════════ 收尾读数 ══════════
  const poIds = ctx.probes.map((p) => p.poId)
  const logsFinal = logRows(poIds)
  const expFinal = expectedCents(logsFinal)
  ctx.final = {
    probes: ctx.probes,
    workLogs: logsFinal,
    independentExpectedTotal: fmt(expFinal.total),
    instanceRowsA: instRows(A.poId),
    instanceRowsB: instRows(B.poId),
  }
  ctx.interferenceProbe = {
    // 我在两次读之间观测到的「非自建行值变化」检查点（由 p9 用同一基线复核）
    operations: psql(`select id, name, unit_price::text as unit_price, scope, status
      from production_operations where tenant_id=${T} and coalesce(deleted,0)=0 order by name`),
    positionPrices: psql(`select id, logical_name, position, unit_price::text as unit_price
      from production_operation_positions where tenant_id=${T} and coalesce(deleted,0)=0 order by logical_name, position, id`),
  }
  save()
  writeFileSync(join(OUT, 'p1p2-raw.json'), JSON.stringify({
    perOrder: pwData, summary: sumData, worklogTotals: wl.json?.data?.totals ?? null, logsFinal,
  }, null, 2))
  log(`probes=${ctx.probes.map((p) => p.tag + ':' + p.poNo).join(' ')}`)
  log(`summary=${JSON.stringify(R.summary())}`)
}

main().catch((e) => { console.error(e); process.exit(1) })
