// p5：权限面 API 负向对照 —— 「UI 看得见的写按钮」对应的写端点，无码岗位必须被后端拒绝（403）
//
// 动机（本轮 P4-BTN 的读数）：客服 / 运营 在 `/knowledge` 页**看得见**「新建知识卡片」按钮，
// 但两岗位都**没有** `knowledge:manage`（DB 现取），而 `POST /api/admin/knowledge/cards` 的
// `@RequirePermission("knowledge:manage")` 在 `KnowledgeCardController` 第 71 行逐字在位。
// ⇒ 必须给一条 **L1 机器判据**回答：「按钮点了会怎样」：403 且库内零变化 = UI 层缺陷（写按钮不随权限显隐）；
//    200 且落库 = 后端也没有护栏（更重）。
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { api, employeeLoginApi, psql, OUT, scrub, PROBE, SUBJECT_SHA, log } from './lib.mjs'
import { readFileSync } from 'node:fs'

const SESSION = JSON.parse(readFileSync(process.env.A06_SESSION || '/tmp/a06-session.json', 'utf8'))
const TENANT_ID = Number(process.env.TENANT_ID || 25)
const stamp = String(Date.now()).slice(-6)
const R = []
const rec = (state, id, name, detail, evidence = []) => R.push({ state, id, name, detail, evidence })

const cardBody = (tag) => ({
  title: `${PROBE}标题${tag}`,
  question: `${PROBE}无码写探针${tag}`,
  answer: `${PROBE}无码写探针答案`,
  keywords: `${PROBE}无码`,
  category: 'faq',
  status: 'draft',
})

async function probe(roleCode, expectStatus) {
  const { token } = await employeeLoginApi(`a06_${roleCode}@${SESSION.tenantCode}`, 'Migao@2026x')
  const before = psql(`select count(*)::int as n from knowledge_cards where tenant_id=${TENANT_ID}`)[0]?.n
  const res = await api('POST', '/api/admin/knowledge/cards', { token, body: cardBody(roleCode) })
  const after = psql(`select count(*)::int as n from knowledge_cards where tenant_id=${TENANT_ID}`)[0]?.n
  const ok = res.status === expectStatus && before === after
  rec(ok ? 'pass' : 'fail', `P5-${roleCode}`, `无码岗位写知识卡片端点：${roleCode}（期望 ${expectStatus} + 库内零变化）`,
    `POST /api/admin/knowledge/cards → HTTP ${res.status}；库内 ${before} → ${after}；响应=${res.text.slice(0, 160)}`,
    ['KnowledgeCardController @RequirePermission("knowledge:manage")', 'SQL: select count(*) from knowledge_cards'])
  return { roleCode, status: res.status, before, after, body: res.text.slice(0, 200) }
}

async function main() {
  const out = { at: new Date().toISOString(), subjectSha: SUBJECT_SHA, tenantId: TENANT_ID, stamp, probes: [] }
  // 无码岗位：客服 / 运营 / 商品管理员（三者都无 knowledge:manage）
  for (const rc of ['customer_service', 'operator', 'product_manager']) {
    try { out.probes.push(await probe(rc, 403)) }
    catch (e) { rec('fail', `P5-${rc}`, `探针异常：${rc}`, String(e).slice(0, 300)) }
  }
  // 正对照：知识编辑（有 knowledge:manage）⇒ 201/200 且落库；随后清理
  try {
    const { token } = await employeeLoginApi(`a06_knowledge_editor@${SESSION.tenantCode}`, 'Migao@2026x')
    const before = psql(`select count(*)::int as n from knowledge_cards where tenant_id=${TENANT_ID}`)[0]?.n
    const res = await api('POST', '/api/admin/knowledge/cards', { token, body: cardBody('positive') })
    const after = psql(`select count(*)::int as n from knowledge_cards where tenant_id=${TENANT_ID}`)[0]?.n
    rec(res.status === 200 && after === before + 1 ? 'pass' : 'fail', 'P5-positive',
      '正对照：有码岗位（知识编辑）同一端点应成功且落库',
      `HTTP ${res.status}；库内 ${before} → ${after}`, ['KnowledgeCardController 同端点'])
    out.positive = { status: res.status, before, after }
  } catch (e) {
    rec('fail', 'P5-positive', '正对照异常', String(e).slice(0, 300))
  }
  const counts = R.reduce((a, x) => ({ ...a, [x.state]: (a[x.state] || 0) + 1 }), {})
  writeFileSync(join(OUT, 'p5-perm-api.json'), JSON.stringify(scrub({ ...out, counts, rows: R }), null, 2))
  log(`== p5 counts: ${JSON.stringify(counts)}`)
  for (const x of R) log(`  [${x.state}] ${x.id} — ${x.detail.slice(0, 260)}`)
}

main().catch((e) => { console.error('p5 失败:', e); process.exit(1) })
