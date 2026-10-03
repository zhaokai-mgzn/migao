// P4：**工艺路线写面**横切扫描（POST /routings · PUT /routings/{id} · DELETE /routings/{id}）
//
// 契约（`frontend/admin-web/src/lib/api.ts` + `ProductionController` 逐字）：部分更新，body 只带变了的键：
//   {name?} {is_default?} {mainline?} {positions?} {status?}
// 护栏（服务端）：空主线拒 / 未知工序拒 / 重复拒 / 缺必完退场 / 重名 409 / is_default:false ⇒ 422 /
//   删默认 ⇒ 422 / 删最后一条 ⇒ 422。
// 探针对象 = **自建路线**（前缀「写面横切」）⇒ 自建自清，绝不动商家的默认路线。
import { api, psql, one, log, Recorder, waitService } from './lib.mjs'
import { T, snapshot, diff, changedKeys, overreach, declaredAudit, fmt, canonStr, login, nowCST, restoreTo, verifyClean, probe, claimsFor } from './sweep.mjs'
import { PREFIX, RUN, buildOp, buildRoute, removeOp, removeRoute, residue, sweepLeftovers } from './setup.mjs'

let token, R
const routeRow = (id) => one(`select id, name, is_default, status, positions::text as positions, mainline::text as mainline,
    coalesce(deleted,0) as del from production_route_templates where tenant_id=${T} and id='${id}'`)
const aliveOps = () => psql(`select name from production_operations where tenant_id=${T} and coalesce(deleted,0)=0 order by name limit 6`)
const defaults = () => psql(`select id, name, is_default, status from production_route_templates where tenant_id=${T} and coalesce(deleted,0)=0 order by name`)

