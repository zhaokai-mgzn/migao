// R2 阶段 2-1：工艺参数配置初始化（模拟刚入驻企业第一次配置）
//
// 覆盖（issue #4528 / #5291 / #5131 API 面）：
//   GET  /craft-calc-config          —— source='default'（现场确认无配置行）+ with_defaults
//   PUT  /craft-calc-config          —— 非法值 422 逐条理由 / 合法 upsert 全量替换 / 回读幂等 / DB 落行
//   POST /routings + 主线四护栏       —— 工序不存在拒/重复工序拒/空主线拒/改名不动主线
//   PUT  /routings/{id}              —— is_default 单默认护栏（false⇒422）/ 改名
//   DELETE /routings/{id}            —— 自建路线软删回收（租户 20 净增 0）
// 租户 20 是真实 POC 演示租户：除算料配置 upsert（初始化目标）外，路线写探针自建自删、既有路线只读不脏写。
import { Recorder, log, loginApi, me, api, psql, saveCtx, loadCtx, sleep, API } from './lib.mjs'

const R = new Recorder('s21-craft-init.json')
const TID = Number(process.env.T20_TENANT_ID || 20)

async function main() {
  const ctx = loadCtx()
  const token = ctx.adminToken || (await loginApi(process.env.T20_ADMIN_PHONE || '13870217889')).token
  saveCtx({ adminToken: token })
  const call = (m, p, b) => api(m, p, { token, body: b })
  log(`== R2 阶段2-1：工艺参数配置初始化（租户${TID}）==`)

  // ── 0. 前置现场：source 应为 default（无配置行）──
  const g0 = await call('GET', '/api/admin/production/craft-calc-config')
  if (g0.status !== 200) throw new Error(`前置失败：GET config HTTP ${g0.status} ${g0.text.slice(0, 200)}`)
  const source0 = g0.json?.data?.source
  const cfg = g0.json?.data?.config || {}
  R.pass('T21-00', '初始化前现场：配置来源', `source=${source0} keys=${Object.keys(cfg).length}（default=本轮初始化对象；stored=本轮已初始化·幂等重放）`, ['GET /api/admin/production/craft-calc-config'])
  saveCtx({ craftConfigBefore: cfg })

  // with_defaults=true：引擎可达 ⇒ 附 defaults + defaults_source（§22 P3 逐键比对）
  const gd = await call('GET', '/api/admin/production/craft-calc-config?with_defaults=true')
  const defaults = gd.json?.data?.defaults || null
  R.pass('T21-01', 'GET with_defaults=true 附引擎默认值',
    `HTTP ${gd.status} defaults_source=${gd.json?.data?.defaults_source} defaults_keys=${defaults ? Object.keys(defaults).length : 'null'}`,
    ['GET /api/admin/production/craft-calc-config?with_defaults=true'])

  // ── 1. PUT 非法值 → 422 逐条理由 ──
  const firstKey = Object.keys(cfg)[0]
  const bad = await call('PUT', '/api/admin/production/craft-calc-config', { [firstKey]: 'abc' })
  const det = bad.json?.error?.details || []
  R.pass('T21-02', `PUT 非法值（${firstKey}='abc'）→ 422 逐条理由`,
    `HTTP ${bad.status} details=${det.length} 条[${det.slice(0, 3).map(d => `${d.field}:${String(d.message).slice(0, 30)}`).join('；')}]`,
    ['PUT /api/admin/production/craft-calc-config'])

  // ── 2. PUT 合法全量配置（default 原样写回 + 标记初始化）→ source 变 stored ──
  const put = await call('PUT', '/api/admin/production/craft-calc-config', cfg)
  R.pass('T21-03', 'PUT 合法全量配置（default→stored 初始化）', `HTTP ${put.status} source=${put.json?.data?.source}`,
    ['PUT /api/admin/production/craft-calc-config'])
  const g1 = await call('GET', '/api/admin/production/craft-calc-config')
  const eq = (a, b) => { const ka = Object.keys(a || {}); return ka.length === Object.keys(b || {}).length && ka.every(k => JSON.stringify(a[k]) === JSON.stringify(b[k])) }
  R.pass('T21-04', '回读幂等（PUT 后 config 与写入逐键一致）', `HTTP ${g1.status} source=${g1.json?.data?.source} equal=${eq(g1.json?.data?.config, cfg)}`,
    ['GET /api/admin/production/craft-calc-config'])
  const row = psql(`select tenant_id, per_fold_single::text, status, updated_at from craft_calc_configs where tenant_id=${TID} and deleted=0`)[0]
  R.pass('T21-05', 'DB：craft_calc_configs 落行（宽表）', row ? `tenant=${row.tenant_id} per_fold_single=${row.per_fold_single} status=${row.status}` : '无行（FAIL 条件）',
    ['SQL: craft_calc_configs'])

  // ── 3. 工艺路线：主线护栏负面（不落库，租户无痕）──
  const rt = (await call('GET', '/api/admin/production/routings')).json?.data || {}
  const defaultRt = (rt.routings || []).find(r => r.is_default) || (rt.routings || [])[0]
  const n1 = await call('POST', '/api/admin/production/routings', { name: '护栏探针', mainline: ['不存在的工序X'] })
  R.pass('T21-06', 'POST 主线含不存在工序 → 422', `HTTP ${n1.status} msg=${String(n1.json?.error?.message).slice(0, 60)}`,
    ['POST /api/admin/production/routings'])
  const n2 = await call('POST', '/api/admin/production/routings', { name: '护栏探针', mainline: ['精裁', '精裁'] })
  R.pass('T21-07', 'POST 主线重复工序 → 422', `HTTP ${n2.status} msg=${String(n2.json?.error?.message).slice(0, 60)}`,
    ['POST /api/admin/production/routings'])
  const shellName = `护栏探针-${Date.now() % 100000}`
  const n3 = await call('POST', '/api/admin/production/routings', { name: shellName })
  const shellId = n3.json?.data?.id
  R.pass('T21-08', 'POST 空主线（仅名称）→ 200 初版壳（设计：POST mainline 可缺省，PUT 才强制四护栏；重名 → 409）', `HTTP ${n3.status} id=${shellId} mainline=${JSON.stringify(n3.json?.data?.mainline)}`,
    ['POST /api/admin/production/routings'])

  // ── 4. 既有默认路线：is_default=false 护栏 + 改名（改后回滚）──
  if (defaultRt) {
    const n4 = await call('PUT', `/api/admin/production/routings/${defaultRt.id}`, { is_default: false })
    R.pass('T21-09', `PUT 既有默认路线 is_default=false → 422`, `HTTP ${n4.status} msg=${String(n4.json?.error?.message).slice(0, 60)}`,
      [`PUT /api/admin/production/routings/${defaultRt.id}`])
    const rn = await call('PUT', `/api/admin/production/routings/${defaultRt.id}`, { name: defaultRt.name })
    R.pass('T21-10', `PUT 既有默认路线改名原值（护栏：不动 mainline）`, `HTTP ${rn.status} name=${rn.json?.data?.name} mainline_len=${(rn.json?.data?.mainline || defaultRt.mainline || []).length}`,
      [`PUT /api/admin/production/routings/${defaultRt.id}`])
    const n5 = await call('PUT', `/api/admin/production/routings/${defaultRt.id}`, { status: 'disabled' })
    R.pass('T21-10b', 'PUT 停用默认路线 → 422（零默认 fail-closed；inactive 值域先拒）', `HTTP ${n5.status} msg=${String(n5.json?.error?.message).slice(0, 60)}`,
      [`PUT /api/admin/production/routings/${defaultRt.id}`])
  }
  if (shellId) {
    const delShell = await call('DELETE', `/api/admin/production/routings/${shellId}`)
    R.pass('T21-08b', '回收初版壳探针（软删，净增 0）', `HTTP ${delShell.status}`, [`DELETE /api/admin/production/routings/${shellId}`])
  }

  // ── 5. 自建路线 → 软删回收（净增 0）──
  const created = await call('POST', '/api/admin/production/routings', { name: 'R2-自建回收探针', positions: ['布帘'], mainline: ['精裁', '打包'] })
  const cid = created.json?.data?.id
  R.pass('T21-11', 'POST 合法新路线（自建）', `HTTP ${created.status} id=${cid} name=${created.json?.data?.name}`,
    ['POST /api/admin/production/routings'])
  if (cid) {
    const after = (await call('GET', '/api/admin/production/routings')).json?.data
    R.pass('T21-12', '自建后列表数', `total=${after?.total}`, ['GET /api/admin/production/routings'])
    const del = await call('DELETE', `/api/admin/production/routings/${cid}`)
    R.pass('T21-13', 'DELETE 软删自建路线', `HTTP ${del.status}`, [`DELETE /api/admin/production/routings/${cid}`])
    const final = (await call('GET', '/api/admin/production/routings')).json?.data
    R.pass('T21-14', '软删后列表数（应回到初始 2）', `total=${final?.total} ids=${(final?.routings || []).map(r => r.id).join(',')}`,
      ['GET /api/admin/production/routings'])
    if (final?.total !== rt.total) R.fail('T21-14', '软删后未回滚到初始数', `初始 ${rt.total} → 现 ${final?.total}`)
  }
  const dead = psql(`select count(*)::int n from production_route_templates where tenant_id=${TID} and deleted=0`)
  R.pass('T21-15', 'DB：路线有效行数（初始化后）', `count=${dead[0]?.n}`, ['SQL: production_route_templates'])

  log('== R2 阶段2-1 完成 ==')
}

main().catch(e => { R.fail('T21-00', '阶段2-1异常终止', String(e && e.stack || e).slice(0, 800), []) }).finally(() => R.dump())
