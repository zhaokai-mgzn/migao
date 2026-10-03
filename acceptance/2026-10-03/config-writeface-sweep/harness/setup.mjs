// 自建探针夹具（前缀「写面横切」）—— 全部探针对象**自建自清**，绝不改动商家既有配置
//
// 为什么自建：同租户另有**并行包**（piecework-wage-sweep）在写同一批表（实测它在 `打包` 上
// 新建了 `布帘` 价目行 fd9f565…@08:36:19）⇒ 共用既有行会让「谁改的」不可归因。
import { api, one, psql, psqlWrite, log } from './lib.mjs'
import { T, alivePriceRows, clearStray, facePrice, canonStr } from './sweep.mjs'

export const PREFIX = '写面横切'
export const RUN = String(Date.now()).slice(-6)

/** 自建一道工序（scope 自选，带价目行）⇒ 探针锚点。`positions` 决定建哪一列的价目行。 */
export async function buildOp(token, { tag, unitPrice = 0.55, scope = 'position', unit = '米', group = '写面探针组', positions }) {
  const name = `${PREFIX}${tag}${RUN}`
  const body = { name, group_name: group, unit, unit_price: unitPrice, scope, sort_order: 999 }
  if (positions) body.positions = positions
  const r = await api('POST', '/api/admin/production/operations', { token, body })
  const op = r.json?.data || {}
  const row = one(`select id, name, scope, unit_price::text as p, status, group_name, unit from production_operations
      where tenant_id=${T} and name='${name}' and coalesce(deleted,0)=0 limit 1`)
  const pos = alivePriceRows(name)
  log(`[build] ${name} HTTP ${r.status} id=${row?.id} scope=${row?.scope} 库价=${row?.p} 价目行=${canonStr(pos)}`)
  return { name, id: row?.id, scope: row?.scope, p: row?.p, posRows: pos, http: r.status, body: r.json }
}

/** 自建一条工艺路线。 */
export async function buildRoute(token, { tag, mainline = [], positions = ['布帘'] }) {
  const name = `${PREFIX}路线${tag}${RUN}`
  const r = await api('POST', '/api/admin/production/routings', { token, body: { name, mainline, positions } })
  const row = one(`select id, name, is_default, status, positions::text as positions, mainline::text as mainline
      from production_route_templates where tenant_id=${T} and name='${name}' and coalesce(deleted,0)=0 limit 1`)
  log(`[build-route] ${name} HTTP ${r.status} id=${row?.id} positions=${row?.positions} mainline=${row?.mainline}`)
  return { name, id: row?.id, http: r.status, body: r.json }
}

/** 自建一条条件工序规则。 */
export async function buildRule(token, { tag, triggerValue = '写面横切触发', operation, action = 'insert', position = '布帘' }) {
  const body = { trigger_value: triggerValue, operation, action, priority: 999 }
  if (position) body.position = position
  const r = await api('POST', '/api/admin/production/route-rules', { token, body })
  const row = one(`select id, trigger_value, operation, action, position, priority, coalesce(deleted,0) as del
      from production_route_rules where tenant_id=${T} and trigger_value='${triggerValue}' order by created_at desc limit 1`)
  log(`[build-rule] ${triggerValue} HTTP ${r.status} resp=${JSON.stringify(r.json).slice(0, 200)} row=${canonStr(row)}`)
  return { triggerValue, id: row?.id, http: r.status, body: r.json, row }
}

/**
 * 清掉一个自建对象（软删；工序走 detach-and-delete 以级联清矩阵行）。返回清理读数。
 * 🔴 **先读后在**：`aliveMatrixRows` 是「这个工序自己的」存活矩阵行数（**不是**全前缀计数 ——
 * 全前缀计数会被别的探针/并行包的行污染，实测误导过一次归因）。
 * 兜底：普通 `DELETE /operations/{id}` 在有挂格时会 **422（护栏③）** ⇒ 返回 422 时改走 detach-and-delete。
 */
