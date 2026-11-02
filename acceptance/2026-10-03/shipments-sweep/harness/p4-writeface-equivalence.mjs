// p4-writeface-equivalence —— 写后等价性：前后**字段级 diff** ⇒ 允许变化集只等于 payload 键（+ 显式声明的审计列）
// 以及：补打 / 导出 / 打印面（同一单据连打两次必须一致、不新建单据、不改数量；不存在则如实登记）
import {
  api, Recorder, judge, cents, fmtQty, psql, one, TENANT_ID, PROBE_PREFIX, createProbeOrder, buildPoint, addProcessingOrder,
  tableSnap, fieldDiff, overreach, fmtDiff, log, SESSION_HEADER, IDEM_HEADER, idemKey, nowCST,
} from './lib.mjs'
import { createHash } from 'node:crypto'

const R = new Recorder('p4-records.json')
const h = (x) => createHash('sha256').update(JSON.stringify(x)).digest('hex').slice(0, 16)

const wship = (session, orderId, body, idem) => api('POST', `/api/worker/shipment/orders/${orderId}/ship`,
  { body, headers: { [SESSION_HEADER]: session, ...(idem ? { [IDEM_HEADER]: idem } : {}) } })
const shipBody = (item, qty, tag, photoRefs = []) => ({
  trackingNo: `SF-PROBE-${tag}`, logisticsCompany: '顺丰', photoRefs,
  items: [{ order_item_id: item.itemId, product_name: item.name, shipped_quantity: qty, unit: '米', set_count: null, roll_count: null }],
})
const snapOf = (orderId) => tableSnap([
  { table: 'orders', where: `tenant_id=${TENANT_ID} and id='${orderId}'` },
  { table: 'order_items', where: `tenant_id=${TENANT_ID} and order_id='${orderId}'` },
  { table: 'order_shipments', where: `tenant_id=${TENANT_ID} and order_id='${orderId}'` },
  { table: 'order_shipment_items', where: `tenant_id=${TENANT_ID} and order_id='${orderId}'` },
  { table: 'order_logistics', where: `tenant_id=${TENANT_ID} and order_id='${orderId}'` },
  { table: 'stock_ledger_entries', where: `tenant_id=${TENANT_ID} and ref_no='${orderId}'` },
])
/** 显式声明的审计/派生态（写面必然产生的非 payload 列）——声明在此，**不静默**。 */
const AUDIT = [
  'orders.id', 'orders.updated_at', 'orders.created_at', 'orders.status', 'orders.order_no',
  'orders.tenant_id', 'orders.customer_name', 'orders.customer_phone', 'orders.total_amount',
  'orders.actual_amount', 'orders.deleted', 'orders.is_urgent',
  'order_items.id', 'order_items.updated_at', 'order_items.created_at', 'order_items.order_id',
  'order_items.product_name', 'order_items.quantity', 'order_items.unit_price', 'order_items.subtotal',
  'order_items.tenant_id', 'order_items.deleted', 'order_items.processing_info', 'order_items.product_id',
  'order_shipments.*', 'order_logistics.*', 'order_shipment_items.*', 'stock_ledger_entries.*',
]

