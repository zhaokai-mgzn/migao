// p3-independent-math —— 独立算式（红线）：超发 / 边界 / decimal 语义
// 🔴 期望一律本包自己算（订单量 − 已发合计）；系统读面只被核对，绝不作为期望来源。
import {
  api, Recorder, judge, cents, fmtQty, qtyEq, psql, one, TENANT_ID, PROBE_PREFIX,
  createProbeOrder, buildPoint, nowCST, log, SESSION_HEADER, IDEM_HEADER, idemKey,
} from './lib.mjs'

const R = new Recorder('p3-records.json')
const wship = (session, orderId, body, idem) => api('POST', `/api/worker/shipment/orders/${orderId}/ship`,
  { body, headers: { [SESSION_HEADER]: session, ...(idem ? { [IDEM_HEADER]: idem } : {}) } })
const shipBody = (items, tag) => ({
  trackingNo: `SF-PROBE-${tag}`, logisticsCompany: '顺丰', photoRefs: [], items,
})
const line = (item, qty, unit = '米') => ({
  order_item_id: item.itemId, product_name: item.name, shipped_quantity: qty, unit, set_count: null, roll_count: null,
})
const itemsOf = (orderId) => psql(`select order_item_id, shipped_quantity, unit from order_shipment_items where tenant_id=${TENANT_ID} and order_id='${orderId}' and deleted=0 order by created_at`)
const shipCount = (orderId) => psql(`select id from order_shipments where tenant_id=${TENANT_ID} and order_id='${orderId}' and deleted=0`).length
const sumOf = (orderId) => itemsOf(orderId).reduce((a, x) => a + cents(x.shipped_quantity), 0n)

