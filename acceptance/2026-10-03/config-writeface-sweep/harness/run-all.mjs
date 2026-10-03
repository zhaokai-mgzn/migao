// 一键跑完整个横切扫描（P1..P6）并汇总读数。
// 用法：REPO_ROOT=<repo> OUT_DIR=<out> node harness/run-all.mjs
//
// 为什么串行：同一租户上并发跑多条探针会让「谁改的」不可归因（另一并行包已在写同一批表）
// —— 本脚本**故意串行**，每次只有一个写者（除了那个并行包，我们无法控制它，只能按内容归因）。
import { spawnSync } from 'node:child_process'
import { readFileSync, writeFileSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const OUT = process.env.OUT_DIR || join(HERE, '..', 'out')
const REPO_ROOT = process.env.REPO_ROOT || join(HERE, '..', '..', '..', '..')
const PROBES = ['p1-selftest-f8', 'p2-operations', 'p3-positions', 'p4-routes', 'p5-rules', 'p6-other-config']

const results = []
for (const p of PROBES) {
  const started = new Date().toISOString()
  const r = spawnSync('node', [join(HERE, `${p}.mjs`)], {
    env: { ...process.env, REPO_ROOT, OUT_DIR: OUT },
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
  })
  const ended = new Date().toISOString()
  const out = (r.stdout || '') + (r.stderr || '')
  const MAP = { 'p1-selftest-f8': 'p1-selftest-f8.json', 'p2-operations': 'p2-operations.json', 'p3-positions': 'p3-positions.json', 'p4-routes': 'p4-routes.json', 'p5-rules': 'p5-rules.json', 'p6-other-config': 'p6-other-config.json' }
  const jsonFile = join(OUT, MAP[p])
  let records = []
  try { records = JSON.parse(readFileSync(jsonFile, 'utf8')) } catch { /* 未产出 */ }
  const c = (s) => records.filter((x) => x.status === s).length
  results.push({ probe: p, exit: r.status, started, ended, pass: c('pass'), fail: c('fail'), skip: c('skip'), total: records.length,
    failures: records.filter((x) => x.status === 'fail').map((x) => `${x.id}: ${x.name} — ${String(x.detail).slice(0, 180)}`) })
  console.log(`[${p}] exit=${r.status} pass=${c('pass')} fail=${c('fail')} skip=${c('skip')} total=${records.length}`)
  writeFileSync(join(OUT, `raw-${p}.log`), out)
}
writeFileSync(join(OUT, 'run-all-summary.json'), JSON.stringify({ results, generatedAt: new Date().toISOString() }, null, 2))
const totals = results.reduce((a, r) => ({ pass: a.pass + r.pass, fail: a.fail + r.fail, skip: a.skip + r.skip, total: a.total + r.total }), { pass: 0, fail: 0, skip: 0, total: 0 })
console.log('TOTAL', JSON.stringify(totals))
if (!existsSync(join(OUT, 'run-all-summary.json'))) process.exit(3)
