// 判据组 P：并发 × 跨租户串号（真 Promise.all 并打 + 预热 + 双读 DB 对照）
// 用法：node probe.mjs [--flip] [--n=120] [--conc=60]
import { api, loginApi, Recorder, psql, log, OUT } from './lib.mjs'
import { RESOURCES, dbIds, A, B } from './resources.mjs'
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'

const args = Object.fromEntries(process.argv.slice(2).map((a) => {
  const [k, v] = a.replace(/^--/, '').split('='); return [k, v ?? true]
}))
const FLIP = !!args.flip
const N = Number(args.n || 120)
const CONC = Number(args.conc || 60)
const R = new Recorder(`probe${FLIP ? '-flip' : ''}-main.json`)
log(`=== probe 开始 flip=${FLIP} n=${N} conc=${CONC} ===`)

/** 期望：本租户响应里的对象必须属本租户。FLIP ⇒ 反转成「允许含对方租户对象」以证断言会红。 */
function judgeLeak(badCount) {
  // FLIP（红证①）：把「必须全部属本租户」反转成「允许含对方租户对象」⇒ 有越租户才 pass
  return FLIP ? badCount > 0 : badCount === 0
}

const OWN = {}, FOREIGN = {}
const subj = {}
for (const s of [A, B]) {
  const l = await loginApi(s.phone)
  subj[s.tenant] = l
  log(`主体登录：${s.phone} → tenantId=${l.user.tenantId} role=${l.user.role} user.id=${l.user.id}`)
}

// 预取每个资源在 A/B 两侧的全量 id 集合（直连 DB，不靠响应自述）
const idSet = {}
for (const r of RESOURCES) {
  idSet[r.table] = { 20: new Set(dbIds(r.table, 20)), 21: new Set(dbIds(r.table, 21)) }
}
// 反向对照：判定「响应里的 id 是否属别的租户」还需第三租户（C=1）无关集
const otherTenants = { 20: [21, 1], 21: [20, 1] }

function classifyId(table, id, tenant) {
  const s = idSet[table]
  if (!s) return 'unknown'
  for (const t of [20, 21, 1]) if (s[t]?.has(String(id))) return t === tenant ? 'own' : `FOREIGN:${t}`
  return 'unknown'
}

/** 从响应体里抽出「对象 id 列表」（与 resources.mjs 的提取器同源） */
function extractIds(res, resource) {
  const d = res.json?.data
  if (!d) return []
  try { return resource.extract(d).filter((x) => x != null).map(String) } catch { return [] }
}

// ── ① 预热：把 Tomcat 线程池填满（先跑一轮不进观测）──
async function warmup() {
  const warm = []
  for (let i = 0; i < CONC * 2; i++) {
    const t = i % 2 === 0 ? 20 : 21
    const r = RESOURCES[i % RESOURCES.length]
    warm.push(api('GET', r.list, { token: subj[t].token }))
  }
  await Promise.all(warm)
  log(`预热完成：${warm.length} 个并发请求（conc=${CONC * 2}）`)
}

