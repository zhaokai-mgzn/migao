// 判据组 P2/P6：barrier 对齐交错 + 高并发（>线程池）+ C 端订单链的租户上下文残留探针
// 主体由 env 注入（issue #6937）：P2/P6 需要 A/B 双侧；P7 需要第三租户 C 的调试夹具（缺则具名 skip）。
import { api, loginApi, Recorder, psql, log, OUT, AGENT } from './lib.mjs'
import { RESOURCES, dbIds, A, B, TENANTS } from './resources.mjs'
import { S, T, PH, SMS_CODE, MISSING_B, B_SKIP, SUBJECTS_LINE } from '../../lib/subjects.mjs'
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'

const args = Object.fromEntries(process.argv.slice(2).map((x) => { const [k, v] = x.replace(/^--/, '').split('='); return [k, v ?? true] }))
const FLIP = !!args.flip
const R = new Recorder(`probe2${FLIP ? '-flip' : ''}.json`)
const ok = (bad) => (FLIP ? bad > 0 : bad === 0)
log(`[env] ${SUBJECTS_LINE}`)

const TA = T.A, TB = T.B
const a = MISSING_B ? null : await loginApi(A.phone, SMS_CODE)
const b = MISSING_B ? null : await loginApi(B.phone, SMS_CODE)
const src = RESOURCES.find((r) => r.key === 'orders')
const idSet = { [TA]: new Set(dbIds('orders', TA)), [TB]: new Set(dbIds('orders', TB)) }
const CLS = {}   // 直连 DB 的 id → 租户
for (const t of TENANTS) for (const id of (idSet[t] ?? [])) CLS[id] = t
const ev = []

// ── P2 barrier 对齐：让 A/B 的请求在同一时刻发出（真交错窗口）──
async function barrierInterleave(rounds = 80) {
  const tasks = []
  for (let i = 0; i < rounds; i++) tasks.push({ i, kind: 'pair', tA: TA, tB: TB })
  const start = { p: null }
  const gate = new Promise((r) => { start.p = r })
  const issues = []
  const ps = []
  for (const t of tasks) {
    ps.push((async () => { await gate; return api('GET', src.list, { token: a.token }) })())
    ps.push((async () => { await gate; return api('GET', src.list, { token: b.token }) })())
  }
  const t0 = Date.now()
  start.p()
  const out = await Promise.all(ps)
  const wall = Date.now() - t0
  let bad = 0
  for (let k = 0; k < out.length; k++) {
    const expectTenant = k % 2 === 0 ? TA : TB
    const res = out[k]
    if (res.status !== 200) { bad++; issues.push({ k, expectTenant, status: res.status, head: res.text.slice(0, 140) }); continue }
    const ids = (res.json?.data?.items ?? []).map((x) => String(x.id))
    const wrong = ids.filter((id) => CLS[id] && CLS[id] !== expectTenant)
    if (wrong.length) { bad++; issues.push({ k, expectTenant, wrong: wrong.slice(0, 5), idsSample: ids.slice(0, 5) }) }
  }
  const firstDone = Math.min(...out.map((r) => r.ms))
  const inFlight = out.filter((r) => r.ms > firstDone).length
  writeFileSync(join(OUT, `probe2-barrier${FLIP ? '-flip' : ''}.json`), JSON.stringify({ requests: out.length, wall, firstDone, inFlightAtFirstDone: inFlight, bad, issues: issues.slice(0, 10) }, null, 2))
  const det = `barrier 对齐 ${out.length} 个请求（A=${TA}/B=${TB} 严格同步起跑，${rounds} 轮），墙钟 ${wall}ms，首个响应 ${firstDone}ms 时仍有 ${inFlight} 个在飞；跨租户/异常响应 ${bad} 个`
  ok(bad) ? R.pass('P2-barrier对齐', 'A/B 严格同时起跑（同一 microtask 门控）下的列表响应租户归属', det, issues.slice(0, 5))
          : R.fail('P2-barrier对齐', 'A/B 严格同时起跑下的列表响应租户归属', '🔴 ' + det, issues.slice(0, 8))
}

// ── P6 高并发 > 线程池上限（200 threads / accept-count 100）──
async function overPool() {
  const N2 = 320
  const ps = []
  for (let i = 0; i < N2; i++) {
    const t = i % 2 === 0 ? TA : TB
    ps.push({ i, t, p: api('GET', src.list, { token: t === TA ? a.token : b.token }) })
  }
  const t0 = Date.now()
  const out = await Promise.all(ps.map((x) => x.p))
  const wall = Date.now() - t0
  let bad = 0; const issues = []
  for (let k = 0; k < ps.length; k++) {
    const { t } = ps[k], res = out[k]
    if (res.status !== 200) { bad++; issues.push({ k, t, status: res.status, head: res.text.slice(0, 120) }); continue }
    const ids = (res.json?.data?.items ?? []).map((x) => String(x.id))
    const wrong = ids.filter((id) => CLS[id] && CLS[id] !== t)
    if (wrong.length) { bad++; issues.push({ k, t, wrong: wrong.slice(0, 5) }) }
  }
  const firstDone = Math.min(...out.map((r) => r.ms))
  const inFlight = out.filter((r) => r.ms > firstDone).length
  const p95 = out.map((r) => r.ms).sort((x, y) => x - y)[Math.floor(out.length * 0.95)]
  writeFileSync(join(OUT, `probe2-overpool${FLIP ? '-flip' : ''}.json`), JSON.stringify({ requests: N2, wall, firstDone, inFlightAtFirstDone: inFlight, p95ms: p95, bad, issues: issues.slice(0, 10) }, null, 2))
  const det = `${N2} 并发（> tomcat max-threads 200），墙钟 ${wall}ms、p95 ${p95}ms；首个响应 ${firstDone}ms 时 ${inFlight} 个在飞；异常/跨租户 ${bad} 个`
  ok(bad) ? R.pass('P6-超线程池并发', '并发 320（超过 200 线程上限）下的租户归属与可用性', det, issues.slice(0, 5))
          : R.fail('P6-超线程池并发', '并发 320 下的租户归属与可用性', '🔴 ' + det, issues.slice(0, 8))
}

