// p8-stock-before —— 记录「存量行零改动」的**前**快照（p9 清理后对照用）
// 用法：node p8-stock-before.mjs
import { writeFileSync } from 'node:fs'
import { psql, sha256, outPath, log, nowCST, TENANT_ID, PROBE_PREFIX } from './lib.mjs'

const parts = []
parts.push(JSON.stringify(psql(`select id::text, status, refund_amount::text, actual_amount::text, deleted::text
                                from orders where tenant_id=${TENANT_ID} and (remark is null or remark not like '${PROBE_PREFIX}%')
                                order by id`)))
parts.push(JSON.stringify(psql(`select id, status, refund_amount::text, deleted::text
                                from after_sales_tickets where tenant_id=${TENANT_ID} and (description is null or description not like '${PROBE_PREFIX}%')
                                order by id`)))
// ⚠️ 台账/流水**不参与 sha 对照**：同租户的线A 并发包也在写这两张表（实测其行数在两次对照之间 +28）
//    ⇒ 把它们算进「零改动」会把**外来写**读成本包的问题（假红）。改为**只取读数 + 按行内容归因**。
parts.push(JSON.stringify(psql(`select count(*)::text as c from stock_ledger_entries where tenant_id=${TENANT_ID}`)))
parts.push(JSON.stringify(psql(`select count(*)::text as c from finance_transactions where tenant_id=${TENANT_ID} and type='refund'`)))

const snap = { at: nowCST(), sha: sha256(parts.join('|')), sizes: parts.map((p) => p.length), parts }
writeFileSync(outPath('B9-stock-before.json'), JSON.stringify(snap, null, 2))
log(`存量行基线快照已记录：sha256=${snap.sha.slice(0, 16)}…（orders/tickets 逐行 + 台账/退款流水 count·sum）`)
