// 线① 判据组 A —— 服务可起性 + 鉴权契约（含 DEBUG 旁路判别力对照）
//
// 用法：MODE=debugfalse|debugtrue node p0-service-auth.mjs
//   · debugfalse → 断言「无 token 一律 401，X-Debug-Role 不构成旁路」（期望拒）
//   · debugtrue  → 同一批请求对照（期望放行）⇒ 证明 debugfalse 侧的判据有判别力
// 期望来源：`app/utils/auth.py::get_current_user` 的契约分派（DEBUG + X-Debug-Role 才放行）
//           + HTTP 鉴权惯例（401/403 不得 500）。禁止拿被测系统读面当期望。
import {
  Recorder, judge, agentApi, internalCall, serviceToken, mintJwt, mintExpiredJwt,
  mintForeignSignedJwt, buildPoint, log, TENANT_A, nowCST,
} from './lib.mjs'

const MODE = process.env.MODE || 'debugfalse'
const IS_DEBUG_FALSE = MODE === 'debugfalse'
const R = new Recorder(`probe-auth-${MODE}.json`)
const EV = []

const bp = buildPoint()
EV.push(`构建点: worktree=${bp.worktree} sha=${bp.shaFull} subject=${bp.subject} procStart=${bp.procStart} dirty="${bp.dirty}"`)

log(`===== 判据组 A [MODE=${MODE}] 开始 ${nowCST().cst} =====`)
log(`构建点: ${bp.shaFull} (${bp.subject}) procStart=${bp.procStart}`)

// ── A1 健康面语义 ────────────────────────────────────────────────
{
  const h = await agentApi('GET', '/health', {})
  judge(R, {
    id: 'A1-1', name: '/health 存活语义',
    expect: 'HTTP 200 且 body.status=="healthy"', actual: { status: h.status, body: h.json },
    pass: h.status === 200 && h.json?.status === 'healthy',
    expectSource: 'main.py::health_check 契约（返回 status/service/version）', evidence: EV,
  })
  const r = await agentApi('GET', '/ready', {})
  judge(R, {
    id: 'A1-2', name: '/ready 就绪语义（fail-closed）',
    expect: 'HTTP 200 且 body.status=="ready"（DB+Redis 均通时）', actual: { status: r.status, body: r.json },
    pass: r.status === 200 && r.json?.status === 'ready',
    expectSource: 'main.py::ready_check 契约（check_readiness 失败 ⇒ 503 not_ready）', evidence: EV,
  })
  const nf = await agentApi('GET', '/api/chat/nonexistent-endpoint-xyz', {})
  judge(R, {
    id: 'A1-3', name: '未注册路径不得 500',
    expect: 'HTTP 404', actual: { status: nf.status, body: String(nf.text).slice(0, 120) },
    pass: nf.status === 404,
    expectSource: 'FastAPI 路由契约（未注册 ⇒ 404，不得 500/502）', evidence: EV,
  })
  const badMethod = await agentApi('DELETE', '/health', {})
  judge(R, {
    id: 'A1-4', name: '错误方法不得 500',
    expect: 'HTTP 405', actual: { status: badMethod.status },
    pass: badMethod.status === 405,
    expectSource: 'HTTP 语义（方法不允许 ⇒ 405）', evidence: EV,
  })
}

// ── A2 C 端 JWT 契约（无 token / 错 token / 过期 / 异钥签名）──────
const C_PATHS = ['/api/chat/sessions', '/api/chat/sessions/latest', '/api/chat/quick-actions']
const debugRole = IS_DEBUG_FALSE ? 'none' : 'customer'

for (const p of C_PATHS) {
  const h = { 'X-Debug-Role': debugRole }
  const r = await agentApi('GET', p, { headers: h })
  const expectCode = IS_DEBUG_FALSE ? 401 : 200
  judge(R, {
    id: `A2-notoken-${p.replace(/[^a-z]+/gi, '_')}`,
    name: `无 token 调 ${p} [X-Debug-Role=${debugRole}, DEBUG=${!IS_DEBUG_FALSE}]`,
    expect: `HTTP ${expectCode}`,
    actual: { status: r.status, body: r.json },
    pass: r.status === expectCode,
    expectSource: IS_DEBUG_FALSE
      ? 'auth.py::get_current_user —— DEBUG=false 时无 token 必 401（X-Debug-Role 不构成旁路）'
      : 'auth.py::get_current_user —— DEBUG=true + X-Debug-Role 显式调试头才放行（对照侧，证明判据有判别力）',
    evidence: EV,
  })
  if (r.status === 0 || r.status >= 500) {
    R.fail(`A2-notoken-${p.replace(/[^a-z]+/gi, '_')}-5xx`, `${p} 未返回 4xx/2xx 而是 ${r.status}`, `不得 500：${String(r.text).slice(0, 160)}`, EV)
  }
}

