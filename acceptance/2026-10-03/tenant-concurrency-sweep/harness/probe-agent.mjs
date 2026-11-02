// 判据组 G：ai-agent-service(:8001) 租户链路（**全部走非 LLM 面**；本脚本不产生任何 chat/LLM 请求）
// 主体由 env 注入（issue #6937）：G2 需要 A/B（C 可选）；G3 需要 C；G4/G5 需要 A/B。
import { api, loginApi, Recorder, psql, log, OUT, AGENT, SERVICE_TOKEN } from './lib.mjs'
import { dbIds, A, B, TENANTS } from './resources.mjs'
import { S, T, PH, SMS_CODE, MISSING_B, B_SKIP, SUBJECTS_LINE } from '../../lib/subjects.mjs'
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'

const args = Object.fromEntries(process.argv.slice(2).map((x) => { const [k, v] = x.replace(/^--/, '').split('='); return [k, v ?? true] }))
const FLIP = !!args.flip
const R = new Recorder(`probe-agent${FLIP ? '-flip' : ''}.json`)
const ok = (badCount) => (FLIP ? badCount > 0 : badCount === 0)   // 红证①：判据反转开关
log(`[env] ${SUBJECTS_LINE}`)

const TA = T.A, TB = T.B
const a = MISSING_B ? null : await loginApi(A.phone, SMS_CODE)
const b = MISSING_B ? null : await loginApi(B.phone, SMS_CODE)
const pids = {}   // 租户 → 该租户商品 id 集合（直连 DB）
for (const t of TENANTS) pids[t] = new Set(dbIds('products', t))
const ev = []
log(`A(${TA}) user=${a?.user.id ?? '未注入'} 商品${pids[TA].size}${MISSING_B ? '' : ` / B(${TB}) user=${b.user.id} 商品${pids[TB].size}`}${S.C ? ` / C(${T.C}) 商品${pids[T.C].size}` : ''}`)
writeFileSync(join(OUT, `agent-fixtures${FLIP ? '-flip' : ''}.json`), JSON.stringify({
  A_products: [...pids[TA]].slice(0, 5), B_products: MISSING_B ? null : [...pids[TB]],
  C_recommended: S.C ? psql(`select id,name from products where tenant_id=${T.C} and recommended and coalesce(deleted,0)=0`) : null,
  tenants: TENANTS, sql: `select id from products where tenant_id in (${TENANTS.join(',')})`,
}, null, 2))

/** 从任意形态的响应里抽商品 id（:8001 工具返回 data.products；admin-api 列表返回 data.items） */
function prodIds(res) {
  const d = res.json?.data
  const arr = d?.products ?? d?.items ?? (Array.isArray(d) ? d : [])
  return arr.map((x) => String(x.id))
}
function foreignOf(resIds, ownT) {
  const own = pids[ownT]
  const others = TENANTS.filter((t) => t !== ownT)
  const foreign = resIds.filter((id) => !own.has(id) && others.some((t) => pids[t].has(id)))
  const unknown = resIds.filter((id) => !own.has(id) && !others.some((t) => pids[t].has(id)))
  return { foreign, unknown }
}

// ── G1 服务令牌闸：无 / 伪造 token ⇒ 401 ──
{
  const [n, bo, em] = await Promise.all([
    api('GET', '/api/internal/tools', { base: AGENT }),
    api('GET', '/api/internal/tools', { base: AGENT, headers: { 'X-Service-Token': 'bogus' } }),
    api('GET', '/api/internal/tools', { base: AGENT, headers: { 'X-Service-Token': '' } }),
  ])
  const bad = [n, bo, em].filter((r) => r.status !== 401).length
  ev.push({ case: 'G1', noToken: n.status, bogus: bo.status, empty: em.status, head: n.text.slice(0, 160) })
  ok(bad) ? R.pass('G1-服务令牌闸', ':8001 内部面无/伪造 X-Service-Token 必须 401', `无=${n.status} 伪造=${bo.status} 空=${em.status}`, ev.slice(-1))
          : R.fail('G1-服务令牌闸', ':8001 内部面令牌闸', `🔴 未全拒 ${n.status}/${bo.status}/${em.status}`, ev.slice(-1))
}

