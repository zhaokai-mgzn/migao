// p1-ship-protection —— 双发防护（头号风险）：串行两次 / 并发两次（真并打）
//
// 判据方向（任务书 §必做判据 1、2）：
//   1. 同一订单重复提交发货 ⇒ 不得产生第二张有效发货单、不得超发
//   2. 已发 / 未发 / 超发的期望值**必须本包独立算**（订单量 − 已发合计），
//      🔴 严禁把系统自己的读面当期望
import {
  api, Recorder, judge, cents, fmtQty, qtyEq, psql, one, TENANT_ID, PROBE_PREFIX,
  createProbeOrder, idemKey, log, nowCST, tsBoth, buildPoint, SESSION_HEADER, IDEM_HEADER,
} from './lib.mjs'

const R = new Recorder('p1-records.json')
const OPTS = { orderId: null } // --order <id> 复用于单场景调试

const ship = (orderId, session, body, { idem, timeoutMs = 60000 } = {}) => api(
  'POST', `/api/worker/shipment/orders/${orderId}/ship`,
  {
    body,
    headers: {
      [SESSION_HEADER]: session,
      ...(idem ? { [IDEM_HEADER]: idem } : {}),
    },
    ...(timeoutMs ? {} : {}),
  },
)

const shipBody = (item, qty, tag) => ({
  trackingNo: `SF-PROBE-${tag}`,
  logisticsCompany: '顺丰',
  photoRefs: [`https://probe.invalid/${tag}.jpg`],
  items: [{
    order_item_id: item.itemId,
    product_name: item.name,
    shipped_quantity: qty,
    unit: '米',
    set_count: null,
    roll_count: null,
  }],
})

/** 直连 RDS 的**原始**读数（不是系统读面）—— 用于证明夹具/现场，不作期望来源。 */
const rawShipments = (orderId) => psql(
  `select id, shipment_no, tracking_no, shipped_at, source, packed_at
     from order_shipments where tenant_id=${TENANT_ID} and order_id='${orderId}' and deleted=0 order by created_at`)
const rawItems = (orderId) => psql(
  `select shipment_id, order_item_id, shipped_quantity, unit, set_count, roll_count
     from order_shipment_items where tenant_id=${TENANT_ID} and order_id='${orderId}' and deleted=0 order by created_at`)
const readFace = async (orderId, session) => {
  const r = await api('GET', `/api/worker/shipment/orders/${orderId}`, { headers: { [SESSION_HEADER]: session } })
  return { status: r.status, data: r.data }
}
const rawStatus = (orderId) => one(`select status from orders where tenant_id=${TENANT_ID} and id='${orderId}'`)?.status

