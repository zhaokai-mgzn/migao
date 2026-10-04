// run-all — 线① 一键重跑（2026-10-04 轮：**被测面 = 已部署 https://api.migaozn.com**）
//
// 顺序即安全顺序：
//   ① 前置清理（本包 `la` 命名域探针行 + 冷启动链，幂等）
//   ② bootstrap-chain（**空租户首个订单端到端**：商品→下单→收款→加工单→工序实例；BRIEF §4.1 前提）
//   ③ p0..p6 各写面分段
//   ④ 终态清理 + 零残留 + 存量自证（excludeProbe 口径）
//   ⑤ 汇总四态 → out/SUMMARY.json
//
// 用法（逐字口径见 acceptance/2026-10-04/BRIEF.md §2）：
//   API_BASE=https://api.migaozn.com TENANT_ID=25 ADMIN_PHONE=13800138000 SMS_CODE=123456 \
//   LIVE_WORKTREE=/Users/guangzhen.zk/migao-wt/main-live \
//   OUT_DIR=acceptance/2026-10-04/worker-miniapp-sweep/out node run-all.mjs
//   SEGMENTS=p2-scan,p2b-cuttingheight-npe node run-all.mjs   # 只跑指定段
//   SKIP_RUN=1 node run-all.mjs                               # 只做终态清理 + 重算 SUMMARY
import { execFileSync } from 'node:child_process'
import { writeFileSync, readFileSync, existsSync, rmSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  buildPoint, outPath, log, nowCST, cleanupProbe, probeResidue, ledgerHash, tableCounts, API,
} from './lib.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const bp = buildPoint()
log(`被测面 API_BASE=${API}｜本地参照 worktree=${bp.worktree} sha=${bp.sha}（**读数不取自它**）`)
log(`部署构建点(声明)=${bp.deployedBuildpoint} / ${bp.deployedSha}｜obs=${bp.observedAt.cst}`)

// ── ① 前置清理（幂等）：本包 `la` 命名域（含 `lac` 冷启动链）──
if (process.env.SKIP_RUN !== '1') {
  const before = probeResidue()
  log(`前置残留: ${JSON.stringify(before.counts)} total=${before.total}`)
  try { cleanupProbe() } catch (e) { log(`前置清理异常（非致命）: ${e.message.slice(0, 160)}`) }
  log(`前置清理后: ${JSON.stringify(probeResidue().counts)} total=${probeResidue().total}`)
  for (const f of ['.store.json', '.session.json']) { try { rmSync(outPath(f)) } catch { /* 不存在 */ } }
  // 链台账一起清（前置清理已把链对象删掉 ⇒ 旧 .chain.json 指向不存在的行）
  try { rmSync(outPath('.chain.json')) } catch { /* 不存在 */ }
}

// ── ② 冷启动链（必须**先于** p0/p2：pickOpTemplate 依赖它落 .chain.json）──
const SEGMENTS = process.env.SEGMENTS
  ? process.env.SEGMENTS.split(',')
  : ['p0-env', 'p1-auth', 'p2-scan', 'p2b-cuttingheight-npe', 'p3-inbound', 'p4-ship-upload', 'p5-ui', 'p6-baseline']
if (process.env.SKIP_RUN === '1') SEGMENTS.length = 0

const results = {}
if (!process.env.SKIP_BOOTSTRAP && process.env.SKIP_RUN !== '1') {
  const f = join(HERE, 'bootstrap-chain.mjs')
  let code = 0, out = ''
  log('▶ bootstrap-chain（空租户首个订单端到端）')
  try { out = execFileSync(process.execPath, [f], { env: { ...process.env, CHAIN_REUSE: '1' }, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 }) }
  catch (e) { code = e.status ?? 1; out = (e.stdout ?? '') + (e.stderr ?? '') }
  results['bootstrap-chain'] = { status: code === 0 ? 'ok' : `exit ${code}`, tail: out.trim().split('\n').slice(-3).join(' | ').slice(0, 600) }
  log(`◀ bootstrap-chain ${code === 0 ? 'ok' : 'exit ' + code}`)
}

// ── ②′ 存量基线（排除本包探针域）──
const ledgerBeforeExisting = ledgerHash({ excludeProbe: true })
log(`存量基线(excludeProbe): ${ledgerBeforeExisting.hash.slice(0, 16)}`)

