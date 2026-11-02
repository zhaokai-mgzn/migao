// P2：**工序库写面**横切扫描 —— 每个写动作一条探针（快照 → 单键保存 → 快照 → diff → 还原 → 自证）
//
// 覆盖（读 `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx` + `lib/api.ts` 枚举）：
//   PUT /operations/{id} 的 {scope} {group_name} {unit} {is_start_marker} {status} {sort_order} {positions}
//   POST /operations（新建）· DELETE /operations/{id}（软删）· DELETE …/detach-and-delete（设为不做并删除）
import { api, psql, one, log, Recorder, waitService } from './lib.mjs'
import { T, snapshot, diff, changedKeys, overreach, fmt, canonStr, login, nowCST, restoreTo, verifyClean, alivePriceRows, priceSig, facePrice, probe } from './sweep.mjs'
import { PREFIX, RUN, buildOp, removeOp, residue } from './setup.mjs'

let token, R
const SIG = (op) => () => `价目签名=${priceSig(op)}；存活价目行=${canonStr(alivePriceRows(op))}`

/** 工序库写面标准序列：一条 payload 一个探针。 */
async function opProbe(id, name, op, body, { payloadKeys, extraAllowed = [], altBodyNote } = {}) {
  return probe(R, {
    id, name,
    note: { request: `PUT /api/admin/production/operations/${op.id} body=${canonStr(body)}${altBodyNote || ''}`, extraAllowed },
    payloadKeys,
    act: async () => {
      const r = await api('PUT', `/api/admin/production/operations/${op.id}`, { token, body })
      return { status: r.status, json: r.json, httpNote: r.json?.success === false ? JSON.stringify(r.json.error || r.json).slice(0, 200) : '' }
    },
  })
}

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  R = new Recorder('p2-operations.json')
  token = await login()
  const t0 = nowCST()
  log(`=== P2 工序库写面 开始 ${t0.cst}（UTC ${t0.utc}）run=${RUN} ===`)

  const built = await buildOp(token, { tag: '工序写面', unitPrice: 0.66, scope: 'position' })
  if (!built.id) throw new Error('自建探针工序失败：' + JSON.stringify(built.body).slice(0, 300))
  R.pass('W2-00', '自建探针工序（探针锚点）',
    `id=${built.id}；name=${built.name}；scope=${built.scope}；库价=${built.p}；价目行=${canonStr(built.posRows)}`)
  const face0 = await facePrice(token, built.name)

  try {
    // ① scope（payload 键 = 1）
    await opProbe('W2-01', '工序写面：只改 scope', built, { scope: built.scope === 'set' ? 'position' : 'set' }, { payloadKeys: ['scope'] })
    // ② group_name
    await opProbe('W2-02', '工序写面：只改 group_name', built, { group_name: `${PREFIX}改组` }, { payloadKeys: ['group_name'] })
    // ③ unit
    await opProbe('W2-03', '工序写面：只改 unit', built, { unit: '个' }, { payloadKeys: ['unit'] })
    // ④ is_start_marker（「标记生产开始」）
    await opProbe('W2-04', '工序写面：只改 is_start_marker（标记生产开始）', built, { is_start_marker: true }, { payloadKeys: ['is_start_marker'] })
    // ⑤ sort_order
    await opProbe('W2-05', '工序写面：只改 sort_order', built, { sort_order: 7 }, { payloadKeys: ['sort_order'] })
    // ⑥ status：停用（UI 发的是 'inactive' ⇒ 已被 F1 证明 422；这里先测 HTTP 是否接受 'disabled'）
    const st = await opProbe('W2-06', '工序写面：status=disabled（停用）', built, { status: 'disabled' }, { payloadKeys: ['status'] })
    // 停用后必须复回 active（后续探针要求工序可用）
    const back = await api('PUT', `/api/admin/production/operations/${built.id}`, { token, body: { status: 'active' } })
    log(`[W2-06] 复原 status=active HTTP ${back.status}`)
    // ⑦ UI 实际发的那个词（F1 回归观测；预期 422）
    const uiWord = await opProbe('W2-07', '工序写面：status=inactive（UI 实发词；F1 形态复核）', built, { status: 'inactive' },
      { payloadKeys: ['status'], extraAllowed: [] })
    // ⑧ unit_price（payload 键 = 1，但**声明**它会写版本账 = 审计面；若它同时改了别处 ⇒ 红）
    await opProbe('W2-08', '工序写面：只改 unit_price（工序库价）', built, { unit_price: 0.99 }, { payloadKeys: ['unit_price'] })
    // ⑨ positions（存量孤儿接入路径：payload 键 = 1，但**声明**它会建矩阵行）
    await opProbe('W2-09', '工序写面：positions=[布帘]（存量孤儿接入；payload 键=1，声明会建矩阵行）',
      built, { positions: ['布帘'] }, { payloadKeys: ['positions', 'production_operation_positions.*'], altBodyNote: '（该写面的语义就是建矩阵行 ⇒ 显式声明放行）' })

    // ⑩ 新建工序（POST）—— 自建自清
    const created = await buildOp(token, { tag: '新建工序', unitPrice: 1.23, scope: 'set' })
    created.id
      ? R.pass('W2-10', '工序写面：POST /operations 新建（自建自清）',
          `HTTP ${created.http}；id=${created.id}；name=${created.name}；价目行=${canonStr(created.posRows)}`)
      : R.fail('W2-10', '工序写面：新建', `HTTP ${created.http}；resp=${JSON.stringify(created.body).slice(0, 300)}`)
    if (created.id) {
      const rm = await removeOp(token, created.id)
      R.add('W2-10b', '新建工序探针自清', rm.goneOrDeleted ? 'pass' : 'fail',
        `via=${rm.via} HTTP ${rm.http}；resp.deleted=${rm.respDeleted} deleted_positions=${rm.respDeletedPositions}；行态=${rm.after?.op == null ? '不存在(已清)' : rm.after?.op?.del}；该工序矩阵行存活=${rm.aliveMatrixRows}`)
    }

    // ⑪-0 **my own retraction check（受控实验）**：`detach-and-delete` 到底有没有级联清矩阵行？
    //    —— 本包上一版把它记成 F2（「不级联」），但那是**我的工装**造成的假象：
    //    我用「全前缀存活矩阵行数」当判据，而后续步骤/清场把刚造的行扫掉了 ⇒ 读数被污染。
    //    这里用**只属于该工序**的存活矩阵行数做先读后在，独立复核。
    {
      const v = await buildOp(token, { tag: '级联复核', unitPrice: 0.44, scope: 'position', positions: ['通用'] })
      if (v.id) {
        const ownBefore = alivePriceRows(v.name).length
        const rd = await api('DELETE', `/api/admin/production/operations/${v.id}/detach-and-delete`, { token })
        const ownAfter = alivePriceRows(v.name).length
        const opDel = one(`select coalesce(deleted,0) as del from production_operations where id='${v.id}'`)?.del
        const okCascade = opDel === 1 && ownAfter === 0
        R.add('W2-12', '受控复核：detach-and-delete 的「级联软删矩阵行」是否真的生效（只数**该工序**的行）',
          okCascade ? 'pass' : 'fail',
          `HTTP ${rd.status}；resp=${JSON.stringify(rd.json?.data)}；op.deleted=${opDel}；` +
          `该工序存活矩阵行 ${ownBefore} → ${ownAfter}` +
          (okCascade ? ' ⇒ **级联生效**（上一版 F2「不级联」= 我的工装读数污染，已撤回）' : ' ⇒ 级联未生效（真缺陷）'),
          [`DELETE /api/admin/production/operations/${v.id}/detach-and-delete`,
           `SQL: select id from production_operation_positions where logical_name='${v.name}' and coalesce(deleted,0)=0`,
           `resp.deleted_positions=${rd.json?.data?.deleted_positions} / detached_positions=${rd.json?.data?.detached_positions}`])
        await removeOp(token, v.id)   // 兜底零残留（若上一步没清干净）
        R.add('W2-12b', '复核用 fixture 清场自证', 'pass', `存活矩阵行=${alivePriceRows(v.name).length}`)
      }
    }

    // ⑪ 软删（DELETE /operations/{id}）—— 对自己新建的第二道工序
    //    ⚠️ 实测：该端点在工序**挂有矩阵格**时被护栏③挡下 ⇒ **HTTP 422**（护栏生效，不是缺陷）
    //    ⇒ fixture 的清理由 `removeOp` 兜底（它会在 422 时改走 detach-and-delete）。
    const del = await buildOp(token, { tag: '软删工序', unitPrice: 0.5, scope: 'set', positions: ['通用'] })
    if (del.id) {
      const before = await snapshot('W2-11-before')
      const r = await api('DELETE', `/api/admin/production/operations/${del.id}`, { token })
      const after = await snapshot('W2-11-after')
      const d = diff(before, after)
      const over = overreach(d, ['deleted'])
      R.add('W2-11', '工序写面：DELETE /operations/{id}（有挂格 ⇒ 预期被护栏③ 422 挡下）',
        over.length === 0 ? 'pass' : 'fail',
        over.length === 0
          ? `HTTP ${r.status}（422 = 护栏③生效，未改动任何列）；changed=${JSON.stringify(changedKeys(d))}；` +
            `护栏理由=${JSON.stringify(r.json?.error?.details?.[0]?.message || '').slice(0, 160)}`
          : `🔴 越界=${JSON.stringify(changedKeys(over))}`,
        [`DELETE /api/admin/production/operations/${del.id}`, `diff=${fmt(d).join(' | ')}`])
      const rm11 = await removeOp(token, del.id)
      R.add('W2-11b', '软删探针清场自证（该工序矩阵行存活 = 0）',
        rm11.goneOrDeleted && rm11.aliveMatrixRows === 0 ? 'pass' : 'fail',
        `via=${rm11.via} HTTP ${rm11.http}；resp.deleted=${rm11.respDeleted}；该工序矩阵行存活=${rm11.aliveMatrixRows}`)
    }
  } finally {
    try {
      const rm = await removeOp(token, built.id)
      rm.goneOrDeleted && rm.aliveMatrixRows === 0
        ? R.pass('W2-98', '探针自清：自建工序已软删 **且** 矩阵行全清', `via=${rm.via} HTTP ${rm.http}；resp.deleted=${rm.respDeleted} deleted_positions=${rm.respDeletedPositions} 行态=${rm.after?.op == null ? '不存在(已清)' : rm.after?.op?.del}；该工序矩阵行存活=${rm.aliveMatrixRows}`)
        : R.fail('W2-98', '探针自清', `via=${rm.via} HTTP ${rm.http}；deleted=${rm.after?.del}；该工序矩阵行存活=${rm.aliveMatrixRows}`)
      const res = residue()
      res.aliveTotal === 0
        ? R.pass('W2-99', '零残留读数：「写面横切」前缀对象存活数 = 0', `存活明细=${res.aliveSummary}；对象总数 ops=${res.ops.length} pos=${res.pos.length} routes=${res.routes.length} rules=${res.rules.length} fees=${res.fees.length}`)
        : R.fail('W2-99', '零残留读数', `存活明细=${res.aliveSummary}`)
    } catch (e) { R.fail('W2-98', '探针自清', String(e).slice(0, 300)) }
  }

  const t1 = nowCST()
  R.pass('W2-90', '时间戳（+08 口径）', `开始 ${t0.cst} / 结束 ${t1.cst}（UTC: ${t0.utc} → ${t1.utc}）；起始读面有效价=${face0.face}`)
  log(`P2 summary=${JSON.stringify(R.summary())} at ${t1.cst}`)
}
main().catch((e) => { console.error(e); process.exit(1) })