// ── P7 C 端订单链的租户上下文残留：非空夹具 = 第三租户 C 的 debug_customer_1 订单 ──
async function cEndResidue() {
  const TC = T.C
  const dbCount = psql(`select count(*)::int c from orders where tenant_id=${TC} and user_id='debug_customer_1'`)[0].c
  const dbIds1 = psql(`select id from orders where tenant_id=${TC} and user_id='debug_customer_1'`).map((r) => String(r.id))
  const dbIdSet = new Set(dbIds1)
  const otherIds = new Set([...idSet[TA], ...idSet[TB]])
  const dbg = () => api('GET', '/api/chat/orders/mine?size=20', { base: AGENT, headers: { 'X-Debug-Role': 'customer' } })
  const attempts = []
  for (let round = 0; round < 3; round++) {
    const pre = []
    for (let i = 0; i < 24; i++) pre.push(api('GET', '/api/chat/orders/mine?size=1', { base: AGENT, token: i % 2 ? a.token : b.token }))
    const noise = await Promise.all(pre)
    const r = await dbg()
    attempts.push({ round, warmupStatuses: [...new Set(noise.map((x) => x.status))], status: r.status, n: (r.json?.data?.items ?? []).length, total: r.json?.data?.total, req: r.json?.requestId, head: r.text.slice(0, 140) })
  }
  const r3 = await api('GET', '/api/chat/orders/mine?size=20', { base: AGENT, headers: { 'X-Debug-Role': 'customer', 'X-Tenant-Id': String(TA), 'X-Service-Token': 'probe' } })
  const got3 = (r3.json?.data?.items ?? []).map((x) => String(x.id))
  const fill = []
  for (let i = 0; i < 200; i++) fill.push(api('GET', src.list, { token: i % 2 ? a.token : b.token }))
  await Promise.all(fill)
  const r4 = await dbg()
  const got4 = (r4.json?.data?.items ?? []).map((x) => String(x.id))
  const foreign = [...got3, ...got4].filter((id) => otherIds.has(id))
  const badIds = [...got3, ...got4].filter((id) => !dbIdSet.has(id))
  ev.push({ case: 'P7-fixture', tenantC: TC, dbCount, dbIds1: dbIds1.slice(0, 3), note: `直连 DB：tenant_id=${TC} 且 user_id=debug_customer_1` })
  ev.push({ case: 'P7-attempts', attempts, forged: { status: r3.status, n: got3.length }, afterFill: { status: r4.status, n: got4.length } })
  const emptyRuns = attempts.filter((x) => x.n === 0).length
  const bad = foreign.length + badIds.length + (attempts.some((x) => x.status !== 200) ? 1 : 0)
  writeFileSync(join(OUT, `probe2-cend${FLIP ? '-flip' : ''}.json`), JSON.stringify({ dbCount, attempts, got3, got4, foreign, badIds }, null, 2))
  const det = `夹具 DB 计数=${dbCount}；3 轮「24 个他租户请求并发 + 立即打」→ ${attempts.map((x) => x.n).join('/')} 单；叠加 X-Tenant-Id:${TA} → ${got3.length}；200 并发压满后 → ${got4.length}；越租户 id ${foreign.length}`
  ok(bad) ? R.pass('P7-C端订单链残留', 'C 端订单链（:8001→admin-api）经交叉/高压请求后仍只返回本租户本用户订单', det + (emptyRuns ? `（观察：其中 ${emptyRuns} 轮出现 0 单，见 REPORT 观察项 OBS-1）` : ''), ev)
          : R.fail('P7-C端订单链残留', 'C 端订单链经交叉请求后仍只返回本租户本用户订单', '🔴 ' + det, ev)
}

if (MISSING_B) {
  for (const [id, name] of [['P2-barrier对齐', 'A/B 严格同时起跑下的列表响应租户归属'], ['P6-超线程池并发', '并发 320 下的租户归属与可用性']])
    R.skip(id, name, `对照租户 B 未注入 ⇒ 本判据的 A/B 对照前提不成立。${B_SKIP}`)
} else {
  await barrierInterleave(80)
  await overPool()
}
if (!S.C) R.skip('P7-C端订单链残留', 'C 端订单链经交叉请求后仍只返回本租户本用户订单',
  '第三租户 C 未注入（TENANT_C/PHONE_C 缺）⇒ C 端调试夹具（debug_customer_1 的订单）无从取真值 ⇒ 具名 skip，不折算 pass')
else await cEndResidue()

const sum = R.summary()
log(`=== probe2 读数（flip=${FLIP}）：pass=${sum.pass} fail=${sum.fail} skip=${sum.skip} total=${sum.total} ===`)
writeFileSync(join(OUT, `probe2${FLIP ? '-flip' : ''}-summary.json`), JSON.stringify({ flip: FLIP, ...sum }, null, 2))
if (sum.fail > 0) process.exitCode = 1