export async function removeOp(token, id) {
  const opName = one(`select name from production_operations where id='${id}'`)?.name
  const ownAlive = () => (opName ? psql(`select id from production_operation_positions where tenant_id=${T}
      and logical_name='${opName}' and coalesce(deleted,0)=0`) : []).length
  const before = { op: one(`select id, coalesce(deleted,0) as del from production_operations where id='${id}'`), matrixRows: ownAlive() }
  let r = await api('DELETE', `/api/admin/production/operations/${id}/detach-and-delete`, { token })
  let via = 'detach-and-delete'
  if (r.status >= 400) { r = await api('DELETE', `/api/admin/production/operations/${id}`, { token }); via = 'plain-delete' }
  const after = { op: one(`select id, coalesce(deleted,0) as del from production_operations where id='${id}'`), matrixRows: ownAlive() }
  // 🔴 顺序即正确性：兜底扫矩阵行必须在**软删工序行之前/独立于它**（`opName` 已捕获）
  //    —— 否则「工序已删 ⇒ 我按名字查不到它的行 ⇒ 以为清干净了」（本包实测踩过，导致跨探针 W*-99 假红）
  let swept = 0
  for (const p of (opName ? psql(`select id from production_operation_positions where tenant_id=${T} and logical_name='${opName}' and coalesce(deleted,0)=0`) : [])) {
    psqlWrite(`update production_operation_positions set deleted=1 where id='${p.id}'`); swept++
  }
  if (after.op?.del === 0) { psqlWrite(`update production_operations set deleted=1 where id='${id}'`) }
  const goneOrDeleted = (after.op == null) || after.op.del === 1   // 行不存在 = 已清；deleted=1 = 软删
  const finalAlive = opName ? psql(`select id from production_operation_positions where tenant_id=${T} and logical_name='${opName}' and coalesce(deleted,0)=0`).length : 0
  log(`[remove-op] ${id}(${opName}) via=${via} HTTP ${r.status} del: ${before.op?.del}→${after.op?.del}；` +
      `该工序矩阵行存活 ${before.matrixRows}→${after.matrixRows}（兜底扫 ${swept}）；最终存活=${finalAlive}；resp=${JSON.stringify(r.json?.data ?? r.json?.error ?? '').slice(0, 160)}`)
  return { before, after, http: r.status, via, swept, goneOrDeleted,
    respDeleted: r.json?.data?.deleted === true, respDeletedPositions: r.json?.data?.deleted_positions,
    aliveMatrixRows: finalAlive, body: r.json }
}

export async function removeRoute(token, id) {
  const before = one(`select id, coalesce(deleted,0) as del, status from production_route_templates where id='${id}'`)
  const r = await api('DELETE', `/api/admin/production/routings/${id}`, { token })
  let after = one(`select id, coalesce(deleted,0) as del, status from production_route_templates where id='${id}'`)
  if (after && after.del === 0) { psqlWrite(`update production_route_templates set deleted=1 where id='${id}'`); after = one(`select id, coalesce(deleted,0) as del, status from production_route_templates where id='${id}'`) }
  log(`[remove-route] ${id} HTTP ${r.status} del: ${before?.del} → ${after?.del ?? '不存在'}`)
  return { before, after, http: r.status, goneOrDeleted: after == null || after.del === 1, body: r.json }
}

export async function removeRule(token, id) {
  const before = one(`select id, coalesce(deleted,0) as del from production_route_rules where id='${id}'`)
  const r = await api('DELETE', `/api/admin/production/route-rules/${id}`, { token })
  let after = one(`select id, coalesce(deleted,0) as del from production_route_rules where id='${id}'`)
  if (after && after.del === 0) { psqlWrite(`update production_route_rules set deleted=1 where id='${id}'`); after = one(`select id, coalesce(deleted,0) as del from production_route_rules where id='${id}'`) }
  log(`[remove-rule] ${id} HTTP ${r.status} del: ${before?.del} → ${after?.del ?? '不存在'}`)
  return { before, after, http: r.status, goneOrDeleted: after == null || after.del === 1, body: r.json }
}


