// 线① 判据组 B —— 租户链路与身份作用域（本线重点）
//
// 覆盖：跨租户读写拒绝 / 租户上下文缺失 fail-closed / 并发串号 / C 端身份面差异
// 期望来源：`app/api/chat.py::_guard_session` 契约（租户或用户不匹配 ⇒ 403）+ DB 租户归属
//           + B 端内部面由 `body.tenant_id` 决定租户（线④已核，本包只做 DB 侧一一对应复核）
// 前置：:8001 需在 DEBUG=false 运行（无 token 一律 401 ⇒ 租户只由 JWT claim 决定，读数可归因）
import {
  Recorder, judge, agentApi, internalCall, mintJwt, psql, one, guardedWrite, assertProbe,
  buildPoint, log, TENANT_A, TENANT_B, PROBE_PREFIX, PROBE_USER, nowCST,
} from './lib.mjs'

const R = new Recorder('probe-tenant-isolation.json')
const bp = buildPoint()
const EV = [`构建点: ${bp.worktree} @ ${bp.shaFull} procStart=${bp.procStart} 观测窗口起点 ${nowCST().cst}`]
const TAG = `b${Date.now().toString(36)}`

const UA1 = PROBE_USER(`A1_${TAG}`), UA2 = PROBE_USER(`A2_${TAG}`), UB1 = PROBE_USER(`B1_${TAG}`)
const tokA1 = mintJwt({ userId: UA1, tenantId: TENANT_A })
const tokA2 = mintJwt({ userId: UA2, tenantId: TENANT_A })
const tokB1 = mintJwt({ userId: UB1, tenantId: TENANT_B })
log(`===== 判据组 B 开始 ${nowCST().cst} | 租户A=${TENANT_A} 租户B=${TENANT_B} =====`)

const created = []   // {sessionId, tenant, user, token}

async function mkSession(token, tenant, user) {
  const r = await agentApi('POST', '/api/chat/sessions', { token, body: { title: `${PROBE_PREFIX}会话 ${user}` } })
  if (r.status !== 200) return { r, sessionId: null }
  return { r, sessionId: r.data?.id ?? r.json?.data?.id }
}

// ── B1 造租户 A 会话（B 端内部面之外的正对照来源）──────────────────
const sA1 = await mkSession(tokA1, TENANT_A, UA1)
const sB1 = await mkSession(tokB1, TENANT_B, UB1)
judge(R, {
  id: 'B1-1', name: '正对照：租户 A 会话创建成功',
  expect: 'HTTP 200 且 data.id 非空', actual: { status: sA1.r.status, sessionId: sA1.sessionId, tenant: sA1.r.data?.tenant_id },
  pass: sA1.r.status === 200 && !!sA1.sessionId,
  expectSource: '正对照（缺它则跨租户判据是空断言）', evidence: EV,
})
judge(R, {
  id: 'B1-2', name: '正对照：租户 B 会话创建成功',
  expect: 'HTTP 200 且 data.id 非空', actual: { status: sB1.r.status, sessionId: sB1.sessionId, tenant: sB1.r.data?.tenant_id },
  pass: sB1.r.status === 200 && !!sB1.sessionId,
  expectSource: '正对照（跨租户判据的对侧夹具）', evidence: EV,
})
created.push({ sessionId: sA1.sessionId, tenant: TENANT_A, user: UA1, token: tokA1 })
created.push({ sessionId: sB1.sessionId, tenant: TENANT_B, user: UB1, token: tokB1 })

// ── B2 DB 侧：会话落库的 tenant_id 必须与 JWT claim 一一对应 ────────
for (const c of created.filter((x) => x.sessionId)) {
  const row = one(`select id, tenant_id, customer_id, status from sessions where id='${c.sessionId}'`)
  judge(R, {
    id: `B2-${c.tenant}`, name: `会话 ${c.sessionId} 落库 tenant_id == JWT claim ${c.tenant}`,
    expect: `${c.tenant} / customer_id=${c.user}`,
    actual: { tenant_id: row?.tenant_id, customer_id: row?.customer_id, status: row?.status },
    pass: Number(row?.tenant_id) === c.tenant && row?.customer_id === c.user,
    expectSource: 'JWT claim tenantId 是服务端唯一租户来源（auth.py::get_current_user）⇒ DB 行必须一致',
    evidence: [...EV, `SQL: select id,tenant_id,customer_id,status from sessions where id='${c.sessionId}'`],
  })
}

