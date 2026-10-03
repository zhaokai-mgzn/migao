// run-all — 线A 一键重跑（顺序即安全顺序：前置清理 → 环境自证 → 各写面分段 → 终态清理 → 零残留/存量自证 → 汇总）
//
// 用法：
//   API_BASE=http://127.0.0.1:8080 node run-all.mjs
//   SEGMENTS=p2-scan,p2b-cuttingheight-npe node run-all.mjs     # 只跑指定段
//   SKIP_RUN=1 node run-all.mjs                                 # 只做终态清理 + 重算 SUMMARY
import { execFileSync } from 'node:child_process'
import { writeFileSync, readFileSync, existsSync, rmSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  buildPoint, outPath, log, nowCST, cleanupProbe, probeResidue, ledgerHash, tableCounts,
} from './lib.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const bp = buildPoint()
log(`构建点: worktree=${bp.worktree} sha=${bp.sha} pid=${bp.pid} 启动=${bp.adminApiStart}`)

// ── ① 前置清理（幂等）：先清掉**本包命名域**的历史探针行，再取存量基线 ──
if (process.env.SKIP_RUN !== '1') {
  const before = probeResidue()
  log(`前置残留: ${JSON.stringify(before.counts)}`)
  try { cleanupProbe() } catch (e) { log(`前置清理异常（非致命）: ${e.message.slice(0, 120)}`) }
  log(`前置清理后: ${JSON.stringify(probeResidue().counts)}`)
  // .store.json / .session.json 清掉 ⇒ 每次重跑都真实重建探针工人（不靠旧 session 假绿）
  for (const f of ['.store.json', '.session.json']) { try { rmSync(outPath(f)) } catch { /* 不存在 */ } }
}

const SEGMENTS = process.env.SEGMENTS
  ? process.env.SEGMENTS.split(',')
  : ['p0-env', 'p1-auth', 'p2-scan', 'p2b-cuttingheight-npe', 'p3-inbound', 'p4-ship-upload', 'p5-ui', 'p6-baseline']
if (process.env.SKIP_RUN === '1') SEGMENTS.length = 0

// ── ①′ 存量基线（**排除本包探针域**）：前置清理刚跑完 ⇒ 此刻的存量行就是「改前」的真值 ──
const ledgerBeforeExisting = ledgerHash({ excludeProbe: true })
log(`存量基线(excludeProbe): ${ledgerBeforeExisting.hash.slice(0, 16)}`)

const results = {}
for (const seg of SEGMENTS) {
  const f = join(HERE, `${seg}.mjs`)
  if (!existsSync(f)) { results[seg] = { status: 'MISSING' }; log(`✗ ${seg} 文件不存在`); continue }
  log(`▶ ${seg}`)
  let code = 0, out = ''
  try {
    out = execFileSync(process.execPath, [f], { env: { ...process.env }, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 })
  } catch (e) { code = e.status ?? 1; out = (e.stdout ?? '') + (e.stderr ?? '') }
  results[seg] = { status: code === 0 ? 'ok' : `exit ${code}`, tail: out.trim().split('\n').slice(-2).join(' | ').slice(0, 400) }
  log(`◀ ${seg} ${code === 0 ? 'ok' : 'exit ' + code}`)
}

// ── ② 存量基线（零改动自证）取自 p0 的 out/P0-env.json；没有则现取 ──
let baseline = null
try { baseline = JSON.parse(readFileSync(outPath('P0-env.json'), 'utf8'))?.ledgerHashAtStart ?? null } catch { /* 无 */ }
if (!baseline) baseline = ledgerHash()   // 注：这是**全表**口径，仅留档（会因清理探针行而变化，不是存量命题）

