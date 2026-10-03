// P3：F8 正对照（含告警）· 双付/超报的精修重跑 · 并发干扰核对
//
// 本脚本独立于 P1P2（P1P2 的探针对象仍在，不重复建）：
//   ① 修掉 P1P2 里两条**我自己写错的**判据（M8 幂等键、M9 超报）—— 用**有剩余量**的实例重跑
//   ② F8 正对照：完整前后读数（工序库行价 / 价目矩阵行 / 探针实例价 / 新报工快照 / 工资读面）
//   ③ 并发干扰核对：把 P0 的基线与我此刻的读数逐行比，非自建行变了 ⇒ 记「疑似并发干扰」
import { writeFileSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { api, loginApi, psql, one, log, OUT, waitService, Recorder, cents, fmt, moneyEq, guardedWrite, PROBE_PREFIX } from './lib.mjs'

const T = Number(process.env.TENANT_ID || 20)
const PHONE = process.env.ADMIN_PHONE || '13870217889'
const PERIOD = process.env.PERIOD || new Date().toISOString().slice(0, 7)
const CTX_FILE = join(OUT, 'probe-ctx.json')
const RUN = String(Date.now()).slice(-6)

function decMul(a, b) {
  const [ai, af = ''] = String(a).split('.'); const [bi, bf = ''] = String(b).split('.')
  const av = BigInt(ai + af), bv = BigInt(bi + bf); const scale = af.length + bf.length
  const prod = (av * bv).toString().padStart(scale + 1, '0')
  const int = prod.slice(0, prod.length - scale) || '0'
  const frac = scale ? prod.slice(prod.length - scale) : ''
  return frac ? `${int}.${frac}` : int
}
function toCentsHalfUp(s0) {
  const neg = String(s0).startsWith('-'); const s = neg ? String(s0).slice(1) : String(s0)
  const [i, f = ''] = s.split('.'); const t = (f + '000').slice(0, 3)
  let c = BigInt(i) * 100n + BigInt(t.slice(0, 2)); if (Number(t[2]) >= 5) c += 1n
  return neg ? -c : c
}
function expectedCents(rows, { worker = null } = {}) {
  let total = 0n; const perOp = new Map(), unpricedQty = new Map()
  for (const r of rows) {
    if (r.work_type !== 'normal') continue
    if (worker && r.worker_name !== worker) continue
    if (r.price_state === 'unpriced') { unpricedQty.set(r.operation_name, (unpricedQty.get(r.operation_name) || 0n) + toCentsHalfUp(r.qualified_qty)); continue }
    if (r.unit_price === null) throw new Error(`缺快照: ${r.id}`)
    const amt = toCentsHalfUp(decMul(decMul(r.qualified_qty, r.unit_price), r.factor ?? '1'))
    total += amt; perOp.set(r.operation_name, (perOp.get(r.operation_name) || 0n) + amt)
  }
  return { total, perOp, unpricedQty }
}
const logRowsOf = (poIds) => psql(`
  select l.id, l.operation_id, l.operation_name, l.worker_name, l.qualified_qty::text as qualified_qty,
         l.unit_price::text as unit_price, l.factor::text as factor, l.price_state, l.work_type,
         l.work_date::text as work_date, l.created_at::text as created_at, l.processing_order_id
  from production_work_logs l where l.tenant_id=${T} and coalesce(l.deleted,0)=0
    and l.processing_order_id in (${poIds.map((x) => `'${x}'`).join(',')}) order by l.created_at, l.id`)

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  const R = new Recorder('p3-f8-redproof.json')
  const { token } = await loginApi(PHONE)
  const ctx = JSON.parse(readFileSync(CTX_FILE, 'utf8'))
  const A = ctx.probes.find((p) => p.tag === 'A')
  const WORKER_A = A.worker
  const out = { at: new Date().toISOString(), run: RUN }

  // ══════ ① 修掉我自己写错的 M8 / M9 ══════
  let rowsA = psql(`select id, operation_name, qty::text as qty, done_qty::text as done_qty, unit_price::text as unit_price
     from processing_position_operations where processing_order_id='${A.poId}' and coalesce(deleted,0)=0 order by seq`)
  const roomy = rowsA.find((r) => Number(r.qty) - Number(r.done_qty) >= 5)
  out.roomy = roomy
  if (roomy) {
    const key = `${RUN}-IDEM`
    const before = logRowsOf([A.poId]).length
    const f1 = await api('POST', `/api/admin/production/orders/${A.orderId}/operations/${roomy.id}/report`,
      { token, body: { worker_name: WORKER_A, qty: 2, qualified_qty: 2, work_type: 'normal' }, headers: { 'X-Client-Request-Id': key } })
    const mid = logRowsOf([A.poId]).length
    const f2 = await api('POST', `/api/admin/production/orders/${A.orderId}/operations/${roomy.id}/report`,
      { token, body: { worker_name: WORKER_A, qty: 2, qualified_qty: 2, work_type: 'normal' }, headers: { 'X-Client-Request-Id': key } })
    const after = logRowsOf([A.poId]).length
    out.idempotency = { op: roomy.operation_name, before, mid, after, firstHttp: f1.status, first: f1.json?.data, secondHttp: f2.status, second: f2.json?.data, secondRaw: f1.status === 200 ? '' : f1.text.slice(0, 200) }
    const idemOk = f1.status === 200 && mid === before + 1 && after === mid && f2.json?.data?.replayed === true
    R[idemOk ? 'pass' : 'fail']('M8-01R',
      '【双付·重跑】同 X-Client-Request-Id：首次落一条、**第二次不再落**且 replayed=true',
      `行数 ${before}（前）→${mid}（首次后）→${after}（重放后）；replayed=${f2.json?.data?.replayed}；HTTP ${f1.status}/${f2.status}`,
      [`POST …/report 带同键 ${key} ×2`, `SQL: production_work_logs where processing_order_id='${A.poId}'`])
    // 幂等键与「执行失败」的关系：第一次失败（超报）后同键应可重试（不得永久占死）
    const failKey = `${RUN}-FAILRETRY`
    const g1 = await api('POST', `/api/admin/production/orders/${A.orderId}/operations/${roomy.id}/report`,
      { token, body: { worker_name: WORKER_A, qty: 9999, qualified_qty: 9999, work_type: 'normal' }, headers: { 'X-Client-Request-Id': failKey } })
    out.failThenRetry = { firstHttp: g1.status, firstMsg: (g1.json?.error?.message || '').slice(0, 120) }
    R.skip('M8-02', '【双付·重跑】失败键可重试', '登记为观察项（见 out/p3-f8-redproof.json .failThenRetry）')
    // 超报 422（用剩余量精确算）
    const remain = Number(roomy.qty) - Number(one(`select done_qty::text as d from processing_position_operations where id='${roomy.id}'`).d)
    const over = Math.max(remain + 1, 1)
    const h = await api('POST', `/api/admin/production/orders/${A.orderId}/operations/${roomy.id}/report`,
      { token, body: { worker_name: WORKER_A, qty: over, qualified_qty: over, work_type: 'normal' }, headers: { 'X-Client-Request-Id': `${RUN}-OVER` } })
    const cnt = logRowsOf([A.poId]).length
    out.overReport = { op: roomy.operation_name, remaining: remain, sent: over, http: h.status, msg: (h.json?.error?.message || '').slice(0, 160), rowsAfter: cnt }
    R[h.status === 422 && /超上限/.test(h.json?.error?.message || '') ? 'pass' : 'fail']('M9-01R',
      '【边界·重跑】超应做数量 ⇒ 422 拒绝，且不落明细',
      `剩余 ${remain}，报 ${over} ⇒ HTTP ${h.status}「${(h.json?.error?.message || '').slice(0, 60)}」`,
      [`POST …/report qty=${over}`, `SQL: 报工行数 ${cnt}`])
  } else {
    R.skip('M8-01R', '【双付·重跑】', '没有剩余量 ≥5 的实例（登记未覆盖）')
    R.skip('M9-01R', '【边界·重跑】', '同上')
  }

  // ══════ ② F8 正对照（完整前后读数） ══════
  const catResp = await api('GET', '/api/admin/production/operations-catalog', { token })
  const allOps = (catResp.json?.data?.groups ?? []).flatMap((g) => g.operations ?? [])
  // 目标 = 探针单 A 上**未定价**的那道（逻辑名 = 变体名去部位后缀）
  const unpricedInst = psql(`select id, operation_name, unit_price::text as unit_price, qty::text as qty, done_qty::text as done_qty
    from processing_position_operations where processing_order_id='${A.poId}' and unit_price is null and coalesce(deleted,0)=0`)
  const target = unpricedInst[0]
  const logical = target ? String(target.operation_name).replace(/-(布|纱|帘头)$/, '') : null
  const catRow = allOps.find((o) => o.name === logical && o.library_name === target?.operation_name)
    ?? allOps.find((o) => o.name === logical)
  out.f8 = { probe: A.tag, poNo: A.poNo, unpricedInstance: target, logical, catalogRow: catRow ?? null }
  if (target && catRow?.id) {
    const posRows = () => psql(`select id, logical_name, position, unit_price::text as unit_price,
        coalesce(deleted,0) as deleted, created_at::text as created_at
      from production_operation_positions where tenant_id=${T} and logical_name='${logical}' order by position, created_at, id`)
    const instRow = () => psql(`select id, operation_name, unit_price::text as unit_price from processing_position_operations where id='${target.id}'`)[0]
    const pwRead = async () => (await api('GET', `/api/admin/production/orders/${A.orderId}/piecework`, { token })).json?.data

    const readFace = async () => {
      const c = await api('GET', '/api/admin/production/operations-catalog', { token })
      const ops = (c.json?.data?.groups ?? []).flatMap((g) => g.operations ?? [])
      const l = await api('GET', '/api/admin/production/operation-layers', { token })
      return {
        catalogRows: ops.filter((o) => o.name === logical).map((o) => [o.library_name, o.position, o.unit_price]),
        layerRows: (l.json?.data?.operations ?? []).filter((o) => o.operation === logical).map((o) => [o.position, o.unit_price, o.applicable]),
      }
    }
    const beforePos = posRows(); const beforeInst = instRow(); const beforePw = await pwRead()
    const beforeRead = await readFace()
    const beforeLogs = logRowsOf([A.poId])
    out.f8.before = { posRows: beforePos, instance: beforeInst, piecework: beforePw, logsCount: beforeLogs.length, readFace: beforeRead }
    const put = await api('PUT', `/api/admin/production/operations/${catRow.id}`, { token, body: { scope: catRow.scope ?? 'position' } })
    const afterPos = posRows(); const afterInst = instRow(); const afterRead = await readFace()
    out.f8.put = { http: put.status, body: put.text.slice(0, 500), catalogId: catRow.id, scopeSent: catRow.scope ?? 'position' }
    // 该动作之后**新报一笔**（F8 的工资侧后果：快照价从「未定价」变成什么）
    const rep = await api('POST', `/api/admin/production/orders/${A.orderId}/operations/${target.id}/report`,
      { token, body: { worker_name: WORKER_A, qty: 2, qualified_qty: 2, work_type: 'normal' }, headers: { 'X-Client-Request-Id': `${RUN}-F8B` } })
    const afterLogs = logRowsOf([A.poId])
    const afterPw = await pwRead()
    const expAfter = expectedCents(afterLogs)
    out.f8.after = {
      posRows: afterPos, instance: afterInst, readFace: afterRead, reportHttp: rep.status,
      newLog: afterLogs.filter((r) => r.operation_id === target.id).slice(-1)[0] ?? null,
      piecework: afterPw, expectedTotal: fmt(expAfter.total),
    }
    // 判据 F8-01：**与价格无关的一次保存**后，探针实例价必须逐字不变
    const instChanged = beforeInst.unit_price !== afterInst.unit_price
    out.f8.instanceUnitPriceChanged = instChanged
    R[!instChanged ? 'pass' : 'fail']('F8-01',
      '【F8 正对照】一次普通设置保存（body 只带 scope）后，探针实例单价必须逐字不变',
      `保存前 ${beforeInst.unit_price ?? 'NULL(未定价)'} → 保存后 ${afterInst.unit_price ?? 'NULL(未定价)'}`,
      [`PUT /api/admin/production/operations/${catRow.id} {scope:'${catRow.scope ?? 'position'}'}`, `SQL: processing_position_operations.id='${target.id}'`])
    // 判据 F8-02：价目矩阵行数/取值不得因此变化
    const posChanged = JSON.stringify(beforePos.map((r) => [r.position, r.unit_price, r.deleted])) !==
                       JSON.stringify(afterPos.map((r) => [r.position, r.unit_price, r.deleted]))
    out.f8.positionRowsChanged = posChanged
    R[!posChanged ? 'pass' : 'fail']('F8-02',
      '【F8 正对照】一次普通设置保存后，该逻辑工序的价目矩阵行（部位×价×软删）必须逐字不变',
      posChanged
        ? `前 ${JSON.stringify(beforePos.map((r) => [r.position, r.unit_price, r.deleted]))} → 后 ${JSON.stringify(afterPos.map((r) => [r.position, r.unit_price, r.deleted]))}`
        : `${beforePos.length} 行逐字一致`,
      [`SQL: production_operation_positions where logical_name='${logical}'（前后各一次）`])
    // 判据 F8-05：读面「有效价」（catalog + 部位价目矩阵）不得因一次普通保存而变
    const readChanged = JSON.stringify(beforeRead) !== JSON.stringify(afterRead)
    out.f8.readFaceChanged = readChanged
    R[!readChanged ? 'pass' : 'fail']('F8-05',
      '【F8 正对照】一次普通保存后，读面有效价（catalog + 部位价目矩阵）必须逐字不变',
      readChanged ? `前 ${JSON.stringify(beforeRead)} → 后 ${JSON.stringify(afterRead)}` : JSON.stringify(beforeRead),
      ['GET /operations-catalog', 'GET /operation-layers（前后各一次）'])
    // 判据 F8-03：**工资侧**读数必须仍等于独立算式（口径自洽）
    const pwMatches = moneyEq(afterPw?.total, fmt(expAfter.total))
    R[pwMatches ? 'pass' : 'fail']('F8-03',
      '【F8 正对照·工资侧】保存后工资读面仍 == 独立算式（口径自洽）',
      `读面 ${afterPw?.total} vs 独立算式 ${fmt(expAfter.total)}`,
      [`GET /orders/{A.orderId}/piecework`, `独立算式（报工快照）`])
    // 判据 F8-04：未定价工序**不得**静默变 0 元工资（这才是钱链的红线）
    const zeroLine = (afterPw?.per_operation ?? []).filter((r) => r.operation === target.operation_name && cents(r.amount) === 0n)
    const newLogPrice = out.f8.after.newLog?.unit_price ?? null
    R[zeroLine.length === 0 ? 'pass' : 'fail']('F8-04',
      '【F8 正对照·钱链红线】保存后未定价工序不得静默变 0 元工资',
      `per_operation 中 ${target.operation_name} 的 0 元行=${JSON.stringify(zeroLine)}；新报工快照价=${newLogPrice ?? 'NULL(未定价)'}；unpriced 块=${JSON.stringify(afterPw?.unpriced?.qty)}`,
      [`GET /orders/{A.orderId}/piecework`])
    out.f8.verdict = {
      instanceSilentlyPriced: instChanged,
      newLogSnapshotPrice: newLogPrice,
      unpricedBlockQtyAfter: afterPw?.unpriced?.qty,
    }
  } else {
    R.skip('F8-01', '【F8 正对照】', `未找到可注入的未定价实例（target=${JSON.stringify(target)} catRow=${catRow?.id ?? null}）`)
    R.skip('F8-02', '【F8 正对照】', '同上')
    R.skip('F8-03', '【F8 正对照】', '同上')
    R.skip('F8-04', '【F8 正对照】', '同上')
  }

  // ══════ ③ 并发干扰核对（非自建行值变化） ══════
  const p0 = JSON.parse(readFileSync(join(OUT, 'p0-surface.json'), 'utf8'))
  const nowOps = psql(`select id, name, unit_price::text as unit_price, scope, status from production_operations where tenant_id=${T} and coalesce(deleted,0)=0 order by name`)
  const nowPos = psql(`select id, logical_name, position, unit_price::text as unit_price from production_operation_positions where tenant_id=${T} and coalesce(deleted,0)=0 order by logical_name, position, id`)
  const key = (r, ks) => ks.map((k) => String(r[k])).join('|')
  const diff = (a, b, ks) => {
    const ma = new Map(a.map((r) => [r.id, key(r, ks)])), mb = new Map(b.map((r) => [r.id, key(r, ks)]))
    const changed = [], added = [], removed = []
    for (const [id, v] of mb) { if (!ma.has(id)) added.push([id, v]); else if (ma.get(id) !== v) changed.push([id, ma.get(id), v]) }
    for (const [id, v] of ma) if (!mb.has(id)) removed.push([id, v])
    return { changed, added, removed }
  }
  // 键比对：只比**两侧都存在的键所共有的列**（基线快照可能缺列，如 deleted）
  const keyOf = (r, ks) => ks.filter((k) => r[k] !== undefined).map((k) => `${k}=${String(r[k])}`).join('|')
  const cmp = (a, b, ks, idOf) => {
    const ma = new Map(a.map((r) => [idOf(r), r])), mb = new Map(b.map((r) => [idOf(r), r]))
    const changed = [], added = [], removed = []
    for (const [id, rb] of mb) {
      const ra = ma.get(id)
      if (!ra) { added.push([id, JSON.stringify(rb)]); continue }
      const common = ks.filter((k) => ra[k] !== undefined && rb[k] !== undefined)
      const va = common.map((k) => `${k}=${String(ra[k])}`).join('|')
      // 若基线缺该字段（如 deleted 未在 P0 选列），单侧取值也算变化但标注 oneSided
      const vb = ks.map((k) => `${k}=${String(rb[k])}`).join('|')
      const oneSided = common.length !== ks.length
      if (va !== vb) changed.push([id, va, vb, oneSided ? 'oneSided(missing column)' : 'both'])
    }
    for (const [id, ra] of ma) if (!mb.has(id)) removed.push([id, JSON.stringify(ra)])
    return { changed, added, removed }
  }
  const opsDiff = cmp(p0.interference.operationsBaseline, nowOps, ['unit_price', 'scope', 'status'], (r) => r.id)
  const posDiff = cmp(p0.interference.positionPriceBaseline, nowPos, ['unit_price'], (r) => r.id)
  const isProbe = (name) => String(name || '').startsWith(PROBE_PREFIX)
  const opNameOf = (id) => nowOps.find((r) => r.id === id)?.name ?? id
  const posNameOf = (id) => { const r = nowPos.find((x) => x.id === id); return r ? `${r.logical_name}@${r.position}` : id }
  const opsReal = opsDiff.changed.filter(([id]) => !isProbe(opNameOf(id)))
  const posReal = posDiff.changed.filter(([id]) => !isProbe(posNameOf(id)))
  const addedReal = [...opsDiff.added, ...posDiff.added].filter(([id]) => {
    const n = opNameOf(id) !== id ? opNameOf(id) : posNameOf(id)
    return !isProbe(n)
  })
  out.interference = {
    at: new Date().toISOString(), p0At: p0.meta.at,
    rawCounts: { opsChanged: opsDiff.changed.length, posChanged: posDiff.changed.length, added: opsDiff.added.length + posDiff.added.length, removed: opsDiff.removed.length + posDiff.removed.length },
    operationsChanged: opsDiff.changed, positionPricesChanged: posDiff.changed,
    added: [...opsDiff.added, ...posDiff.added], removed: [...opsDiff.removed, ...posDiff.removed],
    nonProbe: { operations: opsReal, positionPrices: posReal, added: addedReal },
    note: '只依赖自建探针对象判定；非自建行的变化一律记为「疑似并发干扰」，**不作为缺陷登记**',
  }
  const n = out.interference.nonProbe
  const susp = n.operations.length + n.positionPrices.length + n.added.length
  R.pass('X-01', '并发干扰核对（非自建行两次读之间是否变过）',
    susp === 0
      ? `未发现非自建行变化（工序库 ${p0.interference.operationsBaseline.length} 行 / 价目 ${p0.interference.positionPriceBaseline.length} 行逐行比对）`
      : `**疑似并发干扰 ${susp} 处** ⇒ ${JSON.stringify(n)}（附时间戳 ${p0.meta.at} → ${out.interference.at}，不作为缺陷）`,
    ['SQL 两次快照逐行按对象键比对', `P0 基线时间 ${p0.meta.at}`, `本次时间 ${out.interference.at}`])

  writeFileSync(join(OUT, 'p3-f8-redproof.json'), JSON.stringify(out, null, 2))
  log(`F8: instancePrice ${out.f8?.before?.instance?.unit_price ?? 'NULL'} → ${out.f8?.after?.instance?.unit_price ?? 'NULL'}；新报工快照=${out.f8?.verdict?.newLogSnapshotPrice ?? '-'}`)
  log(`干扰核对: ${JSON.stringify(out.interference.nonProbeChanges)}`)
  log(`summary=${JSON.stringify(R.summary())}`)
}
main().catch((e) => { console.error(e); process.exit(1) })