// ── B3 跨租户读：B 读 A 的会话必须拒（不得返回 A 的内容）──────────
{
  const sid = sA1.sessionId
  const h = await agentApi('GET', `/api/chat/history/${sid}`, { token: tokB1 })
  const leaked = JSON.stringify(h.json || '').includes(String(sid)) && h.status === 200
  judge(R, {
    id: 'B3-1', name: '跨租户读历史（B 读 A 会话）⇒ 拒',
    expect: 'HTTP 403 且 code=="PERMISSION_DENIED"，响应体不含会话内容',
    actual: { status: h.status, code: h.json?.detail?.error?.code, bodyLen: String(h.text).length },
    pass: h.status === 403 && h.json?.detail?.error?.code === 'PERMISSION_DENIED' && !leaked,
    expectSource: 'chat.py::_guard_session —— session.tenant_id != current_user.tenant_id ⇒ 403 PERMISSION_DENIED',
    evidence: [...EV, `GET /api/chat/history/${sid} with tenant ${TENANT_B} token`],
  })
  // 跨租户关闭
  const cl = await agentApi('PUT', `/api/chat/sessions/${sid}/close`, { token: tokB1 })
  judge(R, {
    id: 'B3-2', name: '跨租户关闭会话 ⇒ 拒',
    expect: 'HTTP 403', actual: { status: cl.status, code: cl.json?.detail?.error?.code },
    pass: cl.status === 403,
    expectSource: 'chat.py::_guard_session（close 端点走同一守卫）', evidence: EV,
  })
  // 跨租户删除
  const dl = await agentApi('DELETE', `/api/chat/sessions/${sid}`, { token: tokB1 })
  judge(R, {
    id: 'B3-3', name: '跨租户删除会话 ⇒ 拒',
    expect: 'HTTP 403', actual: { status: dl.status, code: dl.json?.detail?.error?.code },
    pass: dl.status === 403,
    expectSource: 'chat.py::_guard_session（delete 端点走同一守卫）', evidence: EV,
  })
  // A 会话仍在（跨租户操作确实无副作用）
  const after = one(`select id, status, deleted from sessions where id='${sid}'`)
  judge(R, {
    id: 'B3-4', name: '跨租户拒后 A 会话无副作用（未被关闭/删除）',
    expect: 'row 存在 且 deleted=0 且 status 未被改成 closed',
    actual: { exists: !!after, status: after?.status, deleted: after?.deleted },
    pass: !!after && Number(after.deleted) === 0 && after.status !== 'closed',
    expectSource: '拒 ⇒ 不得产生写副作用（守卫在写之前抛出）', evidence: EV,
  })
}

// ── B4 同租户不同用户：不得互读（身份作用域不止租户）──────────────
{
  const sid = sA1.sessionId
  const h = await agentApi('GET', `/api/chat/history/${sid}`, { token: tokA2 })
  judge(R, {
    id: 'B4-1', name: '同租户不同用户读他人会话 ⇒ 拒',
    expect: 'HTTP 403', actual: { status: h.status, code: h.json?.detail?.error?.code },
    pass: h.status === 403,
    expectSource: 'chat.py::_guard_session —— customer_id != user_id ⇒ 403（身份作用域含用户维度）', evidence: EV,
  })
  const own = await agentApi('GET', `/api/chat/history/${sid}`, { token: tokA1 })
  judge(R, {
    id: 'B4-2', name: '正对照：会话属主读自己的会话 ⇒ 200',
    expect: 'HTTP 200 且 success==true', actual: { status: own.status, success: own.json?.success },
    pass: own.status === 200 && own.json?.success === true,
    expectSource: '正对照（缺它则 B4-1 可能只是「一律 403」的空断言）', evidence: EV,
  })
}