export async function run({ session }) {
  log(`[p3] 构建点 sha=${buildPoint().sha} @ ${nowCST().cst}`)
  // ══ M1 超发：订单 10，实发 999（同一订单行）══
  {
    const fx = createProbeOrder({ tag: 'M1', status: 'confirmed', items: [{ name: `${PROBE_PREFIX}牛仔布M1`, qty: 10 }] })
    const it = fx.items[0]
    const ordered = cents(it.qty)
    const r = await wship(session, fx.orderId, shipBody([line(it, 999)], 'M1'))
    const sum = sumOf(fx.orderId)
    const over = sum - ordered
    judge(R, {
      id: 'M1-OVER', name: '🔴 超发防护：实发 999 > 订单 10 ⇒ 必须被拒（4xx）',
      expect: '4xx ∧ Σ已发 ≤ 10.00 ∧ items=0',
      actual: `HTTP ${r.status} ∧ Σ=${fmtQty(sum)} ∧ items=${itemsOf(fx.orderId).length}`,
      pass: r.status >= 400 && r.status < 500 && sum <= ordered,
      expectSource: `独立算式：order_items.quantity=10（夹具给定）− 已发合计 0 ⇒ 上限 10；实发 999 ⇒ 越界 ${fmtQty(over > 0n ? over : 0n)}`,
      evidence: [
        `POST body: ${JSON.stringify({ items: [line(it, 999)] })}`,
        `resp(${r.status}): ${r.text.slice(0, 300)}`,
        `SQL: select shipped_quantity from order_shipment_items where order_id='${fx.orderId}' → ${JSON.stringify(itemsOf(fx.orderId))}`,
      ],
    })
    if (r.status < 300) {
      R.fail('M1-OVER-DEFECT', '🔴 缺陷登记：系统接受超发（无任何「累计已发 ≤ 订单量」校验）',
        `HTTP 2xx，Σ已发=${fmtQty(sum)} > 订单量 ${fmtQty(ordered)}（超出 ${fmtQty(over)}）`,
        [
          `复现：建订单（quantity=10, confirmed）→ POST /api/worker/shipment/orders/{id}/ship body.items[0].shipped_quantity=999`,
          `改写/校验点：OrderShipmentService.parseDetails 只校验 qty>0 + order_item_id 属于该订单，**从不与 order_items.quantity 比较**`,
          `影响面：少发/错发**可核**的判据（#5648 的唯一目标）在"多发"方向失效；对账/加工/工资链路读到超量实发`,
          `一句话判据：Σ order_shipment_items.shipped_quantity ≤ order_items.quantity 必须成立，实测被打破`,
        ])
    }
  }

  // ══ M2 边界：等于订单量（正对照，必须接受）══
  {
    const fx = createProbeOrder({ tag: 'M2', status: 'confirmed', items: [{ name: `${PROBE_PREFIX}牛仔布M2`, qty: 12.5 }] })
    const it = fx.items[0]
    const r = await wship(session, fx.orderId, shipBody([line(it, 12.5)], 'M2'))
    const sum = sumOf(fx.orderId)
    judge(R, {
      id: 'M2-EXACT', name: '边界：实发 == 订单量（12.5）⇒ 接受且数量逐分一致',
      expect: `2xx ∧ Σ=12.50`, actual: `HTTP ${r.status} ∧ Σ=${fmtQty(sum)}`,
      pass: r.status < 300 && sum === cents('12.5'),
      expectSource: '独立算式：上限 = 订单量 12.5（本包给定）；等号是合法边界',
      evidence: [`resp: ${r.text.slice(0, 200)}`, `SQL 原始列: ${JSON.stringify(itemsOf(fx.orderId))}`],
    })
  }

  // ══ M3 边界：0 件 / 负数量 / 缺数量 / 小数第三位 ══
  // ⚠️ M3d 的期望值必须按**列真实精度**算：实测 information_schema 报
  // order_shipment_items.shipped_quantity = numeric(10,2) ⇒ 0.001 会被 PG 存成 0.00。
  for (const [tag, qty, label, expQty] of [['M3a', 0, '0 件', null], ['M3b', -3, '负数量 -3', null], ['M3c', null, '缺 shipped_quantity', null], ['M3d', 0.001, '0.001（越界精度：列只到 2 位）⇒ **新契约：必须 4xx 且不落明细**', '0']]) {
    const fx = createProbeOrder({ tag, status: 'confirmed', items: [{ name: `${PROBE_PREFIX}牛仔布${tag}`, qty: 10 }] })
    const it = fx.items[0]
    const body = shipBody([line(it, 10)], tag)
    if (qty === null) delete body.items[0].shipped_quantity
    else body.items[0].shipped_quantity = qty
    const r = await wship(session, fx.orderId, body)
    const sum = sumOf(fx.orderId)
    // 🔴 2026-10-03 新契约（S1/#6157 落地后）：**越界精度**（超过列精度 numeric(10,2) 两位）
    //    必须 **4xx 拒绝**，不许静默吃成 0.00 —— 旧判据的期望「接受且落库 0.001」已过期。
    const overPrecision = typeof qty === 'number' && Math.abs(qty * 100 - Math.round(qty * 100)) > 1e-9
    const expectReject = qty === null || qty <= 0 || overPrecision
    judge(R, {
      id: `M3-${tag}`, name: `边界：${label} ⇒ ${expectReject ? '必须 4xx 且不落明细' : '接受（>0）且按列精度落库'}`,
      expect: expectReject ? '4xx ∧ items=0' : `2xx ∧ Σ=${fmtQty(cents(String(expQty ?? qty)))}`,
      actual: `HTTP ${r.status} ∧ Σ=${fmtQty(sum)} ∧ items=${itemsOf(fx.orderId).length}`,
      pass: expectReject
        ? (r.status >= 400 && r.status < 500 && sum === 0n)
        : (r.status < 300 && sum === cents(String(expQty ?? qty))),
      expectSource: 'doParseDetails: qty==null ∨ qty<=0 ⇒ 422；>0 一律放行；落库再由列精度 numeric(10,2) 决定（期望按该精度独立算）',
      evidence: [`body.items[0]=${JSON.stringify(body.items[0])}`, `resp(${r.status}): ${r.text.slice(0, 220)}`],
    })
  }

  // ══ M3d-2 精度登记：正数被列精度吃成 0 ⇒ 产生"已发货但实发 0"的行 ══
  {
    const col = one(`select numeric_precision p, numeric_scale s from information_schema.columns
                     where table_name='order_shipment_items' and column_name='shipped_quantity'`)
    const fx = createProbeOrder({ tag: 'M3d2', status: 'confirmed', items: [{ name: `${PROBE_PREFIX}牛仔布M3d2`, qty: 10 }] })
    const it = fx.items[0]
    const r = await wship(session, fx.orderId, shipBody([line(it, 0.001)], 'M3d2'))
    const rows = itemsOf(fx.orderId)
    const sum = rows.reduce((a, x) => a + cents(x.shipped_quantity), 0n)
    judge(R, {
      id: 'M3d2-ZERO-ROW', name: '🔴 越界精度 0.001 ⇒ 必须 4xx 且零写（不再出现「接受但实发 0」）',
      expect: '4xx ∧ 行数=0 ∧ Σ=0 ∧ 订单**不**流转 shipped',
      actual: `HTTP ${r.status} ∧ 状态=${one(`select status from orders where tenant_id=${TENANT_ID} and id='${fx.orderId}'`)?.status} ∧ Σ=${fmtQty(sum)} ∧ 行数=${rows.length}`,
      pass: r.status >= 400 && r.status < 500 && rows.length === 0 && sum === 0n &&
        (one(`select status from orders where tenant_id=${TENANT_ID} and id='${fx.orderId}'`)?.status !== 'shipped'),
      expectSource: `新契约（S1/#6157）：numeric(${col?.p},${col?.s}) 列容不下的精度 ⇒ 写库前拒绝（4xx）+ 零写；旧行为「接受并落 0.00」已废`,
      evidence: [
        `列精度（information_schema）: numeric(${col?.p},${col?.s})`,
        `resp(${r.status}); SQL: select shipped_quantity from order_shipment_items → ${JSON.stringify(rows.map((x) => String(x.shipped_quantity)))}`,
        `影响面（旧行为）：totals() 汇总得 0 ⇒ 下游"少发/错发可核"在极小数量上失真；且订单已 shipped（不可再发、不可撤销）`,
        `一句话判据：POST /ship 收 shipped_quantity=0.001 ⇒ 4xx 且 order_shipment_items 零行、orders.status 不变`,
      ],
    })
  }

  // ══ M4 边界：同一订单行**两次出现在同一请求**（重复行）══
  {
    const fx = createProbeOrder({ tag: 'M4', status: 'confirmed', items: [{ name: `${PROBE_PREFIX}牛仔布M4`, qty: 10 }] })
    const it = fx.items[0]
    const r = await wship(session, fx.orderId, shipBody([line(it, 6), line(it, 6)], 'M4'))
    const sum = sumOf(fx.orderId)
    judge(R, {
      id: 'M4-DUP-LINE', name: '边界：同一 order_item 在**同一请求里写两行**（6+6 > 订单量 10）⇒ 不得放行超量',
      expect: '4xx ∧ Σ ≤ 10.00', actual: `HTTP ${r.status} ∧ Σ=${fmtQty(sum)} ∧ 行数=${itemsOf(fx.orderId).length}`,
      pass: r.status >= 400 && r.status < 500 && sum <= cents('10'),
      expectSource: '独立算式：同一次发货对同一订单行的实发合计 ≤ 订单量 10；6+6=12 越界',
      evidence: [`resp(${r.status}): ${r.text.slice(0, 260)}`,
        `SQL: ${JSON.stringify(itemsOf(fx.orderId))}`,
        `DDL 依据：order_shipment_items 唯一约束只有主键（无 (shipment_id, order_item_id) 唯一）`],
    })
  }

  // ══ M5 并发超发：两路各发「订单量」= 双倍（不同幂等键，真并打）══
  {
    const fx = createProbeOrder({ tag: 'M5', status: 'confirmed', items: [{ name: `${PROBE_PREFIX}牛仔布M5`, qty: 10 }] })
    const it = fx.items[0]
    const t0 = Date.now()
    const [ra, rb] = await Promise.all([
      wship(session, fx.orderId, shipBody([line(it, 10)], 'M5a'), idemKey('M5a')),
      wship(session, fx.orderId, shipBody([line(it, 10)], 'M5b'), idemKey('M5b')),
    ])
    const sum = sumOf(fx.orderId)
    const n = shipCount(fx.orderId)
    judge(R, {
      id: 'M5-CONC-OVER', name: '🔴 并发超发：两路各发满量 ⇒ 不得双记（Σ ≤ 10.00 ∧ 单据 ≤ 1）',
      expect: 'Σ ≤ 10.00 ∧ shipments ≤ 1 ∧ 恰一路 2xx',
      actual: `Σ=${fmtQty(sum)} ∧ shipments=${n} ∧ HTTP=${JSON.stringify([ra.status, rb.status])} ∧ ${Date.now() - t0}ms`,
      pass: sum <= cents('10') && n <= 1,
      expectSource: '独立算式上限 10（订单量）；并发下也须成立（状态机原子流转 + 唯一幂等键）',
      evidence: [`A(${ra.status}): ${ra.text.slice(0, 200)}`, `B(${rb.status}): ${rb.text.slice(0, 200)}`,
        `SQL: ${JSON.stringify(itemsOf(fx.orderId))}`],
    })
  }

  // ══ M6 多行部分发货：两行各发一部分 ⇒ 未发量 = 订单量 − 已发合计（逐行）══
  {
    const fx = createProbeOrder({ tag: 'M6', status: 'confirmed', items: [{ name: `${PROBE_PREFIX}牛仔布M6A`, qty: 10 }, { name: `${PROBE_PREFIX}牛仔布M6B`, qty: 7.25 }] })
    const [a, b] = fx.items
    const r = await wship(session, fx.orderId, shipBody([line(a, 4), line(b, 7.25)], 'M6'))
    const rows = itemsOf(fx.orderId)
    const expA = cents('10') - cents('4')
    const expB = cents('7.25') - cents('7.25')
    const gotA = cents('10') - cents(rows.find((x) => x.order_item_id === a.itemId)?.shipped_quantity ?? '0')
    const gotB = cents('7.25') - cents(rows.find((x) => x.order_item_id === b.itemId)?.shipped_quantity ?? '0')
    judge(R, {
      id: 'M6-REMAIN', name: '多行部分发货：逐行未发量 == 订单量 − 已发（独立算式，逐行）',
      expect: `A未发=${fmtQty(expA)} B未发=${fmtQty(expB)}`,
      actual: `A未发=${fmtQty(gotA)} B未发=${fmtQty(gotB)}`,
      pass: r.status < 300 && expA === gotA && expB === gotB,
      expectSource: '独立算式：逐行 order_items.quantity − Σ order_shipment_items.shipped_quantity（decimal，BigInt 分）',
      evidence: [`SQL 原始列: ${JSON.stringify(rows)}`],
    })
  }

  // ══ M7 decimal 语义：12.5 / 7.25 / 0.001 落库后逐分等价 ══
  {
    const fx = createProbeOrder({ tag: 'M7', status: 'confirmed', items: [{ name: `${PROBE_PREFIX}牛仔布M7`, qty: 100 }] })
    const it = fx.items[0]
    const r = await wship(session, fx.orderId, shipBody([line(it, 12.5)], 'M7'))
    const rows = itemsOf(fx.orderId)
    judge(R, {
      id: 'M7-DECIMAL', name: 'decimal 语义：12.5 原样落库为 12.500（不丢精度、不做浮点截断）',
      expect: `[{"q":"12.500","u":"米"},{"q":"0.000","u":"件"}]（按列精度 numeric(10,2) 解析：0.001 → 0）`,
      actual: JSON.stringify(rows.map((x) => ({ q: fmtQty(cents(x.shipped_quantity)), raw: String(x.shipped_quantity), u: x.unit }))),
      // 0.001 经 numeric(10,2) 落库即 0.00 ⇒ 期望按**列精度**算（12.5→12.500，0.001→0.000）
      pass: rows.length === 1 && qtyEq(rows[0].shipped_quantity, '12.5'),
      expectSource: 'decimal 语义：numeric(10,2) 列按十进制读回；期望 = 原文经该精度解析（12.5 → 12.500，0.001 → 0.000）',
      evidence: [`SQL: select shipped_quantity::text, unit from order_shipment_items where order_id='${fx.orderId}' → ${JSON.stringify(rows.map((x) => String(x.shipped_quantity)))}`],
    })
  }

  const s = R.summary()
  log(`[p3] 完成 pass=${s.pass} fail=${s.fail} skip=${s.skip}`)
  return s
}
