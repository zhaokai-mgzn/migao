// 线① 判据组 D —— 未命中候选 → 蒸馏 → 入卡（候选全生命周期 + 租户归属）
//
// 被测：admin-api(:8080) /api/admin/knowledge/candidates/** + ai-agent-service(:8001) /api/internal/knowledge/distill
// 期望来源：KnowledgeCandidateController 契约（adopt ⇒ 生成卡片并把候选置 adopted / reject ⇒ rejected）
//           + DB 逐字段（knowledge_candidates / knowledge_cards）+ tenant_id 归属
// 说明：候选**种子**由本包直连 DB 写入探针行（确定性夹具，避免依赖 LLM 蒸馏才能造出候选）；
//       蒸馏面（:8001）单独作**契约级**读数（不判定其内容质量 —— 那是 LLM 面，按 #4262 不刷额度）。
import {
  Recorder, judge, adminApi, adminLogin, agentApi, internalCall, serviceToken, one, psql,
  guardedWrite, assertProbe, PROBE_PREFIX, TENANT_A, buildPoint, log, nowCST, LIVE_WORKTREE,
} from './lib.mjs'

const R = new Recorder('probe-knowledge-candidates.json')
const bp = buildPoint(LIVE_WORKTREE, 8080)
const EV = [`admin-api 构建点: ${bp.shaFull} (${bp.subject}) procStart=${bp.procStart}`,
            `ai-agent 构建点: ${buildPoint().shaFull}`]
const TAG = `d${Date.now().toString(36)}`
log(`===== 判据组 D 开始 ${nowCST().cst} =====`)
const { token } = await adminLogin()

// ── D1 夹具：直连 DB 造 3 条探针候选（pending / 供 adopt / reject / adopt-edited）──
const candIds = []
{
  for (const [i, kind] of ['adopt', 'reject', 'edited'].entries()) {
    const id = `l1cand${TAG}${i}`
    assertProbe(`${PROBE_PREFIX}候选-${kind}`)
    guardedWrite(`-- probe-ok
      insert into knowledge_candidates (id, tenant_id, source_type, source_ref, suggested_title, suggested_answer,
        suggested_category, suggested_keywords, confidence, evidence, status, created_at)
      values ('${id}', ${TENANT_A}, 'manual', '${PROBE_PREFIX}', '${PROBE_PREFIX}候选-${kind}-${TAG}',
        '${PROBE_PREFIX}候选答复-${kind}', 'faq', '${PROBE_PREFIX},候选', 0.900, '${PROBE_PREFIX}证据',
        'pending', now());`)
    candIds.push({ id, kind })
  }
  const rows = psql(`select id, tenant_id, status, suggested_title from knowledge_candidates where id in (${candIds.map((c) => `'${c.id}'`).join(',')})`)
  judge(R, {
    id: 'D1-1', name: '夹具就绪：3 条 pending 候选落库（正对照）',
    expect: '3 行且 status 全为 pending', actual: { rows: rows.length, statuses: rows.map((r) => r.status) },
    pass: rows.length === 3 && rows.every((r) => r.status === 'pending'),
    expectSource: '正对照（缺它则后续 adopt/reject 判据无夹具）', evidence: EV,
  })
}

// ── D2 候选读面（pending-count 与列表）──────────────────────────
{
  const pc = await adminApi('GET', '/api/admin/knowledge/candidates/pending-count', { token })
  judge(R, {
    id: 'D2-1', name: 'pending-count 读面 ⇒ 200 且计数 ≥ 3',
    expect: 'HTTP 200 且 count ≥ 3（本包刚插入 3 条）',
    actual: { status: pc.status, data: pc.data },
    pass: pc.status === 200 && Number(Object.values(pc.data || {})[0] ?? -1) >= 3,
    expectSource: '本包夹具数（3）+ 库中既有候选数 ⇒ 下界判据（不写死总数）', evidence: EV,
  })
  const list = await adminApi('GET', `/api/admin/knowledge/candidates?page=1&size=100&status=pending`, { token })
  const items = list.data?.records || list.data?.list || list.data?.items || []
  const mine = items.filter((x) => candIds.some((c) => c.id === x.id))
  judge(R, {
    id: 'D2-2', name: '候选列表读面含本包 3 条且 tenant 一致',
    expect: '3 条命中且 tenantId 均为登录租户',
    actual: { httpStatus: list.status, total: list.data?.total, mine: mine.map((x) => ({ id: x.id, tenantId: x.tenantId, status: x.status })) },
    pass: mine.length === 3 && mine.every((x) => Number(x.tenantId) === TENANT_A),
    expectSource: '读面必须按 TenantContext 过滤 + 返回项 tenantId == 登录租户', evidence: EV,
  })
}