for (const seg of SEGMENTS) {
  const f = join(HERE, `${seg}.mjs`)
  if (!existsSync(f)) { results[seg] = { status: 'MISSING' }; log(`✗ ${seg} 文件不存在`); continue }
  log(`▶ ${seg}`)
  let code = 0, out = ''
  const env = { ...process.env }
  // p5-ui 的默认落点是**本地只读静态服务**（部署面已证整页不可用，见 P0c）；读数不冒充部署面验证。
  if (seg === 'p5-ui' && !env.WORKER_UI) env.WORKER_UI = 'http://127.0.0.1:3170'
  if (seg === 'p5-ui' && !env.WORKER_UI_PATH) env.WORKER_UI_PATH = '/worker-h5'
  try {
    out = execFileSync(process.execPath, [f], { env, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 })
  } catch (e) { code = e.status ?? 1; out = (e.stdout ?? '') + (e.stderr ?? '') }
  results[seg] = { status: code === 0 ? 'ok' : `exit ${code}`, tail: out.trim().split('\n').slice(-2).join(' | ').slice(0, 400) }
  log(`◀ ${seg} ${code === 0 ? 'ok' : 'exit ' + code}`)
}

// ── ③ 终态清理 + 零残留 + 存量自证 ──
let cleanupErr = null
try { cleanupProbe() } catch (e) { cleanupErr = e.message }
const residue = probeResidue()
const ledgerAfter = ledgerHash({ excludeProbe: true })
const ledgerAfterAll = ledgerHash()
const residueReport = {
  at: nowCST(), cleanupError: cleanupErr, residue,
  clean: residue.total === 0,
  ledgerAfterAllRows: ledgerAfterAll,
  ledgerBefore: ledgerBeforeExisting, ledgerAfter,
  ledgerUnchanged: ledgerBeforeExisting.hash === ledgerAfter.hash,
  tableCounts: tableCounts(),
}
writeFileSync(outPath('Z-residue.json'), JSON.stringify(residueReport, null, 2))
log(`零残留: total=${residue.total} clean=${residueReport.clean}｜存量 sha256 一致=${residueReport.ledgerUnchanged}`)

// ── ④ 汇总（四态）──
const SUITES = [
  ['P0b-chain.json', 'P0b 空租户冷启动链（商品→下单→收款→加工单→工序实例）'],
  ['P1-auth.json', 'P1 工人身份面'],
  ['P2-scan.json', 'P2 扫码闭环（核心写路径）'],
  ['P2b-cuttingheight-npe.json', 'P2b 裁高 NPE 复现 + 红证'],
  ['P3-inbound.json', 'P3 小程序入库写面'],
  ['P4-miniapp-ship-upload.json', 'P4 小程序其余写面 + C 端上传'],
  ['P5-ui.json', 'P5 UI 级（本地只读静态服务；部署面 MIME 缺陷见 P0c）'],
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
      redProof: (r.evidence ?? []).filter((e) => /红证|负对照|判据修正|假红|修正留档|单变量/.test(e)).join(' ｜ ').slice(0, 800),
    })
  }
}

const SUMMARY = {
  line: '线① · 工人端（worker-h5）+ 小程序（bmini-app / mini-app）写面 sweep · 2026-10-04 第四轮',
  buildPoint: {
    testedSurface: API,
    declaredBuildpoint: bp.deployedBuildpoint,
    declaredSha: bp.deployedSha,
    how: 'gh run list --workflow=deploy-admin-api.yml（headSha=ff655a06c… success @ 2026-10-03T21:47:10Z = 2026-10-04 05:47 +08）；'
      + 'git diff --stat ff655a06c..origin/main -- backend/admin-api/src/main backend/ai-agent-service/app frontend/*（空 ⇒ 功能面等价）',
    localWorktree: bp.worktree, localSha: bp.sha, localRole: bp.localWorktreeRole,
    observedAt: bp.observedAt,
  },
  window: { start: nowCST().cst, utc: nowCST().utc },
  counts, perSuite, residue: residueReport,
  records,
  segments: results,
  note: [
    '被测面 = https://api.migaozn.com（部署 ff655a06c）；本地 :8080 = main-live@43ca70322 **旧构建点**，本包不把它当被测对象。',
    '本包不下「验收通过」结论（铁律 2）：只产读数 + 判定 + 证据。',
    'skip 不折算 pass；部署面 UI 不可用见 out/P0c-ui-deployed-mime.json（P5 的 UI 读数取自**本地只读静态服务**，只作归因对照，不冒充部署面验证）。',
    '部署面 .mjs MIME 缺陷已由集成侧开单 #6293，本包不改 deploy/**、不重复开单。',
  ],
}
writeFileSync(outPath('SUMMARY.json'), JSON.stringify(SUMMARY, null, 2))
log(`汇总: ${JSON.stringify(counts)}；零残留=${residueReport.clean}；存量一致=${residueReport.ledgerUnchanged}`)