// ── ② 真并发交错：列表 + 按 id 读 ──
async function concurrentSweep() {
  const tasks = []
  for (let i = 0; i < N; i++) {
    const tenant = i % 2 === 0 ? 20 : 21
    const other = tenant === 20 ? 21 : 20
    const r = RESOURCES[i % RESOURCES.length]
    const tok = subj[tenant].token
    const mode = i % 3 // 0,1=列表 2=按 id 读
    if (mode === 2 && r.read) {
      const ids = [...idSet[r.table][tenant]]
      if (!ids.length) continue
      const id = ids[i % ids.length]
      tasks.push({ i, tenant, other, r, kind: 'read', id, p: api('GET', r.read(id), { token: tok }) })
    } else {
      tasks.push({ i, tenant, other, r, kind: 'list', p: api('GET', r.list, { token: tok }) })
    }
  }
  const t0 = Date.now()
  const results = await Promise.all(tasks.map((t) => t.p))
  const wall = Date.now() - t0
  const done = results.map((r) => Date.now() - t0)
  const ev = []
  let leaked = 0, nonOk = 0, checked = 0
  for (let k = 0; k < tasks.length; k++) {
    const t = tasks[k], res = results[k]
    if (res.status !== 200) { nonOk++; continue }
    const ids = extractIds(res, t.r)
    checked += ids.length
    // ① 响应自述 tenant_id（若在体里）② 直连 DB 的 id→租户 归属
    let selfTenant = null
    const obj = res.json?.data?.items?.[0] ?? res.json?.data
    if (obj && typeof obj === 'object' && 'tenant_id' in obj) selfTenant = obj.tenant_id
    const foreign = []
    for (const id of ids) { const c = classifyId(t.r.table, id, t.tenant); if (c.startsWith('FOREIGN')) foreign.push({ id, belongsTo: c }) }
    if (selfTenant != null && selfTenant !== t.tenant && t.kind === 'read') foreign.push({ id: `selfTenant=${selfTenant}`, belongsTo: `FOREIGN:${selfTenant}` })
    if (foreign.length) {
      leaked++
      ev.push({ req: `${t.kind} ${t.r.key} by tenant ${t.tenant}`, other: t.other, status: res.status, foreign: foreign.slice(0, 5), idsSample: ids.slice(0, 5), bodyHead: res.text.slice(0, 200) })
    } else if (ev.length < 3 && ids.length) {
      ev.push({ req: `${t.kind} ${t.r.key} by tenant ${t.tenant}`, other: t.other, status: res.status, foreign: [], idsSample: ids.slice(0, 3), foreignCountLeft: 0 })
    }
  }
  const pass = judgeLeak(leaked)
  // 交错可核性读数：若有 K 个响应在「第 1 个响应到达」之前就已经在飞（并发窗口），说明请求确实重叠
  const msList = results.map((r) => r.ms)
  const firstDone = Math.min(...msList)
  const overlapped = msList.filter((m) => m > firstDone).length
  const stats = { n: tasks.length, concRequested: CONC, wallMs: wall, firstResponseMs: firstDone, requestsStillInFlightWhenFirstResponseArrived: overlapped, maxMs: Math.max(...results.map((r) => r.ms)), checkedIds: checked, leakedResponses: leaked, nonOk, sample: ev.slice(0, 6) }
  writeFileSync(join(OUT, `probe${FLIP ? '-flip' : ''}-concurrency.json`), JSON.stringify(stats, null, 2))
  const detail = `并发 ${tasks.length} 请求（请求并发上限 ${CONC}，预热后观测；墙钟 ${wall}ms，首个响应 ${firstDone}ms 时仍有 ${overlapped} 个请求在飞 ⇒ 真交错），逐响应核对 ${checked} 个对象 id（直连 DB 归属）→ 越租户响应 ${leaked} 个、非 200 ${nonOk} 个`
  if (pass) R.pass('P1-并发交错', 'A/B token 交错打同类端点（列表+按 id 读）', detail, ev.slice(0, 6))
  else R.fail('P1-并发交错', 'A/B token 交错打同类端点（列表+按 id 读）', '🔴 ' + detail + ' ⇒ 出现对方租户数据', ev.slice(0, 6))
  return { leaked, nonOk, checked, n: tasks.length }
}

