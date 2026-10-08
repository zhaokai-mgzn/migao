// run-all（线② 2026-10-04 版）—— 一键重跑：手表 → 基线 → 夹具 → 判据 → 清理 → 汇总
//
// 复用底座 `acceptance/2026-10-03/aftersales-concurrency-sweep/harness/`（**底座文件未改**）：
//   · 段文件解析顺序 = 本目录优先，其次底座目录（本目录只放「需按新环境改写」的段：
//     p0-env / p1-setup / p2-b1-serial / p10-dispatch-concurrency；其余段与底座逐字相同）
//   · 共享库 = 本目录的 lib.mjs（指向底座 lib.mjs 的软链，逐字同一份）
//   · OUT_DIR / REPO_ROOT 一律**绝对化**后传给子段（避免相对路径在不同 cwd 下漂移）
import { execFileSync } from 'node:child_process'
import { writeFileSync, readFileSync, existsSync, unlinkSync } from 'node:fs'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { buildPoint, OUT, outPath, log, nowCST, cleanupProbe, probeResidue } from './lib.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const BASE = resolve(HERE, '..', '..', '..', '2026-10-03', 'aftersales-concurrency-sweep', 'harness')
const OUT_ABS = resolve(OUT)
const REPO = resolve(process.env.REPO_ROOT || join(HERE, '..', '..', '..', '..'))
const CHILD_ENV = { ...process.env, OUT_DIR: OUT_ABS, REPO_ROOT: REPO }

const bp = buildPoint()
writeFileSync(outPath('R0-local-buildpoint.json'), JSON.stringify({ ...bp, note: '本地旧构建点（LIVE_WORKTREE），非被测面' }, null, 2))
log(`run-all 启动：API_BASE=${process.env.API_BASE} TENANT_ID=${process.env.TENANT_ID} ADMIN_PHONE=${process.env.ADMIN_PHONE}`)
log(`  本地工作树（**非被测面**）= ${bp.shaFull}；共享库 = ${HERE}/lib.mjs（软链）`)

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
    const local = join(HERE, `${seg}.mjs`)
    const f = existsSync(local) ? local : join(BASE, `${seg}.mjs`)
    if (!existsSync(f)) { results[seg] = { status: 'MISSING' }; log(`⚠️ 缺段 ${seg}`); continue }
    const src = f === local ? 'overlay' : 'base'
    log(`▶ 运行 ${seg} (${src})`)
    let code = 0, out = ''
    try { out = execFileSync(process.execPath, [f], { env: CHILD_ENV, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 }) }
    catch (e) { code = e.status ?? 1; out = (e.stdout ?? '') + (e.stderr ?? '') }
    results[seg] = { status: code === 0 ? 'ok' : `exit ${code}`, source: src, tail: out.split('\n').filter(Boolean).slice(-3).join(' | ') }
    log(`◀ ${seg} ${code === 0 ? 'ok' : 'exit ' + code}`)
  }
}

// ── 终态零残留（兜底再清一次并复读）──
// 顺序即安全顺序：① 先清**其他线② 的残留行进表** ② 底座 cleanupProbe（删商品/订单/工单/台账…）
// ③ 再清本线新增域的「探针分类」—— 分类被 products.category_id FK 引用 ⇒ **必须晚于**商品删除
//    （实测：顺序反了 ⇒ FK 违例，分类残留 —— 那是本包 harness 的缺陷，不是产品缺陷）
let cleanupErr = null
try { cleanupProbe() } catch (e) { cleanupErr = e.message }
// ③ 收尾不落凭据：登录 token（out/.token）用后即删（避免临时管理员凭据留在产物目录）
let tokenRemoved = false
try { writeFileSync(outPath('.token'), ''); const f = outPath('.token'); if (existsSync(f)) { unlinkSync(f); tokenRemoved = true } } catch { /* 非致命 */ }
if (existsSync(join(HERE, 'cleanup-extra.mjs'))) {
  try { execFileSync(process.execPath, [join(HERE, 'cleanup-extra.mjs')], { env: CHILD_ENV, encoding: 'utf8' }) }
  catch (e) { log(`⚠️ cleanup-extra 非零退出：${String((e.stdout ?? '') + (e.stderr ?? '')).split('\n').filter(Boolean).slice(-2).join(' | ')}`) }
}
const residue = probeResidue()
writeFileSync(outPath('Z-residue.json'), JSON.stringify({ cleanupError: cleanupErr, residue, at: nowCST(), clean: residue.total === 0 }, null, 2))

// ── 汇总 out/SUMMARY.json ──
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
      redProof: (r.evidence || []).filter((e) => /红证|注入|判别力|自曝|负对照/.test(e)).join(' ⏐ ') || null,
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
const deployPoint = existsSync(outPath('E0-deploypoint.json')) ? JSON.parse(readFileSync(outPath('E0-deploypoint.json'), 'utf8')) : null
const SUMMARY = {
  line: '②售后退款',
  package: 'acceptance/2026-10-04/aftersales-refund-sweep（线②）',
  generatedAt: nowCST(),
  apiBase: process.env.API_BASE,
  tenantId: Number(process.env.TENANT_ID),
  buildpoint: {
    deployed: deployPoint,
    deployedShaExpected: 'ff655a06c',
    declaredSha: deployPoint?.declaredSha ?? null,
    lastSuccessDeploySha: deployPoint?.lastSuccessSha ?? null,
    localWorktree: { worktree: bp.worktree, sha: bp.sha, shaFull: bp.shaFull, note: '本地旧构建点 main-live，**读数不取自它**' },
  },
  counts, byGroup, perFile, items, residue, segments: results,
  notes: [
    '四态 = pass / fail(产品) / falseRed(判据缺陷或无判别力) / skip(未覆盖)；**skip 永不记 pass**',
    '本线**不下**「验收通过/交付完成」结论（不自我验收）',
    '并发族每项带 N / rounds[3] / overlapEvidence；未真重叠时判 falseRed 而非 pass',
    '红证一律只在**自建临时表 / 副本**上注入，未改任何产品源码',
    `段解析：本目录（overlay）优先，其余取底座 ${BASE}`,
  ],
}
writeFileSync(outPath('SUMMARY.json'), JSON.stringify(SUMMARY, null, 2))
log(`汇总：counts=${JSON.stringify(counts)}；零残留=${residue.total === 0}（${JSON.stringify(residue.counts)}）；token 凭据已删=${tokenRemoved}`)
log(`产物：out/SUMMARY.json（${items.length} 条判据）`)
