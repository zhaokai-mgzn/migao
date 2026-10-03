// run-all —— 一键重跑本包全部判据（顺序即安全顺序：手表 → 基线 → 夹具 → 判据 → 清理 → 汇总）
// 用法：API_BASE=http://127.0.0.1:8080 node run-all.mjs
//       SEGMENTS=p0,p8,p1,p2,p3,p4,p5,p6,p9 node run-all.mjs     # 只跑指定段
//       SKIP_RUN=1 node run-all.mjs                              # 只做清理+汇总（不重跑判据）
import { execFileSync } from 'node:child_process'
import { writeFileSync, readFileSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { buildPoint, OUT, outPath, log, nowCST, cleanupProbe, probeResidue, readFileSync as rf } from './lib.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))

// ── 0. 构建点自证（本包一切读数的坐标）──
const bp = buildPoint()
const envRound3 = existsSync(outPath('../../env/env-round3.json')) ? JSON.parse(rf(outPath('../../env/env-round3.json'), 'utf8')) : null
writeFileSync(outPath('B0-buildpoint.json'), JSON.stringify({ ...bp, envRound3 }, null, 2))
log(`构建点：main-live HEAD=${bp.shaFull}（pid ${bp.pid}，启动 ${bp.adminApiStart}）origin/main=${bp.originMain}`)

// ── 1. 段（顺序即安全顺序）──
const DEFAULT_SEGMENTS = ['p0-env', 'p8-stock-before', 'p1-setup', 'p2-b1-serial', 'p3-b2-concurrency', 'p4-probe-batch', 'p5-refund-precision', 'p6-order-status-control', 'p7-refund-negative', 'p10-dispatch-concurrency', 'p9-cleanup']
const ALIAS = {
  p0: 'p0-env', p8: 'p8-stock-before', p1: 'p1-setup', p2: 'p2-b1-serial',
  p3: 'p3-b2-concurrency', p4: 'p4-probe-batch', p5: 'p5-refund-precision',
  p6: 'p6-order-status-control', p7: 'p7-refund-negative', p10: 'p10-dispatch-concurrency', p9: 'p9-cleanup',
}
const SEGMENTS = process.env.SEGMENTS
  ? process.env.SEGMENTS.split(',').map((s) => ALIAS[s.trim()] || s.trim())
  : DEFAULT_SEGMENTS
const results = {}
if (process.env.SKIP_RUN !== '1') {
  for (const seg of SEGMENTS) {
    const f = join(HERE, `${seg}.mjs`)
    if (!existsSync(f)) { results[seg] = { status: 'MISSING' }; log(`⚠️ 缺段 ${seg}`); continue }
    log(`▶ 运行 ${seg}`)
    let code = 0, out = ''
    try { out = execFileSync(process.execPath, [f], { env: { ...process.env }, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 }) }
    catch (e) { code = e.status ?? 1; out = (e.stdout ?? '') + (e.stderr ?? '') }
    results[seg] = { status: code === 0 ? 'ok' : `exit ${code}`, tail: out.split('\n').filter(Boolean).slice(-2).join(' | ') }
    log(`◀ ${seg} ${code === 0 ? 'ok' : 'exit ' + code}`)
  }
}

// ── 2. 终态零残留（兜底再清一次并复读）──
let cleanupErr = null
try { cleanupProbe() } catch (e) { cleanupErr = e.message }
const residue = probeResidue()
writeFileSync(outPath('Z-residue.json'), JSON.stringify({ cleanupError: cleanupErr, residue, at: nowCST(), clean: residue.total === 0 }, null, 2))

// ── 3. 汇总 out/SUMMARY.json ──
const FILES = ['B0-env.json', 'B1-setup.json', 'B1-serial.json', 'B2-concurrency.json', 'B4-probe-batch.json', 'B5-refund-precision.json', 'B6-order-status-control.json', 'B7-refund-negative.json', 'B10-dispatch-concurrency.json', 'B9-cleanup.json']
const GROUP = { 'B0-env.json': 'B0-环境自证', 'B1-setup.json': 'B1-夹具', 'B1-serial.json': 'B1-售后退款闭环(串行)', 'B2-concurrency.json': 'B2-并发竞态', 'B4-probe-batch.json': 'B2/B1-补强探针', 'B5-refund-precision.json': 'B1-涉钱精度', 'B6-order-status-control.json': 'B2-正对照', 'B7-refund-negative.json': 'B1-退款负例补强', 'B10-dispatch-concurrency.json': 'B2-并发派工', 'B9-cleanup.json': 'Z-零残留' }
const perFile = {}
const items = []
const counts = { pass: 0, fail: 0, skip: 0, falseRed: 0, total: 0 }
for (const f of FILES) {
  const p = outPath(f)
  if (!existsSync(p)) { perFile[f] = { status: 'MISSING' }; continue }
  const j = JSON.parse(readFileSync(p, 'utf8'))
  perFile[f] = j.summary
  for (const k of Object.keys(counts)) counts[k] += (j.summary[k] || 0)
  for (const r of j.records) {
    items.push({
      id: r.id, group: GROUP[f] || f, name: r.name, verdict: r.status,
      detail: r.detail, evidence: r.evidence, at: r.at,
      redProof: (r.evidence || []).filter((e) => /红证|注入|判别力|自曝/.test(e)).join(' ⏐ ') || null,
      concurrency: r.extra?.N ? { N: r.extra.N, rounds: r.extra.rounds, overlapEvidence: r.extra.overlapEvidence } : undefined,
      extra: r.extra,
    })
  }
}
const byGroup = {}
for (const it of items) {
  byGroup[it.group] = byGroup[it.group] || { pass: 0, fail: 0, skip: 0, falseRed: 0, total: 0 }
  byGroup[it.group][it.verdict] = (byGroup[it.group][it.verdict] || 0) + 1
  byGroup[it.group].total++
}
const SUMMARY = {
  package: 'acceptance/2026-10-03/aftersales-concurrency-sweep（线B）',
  generatedAt: nowCST(),
  buildPoint: {
    worktree: bp.worktree, sha: bp.sha, shaFull: bp.shaFull, subject: bp.subject,
    commitTime: bp.commitTime, originMain: bp.originMain, adminApiPid: bp.pid, adminApiStart: bp.adminApiStart,
    observedAt: bp.observedAt.cst, evidence: `git -C ${bp.worktree} rev-parse HEAD ⇒ ${bp.shaFull}`,
    envRound3File: 'acceptance/2026-10-03/env/env-round3.json',
  },
  counts, byGroup, perFile,
  items,
  residue,
  segments: results,
  notes: [
    '四态 = pass / fail(产品) / falseRed(判据缺陷或无判别力) / skip(未覆盖)；**skip 永不记 pass**',
    '本包**不下**「验收通过/交付完成」结论（不自我验收）',
    '并发族的每一项都带 N / rounds[3] / overlapEvidence（重叠证据）；未真重叠时判 falseRed 而非 pass',
    '所有红证都只在**本包自建临时表 / 副本**上注入，未改任何产品源码',
  ],
}
writeFileSync(outPath('SUMMARY.json'), JSON.stringify(SUMMARY, null, 2))
log(`汇总：counts=${JSON.stringify(counts)}；零残留=${residue.total === 0}（${JSON.stringify(residue.counts)}）`)
log(`产物：out/SUMMARY.json（${items.length} 条判据）`)
