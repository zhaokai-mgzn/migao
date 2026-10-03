// run-all — 顺序跑全部段（顺序即安全顺序：先取证、后清理、最后零残留）
// 用法：API_BASE=http://127.0.0.1:8080 node run-all.mjs
import { execFileSync } from 'node:child_process'
import { writeFileSync, readFileSync, existsSync, rmSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { buildPoint, OUT, outPath, log, nowCST, cleanupProbe, probeResidue } from './lib.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))

const bp = buildPoint()
writeFileSync(outPath('buildpoint.json'), JSON.stringify(bp, null, 2))

// 构建点切换台账（主会话实测：13:44:16 +08 进程被换过）
const SHIFT = {
  from: { worktree: bp.worktree, sha: 'd1c09d02f', subject: 'chore(ci): flaky 台账追加（run 37096947254） (#6183)', adminApiStart: '2026-10-03 13:09:45 +08', pid: 99086 },
  to: { worktree: bp.worktree, sha: bp.sha, subject: bp.subject, adminApiStart: bp.adminApiStart, pid: bp.pid },
  switchAt: '2026-10-03 13:44:16 +08',
  observedAt: nowCST(),
}
writeFileSync(outPath('buildpoint-shift.json'), JSON.stringify(SHIFT, null, 2))
log(`构建点：当前 ${bp.sha}（pid ${bp.pid}，启动 ${bp.adminApiStart}）；切换点 ${SHIFT.switchAt}（前 ${SHIFT.from.sha}）`)

const SEGMENTS = process.env.SEGMENTS ? process.env.SEGMENTS.split(',') : ['a1-import-export', 'b1-batch-detach', 'd1-uploads', 'e1-concurrency', 'f1-redproof']
if (process.env.SKIP_RUN === '1') SEGMENTS.length = 0   // 只汇总/只做零残留（不重跑）
const results = {}
for (const seg of SEGMENTS) {
  const f = join(HERE, `${seg}.mjs`)
  if (!existsSync(f)) { results[seg] = { status: 'MISSING' }; continue }
  log(`▶ 运行 ${seg}`)
  let code = 0, out = ''
  try {
    out = execFileSync(process.execPath, [f], { env: { ...process.env }, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 })
  } catch (e) { code = e.status ?? 1; out = (e.stdout ?? '') + (e.stderr ?? '') }
  results[seg] = { status: code === 0 ? 'ok' : `exit ${code}`, tail: out.split('\n').slice(-3).join('\n') }
  log(`◀ ${seg} ${code === 0 ? 'ok' : 'exit ' + code}`)
}

// ── 终态零残留：清理 + 逐表计数 ──
log('终态清理与零残留自证')
let cleanupErr = null
try { cleanupProbe() } catch (e) { cleanupErr = e.message }
const residue = probeResidue()
writeFileSync(outPath('Z-residue.json'), JSON.stringify({
  cleanupError: cleanupErr, residue, at: nowCST(),
  clean: residue.total === 0,
}, null, 2))

// ── 汇总 ──
const FILES = ['A-import-export.json', 'B-batch-and-detach.json', 'D-uploads.json', 'E-concurrency-and-redproof.json', 'F-redproof.json']
const perSuite = {}
const totals = { pass: 0, fail: 0, skip: 0, total: 0 }
const allFail = []
const allSkip = []
for (const f of FILES) {
  const p = outPath(f)
  if (!existsSync(p)) { perSuite[f] = { status: 'MISSING' }; continue }
  const j = JSON.parse(readFileSync(p, 'utf8'))
  perSuite[f] = j.summary
  for (const k of ['pass', 'fail', 'skip', 'total']) totals[k] += j.summary[k]
  for (const r of j.records) {
    if (r.status === 'fail') allFail.push({ suite: f, id: r.id, name: r.name, detail: r.detail, at: r.at })
    if (r.status === 'skip') allSkip.push({ suite: f, id: r.id, name: r.name, detail: r.detail })
  }
}
const SUMMARY = {
  buildPoint: { worktree: bp.worktree, sha: bp.sha, shaFull: bp.shaFull, subject: bp.subject, adminApiStart: bp.adminApiStart, originMain: bp.originMain },
  buildPointShift: SHIFT,
  window: { start: nowCST().cst, utc: nowCST().utc },
  perSuite, totals, failures: allFail, skips: allSkip,
  residue, segments: results,
  note: 'fail 桶中 F4 是**故意的失效控制项**（必须红，不计缺陷）；判据缺陷（假红）单列在 REPORT §7',
}
writeFileSync(outPath('SUMMARY.json'), JSON.stringify(SUMMARY, null, 2))
log(`汇总: ${JSON.stringify(totals)}；零残留=${residue.total === 0}（${JSON.stringify(residue.counts)}）`)
log(`构建点: ${bp.sha} @ ${bp.adminApiStart}`)
