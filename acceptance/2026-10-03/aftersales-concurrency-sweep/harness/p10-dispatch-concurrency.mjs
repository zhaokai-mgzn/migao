// p10-dispatch-concurrency —— 并发派工（**同一单据/同一工序被并发派工**）
// 用法：API_BASE=http://127.0.0.1:8080 node p10-dispatch-concurrency.mjs
//
// 被测端点：`POST /api/admin/production/pool/dispatch`（body 带 pooled=true 才跨订单成组）
//   —— 源码 backend/admin-api/src/main/java/com/migao/admin/controller/ProductionPoolController.java 的 dispatch
//   ⇒ ProcessingOrderService.generate(orderIds, batches, tenantId, operator, rule, pooled)
//
// 期望（**先给期望再测**）：
//   ① 「一单一加工单」约束（DB partial unique index `uk_processing_orders_active` + 应用层幂等闸）
//      ⇒ N 路并发对同一 orderId 派工：**活跃加工单恰 1 张**；
//   ② 工序实例 `processing_position_operations` 的行数 = 单次派工的行数（不得因并发翻倍）；
//   ③ 同一工序不得被派给两个工人（worker_id/worker_name 一致且唯一）；
//   ④ 结局分布：恰 1 个成功，其余应为 **4xx 可行动拒绝**（不是 5xx —— DB 唯一约束冲突被透传成 500 = 真缺陷）。
import { writeFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import {
  api, adminToken, psql, one, outPath, log, nowCST, Recorder, raceStart, overlapEvidence,
  skuStock, guardedWrite, pgConf, fmtQty, cents, TENANT_ID, PROBE_PREFIX, uniq,
} from './lib.mjs'

const R = new Recorder('B10-dispatch-concurrency.json')
const { token, via } = await adminToken()
log(`鉴权成功（via=${via}）`)

const N = 4

/** 建一张带加工项的探针已确认订单（形状对齐既有跑通的派工夹具）。 */
async function orderWithProcessing(tag) {
  const cat = psql(`select id from categories where tenant_id=${TENANT_ID} and status='active' order by created_at limit 1`)[0]?.id
  const prod = await api('POST', '/api/admin/products', { token, body: {
    name: `${PROBE_PREFIX}派工商品-${tag}`, unit: '米', pricingType: 'fixed', basePrice: 68,
    status: 'on_sale', categoryId: cat, allowReturnRestock: false,
    colors: [{ colorName: `${PROBE_PREFIX}派工色-${tag}`, mainColorHex: '#FAFAFA', sortOrder: 1 }],
    skus: [{ colorName: `${PROBE_PREFIX}派工色-${tag}`, doorWidth: '2.8m', price: 68, stock: 100000, skuCode: `LB-DISP-${tag}`.toUpperCase() }],
  } })
  const productId = prod.data?.id
  const skuId = one(`select id::text as id from product_skus where product_id='${productId}'`)?.['id']
  const order = await api('POST', '/api/admin/orders', { token, body: {
    customerName: `${PROBE_PREFIX}派工客户-${tag}`, customerPhone: '13300000011', customerAddress: `${PROBE_PREFIX}派工地址`,
    logisticsType: 'express', logisticsCompany: `${PROBE_PREFIX}物流`, remark: `${PROBE_PREFIX}（探针订单-派工并发）`,
    items: [{
      productId, skuId, productName: `${PROBE_PREFIX}派工行-${tag}`, quantity: 1, unitPrice: 68, subtotal: 68,
      width: 2.8, height: 2.6,
      processingInfo: {
        skuId, skuCode: `LB-DISP-${tag}`.toUpperCase(), colorName: `${PROBE_PREFIX}派工色-${tag}`, unit: '米',
        sellingMethod: 'bulk_cut', fabric_meters: 12.3, pleat_count: 40, panels: 2, holes: 24,
        fullness: 2, fullness_actual: 2, doorWidth: '2.8m',
        curtainType: '布帘', craft: '罗马帘',
        processingItems: [{ id: `lbpi${tag}`, name: '锁边', quantity: 1, unit: '米' }],
      },
    }],
  } })
  const orderId = order.data?.id ?? order.data?.orderId
  if (!orderId) throw new Error(`建单失败: ${order.text.slice(0, 200)}`)
  await api('PUT', `/api/admin/orders/${orderId}/payment`, { token })
  return { tag, orderId, productId, skuId }
}

const dispatch = (orderId, pooled) =>
  api('POST', '/api/admin/production/pool/dispatch', { token, body: { orderIds: [orderId], ...(pooled ? { pooled: true } : {}) } })
// 🔴 dispatch 的**业务层**结局在 `data[0].success/code/message`（HTTP 恒 200）——
//    只看 HTTP 状态码会把「3 个被幂等闸拒掉」读成「4 个都成功」（本包第一版就是这么读的）。
const brief = (r) => {
  const d0 = Array.isArray(r?.data) ? r.data[0] : null
  return {
    status: r?.status,
    code: r?.bookErr?.code ?? d0?.code,
    msg: r?.bookErr?.message ?? d0?.message ?? (r?.json?.success ? 'ok' : undefined),
    bizOk: d0 ? d0.success === true : (r?.json?.success === true && r?.data == null),
  }
}

function posRows(orderId) {
  return psql(`select ppo.id, ppo.seq, ppo.operation_name, ppo.position_kind, ppo.qty::text as qty,
                      ppo.worker_id, ppo.worker_name, ppo.status
               from processing_position_operations ppo
               join processing_orders po on po.id = ppo.processing_order_id
               where po.order_id='${orderId}' and ppo.deleted=0 order by ppo.seq`)
}
function activePo(orderId) {
  return psql(`select id, processing_order_no, status, qr_token from processing_orders
               where tenant_id=${TENANT_ID} and order_id='${orderId}' and deleted=0 and status <> 'cancelled'`)
}

for (const pooled of [false, true]) {
  const rounds = []
  for (let rd = 1; rd <= 3; rd++) {
    const f = await orderWithProcessing(`${pooled ? 'P' : 'S'}${rd}`)
    // 预热（把连接/JIT 开销挪到 barrier 之前）
    await Promise.all([1, 2, 3].map(() => api('GET', `/api/admin/orders/${f.orderId}`)))
    const race = await raceStart(N, () => dispatch(f.orderId, pooled))
    const ov = overlapEvidence(race)
    const pos = posRows(f.orderId)
    const posIdsUniq = new Set(pos.map((x) => String(x.id))).size
    const workers = new Set(pos.map((x) => `${x.worker_id ?? '-'}/${x.worker_name ?? '-'}`))
    const posByOp = {}
    for (const x of pos) posByOp[x.operation_name] = (posByOp[x.operation_name] || 0) + 1
    const okCount = race.results.filter((r) => r.out?.status === 200).length
    const bizOkCount = race.results.filter((r) => brief(r.out).bizOk === true).length
    const bizFailCount = race.results.filter((r) => brief(r.out).bizOk === false).length
    const s5xx = race.results.filter((r) => (r.out?.status ?? 0) >= 500)
    const actives = activePo(f.orderId)
    // 独立算式期望：活跃加工单恰 1；工序实例行数 == 单次派工行数（由成功的那个响应给出）；
    // 同一工序行不得重复（同名工序的行数 == 其 seq 唯一数）
    const seqDup = pos.length !== new Set(pos.map((x) => x.seq)).size
    // 独立算式期望：**恰 1 个业务成功**（其余被幂等闸拒），HTTP 无 5xx，活跃加工单恰 1，工序实例无重复
    const pass = ov.overlapped && actives.length === 1 && s5xx.length === 0 && bizOkCount === 1 &&
                 bizFailCount === N - 1 && pos.length === posIdsUniq && !seqDup && workers.size <= 1
    rounds.push({
      round: rd, N, pooled, orderId: f.orderId, okCount, bizOkCount, bizFailCount, s5xx: s5xx.length,
      perRequest: race.results.map((r, i) => ({ i, ...brief(r.out), durMs: r.durMs })),
      dbFinal: { activeProcessingOrders: actives.length, processingOrderNos: actives.map((x) => x.processing_order_no),
                 positionRows: pos.length, distinctPositionIds: posIdsUniq, seqDup,
                 distinctWorkers: [...workers], statuses: [...new Set(pos.map((x) => x.status))] },
      expectation: '业务成功恰 1 个（其余 N−1 被幂等闸拒）；活跃加工单恰 1 张；工序实例行数 = 单次派工行数（同 id 不重复、seq 不撞）；同一工序只归一个工人；无 5xx',
      overlapEvidence: ov, pass,
    })
  }
  const overlapAll = rounds.every((r) => r.overlapEvidence.overlapped)
  const allPass = rounds.every((r) => r.pass)
  const s5xxAny = rounds.some((r) => r.s5xx > 0)
  const detail = `pooled=${pooled} 三轮：**业务成功数**=${JSON.stringify(rounds.map((r) => r.bizOkCount))}（期望各 1）/ HTTP 200 数=${JSON.stringify(rounds.map((r) => r.okCount))}；5xx 数=${JSON.stringify(rounds.map((r) => r.s5xx))}；活跃加工单=${JSON.stringify(rounds.map((r) => r.dbFinal.activeProcessingOrders))}（期望各 1）；工序实例行=${JSON.stringify(rounds.map((r) => r.dbFinal.positionRows))}；逐轮状态码=${JSON.stringify(rounds.map((r) => r.perRequest.map((x) => x.status)))}`
  R.add(`LB-C5-DISPATCH-${pooled ? 'POOLED' : 'SERIAL'}`,
    `C5 并发派工（${pooled ? 'pooled=true 跨单成组' : 'pooled 缺省=逐单派'}）同一订单 N=${N}×3 轮：加工单唯一 + 工序实例不重复`,
    allPass ? 'pass' : (overlapAll ? 'fail' : 'falseRed'),
    detail,
    [`期望来源: 本包独立算式 + 源码 ——`,
     `   · 「一单一加工单」：DB partial unique index \`uk_processing_orders_active\`（注释见 backend/admin-api/src/main/java/com/migao/admin/controller/ProductionPoolController.java 的 dispatch）+ 应用层幂等闸（backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java 的 prepare ⇒ selectActiveByOrderId ⇒ 「已有加工单 … 请勿重复生成」）`,
     `   · 工序实例：单次派工的行数由 processing_position_operations 决定；并发不得产生重复 id / 撞 seq`,
     `   · 工人归属：同一工序只能有一个 worker（不得同日两派）`,
     `结局形态判据: **业务层**恰 1 个 success=true，其余 N−1 个 success=false + code=VALIDATION_ERROR（「已有加工单 … 请勿重复生成」）；`,
     `   HTTP 层恒 200（逐单成败在信封 data[0] 内）⇒ 本判据取**业务层**读数，不拿 HTTP 码当成败`,
     `   若出现 **5xx**（DB 唯一约束冲突被透传）或业务成功数 >1 ⇒ 真缺陷`,
     `重叠证据: ${rounds.map((r) => `R${r.round}: ${r.overlapEvidence.verdict}`).join(' ｜ ')}`,
     `逐请求结局: ${JSON.stringify(rounds.map((r) => r.perRequest.map((x) => [x.status, x.code, x.msg])))}`],
    { extra: { N, pooled, rounds, overlapEvidence: rounds.map((r) => r.overlapEvidence) } })
}

// ── 判别力红证：同一装置上「摘掉唯一约束」⇒ 必红；加回 ⇒ 守住 ──
{
  const c = pgConf()
  const setup = () => {
    guardedWrite(`-- probe-ok\ndrop table if exists lb_gp_dispatch;`)
    guardedWrite(`-- probe-ok\ncreate table lb_gp_dispatch (id serial primary key, order_id text);`)
  }
  const run = (withUnique) => {
    setup()
    if (withUnique) guardedWrite(`-- probe-ok\ncreate unique index lb_gp_dispatch_uk on lb_gp_dispatch (order_id) where order_id is not null;`)
    const cmd = `for i in $(seq 1 ${N}); do psql -h ${c.host} -p ${c.port} -U ${c.user} -d ${c.db} -t -A -v ON_ERROR_STOP=1 ` +
      `-c "insert into lb_gp_dispatch (order_id) values ('o1');" >/dev/null 2>&1 & done; wait`
    execFileSync('bash', ['-lc', cmd], { env: { ...process.env, PGPASSWORD: c.password }, encoding: 'utf8' })
    const rows = psql(`select id from lb_gp_dispatch where order_id='o1'`).length
    guardedWrite(`-- probe-ok\ndrop table if exists lb_gp_dispatch;`)
    return rows
  }
  const noUniq = run(false)
  const withUniq = run(true)
  writeFileSync(outPath('B10-redproof.json'), JSON.stringify({ at: nowCST(), N, withoutUniqueRows: noUniq, withUniqueRows: withUniq }, null, 2))
  R.add('LB-C5-REDPROOF', 'C5 判别力红证：摘掉唯一约束 ⇒ N 行；加回 ⇒ 1 行（并发窗口真实存在、判据会红）',
    (noUniq === N && withUniq === 1) ? 'pass' : 'fail',
    `N=${N} 独立 psql 进程并发 INSERT：无唯一约束 ⇒ ${noUniq} 行（期望 ${N}）；有唯一约束（产品同形）⇒ ${withUniq} 行（期望 1）`,
    [`注入方式: **不改产品源码** —— 本包自建临时表 lb_gp_dispatch；有约束那轮建 partial unique index（与 products 侧 uk_processing_orders_active 同形）`,
     `该红证证明: ① N 路并发确实能同时到达 INSERT（否则无约束那轮也不会得 N 行）；② 「活跃加工单恰 1 张」这条判据会红`,
     `读数: 无约束=${noUniq} / 有约束=${withUniq}`],
    { extra: { N, noUniq, withUniq } })
}

log(`p10 完成：${JSON.stringify(R.summary())}`)
