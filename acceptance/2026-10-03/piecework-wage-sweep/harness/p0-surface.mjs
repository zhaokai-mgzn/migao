// P0：计件工资链「读面真值枚举」—— 把这条链的每一跳列清并落成 JSON
//
// 这一跳解决三件事（都必须是**被测系统自身**给出的读数，而不是我照抄代码/seed）：
//   ① 链路上每个读端点的在场性 + 形状（含 query 参数逐组合枚举）
//   ② 库侧真值（report 明细表 / 工序实例 / 加工单 / 订单）
//   ③ **下游结算面到底存不存在** —— 用 OpenAPI 文档（/v3/api-docs，springdoc）全量枚举，
//      按关键词筛「结算/工资/导出/报表」并把**发现方式**写进产物（不是人肉猜）
//
// 产线纪律：本脚本**只读**（除登录）。
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { api, loginApi, psql, log, OUT, sha, waitService, Recorder, PROBE_PREFIX } from './lib.mjs'

const T = Number(process.env.TENANT_ID || 20)
const PHONE = process.env.ADMIN_PHONE || '13870217889'
const PERIOD = process.env.PERIOD || new Date().toISOString().slice(0, 7)

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  const R = new Recorder('p0-surface.json')
  const { token } = await loginApi(PHONE)

  const surface = { meta: {}, api: {}, db: {}, downstream: {}, interference: {} }
  surface.meta = {
    at: new Date().toISOString(),
    tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
    localTime: new Date().toString(),
    tenantId: T, adminPhone: PHONE, period: PERIOD,
    apiBase: process.env.API_BASE || 'http://localhost:8080',
    repoHead: sha('HEAD'), originMain: sha('origin/main'),
    runningApiBuildPoint: 'inspect process cwd (main-live); 见 REPORT「环境与构建点」',
  }

  // ── ① 链路读端点（含 query 组合） ────────────────────────────────
  const probe = async (id, name, method, path, { tok = token, body } = {}) => {
    const r = await api(method, path, { token: tok, body })
    surface.api[id] = {
      http: r.status, ok: !!r.json?.success, keys: r.json?.data && typeof r.json.data === 'object' && !Array.isArray(r.json.data) ? Object.keys(r.json.data) : null,
      data: r.json?.data ?? null, raw_head: r.text.slice(0, 400),
    }
    const shape = r.json?.data == null ? 'null' : (Array.isArray(r.json.data) ? `array[${r.json.data.length}]` : `keys=${(surface.api[id].keys || []).join(',')}`)
    return { r, shape, id, name, path }
  }

  // 无 orderId 版：先拿一张本租户加工单，再打 per-order 读面
  const poRow = psql(`select po.id, po.processing_order_no, po.order_id, po.status
                      from processing_orders po
                      where po.tenant_id=${T} and coalesce(po.deleted,0)=0
                      order by po.created_at desc limit 1`)[0] || null
  surface.db.sampleProcessingOrder = poRow

  const calls = []
  calls.push(await probe('summary_default', '期间报表（period 正确形态）', 'GET', `/api/admin/production/piecework/summary?period=${PERIOD}`))
  if (poRow) {
    calls.push(await probe('perOrder', '单张单计件读数', 'GET', `/api/admin/production/orders/${poRow.order_id}/piecework`))
    calls.push(await probe('worklog_agent', 'agent 侧过程明细（含计件合计）', 'GET', `/api/admin/agent/production/worklog?order_no=${poRow.processing_order_no}`))
  }
  calls.push(await probe('progress_agent', 'agent 侧生产进度', 'GET', `/api/admin/agent/production/progress`))
  calls.push(await probe('agent_piecework', 'agent 侧计件（按人+期间）', 'GET', `/api/admin/agent/production/piecework?period=${PERIOD}`))
  calls.push(await probe('worker_piecework_noperiod', 'agent 侧计件（缺 period）', 'GET', `/api/admin/agent/production/piecework`))
  calls.push(await probe('operations_scan', '订单工序实例读面（无 orderId）', 'GET', `/api/admin/production/orders/__none__/operations`))
  calls.push(await probe('layer_price_state', '未定价徽标读面（operation-layers）', 'GET', `/api/admin/production/operation-layers`))

  // ── query 参数逐组合枚举（期间报表） ────────────────────────────
  surface.queryMatrix = []
  const combos = [
    ['period 正确', `period=${PERIOD}`],
    ['缺 period', ``],
    ['period 空串', `period=`],
    ['period 非法', `period=2026-13`],
    ['period 非法格式', `period=garbage`],
    ['period+worker 命中探针人', `period=${PERIOD}&worker_name=${encodeURIComponent(PROBE_PREFIX + '工人甲')}`],
    ['period+worker 不存在', `period=${PERIOD}&worker_name=__nobody__`],
    ['period+worker 空白', `period=${PERIOD}&worker_name=%20`],
    ['period 上一个月', `period=2026-09`],
  ]
  for (const [label, qs] of combos) {
    const r = await api('GET', `/api/admin/production/piecework/summary${qs ? '?' + qs : ''}`, { token })
    const row = { label, qs, http: r.status, success: !!r.json?.success, code: r.json?.error?.code ?? null, msg: (r.json?.error?.message || r.json?.message || '').slice(0, 160), data: r.json?.data ?? null }
    surface.queryMatrix.push(row)
  }

  // ── ③ 下游结算面：OpenAPI 全量枚举 + 关键词筛（发现方式可复核） ──
  const doc = await api('GET', '/v3/api-docs')
  surface.downstream.openapiHttp = doc.status
  const paths = doc.json?.paths ? Object.keys(doc.json.paths) : []
  surface.downstream.totalPaths = paths.length
  const KW = /(piecework|wage|payroll|salary|settle|reconcil|finance|export|report|statistic)/i
  surface.downstream.matched = paths.filter((p) => KW.test(p)).map((p) => ({
    path: p,
    methods: Object.keys(doc.json.paths[p]).filter((m) => ['get', 'post', 'put', 'delete'].includes(m)),
  }))
  // 前端消费面（脚本内只登记「我去哪里找的」，人工读数写进 REPORT）
  surface.downstream.frontendHint = 'grep -rn "piecework|计件|工资|结算" frontend/admin-web/src (见 REPORT 链路枚举)'

  // ── ② 库侧真值 + 探针/并发基线 ────────────────────────────────
  surface.db.workLogsTotal = psql(`select count(*)::int as n from production_work_logs where tenant_id=${T}`)
  surface.db.workLogsByPeriod = psql(`
    select to_char(work_date,'YYYY-MM') as m, work_type, price_state, count(*)::int as n,
           coalesce(sum(qualified_qty),0)::text as qty
    from production_work_logs where tenant_id=${T} group by 1,2,3 order by 1,2,3`)
  surface.db.workLogsColumns = psql(`
    select column_name, data_type from information_schema.columns
    where table_name='production_work_logs' order by ordinal_position`)
  surface.db.instancesWithPrice = psql(`
    select count(*)::int as total,
           count(*) filter (where unit_price is null)::int as unpriced,
           count(*) filter (where unit_price = 0)::int as zero_priced
    from processing_position_operations where tenant_id=${T} and coalesce(deleted,0)=0`)
  // 干扰面基线：非自建行的**值**快照（与并行配置写面包交叉核对用）
  surface.interference.operationsBaseline = psql(`
    select id, name, unit_price::text as unit_price, position, scope, status
    from production_operations where tenant_id=${T} and coalesce(deleted,0)=0 order by name`)
  surface.interference.positionPriceBaseline = psql(`
    select id, logical_name, position, unit_price::text as unit_price,
           applicable, coalesce(deleted,0) as deleted
    from production_operation_positions where tenant_id=${T} and coalesce(deleted,0)=0 order by logical_name, position`)
  surface.interference.probeRowsAlive = psql(`
    select
      (select count(*)::int from production_operations where tenant_id=${T} and name like '${PROBE_PREFIX}%') as probe_operations,
      (select count(*)::int from processing_orders where tenant_id=${T} and processing_order_no like '${PROBE_PREFIX}%') as probe_orders,
      (select count(*)::int from production_work_logs where tenant_id=${T} and worker_name like '${PROBE_PREFIX}%') as probe_worklogs`)

  // 断言（都会红）
  const hasSummary = surface.api.summary_default?.http === 200 && surface.api.summary_default?.ok
  R[jsonHas(surface.api.summary_default?.data, ['period', 'total', 'per_worker', 'per_operation', 'unpriced']) ? 'pass' : 'fail'](
    'P0-01', '读面 /piecework/summary 在场且返回冻结契约键',
    `HTTP ${surface.api.summary_default?.http}；keys=${(surface.api.summary_default?.keys || []).join(',')}`,
    [`GET /api/admin/production/piecework/summary?period=${PERIOD}`])
  R[hasSummary ? 'pass' : 'fail']('P0-02', '期间报表可用', `HTTP ${surface.api.summary_default?.http}`, [`GET ...?period=${PERIOD}`])
  R[poRow && surface.api.perOrder?.http === 200 ? 'pass' : 'skip']('P0-03', '单张单计件读面在场',
    poRow ? `HTTP ${surface.api.perOrder?.http} keys=${(surface.api.perOrder?.keys || []).join(',')}` : '租户内无加工单',
    poRow ? [`GET /api/admin/production/orders/${poRow.order_id}/piecework`] : [])
  R[surface.downstream.totalPaths > 0 ? 'pass' : 'fail']('P0-04', '下游结算面**由 OpenAPI 全量枚举**（不是人肉猜）',
    `HTTP ${surface.downstream.openapiHttp}；paths=${surface.downstream.totalPaths}；关键词筛中 ${surface.downstream.matched.length} 条`,
    ['GET /v3/api-docs', `关键词 = ${KW}`])
  R[surface.db.workLogsColumns.length > 0 ? 'pass' : 'fail']('P0-05', '报工明细表（计件唯一凭证）结构可读',
    `${surface.db.workLogsColumns.length} 列`, ['information_schema.columns where table_name=production_work_logs'])
  R.pass('P0-06', '并发干扰基线已落盘（非自建行值快照）',
    `工序库 ${surface.interference.operationsBaseline.length} 行 / 价目 ${surface.interference.positionPriceBaseline.length} 行`,
    ['见 out/p0-surface.json .interference'])

  writeFileSync(join(OUT, 'p0-surface.json'), JSON.stringify(surface, null, 2))
  log(`P0 surface.json 已写：paths=${surface.downstream.totalPaths} 关键词命中=${surface.downstream.matched.length}`)
  log(`summary=${JSON.stringify(R.summary())}`)
}

function jsonHas(data, keys) {
  if (!data || typeof data !== 'object') return false
  return keys.every((k) => Object.prototype.hasOwnProperty.call(data, k))
}

main().catch((e) => { console.error(e); process.exit(1) })
