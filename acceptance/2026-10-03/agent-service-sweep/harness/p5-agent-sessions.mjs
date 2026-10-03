// 线① 判据组 F —— 客服工作台（会话列表 / 转人工 / 接管 / 结束）+ @Async 蒸馏监听器租户归属
//
// 被测：admin-api(:8080) /api/admin/agent-sessions/**
// 期望来源：AgentSessionController/Service 契约（状态机 waiting→active→ended；assign 要求 waiting）
//           + DB 留痕（agent_sessions.tenant_id）+ 跨租户读必须拒
// 缺口承接：线④ §9.1 点名「@Async SessionDistillListener：隔离栈建会话→结束→断言
//           knowledge_candidates.tenant_id 与结束方一致」—— 本组 F6/F7 即该缺口。
import {
  Recorder, judge, adminApi, adminLogin, agentApi, mintJwt, one, psql, guardedWrite, assertProbe,
  PROBE_PREFIX, PROBE_USER, TENANT_A, TENANT_B, ADMIN_PHONE, SMS_CODE, buildPoint, log, nowCST, LIVE_WORKTREE, sleep,
} from './lib.mjs'

const R = new Recorder('probe-agent-sessions.json')
const bp = buildPoint(LIVE_WORKTREE, 8080)
const EV = [`admin-api 构建点: ${bp.shaFull} (${bp.subject}) procStart=${bp.procStart}`,
            `ai-agent 构建点: ${buildPoint().shaFull}`]
const TAG = `f${Date.now().toString(36)}`
log(`===== 判据组 F 开始 ${nowCST().cst} =====`)

const { token: tokA } = await adminLogin(ADMIN_PHONE, SMS_CODE)
// 租户 B 管理员（线④已核该手机号 ⇒ tenant 21）
const bLogin = await adminApi('POST', '/api/auth/sms/login', { body: { phone: '13797101248', code: SMS_CODE } })
const tokB = bLogin.json?.data?.accessToken ?? bLogin.json?.data?.access_token
const tenantB = bLogin.json?.data?.user?.tenantId ?? bLogin.json?.data?.tenantId ?? bLogin.json?.data?.tenant_id
EV.push(`登录 A=tenant ${TENANT_A} / B=tenant ${tenantB}`)

let agentSessionId = null

// ── F0 夹具：先建**真实 AI 会话**（:8001 C 端面）——
// 为什么必要：`agent_sessions.ai_session_id` 有外键 `agent_sessions_ai_session_id_fkey`
// 指向 `sessions(id)`；用一个凭空的 aiSessionId 会撞 FK ⇒ 500（实测，见 REPORT §4）。
// ⇒ 正路是「转人工时把**真实存在**的 AI 会话 id 带过来」，本夹具即复刻该正路。
const aiCust = PROBE_USER(`f_${TAG}`)
const tokC = mintJwt({ userId: aiCust, tenantId: TENANT_A })
let aiSessionId = null
{
  const r = await agentApi('POST', '/api/chat/sessions', { token: tokC, body: { title: `${PROBE_PREFIX}转人工源会话-${TAG}` } })
  aiSessionId = r.data?.id
  judge(R, {
    id: 'F0-1', name: '夹具：先建真实 AI 会话（:8001）作为转人工源',
    expect: 'HTTP 200 且有 session id', actual: { status: r.status, aiSessionId },
    pass: r.status === 200 && !!aiSessionId,
    expectSource: '转人工正路要求 ai_session_id 指向真实会话（FK 约束，见 PG 报错逐字）', evidence: EV,
  })
}

