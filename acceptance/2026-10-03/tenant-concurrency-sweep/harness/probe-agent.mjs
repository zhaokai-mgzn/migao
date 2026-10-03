// 判据组 G：ai-agent-service(:8001) 租户链路（**全部走非 LLM 面**；本脚本不产生任何 chat/LLM 请求）
import { api, loginApi, Recorder, psql, log, OUT, AGENT, SERVICE_TOKEN } from './lib.mjs'
import { dbIds, A, B } from './resources.mjs'
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'

const args = Object.fromEntries(process.argv.slice(2).map((x) => { const [k, v] = x.replace(/^--/, '').split('='); return [k, v ?? true] }))
const FLIP = !!args.flip
const R = new Recorder(`probe-agent${FLIP ? '-flip' : ''}.json`)
const ok = (badCount) => (FLIP ? badCount > 0 : badCount === 0)   // 红证①：判据反转开关

const a = await loginApi(A.phone), b = await loginApi(B.phone)
const ids = { p20: new Set(dbIds('products', 20)), p21: new Set(dbIds('products', 21)), p1: new Set(dbIds('products', 1)) }
const ev = []
log(`A(20) user=${a.user.id} 商品${ids.p20.size} / B(21) user=${b.user.id} 商品${ids.p21.size} / C(1) 商品${ids.p1.size}`)
writeFileSync(join(OUT, `agent-fixtures${FLIP ? '-flip' : ''}.json`), JSON.stringify({
  A_products: [...ids.p20].slice(0, 5), B_products: [...ids.p21], C1_recommended: psql('select id,name from products where tenant_id=1 and recommended and coalesce(deleted,0)=0'),
  sql: "select id from products where tenant_id in (20,21,1)",
}, null, 2))

/** 从任意形态的响应里抽商品 id（:8001 工具返回 data.products；admin-api 列表返回 data.items） */
function prodIds(res) {
  const d = res.json?.data
  const arr = d?.products ?? d?.items ?? (Array.isArray(d) ? d : [])
  return arr.map((x) => String(x.id))
}
function foreignOf(resIds, ownT, otherSets) {
  const own = ids[`p${ownT}`]
  const foreign = resIds.filter((id) => !own.has(id) && otherSets.some((s) => s.has(id)))
  const unknown = resIds.filter((id) => !own.has(id) && !otherSets.some((s) => s.has(id)))
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
  const [t20, t21, t1, forged] = await Promise.all([
    call(20), call(21), call(1), call(20, { 'X-Tenant-Id': '21', 'X-User-Id': 'probe-user' }),
  ])
  const f20 = foreignOf(prodIds(t20), 20, [ids.p21, ids.p1])
  const f21 = foreignOf(prodIds(t21), 21, [ids.p20, ids.p1])
  const f1 = foreignOf(prodIds(t1), 1, [ids.p20, ids.p21])
  const fForge = foreignOf(prodIds(forged), 20, [ids.p21, ids.p1])
  const counts = { t20: prodIds(t20).length, t21: prodIds(t21).length, t1: prodIds(t1).length, forgedHdr: prodIds(forged).length }
  ev.push({ case: 'G2-tenant20', status: t20.status, count: counts.t20, foreign: f20.foreign, unknown: f20.unknown.length, head: t20.text.slice(0, 180) })
  ev.push({ case: 'G2-tenant21', status: t21.status, count: counts.t21, foreign: f21.foreign, unknown: f21.unknown.length, head: t21.text.slice(0, 180) })
  ev.push({ case: 'G2-tenant1', status: t1.status, count: counts.t1, foreign: f1.foreign, unknown: f1.unknown.length })
  ev.push({ case: 'G2-forged-header', status: forged.status, count: counts.forgedHdr, foreign: fForge.foreign, unknown: fForge.unknown.length })
  const bad = f20.foreign.length + f21.foreign.length + f1.foreign.length + fForge.foreign.length
  const nonEmpty = counts.t20 > 0 && counts.t21 > 0 && counts.t1 > 0
  const det = `body.tenant_id=20 → ${counts.t20} 件(越租户 ${f20.foreign.length})；=21 → ${counts.t21} 件(越租户 ${f21.foreign.length})；=1 → ${counts.t1} 件(越租户 ${f1.foreign.length})；tenant_id=20 + 头 X-Tenant-Id:21 → ${counts.forgedHdr} 件(越租户 ${fForge.foreign.length})`
  if (!nonEmpty) R.skip('G2-工具直调租户归属', ':8001 /internal/tools/execute 租户归属', `前置不成立（有租户查回 0 件）⇒ 无判别力：${det}`)
  else ok(bad) ? R.pass('G2-工具直调租户归属', ':8001 /internal/tools/execute：租户由 body.tenant_id 决定，X-Tenant-Id 头不生效', det, ev.slice(-4))
              : R.fail('G2-工具直调租户归属', ':8001 /internal/tools/execute 租户归属', '🔴 ' + det, ev.slice(-4))
  writeFileSync(join(OUT, `agent-boundary${FLIP ? '-flip' : ''}.json`), JSON.stringify({
    finding: '设计边界：持有合法 service token 的调用方可用 body.tenant_id 指定**任意**租户（:8001 不校验调用方与该租户的绑定）',
    evidence: { counts, x_tenant_id_header: fForge.foreign.length ? 'applied' : 'ignored', token_len: SERVICE_TOKEN.length },
  }, null, 2))
}

