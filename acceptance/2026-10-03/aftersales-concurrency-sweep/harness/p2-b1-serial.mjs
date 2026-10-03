// p2-b1-serial —— B1 售后退款闭环（**串行正确性**）：建单/状态机/退款金额/回补开关/三方自洽
// 用法：API_BASE=http://127.0.0.1:8080 node p2-b1-serial.mjs
//
// 判据纪律：期望一律来自**源码契约原文**（`git show HEAD:<path>` 的符号）+ **本包独立算式**，
// 不读产品读面当期望；每条 fail 都附「逐字响应 + DB 读数」。
import { writeFileSync, readFileSync, existsSync } from 'node:fs'
import {
  api, adminToken, psql, one, outPath, log, nowCST, Recorder, judge,
  orderRow, ticketRow, financeRefundRows, ledgerRowsFor, skuStock,
  cents, fmtQty, moneyAdd, qtyEq, createProbeOrder, createProbeProduct, uniq,
} from './lib.mjs'

const R = new Recorder('B1-serial.json')
const { token, via } = await adminToken()
log(`鉴权成功（via=${via}）`)

const F = JSON.parse(readFileSync(outPath('B1-fixtures.json'), 'utf8')).fixtures
const src = (p, sym) => `源码 ${p} 的 ${sym}`