// ── B5 租户上下文缺失 / 不存在租户 ⇒ fail-closed ──────────────────
{
  // 5.1 无 tenant_id claim 的 token
  const tokNoTenant = mintJwt({ userId: `probe_line1_notenant_${TAG}`, tenantId: null })
  const r = await agentApi('GET', '/api/chat/sessions', { token: tokNoTenant })
  judge(R, {
    id: 'B5-1', name: 'JWT 缺 tenantId claim ⇒ 401（不得默认落到某租户）',
    expect: 'HTTP 401 且 code=="TOKEN_INVALID"',
    actual: { status: r.status, code: r.json?.detail?.error?.code, body: r.json },
    pass: r.status === 401 && r.json?.detail?.error?.code === 'TOKEN_INVALID',
    expectSource: 'auth.py::get_current_user —— "if not user.user_id or not user.tenant_id: 401 TOKEN_INVALID"（fail-closed）',
    evidence: EV,
  })
  // 5.2 无 token + 伪造 X-Tenant-Id 头：不得被当成租户来源
  const r2 = await agentApi('GET', '/api/chat/sessions', { headers: { 'X-Tenant-Id': String(TENANT_A), 'X-Debug-Role': 'customer' } })
  judge(R, {
    id: 'B5-2', name: '无 token + 伪造 X-Tenant-Id ⇒ 401（头不得成为租户来源）',
    expect: 'HTTP 401', actual: { status: r2.status, body: r2.json },
    pass: r2.status === 401,
    expectSource: 'C 端租户只来自 JWT claim（auth.py）；DEBUG=false 时 X-Debug-Role 亦不构成旁路',
    evidence: EV,
  })
  // 5.3 合法 token + 伪造 X-Tenant-Id：租户必须以 claim 为准
  const r3 = await agentApi('GET', '/api/chat/sessions', { token: tokA1, headers: { 'X-Tenant-Id': String(TENANT_B) } })
  const items = r3.json?.data?.items || []
  const cross = items.filter((i) => Number(i.tenant_id) !== TENANT_A)
  judge(R, {
    id: 'B5-3', name: '合法 A token + X-Tenant-Id=B ⇒ 仍只返回 A 的会话',
    expect: `全部 items.tenant_id == ${TENANT_A}（跨租户条目数 = 0）`,
    actual: { status: r3.status, count: items.length, crossCount: cross.length, tenants: [...new Set(items.map((i) => i.tenant_id))] },
    pass: r3.status === 200 && cross.length === 0,
    expectSource: '租户来源 = JWT claim（auth.py），头不参与；DB 侧另核（B2）',
    evidence: [...EV, 'GET /api/chat/sessions with A token + X-Tenant-Id: B'],
  })
}

// ── B6 并发串号（含交错 X-Tenant-Id）─────────────────────────────
// 设计：N 组 = 3 租户身份 × 6 并发，交错发起；每条核 (a) 响应的 tenant_id (b) DB 行的 tenant_id
// (c) 用「错误租户的 token」回读必须 403。任何跨租户命中 ⇒ 红。
{
  const groups = [
    { tenant: TENANT_A, user: UA1, token: tokA1 },
    { tenant: TENANT_B, user: UB1, token: tokB1 },
    { tenant: TENANT_A, user: UA2, token: tokA2 },
  ]
  const N = 6
  const jobs = []
  for (let i = 0; i < N; i++) {
    for (const [gi, g] of groups.entries()) {
      jobs.push((async () => {
        const hdr = { 'X-Tenant-Id': String(gi % 2 === 0 ? TENANT_B : TENANT_A) } // 故意交错、且与真实租户不同
        const r = await agentApi('POST', '/api/chat/sessions', { token: g.token, headers: hdr, body: { title: `${PROBE_PREFIX}并发 ${g.user} #${i}` } })
        return { gi, tenant: g.tenant, user: g.user, token: g.token, status: r.status, sessionId: r.data?.id ?? r.json?.data?.id, respTenant: r.data?.tenant_id ?? r.json?.data?.tenant_id, hdrTenant: hdr['X-Tenant-Id'] }
      })())
    }
  }
  const results = await Promise.all(jobs)
  const ok = results.filter((x) => x.status === 200 && x.sessionId)
  judge(R, {
    id: 'B6-1', name: `并发建会话 ${results.length} 条全部成功（并发度 ${N}×${groups.length}）`,
    expect: `${results.length} 条 HTTP 200 且有 id`, actual: { total: results.length, ok: ok.length, statuses: [...new Set(results.map((x) => x.status))] },
    pass: ok.length === results.length,
    expectSource: '正对照：并发夹具须先全绿，否则串号判据无判别力', evidence: EV,
  })
  // 逐条核响应租户
  const respMismatch = results.filter((x) => Number(x.respTenant) !== x.tenant)
  judge(R, {
    id: 'B6-2', name: '并发：响应 tenant_id 与请求身份一一对应',
    expect: '不一致条数 = 0', actual: { mismatch: respMismatch.map((x) => ({ user: x.user, want: x.tenant, got: x.respTenant, hdr: x.hdrTenant })) },
    pass: respMismatch.length === 0,
    expectSource: '响应 tenant_id 必须等于该请求 JWT claim 的 tenantId', evidence: EV,
  })
  // 逐条核 DB 行
  const ids = ok.map((x) => `'${x.sessionId}'`).join(',')
  const rows = ids ? psql(`select id, tenant_id, customer_id from sessions where id in (${ids})`) : []
  const byId = new Map(rows.map((r) => [r.id, r]))
  const dbMismatch = ok.filter((x) => {
    const r = byId.get(x.sessionId)
    return !r || Number(r.tenant_id) !== x.tenant || r.customer_id !== x.user
  })
  judge(R, {
    id: 'B6-3', name: '并发：DB 留痕 tenant_id/customer_id 与请求一一对应',
    expect: `不一致条数 = 0（核对 ${ok.length} 行）`,
    actual: { checked: ok.length, dbRows: rows.length, mismatch: dbMismatch.map((x) => ({ sid: x.sessionId, want: x.tenant, wantUser: x.user, got: byId.get(x.sessionId) || null })) },
    pass: ok.length > 0 && rows.length === ok.length && dbMismatch.length === 0,
    expectSource: 'DB 行是权威留痕（sessions.tenant_id / customer_id），逐条与请求身份比对',
    evidence: [...EV, `SQL: select id,tenant_id,customer_id from sessions where id in (${ids.slice(0, 120)}…)`],
  })
  // 交叉回读：用别的租户 token 读每条 ⇒ 必须全 403
  const crossings = []
  for (const x of ok.slice(0, 12)) {
    const otherTok = x.tenant === TENANT_A ? tokB1 : tokA1
    const h = await agentApi('GET', `/api/chat/history/${x.sessionId}`, { token: otherTok })
    crossings.push({ sid: x.sessionId, ownerTenant: x.tenant, readerTenant: x.tenant === TENANT_A ? TENANT_B : TENANT_A, status: h.status })
  }
  const crossHits = crossings.filter((c) => c.status !== 403)
  judge(R, {
    id: 'B6-4', name: '并发：交叉回读全部 403（无一条串号可读）',
    expect: `403 条数 = ${crossings.length}`,
    actual: { total: crossings.length, hits: crossHits },
    pass: crossings.length > 0 && crossHits.length === 0,
    expectSource: '每条会话用「对侧租户」token 回读，必须被 _guard_session 拒',
    evidence: EV,
  })
  for (const x of ok) created.push({ sessionId: x.sessionId, tenant: x.tenant, user: x.user, token: x.token })
}