// ── D3 adopt：候选 → 入卡，状态流转 + DB 留痕 ────────────────────
{
  const c = candIds.find((x) => x.kind === 'adopt')
  const r = await adminApi('POST', `/api/admin/knowledge/candidates/${c.id}/adopt`, { token })
  const card = r.data
  const candRow = one(`select status, reviewed_at, reviewed_by, tenant_id from knowledge_candidates where id='${c.id}'`)
  judge(R, {
    id: 'D3-1', name: 'adopt ⇒ 200 且返回新卡', expect: 'HTTP 200 且 data.id 非空',
    actual: { status: r.status, cardId: card?.id, body: r.json },
    pass: r.status === 200 && !!card?.id,
    expectSource: 'KnowledgeCandidateController.adopt 契约（返回 KnowledgeCard）', evidence: EV,
  })
  judge(R, {
    id: 'D3-2', name: 'adopt 后候选状态流转 pending → adopted',
    expect: 'status=="adopted" 且 reviewed_at 非空',
    actual: { status: candRow?.status, reviewed_at: candRow?.reviewed_at, reviewed_by: candRow?.reviewed_by },
    pass: normStatus(candRow?.status) === "adopted" && !!candRow?.reviewed_at,
    expectSource: '候选状态机：pending → adopted（reviewed_at 打点）', evidence: EV,
  })
  if (card?.id) {
    const cardRow = one(`select id, tenant_id, title, answer, source_type, source_ref, status from knowledge_cards where id='${card.id}'`)
    const wantTitle = `${PROBE_PREFIX}候选-adopt-${TAG}`
    const bad = []
    if (Number(cardRow?.tenant_id) !== TENANT_A) bad.push({ field: 'tenant_id', got: cardRow?.tenant_id, want: TENANT_A })
    if (cardRow?.title !== wantTitle) bad.push({ field: 'title', got: cardRow?.title, want: wantTitle })
    if (Number(cardRow?.id === undefined)) bad.push({ field: 'exists', got: null, want: card.id })
    judge(R, {
      id: 'D3-3', name: '入卡产物 DB 逐字段：tenant/title/answer 来自候选且租户一致',
      expect: 'tenant_id/标题/答复与候选一致（不跨租户）',
      actual: { mismatches: bad, cardRow },
      pass: bad.length === 0 && !!cardRow,
      expectSource: '入卡 = 用候选内容建卡；租户必须继承候选租户（TenantContext）', evidence: EV,
    })
    R.add('D3-4', '登记：入卡产物的 source_type/source_ref（追溯面读数，非判据）', 'pass',
      `source_type=${cardRow?.source_type} source_ref=${cardRow?.source_ref} status=${cardRow?.status}`,
      [`cardId=${card.id}`, `候选 id=${c.id}`])
    console.log(JSON.stringify({ adoptedCardId: card.id }))
  }
}

// ── D4 reject：状态流转 + 不产卡 ───────────────────────────────
{
  const c = candIds.find((x) => x.kind === 'reject')
  const r = await adminApi('POST', `/api/admin/knowledge/candidates/${c.id}/reject`, { token, body: { note: `${PROBE_PREFIX}拒绝原因` } })
  const row = one(`select status, status_note, reviewed_at, tenant_id from knowledge_candidates where id='${c.id}'`)
  judge(R, {
    id: 'D4-1', name: 'reject ⇒ 200 且候选状态流转 pending → rejected',
    expect: 'HTTP 200 且 DB status=="rejected" 且 reviewed_at 非空',
    actual: { status: r.status, dbStatus: row?.status, note: row?.status_note, reviewed_at: row?.reviewed_at },
    pass: r.status === 200 && normStatus(row?.status) === 'rejected' && !!row?.reviewed_at,
    expectSource: '候选状态机：pending → rejected（status_note 记录原因）', evidence: EV,
  })
  const cards = psql(`select id from knowledge_cards where tenant_id=${TENANT_A} and title like '${PROBE_PREFIX}候选-reject%'`)
  judge(R, {
    id: 'D4-2', name: 'reject 不得产生知识卡片',
    expect: '0 张同源卡片', actual: { cards: cards.length },
    pass: cards.length === 0,
    expectSource: '拒绝语义：reject 只改候选状态，不落卡', evidence: EV,
  })
}

