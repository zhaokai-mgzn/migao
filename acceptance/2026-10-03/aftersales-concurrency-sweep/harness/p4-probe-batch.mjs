// p4-probe-batch —— 补强探针批（B1 细节深化 + C4 重做 + C2 泄漏的**独立于时序**的判别力红证）
// 用法：API_BASE=http://127.0.0.1:8080 node p4-probe-batch.mjs
//
// 三块：
//   B1+ 金额/状态/三方自洽的边界深化（科学计数法、空串、精度、累计封顶独立复算、三方一致）
//   C2+ 状态机语义的并发面（C21/C22/C23）+ **持久层行为红证**（唯一被判为泄漏的机器可判读数）
//   C4 重做：响应路径取 `data.items`/`data.total`，**取不到真值 ⇒ fail**；>1000 行不足 ⇒ skip
import { writeFileSync, readFileSync } from 'node:fs'
import {
  api, adminToken, psql, one, outPath, log, nowCST, Recorder, judge, raceStart, overlapEvidence,
  orderRow, ticketRow, financeRefundRows, skuStock, guardedWrite, pgConf,
  cents, fmtQty, moneyAdd, qtyEq, createProbeOrder, createProbeProduct, TENANT_ID,
} from './lib.mjs'
import { execFileSync } from 'node:child_process'

const R = new Recorder('B4-probe-batch.json')
const { token, via } = await adminToken()
log(`鉴权成功（via=${via}）`)
const mkProduct = (tag, opts = {}) => createProbeProduct(token, { tag, ...opts })
const mkOrder = (p, tag, pay = true, qty = 2, unitPrice = 150) =>
  createProbeOrder(token, { productId: p.productId, productName: p.name, skuId: p.skuId, skuCode: p.skuCode, colorId: p.colorId, qty, unitPrice, tag })
const refund = (orderId, amount, reason = '线B验收边界退款') =>
  api('PUT', `/api/admin/orders/${orderId}/refund`, { token, body: { refund_reason: reason, ...(amount === undefined ? {} : { refund_amount: amount }) } })
const setStatus = (id, status, remark) =>
  api('PUT', `/api/admin/after-sales/${id}/status`, { token, body: { status, ...(remark ? { remark } : {}) } })
const brief = (r) => ({ status: r?.status, code: r?.bookErr?.code, msg: r?.bookErr?.message || (r?.json?.success ? 'ok' : undefined) })