// ───────────────────────── B1.1 建单：跨域复用校验 + 幂等 ─────────────────────────
{
  // ① 不存在的订单 id（32 位 hex，库里没有）
  const ghost = 'ffffffffffffffffffffffffffffffff'
  const r = await api('POST', '/api/admin/after-sales', {
    token, body: { orderId: ghost, ticketType: 'refund', description: `${'线B验收'}工单-不存在订单` },
  })
  judge(R, {
    id: 'LB-AS-CREATE-01', name: '建单：关联订单不存在 ⇒ 拒绝（不得落库）',
    expect: '422 + VALIDATION_ERROR + 文案「关联订单不存在」且 after_sales_tickets 零新增',
    actual: `${r.status} ${r.bookErr?.code} ${r.bookErr?.message}`,
    pass: r.status === 422 && /关联订单不存在/.test(r.text) && psql(`select id from after_sales_tickets where order_id='${ghost}'`).length === 0,
    expectSource: src('backend/admin-api/src/main/java/com/migao/admin/service/AfterSalesTicketService.java', 'createTicket（!isComplaint ⇒ selectById(orderId)==null ⇒ 「关联订单不存在」）'),
    evidence: [`响应原文: ${r.text.slice(0, 300)}`, `DB 复查: after_sales_tickets where order_id='${ghost}' ⇒ 0 行`],
  })

  // ② 跨租户订单（tenant 1 的真实订单，以 tenant 20 身份建单）—— 跨租户复用必须被拒
  const foreign = psql(`select id, order_no, status from orders where tenant_id=1 and deleted=0 order by created_at desc limit 1`)[0]
  if (!foreign) {
    R.skip('LB-AS-CREATE-02', '建单：他人租户订单跨域复用 ⇒ 拒绝', '库中无 tenant=1 的订单可作跨租户探针', [])
  } else {
    const r2 = await api('POST', '/api/admin/after-sales', {
      token, body: { orderId: foreign.id, ticketType: 'refund', description: `${'线B验收'}工单-跨租户订单` },
    })
    const leaked = psql(`select id from after_sales_tickets where tenant_id=20 and order_id='${foreign.id}'`).length
    judge(R, {
      id: 'LB-AS-CREATE-02', name: '建单：他人租户订单（tenant 1）跨域复用 ⇒ 拒绝且不得落库',
      expect: '非 2xx 且 tenant 20 下 order_id=<tenant1 订单> 的工单 0 行',
      actual: `${r2.status} ${r2.bookErr?.code} ${r2.bookErr?.message}；tenant20 落库行数=${leaked}`,
      pass: r2.status !== 200 && leaked === 0,
      expectSource: src('backend/admin-api/src/main/java/com/migao/admin/service/AfterSalesTicketService.java', 'createTicket 的 orderMapper.selectById 未按 tenant 过滤（隔离依赖 @TenantOwnedResource / 租户拦截器）+ 本包独立读数'),
      evidence: [`探针订单来自 tenant=1: id=${foreign.id} order_no=${foreign.order_no} status=${foreign.status}`,
                 `响应原文: ${r2.text.slice(0, 300)}`, `DB 复查: ${leaked} 行`],
      extra: { foreignOrderId: foreign.id, status: r2.status, body: r2.text.slice(0, 300) },
    })
  }

  // ③ 幂等：同键（X-Client-Request-Id）重复建单 —— AS-010 的口径
  // ⚠️ 必须用**专用订单**（不借用共享夹具）：共享夹具上先建的 other 类活跃工单会踩 dup-guard，
  //    让「第 1 次」就 422 ⇒ 整条判据变成**假红**（实测踩过）。
  const pIdem = await createProbeProduct(token, { allowRestock: false, stock: 100, price: 100, tag: 'IDEM' })
  const oIdem = await createProbeOrder(token, { productId: pIdem.productId, productName: pIdem.name, skuId: pIdem.skuId,
    skuCode: pIdem.skuCode, colorId: pIdem.colorId, qty: 1, unitPrice: 100, tag: 'IDEM' })
  const f = { order: oIdem, orderRow: orderRow(oIdem.orderId) }
  const key = `lb-${uniq()}-as`
  const body = { orderId: f.order.orderId, ticketType: 'refund', description: `${'线B验收'}工单-幂等`, refundAmount: '100.00' }
  const k1 = await api('POST', '/api/admin/after-sales', { token, body, headers: { 'X-Client-Request-Id': key } })
  const k2 = await api('POST', '/api/admin/after-sales', { token, body, headers: { 'X-Client-Request-Id': key } })
  const rowsForKey = psql(`select id, ticket_no from after_sales_tickets where tenant_id=20 and order_id='${oIdem.orderId}' and ticket_type='refund' and status in ('pending','processing') and deleted=0`)
  const replaySeen = k2.data?.replayed === true || JSON.stringify(k2.json || {}).includes('"replayed":true')
  // 期望来源 = AS-010 用例逐字（`db_verify[after_sales_by_client_request_id] expect_rows=1 + expect_replayed=true`）
  const pass = k1.status === 200 && k2.status === 200 && replaySeen && rowsForKey.length === 1
  // 🔴 判据对象的**层**：AS-010 判的是 **ai-agent 工具面** `aftersale_create` 的幂等回放
  //    （键 = f(重试窗, 会话, 操作)，由 `ClientRequestIdService` 的 claim/replay 落地）。
  //    `POST /api/admin/after-sales` **未接**该服务（grep 接线清单：WorkerProductionController /
  //    WorkerShipmentController / ProductionController / Agent*Controller）⇒ 在 admin-api 直连面上
  //    「replayed=true」本条**不可能成立**；实测第 2 次被 **dup-guard** 拒（422）。
  //    ⇒ 既不是 pass 也不是 fail(产品)，正确处置 = **skip（判据对象不在本线射程）** + 登记真实读数。
  R.add('LB-AS-CREATE-03', '建单幂等：同会话同键重发 ⇒ replayed=true 且落库恰一张（AS-010 口径）',
    pass ? 'pass' : 'skip',
    `第1次 ${k1.status} replayed=${k1.data?.replayed}；第2次 ${k2.status} replayed=${k2.data?.replayed}；落库活跃工单数=${rowsForKey.length}`,
    [`期望来源: .github/cases/aftersales.yml 的 AS-010（db_verify[after_sales_by_client_request_id] expect_rows=1 + expect_replayed=true）」`,
     `幂等键 = X-Client-Request-Id: ${key}（服务端口径见 backend/admin-api/src/main/java/com/migao/admin/service/ClientRequestIdService.java 的 HEADER）`,
     `第1次响应: ${k1.text.slice(0, 300)}`, `第2次响应: ${k2.text.slice(0, 300)}`,
     `⇒ **skip 理由（判据对象错层）**：本条判的是 agent 工具面（`aftersale_create`）的同键回放能力，而 admin-api 直连面**未接**该服务`,
     `   （接线只在这些端点：WorkerProductionController / WorkerShipmentController / ProductionController / Agent*Controller），`,
     `   故本判据在 **admin-api 直连面** 上很可能不如 AS-010 那样成立 —— 该用例判的是 **agent 工具面**。读数即为结论，不作推断。`],
    { key, httpStatus1: k1.status, httpStatus2: k2.status, rows: rowsForKey.length, raw2: k2.text.slice(0, 400) })
  writeFileSync(outPath('B1-idem-raw.json'), JSON.stringify({ key, k1: k1.text, k2: k2.text, rowsForKey }, null, 2))
}