// 错 token（结构合法但不是 JWT）
{
  const r = await agentApi('GET', '/api/chat/sessions', { token: 'garbage.token.here' })
  judge(R, {
    id: 'A2-badtoken', name: '畸形 Bearer token 被拒',
    expect: 'HTTP 401 且 error.code ∈ {TOKEN_INVALID,AUTH_REQUIRED}',
    actual: { status: r.status, code: r.json?.detail?.error?.code },
    pass: r.status === 401 && ['TOKEN_INVALID', 'AUTH_REQUIRED'].includes(r.json?.detail?.error?.code),
    expectSource: 'auth.py::verify_jwt_token 契约（解析失败 ⇒ 401 TOKEN_INVALID）', evidence: EV,
  })
}

// 过期 token
{
  const tok = mintExpiredJwt({ tenantId: TENANT_A })
  const r = await agentApi('GET', '/api/chat/sessions', { token: tok })
  judge(R, {
    id: 'A2-expired', name: '过期 JWT 被拒（TOKEN_EXPIRED）',
    expect: 'HTTP 401 且 error.code=="TOKEN_EXPIRED"',
    actual: { status: r.status, code: r.json?.detail?.error?.code, body: r.json },
    pass: r.status === 401 && r.json?.detail?.error?.code === 'TOKEN_EXPIRED',
    expectSource: 'auth.py::verify_jwt_token —— ExpiredSignatureError ⇒ 401 TOKEN_EXPIRED', evidence: EV,
  })
}

// 异钥签名（结构合法、签名对不上公钥）
{
  const tok = mintForeignSignedJwt({ tenantId: TENANT_A, userId: 'probe_line1_foreign' })
  const r = await agentApi('GET', '/api/chat/sessions', { token: tok })
  judge(R, {
    id: 'A2-foreignkey', name: '异钥签名的 JWT 被拒',
    expect: 'HTTP 401 且 error.code=="TOKEN_INVALID"',
    actual: { status: r.status, code: r.json?.detail?.error?.code },
    pass: r.status === 401 && r.json?.detail?.error?.code === 'TOKEN_INVALID',
    expectSource: 'auth.py::verify_jwt_token —— RS256 公钥验签失败 ⇒ InvalidTokenError ⇒ 401', evidence: EV,
  })
}

// audience 不匹配（结构合法、签名正确、aud 错）
{
  const tok = mintJwt({ userId: 'probe_line1_aud', tenantId: TENANT_A, aud: 'not-migao' })
  const r = await agentApi('GET', '/api/chat/sessions', { token: tok })
  judge(R, {
    id: 'A2-aud', name: 'aud 不含 migao 的 JWT 被拒',
    expect: 'HTTP 401',
    actual: { status: r.status, code: r.json?.detail?.error?.code },
    pass: r.status === 401,
    expectSource: 'auth.py::verify_jwt_token —— 手动校验 aud 含 "migao"，否则 InvalidTokenError', evidence: EV,
  })
}

// 正对照：合法 token 必须通行（证明上面几条不是「一律拒绝」的空断言）
{
  const tok = mintJwt({ userId: 'probe_line1_pos', tenantId: TENANT_A })
  const r = await agentApi('GET', '/api/chat/sessions', { token: tok })
  judge(R, {
    id: 'A2-positive', name: '正对照：合法 RS256 token 放行',
    expect: 'HTTP 200 且 success==true',
    actual: { status: r.status, success: r.json?.success },
    pass: r.status === 200 && r.json?.success === true,
    expectSource: '正对照（缺它则 A2 各条可能只是「一律 401」的空断言）', evidence: EV,
  })
}

