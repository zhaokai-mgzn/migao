// p5-stock-and-print —— 库存/出库回补（存在则测，不存在则**如实登记**）
//   + 打印/补打类的相邻面（入库标签 print）在**发货单**上的等价性
//   + 商家发货路（POST /api/admin/production/orders/{id}/ship）与工人发货路的差异
import {
  api, Recorder, judge, cents, fmtQty, psql, one, TENANT_ID, PROBE_PREFIX, createProbeOrder, buildPoint,
  tableSnap, fieldDiff, fmtDiff, log, SESSION_HEADER, IDEM_HEADER, idemKey, nowCST,
} from './lib.mjs'

const R = new Recorder('p5-records.json')
const wship = (session, orderId, body) => api('POST', `/api/worker/shipment/orders/${orderId}/ship`,
  { body, headers: { [SESSION_HEADER]: session } })
const shipBody = (item, qty, tag) => ({
  trackingNo: `SF-PROBE-${tag}`, logisticsCompany: '顺丰', photoRefs: [],
  items: [{ order_item_id: item.itemId, product_name: item.name, shipped_quantity: qty, unit: '米', set_count: null, roll_count: null }],
})
const stockOf = () => psql(`select count(*) c from stock_ledger_entries where tenant_id=${TENANT_ID}`)[0].c
const ledgerFor = (orderId) => psql(`select id, reason, delta, ref_no from stock_ledger_entries where tenant_id=${TENANT_ID} and ref_no='${orderId}'`)