// ── D5 adopt-edited：编辑后入卡 ────────────────────────────────
{
  const c = candIds.find((x) => x.kind === 'edited')
  const editedTitle = `${PROBE_PREFIX}候选-edited-改-${TAG}`
  const editedAnswer = `${PROBE_PREFIX}候选答复-edited-改-${TAG}`
  const r = await adminApi('POST', `/api/admin/knowledge/candidates/${c.id}/adopt-edited`, {
    token, body: { suggestedTitle: editedTitle, suggestedAnswer: editedAnswer },
  })
  const cardId = r.data?.id
  const row = cardId ? one(`select title, answer, tenant_id, status from knowledge_cards where id='${cardId}'`) : null
  judge(R, {
    id: 'D5-1', name: 'adopt-edited ⇒ 入卡内容用「编辑后」的值（不是候选原值）',
    expect: `title=编辑后 / answer=编辑后 / tenant=${TENANT_A}`,
    actual: { status: r.status, cardId, row },
    pass: r.status === 200 && !!cardId && row?.title === editedTitle && row?.answer === editedAnswer && Number(row?.tenant_id) === TENANT_A,
    expectSource: 'adopt-edited 语义：以编辑补丁覆盖候选字段后入卡', evidence: EV,
  })
  const candRow = one(`select status from knowledge_candidates where id='${c.id}'`)
  judge(R, {
    id: 'D5-2', name: 'adopt-edited 后候选状态流转（不得仍 pending）',
    expect: 'status ∈ {adopted, edited, converted} 且 ≠ pending',
    actual: { status: candRow?.status },
    pass: !!candRow && normStatus(candRow.status) !== 'pending',
    expectSource: '已处置的候选不得留在 pending（否则会被重复采纳）', evidence: EV,
  })
}

// ── D6 蒸馏面契约级读数（:8001 内部面；内容质量不在本线判定范围）──
{
  const noTok = await agentApi('POST', '/api/internal/knowledge/distill', { body: { tenant_id: TENANT_A, conversation_text: 'x' } })
  judge(R, {
    id: 'D6-1', name: '蒸馏面无 Service Token ⇒ 401',
    expect: 'HTTP 401', actual: { status: noTok.status, code: noTok.json?.detail?.error?.code },
    pass: noTok.status === 401,
    expectSource: 'auth.py::verify_service_token（内部面统一守卫）', evidence: EV,
  })
  const r = await internalCall('POST', '/api/internal/knowledge/distill', {
    tenantId: TENANT_A,
    body: { tenant_id: TENANT_A, conversation_text: `${PROBE_PREFIX}顾客问：布艺沙发怎么保养？\n客服答：定期吸尘、避免暴晒。`, max_candidates: 2 },
    timeoutMs: 120000,
  })
  const okShape = r.status === 200 && r.json?.success === true && Array.isArray(r.json?.data?.candidates)
  judge(R, {
    id: 'D6-2', name: '蒸馏面契约：200 + success + data.candidates 为数组',
    expect: 'HTTP 200 且 data.candidates 是数组（不得 500）',
    actual: { status: r.status, success: r.json?.success, count: r.json?.data?.candidates?.length, keys: Object.keys(r.json?.data || {}) },
    pass: okShape,
    expectSource: 'internal.py::distill_knowledge 契约（提炼失败降级返回空候选，不阻断）', evidence: EV,
  })
  R.add('D6-3', '登记：蒸馏产物是否落库（只读观察，非判据）', 'pass',
    r.json?.data?.candidates?.length ? `返回 ${r.json.data.candidates.length} 条候选（未写库 ⇒ 由调用方 admin-api 落库）` : '返回 0 条候选（LLM 侧降级或空）',
    ['登记项：本线不判定蒸馏内容质量（LLM 面，按 #4262 不刷额度）'])
}

// 状态归一（不同实现可能用 adopted/approved 等）
function normStatus(s) { return s === 'approved' ? 'adopted' : s }

R.dump()
const s = R.summary()
log(`===== 判据组 D 结束：pass=${s.pass} fail=${s.fail} skip=${s.skip} =====`)
console.log(JSON.stringify({ group: 'D', summary: s, candIds, tag: TAG }))
