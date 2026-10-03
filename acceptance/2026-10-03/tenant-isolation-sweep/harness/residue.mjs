// 零残留 / 零写入读数：全表（含 tenant_id 的表）行数 + updated_at 最大值 + 行指纹校验和
// 用法：node harness/residue.mjs snap-before | snap-after | diff
import { writeFileSync, readFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { psql, log } from '../../config-writeface-sweep/harness/lib.mjs'
const OUT = fileURLToPath(new URL('../out/', import.meta.url))
const TABLES = ['products','product_skus','customer_profiles','customer_tags','categories','production_operations',
 'production_operation_positions','production_route_templates','production_route_rules','processing_fee_combinations',
 'processing_items','processing_categories','orders','order_items','processing_orders','inbound_orders','order_shipments',
 'agent_sessions','notification_templates','notification_rules','knowledge_cards','roles','after_sales_tickets',
 'users','agent_employees','stock_batches','stock_ledger_entries','finance_transactions','fabric_remnants','sessions','tenants','platform_admins']
const mode = process.argv[2] ?? 'snap'
const file = OUT + 'residue-' + (mode === 'snap-after' ? 'after' : 'before') + '.json'
if (mode.startsWith('snap')) {
  const snap = {}
  for (const t of TABLES) {
    const hasDel = psql(`select 1 x from information_schema.columns where table_schema='public' and table_name='${t}' and column_name='deleted'`).length > 0
    const hasUpd = psql(`select 1 x from information_schema.columns where table_schema='public' and table_name='${t}' and column_name='updated_at'`).length > 0
    const hasTen = psql(`select 1 x from information_schema.columns where table_schema='public' and table_name='${t}' and column_name='tenant_id'`).length > 0
    if (!hasTen) { snap[t] = { rows: psql(`select count(*)::int n from ${t}`)[0].n, max_updated: hasUpd ? psql(`select max(updated_at)::text m from ${t}`)[0].m : null, checksum: psql(`select md5(string_agg(id::text || '|' || ${hasDel ? 'coalesce(deleted,0)::text' : "''"}, ',' order by id::text)) c from ${t}`)[0].c }; continue }
    snap[t] = {}
    for (const ten of [1, 20, 21]) {
      const where = `tenant_id=${ten}` + (hasDel ? ' and coalesce(deleted,0)=0' : '')
      // 单次往返取「行数 + updated_at 最大值 + id/deleted/updated_at 指纹 + 内容指纹（截断降本）」
      const q = `select count(*)::int n,
          ${hasUpd ? 'max(updated_at)::text' : 'null::text'} m,
          md5(coalesce(string_agg(id::text || '|' || ${hasDel ? 'coalesce(deleted,0)::text' : "''"} || '|' || ${hasUpd ? "coalesce(updated_at::text,'')" : "''"}, ';' order by id::text),'')) idfp,
          md5(coalesce(string_agg(left(t::text, 320), ';' order by id::text),'')) rowfp
        from (select *, ${hasDel ? 'coalesce(deleted,0)' : '0'} as _d from ${t} where ${where}) t`
      const r0 = psql(q)[0]
      snap[t][ten] = { alive: r0.n, max_updated: r0.m, idfp: r0.idfp, rowfp: r0.rowfp }
    }
  }
  writeFileSync(file, JSON.stringify(snap, null, 1)); log(`[residue] ${mode} 已写 ${file}`)
} else {
  const b = JSON.parse(readFileSync(OUT + 'residue-before.json', 'utf8')), a = JSON.parse(readFileSync(OUT + 'residue-after.json', 'utf8'))
  const diffs = []
  for (const t of Object.keys(b)) for (const ten of Object.keys(b[t])) {
    const x = b[t][ten], y = a[t][ten]
    if (JSON.stringify(x) !== JSON.stringify(y)) diffs.push({ table: t, tenant: ten, before: x, after: y,
      kind: x.alive !== y.alive ? '行数变' : (x.idfp !== y.idfp ? 'id/deleted/updated_at 指纹变' : (x.rowfp !== y.rowfp ? '行内容指纹变（同 id 同 updated_at 但字段变）' : 'max_updated 变')) })
  }
  writeFileSync(OUT + 'residue-diff.json', JSON.stringify(diffs, null, 1))
  log(`[residue] 表×租户 快照项=${Object.values(b).reduce((n, x) => n + Object.keys(x).length, 0)}，变更项=${diffs.length}`)
  for (const d of diffs) log(`  ⚠️ ${d.table}#${d.tenant} ${d.kind}  before=${JSON.stringify(d.before)} after=${JSON.stringify(d.after)}`)
}