// ── ③ 终态清理 + 零残留 + 存量自证 ──
let cleanupErr = null
try { cleanupProbe() } catch (e) { cleanupErr = e.message }
const residue = probeResidue()
// 🔴 口径修正（自曝）：全表指纹在清理后**必然**变（我删掉了自己的探针行）⇒ 那不是「存量被改」。
// 存量零改动命题用 **excludeProbe** 口径 + 逐表行数分列，见 p6-baseline.mjs / Z-baseline.json。
const ledgerAfter = ledgerHash({ excludeProbe: true })
const ledgerAfterAll = ledgerHash()
const residueReport = {
  at: nowCST(), cleanupError: cleanupErr, residue,
  clean: residue.total === 0,
  ledgerBeforeAllRows: baseline, ledgerAfterAllRows: ledgerAfterAll,
  ledgerBefore: ledgerBeforeExisting, ledgerAfter,
  ledgerUnchanged: ledgerBeforeExisting.hash === ledgerAfter.hash,
  tableCounts: tableCounts(),
}
writeFileSync(outPath('Z-residue.json'), JSON.stringify(residueReport, null, 2))
log(`零残留: total=${residue.total} clean=${residueReport.clean}｜存量 sha256 一致=${residueReport.ledgerUnchanged}`)

// ── ④ 汇总（四态）──
const SUITES = [
  ['P1-auth.json', 'P1 工人身份面'],
  ['P2-scan.json', 'P2 扫码闭环（A1 核心写路径）'],
  ['P2b-cuttingheight-npe.json', 'P2b 裁高 NPE 复现 + 红证'],
  ['P3-inbound.json', 'P3 小程序入库写面'],
  ['P4-miniapp-ship-upload.json', 'P4 小程序其余写面 + C 端上传'],
  ['P5-ui.json', 'P5 UI 级（真机驱动）'],
]
const counts = { pass: 0, fail: 0, skip: 0, falseRed: 0, total: 0 }
const records = []
const perSuite = {}
for (const [file, name] of SUITES) {
  const p = outPath(file)
  if (!existsSync(p)) { perSuite[name] = { status: 'MISSING', file }; continue }
  const j = JSON.parse(readFileSync(p, 'utf8'))
  perSuite[name] = { file, ...j.summary }
  for (const r of j.records) {
    counts[r.status === 'pass' ? 'pass' : r.status === 'fail' ? 'fail' : 'skip']++
    const evText = `${r.detail} ${JSON.stringify(r.evidence ?? [])}`
    const isFalseRed = r.status === 'fail' && /判据缺陷|假红|故意错的期望|失效控制/.test(evText)
    if (isFalseRed) counts.falseRed++
    counts.total++
    records.push({
      id: r.id, group: name, verdict: r.status, falseRed: isFalseRed,
      evidence: [r.detail, ...(r.evidence ?? [])].join(' ｜ ').slice(0, 2000),
      redProof: (r.evidence ?? []).filter((e) => /红证|负对照|判据修正|假红|修正留档/.test(e)).join(' ｜ ').slice(0, 800),
    })
  }
}

const SUMMARY = {
  line: '线A · 工人端（worker-h5）+ 小程序（bmini-app / mini-app）写面 sweep · 2026-10-03 第三轮',
  buildPoint: {
    worktree: bp.worktree, sha: bp.sha, shaFull: bp.shaFull, subject: bp.subject,
    commitTime: bp.commitTime, adminApiPid: bp.pid, adminApiStart: bp.adminApiStart,
    originMain: bp.originMain,
    how: 'git -C /Users/guangzhen.zk/migao-wt/main-live rev-parse HEAD + ps -o lstart（harness/lib.mjs::buildPoint）；服务地址与健康读自 acceptance/2026-10-03/env/env-round3.json（16:23 主会话带 .env 重启，构建点未变）',
    observedAt: bp.observedAt,
  },
  window: { start: nowCST().cst, utc: nowCST().utc },
  counts, perSuite, residue: residueReport,
  records,
  segments: results,
  note: [
    'fail 桶里的 U6 是**故意的失效控制项**（红证），不计产品缺陷；真缺陷见 REPORT §发现。',
    '本包不下「验收通过」结论（铁律 2）：只产读数 + 判定 + 证据。',
  ],
}
writeFileSync(outPath('SUMMARY.json'), JSON.stringify(SUMMARY, null, 2))
log(`汇总: ${JSON.stringify(counts)}；零残留=${residueReport.clean}；存量一致=${residueReport.ledgerUnchanged}`)
