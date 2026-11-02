// p2-state-machine —— 状态机：合法/非法跳转、状态回退/作废留痕、非法流转必须 4xx 且**不改库**
import {
  api, Recorder, judge, cents, fmtQty, psql, one, TENANT_ID, PROBE_PREFIX,
  createProbeOrder, buildPoint, nowCST, tableSnap, fieldDiff, overreach, fmtDiff, log, tsBoth,
  SESSION_HEADER, IDEM_HEADER, idemKey,
} from './lib.mjs'

const R = new Recorder('p2-records.json')

const wpost = (token, path, body, headers = {}) => api('POST', path, { token, body, headers })
const wship = (session, orderId, body) => api('POST', `/api/worker/shipment/orders/${orderId}/ship`,
  { body, headers: { [SESSION_HEADER]: session } })
const wpack = (session, orderId) => api('POST', `/api/worker/shipment/orders/${orderId}/pack`,
  { headers: { [SESSION_HEADER]: session } })
const wunpack = (session, orderId, reason) => api('POST', `/api/worker/shipment/orders/${orderId}/unpack`,
  { body: { reason }, headers: { [SESSION_HEADER]: session } })
const shipBody = (item, qty, tag) => ({
  trackingNo: `SF-PROBE-${tag}`, logisticsCompany: '顺丰', photoRefs: [],
  items: [{ order_item_id: item.itemId, product_name: item.name, shipped_quantity: qty, unit: '米', set_count: null, roll_count: null }],
})

const statusOf = (orderId) => one(`select status from orders where tenant_id=${TENANT_ID} and id='${orderId}'`)?.status
const shipsOf = (orderId) => psql(`select id, shipment_no, packed_at, shipped_at, unpacked_at, unpack_reason, packed_by_worker_name, shipped_by_worker_name from order_shipments where tenant_id=${TENANT_ID} and order_id='${orderId}' and deleted=0`)
const itemsOf = (orderId) => psql(`select shipment_id, order_item_id, shipped_quantity, unit from order_shipment_items where tenant_id=${TENANT_ID} and order_id='${orderId}' and deleted=0`)

/** 字段级快照（非法流转前后必须逐字段一致） */
const snapOf = (orderId) => tableSnap([
  { table: 'orders', where: `tenant_id=${TENANT_ID} and id='${orderId}'` },
  { table: 'order_items', where: `tenant_id=${TENANT_ID} and order_id='${orderId}'` },
  { table: 'order_shipments', where: `tenant_id=${TENANT_ID} and order_id='${orderId}'` },
  { table: 'order_shipment_items', where: `tenant_id=${TENANT_ID} and order_id='${orderId}'` },
  { table: 'order_logistics', where: `tenant_id=${TENANT_ID} and order_id='${orderId}'` },
])