export async function run({ session, token }) {
  log(`[p4] 构建点 sha=${buildPoint().sha} @ ${nowCST().cst}`)
  // ══ W1 工人发货写面：字段级 diff ⇒ 越界（多一处即红）══
  {
    const fx = createProbeOrder({ tag: 'W1', status: 'confirmed', items: [{ name: `${PROBE_PREFIX}灯芯绒W1`, qty: 9 }] })
    const before = snapOf(fx.orderId)
    const r = await wship(session, fx.orderId, shipBody(fx.items[0], 6, 'W1', [`https://probe.invalid/w1.jpg`]))
    const after = snapOf(fx.orderId)
    const d = fieldDiff(before, after)
    // payload 键（写面声明的键）∪ 审计列
    const payloadKeys = ['order_shipments.*', 'order_shipments.tracking_no', 'order_shipments.logistics_company',
      'order_shipments.photo_refs', 'order_shipments.source', 'order_shipments.shipment_no', 'order_shipments.order_no',
      'order_shipment_items.*', 'order_logistics.*', 'orders.status']
    const over = overreach(d, [...payloadKeys, ...AUDIT])
    judge(R, {
      id: 'W1-1', name: '发货写面：HTTP 成功（前置）', expect: '2xx', actual: `HTTP ${r.status}`,
      pass: r.status < 300, expectSource: 'confirmed ∈ SHIPPABLE_FROM，body 完整',
      evidence: [`resp: ${r.text.slice(0, 200)}`],
    })
    judge(R, {
      id: 'W1-2', name: '🔴 写后等价性：变化集 ⊆ payload 键 ∪ 显式声明审计列（多一处即红）',
      expect: '越界 0 处', actual: `越界 ${over.length} 处 / 总变化 ${d.length} 处`,
      pass: over.length === 0,
      expectSource: '允许集 = 本包声明的 payload 键 ∪ AUDIT（订单状态/新建发货单与明细/物流/时间戳）；其余一律越界',
      evidence: [`越界明细: ${JSON.stringify(fmtDiff(over))}`,
        `全部变化(表.字段去重): ${JSON.stringify([...new Set(d.map((x) => `${x.table}.${x.field}`))])}`],
    })
    judge(R, {
      id: 'W1-3', name: '未发货的订单行数量不被写面改动（orders/order_items 的业务列零变化）',
      expect: 'order_items.quantity 无变化 ∧ orders 仅 status/updated_at 变化',
      actual: JSON.stringify([...new Set(d.filter((x) => x.table === 'orders' || x.table === 'order_items').map((x) => `${x.table}.${x.field}`))]),
      pass: d.filter((x) => (x.table === 'orders' && x.field !== 'status' && x.field !== 'updated_at')
        || (x.table === 'order_items' && x.field !== 'updated_at')).length === 0,
      expectSource: '发货是**记录事实**，不得改订单/订单行内容（payload 不含这些键）',
      evidence: [`diff: ${JSON.stringify(fmtDiff(d.filter((x) => (x.table === 'orders' || x.table === 'order_items'))))}`],
    })
  }

  // ══ W2 幂等重放写面的等价性：payload**不含**的字段不得被第二次请求改动 ══
  {
    const fx = createProbeOrder({ tag: 'W2', status: 'confirmed', items: [{ name: `${PROBE_PREFIX}灯芯绒W2`, qty: 9 }] })
    const key = idemKey('W2')
    const body1 = shipBody(fx.items[0], 6, 'W2', ['https://probe.invalid/w2.jpg'])
    body1.trackingNo = 'SF-FIRST-0001'
    const r1 = await wship(session, fx.orderId, body1, key)
    const mid = snapOf(fx.orderId)
    // 同键重放，payload **故意不同**（改写运单号/数量）⇒ 不得生效
    const body2 = shipBody(fx.items[0], 2, 'W2b', ['https://probe.invalid/OTHER.jpg'])
    body2.trackingNo = 'SF-SECOND-9999'
    const r2 = await wship(session, fx.orderId, body2, key)
    const end = snapOf(fx.orderId)
    const d = fieldDiff(mid, end)
    judge(R, {
      id: 'W2-1', name: '同幂等键 + **不同 payload** ⇒ 重放结果为首次快照（运单号/数量均不变）',
      expect: 'tracking_no=SF-FIRST-0001 ∧ Σ=6.000 ∧ diff=0 处',
      actual: `tracking_no=${one(`select tracking_no from order_shipments where tenant_id=${TENANT_ID} and order_id='${fx.orderId}'`)?.tracking_no} ∧ diff=${d.length} 处`,
      pass: d.length === 0
        && one(`select tracking_no from order_shipments where tenant_id=${TENANT_ID} and order_id='${fx.orderId}'`)?.tracking_no === 'SF-FIRST-0001',
      expectSource: '幂等语义：同键 = 回放首次结果，**不得**让第二次 payload 生效（否则改写发货事实）',
      evidence: [`R1(${r1.status}): ${r1.text.slice(0, 160)}`, `R2(${r2.status}) replayed=${r2.data?.replayed}: ${r2.text.slice(0, 200)}`,
        `SQL: select tracking_no, shipped_at from order_shipments → ${JSON.stringify(one(`select tracking_no, shipped_at from order_shipments where tenant_id=${TENANT_ID} and order_id='${fx.orderId}'`))}`,
        `diff: ${JSON.stringify(fmtDiff(d))}`],
    })
  }

  // ══ P1 补打：同一单据连读/连打两次内容一致、不新建单据、不改数量 ══
  {
    const fx = createProbeOrder({ tag: 'P1', status: 'confirmed', items: [{ name: `${PROBE_PREFIX}灯芯绒P1`, qty: 9 }] })
    // 先补一张加工单（否则 production /print 按 order_id 找不到加工单 → 404；读面/补打数据源不受影响）
    addProcessingOrder(fx.orderId, { status: 'cancelled' })
    await wship(session, fx.orderId, shipBody(fx.items[0], 9, 'P1'))
    const snapBefore = snapOf(fx.orderId)

    // 补打页的数据源（前端 shipments/page.tsx：取订单 → ShipmentDoc order+logistics）
    const o1 = await api('GET', `/api/admin/orders/${fx.orderId}`, { token })
    const o2 = await api('GET', `/api/admin/orders/${fx.orderId}`, { token })
    const s1 = await api('GET', `/api/admin/orders/${fx.orderId}/shipments`, { token })
    const s2 = await api('GET', `/api/admin/orders/${fx.orderId}/shipments`, { token })
    const pc0 = one(`select coalesce(print_count,0) c from processing_orders where tenant_id=${TENANT_ID} and order_id='${fx.orderId}'`)?.c
    const p1resp = await api('POST', `/api/admin/production/orders/${fx.orderId}/print`, { token })
    const pc1 = one(`select coalesce(print_count,0) c from processing_orders where tenant_id=${TENANT_ID} and order_id='${fx.orderId}'`)?.c
    const p2resp = await api('POST', `/api/admin/production/orders/${fx.orderId}/print`, { token })
    const pc2 = one(`select coalesce(print_count,0) c from processing_orders where tenant_id=${TENANT_ID} and order_id='${fx.orderId}'`)?.c
    const snapAfter = snapOf(fx.orderId)
    const d = fieldDiff(snapBefore, snapAfter)

    // 纸面数据源归一化（去掉时间/版本噪声列）
    const canon = (o) => {
      const x = JSON.parse(JSON.stringify(o))
      delete x?.requestId; delete x?.timestamp
      return x
    }
    judge(R, {
      id: 'P1-1', name: '补打数据源（订单 + 单据读面）：连读两次逐字段一致（补打纸面内容稳定）',
      expect: `hash(o1)==hash(o2) ∧ hash(s1)==hash(s2)`,
      actual: `o ${h(canon(o1.json))}/${h(canon(o2.json))} ∧ s ${h(canon(s1.json))}/${h(canon(s2.json))}`,
      pass: h(canon(o1.json)) === h(canon(o2.json)) && h(canon(s1.json)) === h(canon(s2.json)),
      expectSource: '前端补打路径 = GET /orders/{id}（订单）+ 该订单的发货单读面；两次必须逐字段一致（否则「同一单据两次补打内容不同」= 缺陷）',
      evidence: [`GET /api/admin/orders/${fx.orderId} ×2`, `GET /api/admin/orders/${fx.orderId}/shipments ×2`],
    })
    judge(R, {
      id: 'P1-2', name: '打印计数端点（production /print）连打两次：不新建单据、不改数量',
      expect: 'shipments=1 ∧ Σ=9.000 ∧ 单据行 diff 仅 orders.updated_at',
      actual: `shipments=${psql(`select id from order_shipments where tenant_id=${TENANT_ID} and order_id='${fx.orderId}'`).length} ∧ 变化列=${JSON.stringify([...new Set(d.map((x) => `${x.table}.${x.field}`))])}`,
      pass: psql(`select id from order_shipments where tenant_id=${TENANT_ID} and order_id='${fx.orderId}'`).length === 1
        && d.every((x) => x.table === 'orders'),
      expectSource: '打印是**读计数**动作（recordPrint 只写 print_count）⇒ 不得触碰发货单/明细',
      evidence: [`print #1(${p1resp.status}): ${p1resp.text.slice(0, 160)}`, `print #2(${p2resp.status}): ${p2resp.text.slice(0, 160)}`,
        `diff: ${JSON.stringify(fmtDiff(d))}`],
    })
    judge(R, {
      id: 'P1-3', name: '补打**不改已发数量**（Σ 前后一致，独立算式）',
      expect: '9.000', actual: fmtQty(psql(`select shipped_quantity from order_shipment_items where tenant_id=${TENANT_ID} and order_id='${fx.orderId}'`).reduce((a, x) => a + cents(x.shipped_quantity), 0n)),
      pass: psql(`select shipped_quantity from order_shipment_items where tenant_id=${TENANT_ID} and order_id='${fx.orderId}'`).reduce((a, x) => a + cents(x.shipped_quantity), 0n) === cents('9'),
      expectSource: '独立算式：订单量 9（夹具给定）；补打不得改动实发',
      evidence: [`SQL: select shipped_quantity from order_shipment_items where order_id='${fx.orderId}'`],
    })
    judge(R, {
      id: 'P1-4', name: '打印次数确实递增（证明这个面**真的被调用**，不是空跑；读数直连 RDS）',
      expect: `print_count: ${pc0} → ${pc0 == null ? '?' : pc0 + 1} → ${pc0 == null ? '?' : pc0 + 2}`,
      actual: `print_count: ${pc0} → ${pc1} → ${pc2}（HTTP ${p1resp.status}/${p2resp.status}）`,
      pass: pc0 != null && Number(pc1) === Number(pc0) + 1 && Number(pc2) === Number(pc0) + 2,
      expectSource: 'recordPrint 每次 +1（issue #4202 的 print_count 唯一写方）⇒ 两次调用必须 +2',
      evidence: [`SQL: select print_count from processing_orders where order_id='${fx.orderId}' → ${pc0}/${pc1}/${pc2}`,
        `print #1: ${p1resp.text.slice(0, 140)}`, `print #2: ${p2resp.text.slice(0, 140)}`],
    })
  }

  // ══ P2 导出面：不存在则如实登记（不许写成"通过"）══
  {
    const paths = [
      ['GET', `/api/admin/shipments/export`],
      ['GET', `/api/admin/shipments?format=csv`],
      ['GET', `/api/admin/orders/${'X'}/shipments/export`],
    ]
    const results = []
    for (const [m, p] of paths) {
      const r = await api(m, p, { token })
      results.push({ path: p, status: r.status, ct: r.text.slice(0, 60) })
    }
    R.skip('P2-EXPORT', '发货单**导出**面：不存在（如实登记，不写成通过）',
      `本包枚举到的发货相关端点里无任何 export；三条候选路径读数 = ${JSON.stringify(results)}（404/405 即不存在）`)
  }

  const s = R.summary()
  log(`[p4] 完成 pass=${s.pass} fail=${s.fail} skip=${s.skip}`)
  return s
}
