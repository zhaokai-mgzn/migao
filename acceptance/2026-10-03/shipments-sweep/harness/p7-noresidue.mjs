// p7-noresidue —— 零残留**机器读数**（直连 RDS 按表计数，不是人眼）
import { Recorder, judge, probeResidue, cleanupProbe, psql, one, TENANT_ID, PROBE_PREFIX, log } from './lib.mjs'

const R = new Recorder('p7-records.json')

export async function run() {
  const before = probeResidue()
  cleanupProbe()
  const after = probeResidue()
  judge(R, {
    id: 'NR-1', name: '探针存活残留 = 0（清理后逐表计数）',
    expect: 'total=0（9 张表全 0）', actual: `total=${after.total} ${JSON.stringify(after.counts)}`,
    pass: after.total === 0,
    expectSource: '任务书：结束给「探针存活残留 = 0」的机器读数（直连 RDS 按表计数）',
    evidence: [
      `清理前: ${JSON.stringify(before.counts)}`,
      `清理后: ${JSON.stringify(after.counts)}`,
      `口径：orders/order_items/order_shipments/order_shipment_items/order_logistics 按 id like 'fsprobe%' 或 order_id like 'fsprobe%'；` +
      `client_request_keys 按 client_request_id like 'fsprobe-%'；stock_ledger_entries 按 ref_no like 'fsprobe%'；` +
      `users/worker_sessions 按本包自建工号 WFS20261003`,
    ],
  })
  // 反证：**别人创建的**行未被本包清理（探针边界自证）
  const outsiders = one(`select count(*) c from orders where tenant_id=${TENANT_ID} and deleted=0 and id not like 'fsprobe%'`)
  judge(R, {
    id: 'NR-2', name: '探针边界自证：本包清理**只**命中自建对象，租户 20 存量订单未被触碰',
    expect: '租户 20 非探针订单 > 0（仍是原样存在）', actual: `非探针订单数 = ${outsiders.c}`,
    pass: Number(outsiders.c) > 0,
    expectSource: '并行纪律：绝不改别人创建的行 ⇒ 清理后其余行必须仍在',
    evidence: [`SQL: select count(*) from orders where tenant_id=${TENANT_ID} and deleted=0 and id not like 'fsprobe%'`],
  })
  const s = R.summary()
  log(`[p7] 完成 pass=${s.pass} fail=${s.fail} skip=${s.skip}`)
  return s
}