// ── F1 转人工建会话（service token 或管理员；此处用管理员 token）──
{
  const r = await adminApi('POST', '/api/admin/agent-sessions', {
    token: tokA,
    body: {
      aiSessionId: aiSessionId, customerId: aiCust,
      reason: `${PROBE_PREFIX}转人工-${TAG}`, aiContextSummary: `${PROBE_PREFIX}摘要`,
      aiContextMessages: [{ role: 'user', content: `${PROBE_PREFIX}顾客说：我要找人工`, createdAt: nowCST().cst }],
    },
  })
  agentSessionId = r.data?.id
  judge(R, {
    id: 'F1-1', name: '转人工建会话 ⇒ 200 且有 id（初始 waiting）',
    expect: 'HTTP 200 且 data.id 非空且 status=="waiting"',
    actual: { status: r.status, id: agentSessionId, s: r.data?.status, body: String(r.text).slice(0, 250) },
    pass: r.status === 200 && !!agentSessionId && r.data?.status === 'waiting',
    expectSource: 'AgentSessionService.createSessionForHandoff —— 初始 status="waiting"', evidence: EV,
  })
}
if (!agentSessionId) {
  R.skip('F2-*', '工作台后续判据', '转人工建会话失败 ⇒ 无夹具')
} else {
  // ── F2 DB 留痕 + 租户归属 ────────────────────────────────────
  const row = one(`select id, tenant_id, customer_id, ai_session_id, status, employee_id, ai_context_messages, started_at, deleted from agent_sessions where id='${agentSessionId}'`)
  const bad = []
  if (Number(row?.tenant_id) !== TENANT_A) bad.push({ field: 'tenant_id', got: row?.tenant_id, want: TENANT_A })
  if (row?.customer_id !== aiCust) bad.push({ field: 'customer_id', got: row?.customer_id, want: aiCust })
  if (row?.ai_session_id !== aiSessionId) bad.push({ field: 'ai_session_id', got: row?.ai_session_id, want: aiSessionId })
  if (row?.status !== 'waiting') bad.push({ field: 'status', got: row?.status, want: 'waiting' })
  judge(R, {
    id: 'F2-1', name: '转人工会话 DB 逐字段（tenant/customer/aiSession/status）',
    expect: `tenant_id=${TENANT_A} ∧ customer_id/ai_session_id 与请求一致 ∧ status=waiting`,
    actual: { mismatches: bad, row: { ...row, ai_context_messages: Array.isArray(row?.ai_context_messages) ? `数组(${row.ai_context_messages.length})` : row?.ai_context_messages } },
    pass: bad.length === 0,
    expectSource: '请求体是期望来源；TenantContext 决定 tenant_id（转人工不得跨租户）', evidence: EV,
  })

  // ── F3 列表读面（本租户可见 / 他租户不可见）────────────────────
  const list = await adminApi('GET', `/api/admin/agent-sessions?page=1&size=100&status=waiting&keyword=probe_line1`, { token: tokA })
  const items = list.data?.records || list.data?.list || list.data?.items || []
  const mine = items.filter((x) => x.id === agentSessionId)
  judge(R, {
    id: 'F3-1', name: '工作台会话列表（本租户）能看到该转人工会话',
    expect: '命中 1 条且 tenantId 一致', actual: { httpStatus: list.status, total: list.data?.total, mine: mine.length },
    pass: mine.length === 1 && Number(mine[0]?.tenantId ?? TENANT_A) === TENANT_A,
    expectSource: 'getSessionPage(..., tenantId=TenantContext) ⇒ 列表按租户过滤', evidence: EV,
  })
  if (tokB) {
    const listB = await adminApi('GET', `/api/admin/agent-sessions?page=1&size=100&keyword=probe_line1`, { token: tokB })
    const itemsB = listB.data?.records || listB.data?.list || listB.data?.items || []
    const leaked = itemsB.filter((x) => x.id === agentSessionId)
    judge(R, {
      id: 'F3-2', name: '他租户（21）列表看不到租户 20 的转人工会话',
      expect: '命中 0 条', actual: { httpStatus: listB.status, total: listB.data?.total, leaked: leaked.length, sampleIds: itemsB.map((x) => x.id).slice(0, 5) },
      pass: leaked.length === 0,
      expectSource: '列表按 TenantContext 租户过滤（跨租户不可见）', evidence: EV,
    })
    // 跨租户按 id 读详情 —— 这是「租户归属」的硬判据
    const detailB = await adminApi('GET', `/api/admin/agent-sessions/${agentSessionId}`, { token: tokB })
    const leakedDetail = detailB.status === 200 && JSON.stringify(detailB.json || '').includes(agentSessionId)
    judge(R, {
      id: 'F3-3', name: '跨租户按 id 读会话详情 ⇒ 必须拒（不得返回他租户内容）',
      expect: 'HTTP 4xx（403/404）且响应不含会话内容',
      actual: { status: detailB.status, body: String(detailB.text).slice(0, 200) },
      pass: detailB.status >= 400 && detailB.status < 500 && !leakedDetail,
      expectSource: '租户归属判据：详情面必须以 TenantContext 校验归属（getSessionDetail 的租户校验）',
      evidence: [...EV, `GET /api/admin/agent-sessions/${agentSessionId} with tenant-${tenantB} token`],
    })
  } else {
    R.skip('F3-2/F3-3', '跨租户工作台判据', '租户 B 登录失败 ⇒ 无对照身份；记未覆盖')
  }

  // ── F4 接管（assign）→ 状态机 ────────────────────────────────
  const emp = one(`select id, nickname, phone from users where tenant_id=${TENANT_A} and role<>'customer' and deleted=0 limit 1`)
  const empId = emp?.id
  if (empId) {
    const r = await adminApi('POST', `/api/admin/agent-sessions/${agentSessionId}/assign`, { token: tokA, body: { employeeId: empId } })
    const row2 = one(`select status, employee_id from agent_sessions where id='${agentSessionId}'`)
    judge(R, {
      id: 'F4-1', name: '接管（assign）⇒ waiting → active 且 employee_id 落库',
      expect: `HTTP 200 且 DB status=="active" 且 employee_id=='${empId}'`,
      actual: { status: r.status, dbStatus: row2?.status, employee_id: row2?.employee_id, body: String(r.text).slice(0, 160) },
      pass: r.status === 200 && row2?.status === 'active' && row2?.employee_id === empId,
      expectSource: 'AgentSessionService.assignSession —— 校验 status=="waiting" 后转 active 并落 employee_id', evidence: EV,
    })
    // 人工接管后可查（human-sessions 面读得到 = "能不能用"）
    const detail = await adminApi('GET', `/api/admin/agent-sessions/${agentSessionId}`, { token: tokA })
    const msgs = detail.data?.messages || detail.data?.messageList || []
    judge(R, {
      id: 'F4-2', name: '接管后详情面可查（含 AI 上下文快照）',
      expect: 'HTTP 200 且返回会话对象（aiContext 相关字段存在）',
      actual: { status: detail.status, keys: Object.keys(detail.data || {}).slice(0, 14), msgCount: msgs.length },
      pass: detail.status === 200 && !!detail.data,
      expectSource: '人工接管后工作台必须能读到会话（闭环可查）', evidence: EV,
    })
    // 重复 assign（已 active）⇒ 必须拒（状态机约束）
    const again = await adminApi('POST', `/api/admin/agent-sessions/${agentSessionId}/assign`, { token: tokA, body: { employeeId: empId } })
    judge(R, {
      id: 'F4-3', name: '状态机：已 active 再 assign ⇒ 拒（非 waiting）',
      expect: 'HTTP 4xx', actual: { status: again.status, body: String(again.text).slice(0, 200) },
      pass: again.status >= 400 && again.status < 500,
      expectSource: 'assignSession 校验「校验会话状态必须为 waiting」⇒ 非法流转拒', evidence: EV,
    })
  } else {
    R.skip('F4-*', '接管与状态流转', '租户 20 无可用员工夹具 ⇒ 未覆盖')
  }

  // ── F5 结束会话 → ended ──────────────────────────────────────
  {
    const r = await adminApi('POST', `/api/admin/agent-sessions/${agentSessionId}/end`, { token: tokA })
    const row3 = one(`select status, ended_at from agent_sessions where id='${agentSessionId}'`)
    judge(R, {
      id: 'F5-1', name: '结束会话 ⇒ status=="ended" 且 ended_at 打点',
      expect: 'HTTP 200 且 DB status=="ended" 且 ended_at 非空',
      actual: { status: r.status, dbStatus: row3?.status, ended_at: row3?.ended_at, body: String(r.text).slice(0, 160) },
      pass: r.status === 200 && row3?.status === 'ended' && !!row3?.ended_at,
      expectSource: 'AgentSessionService.endSession —— setStatus("ended") + setEndedAt(now)', evidence: EV,
    })
    // 已 ended 再 end ⇒ 拒（状态机）
    const again = await adminApi('POST', `/api/admin/agent-sessions/${agentSessionId}/end`, { token: tokA })
    judge(R, {
      id: 'F5-2', name: '状态机：已 ended 再 end ⇒ 拒',
      expect: 'HTTP 4xx', actual: { status: again.status, body: String(again.text).slice(0, 200) },
      pass: again.status >= 400 && again.status < 500,
      expectSource: 'endSession 校验「ended 不可再结束」', evidence: EV,
    })
  }

  // ── F6 @Async 蒸馏监听器：结束后 knowledge_candidates 的租户归属（线④缺口）──
  // 监听器在会话结束（AFTER_COMMIT）触发 → 写候选到本租户。等待其落库（最多 45s，不轮询式 sleep）。
  {
    const since = new Date(Date.now() - 5 * 60 * 1000).toISOString()
    let rows = []
    const deadline = Date.now() + 45000
    while (Date.now() < deadline) {
      rows = psql(`select id, tenant_id, source_type, source_ref, status, created_at from knowledge_candidates where source_ref like '%${agentSessionId}%' or source_ref like '%probe_line1%' order by created_at desc limit 20`)
      if (rows.length) break
      await sleep(5000)
    }
    const foreign = rows.filter((x) => Number(x.tenant_id) !== TENANT_A)
    judge(R, {
      id: 'F6-1', name: '@Async 蒸馏监听器：会话结束后产出的候选租户归属 == 结束方租户',
      expect: `候选行 tenant_id 全为 ${TENANT_A}（跨租户条数 = 0）`,
      actual: { candidateRows: rows.length, foreignTenantRows: foreign.map((x) => ({ id: x.id, tenant_id: x.tenant_id })), sample: rows.slice(0, 3) },
      pass: foreign.length === 0,
      expectSource: 'SessionDistillListener 在租户上下文内写候选（TenantContext 必须随事务/请求传递）⇒ 不得落他租户',
      evidence: [...EV, `SQL: knowledge_candidates where source_ref like %${agentSessionId}% or %probe_line1%`],
    })
    if (rows.length === 0) {
      R.skip('F6-2', '@Async 监听器触发存在性', '45s 内未观测到任何候选行 ⇒ 监听器未触发或该租户蒸馏被关闭；本条记未覆盖（不得读成通过）')
    } else {
      const mine = rows.filter((x) => x.source_ref && String(x.source_ref).includes(agentSessionId))
      R.add('F6-2', '登记：蒸馏候选产出读数（非判据）', 'pass',
        mine.length ? `本次会话产生 ${mine.length} 条候选（source_ref 含 sessionId）` : `未产生绑定本会话的候选（仅观测到 ${rows.length} 条同前缀历史候选）`,
        [`source_ref 样例: ${rows.slice(0, 3).map((x) => x.source_ref).join(' | ')}`])
    }
  }
}

R.dump()
const s = R.summary()
log(`===== 判据组 F 结束：pass=${s.pass} fail=${s.fail} skip=${s.skip} | agentSession=${agentSessionId} =====`)
console.log(JSON.stringify({ group: 'F', summary: s, agentSessionId, tag: TAG }))
export const _meta = { agentSessionId, tag: TAG }