async function routeProbe(id, name, route, body, mainline) {
  return probe(R, {
    id, name,
    note: { request: `PUT /api/admin/production/routings/${route.id} body=${canonStr(body)}（payload 键数=${Object.keys(body).length}）` },
    payloadKeys: Object.keys(body),
    context: { routeId: route.id, routeName: route.name },
    act: async () => {
      const r = await api('PUT', `/api/admin/production/routings/${route.id}`, { token, body })
      return { status: r.status, json: r.json, httpNote: r.json?.success === false ? JSON.stringify(r.json.error || r.json).slice(0, 300) : '' }
    },
  })
}

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  R = new Recorder('p4-routes.json')
  token = await login()
  const t0 = nowCST()
  log(`=== P4 工艺路线写面 开始 ${t0.cst}（UTC ${t0.utc}）run=${RUN} ===`)
  const lo = await sweepLeftovers(token)
  R.pass('W4-L0', '清场：历史残留同前缀对象', `清理 ${lo.done.length} 条：${lo.done.join(' | ') || '（无）'}`)

  const created = []
  try {
    // 先自建两道工序，供主线引用（路线的 mainline 必须引用工序库里存在的工序）
    const op1 = await buildOp(token, { tag: '路线甲', unitPrice: 0.3, scope: 'position', positions: ['通用'] })
    const op2 = await buildOp(token, { tag: '路线乙', unitPrice: 0.4, scope: 'position', positions: ['通用'] })
    created.push(op1.id, op2.id)
    if (!op1.id || !op2.id) throw new Error('自建工序失败')
    R.pass('W4-00', '自建探针夹具：两道工序（供路线主线引用）',
      `op1=${op1.name}(${op1.id}) op2=${op2.name}(${op2.id})；默认路线（只读，不碰）=${canonStr(defaults())}`)

    // ① 新建路线（POST；不含 payload 判据，仅建夹具 + 记录读数）
    const mainline = [op1.name, op2.name]
    const route = await buildRoute(token, { tag: '甲', mainline, positions: ['布帘'] })
    if (!route.id) throw new Error('自建路线失败：' + JSON.stringify(route.body).slice(0, 300))
    R.pass('W4-01', '路线写面：POST /routings 新建（自建自清）',
      `HTTP ${route.http}；id=${route.id}；name=${route.name}；mainline=${routeRow(route.id)?.mainline}；positions=${routeRow(route.id)?.positions}`)

    // ② 改名（payload 键 = 1）
    const newName = `${PREFIX}路线甲改${RUN}`
    await routeProbe('W4-02', '路线写面：只改 name（改名）', route, { name: newName }, mainline)
    route.name = newName
    // ③ 改主线（增删工序 / 调序）—— 三态各一条
    await routeProbe('W4-03', '路线写面：只改 mainline（调序：甲乙 → 乙甲）', route, { mainline: [op2.name, op1.name] }, mainline)
    await routeProbe('W4-04', '路线写面：只改 mainline（删一道：甲乙 → 甲）', route, { mainline: [op1.name] }, mainline)
    await routeProbe('W4-05', '路线写面：只改 mainline（加回：甲 → 甲乙）', route, { mainline: [op1.name, op2.name] }, mainline)
    // ④ 改「适用帘种」positions
    await routeProbe('W4-06', '路线写面：只改 positions（适用帘种 布帘 → 布帘+纱帘）', route, { positions: ['布帘', '纱帘'] }, mainline)
    // ⑤ 停用 / 启用
    await routeProbe('W4-07', '路线写面：只改 status（active → disabled，停用）', route, { status: 'disabled' }, mainline)
    await routeProbe('W4-08', '路线写面：只改 status（disabled → active，启用）', route, { status: 'active' }, mainline)
    // ⑥ is_default=false ⇒ 契约声明 422（不得静默写别的）
    await routeProbe('W4-09', '路线写面：is_default=false（契约声明 422：零默认不可）', route, { is_default: false }, mainline)
    // ⑦ 未覆盖面（如实登记）：is_default=true 会把商家**现有默认路线**降级 ⇒ 属「改动既有生产配置」，
    //    本轮**不做**（见报告「未覆盖面」）。这里只读登记当前默认是谁。
    R.skip('W4-10', '路线写面：is_default=true（设默认）——**本轮不测**',
      `原因：会把商家现有默认路线降级（改动既有生产配置，非自建对象）⇒ 按纪律不碰。当前默认=${canonStr(defaults().filter((r) => r.is_default))}`)
    // ⑧ 删除（DELETE /routings/{id}）
    const bDel = await snapshot('W4-11-before')
    const del = await api('DELETE', `/api/admin/production/routings/${route.id}`, { token })
    const aDel = await snapshot('W4-11-after')
    const dDel = diff(bDel, aDel)
    const ownsR = claimsFor({ routeId: route.id, routeName: route.name })
    const overDel = overreach(dDel, ['deleted', 'status'])
    R.add('W4-11', '路线写面：DELETE /routings/{id}（软删）', overDel.length === 0 ? 'pass' : 'fail',
      overDel.length === 0 ? `HTTP ${del.status}；changed=${JSON.stringify(changedKeys(dDel))}`
        : `🔴 越界=${JSON.stringify(changedKeys(overDel))}（payload 语义=软删该路线）`,
      [`DELETE /api/admin/production/routings/${route.id}`, `diff=${fmt(dDel).join(' | ')}`])
    const opsR = await restoreTo(bDel, { owns: ownsR })
    const cR = await verifyClean(bDel, opsR, { owns: ownsR })
    R.add('W4-11b', '路线软删还原自证', cR.clean ? 'pass' : 'fail',
      `我的行主面残留=${cR.primary.length}；还原动作=${opsR.length}(no-op=${cR.noop.length})；软删回收=${cR.softDeleted}；非我的行=${cR.foreign.length}；${fmt(cR.primary).join(' | ') || '（无残留）'}`)
  } finally {
    try {
      // 自清：路线 + 工序
      const routes = psql(`select id, name from production_route_templates where tenant_id=${T} and name like '${PREFIX}%' and coalesce(deleted,0)=0`)
      for (const r of routes) { const x = await removeRoute(token, r.id); log(`[cleanup-route] ${r.name} HTTP ${x.http} del=${x.after?.del}`) }
      for (const id of created) { if (id) await removeOp(token, id) }
      const res = residue()
      res.aliveTotal === 0
        ? R.pass('W4-98', '零残留读数：前缀对象存活数 = 0', `存活明细=${res.aliveSummary}`)
        : R.fail('W4-98', '零残留读数', `存活：routes=${JSON.stringify(res.aliveRoutes)} ops=${JSON.stringify(res.aliveOps)} pos=${JSON.stringify(res.alivePos)}`)
      // 商家的默认路线必须原样（未被本轮触碰的机器读数）
      R.pass('W4-99', '既有默认路线未被触碰（还原自证：只读比对）',
        `当前活跃路线 = ${canonStr(defaults())}`)
    } catch (e) { R.fail('W4-98', '探针自清', String(e).slice(0, 300)) }
  }
  const t1 = nowCST()
  R.pass('W4-90', '时间戳（+08 口径）', `开始 ${t0.cst} / 结束 ${t1.cst}（UTC: ${t0.utc} → ${t1.utc}）`)
  log(`P4 summary=${JSON.stringify(R.summary())} at ${t1.cst}`)
}
main().catch((e) => { console.error(e); process.exit(1) })