// ── B7 C 端身份面 vs B 端专有面（越权调用）────────────────────────
{
  // C 端 token 调 B 端内部面 ⇒ 必须拒（内部面只认 Service Token）
  const r = await agentApi('GET', '/api/internal/tools', { token: tokA1 })
  judge(R, {
    id: 'B7-1', name: 'C 端 JWT 调 B 端内部面 ⇒ 401（不认 JWT）',
    expect: 'HTTP 401 且 code=="AUTH_REQUIRED"',
    actual: { status: r.status, code: r.json?.detail?.error?.code },
    pass: r.status === 401 && r.json?.detail?.error?.code === 'AUTH_REQUIRED',
    expectSource: 'auth.py::verify_service_token 只读 X-Service-Token；JWT 不构成内部面凭证',
    evidence: EV,
  })
  // 无 Service Token 直接调工具执行 ⇒ 401
  const r2 = await agentApi('POST', '/api/internal/tools/execute', { token: tokA1, body: { tool_name: 'order_query', params: {}, tenant_id: TENANT_A, user_id: 'x' } })
  judge(R, {
    id: 'B7-2', name: 'C 端 JWT 调工具执行面 ⇒ 401',
    expect: 'HTTP 401', actual: { status: r2.status, code: r2.json?.detail?.error?.code },
    pass: r2.status === 401,
    expectSource: '同上（内部面仅 Service Token）', evidence: EV,
  })
  // 内部面是否暴露 C 端专有面差异：列出工具名做只读登记（不作 pass/fail 主张）
  const ok = await agentApi('GET', '/api/internal/tools', { headers: { 'X-Service-Token': (await import('./lib.mjs')).serviceToken() } })
  const names = (ok.json?.data?.tools || []).map((t) => t.name)
  R.add('B7-3', '登记：内部面暴露的只读工具集（读数，非判据）', 'pass',
    `count=${names.length}`, [`工具名: ${names.join(', ')}`])
}

R.dump()
const s = R.summary()
log(`===== 判据组 B 结束：pass=${s.pass} fail=${s.fail} skip=${s.skip} =====`)
console.log(JSON.stringify({ group: 'B', summary: s, created }, null, 2))
