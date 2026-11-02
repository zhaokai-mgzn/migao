// P1：判据自证（注入式红证）+ F8 正对照（本线判据必须在 F8 形态上**当场红**）
//
// 判据：changed_keys ⊆ payload_keys ∪ 显式声明的审计/版本/时间戳字段。**多一处即红。**
//   红证三问（migao-acceptance）：① 注入式能红 ② 还原后能绿 ③ 正对照（F8）当场红
// 并发纪律：同租户另有并行包（piecework-wage-sweep，实测在写 `打包`）⇒
//   正对照改用**自建工序**（前缀「写面横切」），并行包不会碰 ⇒ 归因干净。
import { api, psql, psqlWrite, one, log, Recorder, waitService } from './lib.mjs'
import { T, snapshot, diff, changedKeys, overreach, declaredAudit, fmt, canonStr, login, nowCST, restoreTo, verifyClean, alivePriceRows, priceSig, facePrice, clearStray, probe, claimsFor, priceEffect, buildPoint } from './sweep.mjs'
import { PREFIX, RUN, buildOp, removeOp, residue, sweepLeftovers } from './setup.mjs'

let token

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  const R = new Recorder('p1-selftest-f8.json')
  token = await login()
  const t0 = nowCST()
  log(`=== P1 开始 ${t0.cst}（UTC ${t0.utc}）tenant=${T} run=${RUN} ===`)

  // ───────────────── ⓪ 构建点自证（判据必须钉在**当前部署点**上）─────────────────
  const bp = buildPoint()
  R.pass('W0-00', '构建点自证（本包全部读数对应的部署点）',
    `main-live HEAD=${bp.sha}（${bp.subject}）；编译产物 mtime=${bp.classMtime}；Java 进程启动=${bp.procStart}`,
    [`git -C ${bp.worktree} rev-parse --short HEAD`, `git -C ${bp.worktree} log -1 --format='%H %ci %s'`,
     `git -C ${bp.worktree} merge-base --is-ancestor 1d1fe5e55 HEAD  ⇒ hasFix=${bp.hasFix}`,
     `stat -f '%Sm' -t '%F %T' .../ProductionOperationCommandService.class ⇒ ${bp.classMtime}`,
     `ps -eo lstart,command | grep AdminApiApplication ⇒ ${bp.procStart}`])
  bp.hasFix
    ? R.pass('W0-00b', '构建点**含** #6102 修复 ⇒ F8 的「静默改价」形态预期**已修**（判决由 W1-03 给出）',
        `merge-base --is-ancestor 1d1fe5e55 HEAD ⇒ YES（构建点 ${bp.sha}）`)
    : R.fail('W0-00b', '构建点**不含** #6102 修复 ⇒ F8 预期仍以**涉钱**形态复现',
        `merge-base --is-ancestor 1d1fe5e55 HEAD ⇒ NO（构建点 ${bp.sha}）`)

  // ───────────────── ① 注入式红证：判据能看见「外部直连 RDS 的改动」 ─────────────────
  const victim = one(`select id, name, unit_price::text as p from production_operations
      where tenant_id=${T} and coalesce(deleted,0)=0 order by name limit 1`)
  const injBefore = await snapshot('inject-before')
  const injVal = '0.1234'
  psqlWrite(`update production_operations set unit_price=${injVal} where id='${victim.id}'`)
  const injAfter = await snapshot('inject-after')
  const dInj = diff(injBefore, injAfter)
  const hit = dInj.some((x) => x.table === 'production_operations' && x.field === 'unit_price' && x.rowKey === String(victim.id))
  const injOver = overreach(dInj, [])
  hit
    ? R.pass('W0-01', '注入式红证：判据能看见「外部直连 RDS 的改动」（证明 diff 有判别力）',
        `手工 update production_operations.id=${victim.id}（${victim.name}）unit_price ${victim.p} → ${injVal}；diff 命中=${hit}；判据越界=${JSON.stringify(changedKeys(injOver))}`,
        [`SQL: update production_operations set unit_price=${injVal} where id='${victim.id}'`, `字段级 diff: ${fmt(dInj).join(' | ')}`])
    : R.fail('W0-01', '注入式红证', `注入后 diff 未命中 production_operations.unit_price（victim=${victim.id}）；diff=${JSON.stringify(fmt(dInj))}`)
  const injOps = await restoreTo(injBefore, { owns: () => true })
  const injClean = await verifyClean(injBefore, injOps, { owns: () => true })
  injClean.clean
    ? R.pass('W0-02', '注入还原自证：还原后逐字段 == 注入前（主面残留 = 0）',
        `victim=${victim.id}；还原动作=${injOps.length}（no-op=${injClean.noop.length}）；主面残留=${injClean.primary.length}`,
        [`还原 SQL: ${injOps.map((o) => `${o.sets?.join(',')}[affected=${o.affected}]`).join(' ;; ')}`])
    : R.fail('W0-02', '注入还原自证', `仍有主面差异：${fmt(injClean.primary).join(' | ')}；no-op=${JSON.stringify(injClean.noop)}`)

  // ───────────────── ② 自建探针工序（正对照的锚点：并行包不会碰） ─────────────────
  // 🔴 F8 的触发前置（读 `ProductionOperationCommandService.update()` 逐字得到）：
  //   省略 positions ⇒ 兜底 `List.of(COLLAPSE_PRICE_SOURCE_POSITION)`（= 布帘），
  //   而 `attachPositions` **只补矩阵里没有的那一列**；已有 `布帘` 行 ⇒ 幂等跳过 ⇒ **不触发**。
  //   ⇒ 探针工序必须建在**矩阵里没有布帘行**的形态（用 `positions:['通用']`）。
  let built, ctl
  try {
    const leftover = await sweepLeftovers(token)
    R.pass('W1-L0', '清场：清理历史残留的同前缀探针对象（此前被中断的运行）',
      `清理 ${leftover.done.length} 条：${leftover.done.join(' | ') || '（无）'}；前缀存活矩阵行清空读数=${leftover.posLeft}`)
    built = await buildOp(token, { tag: '正对照', unitPrice: 0.55, scope: 'position', positions: ['通用'] })
    const hasCloth = built.posRows.some((r) => r.position === '布帘')
    built.id
      ? (hasCloth
        ? R.fail('W1-00', '自建探针工序（前置：矩阵里**没有**布帘行）', `建出来的行含布帘 ⇒ F8 前置不成立：${canonStr(built.posRows)}`)
        : R.pass('W1-00', '自建探针工序（前缀「写面横切」；前置：矩阵里**没有**布帘行 —— F8 的触发条件）',
            `POST /operations HTTP ${built.http}；id=${built.id}；name=${built.name}；scope=${built.scope}；库价=${built.p}；价目行=${canonStr(built.posRows)}`))
      : R.fail('W1-00', '自建探针工序', `HTTP ${built.http}；resp=${JSON.stringify(built.body).slice(0, 300)}`)
    if (!built.id) throw new Error('未能自建探针工序')

    // ───────────────── ③ 正对照（F8 形态）：只改 scope ⇒ 判据必须当场红；并判「是否伤钱」 ─────────────────
    // 🔴 判据随部署点改写（铁律：正对照要在**当前构建点**上会红，否则是空断言）：
    //    · 若有效价被改写 ⇒ 红 = **P1 涉钱**（#6102 修复前的形态）
    //    · 若只有价目行集合变化、有效价未变 ⇒ 红 = **P3 等价性越界**（修复后残留的形态）
    const face0 = await facePrice(token, built.name)
    const rows0 = alivePriceRows(built.name)
    const altScope = built.scope === 'set' ? 'position' : 'set'
    const r1 = await probe(R, {
      id: 'W1-01',
      name: '🔴 正对照（F8 形态）：自建工序上一次「只改 scope」的保存 ⇒ 判据当场红',
      note: { request: `PUT /api/admin/production/operations/${built.id} body={"scope":"${altScope}"}（payload 键数 = 1）` },
      payloadKeys: ['scope'],
      context: { opId: built.id, opName: built.name, matrixRowId: built.posRows[0]?.id },
      act: async () => {
        const r = await api('PUT', `/api/admin/production/operations/${built.id}`, { token, body: { scope: altScope } })
        return { status: r.status, json: r.json }
      },
    })
    const eff = await priceEffect(token, built.name, face0, rows0)
    const priceRowHit = !r1.skipped && r1.over.some((x) => x.table === 'production_operation_positions')
    if (r1.skipped) {
      R.add('W1-02', '正对照判定（F8 形态是否当场红）', 'skip', '本条重跑后仍涉并发干扰 ⇒ 见 W1-01')
    } else if (priceRowHit) {
      R.fail('W1-02', `🔴 正对照判定：判据**当场红**（有效）；越界性质 = ${eff.faceChanged ? 'P1 涉钱（有效价被改写）' : '#6102 已生效 ⇒ 不再涉钱（仅等价性越界，P3）'}`,
        `payload 键=[scope] ⇒ 越界命中价目表：${JSON.stringify(changedKeys(r1.over))}；` +
        `有效价（读面）${eff.beforeFace} → ${eff.afterFace}${eff.faceChanged ? '（**被改写**）' : '（未变）'}；` +
        `存活价目行 ${canonStr(rows0)} → ${canonStr(eff.afterRows)}`,
        [`非 payload 键的变化 = F8 形态：${fmt(r1.over).join(' | ')}`,
         `判据口径：changed_keys ⊆ payload_keys ∪ 审计列；越界项 = 发现`,
         `价格副作用：faceChanged=${eff.faceChanged} / rowsChanged=${eff.rowsChanged} ⇒ ${eff.severity}`])
    } else {
      R.fail('W1-02', '🔴 正对照未红 ⇒ 判据是空断言（先修判据再继续）',
        `F8 形态未复现：越界=${JSON.stringify(changedKeys(r1.over))}；读面 ${eff.beforeFace} → ${eff.afterFace}`)
    }
    R.pass('W1-03', `正对照的**严重度**判定（当前构建点）`, `有效价 ${eff.beforeFace} → ${eff.afterFace}；` +
      `存活价目行集合变化=${eff.rowsChanged} ⇒ **${eff.severity}**` +
      (eff.faceChanged ? '（= #6102 未部署时的涉钱形态）' : '（= #6102 修复**已生效**：新行继承有效价 ⇒ 不再静默改价）'))

    // ───────────────── ④ 负对照（空 payload）：一次**不带任何键**的等价保存 ⇒ 允许集合应为空 ─────────────────
    // 前置自证：此刻矩阵里**没有**布帘行（= F8 的触发条件）——否则该条会被幂等跳过而**假绿**。
    const pre = alivePriceRows(built.name)
    R.add('W0-03-pre', '负对照前置自证：矩阵里此刻**没有**布帘行（F8 触发条件在）',
      pre.some((r) => r.position === '布帘') ? 'skip' : 'pass',
      `存活价目行=${canonStr(pre)}；布帘行=${pre.some((r) => r.position === '布帘') ? '在（⚠️ 该条会假绿，须先清）' : '不在 ✅'}`)
    const r2 = await probe(R, {
      id: 'W0-03',
      name: '负对照：空 payload（{}，一个键都不带）的等价保存 ⇒ 允许集合应为空（除审计）',
      note: { request: `PUT /api/admin/production/operations/${built.id} body={}（payload 键数 = 0）` },
      payloadKeys: [],
      context: { opId: built.id, opName: built.name, matrixRowId: built.posRows[0]?.id },
      act: async () => {
        const r = await api('PUT', `/api/admin/production/operations/${built.id}`, { token, body: {} })
        return { status: r.status, json: r.json }
      },
    })
    // 负对照的「允许集合为空」判据：若越界 ⇒ 是**发现**（不是「负对照失败」）
    if (!r2.skipped) {
      r2.over.length === 0
        ? R.pass('W0-03b', '负对照判定：空 payload 的允许变化集合 = 空（除审计列）',
            `越界 = 0；changed=${JSON.stringify(changedKeys(r2.d))}`)
        : R.add('W0-03b', '🔴 负对照判定：空 payload（键数 0）竟产生非审计字段变化 ⇒ **发现**（与 F8 同族）', 'fail',
            `payload 键数 = 0、越界 ${r2.over.length} 处：${JSON.stringify(changedKeys(r2.over))}；` +
            `HTTP ${r2.res?.status}；存活价目行=${canonStr(alivePriceRows(built.name))}`)
    }
  } finally {
    // ───────────────── ⑤ 探针自清 + 零残留 ─────────────────
    try {
      if (built?.id) {
        const rm = await removeOp(token, built.id)
        rm.goneOrDeleted && rm.aliveMatrixRows === 0
          ? R.pass('W1-98', '探针自清：自建工序已软删 **且** 该工序矩阵行全部软删（级联生效）',
              `via=${rm.via} HTTP ${rm.http}；deleted ${rm.before.op?.del} → ${rm.after?.del}；` +
              `该工序矩阵行存活 ${rm.before.matrixRows} → ${rm.after.matrixRows}（兜底扫 ${rm.swept}）；最终存活=0`)
          : R.fail('W1-98', '探针自清', `via=${rm.via} HTTP ${rm.http}；deleted=${rm.after?.del}；该工序矩阵行存活=${rm.aliveMatrixRows}`)
      }
      const res = residue()
      res.aliveTotal === 0
        ? R.pass('W1-99', '零残留读数：「写面横切」前缀对象存活数 = 0',
            `存活明细=${res.aliveSummary}`)
        : R.fail('W1-99', '零残留读数', `存活明细=${res.aliveSummary}`)
    } catch (e) { R.fail('W1-98', '探针自清', String(e).slice(0, 300)) }
  }

  const t1 = nowCST()
  R.pass('W0-07', '时间戳（+08 口径）', `开始 ${t0.cst} / 结束 ${t1.cst}（UTC: ${t0.utc} → ${t1.utc}）`)
  log(`P1 summary=${JSON.stringify(R.summary())} at ${t1.cst}`)
}
main().catch((e) => { console.error(e); process.exit(1) })