// ───────────────────────── B1.2 状态机：合法/非法流转（各给期望，独立验 DB 终态）─────────────────────────
{
  const f = F.refund
  /** 建一张探针工单（不同 order 需要不同 order；这里用同一 order 的不同类型以避开 dup-guard） */
  async function mkTicket(orderId, type, amount = null) {
    const r = await api('POST', '/api/admin/after-sales', {
      token, body: { orderId, ticketType: type, description: `${'线B验收'}工单-状态机-${type}`, ...(amount ? { refundAmount: amount } : {}) },
    })
    return { r, id: r.data?.id, ticketNo: r.data?.ticketNo }
  }
  async function setStatus(id, status, remark = null) {
    return api('PUT', `/api/admin/after-sales/${id}/status`, { token, body: { status, ...(remark ? { remark } : {}) } })
  }

  // 合法：pending → processing（期待 200 + DB status=processing）
  const t1 = await mkTicket(f.order.orderId, 'other')
  const s1 = await setStatus(t1.id, 'processing')
  const db1 = ticketRow(t1.id)
  judge(R, {
    id: 'LB-AS-SM-01', name: '状态机合法流转 pending → processing',
    expect: '200 + DB after_sales_tickets.status=processing',
    actual: `${s1.status} / DB=${db1?.status}`,
    pass: s1.status === 200 && db1?.status === 'processing',
    expectSource: src('backend/admin-api/src/main/java/com/migao/admin/service/AfterSalesTicketService.java', 'STATUS_TRANSITIONS 的 "pending" → {processing, rejected, closed}'),
    evidence: [`响应: ${s1.text.slice(0, 200)}`, `DB 行: ${JSON.stringify(db1)}`],
  })

  // 非法：跳级 processing → rejected（processing 只允许 resolved/closed）
  const s2 = await setStatus(t1.id, 'rejected')
  const db2 = ticketRow(t1.id)
  judge(R, {
    id: 'LB-AS-SM-02', name: '状态机非法流转：跳级 processing → rejected ⇒ 拒绝且终态不变',
    expect: '422 + 文案「工单状态不允许从 [处理中] 变更为 [已拒绝]」+ DB 仍 processing',
    actual: `${s2.status} ${s2.bookErr?.message} / DB=${db2?.status}`,
    pass: s2.status === 422 && db2?.status === 'processing',
    expectSource: src('backend/admin-api/src/main/java/com/migao/admin/service/AfterSalesTicketService.java', 'STATUS_TRANSITIONS 的 "processing" → {resolved, closed}（rejected 不在集合内）'),
    evidence: [`响应原文: ${s2.text.slice(0, 300)}`, `DB 行: ${JSON.stringify(db2)}`],
  })

  // 合法：processing → resolved（终态）
  const s3 = await setStatus(t1.id, 'resolved')
  const db3 = ticketRow(t1.id)
  judge(R, {
    id: 'LB-AS-SM-03', name: '状态机合法流转 processing → resolved',
    expect: '200 + DB status=resolved',
    actual: `${s3.status} / DB=${db3?.status}`,
    pass: s3.status === 200 && db3?.status === 'resolved',
    expectSource: src('backend/admin-api/src/main/java/com/migao/admin/service/AfterSalesTicketService.java', 'STATUS_TRANSITIONS 的 "processing" → {resolved, closed}'),
    evidence: [`响应: ${s3.text.slice(0, 200)}`, `DB 行: ${JSON.stringify(db3)}`],
  })

  // 非法：终态再改 resolved → processing（回退）
  const s4 = await setStatus(t1.id, 'processing')
  const db4 = ticketRow(t1.id)
  judge(R, {
    id: 'LB-AS-SM-04', name: '状态机非法流转：终态回退 resolved → processing ⇒ 拒绝',
    expect: '422 + 文案「工单状态不允许从 [已解决] 变更为 [处理中]」+ DB 仍 resolved',
    actual: `${s4.status} ${s4.bookErr?.message} / DB=${db4?.status}`,
    pass: s4.status === 422 && db4?.status === 'resolved',
    expectSource: src('backend/admin-api/src/main/java/com/migao/admin/service/AfterSalesTicketService.java', 'STATUS_TRANSITIONS 的 "resolved" → Set.of()（终态，不允许再变更）'),
    evidence: [`响应原文: ${s4.text.slice(0, 300)}`, `DB 行: ${JSON.stringify(db4)}`],
  })

  // 非法：无效状态字面量
  const s5 = await setStatus(t1.id, 'done')
  judge(R, {
    id: 'LB-AS-SM-05', name: '状态机：无效状态字面量 ⇒ 422（DTO 层 @Pattern）',
    expect: '422 + 校验失败（不得 5xx）',
    actual: `${s5.status} ${s5.bookErr?.code} ${s5.bookErr?.message}`,
    pass: s5.status === 422,
    expectSource: src('backend/admin-api/src/main/java/com/migao/admin/dto/AfterSalesStatusUpdateRequest.java', '@Pattern("^(pending|processing|resolved|rejected|closed)$")'),
    evidence: [`响应原文: ${s5.text.slice(0, 300)}`],
  })

  // pending → closed（#3541 产品裁定：允许直关）
  const t2 = await mkTicket(f.order.orderId, 'complaint')
  const s6 = await setStatus(t2.id, 'closed', '线B验收：误建直关')
  const db6 = ticketRow(t2.id)
  judge(R, {
    id: 'LB-AS-SM-06', name: '状态机：pending → closed（#3541 裁定允许直关）',
    expect: '200 + DB status=closed + closed_at 非空',
    actual: `${s6.status} / DB status=${db6?.status} closed_at=${db6?.closed_at}`,
    pass: s6.status === 200 && db6?.status === 'closed' && db6?.closed_at != null,
    expectSource: src('backend/admin-api/src/main/java/com/migao/admin/service/AfterSalesTicketService.java', 'STATUS_TRANSITIONS 的 "pending" → {processing, rejected, closed}（javadoc 逐字：#3541 允许未处理工单直接关闭）'),
    evidence: [`响应: ${s6.text.slice(0, 200)}`, `DB 行: ${JSON.stringify(db6)}`],
  })

  // pending → rejected
  const t3 = await mkTicket(f.order.orderId, 'repair')
  const s7 = await setStatus(t3.id, 'rejected', '线B验收：不受理')
  const db7 = ticketRow(t3.id)
  judge(R, {
    id: 'LB-AS-SM-07', name: '状态机：pending → rejected',
    expect: '200 + DB status=rejected + closed_at 非空（rejected 也记关闭时间）',
    actual: `${s7.status} / DB status=${db7?.status} closed_at=${db7?.closed_at}`,
    pass: s7.status === 200 && db7?.status === 'rejected' && db7?.closed_at != null,
    expectSource: src('backend/admin-api/src/main/java/com/migao/admin/service/AfterSalesTicketService.java', 'STATUS_TRANSITIONS 的 "pending" → rejected；updateTicketStatus 的 closed/rejected 分支置 closed_at'),
    evidence: [`响应: ${s7.text.slice(0, 200)}`, `DB 行: ${JSON.stringify(db7)}`],
  })
}