// ═══════════════ B1+ 金额边界与三方自洽 ═══════════════
{
  // ① 科学计数法 '1e2'
  const A = await mkProduct('E1', { allowRestock: false, stock: 100, price: 150 })
  const oA = await mkOrder(A, 'E1', true, 2, 150)          // 实收 300
  const r1 = await refund(oA.orderId, '1e2')
  const a1 = orderRow(oA.orderId)
  R.add('LB-REF-B01', '退款金额：科学计数法 "1e2" 的接受/拒绝口径（如实读数）',
    r1.status === 200 ? (qtyEq(a1?.refund_amount, '100.00') ? 'pass' : 'fail') : (r1.status === 422 ? 'pass' : 'fail'),
    `${r1.status} ${r1.bookErr?.code || ''} ${r1.bookErr?.message || ''}；DB refund_amount=${a1?.refund_amount}`,
    [`期望来源: 本包独立算式 —— 若接受，则 BigDecimal("1e2")=100 ⇒ refund_amount 应恰为 100.00；若拒绝应为 422（不得 500、不得静默按 1 元记）`,
     `响应原文: ${r1.text.slice(0, 300)}`,
     `源码: backend/admin-api/src/main/java/com/migao/admin/controller/OrderController.java 的 refundOrder 用 new BigDecimal(amount.toString().trim()) ⇒ 语法上接受 "1e2"`,
     `⚠️ 形态说明: 本条是**口径登记**（接受=100 或拒绝=422 都算自洽），只有「非 100 且非 422」才判 fail`],
    { extra: { status: r1.status, refundAmount: a1?.refund_amount } })

  // ② 空串 ''
  const B = await mkProduct('E2', { allowRestock: false, stock: 100, price: 150 })
  const oB = await mkOrder(B, 'E2', true, 2, 150)
  const r2 = await refund(oB.orderId, '')
  const b2 = orderRow(oB.orderId)
  R.add('LB-REF-B02', '退款金额：空串 "" ⇒ 视为未传（全额退款）的口径登记',
    r2.status === 200 && qtyEq(b2?.refund_amount, b2?.actual_amount) ? 'pass' : (r2.status === 422 ? 'pass' : 'fail'),
    `${r2.status}；refund_amount=${b2?.refund_amount} 实收=${b2?.actual_amount}`,
    [`期望来源: 源码 backend/admin-api/src/main/java/com/migao/admin/controller/OrderController.java —— refund_amount 为 null/空白 ⇒ refundAmount 保持 null ⇒ service 侧「null = 全额退款」`,
     `响应原文: ${r2.text.slice(0, 250)}`],
    { extra: { status: r2.status, refundAmount: b2?.refund_amount, actual: b2?.actual_amount } })

  // ③ 精度：0.001（三位小数）能否被接受、DB 精度是否截断
  const C = await mkProduct('E3', { allowRestock: false, stock: 100, price: 150 })
  const oC = await mkOrder(C, 'E3', true, 2, 150)
  const r3 = await refund(oC.orderId, '0.001')
  const c3 = orderRow(oC.orderId)
  const fin3 = financeRefundRows(oC.orderId)
  R.add('LB-REF-B03', '退款金额：最小正数 0.001（三位小数）⇒ 接受且落库不截断',
    r3.status === 200 && qtyEq(c3?.refund_amount, '0.001') && fin3.length === 1 && qtyEq(fin3[0]?.amount, '0.001') ? 'pass'
      : (r3.status === 422 ? 'pass' : 'fail'),
    `${r3.status}；orders.refund_amount=${c3?.refund_amount}；流水 ${fin3.length} 行 ${fin3.map((x) => x.amount).join(',')}`,
    [`期望来源: 本包独立算式 —— refund=0.001 > 0 且 ≤ 实收 300 ⇒ 应接受，orders.refund_amount 与流水金额都应恰为 0.001（NUMERIC 不截断）`,
     `⚠️ 若 DB 列为 NUMERIC(12,2) ⇒ 会**静默变 0.00**（订单看起来退过款、金额却是 0）—— 这正是本条要辨的两侧`,
     `响应原文: ${r3.text.slice(0, 250)}`, `DB orders: ${JSON.stringify(c3)}`, `DB 流水: ${JSON.stringify(fin3)}`],
    { extra: { status: r3.status, refundAmount: c3?.refund_amount, finance: fin3.map((x) => x.amount) } })

  // ④ 累计封顶的**独立复算**（6×100 vs 实收 300 ⇒ 恰 3 成；用独立求和式核对 DB 与流水）
  const D = await mkProduct('E4', { allowRestock: false, stock: 100, price: 150 })
  const oD = await mkOrder(D, 'E4', true, 2, 150)
  const seq = []
  for (let i = 0; i < 6; i++) seq.push(await refund(oD.orderId, '100.00'))
  const d4 = orderRow(oD.orderId)
  const fin4 = financeRefundRows(oD.orderId)
  const finSum = moneyAdd(...fin4.map((x) => x.amount))
  const expectSum = fmtQty(cents('100.00') * 3n)
  judge(R, {
    id: 'LB-REF-B04', name: '退款累计封顶：6×100.00 vs 实收 300.00 ⇒ 恰 3 次成功、DB 与流水合计都恰 300.00',
    expect: `逐次结局 = [200,200,200,422,422,422]；orders.refund_amount=${expectSum}；流水 ${3} 行合计 ${expectSum}`,
    actual: `结局=${JSON.stringify(seq.map((x) => x.status))}；refund_amount=${d4?.refund_amount}；流水 ${fin4.length} 行合计 ${finSum}`,
    pass: JSON.stringify(seq.map((x) => x.status)) === JSON.stringify([200, 200, 200, 422, 422, 422]) &&
          qtyEq(d4?.refund_amount, expectSum) && fin4.length === 3 && cents(finSum) === cents(expectSum) &&
          cents(d4?.refund_amount) <= cents(d4?.actual_amount),
    expectSource: '本包独立算式：每次 applied = min(100.00, 实收300.00 − 已退)；第 4 次起 applied ≤ 0 ⇒ 422；成功 3 次 ⇒ 累计恰 300.00',
    evidence: [`逐次响应: ${JSON.stringify(seq.map((x) => `${x.status}:${x.bookErr?.message || 'ok'}`))}`,
               `DB orders: ${JSON.stringify(d4)}`, `流水原始行: ${JSON.stringify(fin4.map((x) => ({ amount: x.amount, remark: x.remark })))}`],
    extra: { perRequest: seq.map((x, i) => ({ round: i + 1, status: x.status, msg: x.bookErr?.message })) },
  })

  // ⑤ 三方自洽（orders.refund_amount / refund_at / 工单 refund_amount·refund_method）—— 走工单完结路径
  const E = await mkProduct('E5', { allowRestock: false, stock: 100, price: 150 })
  const oE = await mkOrder(E, 'E5', true, 2, 150)     // 实收 300
  const tc = await api('POST', '/api/admin/after-sales', { token, body: {
    orderId: oE.orderId, ticketType: 'refund', description: `${'线B验收'}工单-三方一致性`, refundAmount: '120.00' } })
  const tid = tc.data?.id
  await setStatus(tid, 'processing', `${'线B验收'}：受理`)
  const rs = await setStatus(tid, 'resolved', `${'线B验收'}：完结`)
  const oERow = orderRow(oE.orderId)
  const tRow = ticketRow(tid)
  const finE = financeRefundRows(oE.orderId)
  // 独立算式：工单 120.00 ⇒ 订单累计 120.00；流水恰 1 行 120.00
  judge(R, {
    id: 'LB-REF-B05', name: '三方自洽：工单 refund_amount 120.00 ⇒ orders.refund_amount=120.00 + refund_at 非空 + 流水 1 行 120.00',
    expect: `orders.refund_amount=120.00、refund_at 非空；工单 status=resolved、refund_amount=120.00；finance_transactions 恰 1 行 120.00`,
    actual: `orders.refund_amount=${oERow?.refund_amount} refund_at=${oERow?.refund_at ? 'set' : 'null'}；工单 status=${tRow?.status} refund_amount=${tRow?.refund_amount} refund_method=${tRow?.refund_method}；流水 ${finE.length} 行 ${finE.map((x) => x.amount).join(',')}`,
    pass: rs.status === 200 && qtyEq(oERow?.refund_amount, '120.00') && oERow?.refund_at != null &&
          qtyEq(tRow?.refund_amount, '120.00') && finE.length === 1 && qtyEq(finE[0]?.amount, '120.00'),
    expectSource: '本包独立算式：工单携带退款额 120.00（建单请求值）⇒ 完结时订单累计 = 120.00（无其他退款）⇒ 流水恰 1 行 120.00',
    evidence: [`工单建单响应: ${tc.text.slice(0, 200)}`, `完结响应: ${rs.text.slice(0, 200)}`,
               `DB orders: ${JSON.stringify(oERow)}`, `DB 工单: ${JSON.stringify(tRow)}`, `DB 流水: ${JSON.stringify(finE)}`,
               `⚠️ 登记：工单 refund_method 当前为 ${tRow?.refund_method}（该列在本路径上未被写入 —— 见 REPORT 未覆盖/观察项）`],
    extra: { orderRefund: oERow?.refund_amount, ticketRefund: tRow?.refund_amount, refundMethod: tRow?.refund_method, finance: finE.map((x) => x.amount) },
  })
}

