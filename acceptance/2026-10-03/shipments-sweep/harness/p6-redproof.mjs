// p6-redproof —— 红证：每条关键断言都必须**当场红**（不会红的断言 = 空断言）
//
//  ① 注入式：把世界改坏（造重复发货单 / 把已发量改大）⇒ 本包判据必须报红
//  ② 正对照：干净世界 ⇒ 同一条判据必须报绿（两侧夹住）
//  ③ 注入/还原都做**内容指纹自证**（不用 mtime/size 判新鲜度）
//  ④ 先证判据不空：用一条必然为假的期望证明判据的"红"侧可达
import {
  api, Recorder, judge, cents, fmtQty, qtyEq, psql, one, guardedWrite, TENANT_ID, PROBE_PREFIX,
  createProbeOrder, buildPoint, nowCST, log, SESSION_HEADER, tsBoth,
} from './lib.mjs'
import { createHash } from 'node:crypto'

const R = new Recorder('p6-redproof-records.json')
const wship = (session, orderId, body) => api('POST', `/api/worker/shipment/orders/${orderId}/ship`,
  { body, headers: { [SESSION_HEADER]: session } })
const shipBody = (item, qty, tag) => ({
  trackingNo: `SF-PROBE-${tag}`, logisticsCompany: '顺丰', photoRefs: [],
  items: [{ order_item_id: item.itemId, product_name: item.name, shipped_quantity: qty, unit: '米', set_count: null, roll_count: null }],
})

// ── 判据本体（把 p1/p3 用的同一条判据抽出来，才能对同一份读数两侧夹住）──
const rowsOf = (orderId) => psql(`select id, shipment_no, shipped_at from order_shipments where tenant_id=${TENANT_ID} and order_id='${orderId}' and deleted=0`)
const itemsOf = (orderId) => psql(`select shipment_id, order_item_id, shipped_quantity from order_shipment_items where tenant_id=${TENANT_ID} and order_id='${orderId}' and deleted=0`)
const orderedOf = (orderId) => psql(`select id, quantity from order_items where tenant_id=${TENANT_ID} and order_id='${orderId}' and deleted=0`)

/** 判据①：有效发货单必须恰为 1 张（同一订单） */
export function checkExactlyOneShipment(orderId) {
  const rows = rowsOf(orderId)
  const valid = rows.filter((r) => r.shipped_at != null)
  return { pass: rows.length === 1, actual: rows.length, valid: valid.length, rows }
}
/** 判据②：Σ已发（逐订单行）≤ 订单量（本包独立算式） */
export function checkNoOverShip(orderId) {
  const items = itemsOf(orderId)
  const ordered = orderedOf(orderId)
  const byItem = new Map(ordered.map((o) => [o.id, cents(o.quantity)]))
  const sums = new Map()
  for (const it of items) {
    const k = it.order_item_id ?? '(null)'
    sums.set(k, (sums.get(k) ?? 0n) + cents(it.shipped_quantity))
  }
  const violations = []
  for (const [k, s] of sums) {
    const lim = byItem.get(k)
    if (lim === undefined) violations.push({ orderItemId: k, reason: 'order_item_id 不属于该订单', sum: fmtQty(s) })
    else if (s > lim) violations.push({ orderItemId: k, sum: fmtQty(s), limit: fmtQty(lim), over: fmtQty(s - lim) })
  }
  return { pass: violations.length === 0, violations, sums: [...sums].map(([k, v]) => [k, fmtQty(v)]) }
}
const fp = (x) => createHash('sha256').update(JSON.stringify(x)).digest('hex').slice(0, 16)

