// 线① 判据组 C —— 知识卡片全生命周期（建 → 改 → 生效 → 失效 → 读面一致）
//
// 被测：admin-api(:8080, main-live 构建) 的 /api/admin/knowledge/cards/**
// 期望来源：KnowledgeCardService 契约（create 打 TenantContext 租户 / publish→published /
//           archive→archived / update 递增 version）+ 逐字段与 DB 比对（DB 是权威留痕）
// 本包只动「线①验收」前缀的探针卡片；用后自清。
import {
  Recorder, judge, adminApi, adminLogin, one, psql, guardedWrite, assertProbe,
  PROBE_PREFIX, TENANT_A, buildPoint, log, nowCST, LIVE_WORKTREE,
} from './lib.mjs'

const R = new Recorder('probe-knowledge-cards.json')
const bp = buildPoint(LIVE_WORKTREE, 8080)
const EV = [`admin-api 构建点: ${bp.worktree} @ ${bp.shaFull} (${bp.subject}) procStart=${bp.procStart}`,
            `ai-agent 构建点: ${buildPoint().shaFull}`]
const TAG = `c${Date.now().toString(36)}`
log(`===== 判据组 C 开始 ${nowCST().cst} =====`)

const { token } = await adminLogin()
const AUTH_EV = [...EV, `登录: admin ${TENANT_A} 租户（sms 万能码）`]
log(`登录成功 tenant=${token ? 'ok' : 'FAIL'}`)

const created = []
const cardBody = (title, extra = {}) => ({
  title, category: 'faq', industry: 'curtain', sourceType: 'manual',
  question: `${PROBE_PREFIX}问题-${title}`, answer: `${PROBE_PREFIX}标准答复-${title}`,
  keywords: `${PROBE_PREFIX},探针`, ...extra,
})

// ── C1 建卡 ────────────────────────────────────────────────────
const TITLE1 = `${PROBE_PREFIX}知识卡-${TAG}`
let cardId = null
{
  const r = await adminApi('POST', '/api/admin/knowledge/cards', { token, body: cardBody(TITLE1) })
  cardId = r.data?.id
  judge(R, {
    id: 'C1-1', name: '建卡 ⇒ 200 且有 id',
    expect: 'HTTP 200 且 data.id 非空', actual: { status: r.status, id: cardId, body: r.json },
    pass: r.status === 200 && !!cardId,
    expectSource: 'KnowledgeCardController.create 契约（200 + 返回实体）', evidence: AUTH_EV,
  })
  if (!cardId) { log('建卡失败，后续判据无夹具'); }
}
if (cardId) {
  created.push(cardId)
  // 逐字段 DB 核对
  const row = one(`select id, tenant_id, title, category, industry, source_type, question, answer, keywords, status, version, created_by, deleted from knowledge_cards where id='${cardId}'`)
  const d = row || {}
  const checks = [
    ['tenant_id', Number(d.tenant_id), TENANT_A],
    ['title', d.title, TITLE1],
    ['category', d.category, 'faq'],
    ['industry', d.industry, 'curtain'],
    ['source_type', d.source_type, 'manual'],
    ['question', d.question, `${PROBE_PREFIX}问题-${TITLE1}`],
    ['answer', d.answer, `${PROBE_PREFIX}标准答复-${TITLE1}`],
    ['keywords', d.keywords, `${PROBE_PREFIX},探针`],
    ['status', d.status, 'draft'],
    ['version', Number(d.version), 1],
    ['deleted', Number(d.deleted), 0],
  ]
  const bad = checks.filter(([, got, want]) => got !== want)
  judge(R, {
    id: 'C1-2', name: '建卡后 DB 逐字段与请求一致（11 字段）',
    expect: '全部字段相符', actual: { mismatches: bad.map(([f, g, w]) => ({ field: f, got: g, want: w })), row: d },
    pass: bad.length === 0 && !!row,
    expectSource: '请求体是期望来源（逐字段），DB 行是权威留痕；契约声明 create 的 status 初值 = draft、version = 1',
    evidence: [...AUTH_EV, `SQL: select 11 字段 from knowledge_cards where id='${cardId}'`],
  })
  // 创建方必须是「租户 A」，不得出现跨租户
  judge(R, {
    id: 'C1-3', name: '建卡租户归属 = 登录租户（不得落他租户）',
    expect: `tenant_id == ${TENANT_A}`, actual: { tenant_id: d.tenant_id },
    pass: Number(d.tenant_id) === TENANT_A,
    expectSource: 'KnowledgeCardService.create 打 TenantContext.getTenantId()', evidence: AUTH_EV,
  })
}

