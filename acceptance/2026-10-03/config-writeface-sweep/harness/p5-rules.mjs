// P5：**适用条件（规则）写面**横切扫描（POST /route-rules · PUT /route-rules/{id}/customer-unit-price · DELETE）
//
// 契约（`frontend/admin-web/src/lib/api.ts` + `ProductionController` 逐字）：
//   POST /route-rules  body = {trigger_value, operation, after_operation?, priority?, customer_unit_price?}
//   PUT  /route-rules/{id}/customer-unit-price  body = {customer_unit_price}（null = 显式改回未定价）
//   DELETE /route-rules/{id}（软删）
// 🔴 本轮**不做**「改触发维与取值 / 改动作 / 改部位限定」——`lib/api.ts` 与 `types/index.ts` 枚举出的
//   规则写面**只有** create / customer-unit-price / delete 三个（无 update 端点）⇒ 如实登记为「不可达」。
import { api, psql, one, log, Recorder, waitService } from './lib.mjs'
import { T, snapshot, diff, changedKeys, overreach, declaredAudit, fmt, canonStr, login, nowCST, restoreTo, verifyClean, probe, claimsFor } from './sweep.mjs'
import { PREFIX, RUN, buildOp, buildRule, removeOp, removeRule, residue, sweepLeftovers } from './setup.mjs'

