// 线③ 判据组 C：跨租户 TenantContext 串号（并发混打 + 伪造 X-Tenant-Id）
// 对照租户 B = 26（本线经 §4.3 入驻流程临时建立，收尾清理）
// 命名空间纪律：只断言本线探针对象（name/skuCode 前缀 race-sweep）在两租户间的归属，不碰任何租户级全局计数。
import { api, loginApi, Recorder, log, OUT, one, psql } from './lib.mjs'
import { T_A, PROBE } from './config.mjs'
import { timedApi, fanOut, overlapStats, save } from './lib2.mjs'
import { readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const FIX = JSON.parse(readFileSync(join(OUT, 'fixtures.json'), 'utf8'))
const T_B = FIX.tenantB
const R = new Recorder('probe-cross.json')
const STAMP = FIX.stamp
const rnd = () => Math.random().toString(36).slice(2, 8)
const a = await loginApi(FIX.phoneA)
const b = await loginApi(FIX.phoneB)
if (a.user.tenantId !== T_A || b.user.tenantId !== T_B) throw new Error(`登录租户不符 A=${a.user.tenantId} B=${b.user.tenantId}`)
const REC = { stamp: STAMP, tenantA: T_A, tenantB: T_B, probePrefix: PROBE, cases: {} }

// 本线命名空间：两租户各自的探针商品 id 集合（直连 DB 取，不靠响应自述）
function idsByTenant(t) {
  return psql(`select id, name from products where tenant_id=${t} and name like '${PROBE}%'`).map((r) => ({ id: String(r.id), name: r.name }))
}
const A_IDS = new Set(idsByTenant(T_A).map((x) => x.id))
const B_IDS = new Set(idsByTenant(T_B).map((x) => x.id))
const ownerOf = (id) => (A_IDS.has(String(id)) ? T_A : B_IDS.has(String(id)) ? T_B : null)
log(`本线探针商品：A(${T_A})=${A_IDS.size} 个 / B(${T_B})=${B_IDS.size} 个`)

const extractProductIds = (res) => ((res.json?.data?.items ?? res.json?.data ?? []).map?.((x) => String(x.id)) ?? [])

// ── C1 并发交错列表读：响应里只能有本租户对象 ──
async function C1(n = 120) {
  const t = Date.now()
  const res = await fanOut(n, (i) => timedApi('GET', '/api/admin/products?page=1&size=200',
    { token: i % 2 === 0 ? a.token : b.token }, t), t)
  const st = overlapStats(res)
  const bad = []
  let checked = 0
  for (let i = 0; i < n; i++) {
    const expect = i % 2 === 0 ? T_A : T_B
    const r = res[i]
    if (r.status !== 200) { bad.push({ i, expect, status: r.status, head: r.text.slice(0, 120) }); continue }
    for (const id of extractProductIds(r)) {
      const own = ownerOf(id)
      if (own === null) continue                    // 非本线探针对象（别的线在 25 里建的商品）⇒ 不判
      checked++
      if (own !== expect) bad.push({ i, expect, foreign: id, belongsTo: own })
    }
  }
  const ev = { n, window: st, checkedProbeObjects: checked, badCount: bad.length, bad: bad.slice(0, 8) }
  REC.cases.C1 = ev
  const detail = `${n} 并发交错列表读（issueSpan=${st.issueSpanMs}ms、重叠对=${st.overlappedPairs}）：逐响应核对本线探针对象 ${checked} 次 ⇒ 跨租户 ${bad.length} 次；非 200 ${res.filter((r) => r.status !== 200).length}`
  bad.length === 0 ? R.pass('C1-并发交错列表不串号', 'A/B token 并发交错打商品列表 ⇒ 响应中本线对象必属本租户', detail, [ev])
                   : R.fail('C1-并发交错列表不串号', 'A/B token 并发交错打商品列表', '🔴 ' + detail, [ev])
}

// ── C2 按 id 跨租户读（并发）：A 打 B 的 id / B 打 A 的 id ⇒ 必须拒绝 ──
async function C2() {
  const pairs = []
  for (const id of [...B_IDS].slice(0, 6)) pairs.push({ attacker: T_A, victim: T_B, id, token: a.token })
  for (const id of [...A_IDS].slice(0, 6)) pairs.push({ attacker: T_B, victim: T_A, id, token: b.token })
  const t = Date.now()
  const res = await fanOut(pairs.length, (i) => timedApi('GET', `/api/admin/products/${pairs[i].id}`, { token: pairs[i].token }, t), t)
  const st = overlapStats(res)
  const leak = []
  const rejected = []
  for (let i = 0; i < pairs.length; i++) {
    const r = res[i], p = pairs[i]
    if ([403, 404].includes(r.status)) { rejected.push({ id: p.id, status: r.status }); continue }
    if (r.status === 200) {
      const got = r.json?.data?.id ?? r.json?.data?.name
      leak.push({ attacker: p.attacker, victim: p.victim, id: p.id, status: r.status, got, head: r.text.slice(0, 160) })
      continue
    }
    leak.push({ attacker: p.attacker, victim: p.victim, id: p.id, status: r.status, note: '既非 200 也非 403/404', head: r.text.slice(0, 120) })
  }
  const ev = { pairs: pairs.length, window: st, rejected, leak, statuses: res.map((r) => r.status) }
  REC.cases.C2 = ev
  const detail = `跨租户按 id 读 ${pairs.length} 个并发（issueSpan=${st.issueSpanMs}ms、重叠对=${st.overlappedPairs}）：被拒 ${rejected.length}、越权成功/异常态 ${leak.length}`
  leak.length === 0 ? R.pass('C2-并发跨租户按 id 读被拒', 'A 用 B 的 id（反向亦然）并发读 ⇒ 一律 403/404，绝不返回对方对象', detail, [ev])
                    : R.fail('C2-并发跨租户按 id 读被拒', 'A 用 B 的 id（反向亦然）并发读', '🔴 ' + detail, [ev])
}

// ── C3 伪造 X-Tenant-Id / X-User-Id 头：不得改变归属 ──
async function C3() {
  const spoofs = [
    { name: 'A+伪造 B 的 X-Tenant-Id', token: a.token, headers: { 'X-Tenant-Id': String(T_B) }, expect: T_A },
    { name: 'B+伪造 A 的 X-Tenant-Id', token: b.token, headers: { 'X-Tenant-Id': String(T_A) }, expect: T_B },
    { name: 'A+伪造 X-Tenant-Id=-1', token: a.token, headers: { 'X-Tenant-Id': '-1' }, expect: T_A },
    { name: 'A+伪造超大 X-Tenant-Id', token: a.token, headers: { 'X-Tenant-Id': '999999' }, expect: T_A },
  ]
  const t = Date.now()
  const res = await fanOut(spoofs.length, (i) => timedApi('GET', '/api/admin/products?page=1&size=200', { token: spoofs[i].token, headers: spoofs[i].headers }, t), t)
  const st = overlapStats(res)
  const bad = []
  for (let i = 0; i < spoofs.length; i++) {
    const r = res[i], s = spoofs[i]
    if (r.status !== 200) { bad.push({ case: s.name, status: r.status, head: r.text.slice(0, 120) }); continue }
    for (const id of extractProductIds(r)) {
      const own = ownerOf(id)
      if (own === null) continue
      if (own !== s.expect) bad.push({ case: s.name, expect: s.expect, foreign: id, belongsTo: own })
    }
  }
  const ev = { spoofs: spoofs.map((s) => s.name), statuses: res.map((r) => r.status), window: st, bad }
  REC.cases.C3 = ev
  const detail = `4 条伪造头并发（issueSpan=${st.issueSpanMs}ms）：状态 ${JSON.stringify(ev.statuses)}；越租户 ${bad.length}`
  bad.length === 0 ? R.pass('C3-伪造 X-Tenant-Id 无效', '带伪造 X-Tenant-Id（对方租户/-1/超大）并发读 ⇒ 归属仍由 JWT 决定', detail, [ev])
                   : R.fail('C3-伪造 X-Tenant-Id 无效', '带伪造 X-Tenant-Id 并发读', '🔴 ' + detail, [ev])
}

// ── C4 并发混合读写：A 写自己的 / B 写自己的，同时各读对方 id ──
async function C4() {
  const nameA = `${PROBE}-X-A-${STAMP}-${rnd()}`, nameB = `${PROBE}-X-B-${STAMP}-${rnd()}`
  const otherId = { [T_A]: [...B_IDS][0], [T_B]: [...A_IDS][0] }
  const t = Date.now()
  const tasks = [
    () => timedApi('POST', '/api/admin/products', { token: a.token, body: { name: nameA, skuCode: `RXA${rnd()}`.slice(0, 20), unit: '米', pricingType: 'per_meter', basePrice: 9.9, status: 'draft', stock: 3, colors: [{ colorName: '探针色' }], doorWidths: ['2.8m'] } }, t),
    () => timedApi('POST', '/api/admin/products', { token: b.token, body: { name: nameB, skuCode: `RXB${rnd()}`.slice(0, 20), unit: '米', pricingType: 'per_meter', basePrice: 9.9, status: 'draft', stock: 3, colors: [{ colorName: '探针色' }], doorWidths: ['2.8m'] } }, t),
    () => timedApi('GET', `/api/admin/products/${otherId[T_A]}`, { token: a.token }, t),   // A 读 B 的（otherId[T_A] = B 侧 id）
    () => timedApi('GET', `/api/admin/products/${otherId[T_B]}`, { token: b.token }, t),   // B 读 A 的（otherId[T_B] = A 侧 id）
    () => timedApi('GET', '/api/admin/products?page=1&size=200', { token: a.token }, t),
    () => timedApi('GET', '/api/admin/products?page=1&size=200', { token: b.token }, t),
  ]
  const gate = { p: null }; const g = new Promise((r) => { gate.p = r })
  const jobs = tasks.map((f) => (async () => { await g; return f() })())
  await new Promise((r) => setImmediate(r)); gate.p()
  const res = await Promise.all(jobs)
  const st = overlapStats(res)
  const leakList = []
  for (const idx of [4, 5]) {
    const expect = idx === 4 ? T_A : T_B
    for (const id of extractProductIds(res[idx])) { const own = ownerOf(id); if (own !== null && own !== expect) leakList.push({ idx, expect, foreign: id, belongsTo: own }) }
  }
  const otherIdNow = { [T_A]: [...new Set(idsByTenant(T_B).map((x) => x.id))][0], [T_B]: [...new Set(idsByTenant(T_A).map((x) => x.id))][0] }
  const posOwn = await Promise.all([
    api('GET', `/api/admin/products/${otherIdNow[T_B]}`, { token: a.token }),   // A 读自己的（正对照）
    api('GET', `/api/admin/products/${otherIdNow[T_A]}`, { token: b.token }),   // B 读自己的（正对照）
  ])
  const crossStatus = [res[2].status, res[3].status]
  const newRows = { A: one(`select count(*)::int c from products where tenant_id=${T_A} and name='${nameA}'`).c,
                    B: one(`select count(*)::int c from products where tenant_id=${T_B} and name='${nameB}'`).c }
  const ev = { window: st, statuses: res.map((r) => r.status), crossReadStatuses: crossStatus,
    crossReadRequestedIds: { aReadsB: otherIdNow[T_A], bReadsA: otherIdNow[T_B] },
    positiveControlOwnRead: posOwn.map((r) => r.status), leakList,
    newRows, writeStatuses: [res[0].status, res[1].status] }
  REC.cases.C4 = ev
  const bad = leakList.length > 0 || crossStatus.some((s) => ![403, 404].includes(s)) || newRows.A !== 1 || newRows.B !== 1
    || posOwn.some((r) => r.status !== 200)   // 正对照：各自读自己的必须 200（否则「一律 403」会假绿）
  const detail = `并发混合（issueSpan=${st.issueSpanMs}ms、重叠对=${st.overlappedPairs}）：状态 ${JSON.stringify(ev.statuses)}；跨租户读状态 ${JSON.stringify(crossStatus)}（应 403/404）；写入各自命名空间 ${JSON.stringify(newRows)}；串号 ${leakList.length}`
  bad ? R.fail('C4-并发混合读写不串号', 'A/B 并发：各建各的商品 + 各读对方 id + 各读列表', '🔴 ' + detail, [ev])
      : R.pass('C4-并发混合读写不串号', 'A/B 并发：各建各的商品 + 各读对方 id + 各读列表', detail, [ev])
}

// ── C5 超并发（>线程池）交错：租户归属不漂移 ──
async function C5(n = 160) {
  const t = Date.now()
  const res = await fanOut(n, (i) => timedApi('GET', '/api/admin/products?page=1&size=100',
    { token: i % 2 === 0 ? a.token : b.token }, t), t)
  const st = overlapStats(res)
  let bad = 0; const ev0 = []
  let checked = 0
  for (let i = 0; i < n; i++) {
    const expect = i % 2 === 0 ? T_A : T_B, r = res[i]
    if (r.status !== 200) { bad++; ev0.push({ i, expect, status: r.status }); continue }
    for (const id of extractProductIds(r)) { const own = ownerOf(id); if (own === null) continue; checked++; if (own !== expect) { bad++; ev0.push({ i, expect, foreign: id, belongsTo: own }) } }
  }
  const ev = { n, window: st, checkedProbeObjects: checked, bad, ev: ev0.slice(0, 8) }
  REC.cases.C5 = ev
  const detail = `${n} 并发交错（issueSpan=${st.issueSpanMs}ms、重叠对=${st.overlappedPairs}）：核对探针对象 ${checked} 次、异常/串号 ${bad} 次`
  bad === 0 ? R.pass('C5-超并发交错不串号', `并发 ${n}（> Tomcat 线程数）下 A/B 交错读的归属不漂移`, detail, [ev])
            : R.fail('C5-超并发交错不串号', `并发 ${n} 下 A/B 交错读`, '🔴 ' + detail, [ev])
}

const CASES = { C1, C2, C3, C4, C5 }
const only = (process.argv.slice(2).find((x) => x.startsWith('--only=')) || '').replace('--only=', '')
for (const k of (only ? only.split(',') : Object.keys(CASES))) {
  try { await CASES[k]() } catch (e) { R.skip(`${k}-环境阻塞`, `${k} 未完成`, String(e.message).slice(0, 300)) }
}
writeFileSync(join(OUT, 'probe-cross-raw.json'), JSON.stringify(REC, null, 2))
const sum = R.summary()
log(`=== probe-cross 读数：pass=${sum.pass} fail=${sum.fail} skip=${sum.skip} total=${sum.total} ===`)
save('probe-cross-summary.json', { ...sum, stamp: STAMP })