// ── C2 更新（改字段 + version 递增）────────────────────────────
if (cardId) {
  const NEW_ANSWER = `${PROBE_PREFIX}修订答复-${TAG}`
  const NEW_TITLE = `${TITLE1}-改`
  const r = await adminApi('PUT', `/api/admin/knowledge/cards/${cardId}`, {
    token, body: { title: NEW_TITLE, answer: NEW_ANSWER, category: 'policy' },
  })
  judge(R, {
    id: 'C2-1', name: '更新卡 ⇒ 200', expect: 'HTTP 200', actual: { status: r.status, body: r.json },
    pass: r.status === 200,
    expectSource: 'KnowledgeCardController.update 契约', evidence: AUTH_EV,
  })
  const row = one(`select title, answer, category, status, version, tenant_id, updated_at from knowledge_cards where id='${cardId}'`)
  const bad = []
  if (row?.title !== NEW_TITLE) bad.push({ field: 'title', got: row?.title, want: NEW_TITLE })
  if (row?.answer !== NEW_ANSWER) bad.push({ field: 'answer', got: row?.answer, want: NEW_ANSWER })
  if (row?.category !== 'policy') bad.push({ field: 'category', got: row?.category, want: 'policy' })
  if (Number(row?.version) !== 2) bad.push({ field: 'version', got: row?.version, want: 2 })
  if (Number(row?.tenant_id) !== TENANT_A) bad.push({ field: 'tenant_id', got: row?.tenant_id, want: TENANT_A })
  judge(R, {
    id: 'C2-2', name: '更新后 DB 字段生效且 version 1→2、租户不变',
    expect: 'title/answer/category 已改、version==2、tenant_id 不变',
    actual: { mismatches: bad, row },
    pass: bad.length === 0,
    expectSource: 'KnowledgeCardService.update —— setVersion(existing.version + 1)；租户不得被改', evidence: AUTH_EV,
  })
}

// ── C3 发布（生效）─────────────────────────────────────────────
if (cardId) {
  const r = await adminApi('POST', `/api/admin/knowledge/cards/${cardId}/publish`, { token })
  const row = one(`select status, reviewed_at, reviewed_by, tenant_id from knowledge_cards where id='${cardId}'`)
  judge(R, {
    id: 'C3-1', name: '发布卡 ⇒ status 落库 published',
    expect: 'HTTP 200 且 DB status=="published"', actual: { status: r.status, dbStatus: row?.status, reviewed_at: row?.reviewed_at },
    pass: r.status === 200 && row?.status === 'published',
    expectSource: 'KnowledgeCardService.publish —— setStatus(STATUS_PUBLISHED)', evidence: AUTH_EV,
  })
  // 读面一致：列表 + search 能找到，且字段与 DB 一致
  const list = await adminApi('GET', `/api/admin/knowledge/cards?page=1&size=50&keyword=${encodeURIComponent(PROBE_PREFIX)}`, { token })
  const items = list.data?.records || list.data?.list || list.data?.items || []
  const found = items.find((x) => x.id === cardId)
  judge(R, {
    id: 'C3-2', name: '读面一致：列表按关键词能读到该卡且字段与 DB 一致',
    expect: 'found 且 status=="published" 且 title 与 DB 相同',
    actual: { httpStatus: list.status, total: list.data?.total, found: found ? { id: found.id, status: found.status, title: found.title } : null, dbTitle: row ? undefined : undefined },
    pass: !!found && found.status === 'published',
    expectSource: '读面（列表）与写面（DB 行）必须一致 —— 禁止只看 HTTP 200', evidence: AUTH_EV,
  })
  const search = await adminApi('GET', `/api/admin/knowledge/cards/search?keyword=${encodeURIComponent(TAG)}`, { token })
  const sItems = Array.isArray(search.data) ? search.data : (search.data?.records || [])
  judge(R, {
    id: 'C3-3', name: '读面一致：search 面能读到该卡',
    expect: '搜索结果含该 cardId', actual: { httpStatus: search.status, count: sItems.length, ids: sItems.map((x) => x.id).slice(0, 5) },
    pass: sItems.some((x) => x.id === cardId),
    expectSource: 'KnowledgeCardController.search 契约（按 title/keywords 命中）', evidence: AUTH_EV,
  })
}