// ── G2 工具直调的租户归属：body.tenant_id 决定查哪个租户；X-Tenant-Id 头在 :8001 不被消费 ──
{
  const call = (tenantId, headers = {}) => api('POST', '/api/internal/tools/execute', {
    base: AGENT, headers: { 'X-Service-Token': SERVICE_TOKEN, ...headers },
    body: { tool_name: 'product_search', params: { keyword: '', size: 100, page: 1 }, tenant_id: tenantId, user_id: 'probe-user' },
  })
  const targetTenants = MISSING_B ? [TA] : [TA, TB].concat(S.C ? [T.C] : [])
  const outs = await Promise.all(targetTenants.map((t) => call(t)))
  const forged = await call(TA, { 'X-Tenant-Id': String(TB ?? TA), 'X-User-Id': 'probe-user' })
  const counts = {}; let bad = 0
  targetTenants.forEach((t, i) => {
    const got = prodIds(outs[i]); const f = foreignOf(got, t)
    counts[t] = got.length
    ev.push({ case: `G2-tenant${t}`, status: outs[i].status, count: got.length, foreign: f.foreign, unknown: f.unknown.length, head: outs[i].text.slice(0, 180) })
    bad += f.foreign.length
  })
  const fForge = foreignOf(prodIds(forged), TA); bad += fForge.foreign.length
  ev.push({ case: 'G2-forged-header', status: forged.status, count: prodIds(forged).length, foreign: fForge.foreign, unknown: fForge.unknown.length })
  const nonEmpty = targetTenants.every((t) => pids[t].size > 0)
  const det = `body.tenant_id=${TA} → ${counts[TA]} 件(越租户 ${foreignOf(prodIds(outs[0]), TA).foreign.length})`
    + (MISSING_B ? '（B 未注入 ⇒ 未做 B 侧）' : `；=${TB} → ${counts[TB]} 件(越租户 ${foreignOf(prodIds(outs[1]), TB).foreign.length})`)
    + (S.C ? `；=${T.C} → ${counts[T.C]} 件` : '')
    + `；tenant_id=${TA} + 头 X-Tenant-Id:${TB ?? TA} → ${prodIds(forged).length} 件(越租户 ${fForge.foreign.length})`
  if (!nonEmpty) R.skip('G2-工具直调租户归属', ':8001 /internal/tools/execute 租户归属', `前置不成立（有租户查回 0 件）⇒ 无判别力：${det}`)
  else ok(bad) ? R.pass('G2-工具直调租户归属', ':8001 /internal/tools/execute：租户由 body.tenant_id 决定，X-Tenant-Id 头不生效', det, ev.slice(-(targetTenants.length + 1)))
              : R.fail('G2-工具直调租户归属', ':8001 /internal/tools/execute 租户归属', '🔴 ' + det, ev.slice(-(targetTenants.length + 1)))
  writeFileSync(join(OUT, `agent-boundary${FLIP ? '-flip' : ''}.json`), JSON.stringify({
    finding: '设计边界：持有合法 service token 的调用方可用 body.tenant_id 指定**任意**租户（:8001 不校验调用方与该租户的绑定）',
    evidence: { tenants: targetTenants, counts, x_tenant_id_header: fForge.foreign.length ? 'applied' : 'ignored', token_len: SERVICE_TOKEN?.length ?? 0 },
  }, null, 2))
}

// ── G3 端点级租户过滤的**可判别夹具**：第三租户 C 的 recommended 商品（需 C 注入）──
if (!S.C) {
  R.skip('G3-C端端点租户过滤', 'C 端只读端点按 token/调试身份的租户过滤', '第三租户 C 未注入（TENANT_C/PHONE_C 缺）⇒ 「非空夹具」无从取真值 ⇒ 具名 skip，不折算 pass')
} else {
  const TC = T.C
  const nr = (h) => api('GET', '/api/chat/products/new-arrivals?size=12', { base: AGENT, headers: h })
  const [dbgC, dbgCF, dbgMibao] = await Promise.all([
    nr({ 'X-Debug-Role': 'customer' }),
    nr({ 'X-Debug-Role': 'customer', 'X-Tenant-Id': String(TA), 'X-Service-Token': SERVICE_TOKEN, 'X-User-Id': 'probe' }),
    nr({ 'X-Debug-Role': 'mibao', 'X-Tenant-Id': String(TA) }),
  ])
  const rec1 = psql(`select id from products where tenant_id=${TC} and recommended and coalesce(deleted,0)=0`).map((r) => String(r.id))
  const got = prodIds(dbgC)
  const gotF = prodIds(dbgCF)
  ev.push({ case: 'G3-debug-customer', status: dbgC.status, got, dbFixture: rec1, head: dbgC.text.slice(0, 200) })
  ev.push({ case: 'G3-debug-customer+伪造头', status: dbgCF.status, got: gotF })
  ev.push({ case: 'G3-debug-mibao(非customer)', status: dbgMibao.status, head: dbgMibao.text.slice(0, 200) })
  const fixtureOk = rec1.length > 0 && got.length > 0 && got.every((id) => rec1.includes(id))
  const headerIgnored = JSON.stringify(gotF) === JSON.stringify(got)
  const noLeak = ![...got, ...gotF].some((id) => TENANTS.filter((t) => t !== TC).some((t) => pids[t].has(id)))
  const bad = (fixtureOk && noLeak && headerIgnored) ? 0 : 1
  const det = `DEBUG 夹具（X-Debug-Role: customer ⇒ tenant ${TC}）返回 ${got.length} 件，与 DB 的租户 ${TC} recommended 商品 ${JSON.stringify(rec1)} ${fixtureOk ? '一致' : '不一致'}；叠加伪造头后 ${JSON.stringify(gotF)}（${headerIgnored ? '头被忽略' : '头生效=异常'}）；含他租户商品 ${[...got, ...gotF].filter((id) => TENANTS.filter((t) => t !== TC).some((t) => pids[t].has(id))).length} 件`
  ok(bad) ? R.pass('G3-C端端点租户过滤', 'C 端只读端点按 token/调试身份的租户过滤（用第三租户的 recommended 商品做非空夹具）', det, ev.slice(-3))
          : R.fail('G3-C端端点租户过滤', 'C 端端点租户过滤', '🔴 ' + det, ev.slice(-3))
}

