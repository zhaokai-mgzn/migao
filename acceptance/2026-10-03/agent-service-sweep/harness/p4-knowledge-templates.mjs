// 线① 判据组 E —— 知识模板（读面 / 应用 / 非法 id）
// 被测：admin-api(:8080) /api/admin/knowledge/templates/**
// 期望来源：KnowledgeTemplateController 契约（list 返回模板清单；{id}/apply 返回应用结果 Map）
import {
  Recorder, judge, adminApi, adminLogin, PROBE_PREFIX, TENANT_A, buildPoint, log, nowCST, LIVE_WORKTREE, psql, one,
} from './lib.mjs'

const R = new Recorder('probe-knowledge-templates.json')
const bp = buildPoint(LIVE_WORKTREE, 8080)
const EV = [`admin-api 构建点: ${bp.shaFull} (${bp.subject}) procStart=${bp.procStart}`,
            `观测窗口: ${nowCST().cst}`]
log(`===== 判据组 E 开始 ${nowCST().cst} =====`)
const { token } = await adminLogin()

let tpl = []
{
  const r = await adminApi('GET', '/api/admin/knowledge/templates', { token })
  tpl = Array.isArray(r.data) ? r.data : (r.data?.records || [])
  judge(R, {
    id: 'E1-1', name: '模板清单读面 ⇒ 200 且结构合法',
    expect: 'HTTP 200 且 data 为数组（可为空）',
    actual: { status: r.status, isArray: Array.isArray(r.data), count: tpl.length, body: String(r.text).slice(0, 200) },
    pass: r.status === 200 && Array.isArray(r.data),
    expectSource: 'KnowledgeTemplateController.list 契约（ApiResponse<List<KnowledgeTemplateInfo>>）', evidence: EV,
  })
  R.add('E1-2', '登记：模板清单读数（非判据）', 'pass',
    tpl.length ? `模板 ${tpl.length} 个：${tpl.map((t) => t.templateId || t.id || t.code).slice(0, 10).join(', ')}` : '模板清单为空 ⇒ 应用面无可选夹具',
    [`原始首项: ${JSON.stringify(tpl[0] || null).slice(0, 400)}`])
}

// 模板是**代码内建**清单（库中无 knowledge_templates 表）—— 登记这一事实
{
  const t = psql(`select table_name from information_schema.tables where table_schema='public' and table_name='knowledge_templates'`)
  R.add('E1-3', '登记：knowledge_templates 表不存在（模板为代码内建）', 'pass',
    t.length === 0 ? '库中无 knowledge_templates 表 ⇒ 模板清单来自代码内建（与"建/改/停用"需另找载体）' : '存在该表',
    ['SQL: select table_name from information_schema.tables where table_name=\'knowledge_templates\''])
}

// ── E2 应用模板 ────────────────────────────────────────────────
if (tpl.length) {
  const tid = tpl[0].templateId || tpl[0].id || tpl[0].code
  const r = await adminApi('POST', `/api/admin/knowledge/templates/${tid}/apply`, { token })
  judge(R, {
    id: 'E2-1', name: `应用模板 ${tid} ⇒ 200 且返回结果对象`,
    expect: 'HTTP 200 且 data 为对象', actual: { status: r.status, data: JSON.stringify(r.data).slice(0, 300) },
    pass: r.status === 200 && r.data != null,
    expectSource: 'KnowledgeTemplateController.apply 契约（ApiResponse<Map<String,Object>>）', evidence: EV,
  })
  // 应用后：本租户是否新增了带模板来源的卡片？（读面一致，只读判定）
  const cards = psql(`select id, title, source_type, source_ref, tenant_id, status from knowledge_cards where tenant_id=${TENANT_A} and (source_ref like '%${tid}%' or source_type like '%template%') order by created_at desc limit 5`)
  R.add('E2-2', '登记：应用模板后的卡片留痕（只读观察，非判据）', 'pass',
    cards.length ? `命中 ${cards.length} 张：${cards.map((c) => `${c.id}:${c.title}`).join(' | ').slice(0, 200)}` : '未见带该模板来源的卡片',
    [`SQL: knowledge_cards where tenant_id=${TENANT_A} and source_ref like %${tid}%`,
     '⚠️ 本项为登记项：模板应用语义（是否落卡/落草稿）未在被测契约中声明，不作 pass/fail 主张'])
} else {
  R.skip('E2-1', '应用模板', '模板清单为空 ⇒ 无夹具；应用面未覆盖')
}

// ── E3 非法模板 id ⇒ 4xx（不得 500）────────────────────────────
{
  const r = await adminApi('POST', '/api/admin/knowledge/templates/l1probe-no-such-template/apply', { token })
  judge(R, {
    id: 'E3-1', name: '应用不存在的模板 ⇒ 4xx（不得 500）',
    expect: 'HTTP 4xx', actual: { status: r.status, body: String(r.text).slice(0, 200) },
    pass: r.status >= 400 && r.status < 500,
    expectSource: '未知模板 id ⇒ 4xx（不得静默 200、不得 500）', evidence: EV,
  })
}

R.dump()
const s = R.summary()
log(`===== 判据组 E 结束：pass=${s.pass} fail=${s.fail} skip=${s.skip} =====`)
console.log(JSON.stringify({ group: 'E', summary: s, templates: tpl.map((t) => t.templateId || t.id || t.code) }))