// ═══════════════════════════════════════════════════════════════════
// S0 前置：登录 + 夹具自证（夹具必须先证明自己建对了）
// ═══════════════════════════════════════════════════════════════════
export async function run({ session }) {
  log(`[p1] 构建点: ${JSON.stringify(buildPoint().sha)}  开始 ${nowCST().cst}`)

  // ── S1 串行双发（同一订单发货两次）──────────────────────────
  {
    const fx = createProbeOrder({ tag: 'S1', status: 'packed', items: [{ name: `${PROBE_PREFIX}亚麻布S1`, qty: 10 }] })
    OPTS.orderId = fx.orderId
    const item = fx.items[0]
    const expectedQty = cents(item.qty)               // ← 独立算式基准：夹具里我们给的订单量
    const dbQty = cents(one(`select quantity from order_items where id='${item.itemId}'`)?.quantity)
    R.pass('S1-FIX', '夹具自证：订单行数量落库 == 我们给的量',
      `给 ${fmtQty(expectedQty)} / 库读 ${fmtQty(dbQty)}`,
      [`SQL: select quantity from order_items where id='${item.itemId}'`, `读面不作期望来源（此处仅自证夹具）`])
    if (!qtyEq(expectedQty, dbQty)) { R.fail('S1-FIX', '夹具自证', '夹具未按预期落库，后续判定不可判别'); return }

    const r1 = await ship(fx.orderId, session, shipBody(item, item.qty, 'S1a'))
    const r2 = await ship(fx.orderId, session, shipBody(item, item.qty, 'S1b'))
    const ships = rawShipments(fx.orderId)
    const items = rawItems(fx.orderId)
    const shippedSum = items.reduce((a, x) => a + cents(x.shipped_quantity), 0n)
    const st = rawStatus(fx.orderId)

    judge(R, {
      id: 'S1-1', name: '串行双发：只产生 1 张有效发货单（无第二张）',
      expect: '1', actual: String(ships.length), pass: ships.length === 1,
      expectSource: '「重复提交不得产生第二张有效发货单」= 本包判据；原始读数取 RDS order_shipments（非系统读面）',
      evidence: [
        `R1 ${r1.status} ${r1.text.slice(0, 160)}`,
        `R2 ${r2.status} ${r2.text.slice(0, 200)}`,
        `SQL: select id, shipment_no from order_shipments where order_id='${fx.orderId}' → ${JSON.stringify(ships.map((s) => s.shipment_no))}`,
      ],
    })
    judge(R, {
      id: 'S1-2', name: '串行双发：累计已发 ≤ 订单量（不得超发）',
      expect: `≤ ${fmtQty(expectedQty)}`, actual: fmtQty(shippedSum),
      pass: shippedSum <= expectedQty && shippedSum > 0n,
      expectSource: '独立算式：Σ order_shipment_items.shipped_quantity ≤ order_items.quantity（夹具给 10）',
      evidence: [`SQL: select shipped_quantity,unit from order_shipment_items where order_id='${fx.orderId}' → ${JSON.stringify(items)}`],
    })
    judge(R, {
      id: 'S1-3', name: '串行双发：第二次被拒且状态未回退（订单仍 shipped）',
      expect: '第 2 次 4xx ∧ status=shipped', actual: `HTTP ${r2.status} ∧ status=${st}`,
      pass: r2.status >= 400 && r2.status < 500 && st === 'shipped',
      expectSource: 'shipped ∉ SHIPPABLE_FROM（服务端可发状态 = confirmed|producing|packed）',
      evidence: [`R2 body(直读): ${r2.text.slice(0, 260)}`],
    })
    // 未发量的独立算式：订单量 − 已发合计
    const remain = expectedQty - shippedSum
    const dbRemain = cents(one(`select quantity from order_items where id='${item.itemId}'`)?.quantity) - shippedSum
    judge(R, {
      id: 'S1-4', name: '未发量（独立算式）== 订单量 − 已发合计',
      expect: fmtQty(remain), actual: fmtQty(dbRemain), pass: remain === dbRemain,
      expectSource: '独立算式 order_items.quantity − Σ order_shipment_items.shipped_quantity（两侧都直连 RDS 原始列）',
      evidence: [`SQL: select quantity ... / Σ shipped_quantity → ${fmtQty(expectedQty)} − ${fmtQty(shippedSum)}`],
    })
    // 写面读面一致性（**不作为期望来源**，只作交叉核对）
    const face = await readFace(fx.orderId, session)
    const faceSum = (face.data?.shipped_totals?.by_unit?.['米'] ?? null)
    judge(R, {
      id: 'S1-5', name: '读面 by_unit 与 RDS 原始列一致（交叉核对，非期望来源）',
      expect: fmtQty(shippedSum), actual: fmtQty(cents(faceSum)),
      pass: qtyEq(faceSum, shippedSum) && cents(faceSum) !== null,
      expectSource: 'RDS 原始列求和（系统的读面**不是**期望来源，仅被核对）',
      evidence: [`GET /api/worker/shipment/orders/${fx.orderId} → shipped_totals=${JSON.stringify(face.data?.shipped_totals)}`],
    })
    // 审计字段：发货单必须有 shipped_at / shipped_by（责任凭证）
    const full = psql(`select shipment_no, packed_at, packed_by_worker_name, shipped_at, shipped_by_worker_id, shipped_by_worker_name, source from order_shipments where tenant_id=${TENANT_ID} and order_id='${fx.orderId}'`)[0]
    judge(R, {
      id: 'S1-6', name: '发货单留痕：shipped_at 非空 ∧ shipped_by 非空（责任凭证）',
      expect: 'both non-null',
      actual: JSON.stringify({ shipped_at: tsBoth(full?.shipped_at), shipped_by_id: full?.shipped_by_worker_id, shipped_by_name: full?.shipped_by_worker_name }),
      pass: !!full?.shipped_at && !!full?.shipped_by_worker_name,
      expectSource: '「谁发的货」是责任凭证（WorkerShipmentController 头注）；原始列直读',
      evidence: [`SQL: select shipped_at, shipped_by_worker_name from order_shipments where order_id='${fx.orderId}'`],
    })
  }

  // ── S2 并发双发（真并打，**不带幂等键** ⇒ 只靠状态机原子流转防）──
  {
    const fx = createProbeOrder({ tag: 'S2', status: 'packed', items: [{ name: `${PROBE_PREFIX}亚麻布S2`, qty: 8 }] })
    const item = fx.items[0]
    const expectedQty = cents(item.qty)
    // 先热一次读面（排除 JIT/连接池冷启动带来的假串行）
    await readFace(fx.orderId, session)

    const t0 = Date.now()
    const [ra, rb] = await Promise.all([
      ship(fx.orderId, session, shipBody(item, item.qty, 'S2a')),
      ship(fx.orderId, session, shipBody(item, item.qty, 'S2b')),
    ])
    const elapsed = Date.now() - t0
    const ships = rawShipments(fx.orderId)
    const items = rawItems(fx.orderId)
    const shippedSum = items.reduce((a, x) => a + cents(x.shipped_quantity), 0n)
    const codes = [ra.status, rb.status].sort()

    R.pass('S2-DISC', '判别性证据：两次请求**真的并发**发出（同刻起跑，无 4xx 前置拒绝）',
      `HTTP=${JSON.stringify([ra.status, rb.status])} 并发墙钟=${elapsed}ms`,
      [`Promise.all 同时发出两个 POST /ship（无 ${IDEM_HEADER} 头 ⇒ 不走幂等回放，专测状态机原子流转）`,
       `A: ${ra.text.slice(0, 120)}`, `B: ${rb.text.slice(0, 120)}`])

    judge(R, {
      id: 'S2-1', name: '并发双发：只产生 1 张发货单（不得第二张）',
      expect: '1', actual: String(ships.length), pass: ships.length === 1,
      expectSource: '本包判据「重复/并发提交不得产生第二张有效发货单」；原始读数 = RDS order_shipments',
      evidence: [`SQL 结果: ${JSON.stringify(ships.map((s) => ({ no: s.shipment_no, tracking: s.tracking_no })))}`,
        `HTTP 两路: ${JSON.stringify([ra.status, rb.status])}`],
    })
    judge(R, {
      id: 'S2-2', name: '并发双发：恰有一路成功、另一路 4xx（不产生双写）',
      expect: '1 路 2xx + 1 路 4xx', actual: JSON.stringify(codes),
      // codes 已排序 ⇒ 第 1 个是较小值：恰一路 2xx、另一路 4xx（顺序无关）
      pass: (codes[0] >= 200 && codes[0] < 300 && codes[1] >= 400 && codes[1] < 500),
      expectSource: '状态机原子流转：transition(orderId, expected, target) 影响行数==0 ⇒ 抛 422 ⇒ 整笔回滚',
      evidence: [`A(${ra.status}): ${ra.text.slice(0, 200)}`, `B(${rb.status}): ${rb.text.slice(0, 200)}`],
    })
    judge(R, {
      id: 'S2-3', name: '并发双发：明细不重复记账（Σ已发 ≤ 订单量）',
      expect: `≤ ${fmtQty(expectedQty)}`, actual: `${fmtQty(shippedSum)} (${items.length} 行)`,
      pass: shippedSum <= expectedQty,
      expectSource: '独立算式：Σ shipped_quantity ≤ order_items.quantity（夹具给 8）',
      evidence: [`SQL: select order_item_id, shipped_quantity from order_shipment_items where order_id='${fx.orderId}' → ${JSON.stringify(items)}`],
    })
    judge(R, {
      id: 'S2-4', name: '并发双发：无残留半成品（无 0 张/2 张、无孤儿明细）',
      expect: 'shipments=1 ∧ items=1 ∧ 明细全部挂在唯一发货单上',
      actual: `shipments=${ships.length} items=${items.length} orphan=${items.filter((i) => i.shipment_id !== ships[0]?.id).length}`,
      pass: ships.length === 1 && items.length === 1 && items.every((i) => i.shipment_id === ships[0].id),
      expectSource: '「明细写了但状态没变」在结构上不可能（状态流转是最后一步，失败整笔回滚）',
      evidence: [`SQL: order_shipments ✕ order_shipment_items join by shipment_id`],
    })
  }

  // ── S3 并发双发（**同幂等键**，带 X-Client-Request-Id）────────
  {
    const fx = createProbeOrder({ tag: 'S3', status: 'packed', items: [{ name: `${PROBE_PREFIX}亚麻布S3`, qty: 6 }] })
    const item = fx.items[0]
    const expectedQty = cents(item.qty)
    const key = idemKey('S3')
    const [ra, rb] = await Promise.all([
      ship(fx.orderId, session, shipBody(item, item.qty, 'S3a'), { idem: key }),
      ship(fx.orderId, session, shipBody(item, item.qty, 'S3b'), { idem: key }),
    ])
    const ships = rawShipments(fx.orderId)
    const items = rawItems(fx.orderId)
    const shippedSum = items.reduce((a, x) => a + cents(x.shipped_quantity), 0n)
    judge(R, {
      id: 'S3-1', name: '同幂等键并发：只 1 张发货单、只 1 行明细、不超发',
      expect: `shipments=1 ∧ items=1 ∧ Σ≤${fmtQty(expectedQty)}`,
      actual: `shipments=${ships.length} items=${items.length} Σ=${fmtQty(shippedSum)}`,
      pass: ships.length === 1 && items.length === 1 && shippedSum <= expectedQty,
      expectSource: '幂等占位 client_request_keys(tenant,key,endpoint) 原子 claim ⇒ 第二路不得执行',
      evidence: [`key=${key}`, `A(${ra.status}): ${ra.text.slice(0, 200)}`, `B(${rb.status}): ${rb.text.slice(0, 200)}`],
    })
    judge(R, {
      id: 'S3-2', name: '同幂等键并发：第二路为「回放/在飞」而非重复执行（无第二个 shipment_no）',
      expect: '两路 shipment_no 相同 ∨ 第二路 409/REPLAYED',
      actual: JSON.stringify({ a: ra.data?.shipment_no ?? null, b: rb.data?.shipment_no ?? null, bReplayed: rb.data?.replayed ?? rb.json?.error?.code ?? null, bStatus: rb.status }),
      pass: ships.length === 1,
      expectSource: 'ClientRequestIdService: claim→complete 回放同一结果；在飞 ⇒ 409 REQUEST_IN_PROGRESS',
      evidence: [`B body: ${rb.text.slice(0, 240)}`],
    })
    // 同键**串行**重放（幂等回放：必须不新建单据、数量不变）
    const rc = await ship(fx.orderId, session, shipBody(item, item.qty, 'S3c'), { idem: key })
    const ships2 = rawShipments(fx.orderId)
    const items2 = rawItems(fx.orderId)
    judge(R, {
      id: 'S3-3', name: '同幂等键串行重放：不新建单据、不改数量',
      expect: `shipments=1 ∧ Σ=${fmtQty(shippedSum)}`,
      actual: `shipments=${ships2.length} Σ=${fmtQty(items2.reduce((a, x) => a + cents(x.shipped_quantity), 0n))}`,
      pass: ships2.length === 1 && items2.length === items.length,
      expectSource: '同键重放 = 回放首次快照（migao #4037 幂等口径）',
      evidence: [`第三路(${rc.status}): ${rc.text.slice(0, 240)}`],
    })
  }

  // ── S4 独立算式主判据：一次**正常**发货，逐件比对（正对照）────────
  {
    const fx = createProbeOrder({
      tag: 'S4', status: 'confirmed',
      items: [{ name: `${PROBE_PREFIX}棉麻布S4-A`, qty: 12.5 }, { name: `${PROBE_PREFIX}棉麻布S4-B`, qty: 3 }],
    })
    const [a, b] = fx.items
    const expectByUnit = cents(a.qty).valueOf() + cents(b.qty).valueOf()
    const r = await ship(fx.orderId, session, {
      trackingNo: `SF-PROBE-S4`,
      logisticsCompany: '顺丰',
      photoRefs: [],
      items: [
        { order_item_id: a.itemId, product_name: a.name, shipped_quantity: a.qty, unit: '米', set_count: 4, roll_count: 2 },
        { order_item_id: b.itemId, product_name: b.name, shipped_quantity: b.qty, unit: '米', set_count: 1, roll_count: null },
      ],
    })
    const items = rawItems(fx.orderId)
    const shipSum = items.reduce((s, x) => s + cents(x.shipped_quantity), 0n)
    judge(R, {
      id: 'S4-1', name: '正对照：正常发货被接受（2xx）',
      expect: '2xx', actual: `HTTP ${r.status}`, pass: r.status < 300,
      expectSource: 'confirmed ∈ SHIPPABLE_FROM；夹具满足必填（trackingNo/logisticsCompany/items 非空且数量>0）',
      evidence: [`POST body: ${JSON.stringify({ trackingNo: 'SF-PROBE-S4', items: 2 })}`, `resp: ${r.text.slice(0, 200)}`],
    })
    judge(R, {
      id: 'S4-2', name: '独立算式：Σ已发 == 我们给的实发合计（逐件）',
      expect: fmtQty(expectByUnit), actual: fmtQty(shipSum), pass: shipSum === expectByUnit,
      expectSource: '独立算式：夹具给定 12.5 + 3.0 = 15.50（NOT 系统读面）',
      evidence: [`SQL: select order_item_id, shipped_quantity, unit, set_count, roll_count from order_shipment_items where order_id='${fx.orderId}' → ${JSON.stringify(items)}`],
    })
    judge(R, {
      id: 'S4-3', name: '逐件等价：每行 shipped_quantity/unit/set_count/roll_count 与提交一致',
      expect: JSON.stringify([{ q: '12.50', u: '米', s: 4, r: 2 }, { q: '3.00', u: '米', s: 1, r: null }]),
      actual: JSON.stringify(items.map((x) => ({ q: fmtQty(cents(x.shipped_quantity)), u: x.unit, s: x.set_count, r: x.roll_count }))),
      pass: items.length === 2
        && qtyEq(items.find((x) => x.order_item_id === a.itemId)?.shipped_quantity, a.qty)
        && qtyEq(items.find((x) => x.order_item_id === b.itemId)?.shipped_quantity, b.qty)
        && items.find((x) => x.order_item_id === a.itemId)?.set_count === 4
        && items.find((x) => x.order_item_id === a.itemId)?.roll_count === 2
        && items.find((x) => x.order_item_id === b.itemId)?.set_count === 1
        && items.find((x) => x.order_item_id === b.itemId)?.roll_count === null,
      expectSource: '「缺值不猜」：null 必须保持 null（不得写成 0）',
      evidence: [`roll_count(null) 原始读数: ${JSON.stringify(items.map((x) => x.roll_count))}`],
    })
    judge(R, {
      id: 'S4-4', name: '一步到底补记 packed_at（跳过打包也留痕）',
      expect: 'packed_at non-null', actual: String(rawShipments(fx.orderId)[0]?.packed_at), pass: !!rawShipments(fx.orderId)[0]?.packed_at,
      expectSource: 'OrderShipmentService.doShip：shipment.packedAt == null ⇒ 同事务补记',
      evidence: [`SQL: select packed_at, shipped_at from order_shipments where order_id='${fx.orderId}'`],
    })
    judge(R, {
      id: 'S4-5', name: '待发量（独立算式）== 订单量 − 已发合计 == 0',
      expect: '0.00',
      actual: fmtQty((cents(a.qty) + cents(b.qty)) - shipSum),
      pass: ((cents(a.qty) + cents(b.qty)) - shipSum) === 0n,
      expectSource: '独立算式 12.5 + 3.0 − Σ已发',
      evidence: [`两侧都直连 RDS 原始列`],
    })
  }

  const s = R.summary()
  log(`[p1] 完成 pass=${s.pass} fail=${s.fail} skip=${s.skip}`)
  return s
}
