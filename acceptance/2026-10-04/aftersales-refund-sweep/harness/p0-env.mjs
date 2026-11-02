// p0-env（线② 2026-10-04 版）—— 被测面坐标自证 + 时钟自检 + 端点可达性 + 鉴权 + 租户基线
//
// 与底座 `acceptance/2026-10-03/aftersales-concurrency-sweep/harness/p0-env.mjs` 的差异（**底座未改**）：
//   ① 坐标系 = **已部署面**（`API_BASE` 指向 https://api.migaozn.com）；`LIVE_WORKTREE` 的本地 HEAD
//      只作**本地旧构建点**如实登记（读数**不取自它**，见 BRIEF §1/§2 注）。
//   ② 租户基线改按 `TENANT_ID` 现取（底座硬编码 tenant 20 —— 该租户已于 2026-10-04 08:31 清空）。
//   ③ 登录手机号取自 `ADMIN_PHONE`（底座报告里写死旧号，属取证文案漂移）。
import { writeFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { buildPoint, api, adminToken, psql, outPath, log, nowCST, Recorder } from './lib.mjs'

const R = new Recorder('B0-env.json')
const bp = buildPoint()   // 本地旧构建点（**非被测面**）
const sh = (c) => { try { return execFileSync('bash', ['-lc', c], { encoding: 'utf8' }).trim() } catch (e) { return `ERR ${String(e.message).slice(0, 120)}` } }
const ghVar = (k) => sh(`gh variable get ${k} --json value --jq .value 2>/dev/null`).replace(/^ERR .*$/, '')

// ── ① 被测面坐标自证（**唯一权威来自部署台账/变量，不来自本地工作树**）──
const deployRuns = sh(`gh run list --workflow=deploy-admin-api.yml --limit 12 --json headSha,conclusion,createdAt --jq '.[] | "\\(.createdAt)|\\(.conclusion)|\\(.headSha)"'`)
const lastSuccess = deployRuns.split('\n').map((l) => l.split('|')).filter((p) => p[1] === 'success').sort((a, b) => (a[0] < b[0] ? 1 : -1))[0] ?? []
const declaredSha = ghVar('ADMIN_API_DEPLOYED_SHA')
const lastSuccessSha = (lastSuccess[2] || '').slice(0, 9) || null
// 期望构建点 = 任务书钉死的 ff655a06c（BRIEF §1）
const EXPECTED = 'ff655a06c'
const evidence = {
  expected: EXPECTED,
  declaredSha,
  lastSuccessSha,
  lastSuccessAtUtc: lastSuccess[0] ?? null,
  deployRunsRaw: deployRuns.slice(0, 1200),
  localWorktree: { worktree: bp.worktree, sha: bp.sha, shaFull: bp.shaFull, note: '本地旧构建点，非被测面；读数不取自它' },
  probeUrl: `${process.env.API_BASE}/api/admin/after-sales`,
  observedAt: nowCST(),
}
writeFileSync(outPath('E0-deploypoint.json'), JSON.stringify(evidence, null, 2))
writeFileSync(outPath('B0-buildpoint.json'), JSON.stringify({ local: bp, deployed: evidence }, null, 2))
log(`被测面坐标：declared=${declaredSha || '(变量未设)'} lastSuccessDeploy=${lastSuccessSha}（本地旧构建点 ${bp.sha}）`)

const shaOk = (declaredSha && declaredSha.startsWith(EXPECTED)) || (!declaredSha && lastSuccessSha === EXPECTED)
R.add('LB0-01', '被测构建点自证（部署台账/远端变量 ⇒ 期望 ff655a06c）', shaOk ? 'pass' : 'fail',
  `远端声明=${declaredSha || '(ADMIN_API_DEPLOYED_SHA 未设)'}；最后一个 success 部署=${lastSuccessSha} @ ${lastSuccess[0] || 'n/a'}（UTC）`,
  [`期望来源: BRIEF §1 —— 被测构建点 = 已部署 ff655a06c（2026-10-04 05:47 +08 部署）`,
   `取证命令: gh variable get ADMIN_API_DEPLOYED_SHA / gh run list --workflow=deploy-admin-api.yml`,
   `部署台账（UTC，换算 +08）：${deployRuns.split('\n').slice(0, 4).join(' ｜ ')}`,
   `⚠️ 本地工作树 ${bp.worktree} HEAD=${bp.shaFull} —— **本地旧构建点，非被测面**（BRIEF：读数一律取自 API_BASE）`,
   `口径：若远端变量缺失，则以「最近一个 success 部署的 headSha」为准（本判据取两者之一命中即 pass）`])

// ── ② 时钟自检 ──
const parseCST = (s) => Date.parse(String(s).replace(' ', 'T') + '+08:00')
const jsNow = nowCST().cst.slice(0, 19)
const dbNow = psql(`select to_char(now() at time zone 'Asia/Shanghai','YYYY-MM-DD HH24:MI:SS') as t`)[0].t
const skewSec = Math.abs(parseCST(jsNow) - parseCST(dbNow)) / 1000
writeFileSync(outPath('B0-clock.json'), JSON.stringify({ jsNow, dbNow, skewSec, at: nowCST() }, null, 2))
R.add('LB0-02', '时钟自检（JS +08 vs SQL Asia/Shanghai）', Number.isFinite(skewSec) ? 'pass' : 'fail',
  `JS=${jsNow} / SQL=${dbNow}（差 ${skewSec}s）`,
  [`取值口径: nowCST() 走 Intl timeZone=Asia/Shanghai；SQL 走 now() at time zone 'Asia/Shanghai'`,
   `两侧均按 '+08:00' 显式解析后比较（不依赖进程 TZ）`])

// ── ③ 端点可达性（未鉴权 ⇒ 401）──
for (const [id, m, p] of [['LB0-03', 'GET', '/api/admin/after-sales?page=1&size=1'], ['LB0-04', 'GET', '/api/admin/orders?page=1&size=1']]) {
  const r = await api(m, p)
  R.add(id, `端点可达性 ${m} ${p}（已部署面）`, r.status === 401 ? 'pass' : 'fail',
    `未鉴权访问返回 ${r.status}（期望 401 —— 该端点是鉴权面）`, [`响应原文: ${r.text.slice(0, 160)}`, `目标: ${process.env.API_BASE}${p}`])
}

// ── ④ 鉴权 ──
let token = null
try {
  const l = await adminToken()
  token = l.token
  const tenantSeen = l.raw?.user?.tenantId ?? l.raw?.tenantId
  writeFileSync(outPath('B0-auth.json'), JSON.stringify({
    ok: true, phone: process.env.ADMIN_PHONE, expectedTenant: Number(process.env.TENANT_ID), tenantSeen, via: l.via,
    user: l.raw?.user ? { id: l.raw.user.id, username: l.raw.user.username, role: l.raw.user.role, tenantId: l.raw.user.tenantId } : null,
  }, null, 2))
  writeFileSync(outPath('.token'), String(token))   // 供 p1..pN 复用（收尾随产物清理）
  R.add('LB0-05', '管理员登录（已部署面）+ 租户自证', (token && Number(tenantSeen) === Number(process.env.TENANT_ID)) ? 'pass' : 'fail',
    `取到 token（长度 ${String(token).length}），方式=${l.via}；登录租户=${tenantSeen}（期望 ${process.env.TENANT_ID}）`,
    [`手机号 = ${process.env.ADMIN_PHONE}（env 覆盖；底座默认值属已删除租户 20）`,
     `租户自证：响应 user.tenantId=${tenantSeen} ⇒ 后续所有写操作落在租户 ${process.env.TENANT_ID}`,
     `响应 data 键: ${Object.keys(l.raw || {}).join(',')}`])
} catch (e) {
  R.add('LB0-05', '管理员登录（已部署面）+ 租户自证', 'fail', e.message.slice(0, 300), [])
}

// ── ⑤ 探针域基线现取（跨包隔离：记录此刻本租户存量，供「外来行归因」与清理前后对照用）──
const T = Number(process.env.TENANT_ID)
const base = psql(`select
  (select count(*) from orders where tenant_id=${T}) as orders,
  (select count(*) from after_sales_tickets where tenant_id=${T}) as tickets,
  (select count(*) from stock_ledger_entries where tenant_id=${T}) as ledger,
  (select count(*) from finance_transactions where tenant_id=${T}) as finance,
  (select count(*) from products where tenant_id=${T}) as products,
  (select count(*) from categories where tenant_id=${T} and status='active') as active_categories,
  (select count(*) from users where tenant_id=${T}) as users`)[0]
writeFileSync(outPath('B0-tenant-baseline.json'), JSON.stringify({ tenant: T, at: nowCST(), base }, null, 2))
R.add('LB0-06', `租户 ${T} 存量基线（外来行归因 + 清理对照用）`, 'pass', JSON.stringify(base),
  [`只读现取；量纲 = 行数（判据只断言**本线前缀对象**，不断言租户级全局计数 —— BRIEF 纪律 8）`,
   `三线并发写同一租户 ${T} ⇒ 该基线只作「外来行归因」参照，不作零不变判据`])

log(`p0 完成：${JSON.stringify(R.summary())}`)
if (!token) process.exit(1)