// ── A3 B 端内部面 Service Token 契约 ─────────────────────────────
{
  const r = await agentApi('GET', '/api/internal/tools', {})
  judge(R, {
    id: 'A3-1', name: '内部面无 Service Token ⇒ 401',
    expect: 'HTTP 401 且 code=="AUTH_REQUIRED"',
    actual: { status: r.status, code: r.json?.detail?.error?.code },
    pass: r.status === 401 && r.json?.detail?.error?.code === 'AUTH_REQUIRED',
    expectSource: 'auth.py::verify_service_token —— 缺头 ⇒ 401 AUTH_REQUIRED', evidence: EV,
  })
  const w = await agentApi('GET', '/api/internal/tools', { headers: { 'X-Service-Token': 'deadbeef-wrong-token' } })
  judge(R, {
    id: 'A3-2', name: '内部面错误 Service Token ⇒ 401（不得 500）',
    expect: 'HTTP 401 且 code=="AUTH_REQUIRED"',
    actual: { status: w.status, code: w.json?.detail?.error?.code },
    pass: w.status === 401 && w.json?.detail?.error?.code === 'AUTH_REQUIRED',
    expectSource: 'auth.py::verify_service_token —— compare_digest 不等 ⇒ 401', evidence: EV,
  })
  const ok = await agentApi('GET', '/api/internal/tools', { headers: { 'X-Service-Token': serviceToken() } })
  const names = (ok.json?.data?.tools || []).map((t) => t.name)
  judge(R, {
    id: 'A3-3', name: '正对照：正确 Service Token 放行且工具集非空',
    expect: 'HTTP 200 且 tools.length>0',
    actual: { status: ok.status, count: names.length, sample: names.slice(0, 5) },
    pass: ok.status === 200 && names.length > 0,
    expectSource: '正对照 + auth.py::verify_service_token 通过分支', evidence: EV,
  })
  // 写工具必须被内部面拦（read_only=False ⇒ 403）
  const writeTools = ['order_create', 'product_update', 'customer_manage', 'knowledge_card_manage']
  const found = writeTools.filter((n) => names.includes(n))
  if (found.length) {
    const w = await internalCall('POST', '/api/internal/tools/execute', {
      tenantId: TENANT_A, body: { tool_name: found[0], params: {}, tenant_id: TENANT_A, user_id: 'probe_line1_write' },
    })
    judge(R, {
      id: 'A3-4', name: `内部面拒写工具（${found[0]}）`,
      expect: 'HTTP 403 且 code=="WRITE_TOOL_FORBIDDEN"',
      actual: { status: w.status, code: w.json?.detail?.error?.code, body: w.json },
      pass: w.status === 403 && w.json?.detail?.error?.code === 'WRITE_TOOL_FORBIDDEN',
      expectSource: 'internal.py::execute_tool —— read_only=False ⇒ 403 WRITE_TOOL_FORBIDDEN', evidence: EV,
    })
  } else {
    R.skip('A3-4', '内部面拒写工具', `工具集中未出现候选写工具（${writeTools.join(',')}）⇒ 本条无夹具，记未覆盖`)
  }
  // 不存在的工具 ⇒ 404
  const nf = await internalCall('POST', '/api/internal/tools/execute', {
    tenantId: TENANT_A, body: { tool_name: 'no_such_tool_xyz', params: {}, tenant_id: TENANT_A, user_id: 'probe_line1' },
  })
  judge(R, {
    id: 'A3-5', name: '内部面未知工具 ⇒ 404 TOOL_NOT_FOUND',
    expect: 'HTTP 404', actual: { status: nf.status, code: nf.json?.detail?.error?.code },
    pass: nf.status === 404,
    expectSource: 'internal.py::execute_tool —— registry.get_tool 为 None ⇒ 404', evidence: EV,
  })
}

// ── A4 Service Token 不回显 / 不泄露（只读判定）────────────────────
{
  const tok = serviceToken()
  const probes = [
    ['GET', '/health'], ['GET', '/ready'], ['GET', '/openapi.json'],
  ]
  let leaked = []
  for (const [m, p] of probes) {
    const r = await agentApi(m, p, {})
    if (String(r.text).includes(tok)) leaked.push(`${p} 响应体含 service token`)
  }
  const err = await agentApi('GET', '/api/internal/tools', { headers: { 'X-Service-Token': 'x' } })
  if (String(err.text).includes(tok)) leaked.push('/api/internal/tools 错误响应含 service token')
  judge(R, {
    id: 'A4-1', name: 'SERVICE_TOKEN 不在无鉴权/错误响应中回显',
    expect: '0 处命中', actual: { leaked, tokenLen: tok.length },
    pass: leaked.length === 0,
    expectSource: '机密不回显（只读判定：扫描 health/ready/openapi 与 401 响应体）', evidence: EV,
  })
}

// ── A5 汇总 + 判别力自证 ─────────────────────────────────────────
const s = R.summary()
log(`===== 判据组 A [MODE=${MODE}] 结束：pass=${s.pass} fail=${s.fail} skip=${s.skip} =====`)
if (!IS_DEBUG_FALSE) {
  const noTokenRecs = R.records.filter((r) => r.id.startsWith('A2-notoken-'))
  const all200 = noTokenRecs.length > 0 && noTokenRecs.every((r) => r.detail.includes('200'))
  R.add('A5-discriminator', '判别力自证：DEBUG=true 侧旁路确实放行',
    all200 ? 'pass' : 'fail',
    all200
      ? `DEBUG=true 侧 ${noTokenRecs.length} 条无 token 请求全部放行（≠ DEBUG=false 侧的 401）⇒ A2 各条有判别力`
      : `DEBUG=true 侧未如预期放行（${noTokenRecs.map((r) => r.id).join(',')}）`,
    EV)
}
R.dump()
export default R
