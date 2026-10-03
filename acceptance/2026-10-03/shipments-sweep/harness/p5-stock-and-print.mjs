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
      id: 'K3-3', name: '商家发货路重复调用（**不带**幂等键、换单号）：已发货 ⇒ **4xx 且不多建单、不覆写运单号**',
      expect: '4xx ∧ shipments 仍 1 ∧ logistics 仍 1 行 ∧ 运单号仍 SF-ADMIN-1',
      actual: `HTTP ${r2.status} ∧ shipments=${ships.length} ∧ logistics=${logis.length} ∧ tracking=${logis[0]?.tracking_no}`,
      pass: r2.status >= 400 && r2.status < 500 && ships.length === 1 && logis.length === 1 && logis[0]?.tracking_no === 'SF-ADMIN-1',
      expectSource: '新契约（#6190）：已发货订单的再次发货**被拒**（不再静默改物流）⇒ 必须 4xx；不变量 = 不得多建第二张单据、不得覆写首次运单号',
      evidence: [`R2(${r2.status}): ${r2.text.slice(0, 160)}`,
        `SQL: select tracking_no from order_logistics → ${JSON.stringify(logis)}`,
        `⚠️ 覆写判定：第二次 tracking_no=${logis[0]?.tracking_no}（若为 SF-ADMIN-2 则该次调用**改写了发货事实**）`],
    })

    // 🔴 K3-4（2026-10-03 补，用户裁定「要建」的**核心语义**）：光看 DB 行不算数 ——
    //    商家发货后必须**在「发货单」列表读面上查得到**，且列表里的实发量与**按单读面**同源
    //    （同一份 totals() 投影；不硬编码单位/数量 ⇒ 与夹具解耦）。
    {
      const listRes = await api('GET', `/api/admin/shipments?keyword=${encodeURIComponent(fx.orderNo)}`, { token })
      const listHit = (listRes.data || []).filter((x) => x.orderNo === fx.orderNo)
      // 🔴 期望来自**写面（库）**的独立算式：逐单位合计 shipped_quantity —— 不依赖第二个 API 的形状
      const dbRows = psql(`select unit, sum(shipped_quantity)::numeric(10,2) as q from order_shipment_items
                           where tenant_id=${TENANT_ID} and order_id='${fx.orderId}' group by unit`)
      const dbTotals = Object.fromEntries(dbRows.map((x) => [x.unit, Number(x.q).toFixed(2)]))
      const listTotals = listHit[0]?.shippedTotals?.by_unit ?? null
      const listNorm = Object.fromEntries(Object.entries(listTotals ?? {}).map(([k, v]) => [k, Number(v).toFixed(2)]))
      const same = Object.keys(dbTotals).length > 0 && JSON.stringify(listNorm) === JSON.stringify(dbTotals)
      judge(R, {
        id: 'K3-4', name: '🔴 读面一致（用户裁定的核心）：商家发货后该订单**在发货单列表查得到**，实发量与按单读面同源',
        expect: '列表命中 = 1 ∧ itemCount ≥ 1 ∧ 列表 by_unit = **库写面**逐单位合计（独立算式，逐字相同）',
        actual: `命中=${listHit.length} ∧ itemCount=${listHit[0]?.itemCount} ∧ 列表=${JSON.stringify(listNorm)} ∧ 库=${JSON.stringify(dbTotals)}`,
        pass: listHit.length === 1 && Number(listHit[0]?.itemCount ?? 0) >= 1 && same,
        expectSource: '用户 2026-10-03 裁定「商家发货也应产生发货单」的**可查**语义：列表能查到 ∧ 其实发汇总 = 写面库值（独立算式；#5939 判据 4 的「同一份 totals 投影」由该等式独立把守）',
        evidence: [`GET /api/admin/shipments?keyword=${fx.orderNo} → HTTP ${listRes.status}，命中 ${listHit.length} 行`,
          `命中行: ${JSON.stringify(listHit.map((x) => ({ no: x.shipmentNo, orderNo: x.orderNo, itemCount: x.itemCount, totals: x.shippedTotals })))}`,
          `库写面（独立算式）: select unit, sum(shipped_quantity) … group by unit → ${JSON.stringify(dbRows)}`],
      })
    }
  }

  // ══ K3b 商家发货路**幂等键**（#6190 后口径变了：已发货订单会被拒、不再静默改物流）
  //     ⇒ 正确验法 = 用**带键的首次发货**打头，再同键重复 ⇒ 必须**回放首次结果**（不得二次生效、不得多建单）══
  {
    const fx = createProbeOrder({ tag: 'K3b', status: 'confirmed', items: [{ name: `${PROBE_PREFIX}库存布K3b`, qty: 5 }] })
    const key = idemKey('K3b')
    const r1 = await api('POST', `/api/admin/production/orders/${fx.orderId}/ship`,
      { token, body: { trackingNo: 'SF-FIRST-7777', logisticsCompany: '顺丰' }, headers: { [IDEM_HEADER]: key } })
    const t1 = one(`select tracking_no from order_logistics where tenant_id=${TENANT_ID} and order_id='${fx.orderId}'`)
    const ships1 = psql(`select id from order_shipments where tenant_id=${TENANT_ID} and order_id='${fx.orderId}'`)
    const keys1 = psql(`select client_request_id, endpoint from client_request_keys where tenant_id=${TENANT_ID} and client_request_id='${key}'`)
    const rB = await api('POST', `/api/admin/production/orders/${fx.orderId}/ship`,
      { token, body: { trackingNo: 'SF-SECOND-8888', logisticsCompany: '顺丰' }, headers: { [IDEM_HEADER]: key } })
    const tB = one(`select tracking_no from order_logistics where tenant_id=${TENANT_ID} and order_id='${fx.orderId}'`)
    const ships2 = psql(`select id from order_shipments where tenant_id=${TENANT_ID} and order_id='${fx.orderId}'`)
    judge(R, {
      id: 'K3b-1', name: '🔴 同 X-Client-Request-Id 重复调用 ⇒ **回放首次结果**（不得二次生效、不得多建单）',
      expect: 'R1 2xx ∧ 同键重放 2xx ∧ 运单号仍 SF-FIRST-7777 ∧ shipments 恰 1 ∧ client_request_keys 命中 1 行',
      actual: `R1(${r1.status}) ∧ 重放(${rB.status}) ∧ tracking=${tB?.tracking_no} ∧ shipments=${ships2.length} ∧ keys=${keys1.length}`,
      pass: r1.status < 300 && rB.status < 300 && tB?.tracking_no === 'SF-FIRST-7777' && ships2.length === 1 && keys1.length === 1,
      expectSource: '幂等契约（#4037）：带 X-Client-Request-Id 的写请求同键重复 ⇒ **回放首次结果**，不得再执行（`ClientRequestIdService.claim/complete`）',
      evidence: [
        `R1(${r1.status}) tracking=${t1?.tracking_no} ∧ shipments=${ships1.length} ∧ keys=${JSON.stringify(keys1)}`,
        `同键重放(${rB.status}) tracking=${tB?.tracking_no} ∧ shipments=${ships2.length}`,
        `⚠️ #6190 后的口径：**不带键**的重复调用会被拒（「本次未发生订单发货流转…」）—— 该形态由 K3-3 判`,
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