// ── G4 C 端 JWT 认证：真 token 可用、坏 token 一律拒（fail-closed，不回落任何租户）──
if (MISSING_B) {
  R.skip('G4-C端JWT认证', 'C 端 JWT：真 token 可用、坏/缺 token 一律 401', `对照租户 B 未注入 ⇒ 「两个真 token 均可用」这一半无从判 ⇒ 具名 skip。${B_SKIP}`)
} else {
  const p = (token, extra = {}) => api('GET', '/api/chat/products/new-arrivals?size=6', { base: AGENT, token, headers: extra })
  const [realA, realB, bad, noTok, noTenant] = await Promise.all([
    p(a.token), p(b.token), p('garbage.token.value'), p(undefined), p('<REDACTED-JWT>'),
  ])
  ev.push({ case: 'G4-realA', status: realA.status, got: prodIds(realA) })
  ev.push({ case: 'G4-realB', status: realB.status, got: prodIds(realB) })
  ev.push({ case: 'G4-bad', status: bad.status, head: bad.text.slice(0, 140) })
  ev.push({ case: 'G4-noToken', status: noTok.status, head: noTok.text.slice(0, 140) })
  ev.push({ case: 'G4-forgedNoTenant', status: noTenant.status, head: noTenant.text.slice(0, 140) })
  const badCount = [bad, noTok, noTenant].filter((r) => r.status !== 401).length
  ev[0].note = `A(${TA})/${TB} 均无 recommended 商品时的空集是数据事实（非隔离证据），隔离判据见 G2/G3`
  ok(badCount) ? R.pass('G4-C端JWT认证', 'C 端 JWT：真 token 可用、坏/缺 token 一律 401（fail-closed，不回落任何租户）', `真A=${realA.status} 真B=${realB.status} 乱码=${bad.status} 无token=${noTok.status} 伪造无tenantId=${noTenant.status}`, ev.slice(-5))
              : R.fail('G4-C端JWT认证', 'C 端 JWT 认证', `🔴 坏 token 未被拒：乱码=${bad.status} 无=${noTok.status} 伪造=${noTenant.status}`, ev.slice(-5))
}

// ── G5 并发下的 :8001 工具直调（A/B 交替，逐响应核对商品 id 的 DB 归属）──
if (MISSING_B) {
  R.skip('G5-并发租户归属', 'ai-agent-service 并发下工具直调的租户归属', `对照租户 B 未注入 ⇒ 「A/B 交替」前提不成立 ⇒ 具名 skip。${B_SKIP}`)
} else {
  const tasks = []
  for (let i = 0; i < 60; i++) {
    const t = i % 2 === 0 ? TA : TB
    tasks.push({ i, t, p: api('POST', '/api/internal/tools/execute', {
      base: AGENT, headers: { 'X-Service-Token': SERVICE_TOKEN },
      body: { tool_name: 'product_search', params: { keyword: '', size: 100, page: 1 }, tenant_id: t, user_id: `probe-${i}` },
    }) })
  }
  const t0 = Date.now()
  const out = await Promise.all(tasks.map((x) => x.p))
  const wall = Date.now() - t0
  const firstDone = Math.min(...out.map((r) => r.ms))
  const inFlightAtFirst = out.filter((r) => r.ms > firstDone).length
  let bad = 0
  for (let k = 0; k < tasks.length; k++) {
    const { t } = tasks[k], res = out[k]
    if (res.status !== 200) { bad++; continue }
    const f = foreignOf(prodIds(res), t)
    if (f.foreign.length) { bad++; ev.push({ case: 'G5-越租户', tenant: t, ids: f.foreign }) }
  }
  const det = `:8001 并发 60 请求（A=${TA}/B=${TB} 交错工具直调），墙钟 ${wall}ms，首个响应 ${firstDone}ms 时仍有 ${inFlightAtFirst} 个在飞；越租户响应 ${bad} 个`
  writeFileSync(join(OUT, `agent-concurrency${FLIP ? '-flip' : ''}.json`), JSON.stringify({ wall, firstDone, inFlightAtFirst, bad }, null, 2))
  ok(bad) ? R.pass('G5-并发租户归属', 'ai-agent-service 并发下工具直调的租户归属', det, ev.slice(-3))
          : R.fail('G5-并发租户归属', 'ai-agent-service 并发下工具直调的租户归属', '🔴 ' + det, ev.slice(-3))
}

const sum = R.summary()
log(`=== probe-agent 读数（flip=${FLIP}）：pass=${sum.pass} fail=${sum.fail} skip=${sum.skip} total=${sum.total} ===`)
writeFileSync(join(OUT, `probe-agent${FLIP ? '-flip' : ''}-summary.json`), JSON.stringify({ flip: FLIP, ...sum }, null, 2))
if (sum.fail > 0) process.exitCode = 1