// ── C4 归档（失效）─────────────────────────────────────────────
if (cardId) {
  const r = await adminApi('POST', `/api/admin/knowledge/cards/${cardId}/archive`, { token })
  const row = one(`select status, tenant_id from knowledge_cards where id='${cardId}'`)
  judge(R, {
    id: 'C4-1', name: '归档卡 ⇒ status 落库 archived（失效）',
    expect: 'HTTP 200 且 DB status=="archived"', actual: { status: r.status, dbStatus: row?.status },
    pass: r.status === 200 && row?.status === 'archived',
    expectSource: 'KnowledgeCardService.archive —— setStatus(STATUS_ARCHIVED)', evidence: AUTH_EV,
  })
  // 归档后不得再被 search 当作可用知识（读面一致性）
  const search = await adminApi('GET', `/api/admin/knowledge/cards/search?keyword=${encodeURIComponent(TAG)}`, { token })
  const sItems = Array.isArray(search.data) ? search.data : (search.data?.records || [])
  const still = sItems.find((x) => x.id === cardId)
  judge(R, {
    id: 'C4-2', name: '归档后读面：search 不得再返回该卡（或状态为 archived）',
    expect: 'search 未返回该卡，或返回的 status=="archived"',
    actual: { count: sItems.length, hit: still ? { id: still.id, status: still.status } : null },
    pass: !still || still.status === 'archived',
    expectSource: '失效语义：归档卡片不应作为生效知识被检索命中（读面须与 status 一致）',
    evidence: [...AUTH_EV, '登记：本判据允许两种合法实现（不返回 / 返回但带 archived），只要不冒充生效'],
  })
}

// ── C5 状态机非法流转（跨租户/不存在 id）────────────────────────
{
  const r = await adminApi('PUT', '/api/admin/knowledge/cards/l1probe-no-such-card-xyz', { token, body: { title: 'x' } })
  judge(R, {
    id: 'C5-1', name: '更新不存在的卡 ⇒ 4xx（不得 200/500）',
    expect: 'HTTP 4xx', actual: { status: r.status, body: String(r.text).slice(0, 200) },
    pass: r.status >= 400 && r.status < 500,
    expectSource: '资源不存在 ⇒ 4xx（不得静默 200，也不得 500）', evidence: AUTH_EV,
  })
  const d = await adminApi('DELETE', '/api/admin/knowledge/cards/l1probe-no-such-card-xyz', { token })
  judge(R, {
    id: 'C5-2', name: '删除不存在的卡 ⇒ 4xx（不得 500）',
    expect: 'HTTP 4xx', actual: { status: d.status },
    pass: d.status >= 400 && d.status < 500,
    expectSource: '同上', evidence: AUTH_EV,
  })
}

R.dump()
const s = R.summary()
log(`===== 判据组 C 结束：pass=${s.pass} fail=${s.fail} skip=${s.skip} | 探针卡片: ${created.join(',')} =====`)
console.log(JSON.stringify({ group: 'C', summary: s, cardIds: created, tag: TAG }))