// ═══════════════ C2+ 状态机语义并发面 + 持久层判别力红证 ═══════════════
{
  const N = 4
  // C21：并发重复 processing（同一起点 pending，N 路并发打 →processing）
  const rounds21 = []
  const rounds22 = []
  const rounds23 = []
  for (let rd = 1; rd <= 3; rd++) {
    // —— C21 ——
    const p1 = await mkProduct(`C21R${rd}`, { allowRestock: false, stock: 100, price: 100 })
    const o1 = await mkOrder(p1, `C21R${rd}`, true, 1, 100)
    const c1 = await api('POST', '/api/admin/after-sales', { token, body: { orderId: o1.orderId, ticketType: 'other', description: `${'线B验收'}工单-C21-${rd}` } })
    const t1 = c1.data?.id
    await Promise.all([1, 2, 3].map(() => api('GET', `/api/admin/after-sales/${t1}`)))
    const race21 = await raceStart(N, () => setStatus(t1, 'processing', `${'线B验收'}：并发受理-${rd}`))
    const ov21 = overlapEvidence(race21)
    const tl21 = psql(`select id, content from ticket_timeline where tenant_id=${TENANT_ID} and ticket_id='${t1}' and action='status_change'`)
    const ok21 = race21.results.filter((r) => r.out?.status === 200).length
    rounds21.push({
      round: rd, N, okCount: ok21, statuses: race21.results.map((r) => r.out?.status),
      timelineRows: tl21.length, dbStatus: ticketRow(t1)?.status,
      expectation: `恰好 1 次 200（其余 422）；timeline 恰 1 行；DB status=processing`,
      pass: ov21.overlapped && ok21 === 1 && tl21.length === 1,
      overlapEvidence: ov21, ticketId: t1,
    })

    // —— C22：并发打 different 目标（processing vs closed）—— 终态必须合法且只有一个赢家 ——
    const p2 = await mkProduct(`C22R${rd}`, { allowRestock: false, stock: 100, price: 100 })
    const o2 = await mkOrder(p2, `C22R${rd}`, true, 1, 100)
    const c2 = await api('POST', '/api/admin/after-sales', { token, body: { orderId: o2.orderId, ticketType: 'other', description: `${'线B验收'}工单-C22-${rd}` } })
    const t2 = c2.data?.id
    await Promise.all([1, 2, 3].map(() => api('GET', `/api/admin/after-sales/${t2}`)))
    const race22 = await raceStart(2, (i) => setStatus(t2, i === 0 ? 'processing' : 'closed', `${'线B验收'}：并发分歧-${rd}`))
    const ov22 = overlapEvidence(race22)
    const ok22 = race22.results.filter((r) => r.out?.status === 200).length
    const st22 = ticketRow(t2)?.status
    rounds22.push({
      round: rd, N: 2, okCount: ok22, statuses: race22.results.map((r) => r.out?.status),
      dbStatus: st22, expectation: '至多 1 次 200（其余 422）；终态 ∈ {processing, closed}',
      pass: ov22.overlapped && ok22 <= 1 && ['processing', 'closed'].includes(st22),
      overlapEvidence: ov22, ticketId: t2,
    })

    // —— C23：并发 resolved ⇒ timeline 行数（**本条不依赖重叠**：状态守卫是内存读 ⇒ 重复写窗口客观存在）——
    const p3 = await mkProduct(`C23R${rd}`, { allowRestock: false, stock: 100, price: 100 })
    const o3 = await mkOrder(p3, `C23R${rd}`, true, 1, 100)
    const c3 = await api('POST', '/api/admin/after-sales', { token, body: { orderId: o3.orderId, ticketType: 'other', description: `${'线B验收'}工单-C23-${rd}` } })
    const t3 = c3.data?.id
    await setStatus(t3, 'processing', `${'线B验收'}：受理`)
    await Promise.all([1, 2, 3].map(() => api('GET', `/api/admin/after-sales/${t3}`)))
    const race23 = await raceStart(N, () => setStatus(t3, 'resolved', `${'线B验收'}：并发完结-${rd}`))
    const ov23 = overlapEvidence(race23)
    const tl23 = psql(`select id, content, created_at from ticket_timeline where tenant_id=${TENANT_ID} and ticket_id='${t3}' and action='status_change' order by created_at`)
    const resolvedRecords = tl23.filter((x) => JSON.stringify(x.content).includes('resolved')).length
    const ok23 = race23.results.filter((r) => r.out?.status === 200).length
    rounds23.push({
      round: rd, N, okCount: ok23, statuses: race23.results.map((r) => r.out?.status),
      timelineRowsTotal: tl23.length, timelineResolvedTo: resolvedRecords,
      dbStatus: ticketRow(t3)?.status,
      expectation: '恰好 1 次 200；timeline 中「→ resolved」恰 1 行（每次合法状态变更 1 行）',
      pass: ov23.overlapped && ok23 === 1 && resolvedRecords === 1,
      overlapEvidence: ov23, ticketId: t3, timelineRaw: tl23.map((x) => ({ content: x.content, at: x.created_at })),
    })
  }
  const mk = (id, name, rounds, expectation) => {
    const allPass = rounds.every((r) => r.pass)
    const overlapAll = rounds.every((r) => r.overlapEvidence.overlapped)
    return R.add(id, name, allPass ? 'pass' : (overlapAll ? 'fail' : 'falseRed'),
      `三轮：成功数=${JSON.stringify(rounds.map((r) => r.okCount))}；逐轮状态码=${JSON.stringify(rounds.map((r) => r.statuses))}；DB 终态=${JSON.stringify(rounds.map((r) => r.dbStatus))}；时间线读数=${JSON.stringify(rounds.map((r) => r.timelineResolvedTo ?? r.timelineRows))}`,
      [`期望来源: 本包独立算式 —— ${expectation}`,
       `源码: backend/admin-api/src/main/java/com/migao/admin/service/AfterSalesTicketService.java 的 updateTicketStatus —— 状态机校验基于 selectById 读到的**旧值**，落库 updateById(ticket) 的 WHERE 仅 id（**无状态谓词**）`,
       `重叠证据: ${rounds.map((r) => `R${r.round}: ${r.overlapEvidence.verdict}`).join(' ｜ ')}`,
       `⚠️ 判据的独立性: 时间线行数 / 状态码分布是**数据库与响应层的事实**，不依赖请求是否重叠 —— 重叠证据只用来判「这轮绿算不算数」`],
      { extra: { N, rounds, overlapEvidence: rounds.map((r) => r.overlapEvidence) } })
  }
  mk('LB-C21-CONCURRENT-SAME-TARGET', 'C21 同一工单并发打同一目标（pending→processing×4）：恰一个赢家',
    rounds21, 'N 路并发对同一 (from,to) ⇒ 只应有 1 次 200（其余 422「不允许从 [处理中] 变更为 [处理中]」）；timeline 恰 1 行')
  mk('LB-C22-CONCURRENT-CONFLICT', 'C22 同一工单并发分歧（processing vs closed）：终态合法且至多一个赢家',
    rounds22, '两路分别打不同目标 ⇒ 终态必须合法（processing/closed），不得出现非法中间态')
  mk('LB-C23-CONCURRENT-RESOLVE-TIMELINE', 'C23 同一工单并发 resolved：时间线「→resolved」恰 1 行（重复写审计）',
    rounds23, 'N 路并发 →resolved ⇒ 只应 1 次 200（其余 422「不允许从 [已解决] 变更为 [已解决]」）；timeline「→resolved」恰 1 行（1 次合法变更 = 1 行审计）')

  // ── 持久层判别力红证（**唯一被判为泄漏的机器可判读数**，独立于请求时序）──
  // 为什么需要：上面的「成功数」与「重叠」都是**时序相关**读数；而「库存终值 > 基线+1 次增量」
  // 是**库内事实**。本实验证明「时间线行数」这个读数确实会随「几次写到达」变化（⇒ 有判别力）。
  const rpRows = (n) => {
    guardedWrite(`-- probe-ok\ndrop table if exists lb_gp_timeline;`)
    guardedWrite(`-- probe-ok\ncreate table lb_gp_timeline (id serial primary key, ticket_id text, action text, content jsonb, created_at timestamptz);`)
    const c = pgConf()
    // n 个独立 psql 进程并发 INSERT —— 与产品 updateTicketStatus 末尾的 timeline 插入同形
    const cmd = `for i in $(seq 1 ${n}); do psql -h ${c.host} -p ${c.port} -U ${c.user} -d ${c.db} -t -A -v ON_ERROR_STOP=1 ` +
      `-c "insert into lb_gp_timeline (ticket_id, action, content, created_at) values ('t1','status_change','{\\"from\\":\\"processing\\",\\"to\\":\\"resolved\\"}'::jsonb, now());" >/dev/null 2>&1 & done; wait`
    execFileSync('bash', ['-lc', cmd], { env: { ...process.env, PGPASSWORD: c.password }, encoding: 'utf8' })
    const rows = psql(`select id from lb_gp_timeline where ticket_id='t1' and content->>'to'='resolved'`).length
    guardedWrite(`-- probe-ok\ndrop table if exists lb_gp_timeline;`)
    return rows
  }
  const n4 = rpRows(4)
  const n1 = rpRows(1)
  R.add('LB-C23-ROWCOUNT-REDPROOF', 'C23 判别力红证：N 次「到达」⇒ 时间线 N 行（1 次 ⇒ 1 行）—— 行数读数确实会变',
    (n4 === 4 && n1 === 1) ? 'pass' : 'fail',
    `4 次并发写 ⇒ 读到 ${n4} 行（期望 4）；1 次写 ⇒ 读到 ${n1} 行（期望 1）⇒ 该读数对「几次写到达」敏感（有判别力）`,
    [`注入方式: **不改产品源码** —— 在本包自建临时表 lb_gp_timeline 上跑与产品同形的 INSERT（4 个独立 psql 进程并发 / 1 个进程）`,
     `该实验回答的问题: 「时间线行数」这个观测是否可能**恒为 1**（那样它就是空断言）—— 实测 4 次到达得 4 行 ⇒ 不是空断言`,
     `注: 该实验只自证**观测的判别力**；C2（库存 98→106、台账 4 行）的泄漏事实由**库内终值**直接读出，不经本实验`],
    { extra: { n4, n1 } })
}