// ── ③ 租户切换疲劳：同会话连接连续交替 A→B→A→B ──
async function fatigueSwitch() {
  const seq = []
  const r = RESOURCES.find((x) => x.key === 'orders')
  // 用同一 keep-alive 连接（fetch 默认复用 undici 连接池）
  for (let i = 0; i < 120; i++) {
    const tenant = i % 2 === 0 ? 20 : 21
    seq.push({ i, tenant, p: api('GET', r.list, { token: subj[tenant].token }) })
  }
  const out = await Promise.all(seq.map((s) => s.p))
  let bad = 0; const ev = []
  for (let k = 0; k < seq.length; k++) {
    const t = seq[k], res = out[k]
    if (res.status !== 200) { bad++; ev.push({ i: t.i, tenant: t.tenant, status: res.status, head: res.text.slice(0, 120) }); continue }
    const ids = extractIds(res, r)
    const foreign = ids.filter((id) => classifyId(r.table, id, t.tenant).startsWith('FOREIGN'))
    if (foreign.length) { bad++; ev.push({ i: t.i, tenant: t.tenant, status: res.status, foreign: foreign.slice(0, 5) }) }
  }
  const pass = FLIP ? bad > 0 : bad === 0
  const detail = `交替 120 次（A↔B），异常响应 ${bad} 个`
  writeFileSync(join(OUT, `probe${FLIP ? '-flip' : ''}-fatigue.json`), JSON.stringify({ bad, ev: ev.slice(0, 10) }, null, 2))
  if (pass) R.pass('P3-切换疲劳', '连续交替 A→B→A→B ≥60 次后仍不得串号', detail, ev.slice(0, 5))
  else R.fail('P3-切换疲劳', '连续交替 A→B→A→B ≥60 次后仍不得串号', '🔴 ' + detail, ev.slice(0, 5))
}

// ── ④ 异常路径：让一个请求中途失败，紧接着换另一租户发请求 ──
async function exceptionPaths() {
  const r = RESOURCES.find((x) => x.key === 'orders')
  const bigBody = 'x'.repeat(3 * 1024 * 1024)
  const cases = [
    { id: 'X1-非法id', trigger: () => api('GET', '/api/admin/orders/not-a-uuid-@@@', { token: subj[20].token }) },
    { id: 'X2-超大body', trigger: () => api('POST', '/api/admin/orders', { token: subj[20].token, raw: true, body: '{"remark":"' + bigBody + '"}', headers: { 'Content-Type': 'application/json' }, timeoutMs: 20000 }) },
    { id: 'X3-删除中读', trigger: () => api('DELETE', '/api/admin/products/00000000000000000000000000000000', { token: subj[20].token }) },
    { id: 'X4-无token', trigger: () => api('GET', r.list, {}) },
    { id: 'X5-篡改token', trigger: () => api('GET', r.list, { token: subj[20].token.slice(0, -3) + 'xyz' }) },
  ]
  const ev = []
  let bad = 0
  for (const c of cases) {
    const trig = await c.trigger()
    // 紧接着用另一租户(B=21)发同类请求 ⇒ 不得继承 20 的租户上下文
    const after = await api('GET', r.list, { token: subj[21].token })
    const ids = after.status === 200 ? extractIds(after, r) : []
    const foreign = ids.filter((id) => classifyId(r.table, id, 21).startsWith('FOREIGN'))
    const ok = (after.status === 200 && foreign.length === 0) || after.status === 401 || after.status === 403
    if (!ok) bad++
    ev.push({ case: c.id, triggerStatus: trig.status, triggerHead: trig.text.slice(0, 120), afterStatus: after.status, afterTenant: 21, foreign: foreign.slice(0, 5), idsSample: ids.slice(0, 3) })
  }
  const pass = FLIP ? bad > 0 : bad === 0
  writeFileSync(join(OUT, `probe${FLIP ? '-flip' : ''}-exception.json`), JSON.stringify(ev, null, 2))
  const detail = `5 条异常路径（非法 id / 3MB body / 并发删除 / 无 token / 篡改 token）后紧接另一租户请求 ⇒ 继承前一租户上下文 ${bad} 次`
  if (pass) R.pass('P4-异常路径', '异常/失败请求后不得继承前一请求的租户上下文', detail, ev)
  else R.fail('P4-异常路径', '异常/失败请求后不得继承前一请求的租户上下文', '🔴 ' + detail, ev)
}

