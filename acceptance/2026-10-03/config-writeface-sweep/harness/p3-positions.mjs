// P3：**工艺项价目矩阵写面**横切扫描（PUT /operation-positions/{id}）
//
// 契约（`frontend/admin-web/src/lib/api.ts` 逐字）：**部分更新** ⇒ body 只带变了的键；
//   只收 `{unit_price}`（`applicable` 已退场，收到即 422）；`unit_price=null` = 改回**未定价**（≠ 0 元）。
// 探针：自建工序（前缀「写面横切」）⇒ 拿它自己的价目行 ⇒ 每个动作一条探针。
import { api, psql, one, log, Recorder, waitService } from './lib.mjs'
import { T, snapshot, diff, changedKeys, overreach, declaredAudit, fmt, canonStr, login, nowCST, restoreTo, verifyClean, alivePriceRows, priceSig, facePrice, probe } from './sweep.mjs'
import { PREFIX, RUN, buildOp, removeOp, residue } from './setup.mjs'

let token, R

async function cellProbe(id, name, rowId, body, { payloadKeys, opName, expectHttp } = {}) {
  const before = await snapshot(`${id}-pre`)
  const faceB = await facePrice(token, opName)
  const r = await probe(R, {
    id, name,
    note: { request: `PUT /api/admin/production/operation-positions/${rowId} body=${canonStr(body)}（payload 键数=${Object.keys(body).length}）` },
    payloadKeys,
    act: async () => {
      const x = await api('PUT', `/api/admin/production/operation-positions/${rowId}`, { token, body })
      return { status: x.status, json: x.json }
    },
  })
  const faceA = await facePrice(token, opName)
  return { ...r, faceB, faceA, before }
}

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  R = new Recorder('p3-positions.json')
  token = await login()
  const t0 = nowCST()
  log(`=== P3 价目矩阵写面 开始 ${t0.cst}（UTC ${t0.utc}）run=${RUN} ===`)

  const built = await buildOp(token, { tag: '价目写面', unitPrice: 0.66, scope: 'position' })
  if (!built.id) throw new Error('自建探针工序失败')
  const posRow = alivePriceRows(built.name)[0]
  R.pass('W3-00', '自建探针工序 + 定位它的价目行',
    `工序 id=${built.id} name=${built.name}；价目行 id=${posRow?.id} position=${posRow?.position} p=${posRow?.p}`)
  const face0 = await facePrice(token, built.name)

  try {
    // ① 改价（0.77）
    const a = await cellProbe('W3-01', '价目写面：改价 unit_price=0.77', posRow.id, { unit_price: 0.77 }, { payloadKeys: ['unit_price'], opName: built.name })
    log(`W3-01 读面 ${a.faceB.face} → ${a.faceA.face}`)
    // ② 改价 = 0（显式 0 元 ≠ 未定价）
    const b = await cellProbe('W3-02', '价目写面：改价 unit_price=0（显式 0 元）', posRow.id, { unit_price: 0 }, { payloadKeys: ['unit_price'], opName: built.name })
    log(`W3-02 读面 ${b.faceB.face} → ${b.faceA.face}`)
    // ③ 清空 = 改回未定价（null）
    const c = await cellProbe('W3-03', '价目写面：清空 unit_price=null（改回未定价 ≠ 0 元）', posRow.id, { unit_price: null }, { payloadKeys: ['unit_price'], opName: built.name })
    log(`W3-03 读面 ${c.faceB.face} → ${c.faceA.face}`)
    // 🔴 判据：`unit_price=null` 必须落成**未定价**（NULL）而不是 0 元 —— 读面就是被测系统自己的口径
    c.faceA.face === 'NULL(未定价)'
      ? R.pass('W3-03b', '读面语义核对：清空（null）必须落成「未定价」而不是 0 元',
          `改价前读面=${c.faceB.face}（上一步显式 0）⇒ 清空后读面=${c.faceA.face}（HTTP ${c.res?.status}）⇒ **未定价 ≠ 0 元** 成立`)
      : R.fail('W3-03b', '读面语义核对：清空（null）', `清空后读面=${c.faceA.face}（期望「NULL(未定价)」）；HTTP ${c.res?.status}`)
    // ④ 同值重发（负对照）
    await cellProbe('W3-04', '价目写面：负对照（同值重发）', posRow.id, { unit_price: null }, { payloadKeys: ['unit_price'], opName: built.name })
    // ⑤ 退场字段 applicable（声明层拒收：422，且不许静默写别的）
    await cellProbe('W3-05', '价目写面：字段 applicable（已退场 ⇒ 应 422 且不写任何列）', posRow.id,
      { applicable: false }, { payloadKeys: ['applicable'], opName: built.name })
    // ⑥ 未知字段（应 422 / 忽略但不许连锁改价）
    await cellProbe('W3-06', '价目写面：未知字段 position（应拒收且不改别的列）', posRow.id,
      { position: '纱帘' }, { payloadKeys: ['position'], opName: built.name })
    // ⑦ 空 payload（负对照：允许集合应为空）
    await cellProbe('W3-07', '价目写面：空 payload {}（负对照，允许集合应为空）', posRow.id, {}, { payloadKeys: [], opName: built.name })
  } finally {
    try {
      const rm = await removeOp(token, built.id)
      const alive = alivePriceRows(built.name)
      rm.goneOrDeleted && rm.aliveMatrixRows === 0 && alive.length === 0
        ? R.pass('W3-98', '探针自清：自建工序 + 其价目行已软删', `via=${rm.via} HTTP ${rm.http}；该工序矩阵行存活=${rm.aliveMatrixRows}`)
        : R.fail('W3-98', '探针自清', `via=${rm.via} HTTP ${rm.http}；deleted=${rm.after?.del}；该工序矩阵行存活=${rm.aliveMatrixRows}；alive=${JSON.stringify(alive)}`)
      const res = residue()
      res.aliveTotal === 0
        ? R.pass('W3-99', '零残留读数：「写面横切」前缀对象存活数 = 0', `存活明细=${res.aliveSummary}`)
        : R.fail('W3-99', '零残留读数', `存活明细=${res.aliveSummary}`)
    } catch (e) { R.fail('W3-98', '探针自清', String(e).slice(0, 300)) }
  }
  const t1 = nowCST()
  R.pass('W3-90', '时间戳（+08 口径）', `开始 ${t0.cst} / 结束 ${t1.cst}（UTC: ${t0.utc} → ${t1.utc}）；起始读面=${face0.face}`)
  log(`P3 summary=${JSON.stringify(R.summary())} at ${t1.cst}`)
}
const jsonLen = (a) => a.length
main().catch((e) => { console.error(e); process.exit(1) })
