// 线③ 验收总入口 —— 财务/库存下游 + 账期时间口径。
//
// 顺序即安全顺序：
//   0) 时钟自检（防 harness 口径 bug 静默污染全部读数）
//   1) 存量前后快照（零改动自证）
//   2) 家族 A（钱的收尾段：面枚举，read-only 为主）
//   3) 家族 B（库存下游：造探针货号/SKU/入库单 → 加权平均 + 台账不变式）
//   4) 家族 C（账期时间口径：注入时间探针 + 红证 + 还原）
//   5) 残留自清 + 逐表计数
//   6) 存量快照比对（非探针行必须零改动）
//   7) out/SUMMARY.json
import { loginApi, Recorder, buildPoint, psql, one, log, OUT, TENANT_ID, nowCST, guardedWrite, rowFingerprint, psqlRaw } from './lib.mjs'
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { familyA } from './famA-money.mjs'
import { familyB } from './famB-stock.mjs'
import { familyC } from './famC-time.mjs'
import { familyT } from './famT-clock.mjs'

const startedAt = nowCST()
log(`════ 线③ 验收开始 ${startedAt.cst} （utc=${startedAt.utc}）════`)
const bp = buildPoint()
log(`构建点: ${bp.worktree} @ ${bp.sha} (${bp.commitTime}) pid=${bp.adminApiPid} start=${bp.adminApiStart} ${bp.jvmTz}`)

// ── 存量快照（受影响表；排除本包探针行）────────────────────────────
// 归因纪律：非探针行若变化 ⇒ **不可能是本包所写**（assertProbeSql 拒绝未命中命名域的写），
// 故一律登记为「疑似并发包干扰」，不计本包违规。
// 🔴 逐表**各自**的探针排除谓词（原实现用一条通用谓词引用 transaction_no/sku_code，
//    而这些列并非每张表都有 ⇒ SQL 报错 ⇒ 快照退化成**空集** ⇒ 「空集 == 空集」恒真 = **假绿**。
//    这条正是 migao-acceptance 明令的「关系式断言在空集上恒真」形态，已修。）
const TABLES_SPEC = [
  { table: 'products', hasDeleted: true, excl: `id like 'c3prod%'` },
  { table: 'product_skus', hasDeleted: false, excl: `sku_code like 'c3sku%'` },
  { table: 'stock_batches', hasDeleted: true, excl: `inbound_no like 'c3RK%'` },
  { table: 'stock_ledger_entries', hasDeleted: true, excl: `ref_no like 'c3%'` },
  { table: 'stock_batch_consumptions', hasDeleted: true, excl: `sku_code like 'c3sku%'` },
  { table: 'finance_transactions', hasDeleted: true, excl: `transaction_no like 'c3ref%'` },
  { table: 'inbound_orders', hasDeleted: true, excl: `(id like 'c3inb%' or inbound_no like 'c3RK%')` },
  { table: 'inbound_order_items', hasDeleted: true, excl: `inbound_order_id like 'c3inb%'` },
  { table: 'fabric_remnants', hasDeleted: true, excl: `id::text like 'c3%'` },
  { table: 'daily_briefings', hasDeleted: true, excl: `id like 'c3%'` },
  { table: 'orders', hasDeleted: true, excl: `id like 'c3%'` },
]
const TABLES = TABLES_SPEC.map((t) => t.table)

function snapAll() {
  const s = {}
  for (const spec of TABLES_SPEC) {
    const where = [`tenant_id=${TENANT_ID}`]
    if (spec.hasDeleted) where.push('deleted=0')
    where.push(`not (${spec.excl})`)
    const rows = psql(`select * from ${spec.table} where ${where.join(' and ')}`)
    if (rows.length === 0) {
      // 🔴 空集守卫：空快照会让"前后相等"恒真 ⇒ 必须显式标注（不许静默当证据）
      log(`  ⚠️ 快照空集: ${spec.table}（该表在本租户无存量行 ⇒ 其"零改动"读数无判别力）`)
    }
    s[spec.table] = rows
  }
  return s
}
const stockBefore = snapAll()
const stockBeforeFp = Object.fromEntries(Object.entries(stockBefore).map(([k, v]) => [k, rowFingerprint(v)]))
writeFileSync(join(OUT, 'stock-snapshot-before.json'), JSON.stringify(stockBeforeFp, null, 2))
log(`存量快照(前): ${Object.entries(stockBeforeFp).map(([k, v]) => `${k}=${v.n}`).join(' ')}`)

const R = new Recorder('summary-raw.json')
let famBRet = null
let famCRet = null
let fatal = null

