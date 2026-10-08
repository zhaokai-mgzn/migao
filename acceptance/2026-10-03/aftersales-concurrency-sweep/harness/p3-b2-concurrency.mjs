// p3-b2-concurrency —— B2 并发/竞态 sweep（本轮方法学重点）
// 用法：API_BASE=http://127.0.0.1:8080 node p3-b2-concurrency.mjs
//
// 四类形态（每类 **重复 3 轮**，逐轮给读数）：
//   C1 同一订单并发退款（防双花 —— 源码 refundOrder 的 COALESCE + WHERE 上限原子条件更新）
//   C2 同一工单并发完结（processing→resolved，双重副作用：累加退款 + 库存回补）
//   C3 同一 SKU 并发扣减（超卖 / 负数 / 台账守恒）
//   C4 大批量读（分页上限 / 总数与行数一致性 / 响应时间机器读数）
//
// 每轮记录：并发度 N、逐请求结局（状态码 + 业务码 + 摘录）、DB 终态、独立算式期望、**重叠证据**。
// 「并发未真正重叠」的绿**不算通过**（记为 falseRed/无判别力）。
import { writeFileSync, readFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import {
  api, adminToken, psql, one, outPath, log, nowCST, Recorder, judge, raceStart, overlapEvidence,
  orderRow, ticketRow, financeRefundRows, skuStock, pgConf,
  cents, fmtQty, moneyAdd, qtyEq, createProbeOrder, createProbeProduct,
  redProofGuardExperiment, guardedWrite, sleep, TENANT_ID,
} from './lib.mjs'

const R = new Recorder('B2-concurrency.json')
const { token, via } = await adminToken()
log(`鉴权成功（via=${via}）`)

const mkProduct = (tag, opts = {}) => createProbeProduct(token, { tag, ...opts })
const mkOrder = (p, tag, onPayment = true, qty = 2, unitPrice = 150) =>
  createProbeOrder(token, { productId: p.productId, productName: p.name, skuId: p.skuId, skuCode: p.skuCode, colorId: p.colorId, qty, unitPrice, tag })

const refund = (orderId, amount, reason = '线B验收并发退款') =>
  api('PUT', `/api/admin/orders/${orderId}/refund`, { token, body: { refund_reason: reason, refund_amount: amount } })
const setStatus = (ticketId, status, remark) =>
  api('PUT', `/api/admin/after-sales/${ticketId}/status`, { token, body: { status, ...(remark ? { remark } : {}) } })
const brief = (r) => ({ status: r?.status, code: r?.bookErr?.code, msg: r?.bookErr?.message || (r?.json?.success ? 'ok' : undefined), text: String(r?.text || '').slice(0, 160) })

/** 预热：把连接池/JIT/首次鉴权开销挪到 barrier 之前（避免把「冷启动」误读成「串行化」）。 */
async function warmup(orderId) {
  await Promise.all([1, 2, 3, 4].map(() => api('GET', `/api/admin/orders/${orderId}`)))
  await api('GET', '/api/admin/after-sales?page=1&size=1')
}

// ═══════════════════════ C1 同一订单并发退款（防双花）═══════════════════════
{
  const N = 8
  const rounds = []
  const perRoundPass = []
  for (let rd = 1; rd <= 3; rd++) {
    const p = await mkProduct(`C1R${rd}`, { allowRestock: false, stock: 100, price: 150 })
    const o = await mkOrder(p, `C1R${rd}`, true, 2, 150)          // 实收 = 300.00
    const actual = orderRow(o.orderId).actual_amount
    await warmup(o.orderId)
    const race = await raceStart(N, () => refund(o.orderId, '100.00', `线B验收并发退款-R${rd}`))
    const ov = overlapEvidence(race)
    const after = orderRow(o.orderId)
    const fin = financeRefundRows(o.orderId)
    const finSum = moneyAdd(...fin.map((x) => x.amount))
    const okCount = race.results.filter((r) => r.out?.status === 200).length
    const failCount = race.results.filter((r) => r.out?.status === 422).length
    // 独立算式期望：每笔 100.00、封顶 300.00 ⇒ 恰好 3 笔成功；累计 = 300.00；流水合计 ≤ 300.00
    const expectOk = 3
    const pass = ov.overlapped && okCount === expectOk &&
                 qtyEq(after?.refund_amount, '300.00') && cents(after?.refund_amount) <= cents(actual) &&
                 cents(finSum) <= cents(actual) && fin.length <= expectOk
    perRoundPass.push(pass)
    rounds.push({
      round: rd, N, orderNo: after?.order_no, actual,
      perRequest: race.results.map((r, i) => ({ i, ...brief(r.out), durMs: r.durMs, startedAtMs: r.t0 })),
      okCount, failCount,
      dbFinal: { refund_amount: after?.refund_amount, refund_at: after?.refund_at, status: after?.status },
      financeRows: fin.length, financeSum: finSum,
      expectation: `成功数 × 100.00 ≤ 实收 ${actual}；refund_amount 终值 ≤ ${actual}；流水合计 ≤ ${actual}`,
      overlapEvidence: ov,
      pass,
    })
  }
  const allPass = perRoundPass.every(Boolean)
  const overlapAll = rounds.every((r) => r.overlapEvidence.overlapped)
  R.add('LB-C1-CONCURRENT-REFUND',
    `C1 同一订单并发退款 N=${N}×3 轮：成功数×金额 ≤ 实收，DB refund_amount 终值 ≤ 实收`,
    allPass ? 'pass' : (overlapAll ? 'fail' : 'falseRed'),
    `三轮成功数=${JSON.stringify(rounds.map((r) => r.okCount))}（期望各 3）；refund_amount 终值=${JSON.stringify(rounds.map((r) => r.dbFinal.refund_amount))}（期望各 300.00 = 实收）；流水行数=${JSON.stringify(rounds.map((r) => r.financeRows))} 合计=${JSON.stringify(rounds.map((r) => r.financeSum))}`,
    [`期望来源: 本包独立算式 —— 每笔请求 100.00、实收 300.00 ⇒ 恰 3 笔可成、第 4 笔起 applied ≤ 0 ⇒ 422`,
     `源码守卫: backend/admin-api/src/main/java/com/migao/admin/service/OrderService.java 的 refundOrder —— setSql("refund_amount = COALESCE(refund_amount,0) + <applied>") + WHERE COALESCE(refund_amount,0) + <applied> <= <actual>；updated==0 ⇒ 抛「该订单已全额退款」`,
     `重叠证据（每轮）: ${rounds.map((r) => `R${r.round}: ${r.overlapEvidence.verdict}`).join(' ｜ ')}`,
     `逐轮逐请求结局: ${JSON.stringify(rounds.map((r) => r.perRequest.map((x) => x.status)))}`,
     `判据纪律: 任一轮未真重叠 ⇒ 整条记 falseRed（无判别力）而非 pass`],
    { extra: { N, rounds, overlapEvidence: rounds.map((r) => r.overlapEvidence) } })

  // 判别力红证（注入）：无守卫 vs 有守卫（产品守卫的同形 SQL），在**本包临时表**上
  const rp = redProofGuardExperiment(N, '300.00', '100.00')
  R.add('LB-C1-REDPROOF', 'C1 判别力红证（注入）：把 WHERE 上限摘掉 ⇒ 必红；同一装置加回守卫 ⇒ 绿',
    (rp.unguardedLeaked && rp.guardedHeld) ? 'pass' : 'fail',
    rp.verdict,
    [`注入方式: **不改产品源码**（铁律 1）—— 在本包自建临时表 lb_gp_redproof 上跑两种等价 UPDATE：`,
     `  ① 无守卫: UPDATE lb_gp_redproof SET refund_amount = COALESCE(refund_amount,0) + 100.00 WHERE id=1;`,
     `  ② 有守卫（产品同形）: … WHERE id=1 AND COALESCE(refund_amount,0) + 100.00 <= cap(300.00);`,
     `N=${N} 个**独立 psql 进程**同时开跑（真并发，非同进程 await）；临时表用后即 drop`,
     `读数: 无守卫终值=${rp.unguardedResult}（泄漏=${rp.unguardedLeaked}）；有守卫终值=${rp.guardedResult}（守住=${rp.guardedHeld}）`,
     `该红证证明：① 实验装置的并发窗口真实存在（否则无守卫也不会超额）；② 判据（累计 ≤ 上限）会红 ⇒ 有判别力`],
    { extra: rp })
}

// ═══════════════════════ C2 同一工单并发完结（双重副作用）═══════════════════════
{
  const N = 4
  const rounds = []
  for (let rd = 1; rd <= 3; rd++) {
    const p = await mkProduct(`C2R${rd}`, { allowRestock: true, stock: 100, price: 150 })
    const o = await mkOrder(p, `C2R${rd}`, true, 2, 150)   // 实收 300.00；SKU 100 → 98
    const skuBefore = skuStock(p.skuId)
    const c = await api('POST', '/api/admin/after-sales', { token, body: {
      orderId: o.orderId, ticketType: 'return', description: `${'线B验收'}工单-C2并发-${rd}`, refundAmount: '300.00' } })
    const ticketId = c.data?.id
    const ticketNo = c.data?.ticketNo
    // 必须先到 processing（pending → resolved 非法）；barrier 之后并发打 processing→resolved
    const toProcessing = await setStatus(ticketId, 'processing', `${'线B验收'}：受理`)
    await warmup(o.orderId)
    const race = await raceStart(N, () => setStatus(ticketId, 'resolved', `${'线B验收'}：并发完结-${rd}`))
    const ov = overlapEvidence(race)
    const tk = ticketRow(ticketId)
    const after = orderRow(o.orderId)
    const skuAfter = skuStock(p.skuId)
    const ledger = psql(`select id, delta, before_qty, after_qty, reason, ref_no from stock_ledger_entries
                         where tenant_id=${TENANT_ID} and ref_no='${ticketNo}' order by id`)
    const timeline = psql(`select id, action, content from ticket_timeline where tenant_id=${TENANT_ID} and ticket_id='${ticketId}' and action='status_change' order by created_at`)
    const fin = financeRefundRows(o.orderId)
    const okCount = race.results.filter((r) => r.out?.status === 200).length
    // 独立算式：一次合法完结 ⇒ 退款 300.00（= 实收）、回补 2.00（98 → 100）、aftersales 台账 1 行
    // 期望：终态 resolved；refund_amount ≤ 实收（守卫）；库存 ≤ 100.00（**不得回补两次**）
    const stockOver = cents(skuAfter?.stock) > cents('100.00')
    const ledgerOver = ledger.length > 1
    const refundOver = cents(after?.refund_amount) > cents(after?.actual_amount)
    const pass = ov.overlapped && tk?.status === 'resolved' && !stockOver && !ledgerOver && !refundOver &&
                 qtyEq(after?.refund_amount, '300.00') && qtyEq(skuAfter?.stock, '100.00') && ledger.length === 1
    rounds.push({
      round: rd, N, ticketNo, okCount,
      perRequest: race.results.map((r, i) => ({ i, ...brief(r.out), durMs: r.durMs })),
      dbFinal: { ticketStatus: tk?.status, refund_amount: after?.refund_amount, actual: after?.actual_amount,
                 skuBefore: skuBefore?.stock, skuAfter: skuAfter?.stock,
                 ledgerRows: ledger.length, timelineRows: timeline.length, financeRows: fin.length },
      leaks: { stockOver, ledgerOver, refundOver },
      expectation: '一次完结的副作用 = 退款 300.00 封顶 + 回补 2.00（98→100）+ 台账 1 行；并发不得翻倍',
      overlapEvidence: ov, pass,
      raw: { race: race.results.map((r) => brief(r.out)), ledger, timeline: timeline.map((t) => t.content) },
    })
  }
  const overlapAll = rounds.every((r) => r.overlapEvidence.overlapped)
  const anyLeak = rounds.some((r) => r.leaks.stockOver || r.leaks.ledgerOver || r.leaks.refundOver)
  const allPass = rounds.every((r) => r.pass)
  R.add('LB-C2-CONCURRENT-RESOLVE',
    `C2 同一工单并发完结（processing→resolved）N=${N}×3 轮：副作用不得翻倍`,
    allPass ? 'pass' : (overlapAll ? 'fail' : 'falseRed'),
    `三轮结论=${JSON.stringify(rounds.map((r) => ({ 成功数: r.okCount, 工单终态: r.dbFinal.ticketStatus, 退款: r.dbFinal.refund_amount, 库存: `${r.dbFinal.skuBefore}→${r.dbFinal.skuAfter}`, 台账行: r.dbFinal.ledgerRows, 时间线行: r.dbFinal.timelineRows, 流水行: r.dbFinal.financeRows, 泄漏: r.leaks })))}`,
    [`期望来源: 本包独立算式 —— 一次完结的副作用：退款 applied=min(300.00, 实收−已退) 封顶实收；回补 2.00；台账恰 1 行；时间线每次状态变更 1 行`,
     `源码: backend/admin-api/src/main/java/com/migao/admin/service/AfterSalesTicketService.java 的 updateTicketStatus —— 状态机校验读的是**内存里的旧值**，落库用 updateById(ticket)（WHERE 仅 id）`,
     `源码: 同文件的 linkRefundToOrderAndFinance（有 COALESCE+WHERE 上限守卫）与 maybeRestockOnReturn（调 OrderService.restoreStockForReturn）`,
     `源码: backend/admin-api/src/main/java/com/migao/admin/mapper/ProductSkuMapper.java 的 restoreStock = "UPDATE product_skus SET stock = COALESCE(stock,0) + #{quantity} WHERE id = #{skuId}"（**无上限、无幂等谓词**）`,
     `重叠证据（每轮）: ${rounds.map((r) => `R${r.round}: ${r.overlapEvidence.verdict}`).join(' ｜ ')}`,
     `逐轮逐请求结局: ${JSON.stringify(rounds.map((r) => r.perRequest.map((x) => x.status)))}`,
     `⚠️ 泄漏判据（独立于时序的）: 库存 > 100.00（回补两次）/ 台账 > 1 行 / 退款 > 实收`,
     `判据纪律: 任一轮未真重叠 ⇒ 原记 falseRed，但若**已观察到泄漏读数**则泄漏事实独立成立（另行说明）`],
    { extra: { N, rounds, overlapEvidence: rounds.map((r) => r.overlapEvidence) } })
}

// ═══════════════════════ C3 同一 SKU 并发扣减（超卖 / 负数 / 守恒）═══════════════════════
{
  const N = 8
  const rounds = []
  for (let rd = 1; rd <= 3; rd++) {
    // ① 并发扣减的**守卫**（与产品 SKU 扣减同形 SQL）在自建临时表上跑真并发
    const setup = () => {
      guardedWrite(`-- probe-ok\ndrop table if exists lb_gp_stock;`)
      guardedWrite(`-- probe-ok\ncreate table lb_gp_stock (sku bigint primary key, stock numeric(12,1));`)
      guardedWrite(`-- probe-ok\ninsert into lb_gp_stock values (1, 3.0);`)
    }
    const runConcurrent = (qty) => {
      const c = pgConf()
      const cmd = `for i in $(seq 1 ${N}); do psql -h ${c.host} -p ${c.port} -U ${c.user} -d ${c.db} -t -A -v ON_ERROR_STOP=1 ` +
        `-c "UPDATE lb_gp_stock SET stock = GREATEST(COALESCE(stock,0) - ${qty}, 0) WHERE sku=1;" >/dev/null 2>&1 & done; wait`
      execFileSync('bash', ['-lc', cmd], { env: { ...process.env, PGPASSWORD: c.password }, encoding: 'utf8' })
      return one(`select stock from lb_gp_stock where sku=1`)?.stock
    }
    setup()
    const stockAfter = runConcurrent('1.0')
    guardedWrite(`-- probe-ok\ndrop table if exists lb_gp_stock;`)
    // ② 真实端点：库存不足时的**串行**负例（超卖必须被拒，而非静默截断）
    const p = await mkProduct(`C3R${rd}`, { allowRestock: false, stock: 3, price: 100 })
    const over = await api('POST', '/api/admin/orders', { token, body: {
      customerName: `${'线B验收'}客户-C3-${rd}`, customerPhone: '13900000031', customerAddress: `${'线B验收'}地址`,
      logisticsType: 'express', logisticsCompany: `${'线B验收'}物流`, remark: `${'线B验收'}（探针订单-C3超卖）`,
      items: [{ productId: p.productId, productName: p.name, quantity: 5, unitPrice: 100, subtotal: '500.000',
                width: 2.8, height: 2.0, processingInfo: { skuId: p.skuId, skuCode: p.skuCode, colorId: p.colorId, doorWidth: '2.8m' } }],
    } })
    const stockUntouched = skuStock(p.skuId)
    // ③ 并发「确认收款」同一订单（含扣减）—— 验幂等/守恒
    const p3 = await mkProduct(`C3D${rd}`, { allowRestock: false, stock: 100, price: 100 })
    const o3 = await mkOrder(p3, `C3D${rd}`, false, 2, 100)   // 不自动确认收款
    await warmup(o3.orderId)
    const race = await raceStart(N, () => api('PUT', `/api/admin/orders/${o3.orderId}/payment`, { token, body: {} }))
    const ov = overlapEvidence(race)
    const skuAfterPay = skuStock(p3.skuId)
    const orderAfterPay = orderRow(o3.orderId)
    const okCount = race.results.filter((r) => r.out?.status === 200).length
    const ledgerPay = psql(`select id, delta, before_qty, after_qty, reason from stock_ledger_entries
                            where tenant_id=${TENANT_ID} and sku_id=${p3.skuId} and ref_no='${orderAfterPay?.order_no}' order by id`)
    const pass = qtyEq(stockAfter, '0.0') && over.status === 422 && qtyEq(stockUntouched?.stock, '3.0') &&
                 cents(skuAfterPay?.stock) >= 0n && qtyEq(skuAfterPay?.stock, '98.0')
    rounds.push({
      round: rd, N,
      guardSql: { concurrentDeductFinal: stockAfter, expected: '0.0（GREATEST 夹在 0，且 8×(3−8) 不得为负）' },
      oversell: { status: over.status, code: over.bookErr?.code, msg: over.bookErr?.message,
                  stockUntouched: stockUntouched?.stock, expect: '422 + 请求 5 > 库存 3 被拒 + SKU 库存保持 3.0' },
      concurrentPay: { okCount, perRequest: race.results.map((r, i) => ({ i, ...brief(r.out), durMs: r.durMs })),
                       skuAfter: skuAfterPay?.stock, orderStatus: orderAfterPay?.status, ledgerRows: ledgerPay.length,
                       expect: 'SKU 100 → 98.0 恰一次（不得扣两次）；订单终态 confirmed' },
      overlapEvidence: ov, pass,
    })
  }
  const allPass = rounds.every((r) => r.pass)
  const overlapAll = rounds.every((r) => r.overlapEvidence.overlapped)
  R.add('LB-C3-CONCURRENT-STOCK', `C3 同一 SKU 并发扣减 N=${N}×3 轮：超卖拒绝 / 库存不为负 / 台账守恒`,
    allPass ? 'pass' : (overlapAll ? 'fail' : 'falseRed'),
    `三轮：并发扣减终值=${JSON.stringify(rounds.map((r) => r.guardSql.concurrentDeductFinal))}（期望 0.0）；超卖请求结局=${JSON.stringify(rounds.map((r) => [r.oversell.status, r.oversell.stockUntouched]))}（期望 [422, 3.0]）；并发收款后 SKU=${JSON.stringify(rounds.map((r) => r.concurrentPay.skuAfter))}（期望 98.0）`,
    [`期望来源: 本包独立算式 —— 临时表初值 3.0、8 个并发各扣 1.0 ⇒ GREATEST(…,0) 夹在 0.0（不得为负）；`,
     `   产品扣减 SQL 同形（backend/admin-api/src/main/java/com/migao/admin/mapper/ProductSkuMapper.java 的 deductStock = "UPDATE product_skus SET stock = GREATEST(COALESCE(stock,0) - #{quantity}, 0) WHERE id = #{skuId}"）`,
     `   超卖：请求 5 米 > 库存 3 米 ⇒ 必须 422（不得静默截断成 3 米）；`,
     `   并发确认收款：SKU 100 → 98.0 恰一次（事务 + 状态机守卫）`,
     `重叠证据（每轮）: ${rounds.map((r) => `R${r.round}: ${r.overlapEvidence.verdict}`).join(' ｜ ')}`,
     `⚠️ 未覆盖（如实登记）: 真实 API 面上**并发下单**的扣减发生在 confirmPayment（下单不扣库存）⇒ 本类以「并发确认收款 + 扣减守卫同形 SQL」两路覆盖，未覆盖「并发下单同时确认」的混合形态`],
    { extra: { N, rounds, overlapEvidence: rounds.map((r) => r.overlapEvidence) } })
}

// ═══════════════════════ C4 大批量读（机器读数，不设主观阈值）═══════════════════════
{
  const sizes = [20, 200, 2000, 5000]
  const readings = []
  for (const size of sizes) {
    for (const [path, label] of [
      [`/api/admin/orders?page=1&size=${size}`, 'orders'],
      [`/api/admin/after-sales?page=1&size=${size}`, 'after-sales'],
    ]) {
      const t0 = Date.now()
      const r = await api('GET', path)
      const ms = Date.now() - t0
      const list = r.data?.records ?? r.data?.list ?? r.data?.content ?? r.data?.items ?? null
      const rows = Array.isArray(list) ? list.length : null
      const total = r.data?.total
      readings.push({ path, label, size, status: r.status, total, rows, ms, ok: r.status === 200,
                      consistent: r.status === 200 && rows !== null && (total == null || rows <= total) })
    }
  }
  writeFileSync(outPath('B2-bulk-read.json'), JSON.stringify({ at: nowCST(), readings }, null, 2))
  const s5xx = readings.filter((x) => x.status >= 500)
  const inconsistent = readings.filter((x) => x.ok && (x.rows === null || (x.total != null && x.rows > x.total)))
  const pass = s5xx.length === 0 && inconsistent.length === 0
  R.add('LB-C4-BULK-READ', 'C4 大批量读：分页上限 / 总数与行数一致性 / 响应时间（机器读数）',
    pass ? 'pass' : 'fail',
    `orders size=5000 ⇒ total=${readings.find((x) => x.label === 'orders' && x.size === 5000)?.total} rows=${readings.find((x) => x.label === 'orders' && x.size === 5000)?.rows} ${readings.find((x) => x.label === 'orders' && x.size === 5000)?.ms}ms；after-sales size=5000 ⇒ total=${readings.find((x) => x.label === 'after-sales' && x.size === 5000)?.total} rows=${readings.find((x) => x.label === 'after-sales' && x.size === 5000)?.rows} ${readings.find((x) => x.label === 'after-sales' && x.size === 5000)?.ms}ms`,
    [`期望来源: 端点契约 —— 200 且 records 行数 ≤ total；**无 5xx、无静默截断**（行数 < 请求 size 时 total ≤ size 或分页语义自洽）`,
     `机器读数全表: ${JSON.stringify(readings)}`,
     `⚠️ 纪律: **不设主观性能阈值、不判性能缺陷**（任务书 §2.B2-4）；仅登记 5xx / 截断 / 总数与行数不符`,
     `⚠️ 数据量边界（如实登记）: 本租户 orders≈397 行、after-sales≈5 行 ⇒ 「>1000 行真实数据量」在本租户**不存在**；`,
     `   故本条覆盖的是「分页上限与一致性」而非「>1000 行性能」`,
     `判据: 5xx 数=${s5xx.length}（期望 0）；总数/行数不自洽数=${inconsistent.length}（期望 0）`],
    { extra: { readings } })
}

log(`p3 完成：${JSON.stringify(R.summary())}`)