// ── G3 端点级租户过滤的**可判别夹具**：租户 1 有 1 件 recommended 商品，租户 20/21 各 0 件 ──
{
  const nr = (h) => api('GET', '/api/chat/products/new-arrivals?size=12', { base: AGENT, headers: h })
  const [dbgC1, dbgC1F, dbgMibao] = await Promise.all([
    nr({ 'X-Debug-Role': 'customer' }),
    nr({ 'X-Debug-Role': 'customer', 'X-Tenant-Id': '20', 'X-Service-Token': SERVICE_TOKEN, 'X-User-Id': 'probe' }),
    nr({ 'X-Debug-Role': 'mibao', 'X-Tenant-Id': '20' }),
  ])
  const rec1 = psql('select id from products where tenant_id=1 and recommended and coalesce(deleted,0)=0').map((r) => String(r.id))
  const got = prodIds(dbgC1)
  const gotF = prodIds(dbgC1F)
  ev.push({ case: 'G3-debug-customer', status: dbgC1.status, got, dbFixture: rec1, head: dbgC1.text.slice(0, 200) })
  ev.push({ case: 'G3-debug-customer+伪造头', status: dbgC1F.status, got: gotF })
  ev.push({ case: 'G3-debug-mibao(非customer)', status: dbgMibao.status, head: dbgMibao.text.slice(0, 200) })
  const fixtureOk = rec1.length > 0 && got.length > 0 && got.every((id) => rec1.includes(id))
  const headerIgnored = JSON.stringify(gotF) === JSON.stringify(got)
  const noLeak = ![...got, ...gotF].some((id) => ids.p20.has(id) || ids.p21.has(id))
  const bad = (fixtureOk && noLeak && headerIgnored) ? 0 : 1
  const det = `DEBUG 夹具（X-Debug-Role: customer ⇒ tenant 1）返回 ${got.length} 件，与 DB 的租户 1 recommended 商品 ${JSON.stringify(rec1)} ${fixtureOk ? '一致' : '不一致'}；叠加伪造头后 ${JSON.stringify(gotF)}（${headerIgnored ? '头被忽略' : '头生效=异常'}）；含租户 20/21 商品 ${[...got, ...gotF].filter((id) => ids.p20.has(id) || ids.p21.has(id)).length} 件`
  ok(bad) ? R.pass('G3-C端端点租户过滤', 'C 端只读端点按 token/调试身份的租户过滤（用租户 1 的 recommended 商品做非空夹具）', det, ev.slice(-3))
          : R.fail('G3-C端端点租户过滤', 'C 端端点租户过滤', '🔴 ' + det, ev.slice(-3))
}

// ── G4 C 端 JWT 认证：真 token 可用、坏 token 一律拒（fail-closed，不回落租户 1）──
{
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
  ev[0].note = 'A/B 均无 recommended 商品 ⇒ 空集是数据事实（非隔离证据），隔离判据见 G2/G3'
  ok(badCount) ? R.pass('G4-C端JWT认证', 'C 端 JWT：真 token 可用、坏/缺 token 一律 401（fail-closed，不回落租户 1）', `真A=${realA.status} 真B=${realB.status} 乱码=${bad.status} 无token=${noTok.status} 伪造无tenantId=${noTenant.status}`, ev.slice(-5))
              : R.fail('G4-C端JWT认证', 'C 端 JWT 认证', `🔴 坏 token 未被拒：乱码=${bad.status} 无=${noTok.status} 伪造=${noTenant.status}`, ev.slice(-5))
}

// ── G5 并发下的 :8001 工具直调（A/B 交替，逐响应核对商品 id 的 DB 归属）──
{
  const tasks = []
  for (let i = 0; i < 60; i++) {
    const t = i % 2 === 0 ? 20 : 21
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
    const f = foreignOf(prodIds(res), t, [t === 20 ? ids.p21 : ids.p20, ids.p1])
    if (f.foreign.length) { bad++; ev.push({ case: 'G5-越租户', tenant: t, ids: f.foreign }) }
  }
  const det = `:8001 并发 60 请求（A/B 交错工具直调），墙钟 ${wall}ms，首个响应 ${firstDone}ms 时仍有 ${inFlightAtFirst} 个在飞；越租户响应 ${bad} 个`
  writeFileSync(join(OUT, `agent-concurrency${FLIP ? '-flip' : ''}.json`), JSON.stringify({ wall, firstDone, inFlightAtFirst, bad }, null, 2))
  ok(bad) ? R.pass('G5-并发租户归属', 'ai-agent-service 并发下工具直调的租户归属', det, ev.slice(-3))
          : R.fail('G5-并发租户归属', 'ai-agent-service 并发下工具直调的租户归属', '🔴 ' + det, ev.slice(-3))
}

const sum = R.summary()
log(`=== probe-agent 读数（flip=${FLIP}）：pass=${sum.pass} fail=${sum.fail} skip=${sum.skip} total=${sum.total} ===`)
writeFileSync(join(OUT, `probe-agent${FLIP ? '-flip' : ''}-summary.json`), JSON.stringify({ flip: FLIP, ...sum }, null, 2))