/** 清理**历史残留**的自建对象（此前被中断的运行留下的存活行）——只碰自己的前缀。 */
export async function sweepLeftovers(token) {
  const done = []
  // ① 先扫**矩阵行**（用名字前缀，与工序行是否已软删无关 —— 顺序即正确性）
  const strayPos = psql(`select id, logical_name from production_operation_positions where tenant_id=${T}
      and logical_name like '${PREFIX}%' and coalesce(deleted,0)=0`)
  for (const p of strayPos) { psqlWrite(`update production_operation_positions set deleted=1 where id='${p.id}'`); done.push(`pos:${p.logical_name}`) }
  // ② 再清对象行
  const ops = psql(`select id, name from production_operations where tenant_id=${T} and name like '${PREFIX}%' and coalesce(deleted,0)=0`)
  const routes = psql(`select id, name from production_route_templates where tenant_id=${T} and name like '${PREFIX}%' and coalesce(deleted,0)=0`)
  const rules = psql(`select id, trigger_value from production_route_rules where tenant_id=${T} and trigger_value like '${PREFIX}%' and coalesce(deleted,0)=0`)
  const fees = psql(`select id, composition_key from processing_fee_combinations where tenant_id=${T} and composition_key like '${PREFIX}%' and coalesce(deleted,0)=0`)
  for (const o of ops) { const r = await removeOp(token, o.id); done.push(`op:${o.name}→del=${r.after?.del}`) }
  for (const r of routes) { await api('DELETE', `/api/admin/production/routings/${r.id}`, { token }); done.push(`route:${r.name}`) }
  for (const r of rules) { await api('DELETE', `/api/admin/production/route-rules/${r.id}`, { token }); done.push(`rule:${r.trigger_value}`) }
  for (const f of fees) {
    const r = await api('DELETE', `/api/admin/production/processing-fee-combinations/${f.id}`, { token })
    // 该端点的「删除」= `status=disabled`（`deleted` 仍 0）⇒ 复核一次，未生效则显式写列
    const st = one(`select coalesce(status,'active') as status, coalesce(deleted,0) as del from processing_fee_combinations where id='${f.id}'`)
    if (st && st.del === 0 && String(st.status) !== 'disabled') psqlWrite(`update processing_fee_combinations set status='disabled' where id='${f.id}'`)
    done.push(`fee:${f.composition_key}(HTTP ${r.status}→${st?.status ?? '不存在'})`)
  }
  // ③ 复核（机器读数）
  const left = psql(`select id from production_operation_positions where tenant_id=${T} and logical_name like '${PREFIX}%' and coalesce(deleted,0)=0`).length
  log(`[leftovers] 清理 ${done.length} 条：${done.join(' | ') || '（无）'}；复核：前缀存活矩阵行=${left}`)
  return { done, posLeft: `alive=${left}` }
}

/** 零残留总检：所有前缀对象都不许有存活行。 */
export function residue() {
  const ops = psql(`select id, name, coalesce(deleted,0) as del from production_operations where tenant_id=${T} and name like '${PREFIX}%'`)
  const pos = psql(`select id, logical_name, coalesce(deleted,0) as del from production_operation_positions where tenant_id=${T} and logical_name like '${PREFIX}%'`)
  const routes = psql(`select id, name, coalesce(deleted,0) as del from production_route_templates where tenant_id=${T} and name like '${PREFIX}%'`)
  const rules = psql(`select id, trigger_value, coalesce(deleted,0) as del from production_route_rules where tenant_id=${T} and trigger_value like '${PREFIX}%'`)
  // ⚠️ 加工费组合的「删除」= `status=disabled`（`deleted` 仍 0）；读面/契约都是这套口径
  const fees = psql(`select id, composition_key, coalesce(status,'active') as status, coalesce(deleted,0) as del
      from processing_fee_combinations where tenant_id=${T} and composition_key like '${PREFIX}%'`)
  const alive = (rs) => rs.filter((r) => r.del === 0 && String(r.status ?? 'active') !== 'disabled')
  return {
    ops, pos, routes, rules, fees, aliveSummary:
      (alive(ops).length + alive(pos).length + alive(routes).length + alive(rules).length + alive(fees).length) === 0
        ? '0（ops/pos/routes/rules/fees 全部 deleted=1 或不存在）'
        : JSON.stringify({ ops: alive(ops), pos: alive(pos), routes: alive(routes), rules: alive(rules), fees: alive(fees) }),
    aliveOps: alive(ops), alivePos: alive(pos), aliveRoutes: alive(routes), aliveRules: alive(rules), aliveFees: alive(fees),
    aliveTotal: alive(ops).length + alive(pos).length + alive(routes).length + alive(rules).length + alive(fees).length,
  }
}

export { clearStray, facePrice, alivePriceRows, psqlWrite, one }