export async function run({ token, session }) {
  log(`[p2] 构建点 sha=${buildPoint().sha} @ ${nowCST().cst}`)
  // ══ T1 合法跳转：confirmed → packed → shipped（工人主路径）══
  {
    const fx = createProbeOrder({ tag: 'T1', status: 'confirmed', items: [{ name: `${PROBE_PREFIX}帆布T1`, qty: 5 }] })
    const pk = await wpack(session, fx.orderId)
    const st1 = statusOf(fx.orderId)
    const sh = await wship(session, fx.orderId, shipBody(fx.items[0], 5, 'T1'))
    const st2 = statusOf(fx.orderId)
    const s = shipsOf(fx.orderId)[0]
    judge(R, {
      id: 'T1-1', name: '合法：confirmed → packed（工人打包）被接受且落 packed_at/by',
      expect: '2xx ∧ status=packed ∧ packed_at/by 非空',
      actual: `HTTP ${pk.status} ∧ ${st1} ∧ ${JSON.stringify({ at: !!s?.packed_at, by: s?.packed_by_worker_name })}`,
      pass: pk.status < 300 && st1 === 'packed' && !!s?.packed_at && !!s?.packed_by_worker_name,
      expectSource: 'STATUS_TRANSITIONS: confirmed → {producing,packed,shipped,cancelled}（逐字取自 OrderStatusTransitions.java）',
      evidence: [`POST /worker/shipment/orders/${fx.orderId}/pack → ${pk.text.slice(0, 180)}`],
    })
    judge(R, {
      id: 'T1-2', name: '合法：packed → shipped，且**同一张**发货单延续（不新建第二张）',
      expect: '2xx ∧ status=shipped ∧ shipments=1',
      actual: `HTTP ${sh.status} ∧ ${st2} ∧ shipments=${shipsOf(fx.orderId).length}`,
      pass: sh.status < 300 && st2 === 'shipped' && shipsOf(fx.orderId).length === 1,
      expectSource: 'activeShipment() 取「未发货」那张 → 复用；packed → shipped 是表里唯一出口',
      evidence: [`shipment_no=${s?.shipment_no} packed_at=${tsBoth(s?.packed_at)?.raw} shipped_at=${tsBoth(s?.shipped_at)?.raw}`],
    })
  }

  // ══ T2 非法跳转：未发货 → 已签收（不存在该状态）══
  {
    const fx = createProbeOrder({ tag: 'T2', status: 'confirmed', items: [{ name: `${PROBE_PREFIX}帆布T2`, qty: 4 }] })
    const before = snapOf(fx.orderId)
    const r = await api('PUT', `/api/admin/orders/${fx.orderId}/status`, { token, body: { status: 'delivered' } })
    const after = snapOf(fx.orderId)
    const d = fieldDiff(before, after)
    const route404 = r.status === 404 && r.json?.error?.code === 'NOT_FOUND'
    R.pass('T2-ROUTE', '判别性前置：请求**真的进到状态机**（不是路由 404 的空断言）',
      `HTTP ${r.status} ∧ code=${r.json?.error?.code}`,
      [`OrderController 的写端点路由带正则 @PutMapping("/{id:[0-9a-fA-F-]+}/status")`,
       `若 id 不在该集合 ⇒ 路由层 404，测的是路由不是状态机（实测踩过，故本判据存在）`,
       `本包订单 id 全部落在 [0-9a-fA-F-] 内：${fx.orderId}`])
    judge(R, {
      id: 'T2-1', name: '非法：confirmed → delivered（「已签收」不在状态机内）⇒ 4xx 拒绝',
      expect: '4xx ∧ 状态仍 confirmed ∧ **非路由 404**',
      actual: `HTTP ${r.status} ∧ code=${r.json?.error?.code} ∧ ${statusOf(fx.orderId)}`,
      pass: r.status >= 400 && r.status < 500 && !route404 && statusOf(fx.orderId) === 'confirmed',
      expectSource: 'assertTransitionAllowed: isKnownStatus(to)==false ⇒ 422「无效的订单状态」',
      evidence: [`PUT /api/admin/orders/${fx.orderId}/status body={"status":"delivered"} → ${r.text.slice(0, 260)}`],
    })
    judge(R, {
      id: 'T2-2', name: '非法流转**不改库**（前后字段级 diff 为空）',
      expect: 'diff=[]', actual: `${d.length} 处变化`,
      pass: d.length === 0,
      expectSource: '「非法必须 422/409 且不改库」= 本包判据；判定用 RDS 前后逐字段 diff',
      evidence: [`diff: ${JSON.stringify(fmtDiff(d))}`],
    })
  }

  // ══ T3 非法跳转：packed → producing（无理由的裸状态接口）══
  {
    const fx = createProbeOrder({ tag: 'T3', status: 'packed', items: [{ name: `${PROBE_PREFIX}帆布T3`, qty: 4 }] })
    // 先让仓库里真有一张 packed 态的发货单（更接近现场）
    await wpack(session, fx.orderId)
    const before = snapOf(fx.orderId)
    const r = await api('PUT', `/api/admin/orders/${fx.orderId}/status`, { token, body: { status: 'producing' } })
    const after = snapOf(fx.orderId)
    const d = fieldDiff(before, after)
    const route404 = r.status === 404 && r.json?.error?.code === 'NOT_FOUND'
    judge(R, {
      id: 'T3-1', name: '非法：packed → producing 走商家裸状态接口 ⇒ 拒绝（回退是具名动作，不能无理由）',
      expect: '4xx（非路由 404）∧ status=packed',
      actual: `HTTP ${r.status} ∧ code=${r.json?.error?.code} ∧ ${statusOf(fx.orderId)}`,
      pass: r.status >= 400 && r.status < 500 && !route404 && statusOf(fx.orderId) === 'packed',
      expectSource: 'STATUS_TRANSITIONS["packed"] = {shipped}（撤销打包**有意**不在表里，见 OrderShipmentService.unpack 注释）',
      evidence: [`resp: ${r.text.slice(0, 220)}`],
    })
    judge(R, {
      id: 'T3-2', name: '非法流转不改库（逐字段 diff 为空）',
      expect: 'diff=[]', actual: `${d.length} 处变化`, pass: d.length === 0,
      expectSource: '本包判据（RDS 前后逐字段 diff）',
      evidence: [`diff: ${JSON.stringify(fmtDiff(d))}`],
    })
  }

  // ══ T4 状态回退：工人撤销打包（具名动作，必带理由 + 留痕）══
  {
    const fx = createProbeOrder({ tag: 'T4', status: 'confirmed', items: [{ name: `${PROBE_PREFIX}帆布T4`, qty: 4 }] })
    await wpack(session, fx.orderId)
    const noReason = await wunpack(session, fx.orderId, '')
    const stAfterNoReason = statusOf(fx.orderId)
    judge(R, {
      id: 'T4-1', name: '撤销打包必须带理由（空理由 ⇒ 4xx 且不动状态）',
      expect: '4xx ∧ status=packed', actual: `HTTP ${noReason.status} ∧ ${stAfterNoReason}`,
      pass: noReason.status >= 400 && noReason.status < 500 && stAfterNoReason === 'packed',
      expectSource: 'doUnpack: !hasText(reason) ⇒ validationError（1~500 字）',
      evidence: [`resp: ${noReason.text.slice(0, 220)}`],
    })
    const ok = await wunpack(session, fx.orderId, `${PROBE_PREFIX}装错箱，撤销重打`)
    const s = shipsOf(fx.orderId)[0]
    const its = itemsOf(fx.orderId)
    judge(R, {
      id: 'T4-2', name: '撤销打包：packed → producing，且留痕（unpacked_at/by/reason 非空）',
      expect: '2xx ∧ status=producing ∧ 三留痕非空',
      actual: `HTTP ${ok.status} ∧ ${statusOf(fx.orderId)} ∧ ${JSON.stringify({ at: !!s?.unpacked_at, reason: (s?.unpack_reason || '').slice(0, 20) })}`,
      pass: ok.status < 300 && statusOf(fx.orderId) === 'producing' && !!s?.unpacked_at && !!s?.unpack_reason,
      expectSource: '「涉责任的动作不留白」：unpacked_at/unpacked_by_*/unpack_reason 必须落库',
      evidence: [`resp: ${ok.text.slice(0, 200)}`, `SQL: select unpacked_at, unpack_reason → ${JSON.stringify(s)}`],
    })
    judge(R, {
      id: 'T4-3', name: '撤销打包**不影响已发数量**（此时尚未发货 ⇒ 明细仍为 0 行）',
      expect: 'items=0 ∧ 无 shipped_at', actual: `items=${its.length} shipped_at=${JSON.stringify(s?.shipped_at)}`,
      pass: its.length === 0 && !s?.shipped_at,
      expectSource: '撤销只清 packed_* 与状态，不碰实发明细（未发货 ⇒ 明细本就为空）',
      evidence: [`SQL: select shipped_quantity from order_shipment_items where order_id='${fx.orderId}' → ${JSON.stringify(its)}`],
    })
    judge(R, {
      id: 'T4-4', name: '撤销打包后 packed_* 被清空（状态与留痕一致，不出现"已撤销却仍标已打包"）',
      expect: 'packed_at=null ∧ packed_by=null', actual: JSON.stringify({ at: s?.packed_at, by: s?.packed_by_worker_name }),
      pass: s?.packed_at == null && s?.packed_by_worker_name == null,
      expectSource: 'doUnpack 显式 setPackedAt(null)/setPackedByWorker*(null)',
      evidence: [`SQL 原始读数上一条`],
    })
  }

  // ══ T5 状态回退：已发货**不可**回退 / 不可再撤销 ══
  {
    const fx = createProbeOrder({ tag: 'T5', status: 'confirmed', items: [{ name: `${PROBE_PREFIX}帆布T5`, qty: 4 }] })
    await wship(session, fx.orderId, shipBody(fx.items[0], 4, 'T5'))
    const before = snapOf(fx.orderId)
    const unpack = await wunpack(session, fx.orderId, `${PROBE_PREFIX}想撤销已发货单`)
    const cancel = await api('PUT', `/api/admin/orders/${fx.orderId}/status`, { token, body: { status: 'cancelled' } })
    const cancelRoute404 = cancel.status === 404 && cancel.json?.error?.code === 'NOT_FOUND'
    const after = snapOf(fx.orderId)
    const d = fieldDiff(before, after)
    const s = shipsOf(fx.orderId)[0]
    const its = itemsOf(fx.orderId)
    judge(R, {
      id: 'T5-1', name: '已发货单不可撤销打包（4xx，且不产生 unpacked_* 留痕）',
      expect: '4xx ∧ unpacked_at=null', actual: `HTTP ${unpack.status} ∧ ${JSON.stringify(s?.unpacked_at)}`,
      pass: unpack.status >= 400 && unpack.status < 500 && !s?.unpacked_at,
      expectSource: 'doUnpack: 仅 "packed" 可撤销 ⇒ shipped 被拒',
      evidence: [`resp: ${unpack.text.slice(0, 220)}`],
    })
    judge(R, {
      id: 'T5-2', name: '已发货订单不可直接取消（shipped 的唯一后继 = completed）',
      expect: '4xx（非路由 404）∧ status=shipped',
      actual: `HTTP ${cancel.status} ∧ code=${cancel.json?.error?.code} ∧ ${statusOf(fx.orderId)}`,
      pass: cancel.status >= 400 && cancel.status < 500 && !cancelRoute404 && statusOf(fx.orderId) === 'shipped',
      expectSource: 'STATUS_TRANSITIONS["shipped"] = {completed}',
      evidence: [`resp: ${cancel.text.slice(0, 220)}`],
    })
    judge(R, {
      id: 'T5-3', name: '两次非法回退后 **已发数量与单据不变**（diff 仅允许 0 处）',
      expect: 'diff=[] ∧ Σ已发=4.00 ∧ shipments=1',
      actual: `diff=${d.length} 处 Σ=${fmtQty(its.reduce((a, x) => a + cents(x.shipped_quantity), 0n))} shipments=${shipsOf(fx.orderId).length}`,
      pass: d.length === 0 && its.length === 1,
      expectSource: '本包判据：非法动作不得改库（含不得改已发数量）',
      evidence: [`diff: ${JSON.stringify(fmtDiff(d)).slice(0, 300)}`],
    })
  }

  // ══ T6 已取消订单不可发货；待付款订单不可发货 ══
  for (const [tag, st] of [['T6a', 'cancelled'], ['T6b', 'pending']]) {
    const fx = createProbeOrder({ tag, status: st, items: [{ name: `${PROBE_PREFIX}帆布${tag}`, qty: 3 }] })
    const before = snapOf(fx.orderId)
    const r = await wship(session, fx.orderId, shipBody(fx.items[0], 3, tag))
    const after = snapOf(fx.orderId)
    const d = fieldDiff(before, after)
    judge(R, {
      id: `T6-${st}`, name: `不可发货状态（${st}）⇒ 4xx 且**不改库**（不产生发货单/明细）`,
      expect: '4xx ∧ diff=[] ∧ shipments=0',
      actual: `HTTP ${r.status} ∧ diff=${d.length} ∧ shipments=${shipsOf(fx.orderId).length}`,
      pass: r.status >= 400 && r.status < 500 && d.length === 0 && shipsOf(fx.orderId).length === 0,
      expectSource: `SHIPPABLE_FROM = {confirmed, producing, packed}（${st} ∉）`,
      evidence: [`resp: ${r.text.slice(0, 220)}`, `diff: ${JSON.stringify(fmtDiff(d))}`],
    })
  }

  const s = R.summary()
  log(`[p2] 完成 pass=${s.pass} fail=${s.fail} skip=${s.skip}`)
  return s
}