// ── ⑤ 高并发下的按 id 读（同类端点双向交错，A 打 B 的 id / B 打 A 的 id）──
async function crossReadConcurrent() {
  const pairs = RESOURCES.filter((x) => x.read)
  const tasks = []; const ev0 = []
  for (let i = 0; i < 40; i++) {
    const r = pairs[i % pairs.length]
    const attacker = i % 2 === 0 ? 20 : 21
    const victim = attacker === 20 ? 21 : 20
    const vids = [...idSet[r.table][victim]]
    if (!vids.length) continue
    const vid = vids[i % vids.length]
    const ownIds = [...idSet[r.table][attacker]]
    if (!ownIds.length) { ev0.push({ note: '正对照不可达：attacker 侧该表无行', r: r.key, attacker }); continue }
    tasks.push({ i, r, attacker, victim, vid, p: api('GET', r.read(vid), { token: subj[attacker].token }) })
    tasks.push({ i, r, attacker, victim, vid, pos: true, p: api('GET', r.read(ownIds[0]), { token: subj[attacker].token }) })
  }
  const out = await Promise.all(tasks.map((t) => t.p))
  let leak = 0, posOk = 0, posTot = 0, negRejected = 0, negTot = 0
  const ev = []
  for (let k = 0; k < tasks.length; k++) {
    const t = tasks[k], res = out[k]
    if (t.pos) { posTot++; if (res.status === 200) posOk++; else ev.push({ case: '正对照未 200', r: t.r.key, tenant: t.attacker, status: res.status, head: res.text.slice(0, 150) }) }
    else {
      negTot++
      if ([403, 404].includes(res.status)) negRejected++
      const ids = res.status === 200 ? extractIds(res, t.r) : []
      const foreign = ids.filter((id) => classifyId(t.r.table, id, t.attacker).startsWith('FOREIGN'))
      if (res.status === 200 && (ids.length > 0 || foreign.length)) { leak++; ev.push({ case: '越租户读成功', r: t.r.key, attacker: t.attacker, victim: t.victim, status: res.status, ids: ids.slice(0, 5), head: res.text.slice(0, 200) }) }
    }
  }
  writeFileSync(join(OUT, `probe${FLIP ? '-flip' : ''}-crossread.json`), JSON.stringify({ posOk, posTot, negRejected, negTot, leak, skippedNoRows: ev0, ev: ev.slice(0, 10) }, null, 2))
  const expectPos = FLIP ? posOk < posTot : posOk === posTot
  const expectNeg = FLIP ? leak > 0 : leak === 0
  const detail = `正对照 A→A ${posOk}/${posTot} 个 200（跳过 ${ev0.length} 个 attacker 侧无行的资源）；越租户 A→B 的 id ${negTot} 个：被拒 ${negRejected}、越权成功 ${leak}`
  if (posTot === 0) { R.skip('P5-并发跨租户读', '并发下按 id 读的跨租户拒绝 + 同租户正对照', '正对照前置不成立（两侧均无行）'); return }
  if (expectPos && expectNeg) R.pass('P5-并发跨租户读', '并发下按 id 读的跨租户拒绝 + 同租户正对照', detail, ev.slice(0, 5))
  else R.fail('P5-并发跨租户读', '并发下按 id 读的跨租户拒绝 + 同租户正对照', '🔴 ' + detail, [...ev0, ...ev].slice(0, 6))
}

await warmup()
const s1 = await concurrentSweep()
await fatigueSwitch()
await exceptionPaths()
await crossReadRes()
async function crossReadRes() { await crossReadConcurrent() }

const sum = R.summary()
log(`=== probe 读数：pass=${sum.pass} fail=${sum.fail} skip=${sum.skip} total=${sum.total} ===`)
writeFileSync(join(OUT, `probe${FLIP ? '-flip' : ''}-summary.json`), JSON.stringify({ flip: FLIP, n: N, conc: CONC, ...sum, sweep: s1 }, null, 2))