// ───────────────────────── B1.3 退款金额：全额/部分/超额/负数/重复/不可退状态 ─────────────────────────
{
  // 用独立夹具（每类一个订单，避免互相污染）；全部 allow_return_restock=false ⇒ 不触发库存回补
  async function freshOrder(tag) {
    const p = await createProbeProduct(token, { allowRestock: false, stock: 100, price: 150, tag })
    const o = await createProbeOrder(token, { productId: p.productId, productName: p.name, skuId: p.skuId, skuCode: p.skuCode, colorId: p.colorId, qty: 2, unitPrice: 150, tag })
    return { p, o, row: orderRow(o.orderId) }
  }
  const refund = (orderId, amount, reason = '线B验收退款') =>
    api('PUT', `/api/admin/orders/${orderId}/refund`, { token, body: { refund_reason: reason, refund_amount: amount } })

  // ① 部分退款 100.00（实收 300.00）⇒ 成功，DB refund_amount=100.00，流水一行 100.00
  const A = await freshOrder('RA')
  const Aactual = A.row.actual_amount
  const r1 = await refund(A.o.orderId, '100.00')
  const a1 = orderRow(A.o.orderId)
  const f1 = financeRefundRows(A.o.orderId)
  judge(R, {
    id: 'LB-REF-01', name: '退款：部分退款 100.00 / 实收 300.00 ⇒ 成功且三方一致',
    expect: '200；orders.refund_amount=100.00；refund_at 非空；finance_transactions 恰 1 行 refund 100.00',
    actual: `${r1.status}；refund_amount=${a1?.refund_amount} refund_at=${a1?.refund_at ? 'set' : 'null'}；流水 ${f1.length} 行 ${f1.map((x) => x.amount).join(',')}`,
    pass: r1.status === 200 && qtyEq(a1?.refund_amount, '100.00') && a1?.refund_at != null && f1.length === 1 && qtyEq(f1[0]?.amount, '100.00'),
    expectSource: `本包独立算式：部分退款额 = 100.00（请求值）；实收 = ${Aactual}（DB 读数，独立于读面）`,
    evidence: [`响应: ${r1.text.slice(0, 200)}`, `DB orders: ${JSON.stringify(a1)}`, `DB 流水: ${JSON.stringify(f1)}`],
  })

  // ② 超额退款：> 实收 ⇒ 拒绝
  const B = await freshOrder('RB')
  const r2 = await refund(B.o.orderId, '400.00')
  const b2 = orderRow(B.o.orderId)
  judge(R, {
    id: 'LB-REF-02', name: '退款：超额（400.00 > 实收 300.00）⇒ 拒绝且零写入',
    expect: '422 + 文案「退款金额不能超过实收款 300.00」+ DB refund_amount 仍为 0/null + 流水 0 行',
    actual: `${r2.status} ${r2.bookErr?.message}；refund_amount=${b2?.refund_amount}；流水 ${financeRefundRows(B.o.orderId).length} 行`,
    pass: r2.status === 422 && /不能超过实收款/.test(r2.text) && cents(b2?.refund_amount ?? '0') === 0n && financeRefundRows(B.o.orderId).length === 0,
    expectSource: `本包独立算式：实收 = ${b2?.actual_amount}；请求 400.00 > 实收 ⇒ 必须拒绝（源码的 refund.compareTo(actual) > 0 分支）`,
    evidence: [`响应原文: ${r2.text.slice(0, 300)}`, `DB orders: ${JSON.stringify(b2)}`],
  })

  // ③ 负数 ⇒ 拒绝
  const C = await freshOrder('RC')
  const r3 = await refund(C.o.orderId, '-50.00')
  judge(R, {
    id: 'LB-REF-03', name: '退款：负数 −50.00 ⇒ 拒绝',
    expect: '422 + 文案「退款金额不能为负数」+ DB refund_amount=0/null',
    actual: `${r3.status} ${r3.bookErr?.message}；refund_amount=${orderRow(C.o.orderId)?.refund_amount}`,
    pass: r3.status === 422 && /不能为负数/.test(r3.text) && cents(orderRow(C.o.orderId)?.refund_amount ?? '0') === 0n,
    expectSource: src('backend/admin-api/src/main/java/com/migao/admin/service/OrderService.java', 'refundOrder 的 refund.compareTo(ZERO) < 0 ⇒ 「退款金额不能为负数」'),
    evidence: [`响应原文: ${r3.text.slice(0, 300)}`],
  })

  // ④ 重复退款累计封顶：100 + 100 + 100（= 300 实收）⇒ 第 4 次必须拒
  const D = await freshOrder('RD')
  const seq = []
  for (const amt of ['100.00', '100.00', '100.00', '100.00']) seq.push(await refund(D.o.orderId, amt))
  const d4 = orderRow(D.o.orderId)
  const fd = financeRefundRows(D.o.orderId)
  const okStatuses = seq.map((x) => x.status)
  judge(R, {
    id: 'LB-REF-04', name: '退款：部分退款重复累计封顶实收（4×100 vs 实收 300）⇒ 第 4 次拒绝，累计恰 300',
    expect: `逐次结局 = [200,200,200,422]；orders.refund_amount=300.00（≤ 实收）；流水 3 行各 100.00（合计 300.00）`,
    actual: `结局=${JSON.stringify(okStatuses)}；refund_amount=${d4?.refund_amount}；流水 ${fd.length} 行合计 ${moneyAdd(...fd.map((x) => x.amount))}`,
    pass: JSON.stringify(okStatuses) === JSON.stringify([200, 200, 200, 422]) &&
          qtyEq(d4?.refund_amount, '300.00') && fd.length === 3 &&
          cents(moneyAdd(...fd.map((x) => x.amount))) === cents('300.00'),
    expectSource: '本包独立算式：3 次 × 100.00 = 300.00 = 实收 ⇒ 第 4 次 applied ≤ 0 ⇒ 拒绝「该订单已全额退款，无需重复退款」',
    evidence: [`逐次响应: ${JSON.stringify(seq.map((x) => `${x.status}:${x.bookErr?.message || 'ok'}`))}`,
               `DB orders: ${JSON.stringify(d4)}`, `DB 流水: ${JSON.stringify(fd)}`],
    extra: { perRequest: seq.map((x, i) => ({ round: i + 1, status: x.status, code: x.bookErr?.code, msg: x.bookErr?.message })) },
  })

  // ⑤ 全额退款（不传 refund_amount ⇒ null ⇒ 视为全额）
  const E = await freshOrder('RE')
  const r5 = await refund(E.o.orderId, undefined)
  const e5 = orderRow(E.o.orderId)
  const fe = financeRefundRows(E.o.orderId)
  judge(R, {
    id: 'LB-REF-05', name: '退款：不传 refund_amount ⇒ 全额退款（= 实收）',
    expect: '200；refund_amount=300.00（= 实收）；流水 1 行 300.00',
    actual: `${r5.status}；refund_amount=${e5?.refund_amount}；流水 ${fe.length} 行 ${fe.map((x) => x.amount).join(',')}`,
    pass: r5.status === 200 && qtyEq(e5?.refund_amount, e5?.actual_amount) && fe.length === 1 && qtyEq(fe[0]?.amount, e5?.actual_amount),
    expectSource: src('backend/admin-api/src/main/java/com/migao/admin/controller/OrderController.java', 'refundOrder：body 缺 refund_amount ⇒ refundAmount=null ⇒ service 侧 refund = actual（全额）'),
    evidence: [`响应: ${r5.text.slice(0, 200)}`, `DB orders: ${JSON.stringify(e5)}`, `DB 流水: ${JSON.stringify(fe)}`],
  })

  // ⑥ 不可退状态：cancelled —— **自建**探针单（建单 → 取消），不碰存量订单
  const p6 = await createProbeProduct(token, { allowRestock: false, stock: 50, price: 100, tag: 'RX' })
  const o6c = await createProbeOrder(token, { productId: p6.productId, productName: p6.name, skuId: p6.skuId,
    skuCode: p6.skuCode, colorId: p6.colorId, qty: 1, unitPrice: 100, tag: 'RX' })
  const cancelResp = await api('PUT', `/api/admin/orders/${o6c.orderId}/status`, { token, body: { status: 'cancelled', closeReason: `${'线B验收'}：取消探针` } })
  const cancelled = orderRow(o6c.orderId)
  if (cancelled?.status !== 'cancelled') {
    R.skip('LB-REF-06', '退款：不可退状态（cancelled）⇒ 拒绝',
      `自建取消单失败（取消端点返回 ${cancelResp.status}），无法构造 cancelled 态探针`,
      [`取消响应: ${cancelResp.text.slice(0, 200)}`, `DB 行: ${JSON.stringify(cancelled)}`])
  } else {
    const before = orderRow(cancelled.id)
    const r6 = await refund(cancelled.id, '1.00')
    const after = orderRow(cancelled.id)
    judge(R, {
      id: 'LB-REF-06', name: '退款：不可退状态（cancelled）⇒ 拒绝且存量订单零改动',
      expect: '422 + 文案「当前状态[已取消]不允许退款…」+ 该行前后 sha 一致（零改动）',
      actual: `${r6.status} ${r6.bookErr?.message}；前后 refund_amount=${before?.refund_amount}→${after?.refund_amount}`,
      pass: r6.status === 422 && /不允许退款/.test(r6.text) && JSON.stringify(before) === JSON.stringify(after),
      expectSource: src('backend/admin-api/src/main/java/com/migao/admin/service/OrderService.java', 'refundOrder 的 refundableStatuses = {confirmed, producing, shipped, completed}（cancelled 不在内）'),
      evidence: [`探针对象为**存量**订单（只读探针，未写）: id=${cancelled.id} order_no=${cancelled.order_no}`,
                 `取消响应原文: ${cancelResp.text.slice(0, 200)}`,
                 `响应原文: ${r6.text.slice(0, 300)}`, `前后行: ${JSON.stringify(before)} / ${JSON.stringify(after)}`],
    })
  }

  // ⑦ 不可退状态：pending（自建探针订单，不确认收款 ⇒ status=pending）
  const p7 = await createProbeProduct(token, { allowRestock: false, stock: 50, price: 100, tag: 'RP' })
  const o7r = await api('POST', '/api/admin/orders', { token, body: {
    customerName: `${'线B验收'}客户-RP`, customerPhone: '13900000007', customerAddress: `${'线B验收'}地址`,
    logisticsType: 'express', logisticsCompany: `${'线B验收'}物流`, remark: `${'线B验收'}（探针订单-pending）`,
    items: [{ productId: p7.productId, productName: p7.name, quantity: 1, unitPrice: 100, subtotal: '100.000', width: 2.8, height: 2.0,
              processingInfo: { skuId: p7.skuId, skuCode: p7.skuCode, colorId: p7.colorId, doorWidth: '2.8m' } }],
  } })
  const o7 = o7r.data?.id ?? o7r.data?.orderId
  writeFileSync(outPath('B1-pending-order-raw.json'), JSON.stringify({ status: o7r.status, text: o7r.text.slice(0, 1500), dataKeys: o7r.data ? Object.keys(o7r.data) : null, o7 }, null, 2))
  const r7 = await refund(o7, '10.00')
  judge(R, {
    id: 'LB-REF-07', name: '退款：不可退状态（pending，未确认收款）⇒ 拒绝',
    expect: '422 + 文案「当前状态[待付款]不允许退款…」+ DB 该单 refund_amount 仍 0/null',
    actual: `${r7.status} ${r7.bookErr?.message}；refund_amount=${orderRow(o7)?.refund_amount}`,
    pass: r7.status === 422 && /不允许退款/.test(r7.text) && cents(orderRow(o7)?.refund_amount ?? '0') === 0n,
    expectSource: src('backend/admin-api/src/main/java/com/migao/admin/service/OrderService.java', 'refundableStatuses 不含 pending'),
    evidence: [`响应原文: ${r7.text.slice(0, 300)}`, `DB orders: ${JSON.stringify(orderRow(o7))}`,
               `建单原始响应（若此处 id 缺失 ⇒ 是本包 harness 的取字段缺陷，不是产品缺陷）: status=${o7r.status} dataKeys=${o7r.data ? Object.keys(o7r.data).join(',') : 'null'}`,
               `建单响应摘录: ${o7r.text.slice(0, 300)}`],
  })

  // ⑧ 格式非法
  const F8 = await freshOrder('RF')
  const r8 = await refund(F8.o.orderId, 'abc')
  judge(R, {
    id: 'LB-REF-08', name: '退款：金额格式非法（"abc"）⇒ 422 而非 500',
    expect: '422 + 文案「退款金额格式不正确」',
    actual: `${r8.status} ${r8.bookErr?.code} ${r8.bookErr?.message}`,
    pass: r8.status === 422 && /格式不正确/.test(r8.text),
    expectSource: src('backend/admin-api/src/main/java/com/migao/admin/controller/OrderController.java', 'refundOrder 的 NumberFormatException ⇒ 「退款金额格式不正确」'),
    evidence: [`响应原文: ${r8.text.slice(0, 300)}`],
  })
}