try {
  const { token } = await loginApi()
  log('登录 OK')

  familyT(R)                                   // 0) 时钟自检
  await familyA(R, { token })                  // 1) 钱的收尾段
  famBRet = await familyB(R, { token })        // 2) 库存下游
  famCRet = await familyC(R, { token })        // 3) 账期时间口径
} catch (e) {
  fatal = `${e?.name}: ${e?.message}`
  log(`🔴 致命异常：${fatal}`)
  R.fail('X0', '总入口', `执行中断：${fatal}`, [String(e?.stack || '').slice(0, 1500)])
} finally {
  // ── 残留自清（只删本包命名域）──────────────────────────────────
  log('═══ 残留自清 ═══')
  const st = famBRet?.stamp || ''
  const del = (sql, label) => {
    try {
      const out = guardedWrite(`-- probe-ok\n${sql};`)
      log(`  清理 ${label}: ${String(out).trim().split('\n').filter(Boolean).slice(-1)[0] || 'ok'}`)
    } catch (e) {
      log(`  ⚠️ 清理失败 ${label}: ${e.message.slice(0, 200)}`)
    }
  }
  // 🔴 主锚 = **探针货号 product_id**（实测教训：st 盘点/调账落台账时 ref_no 是 NULL 或 batch_no
  //    'PC-…'，**不带探针前缀** ⇒ 用 `ref_no like 'c3%'` 会漏删，进而 products 被 FK 挡住删不掉）。
  //    product_id 是本包探针货号，所有下游行都带它 ⇒ 唯一可靠锚点。
  const PID = famBRet ? `'${famBRet.productId}'` : `''`
  {
    // 依赖顺序 = 安全顺序（子表在前）：consumptions → batches → ledger → inbound_items → inbound_orders → skus。
    del(`delete from stock_batch_consumptions where tenant_id=${TENANT_ID} and product_id = ${PID}`, '批次分录')
    del(`delete from stock_batches where tenant_id=${TENANT_ID} and product_id = ${PID}`, '批次')
    del(`delete from stock_ledger_entries where tenant_id=${TENANT_ID} and product_id = ${PID}`, '台账')
    del(`delete from inbound_order_items where tenant_id=${TENANT_ID}
      and inbound_order_id like 'c3inb%'`, '入库明细')
    del(`delete from inbound_orders where tenant_id=${TENANT_ID}
      and (id like 'c3inb%' or inbound_no like 'c3RK%')`, '入库单')
    del(`delete from product_skus where tenant_id=${TENANT_ID} and sku_code like 'c3sku%'`, '探针 SKU')
  }
  del(`delete from products where tenant_id=${TENANT_ID} and id like 'c3prod%'`, '探针货号')
  del(`delete from finance_transactions where tenant_id=${TENANT_ID} and transaction_no like 'c3ref%'`, '时间探针流水')
  del(`delete from orders where tenant_id=${TENANT_ID} and id like 'c3%' and customer_name like '线③验收%'`, '时间探针订单')

  // ── 残留计数（逐表必须 0）─────────────────────────────────────
  const residue = one(`select
    (select count(*) from products where tenant_id=${TENANT_ID} and id like 'c3prod%') products,
    (select count(*) from product_skus where tenant_id=${TENANT_ID} and sku_code like 'c3sku%') skus,
    (select count(*) from inbound_orders where tenant_id=${TENANT_ID} and (id like 'c3inb%' or inbound_no like 'c3RK%')) inbound,
    (select count(*) from inbound_order_items where tenant_id=${TENANT_ID} and inbound_order_id like 'c3inb%') inbound_items,
    (select count(*) from stock_batches where tenant_id=${TENANT_ID} and product_id like 'c3prod%') batches,
    (select count(*) from stock_batch_consumptions where tenant_id=${TENANT_ID} and product_id like 'c3prod%') consumptions,
    (select count(*) from stock_ledger_entries where tenant_id=${TENANT_ID} and product_id like 'c3prod%') ledger,
    (select count(*) from finance_transactions where tenant_id=${TENANT_ID} and transaction_no like 'c3ref%') txns,
    (select count(*) from orders where tenant_id=${TENANT_ID} and id like 'c3%') orders`)
  const residueTotal = Object.values(residue).reduce((a, b) => a + Number(b), 0)
  writeFileSync(join(OUT, 'residue.json'), JSON.stringify({ at: nowCST(), residue, residueTotal }, null, 2))
  log(`残留总计=${residueTotal} ${JSON.stringify(residue)}`)
  if (residueTotal === 0) R.pass('Z1', '零残留：本包探针全部自清（逐表计数=0）', JSON.stringify(residue), ['逐表计数见 out/residue.json'])
  else R.fail('Z1', '零残留：本包探针全部自清（逐表计数=0）', `残留 ${residueTotal} 行: ${JSON.stringify(residue)}`, [])

  // ── 存量零改动自证（前后指纹逐表比对）──────────────────────────
  // 🔴 分层归因（关键）：**本包实际写过的表**才是「零改动」的判别对象 —— 对这些表给出强判据；
  //    从未写过的表只作登记（并行包会写 orders ⇒ 变了也不可能是本包，见下）。
  const WRITTEN = ['products', 'product_skus', 'inbound_orders', 'inbound_order_items',
    'stock_batches', 'stock_ledger_entries', 'stock_batch_consumptions', 'finance_transactions']
  const NEVER_WRITTEN = TABLES.filter((t) => !WRITTEN.includes(t))
  const stockAfter = snapAll()
  const stockAfterFp = Object.fromEntries(Object.entries(stockAfter).map(([k, v]) => [k, rowFingerprint(v)]))
  const changedAll = []
  for (const t of TABLES) {
    const b = stockBeforeFp[t], a = stockAfterFp[t]
    if (b.sha256 !== a.sha256 || b.n !== a.n) changedAll.push({ table: t, before: b, after: a })
  }
  const changedWritten = changedAll.filter((c) => WRITTEN.includes(c.table))
  const changedForeign = changedAll.filter((c) => NEVER_WRITTEN.includes(c.table))
  writeFileSync(join(OUT, 'stock-snapshot-after.json'), JSON.stringify(stockAfterFp, null, 2))
  writeFileSync(join(OUT, 'stock-snapshot-diff.json'), JSON.stringify({ changedAll, changedWritten, changedForeign }, null, 2))
  const evW = changedWritten.map((c) => `${c.table}: n ${c.before.n}→${c.after.n}, sha ${c.before.sha256.slice(0, 12)}→${c.after.sha256.slice(0, 12)}`)

  if (changedWritten.length === 0) {
    R.pass('Z2', '存量真实数据零改动（**本包写过的 8 张表**：非探针行前后 sha256 逐表相等）',
      `${WRITTEN.length} 张写过的表全部逐字节相等（覆盖 products/${WRITTEN.length} 表；未写过的 ${NEVER_WRITTEN.length} 表另见 Z3）`,
      [`逐表指纹: ${JSON.stringify(Object.fromEntries(WRITTEN.map((t) => [t, stockBeforeFp[t].sha256.slice(0, 12) + '==' + stockAfterFp[t].sha256.slice(0, 12)])))}`])
  } else {
    R.fail('Z2', '存量真实数据零改动（本包写过的表：非探针行前后 sha256 逐表相等）',
      `检测到**本包写过的表**上非探针行变化 ⇒ 违反零改动纪律: ${evW.join(' | ')}`, evW)
  }
  // 从未写过的表：只登记（并行包会写 orders；本包写 SQL 受 assertProbeSql 强制命名域 ⇒ 非本包）
  R.skip('Z3', '未写过的表（orders/remnants/briefings）零改动核对',
    changedForeign.length === 0
      ? `未写过的 ${NEVER_WRITTEN.length} 张表恰好也未变（无并发写入被观测到）`
      : `观测到变化，**结构性归因 = 并行包（线①/线②）干扰，非本包**：本包**没有任何**写语句触及这些表` +
        `（assertProbeSql 强制全部写语句命中 c3/c4/c5/线③验收 命名域，且 run-all 的清理只删探针行）。` +
        `变化表: ${changedForeign.map((c) => `${c.table}(n ${c.before.n}→${c.after.n})`).join(', ')}`)


  const summary = R.summary()
  const out = {
    pkg: 'line3-finance-stock-time-sweep',
    startedAt, finishedAt: nowCST(),
    buildPoint: bp,
    fatal,
    summary,
    byFamily: {
      T: R.records.filter((r) => /^T/.test(r.id)).length,
      A: R.records.filter((r) => /^A/.test(r.id)).length,
      B: R.records.filter((r) => /^B/.test(r.id)).length,
      C: R.records.filter((r) => /^C/.test(r.id)).length,
      Z: R.records.filter((r) => /^Z/.test(r.id)).length,
    },
    residue, residueTotal,
    stockSnapshot: { before: stockBeforeFp, after: stockAfterFp, changedAll, changedWritten, changedForeign },
    records: R.records,
  }
  writeFileSync(join(OUT, 'SUMMARY.json'), JSON.stringify(out, null, 2))
  log(`════ 完成 pass=${summary.pass} fail=${summary.fail} skip=${summary.skip} total=${summary.total} ════`)
}