export async function run({ session, token }) {
  log(`[p5] 构建点 sha=${buildPoint().sha} @ ${nowCST().cst}`)
  // ══ K1 发货是否扣减库存 / 是否写库存台账 ══
  {
    const fx = createProbeOrder({ tag: 'K1', status: 'confirmed', items: [{ name: `${PROBE_PREFIX}库存布K1`, qty: 9 }] })
    const stockBefore = stockOf()
    const r = await wship(session, fx.orderId, shipBody(fx.items[0], 9, 'K1'))
    const stockAfter = stockOf()
    const led = ledgerFor(fx.orderId)
    judge(R, {
      id: 'K1-1', name: '发货**不写**库存台账（stock_ledger_entries 无本单 ref_no 的行）',
      expect: '本单台账行 = 0', actual: `本单台账行 = ${led.length}；全租户台账 ${stockBefore} → ${stockAfter}`,
      pass: led.length === 0,
      expectSource: '代码事实：OrderShipmentService 不引用 StockLedger；台账 reason 实测只有 order/manual/inbound（发货运维不在其中）',
      evidence: [`resp: ${r.text.slice(0, 160)}`,
        `SQL: select * from stock_ledger_entries where ref_no='${fx.orderId}' → ${JSON.stringify(led)}`,
        `SQL: select reason, count(*) from stock_ledger_entries where tenant_id=${TENANT_ID} group by reason`],
    })
    R.skip('K1-2', '发货扣减库存（products.stock / stock_ledger）面：**不存在**',
      `本包枚举全量端点无「发货出库」写面；实证：worker /ship 后本单零台账行（K1-1）。` +
      `⇒ 按任务书口径「如实登记不存在」，不写成通过。`)
  }

  // ══ K2 取消/退回是否回补 ⇒ 不存在（无「退回/退货」端点），登记即可 ══
  {
    const docs = JSON.parse(await (await fetch('http://localhost:8080/v3/api-docs')).text())
    const ret = Object.keys(docs.paths).filter((p) => /return|refund|after-?sales|revert|restock|回补|退回|退货/i.test(p))
    R.skip('K2-RESTOCK', '发货退回 / 库存回补 / 回补幂等面：**不存在**（如实登记）',
      `OpenAPI 里与退货/回补相关的路径 = ${JSON.stringify(ret.slice(0, 12))}（无一属于发货单回补语义）；` +
      `发货单无「作废/红冲」写面（唯一回退动作是工人 unpack：packed→producing，且不影响已发数量）。`)
  }

  // ══ K3 商家发货路（production /ship）：双发防护与工人路是否同口径 ══
  {
    const fx = createProbeOrder({ tag: 'K3', status: 'confirmed', items: [{ name: `${PROBE_PREFIX}库存布K3`, qty: 5 }] })
    const before = tableSnap([
      { table: 'orders', where: `tenant_id=${TENANT_ID} and id='${fx.orderId}'` },
      { table: 'order_logistics', where: `tenant_id=${TENANT_ID} and order_id='${fx.orderId}'` },
      { table: 'order_shipments', where: `tenant_id=${TENANT_ID} and order_id='${fx.orderId}'` },
    ])
    const r1 = await api('POST', `/api/admin/production/orders/${fx.orderId}/ship`, { token, body: { trackingNo: 'SF-ADMIN-1', logisticsCompany: '顺丰' } })
    const after1 = tableSnap([
      { table: 'orders', where: `tenant_id=${TENANT_ID} and id='${fx.orderId}'` },
      { table: 'order_logistics', where: `tenant_id=${TENANT_ID} and order_id='${fx.orderId}'` },
      { table: 'order_shipments', where: `tenant_id=${TENANT_ID} and order_id='${fx.orderId}'` },
    ])
    const d1 = fieldDiff(before, after1)
    const st1 = one(`select status from orders where tenant_id=${TENANT_ID} and id='${fx.orderId}'`)?.status
    const r2 = await api('POST', `/api/admin/production/orders/${fx.orderId}/ship`, { token, body: { trackingNo: 'SF-ADMIN-2', logisticsCompany: '顺丰' } })
    const ships = psql(`select id, tracking_no from order_shipments where tenant_id=${TENANT_ID} and order_id='${fx.orderId}'`)
    const logis = psql(`select id, tracking_no from order_logistics where tenant_id=${TENANT_ID} and order_id='${fx.orderId}'`)
    judge(R, {
      id: 'K3-1', name: '商家发货路：confirmed → shipped 且记物流（2xx）',
      expect: '2xx ∧ status=shipped ∧ logistics 1 行', actual: `HTTP ${r1.status} ∧ ${st1} ∧ ${logis.length} 行`,
      pass: r1.status < 300 && st1 === 'shipped' && logis.length === 1,
      expectSource: 'shipWithLogistics：记物流 + 原子流转 shipped',
      evidence: [`resp: ${r1.text.slice(0, 160)}`, `变化: ${JSON.stringify([...new Set(d1.map((x) => `${x.table}.${x.field}`))])}`],
    })
    judge(R, {
      id: 'K3-2', name: '🔴 商家发货路**必须**产出可查的发货单（用户 2026-10-03 裁定「要建」）',
      expect: 'shipments=1（可查）∧ logistics=1', actual: `shipments=${ships.length} ∧ logistics=${logis.length}`,
      pass: ships.length === 1,
      expectSource: '用户裁定 2026-10-03「商家发货也应产生发货单」（实现单 #6171）⇒ 本判据在 S2 落地前**应为红**（判据先红后绿）',
      evidence: [`SQL: select * from order_shipments where order_id='${fx.orderId}' → ${JSON.stringify(ships)}`,
        `SQL: select * from order_logistics where order_id='${fx.orderId}' → ${JSON.stringify(logis)}`,
        `⇒ 已发货订单在「发货单」读面/列表上是**查不到的**（无单据 ⇒ 无实发数量）`],
    })
    judge(R, {
      id: 'K3-3', name: '商家发货路重复调用（第二次换单号）：**不得多建**发货单（恰一张），物流一把',
      expect: '2xx（幂等重发不报错）∧ shipments 仍 1 ∧ logistics 仍 1 行',
      actual: `HTTP ${r2.status} ∧ shipments=${ships.length} ∧ logistics=${logis.length} ∧ tracking=${logis[0]?.tracking_no}`,
      pass: r2.status < 300 && ships.length === 1 && logis.length === 1 && logis[0]?.tracking_no === 'SF-ADMIN-2',
      expectSource: '不变量：重复发货不得产生第二张单据；upsertLogistics = 存在则更新（同一订单一条物流）',
      evidence: [`R2(${r2.status}): ${r2.text.slice(0, 160)}`,
        `SQL: select tracking_no from order_logistics → ${JSON.stringify(logis)}`,
        `⚠️ 覆写判定：第二次 tracking_no=${logis[0]?.tracking_no}（若为 SF-ADMIN-2 则该次调用**改写了发货事实**）`],
    })
  }

  // ══ K3b 商家发货路**非幂等**（无幂等键）⇒ 同单第二次调用**覆写运单号**，纸面/物流与首次不一致 ══
  {
    const fx = createProbeOrder({ tag: 'K3b', status: 'confirmed', items: [{ name: `${PROBE_PREFIX}库存布K3b`, qty: 5 }] })
    const r1 = await api('POST', `/api/admin/production/orders/${fx.orderId}/ship`, { token, body: { trackingNo: 'SF-FIRST-7777', logisticsCompany: '顺丰' } })
    const t1 = one(`select tracking_no, logistics_company from order_logistics where tenant_id=${TENANT_ID} and order_id='${fx.orderId}'`)
    // 同键复用（幂等键存在时应当回放）；此处**带同一个 X-Client-Request-Id** 再打一次
    const key = idemKey('K3b')
    const rA = await api('POST', `/api/admin/production/orders/${fx.orderId}/ship`, { token, body: { trackingNo: 'SF-SECOND-8888', logisticsCompany: '顺丰' }, headers: { [IDEM_HEADER]: key } })
    const tA = one(`select tracking_no from order_logistics where tenant_id=${TENANT_ID} and order_id='${fx.orderId}'`)
    const rB = await api('POST', `/api/admin/production/orders/${fx.orderId}/ship`, { token, body: { trackingNo: 'SF-THIRD-9999', logisticsCompany: '顺丰' }, headers: { [IDEM_HEADER]: key } })
    const tB = one(`select tracking_no from order_logistics where tenant_id=${TENANT_ID} and order_id='${fx.orderId}'`)
    const keys = psql(`select client_request_id, endpoint from client_request_keys where tenant_id=${TENANT_ID} and client_request_id='${key}'`)
    judge(R, {
      id: 'K3b-1', name: '🔴 商家发货路**不认幂等键**：同 X-Client-Request-Id 两次调用都生效（运单号被二次覆写）',
      expect: '带同键的两次调用应回放首次结果 ⇒ tracking_no 保持 SF-SECOND-8888',
      actual: `tracking_no: ${t1?.tracking_no} → ${tA?.tracking_no} → ${tB?.tracking_no}（HTTP ${rA.status}/${rB.status}，client_request_keys 命中 ${keys.length} 行）`,
      pass: tA?.tracking_no === 'SF-SECOND-8888' && tB?.tracking_no === 'SF-SECOND-8888',
      expectSource: '幂等契约（#4037）：带 X-Client-Request-Id 的写请求同键重复 ⇒ 回放首次结果，不得再执行',
      evidence: [
        `R1(${r1.status}) tracking=${t1?.tracking_no}`,
        `RA(${rA.status}) tracking=${tA?.tracking_no}`, `RB(${rB.status}) tracking=${tB?.tracking_no}`,
        `client_request_keys 命中: ${JSON.stringify(keys)}（空 ⇒ 该端点从未接幂等键）`,
        `代码依据：ProductionController.ship 直接转发 orderService.shipWithLogistics，未走 ClientRequestIdService.claim`,
      ],
    })
  }

  // ══ K4 入库面（仓储）不在本包射程：如实登记覆盖边界 ══
  {
    R.skip('K4-INBOUND', '入库单 / 入库标签补打（WorkerInboundLabelController /print）不在本包射程',
      '本包射程 = 发货单/仓储链中的**发货**半边；入库标签 print 属「入库」半边（另包/另轮）。' +
      '任务书要求「不存在则如实登记」——此处登记为**未覆盖**，不写成通过。')
  }

  const s = R.summary()
  log(`[p5] 完成 pass=${s.pass} fail=${s.fail} skip=${s.skip}`)
  return s
}
