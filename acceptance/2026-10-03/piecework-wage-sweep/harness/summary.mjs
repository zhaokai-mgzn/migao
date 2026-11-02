// 汇总：以 out/run.log 为**唯一**断言流水（每次 Recorder.add 都同步落盘一行），
// 再对同名 id 取**最后一次**读数（= 最新重跑结果），并标注被取代的首轮失败。
import { readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
const OUT = 'out'
const lines = readFileSync(join(OUT, 'run.log'), 'utf8').split('\n')
const recs = []
for (const l of lines) {
  const m = /^(\S+)\s+(✅|❌|⏭️)\s+\[([\w.\-]+)\]\s+(.*?)\s+—\s+(.*)$/.exec(l.trim())
  if (!m) continue
  recs.push({
    at: m[1], status: m[2] === '✅' ? 'pass' : m[2] === '❌' ? 'fail' : 'skip',
    id: m[3], name: m[4], detail: m[5],
  })
}
// 同名 id 取最后一次（重跑覆盖）；同时记录被覆盖的历史失败
const latest = new Map(), history = new Map()
for (const r of recs) {
  if (latest.has(r.id)) {
    const prev = latest.get(r.id)
    if (prev.status === 'fail') (history.get(r.id) ?? history.set(r.id, []).get(r.id)).push(prev)
  }
  latest.set(r.id, r)
}
const rows = [...latest.values()]
const c = { pass: 0, fail: 0, skip: 0 }
rows.forEach((r) => c[r.status]++)
const superseded = [...history.entries()].map(([id, arr]) => ({ id, earlier: arr.map((a) => `${a.status}@${a.at}`) }))
const summary = {
  at: new Date().toISOString(),
  note: '读数 = out/run.log 中每条断言的最后一次；同名 id 的重跑覆盖旧值（被覆盖的首轮失败列在 supersededFails）',
  totals: { ...c, total: rows.length, supersededFailCount: superseded.length },
  supersededFails: superseded,
  rows: rows.sort((a, b) => a.id.localeCompare(b.id)),
}
writeFileSync(join(OUT, 'SUMMARY.json'), JSON.stringify(summary, null, 2))
console.log('TOTALS', JSON.stringify(summary.totals))
const byPrefix = {}
for (const r of rows) { const p = r.id.split('-')[0]; byPrefix[p] = byPrefix[p] || { pass: 0, fail: 0, skip: 0 }; byPrefix[p][r.status]++ }
console.log('by suite:', JSON.stringify(byPrefix))
console.log('FAILS:', rows.filter((r) => r.status === 'fail').map((r) => r.id).join(',') || '-')
console.log('SKIPS:', rows.filter((r) => r.status === 'skip').map((r) => r.id).join(',') || '-')
console.log('superseded:', JSON.stringify(superseded))