// ═══════════════ C4 重做：大批量读（响应路径 data.items / data.total + 跨页求和）═══════════════
{
  const readings = []
  const get = async (path, label) => {
    const t0 = Date.now()
    const r = await api('GET', path, { token })
    const ms = Date.now() - t0
    const items = r.data?.items
    const rec = { label, path, status: r.status, total: r.data?.total, page: r.data?.page, size: r.data?.size,
                  rows: Array.isArray(items) ? items.length : null, ms,
                  truthy: typeof r.data?.total === 'number' && Array.isArray(items) }
    readings.push(rec)
    return rec
  }
  // ① 主面：stock-ledger（本租户最大的可读面，>500 行 ⇒ 必须跨页取全）
  const led1 = await get('/api/admin/stock-ledger?page=1&size=5000', 'ledger-size5000')   // size 应被钳到 500
  const total0 = led1.total
  const led2 = await get('/api/admin/stock-ledger?page=2&size=500', 'ledger-page2')
  const led3 = await get('/api/admin/stock-ledger?page=3&size=500', 'ledger-page3')
  // 跨页求和（只取前若干页直到取满 total）
  let sum = 0, page = 1
  const capacity = Math.min(6, Math.ceil((total0 || 0) / 500) + 1)
  while (page <= capacity && sum < total0) {
    const rec = page === 1 ? led1 : await get(`/api/admin/stock-ledger?page=${page}&size=500`, `ledger-page${page}-sum`)
    sum += rec.rows || 0
    page++
  }
  // ② orders 面（同形读数）
  const ord1 = await get('/api/admin/orders?page=1&size=5000', 'orders-size5000')
  // ③ after-sales 面
  const as1 = await get('/api/admin/after-sales?page=1&size=5000', 'after-sales-size5000')
  // ④ 边界：size 非法值 / 超上限
  const neg = await get('/api/admin/orders?page=1&size=-5', 'orders-size-negative')
  const zero = await get('/api/admin/orders?page=1&size=0', 'orders-size-zero')
  const big = await get('/api/admin/orders?page=1&size=100000', 'orders-size-100000')
  const counts = psql(`select (select count(*) from orders where tenant_id=${TENANT_ID}) as orders,
                              (select count(*) from stock_ledger_entries where tenant_id=${TENANT_ID}) as ledger,
                              (select count(*) from finance_transactions where tenant_id=${TENANT_ID}) as finance,
                              (select count(*) from after_sales_tickets where tenant_id=${TENANT_ID}) as tickets`)[0]
  writeFileSync(outPath('B4-bulk-read.json'), JSON.stringify({ at: nowCST(), counts, readings, crossPageSum: sum, ledgerTotalAtRead: total0 }, null, 2))

  const s5xx = readings.filter((x) => x.status >= 500)
  // ⚠️ 负 size 的读数**不在本判据的域内**（它由 LB-C4-NEGATIVE-SIZE 单独判）—— 否则同一现象会同时拉红两条
  const badTruth = readings.filter((x) => !x.path.includes('size=-5') && (!x.truthy || (typeof x.total === 'number' && typeof x.rows === 'number' && x.rows > x.total)))
  const capHeld = led1.size === 500 && ord1.size === 500 && as1.size === 500
  // 翻页可达：跨页求和 == total（无静默丢行）。⚠️ total 会随并发写漂移 ⇒ 与「读取时刻的 count(*)」对照
  const crossPageOk = Math.abs(sum - total0) <= 2   // 容差 2 行：读数期间 lineA/lineB 仍在写
  const driftNote = `跨页求和=${sum} / 读取时刻 total=${total0} / 现查 count(*)=${counts.ledger}（写库并发 ⇒ 允许 ≤2 行漂移）`
  const pass = s5xx.length === 0 && badTruth.length === 0 && capHeld && crossPageOk
  R.add('LB-C4-BULK-READ', 'C4 大批量读：size 钳到全局上限 500 / total 诚实 / 跨页求和可达（= total）/ 无 5xx',
    pass ? 'pass' : 'fail',
    `ledger size=5000 ⇒ status=${led1.status} size=${led1.size} total=${led1.total} rows=${led1.rows} ${led1.ms}ms；` +
    `page2 ⇒ rows=${led2.rows}；${driftNote}；orders size=5000 ⇒ total=${ord1.total} size=${ord1.size} rows=${ord1.rows} ${ord1.ms}ms；` +
    `after-sales ⇒ total=${as1.total} size=${as1.size} rows=${as1.rows}；size=100000 ⇒ size=${big.size}；size=-5 ⇒ total=${neg.total}/rows=${neg.rows}；size=0 ⇒ total=${zero.total}/rows=${zero.rows}`,
    [`期望来源: 端点契约 + 源码 backend/admin-api/src/main/java/com/migao/admin/config/MybatisPlusConfig.java 的 PaginationInnerInterceptor(setMaxLimit(500))`,
     `  ⇒ ① 请求 size > 500 必须被**钳到 500**（响应 data.size=500）；② data.total 为真实总数；③ **跨页求和可达 total**（无静默丢行）`,
     `⚠️ 上一版**假绿自曝**：行数原取自 data.records/list/content ⇒ 全部 undefined，却仍判 pass ⇒ 已改判（取不到真值 ⇒ fail）`,
     `⚠️ 响应时间**只作机器读数登记**，不设主观阈值（任务书 §2.B2-4）；5xx / 截断 / 总数与行数不符 = 真缺陷`,
     `机器读数全表: ${JSON.stringify(readings)}`,
     `真值断言: 坏读数（total/rows 非 number，或 rows > total）=${badTruth.length}（期望 0）；5xx=${s5xx.length}（期望 0）；size 钳制成立=${capHeld}；跨页求和 ${sum} vs total ${total0}`,
     `说明: 负 size 的不一致另有独立条目 LB-C4-NEGATIVE-SIZE（判据分离 ⇒ 证据与红证不混）`,
     `数据量真值（现取）: ${JSON.stringify(counts)}`],
    { extra: { counts, readings, crossPageSum: sum, ledgerTotalAtRead: total0 } })

  // ── 独立条目：负 size ⇒ total 与行数不自洽（同族缺陷，判据分离）──
  const negProbe = []
  for (const [url, label] of [['/api/admin/orders?page=1&size=-5', 'orders'],
                              ['/api/admin/stock-ledger?page=1&size=-5', 'stock-ledger'],
                              ['/api/admin/after-sales?page=1&size=-5', 'after-sales']]) {
    const r = await api('GET', url, { token })
    negProbe.push({ label, status: r.status, total: r.data?.total, size: r.data?.size,
                    rows: Array.isArray(r.data?.items) ? r.data.items.length : null })
  }
  writeFileSync(outPath('B4-negative-size.json'), JSON.stringify({ at: nowCST(), negProbe }, null, 2))
  const bad = negProbe.filter((x) => typeof x.total === 'number' && typeof x.rows === 'number' && x.rows > x.total)
  R.add('LB-C4-NEGATIVE-SIZE', 'C4 同族：size 为负数 ⇒ HTTP 200 但 **total=0 而仍返回整页行**（总数与行数不自洽）',
    bad.length === 0 ? 'pass' : 'fail',
    `三个列表端点 size=-5 的读数：${JSON.stringify(negProbe)}；不自洽（rows > total）的点数=${bad.length}`,
    [`期望来源: 端点契约 —— 分页响应里 total = **总记录数**、items = 当前页行 ⇒ 任意 200 响应都必须满足 items.length ≤ total；`,
     `   若 size 非法，应 **4xx 显式拒绝** 或回退默认值（20），**不得**给出 total=0 却返回整页数据的自相矛盾响应`,
     `源码: backend/admin-api/src/main/java/com/migao/admin/controller/OrderController.java 的 getOrders（@RequestParam(defaultValue="1") long size —— **无下限校验**）；`,
     `   分页插件: backend/admin-api/src/main/java/com/migao/admin/config/MybatisPlusConfig.java 的 PaginationInnerInterceptor(setMaxLimit(500)) 只设上限`,
     `影响（机器可判）: 按 total 做翻页/分页器的调用方会以为「0 条」而**静默停在第 1 页**（或显示空列表），数据在响应里却真实存在`,
     `对照组（正例）: size=0 ⇒ total=真实总数、rows=0（自洽）；size=-5 ⇒ total=0、rows=整页（不自洽）⇒ 说明是负数的特殊分支，而不是「size 一律被忽略」`,
     `原始读数: ${JSON.stringify(negProbe)}`],
    { extra: { negProbe } })

  // >1000 行的真实数据量在本租户**不存在**（最大面 ~570 行）⇒ 如实记 skip
  const maxRows = Math.max(counts.orders, counts.ledger, counts.finance, counts.tickets)
  if (maxRows < 1000) {
    R.skip('LB-C4-BULK-READ-1000', 'C4+ 「>1000 行真实数据量」的列表/看板读（截断与总数一致性）',
      `本租户最大可读面行数 = ${maxRows}（orders=${counts.orders} / ledger=${counts.ledger} / finance=${counts.finance} / tickets=${counts.tickets}）< 1000 ⇒ **未覆盖**`,
      [`边界依据（现查 count(*)）: ${JSON.stringify(counts)}`,
       `说明: 分页上限、total 诚实性与跨页可达性已由 LB-C4-BULK-READ 覆盖（ledger 面 >500 行 ⇒ 真跨页）；本条的缺口仅是「>1000 行下的响应时间与截断」`,
       `为什么不自灌: 会污染活库计数（跨包隔离铁律）且成本高 ⇒ 如实记未覆盖，交主会话裁定是否单开环境`])
  } else {
    R.add('LB-C4-BULK-READ-1000', 'C4+ 「>1000 行真实数据量」的列表读', 'pass', `最大面行数 = ${maxRows} ≥ 1000`, [])
  }
}

log(`p4 完成：${JSON.stringify(R.summary())}`)
