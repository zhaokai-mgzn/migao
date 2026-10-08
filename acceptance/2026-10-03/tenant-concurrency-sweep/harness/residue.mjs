// 零残留读数：对**所有含 tenant_id 的表**逐表计数 + 前缀标记扫描（`并发验收` 与 `probe`）
// 用法：node residue.mjs snap-before | snap-after | diff | marker
import { psql, log, OUT } from './lib.mjs'
import { writeFileSync, readFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'

const mode = process.argv[2] || 'snap-before'
const T = [1, 20, 21]
const tables = psql("select table_name from information_schema.columns where table_schema='public' and column_name='tenant_id' group by 1 order by 1").map((r) => r.table_name)
log(`含 tenant_id 表 ${tables.length} 张；模式=${mode}`)

function snapshot() {
  const out = {}
  for (const t of tables) {
    const cnt = psql(`select tenant_id, count(*)::int as c from ${t} where tenant_id in (${T.join(',')}) group by 1`)
    const per = {}; for (const c of T) per[c] = 0
    for (const r of cnt) per[Number(r.tenant_id)] = r.c
    // 行指纹（id 集合的哈希近似：排序后拼接的 md5 由 DB 算）
    const fp = psql(`select tenant_id, coalesce(md5(string_agg(id::text, ',' order by id::text)),'-') as fp from ${t} where tenant_id in (${T.join(',')}) group by 1`)
    const fps = {}; for (const c of T) fps[c] = '-'
    for (const r of fp) fps[Number(r.tenant_id)] = r.fp
    out[t] = { counts: per, fps }
  }
  return out
}

if (mode === 'marker') {
  const hits = []
  for (const t of tables) {
    const cols = psql(`select column_name, data_type from information_schema.columns where table_schema='public' and table_name='${t}'`).filter((c) => ['text', 'character varying', 'jsonb', 'json'].includes(c.data_type))
    if (!cols.length) continue
    const cond = cols.map((c) => {
      const cast = c.data_type === 'jsonb' || c.data_type === 'json' ? `${c.column_name}::text` : `${c.column_name}`
      return `${cast} like '%并发验收%' or ${cast} like '%probe-%'`
    }).join(' or ')
    try {
      const n = psql(`select count(*)::int c from ${t} where (${cond})`)[0].c
      if (n > 0) hits.push({ table: t, rows: n })
    } catch (e) { hits.push({ table: t, error: String(e.message).slice(0, 80) }) }
  }
  writeFileSync(join(OUT, 'residue-marker.json'), JSON.stringify(hits, null, 2))
  log(`前缀标记（并发验收/probe-）命中表：${JSON.stringify(hits)}`)
} else if (mode === 'snap-before') {
  writeFileSync(join(OUT, 'residue-before.json'), JSON.stringify(snapshot(), null, 2))
  log('baseline 已落盘 out/residue-before.json')
} else if (mode === 'snap-after') {
  writeFileSync(join(OUT, 'residue-after.json'), JSON.stringify(snapshot(), null, 2))
  const before = JSON.parse(readFileSync(join(OUT, 'residue-before.json'), 'utf8'))
  const after = JSON.parse(readFileSync(join(OUT, 'residue-after.json'), 'utf8'))
  const diff = []
  for (const t of tables) {
    for (const tn of T) {
      const b = before[t]?.counts?.[tn] ?? 0, a = after[t]?.counts?.[tn] ?? 0
      const bf = before[t]?.fps?.[tn], af = after[t]?.fps?.[tn]
      if (a !== b || bf !== af) diff.push({ table: t, tenant: tn, before: b, after: a, countDelta: a - b, fpChanged: bf !== af })
    }
  }
  writeFileSync(join(OUT, 'residue-diff.json'), JSON.stringify({ tables: tables.length, tenants: T.length, cells: tables.length * T.length, changed: diff }, null, 2))
  log(`残留比对：${tables.length}×${T.length}=${tables.length * T.length} 格，变化 ${diff.length} 格`)
  for (const d of diff) log(`  变更 ${d.table}#${d.tenant}: 行数 ${d.before}→${d.after}，指纹变=${d.fpChanged}`)
}
