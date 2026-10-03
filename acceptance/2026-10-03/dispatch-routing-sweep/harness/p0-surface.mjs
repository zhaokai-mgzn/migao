// P0：枚举「工序设置」面真值 —— 工序库 / 路线 / 规则 / 选项 / 信号 / 缺口
//
// 目的：把「每一道工序 × 每一项工序设置」的对象清单**从被测系统自身读出来**（而不是照抄 seed 文件），
// 后续矩阵逐条覆盖。产物 = out/surface.json（机器可读，供矩阵消费）。
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { api, loginApi, psql, one, log, OUT, sha, waitService, Recorder } from './lib.mjs'

const T = Number(process.env.TENANT_ID || 20)
const PHONE = process.env.ADMIN_PHONE || '13870217889'

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  const R = new Recorder('p0-surface.json')
  const { token } = await loginApi(PHONE)

  const gets = {
    operationsCatalog: '/api/admin/production/operations-catalog',
    routings: '/api/admin/production/routings',
    routeRules: '/api/admin/production/route-rules',
    routeRuleOptions: '/api/admin/production/route-rule-options',
    routeSignals: '/api/admin/production/route-signals',
    routingGaps: '/api/admin/production/routing-gaps',
    routingAnomalies: '/api/admin/production/orders/routing-anomalies',
    operationPositions: '/api/admin/production/operation-positions',
  }
  const surface = { meta: {}, raw: {} }
  surface.meta = {
    at: new Date().toISOString(), tenantId: T, adminPhone: PHONE,
    apiBase: process.env.API_BASE || 'http://localhost:8080',
    repoHead: sha('HEAD'), originMain: sha('origin/main'),
    runningApiCheckout: 'inspect process cwd manually (main-live)',
  }

  for (const [k, p] of Object.entries(gets)) {
    const r = await api('GET', p, { token })
    surface.raw[k] = r.json?.data ?? null
    const n = Array.isArray(r.json?.data) ? r.json.data.length : (r.json?.data && typeof r.json.data === 'object' ? Object.keys(r.json.data).length : -1)
    r.status === 200 && r.json?.success
      ? R.pass(`P0-${k}`, `读面 ${p}`, `HTTP ${r.status}；条目/键数=${n}`, [`GET ${p}`])
      : R.fail(`P0-${k}`, `读面 ${p}`, `HTTP ${r.status} ${(r.text || '').slice(0, 200)}`, [`GET ${p}`])
  }

  // 工序库：从 DB 取权威行（含 position / scope / unit / unit_price / is_start_marker / status）
  surface.dbOperations = psql(`
    select id, name, group_name, position, scope, unit,
           unit_price::text as unit_price, is_start_marker, is_must_finish, status, sort_order,
           source, coalesce(deleted,0) as deleted
    from production_operations where tenant_id=${T} order by sort_order, name`)
  surface.dbRouteTemplates = psql(`
    select id, name, is_default, positions::text as positions, mainline::text as mainline, status,
           coalesce(deleted,0) as deleted
    from production_route_templates where tenant_id=${T} order by is_default desc, name`)
  surface.dbLegacyRoutings = psql(`
    select id, curtain_type, craft, operations::text as operations, status, source,
           coalesce(deleted,0) as deleted
    from production_routings where tenant_id=${T} order by curtain_type, craft`)
  surface.dbRouteRules = (() => {
    try {
      return psql(`select id, trigger_kind, trigger_value, position, action, operation, after_operation,
                          priority, status, factor::text as factor, customer_unit_price::text as customer_unit_price,
                          coalesce(deleted,0) as deleted
                   from production_route_rules where tenant_id=${T} order by priority, trigger_kind`)
    } catch (e) { return [{ error: String(e).slice(0, 300) }] }
  })()

  // 路线取路的实现面：部位 × 工艺 → 主线工序（读面给的派生结果）
  surface.routeSignalsData = surface.raw.routeSignals

  writeFileSync(join(OUT, 'surface.json'), JSON.stringify(surface, null, 2))
  log(`surface.json 已写：工序 ${surface.dbOperations.length} 道 / 路线 ${surface.dbRouteTemplates.length} 条 / 规则 ${Array.isArray(surface.dbRouteRules) ? surface.dbRouteRules.length : 'ERR'}`)
  log(`summary=${JSON.stringify(R.summary())}`)
}

main().catch((e) => { console.error(e); process.exit(1) })