let token, R
const ruleRow = (id) => one(`select id, trigger_kind, trigger_value, operation, action, position, after_operation,
    priority, coalesce(status,'') as status, factor::text as factor, customer_unit_price::text as cup, coalesce(deleted,0) as del
    from production_route_rules where tenant_id=${T} and id='${id}'`)

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  R = new Recorder('p5-rules.json')
  token = await login()
  const t0 = nowCST()
  log(`=== P5 规则写面 开始 ${t0.cst}（UTC ${t0.utc}）run=${RUN} ===`)
  const lo = await sweepLeftovers(token)
  R.pass('W5-L0', '清场：历史残留同前缀对象', `清理 ${lo.done.length} 条：${lo.done.join(' | ') || '（无）'}`)

  const createdOps = []
  try {
    // 探针夹具：自建一道工序（规则的 operation 必须命中工序库；触发器名自建，不会命中真实订单）
    const op = await buildOp(token, { tag: '规则用', unitPrice: 0.2, scope: 'position', positions: ['通用'] })
    if (!op.id) throw new Error('自建工序失败')
    createdOps.push(op.id)
    R.pass('W5-00', '自建探针夹具：一道工序（规则的 operation 引用它）', `op=${op.name}(${op.id})`)

    // ① 新建规则（trigger_kind='option'：特殊选项；词表外名字可新建 ⇒ 不污染真实触发）
    const trigger = `${PREFIX}选${RUN}`
    const before1 = await snapshot('W5-01-before')
    const built = await buildRule(token, { tag: '规则', triggerValue: trigger, operation: op.name, action: 'insert', position: '布帘' })
    const after1 = await snapshot('W5-01-after')
    const d1 = diff(before1, after1)
    if (built.id) {
      // 新建是「新增一行业务配置」：判据 = 除新行本身外不得有别的变化
      const notMine = d1.filter((x) => !(x.table === 'production_route_rules' && x.rowKey === String(built.id)))
      R.add('W5-01', '规则写面：POST /route-rules 新建（自建自清）',
        notMine.length === 0 ? 'pass' : 'fail',
        notMine.length === 0
          ? `HTTP ${built.http}；新建行=${canonStr(ruleRow(built.id))}；其余变化 = 0（含审计面 ${d1.length - notMine.length - 1 >= 0 ? '' : ''}）`
          : `🔴 新建之外还有 ${notMine.length} 处变化：${fmt(notMine).join(' | ')}`,
        [`POST /api/admin/production/route-rules body={trigger_value:'${trigger}',operation:'${op.name}',action:'insert',priority:999,position:'布帘'}`,
         `新建行 SQL 读数=${canonStr(ruleRow(built.id))}`, `diff=${fmt(d1).join(' | ')}`])
    } else {
      R.skip('W5-01', '规则写面：POST /route-rules 新建（本环境不接受该形态）',
        `HTTP ${built.http}；resp=${JSON.stringify(built.body).slice(0, 300)} ⇒ 该写面在本环境不可达（如实登记）`)
    }

    // ② 改对客单价（payload 键 = 1）
    if (built.id) {
      await probe(R, {
        id: 'W5-02', name: '规则写面：只改 customer_unit_price（元/套）',
        note: { request: `PUT /api/admin/production/route-rules/${built.id}/customer-unit-price body={"customer_unit_price":12.5}` },
        payloadKeys: ['customer_unit_price'],
        context: { ruleId: built.id, ruleTrigger: trigger },
        act: async () => { const r = await api('PUT', `/api/admin/production/route-rules/${built.id}/customer-unit-price`, { token, body: { customer_unit_price: 12.5 } }); return { status: r.status, json: r.json } },
      })
      await probe(R, {
        id: 'W5-03', name: '规则写面：只改 customer_unit_price=null（改回未定价）',
        note: { request: `PUT /api/admin/production/route-rules/${built.id}/customer-unit-price body={"customer_unit_price":null}` },
        payloadKeys: ['customer_unit_price'],
        context: { ruleId: built.id, ruleTrigger: trigger },
        act: async () => { const r = await api('PUT', `/api/admin/production/route-rules/${built.id}/customer-unit-price`, { token, body: { customer_unit_price: null } }); return { status: r.status, json: r.json } },
      })
      // ③ 删除（软删）
      await probe(R, {
        id: 'W5-04', name: '规则写面：DELETE /route-rules/{id}（软删）',
        note: { request: `DELETE /api/admin/production/route-rules/${built.id}` },
        payloadKeys: ['deleted'],
        context: { ruleId: built.id, ruleTrigger: trigger },
        act: async () => { const r = await api('DELETE', `/api/admin/production/route-rules/${built.id}`, { token }); return { status: r.status, json: r.json } },
      })
    }

    // ④ 未覆盖面登记：规则的「更新触发维/动作/部位」在本仓**无写面**（只有 create/price/delete）
    R.skip('W5-05', '规则写面：改触发维与取值 / 改动作 / 改部位限定 —— 仓内**无该写面**',
      `依据：backend/admin-api/src/main/java/com/migao/admin/controller/ProductionController.java 只有 @PostMapping("/route-rules")、` +
      `@PutMapping("/route-rules/{id}/customer-unit-price")、@DeleteMapping("/route-rules/{id}") 三个；` +
      `frontend/admin-web/src/lib/api.ts 同。⇒ 该动作**不可达**（如实登记为未覆盖面，不是「已覆盖」）`)
  } finally {
    try {
      const rules = psql(`select id, trigger_value from production_route_rules where tenant_id=${T} and trigger_value like '${PREFIX}%' and coalesce(deleted,0)=0`)
      for (const r of rules) { const x = await removeRule(token, r.id); log(`[cleanup-rule] ${r.trigger_value} HTTP ${x.http} del=${x.after?.del}`) }
      for (const id of createdOps) if (id) await removeOp(token, id)
      const res = residue()
      res.aliveTotal === 0
        ? R.pass('W5-98', '零残留读数：前缀对象存活数 = 0', `存活明细=${res.aliveSummary}`)
        : R.fail('W5-98', '零残留读数', `存活：rules=${JSON.stringify(res.aliveRules)} ops=${JSON.stringify(res.aliveOps)}`)
    } catch (e) { R.fail('W5-98', '探针自清', String(e).slice(0, 300)) }
  }
  const t1 = nowCST()
  R.pass('W5-90', '时间戳（+08 口径）', `开始 ${t0.cst} / 结束 ${t1.cst}（UTC: ${t0.utc} → ${t1.utc}）`)
  log(`P5 summary=${JSON.stringify(R.summary())} at ${t1.cst}`)
}
main().catch((e) => { console.error(e); process.exit(1) })
