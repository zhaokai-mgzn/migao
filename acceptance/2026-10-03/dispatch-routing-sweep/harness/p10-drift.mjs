// P10：**配置零漂移**机器判据 —— 把「验收前后商家配置逐字不变」变成会红的断言（不靠人眼）
//
// 基线 = `out/surface.json`（本轮 07:00 开跑前采集）。比对维度：
//   ① 工序库 40 行 × 8 字段   ② 活跃路线（id/名称/默认/主线/适用帘种）
//   ③ 活跃适用条件 26 条（触发/动作/工序/锚点/优先级/部位维）   ④ 价目读面（逻辑名@部位 × 单价）
import { api, loginApi, psql, Recorder, waitService } from './lib.mjs'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { OUT } from './lib.mjs'

const T = Number(process.env.TENANT_ID || 20)
const PHONE = process.env.ADMIN_PHONE || '13870217889'
const num = (v) => (v == null ? null : Number(v))

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  const R = new Recorder('p10-drift.json')
  const base = JSON.parse(readFileSync(join(OUT, 'surface.json'), 'utf8'))
  const { token } = await loginApi(PHONE)

  // ① 工序库
  const nb = (o) => ({
    name: o.name, group_name: o.group_name, scope: o.scope, unit: o.unit,
    p: num(o.p !== undefined ? o.p : o.unit_price), start: o.is_start_marker === true, status: o.status, source: o.source,
  })
  const B = new Map((base.dbOperations || []).filter((o) => o.deleted === 0).map((o) => [o.name, nb(o)]))
  const N = new Map(psql(`select name, group_name, scope, unit, unit_price p, is_start_marker, status, source
      from production_operations where tenant_id=${T} and coalesce(deleted,0)=0`).map((o) => [o.name, nb(o)]))
  const diffs = []
  for (const [k, v] of N) {
    const b = B.get(k)
    if (!b) { diffs.push(`新增工序 ${k}`); continue }
    for (const f of Object.keys(v)) if (JSON.stringify(v[f]) !== JSON.stringify(b[f])) diffs.push(`${k}.${f}: 基线=${JSON.stringify(b[f])} 现状=${JSON.stringify(v[f])}`)
  }
  for (const k of B.keys()) if (!N.has(k)) diffs.push(`工序消失 ${k}`)
  diffs.length === 0
    ? R.pass('DR-01', `工序库 ${N.size} 道 × 8 字段与开工前基线逐字一致`, `基线 ${B.size} 道；比对字段=名称/分组/作用域/单位/单价/开工标记/状态/来源`)
    : R.fail('DR-01', '工序库零漂移', diffs.slice(0, 8).join(' ｜ '))

  // ② 活跃路线
  const normR = (r) => ({ id: r.id, name: r.name, is_default: r.is_default === true, mainline: r.mainline, positions: r.positions })
  const br = (base.raw.routings.routings || []).map(normR).sort((a, b) => a.id.localeCompare(b.id))
  const nr = ((await api('GET', '/api/admin/production/routings', { token })).json?.data?.routings || []).map(normR).sort((a, b) => a.id.localeCompare(b.id))
  JSON.stringify(br) === JSON.stringify(nr)
    ? R.pass('DR-02', `活跃路线 ${nr.length} 条与基线逐字一致（含默认标记、主线顺序、适用帘种）`, JSON.stringify(nr.map((r) => `${r.name}${r.is_default ? '(默认)' : ''}`)))
    : R.fail('DR-02', '路线零漂移', `基线=${JSON.stringify(br)} 现状=${JSON.stringify(nr)}`)

  // ③ 活跃适用条件
  const normRule = (r) => ({ k: r.trigger_kind, v: r.trigger_value, a: r.action, o: r.operation, af: r.after_operation, p: r.priority, pos: r.position })
  const bRules = (base.dbRouteRules || []).filter((r) => r.status === 'active' && r.deleted === 0).map(normRule)
  const nRules = psql(`select trigger_kind,trigger_value,action,operation,after_operation,priority,position
      from production_route_rules where tenant_id=${T} and status='active' and coalesce(deleted,0)=0`).map(normRule)
  const keyRule = (r) => `${r.k}|${r.v}|${r.a}|${r.o}|${r.af}|${r.p}|${r.pos}`
  const setB = new Set(bRules.map(keyRule)), setN = new Set(nRules.map(keyRule))
  const rDiff = [...setN].filter((x) => !setB.has(x)).map((x) => `多出 ${x}`).concat([...setB].filter((x) => !setN.has(x)).map((x) => `缺失 ${x}`))
  rDiff.length === 0
    ? R.pass('DR-03', `活跃适用条件 ${nRules.length} 条与基线逐字一致（触发/动作/工序/锚点/优先级/部位维）`, `基线 ${bRules.length} 条`)
    : R.fail('DR-03', '适用条件零漂移', rDiff.slice(0, 6).join(' ｜ '))

  // ④ 价目读面
  const keyP = (r) => `${r.operation}@${r.position}`
  const bp = new Map((base.raw.operationPositions || []).map((r) => [keyP(r), num(r.unit_price)]))
  const np = new Map(((await api('GET', '/api/admin/production/operation-positions', { token })).json?.data || []).map((r) => [keyP(r), num(r.unit_price)]))
  const pDiff = []
  for (const [k, v] of np) if (!bp.has(k)) pDiff.push(`多出 ${k}`); else if (bp.get(k) !== v) pDiff.push(`${k}: 基线=${bp.get(k)} 现状=${v}`)
  for (const k of bp.keys()) if (!np.has(k)) pDiff.push(`缺失 ${k}`)
  pDiff.length === 0
    ? R.pass('DR-04', `价目读面 ${np.size} 行（逻辑名@部位 × 单价）与基线逐字一致`, `基线 ${bp.size} 行`)
    : R.fail('DR-04', '价目零漂移', pDiff.slice(0, 8).join(' ｜ '))

  // ⑤ 探针残留（软删留痕如实报数，不作为失败）
  const probes = psql(`select
      (select count(*) from production_operations where tenant_id=${T} and name like '验收探针%' and coalesce(deleted,0)=0)::int ops_alive,
      (select count(*) from production_route_templates where tenant_id=${T} and name like '路线探针%' and coalesce(deleted,0)=0)::int routes_alive,
      (select count(*) from production_operation_positions where tenant_id=${T} and position='布帘' and coalesce(deleted,0)=0)::int cloth_rows_alive,
      (select count(*) from production_route_rules where tenant_id=${T} and coalesce(deleted,0)=1)::int rules_softdeleted`)
  const p = probes[0]
  p.ops_alive === 0 && p.routes_alive === 0 && p.cloth_rows_alive === 0
    ? R.pass('DR-05', '探针无存活残留（工序 0 / 路线 0 / 价目「布帘」行 0）', JSON.stringify(p))
    : R.fail('DR-05', '探针残留', JSON.stringify(p))

  const s = R.summary()
  console.log(JSON.stringify({ summary: s, probes: p }))
  if (s.fail > 0) process.exit(2)
}

main().catch((e) => { console.error(e); process.exit(1) })