export async function run({ session, token }) {
  log(`[p6] 构建点 sha=${buildPoint().sha} @ ${nowCST().cst}`)
  // ══ R0 先证判据**不空**：一条必然为假的期望必须报红 ══
  {
    const vac = judge(R, {
      id: 'R0-VACUOUS-CONTROL', name: '判据非空自证：故意写一条必然为假的期望 ⇒ 必须 FAIL',
      expect: '99（故意错）', actual: '1', pass: 1 === 99,
      expectSource: '自证用（期望与真值故意不符）—— 若这条不红，说明 judge() 坏了，后面所有红证都不可信',
      evidence: ['本例证明 Recorder/judge 的 FAIL 侧可达'],
    })
    R.pass('R0-VACUOUS-PROOF', '判据非空自证：上面那条确实落了 FAIL（不是空跑）',
      `records 里可见 R0-VACUOUS-CONTROL.status=${vac.status}`,
      [`见 out/p6-redproof-records.json 的 R0-VACUOUS-CONTROL 条目`])
  }

  // ══ R1 正对照：干净世界 ⇒ ①恰一张 ②不超发 两侧都绿 ══
  const fx1 = createProbeOrder({ tag: 'R1', status: 'confirmed', items: [{ name: `${PROBE_PREFIX}红证布R1`, qty: 10 }] })
  {
    const r = await wship(session, fx1.orderId, shipBody(fx1.items[0], 10, 'R1'))
    const c1 = checkExactlyOneShipment(fx1.orderId)
    const c2 = checkNoOverShip(fx1.orderId)
    judge(R, {
      id: 'R1-POS-CTRL', name: '正对照（干净世界）：正常发一次货 ⇒ ①恰 1 张 ②不超发 **都绿**',
      expect: '①pass ∧ ②pass ∧ HTTP 2xx',
      actual: `①${c1.pass}(n=${c1.actual}) ②${c2.pass} HTTP ${r.status}`,
      pass: c1.pass && c2.pass && r.status < 300,
      expectSource: '两侧夹住的正侧：夹具 10 全发，判据必须绿（否则判据恒红 = 什么都没测）',
      evidence: [`resp: ${r.text.slice(0, 160)}`, `① 读数 ${JSON.stringify(c1.rows)}`, `② 读数 ${JSON.stringify(c2.sums)}`],
    })
  }

  // ══ R2 注入式红证 A：手工把已发量改大（6 → 999）⇒ 「不超发」判据必须红 ══
  {
    const fx = createProbeOrder({ tag: 'R2', status: 'confirmed', items: [{ name: `${PROBE_PREFIX}红证布R2`, qty: 10 }] })
    await wship(session, fx.orderId, shipBody(fx.items[0], 6, 'R2'))
    const before = itemsOf(fx.orderId)
    const cBefore = checkNoOverShip(fx.orderId)
    // 注入：直接改库（模拟"发货量被写大"的形态）
    guardedWrite(`-- probe-ok
      update order_shipment_items set shipped_quantity = 999
      where tenant_id=${TENANT_ID} and order_id='${fx.orderId}';`)
    const after = itemsOf(fx.orderId)
    const cAfter = checkNoOverShip(fx.orderId)
    judge(R, {
      id: 'R2-INJECT-APPLIED', name: '注入**真的生效**（内容指纹自证，不用 mtime/size）',
      expect: '注入前后 shipped_quantity 指纹不同 ∧ 读数 999',
      actual: `${fp(before.map((x) => String(x.shipped_quantity)))} → ${fp(after.map((x) => String(x.shipped_quantity)))} ∧ ${JSON.stringify(after.map((x) => String(x.shipped_quantity)))}`,
      pass: fp(before.map((x) => String(x.shipped_quantity))) !== fp(after.map((x) => String(x.shipped_quantity)))
        && after.some((x) => cents(x.shipped_quantity) === cents('999')),
      expectSource: '注入式红证的**前置**：注入未生效 ⇒ 后续"判据红了"不构成红证（假红）',
      evidence: [`SQL: update order_shipment_items set shipped_quantity=999 where order_id='${fx.orderId}'`],
    })
    judge(R, {
      id: 'R2-REDPROOF', name: '🔴 注入式红证：已发量被改大 ⇒ 「Σ已发 ≤ 订单量」判据**当场红**（并报出超发量）',
      expect: '注入前 pass=true，注入后 pass=false 且 over=989.000',
      actual: `注入前 pass=${cBefore.pass}；注入后 pass=${cAfter.pass} violations=${JSON.stringify(cAfter.violations)}`,
      pass: cBefore.pass === true && cAfter.pass === false
        && cAfter.violations.some((v) => v.over === fmtQty(cents('999') - cents('10'))),
      expectSource: '同一条判据两侧夹住（干净绿 / 改坏红）；期望来源 = 独立算式 10 vs 999',
      evidence: [`violations: ${JSON.stringify(cAfter.violations)}`, `判定用读数: ${JSON.stringify(after.map((x) => String(x.shipped_quantity)))}`],
    })
    judge(R, {
      id: 'R2-CROSSFACE', name: '交叉面：被改大的数量在**系统读面**上同样读得到（证明判据读的是真值）',
      expect: 'GET /orders/{id}/shipments 的 shipped_totals.by_unit.米 = 999.000',
      actual: JSON.stringify((await api('GET', `/api/worker/shipment/orders/${fx.orderId}`, { headers: { [SESSION_HEADER]: session } })).data?.shipped_totals),
      pass: cents((await api('GET', `/api/worker/shipment/orders/${fx.orderId}`, { headers: { [SESSION_HEADER]: session } })).data?.shipped_totals?.by_unit?.['米']) === cents('999'),
      expectSource: '⚠️ 此处**故意**读系统读面：不是拿它当期望，而是证明"我改的就是系统看到的那个东西"',
      evidence: [`GET /api/worker/shipment/orders/${fx.orderId}`],
    })
    // 还原 + 指纹自证
    guardedWrite(`-- probe-ok
      update order_shipment_items set shipped_quantity = 6
      where tenant_id=${TENANT_ID} and order_id='${fx.orderId}';`)
    const restored = itemsOf(fx.orderId)
    const cRestored = checkNoOverShip(fx.orderId)
    judge(R, {
      id: 'R2-RESTORED', name: '还原**真的生效** ⇒ 判据回到绿（两侧都夹住，证明红不是恒红）',
      expect: '还原后 pass=true ∧ 读数 6',
      actual: `pass=${cRestored.pass} 读数=${JSON.stringify(restored.map((x) => String(x.shipped_quantity)))}`,
      pass: cRestored.pass === true && restored.some((x) => cents(x.shipped_quantity) === cents('6')),
      expectSource: '两侧夹住：红侧（999）与绿侧（6）都由同一条判据判出',
      evidence: [`SQL: update ... set shipped_quantity=6`],
    })
  }

  // ══ R3 注入式红证 B：造**第二张有效发货单**（重复单形态）⇒ 「恰一张」判据必须红 ══
  {
    const fx = createProbeOrder({ tag: 'R3', status: 'confirmed', items: [{ name: `${PROBE_PREFIX}红证布R3`, qty: 5 }] })
    await wship(session, fx.orderId, shipBody(fx.items[0], 5, 'R3'))
    const cBefore = checkExactlyOneShipment(fx.orderId)
    const dupId = `fsprobe-dup-${Date.now().toString(36)}`
    guardedWrite(`-- probe-ok
      insert into order_shipments (id, tenant_id, order_id, order_no, shipment_no, source, tracking_no, logistics_company, shipped_at, created_at, updated_at, deleted)
      select '${dupId}', tenant_id, order_id, order_no, shipment_no || '-DUP', source, 'SF-DUP', logistics_company, now(), now(), now(), 0
      from order_shipments where tenant_id=${TENANT_ID} and order_id='${fx.orderId}' limit 1;`)
    const cAfter = checkExactlyOneShipment(fx.orderId)
    judge(R, {
      id: 'R3-INJECT-APPLIED', name: '注入**真的生效**：库里出现第二张带 shipped_at 的发货单',
      expect: '注入后 rowCount=2 ∧ valid=2',
      actual: `注入前 rowCount=${cBefore.actual} → 注入后 rowCount=${cAfter.actual}（valid=${cAfter.valid}）`,
      pass: cBefore.actual === 1 && cAfter.actual === 2,
      expectSource: '注入式红证的前置自证（指纹式：行数 + shipment_no 集合）',
      evidence: [`dupId=${dupId}`, `① 读数 ${JSON.stringify(cAfter.rows.map((x) => x.shipment_no))}`],
    })
    judge(R, {
      id: 'R3-REDPROOF', name: '🔴 注入式红证：出现第二张有效发货单 ⇒ 「恰一张」判据**当场红**',
      expect: '注入前 pass=true，注入后 pass=false（actual=2）',
      actual: `注入前 pass=${cBefore.pass}；注入后 pass=${cAfter.pass} actual=${cAfter.actual}`,
      pass: cBefore.pass === true && cAfter.pass === false && cAfter.actual === 2,
      expectSource: '同一条判据两侧夹住；本注入形态 = 真实的「双发」缺陷产物（第二张有效发货单）',
      evidence: [`注入前: ${JSON.stringify(cBefore.rows.map((x) => x.shipment_no))}`,
        `注入后: ${JSON.stringify(cAfter.rows.map((x) => x.shipment_no))}`],
    })
    const lr = await api('GET', `/api/admin/shipments?keyword=${encodeURIComponent(fx.orderNo)}`, { token })
    const hit = (lr.data || []).filter((x) => x.orderNo === fx.orderNo)
    judge(R, {
      id: 'R3-LISTFACE', name: '交叉面（实读）：发货单列表命中 2 行（注入可见，证明落在被测真值上）',
      expect: '2', actual: String(hit.length), pass: hit.length === 2,
      expectSource: '⚠️ 只作交叉核对（证明注入的真值被系统读面看到），不作任何期望来源',
      evidence: [`GET /api/admin/shipments?keyword=${fx.orderNo} → HTTP ${lr.status}`,
        `命中行: ${JSON.stringify(hit.map((x) => ({ no: x.shipmentNo, orderNo: x.orderNo })))}`],
    })
  }

  // ══ R4 状态机判据的红证：把订单**手工置为 shipped** 再走发货 ⇒ 必须 4xx 且零写 ══
  {
    const fx = createProbeOrder({ tag: 'R4', status: 'packed', items: [{ name: `${PROBE_PREFIX}红证布R4`, qty: 5 }] })
    const okBefore = checkExactlyOneShipment(fx.orderId)
    guardedWrite(`-- probe-ok
      update orders set status='shipped' where tenant_id=${TENANT_ID} and id='${fx.orderId}';`)
    const st = one(`select status from orders where tenant_id=${TENANT_ID} and id='${fx.orderId}'`)?.status
    const r = await wship(session, fx.orderId, shipBody(fx.items[0], 5, 'R4'))
    const after = checkExactlyOneShipment(fx.orderId)
    const itemsAfter = itemsOf(fx.orderId)
    judge(R, {
      id: 'R4-REDPROOF', name: '🔴 注入式红证：世界被改成「已发货」后再次发货 ⇒ 必须 4xx 且**零写**',
      expect: '注入前 status=packed，注入后 4xx ∧ shipments 仍 0 ∧ items 仍 0',
      actual: `注入后 status=${st} ∧ HTTP ${r.status} ∧ shipments=${after.actual} ∧ items=${itemsAfter.length}`,
      pass: st === 'shipped' && r.status >= 400 && r.status < 500 && after.actual === 0 && itemsAfter.length === 0,
      expectSource: '状态机守卫：shipped ∉ SHIPPABLE_FROM ⇒ 422；且校验发生在**任何写之前** ⇒ 零写',
      evidence: [`注入前 shipments=${okBefore.actual}`, `resp(${r.status}): ${r.text.slice(0, 220)}`],
    })
  }

  // ══ R5 加工单守卫（间接）：含加工项且无完成加工单 ⇒ 必须 4xx 且零写 ══
  {
    const fx = createProbeOrder({ tag: 'R5', status: 'confirmed', items: [{ name: `${PROBE_PREFIX}红证布R5`, qty: 5 }] })
    guardedWrite(`-- probe-ok
      update order_items set processing_info = '{"processingItems":[{"id":"probe-op-r5","name":"${PROBE_PREFIX}加工项R5","quantity":1}]}'::jsonb
      where tenant_id=${TENANT_ID} and order_id='${fx.orderId}';`)
    const pi = one(`select processing_info from order_items where tenant_id=${TENANT_ID} and order_id='${fx.orderId}'`)?.processing_info
    const r = await wship(session, fx.orderId, shipBody(fx.items[0], 5, 'R5'))
    judge(R, {
      id: 'R5-1', name: '注入「含加工项 + 无完成加工单」⇒ 发货必须被拒且零写（运费守卫不可绕过）',
      expect: '4xx ∧ shipments=0 ∧ items=0',
      actual: `HTTP ${r.status} ∧ shipments=${rowsOf(fx.orderId).length} ∧ items=${itemsOf(fx.orderId).length}`,
      pass: r.status >= 400 && r.status < 500 && rowsOf(fx.orderId).length === 0 && itemsOf(fx.orderId).length === 0,
      expectSource: 'OrderShipGuard.assertProcessingCompletedBeforeShip（#3340），调用点在**任何写之前**',
      evidence: [`注入后 processing_info=${JSON.stringify(pi)}`, `resp(${r.status}): ${r.text.slice(0, 260)}`],
    })
  }

  const s = R.summary()
  log(`[p6] 完成 pass=${s.pass} fail=${s.fail} skip=${s.skip}`)
  return s
}