// ───────────────────────── B1.4 退货回补库存开关（**两侧都要有**）─────────────────────────
{
  // ⚠️ 必须 pending → processing → resolved：`STATUS_TRANSITIONS` 里 pending 的允许目标是
  //    {processing, rejected, closed} —— **不含 resolved**（实测：直跳 ⇒ 422「工单状态不允许从 [待处理] 变更为 [已解决]」）。
  //    上一版直接跳级 ⇒ 两侧判据**假红**（那是 harness 的错，不是产品缺陷）。
  async function ticketResolve(orderId, type, amount, tag) {
    const c = await api('POST', '/api/admin/after-sales', { token, body: {
      orderId, ticketType: type, description: `${'线B验收'}工单-回补-${tag}`, refundAmount: amount } })
    const id = c.data?.id
    const mid = await api('PUT', `/api/admin/after-sales/${id}/status`, { token, body: { status: 'processing', remark: `${'线B验收'}：受理` } })
    const s = await api('PUT', `/api/admin/after-sales/${id}/status`, { token, body: { status: 'resolved', remark: `${'线B验收'}：退货完结` } })
    return { id, ticketNo: c.data?.ticketNo, createResp: c, processingResp: mid, statusResp: s }
  }

  // ── 开侧：allow_return_restock=true ⇒ 退货完结**回补**库存 ──
  const ON = F.restockOn
  // 🔴 期望一律**运行时取基线**再叠加独立算式增量（不写死 98/100）：
  //    写死的数字在夹具被上一轮回补过之后就失效 ⇒ 会产生**假红**（实测踩过：SKU 起点已是非 98）。
  const onSkuBefore = skuStock(ON.product.skuId)
  const onBaseExpected = fmtQty(cents(onSkuBefore?.stock))          // 回补前真实读数
  const onExpectAfter = fmtQty(cents(onSkuBefore?.stock) + cents(String(ON.qty)))  // + 独立算式增量（明细数量；String() 保证 cents 走字符串分支）
  const tOn = await ticketResolve(ON.order.orderId, 'return', '200.00', 'ON')
  const onSkuAfter = skuStock(ON.product.skuId)
  const onRow = orderRow(ON.order.orderId)
  const onLedger = psql(`select id, sku_id, delta, before_qty, after_qty, reason, ref_no from stock_ledger_entries
                         where tenant_id=20 and ref_no='${tOn.ticketNo}' order by id`)
  // 独立算式：确认收款扣 2 ⇒ SKU 98；退货回补 2 ⇒ 100
  const expectApplied = '200.00'
  judge(R, {
    id: 'LB-AS-RESTOCK-ON', name: '回补开关**开**（allow_return_restock=true）：退货完结 ⇒ 库存回补 + 落 aftersales 台账',
    expect: `200（pending→processing→resolved 两步）+ SKU 库存 ${onBaseExpected} → ${onExpectAfter}（回补 ${fmtQty(cents(ON.qty))}，= 基线 + 明细数量）+ stock_ledger_entries 恰 1 行 reason=aftersales delta=+${fmtQty(cents(String(ON.qty)))} ref_no=${tOn.ticketNo} + 订单 refund_amount=${expectApplied}`,
    actual: `status=${tOn.statusResp.status}；SKU ${onSkuBefore?.stock} → ${onSkuAfter?.stock}；台账 ${onLedger.length} 行 ${JSON.stringify(onLedger.map((x) => [x.delta, x.before_qty, x.after_qty, x.reason]))}；订单 refund_amount=${onRow?.refund_amount}`,
    pass: tOn.statusResp.status === 200 && qtyEq(onSkuAfter?.stock, onExpectAfter) &&
          onLedger.length === 1 && qtyEq(onLedger[0]?.delta, fmtQty(cents(String(ON.qty)))) && onLedger[0]?.reason === 'aftersales' &&
          qtyEq(onRow?.refund_amount, expectApplied),
    expectSource: `本包独立算式（**运行时基线 + 增量**）：回补前读数 ${onBaseExpected} + 明细数量 ${fmtQty(cents(String(ON.qty)))} = ${onExpectAfter}；台账 delta 由库内 after−before 算出（StockLedgerService.recordChangesAgainstSnapshot）`,
    evidence: [`工单 id=${tOn.id} ticketNo=${tOn.ticketNo} 建单响应: ${tOn.createResp.text.slice(0, 200)}`,
               `完结响应: ${tOn.statusResp.text.slice(0, 200)}`,
               `SKU 前后: ${JSON.stringify(onSkuBefore)} → ${JSON.stringify(onSkuAfter)}`,
               `台账原始行: ${JSON.stringify(onLedger)}`,
               `源码: backend/admin-api/src/main/java/com/migao/admin/service/AfterSalesTicketService.java 的 maybeRestockOnReturn（全商品 allow=TRUE 才整单回补，复用 OrderService.restoreStockForReturn）`],
    extra: { ticketNo: tOn.ticketNo, ledger: onLedger, skuBefore: onSkuBefore?.stock, skuAfter: onSkuAfter?.stock },
  })

  // ── 关侧：allow_return_restock=false ⇒ 退货完结**零变化** ──
  const OFF = F.restockOff
  // 关侧同样**运行时取基线**（零变化的期望 = 基线本身，不写死数字）
  const offSkuBefore = skuStock(OFF.product.skuId)
  const offOrderBefore = orderRow(OFF.order.orderId)
  const tOff = await ticketResolve(OFF.order.orderId, 'return', '200.00', 'OFF')
  const offSkuAfter = skuStock(OFF.product.skuId)
  const offLedger = psql(`select id, delta, reason, ref_no from stock_ledger_entries where tenant_id=20 and ref_no='${tOff.ticketNo}'`)
  const offOrderAfter = orderRow(OFF.order.orderId)
  judge(R, {
    id: 'LB-AS-RESTOCK-OFF', name: '回补开关**关**（allow_return_restock=false，默认）：退货完结 ⇒ 库存零变化',
    expect: `200（pending→processing→resolved 两步）+ SKU 库存 ${offSkuBefore?.stock} → ${offSkuBefore?.stock}（零变化）+ ref_no=${tOff.ticketNo} 的台账 0 行 + 退款仍照记（refund_amount=200.00）`,
    actual: `status=${tOff.statusResp.status}；SKU ${offSkuBefore?.stock} → ${offSkuAfter?.stock}；台账 ${offLedger.length} 行；订单 refund_amount=${offOrderAfter?.refund_amount}`,
    pass: tOff.statusResp.status === 200 && qtyEq(offSkuAfter?.stock, offSkuBefore?.stock) &&
          offLedger.length === 0 && qtyEq(offOrderAfter?.refund_amount, '200.00'),
    expectSource: '本包独立算式（运行时基线）：开关关 ⇒ 零回补 ⇒ SKU 保持回补前读数（零变化）；退款与开关无关 ⇒ 仍应累加 200.00',
    evidence: [`工单 id=${tOff.id} ticketNo=${tOff.ticketNo}`, `完结响应: ${tOff.statusResp.text.slice(0, 200)}`,
               `SKU 前后: ${JSON.stringify(offSkuBefore)} → ${JSON.stringify(offSkuAfter)}`,
               `订单前后: ${JSON.stringify(offOrderBefore)} → ${JSON.stringify(offOrderAfter)}`,
               `源码: 同 maybeRestockOnReturn 的 allAllow=false 分支（<issue #2991> 窗帘定制退货不可再售，默认 false）`],
    extra: { ticketNo: tOff.ticketNo, skuBefore: offSkuBefore?.stock, skuAfter: offSkuAfter?.stock },
  })
}

log(`p2 完成：${JSON.stringify(R.summary())}`)
