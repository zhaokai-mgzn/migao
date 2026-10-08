// P6 — 存量零改动（口径修正）+ 终态零残留复读
//
// 🔴 为什么需要这一段：run-all 里第一次比较的是**全表**指纹，而清理会删掉本包探针行
// ⇒ 指纹必变（如实测 orders 411→366）。那是**预期变化**，不是「存量被改」。
// 本段把命题写准：**排除本包 `la` 命名域后，存量行逐字节相同 + 逐表行数相同**。
import { writeFileSync, readFileSync, existsSync, outPath } from './lib.mjs'
import { log, nowCST, ledgerHash, probeResidue, tableCounts, psql, TENANT_ID, ID_PREFIX } from './lib.mjs'

const out = { at: nowCST(), probePrefix: ID_PREFIX }
out.residue = probeResidue()
out.residueClean = out.residue.total === 0
out.tableCounts = tableCounts()

// 存量指纹（排除探针域）——基线取本次会话最早的读数：用 p0 之前**前置清理刚跑完**的时刻不可回放，
// ⇒ 改用一个可复算的等价口径：同一份 SELECT 现在取一次，并与「排除探针行」的**全表行数**一起留档；
// 真正的「前后对照」由 run-all 的 `ledgerBefore/After`（同一口径）承担，这里补一条**可复核**的读数：
out.ledgerExisting = ledgerHash({ excludeProbe: true })

// 逐表「存量行数 + 探针行数」分列（读得懂、可复核）
out.perTable = {}
for (const t of ['orders', 'processing_orders', 'processing_position_operations', 'processing_set_part_tokens', 'production_work_logs', 'worker_report_audits', 'users', 'worker_sessions', 'inbound_labels', 'client_request_keys']) {
  const r = psql(`select
      count(*) filter (where coalesce(id::text,'') like '${ID_PREFIX}%')::int as probe,
      count(*) filter (where coalesce(id::text,'') not like '${ID_PREFIX}%')::int as existing
    from ${t} where tenant_id=${TENANT_ID}`)[0]
  out.perTable[t] = { probe: r?.probe ?? null, existing: r?.existing ?? null }
}
// 交叉核对：probe 计数必须全 0；existing 行数由上面的 perTable 给出（供下一轮对照）
out.probeAllZero = Object.values(out.perTable).every((v) => v.probe === 0)

writeFileSync(outPath('Z-baseline.json'), JSON.stringify(out, null, 2))
log(`P6: 残留=${out.residue.total}（clean=${out.residueClean}）探针行全 0=${out.probeAllZero} 存量指纹=${out.ledgerExisting.hash.slice(0, 16)}`)
log(`P6 逐表: ${JSON.stringify(out.perTable)}`)
process.exit(0)
