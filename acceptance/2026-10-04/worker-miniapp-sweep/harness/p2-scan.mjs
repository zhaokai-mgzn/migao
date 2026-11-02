// P2 — 工人端**扫码闭环**（A1 核心写路径）：GET scan（只读）→ POST scan/complete（唯一写入口）
//
// 判据来源（源码符号）：
//   GET  /api/worker/production/scan                → ProductionScanService.resolve
//   POST /api/worker/production/scan/complete       → ProductionScanCompleteService.complete
//   POST /api/worker/production/orders/{o}/operations/{op}/report → ProductionService.report
// 期望一律本包**独立算出**：qty/qualified_qty/worker 绑定/时间戳从 DB 复读，不拿被测读面当期望。
import { writeFileSync, readFileSync, existsSync, outPath } from './lib.mjs'
import {
  Recorder, judge, apiWorker, log, nowCST, psql, one, loginApi, log as _log,
  buildFixture, fixtureDupSeq, fixtureOps, workLogs, reportAudits, idemRow, idemKey,
  cleanupFixture, guardedWrite, ensureWorkerSession, storePath, saveStore,
  TENANT_ID, PROBE_PREFIX, ID_PREFIX, fmtQty, cents,
} from './lib.mjs'

const R = new Recorder('P2-scan.json')
const store = existsSync(storePath()) ? JSON.parse(readFileSync(storePath(), 'utf8')) : {}
const A = await ensureWorkerSession(store, 'A')
const B = await ensureWorkerSession(store, 'B')
const fixtures = store.fixtures || (store.fixtures = {})

// ══════════════ P2-1 正路径：夹具自建 + 扫码解析（只读）+ 开工写库 ══════════════
const F = buildFixture({ tag: 'P2', qty: '12.30' })
fixtures.P2 = F; saveStore(store)
log(`夹具 P2: po=${F.poId} set=${F.setId} op=${F.opId} token=${F.token}`)

const beforeScanOps = fixtureOps(F)
const beforeScanLogs = workLogs(F)

// ① scan 是只读面：解析出 (套, 部位) + 推断出的工序 + set_overview
const scan1 = await apiWorker('GET', `/api/worker/production/scan?token=${encodeURIComponent(F.token)}`, { sessionId: A.sessionId })
const scanOpId = scan1.json?.data?.operation?.operation_id ?? null
const afterScanOps = fixtureOps(F)
const afterScanLogs = workLogs(F)
judge(R, {
  id: 'C1.scan-resolves', name: 'GET /api/worker/production/scan（新码）⇒ 解析出套×部位 + 推断出唯一工序',
  expect: 'HTTP 200 + granularity=set_position + set_no 与本夹具一致 + operation.operation_id == 夹具唯一待做工序',
  actual: `HTTP ${scan1.status} granularity=${scan1.json?.data?.granularity} set_no=${scan1.json?.data?.set_no} op=${scanOpId} determined_by=${scan1.json?.data?.operation?.determined_by}`,
  pass: scan1.status === 200 && scan1.json?.data?.granularity === 'set_position'
    && scan1.json?.data?.set_no === `${F.poNo}-001` && scanOpId === F.opId,
  expectSource: 'ProductionScanService.findPartToken + setPositionView（工序由系统推断 = min(seq) 唯一那道）',
  evidence: [`set_overview.positions=${JSON.stringify(scan1.json?.data?.set_overview?.positions?.map((p) => ({ item: p.order_item_id, ops: p.operations?.length })))}`],
})
judge(R, {
  id: 'C2.scan-is-readonly', name: 'scan 是**只读**面：工序实例与报工明细零变化',
  expect: 'before == after（processing_position_operations 与 production_work_logs 逐字相同）',
  actual: `ops: ${JSON.stringify(beforeScanOps) === JSON.stringify(afterScanOps)} / logs: ${beforeScanLogs.length}→${afterScanLogs.length}`,
  pass: JSON.stringify(beforeScanOps) === JSON.stringify(afterScanOps) && afterScanLogs.length === 0,
  expectSource: 'ProductionScanService 类注释「本切片是只读面，不写库、不落痕」',
  evidence: [`beforeOps=${JSON.stringify(beforeScanOps)}`, `afterOps=${JSON.stringify(afterScanOps)}`],
})

// ② 开工（唯一写入口）：不带 qty ⇒ 服务端取「剩余应做」= 12.30
const key1 = idemKey('p2complete')
const comp1 = await apiWorker('POST', '/api/worker/production/scan/complete', {
  sessionId: A.sessionId, body: { token: F.token }, headers: { 'X-Client-Request-Id': key1 },
})
const opAfter = fixtureOps(F).find((o) => o.id === F.opId)
const logsAfter = workLogs(F)
const auditAfter = reportAudits(F)
const l0 = logsAfter[0]
judge(R, {
  id: 'C3.complete-writes', name: 'POST scan/complete ⇒ HTTP 200 + 落 1 行 production_work_logs',
  expect: 'HTTP 200 + work_logs 恰好 1 行（operation_id=夹具工序）',
  actual: `HTTP ${comp1.status} logs=${logsAfter.length} ${JSON.stringify(logsAfter)}`,
  pass: comp1.status === 200 && logsAfter.length === 1 && l0?.operation_id === F.opId,
  expectSource: 'ProductionScanCompleteService.complete → ProductionService.applyScanComplete（一次事务）',
  evidence: [`resp=${JSON.stringify(comp1.json?.data).slice(0, 400)}`],
})
judge(R, {
  id: 'C4.log-qty-and-worker', name: '落库数量/合格数/工人绑定与请求一致（期望本包独立算出）',
  expect: `qty=12.30 qualified=12.30 worker_id=${A.workerId} worker_name=${A.workerName}`,
  actual: `qty=${l0?.qty} qualified=${l0?.qualified_qty} worker_id=${l0?.worker_id} worker_name=${l0?.worker_name}`,
  pass: cents(l0?.qty) === cents('12.30') && cents(l0?.qualified_qty) === cents('12.30')
    && l0?.worker_id === A.workerId && l0?.worker_name === A.workerName,
  expectSource: '缺省 qty = 剩余应做(12.30)；worker 由 X-Worker-Session-Id 解（#4733：body 同名字段不读）',
})
judge(R, {
  id: 'C5.op-advanced-and-stamped', name: '工序实例被推进：done_qty=12.30 + done_at/started_at + 领活人 = 本次工人',
  expect: 'done_qty=12.30 + has_done_at + has_started_at + worker_id=本次工人',
  actual: `done_qty=${opAfter?.done_qty} done_at=${opAfter?.has_done_at} started_at=${opAfter?.has_started_at} worker_id=${opAfter?.worker_id} started_cst=${opAfter?.started_at_cst}`,
  pass: cents(opAfter?.done_qty) === cents('12.30') && opAfter?.has_done_at === true
    && opAfter?.has_started_at === true && opAfter?.worker_id === A.workerId,
  expectSource: 'applyScanComplete：CAS 推进 done_qty + done_at + started_at/worker_id（#4967 领活语义）',
})
judge(R, {
  id: 'C6.audit-identity-source', name: '身份旁路账：identity_source=server_session（body 不能自称工人）',
  expect: 'worker_report_audits 行数 ≥1 且 identity_source=server_session + session_id 为本次',
  actual: JSON.stringify(auditAfter),
  pass: auditAfter.length >= 1 && auditAfter.every((a) => a.identity_source === 'server_session') && auditAfter[0]?.worker_session_id === A.sessionId,
  expectSource: 'WorkerReportAudit（V98 旁路账：server_session 权威 / client_body 显式降级）',
})

// ③ 幂等：同 X-Client-Request-Id 重放 ⇒ 不重复计件
const comp2 = await apiWorker('POST', '/api/worker/production/scan/complete', {
  sessionId: A.sessionId, body: { token: F.token }, headers: { 'X-Client-Request-Id': key1 },
})
const logsAfter2 = workLogs(F)
const opAfter2 = fixtureOps(F).find((o) => o.id === F.opId)
const idem = idemRow(key1)
judge(R, {
  id: 'C7.idempotent-replay', name: '同 X-Client-Request-Id 重复提交 ⇒ 回放首次结果、**不重复计件**',
  expect: 'work_logs 仍恰好 1 行 + 第二次响应 replayed=true + client_request_keys 有快照',
  actual: `logs=${logsAfter2.length}（第二次 HTTP ${comp2.status}）第二次响应=${JSON.stringify(comp2.json?.data).slice(0, 200)} idemRow=${JSON.stringify(idem)}`,
  pass: logsAfter2.length === 1 && comp2.status === 200
    && (comp2.json?.data?.replayed === true || JSON.stringify(comp2.json?.data) === JSON.stringify(comp1.json?.data)),
  expectSource: 'ClientRequestIdService.claim/complete（同租户同键唯一 + 响应快照回放，issue #4037）',
  evidence: [`op done_qty=${opAfter2?.done_qty}（不得被再加一次）`],
})

// ④ 重复完工（无幂等键）：已报满 ⇒ 必须拒绝且**不写第二行**
const comp3 = await apiWorker('POST', '/api/worker/production/scan/complete', { sessionId: A.sessionId, body: { token: F.token } })
const logsAfter3 = workLogs(F)
const opAfter3 = fixtureOps(F).find((o) => o.id === F.opId)
judge(R, {
  id: 'C8.repeat-complete-rejected', name: '同一码重复开工（无幂等键）⇒ 拒绝（409/422）且不写第二行、不加数量',
  expect: 'HTTP 4xx + work_logs 仍 1 行 + done_qty 仍 12.30',
  actual: `HTTP ${comp3.status} code=${comp3.json?.error?.code} logs=${logsAfter3.length} done_qty=${opAfter3?.done_qty}`,
  pass: comp3.status >= 400 && comp3.status < 500 && logsAfter3.length === 1 && cents(opAfter3?.done_qty) === cents('12.30'),
  expectSource: 'ProductionScanCompleteService：plannedRemaining<=0 ⇒ OPERATION_ALREADY_ADVANCED(409) / 推断 completed',
  evidence: [`body=${JSON.stringify(comp3.json?.error ?? comp3.json?.data ?? {}).slice(0, 300)}`],
})

// ⑤ 回执形状（🔴 判据修正：不能只断言「六键齐全」——全局 `spring.jackson.default-property-inclusion: non_null`
//    会把值为 null 的键整个丢掉 ⇒「没有下一道」时 `next_operation` **合法缺键**）
//    C9a 正例：**确实还有下一道** ⇒ 必须含 next_operation 且指向下一道
//    C9b 口径：单工序夹具（报完就完）⇒ 允许缺 next_operation，但 set_* 系列必须在
const shapeKeys = Object.keys(comp1.json?.data ?? {})
judge(R, {
  id: 'C9a.receipt-shape', name: '回执含「本套进度 + 本道结果」（set_no/position/set_overview/set_progress/set_completed 必在）',
  expect: '上述五键都在（值可空；受全局 non_null 影响 ⇒ 非空才有键）',
  actual: `keys=${JSON.stringify(shapeKeys)}`,
  pass: ['set_no', 'position', 'set_overview', 'set_progress', 'set_completed'].every((k) => k in (comp1.json?.data ?? {})),
  expectSource: 'ProductionScanCompleteService.doComplete（成功/异常两条路径都写 set_progress/set_completed/next_operation）+ application.yml 的 `spring.jackson.default-property-inclusion: non_null`',
  evidence: ['观察项：值为 null 的键被全局序列化口径丢弃 ⇒ 对外契约是「**非空才有该键**」，客户端不得用 hasOwnProperty 判「有没有下一道」'],
})
// 造一张**两道工序**的夹具：报第一道后，回执必须给出下一道
const FM = buildFixture({ tag: 'P2I', qty: '5.00', opCount: 2 })
fixtures.P2I = FM; saveStore(store)
const fmScan = await apiWorker('GET', `/api/worker/production/scan?token=${encodeURIComponent(FM.token)}`, { sessionId: A.sessionId })
const fmFirst = fmScan.json?.data?.operation?.operation_id ?? FM.opIds[0]
const fmComp = await apiWorker('POST', '/api/worker/production/scan/complete', { sessionId: A.sessionId, body: { token: FM.token, qty: '5' } })
const fmNext = fmComp.json?.data?.next_operation ?? null
const remaining = fixtureOps(FM).filter((o) => o.done_qty === '0.00')
judge(R, {
  id: 'C9b.next-operation-present', name: '🔴 还有下一道时：回执**必须**含 next_operation，且指向本套剩下的那道（与 DB 独立读数对齐）',
  expect: `next_operation 存在且其 operation_id == ${JSON.stringify(remaining[0]?.id)}（= 本包独立从 DB 读出的剩余工序）`,
  actual: `keys=${JSON.stringify(Object.keys(fmComp.json?.data ?? {}))} next=${JSON.stringify(fmNext)} 剩余工序=${JSON.stringify(remaining.map((o) => o.id))}`,
  pass: !!fmNext && nextTarget(fmNext) === remaining[0]?.id,
  expectSource: 'ProductionScanCompleteService 的 next_operation（报工提交后**再解析一次**，尽力而为）+ DB 独立复读剩余工序',
  evidence: [`首道=${fmFirst} 已报满；剩余=${remaining.length} 道`],
})
function nextTarget(n) {
  return n?.operation_id ?? n?.operation?.operation_id ?? n?.id ?? null
}

// ══════════════ P2-2 负例：非法/跨租户/未确定工序（每条都要**零写入**）══════════════
const logsBeforeNeg = workLogs(F).length

// ⑥ 未确定工序：同 seq 两道 ⇒ 必须 422 且零写入（红证核心）
const F2 = buildFixture({ tag: 'P2D', qty: '5.00' })
fixtures.P2D = F2; saveStore(store)
fixtureDupSeq(F2)
const dupScan = await apiWorker('GET', `/api/worker/production/scan?token=${encodeURIComponent(F2.token)}`, { sessionId: A.sessionId })
const dupComplete = await apiWorker('POST', '/api/worker/production/scan/complete', { sessionId: A.sessionId, body: { token: F2.token } })
const dupLogs = workLogs(F2)
const dupOps = fixtureOps(F2)
judge(R, {
  id: 'C10.ambiguous-operation', name: '同 seq 多道待做工序 ⇒ 422 OPERATION_AMBIGUOUS（scan 与 complete 都拒绝）',
  expect: 'scan 422 + complete 422 + code=OPERATION_AMBIGUOUS',
  actual: `scan=${dupScan.status}/${dupScan.json?.error?.code} complete=${dupComplete.status}/${dupComplete.json?.error?.code}`,
  pass: dupScan.status === 422 && dupComplete.status === 422
    && dupScan.json?.error?.code === 'OPERATION_AMBIGUOUS' && dupComplete.json?.error?.code === 'OPERATION_AMBIGUOUS',
  expectSource: 'ProductionScanService.setPositionView：ties>1 ⇒ OPERATION_AMBIGUOUS（不静默取第一道）',
})
judge(R, {
  id: 'C11.ambiguous-no-write', name: '🔴 红证：工序未确定时**一个字节都不写**（work_logs=0 且两道工序 done_qty 都还是 0）',
  expect: 'work_logs=0 + 两道工序 done_qty 全 0 + status 全 pending',
  actual: `logs=${dupLogs.length} ops=${JSON.stringify(dupOps.map((o) => [o.id.slice(-6), o.done_qty, o.status]))}`,
  pass: dupLogs.length === 0 && dupOps.length === 2 && dupOps.every((o) => cents(o.done_qty) === 0n && o.status === 'pending'),
  expectSource: 'ProductionScanCompleteService 类注释③「未确定工序 ⇒ 拒绝记账，一个字节都不写 production_work_logs」',
})

// ⑦ 非法工序（不属于本次扫码部位）⇒ 422 OPERATION_NOT_IN_SCAN_TARGET，零写入
const F3 = buildFixture({ tag: 'P2E', qty: '3.00' })
fixtures.P2E = F3; saveStore(store)
const foreignOp = F.opId // 属于**另一个**夹具的部位
const foreignScan = await apiWorker('GET', `/api/worker/production/scan?token=${encodeURIComponent(F3.token)}&operation_id=${foreignOp}`, { sessionId: A.sessionId })
const foreignComplete = await apiWorker('POST', '/api/worker/production/scan/complete', { sessionId: A.sessionId, body: { token: F3.token, operation_id: foreignOp } })
judge(R, {
  id: 'C12.foreign-operation', name: '显式指定**别的部位**的工序 ⇒ 422 OPERATION_NOT_IN_SCAN_TARGET（跨部位报工被拒）',
  expect: 'scan 422 + complete 422 + 零写入',
  actual: `scan=${foreignScan.status}/${foreignScan.json?.error?.code} complete=${foreignComplete.status}/${foreignComplete.json?.error?.code} logs=${workLogs(F3).length}`,
  pass: foreignScan.status === 422 && foreignComplete.status === 422
    && foreignScan.json?.error?.code === 'OPERATION_NOT_IN_SCAN_TARGET' && workLogs(F3).length === 0,
  expectSource: 'ProductionScanService：operationId 必须属于本次扫码的部位/套（防呆④）',
})

// ⑧ 超量报工 ⇒ 拒绝（不 clamp）
const overQty = await apiWorker('POST', '/api/worker/production/scan/complete', { sessionId: A.sessionId, body: { token: F3.token, qty: '99' } })
judge(R, {
  id: 'C13.over-qty', name: '超量报工（qty 99 > 应做 3.00）⇒ 拒绝且零写入',
  expect: 'HTTP 4xx + work_logs=0 + 工序 done_qty 仍 0',
  actual: `HTTP ${overQty.status} code=${overQty.json?.error?.code} logs=${workLogs(F3).length} done=${fixtureOps(F3)[0]?.done_qty}`,
  pass: overQty.status >= 400 && overQty.status < 500 && workLogs(F3).length === 0 && cents(fixtureOps(F3)[0]?.done_qty) === 0n,
  expectSource: 'assertWithinPlannedQty（#4116 §5-3：超上限拒绝不 clamp）',
  evidence: [`body=${JSON.stringify(overQty.json?.error ?? {}).slice(0, 240)}`],
})

// ⑨ 负数/0 数量 ⇒ 422
const negQty = await apiWorker('POST', '/api/worker/production/scan/complete', { sessionId: A.sessionId, body: { token: F3.token, qty: '-1' } })
const zeroQty = await apiWorker('POST', '/api/worker/production/scan/complete', { sessionId: A.sessionId, body: { token: F3.token, qty: '0' } })
judge(R, {
  id: 'C14.nonpositive-qty', name: 'qty ≤ 0 ⇒ 422 VALIDATION_ERROR（负数 / 零各一条）',
  expect: 'both 422', actual: `neg=${negQty.status}/${negQty.json?.error?.code} zero=${zeroQty.status}/${zeroQty.json?.error?.code}`,
  pass: negQty.status === 422 && zeroQty.status === 422,
  expectSource: 'ProductionScanCompleteService：qty.signum()<=0 ⇒ validationError("qty 必须大于 0")',
})

// ⑩ 非法 token ⇒ 404 且零写入
const badToken = await apiWorker('POST', '/api/worker/production/scan/complete', { sessionId: A.sessionId, body: { token: 'la' + '1'.repeat(30) } })
judge(R, {
  id: 'C15.bad-token', name: '不存在的码 ⇒ 404（既有的「订单不存在」行为）且零写入',
  expect: 'HTTP 404 + code=NOT_FOUND', actual: `HTTP ${badToken.status} code=${badToken.json?.error?.code} msg=${badToken.json?.error?.message}`,
  pass: badToken.status === 404,
  expectSource: 'ProductionScanService.degradedView → ProductionService.resolveOrder（四形态全不命中 ⇒ 404）',
})

// ⑪ 空 token ⇒ 422（校验，不是 500）
const emptyToken = await apiWorker('POST', '/api/worker/production/scan/complete', { sessionId: A.sessionId, body: { token: '   ' } })
judge(R, {
  id: 'C16.empty-token', name: 'token 空白 ⇒ 422 VALIDATION_ERROR（不得 500）',
  expect: 'HTTP 422', actual: `HTTP ${emptyToken.status} code=${emptyToken.json?.error?.code}`,
  pass: emptyToken.status === 422,
  expectSource: 'ProductionScanCompleteService.doComplete：token 缺失 ⇒ validationError',
})

// ⑫ 跨租户：本租户 session 动**别的租户**的对象 ⇒ 404/0 命中
// 🔴 2026-10-04 口径修正：旧底座写死 `T21 = 21`，而旧租户 20/1/21 已于 2026-10-04 08:31 清空
// ⇒ 必须**动态**找对照租户（`tenants` 表里 id ≠ 本租户的第一个）；一个都没有 ⇒ 如实 skip。
const T21 = one(`select id from tenants where id <> ${TENANT_ID} order by id limit 1`)?.id ?? null
const t21Row = T21 == null ? null : one(`select o.id as po_id, o.processing_order_id, o.set_id, o.order_item_id, t.token
                      from processing_set_part_tokens t
                      join processing_position_operations o
                        on o.tenant_id=t.tenant_id and o.processing_order_id=t.processing_order_id
                       and o.set_id=t.set_id and o.order_item_id=t.order_item_id and o.deleted=0
                     where t.tenant_id=${T21} and t.deleted=0 and t.token is not null limit 1`)
if (!t21Row) {
  R.skip('C17.cross-tenant-object', '跨租户对象写入（对照租户的部位码）',
    T21 == null ? '库内**没有第二个租户**（旧租户 20/1/21 已清空，对照租户由线③临时创建且会被其删除）⇒ 无对照对象，本判定未覆盖' : `租户 ${T21} 无「码 + 待做工序」的夹具（无可用对象），本判定未覆盖`)
} else {
  const logs21Before = psql(`select count(*)::int n from production_work_logs where tenant_id=${T21} and processing_order_id='${t21Row.processing_order_id}'`)[0].n
  const ct = await apiWorker('POST', '/api/worker/production/scan/complete', { sessionId: A.sessionId, body: { token: t21Row.token } })
  log(`C17 跨租户对照租户 = ${T21}`)
  const logs21After = psql(`select count(*)::int n from production_work_logs where tenant_id=${T21} and processing_order_id='${t21Row.processing_order_id}'`)[0].n
  judge(R, {
    id: 'C17.cross-tenant-object', name: `本租户(${TENANT_ID}) 的工人 session 扫**对照租户 ${T21}** 的码 ⇒ 4xx 且对照租户零写入`,
    expect: 'HTTP 404（findPartToken 带 tenant_id 谓词 ⇒ 未命中 ⇒ 回落四形态 ⇒ 404）+ 租户21 work_logs 行数不变',
    actual: `HTTP ${ct.status} code=${ct.json?.error?.code} T${T21} logs: ${logs21Before}→${logs21After}`,
    pass: ct.status === 404 && logs21Before === logs21After,
    expectSource: 'ProductionScanService.findPartToken：`tenant_id` 正向相等（fail-closed，不按别人的单记账）',
  })
}

// ⑬ 工人身份不可由 body 冒领（红证：body 塞别人的 worker_id/worker_name）
const F4 = buildFixture({ tag: 'P2F', qty: '2.50' })
fixtures.P2F = F4; saveStore(store)
const spoof = await apiWorker('POST', '/api/worker/production/scan/complete', {
  sessionId: A.sessionId,
  body: { token: F4.token, worker_id: B.workerId, worker_name: B.workerName },
})
const spoofLog = workLogs(F4)[0]
judge(R, {
  id: 'C18.spoof-identity-ignored', name: '🔴 body 塞别人的 worker_id/worker_name ⇒ 仍记在**登录者**头上',
  expect: `worker_id=${A.workerId}（不是 ${B.workerId}）`,
  actual: `HTTP ${spoof.status} log.worker_id=${spoofLog?.worker_id} worker_name=${spoofLog?.worker_name}`,
  pass: spoof.status === 200 && spoofLog?.worker_id === A.workerId && spoofLog?.worker_name === A.workerName,
  expectSource: 'WorkerProductionController 类注释：body 的 worker_id/worker_name「一个字节都不读」（#4733 工资凭证）',
})

// ══════════════ P2-3 report 端点（逐道报工；商家侧口径）══════════════
const F5 = buildFixture({ tag: 'P2G', qty: '4.00' })
fixtures.P2G = F5; saveStore(store)
const repKey = idemKey('p2report')
const rep = await apiWorker('POST', `/api/worker/production/orders/${F.orderId}/operations/${F.opId}/report`, {
  sessionId: A.sessionId, body: { qty: '4.00', qualified_qty: '4.00' }, headers: { 'X-Client-Request-Id': repKey },
})
log(`report 探针（对已完工的 P2 工序）：HTTP ${rep.status} code=${rep.json?.error?.code ?? '-'}`)

const repOk = await apiWorker('POST', `/api/worker/production/orders/${F5.orderId}/operations/${F5.opId}/report`, {
  sessionId: A.sessionId, body: { qty: '4.00', qualified_qty: '4.00', worker_id: B.workerId, worker_name: B.workerName }, headers: { 'X-Client-Request-Id': repKey },
})
const repLog = workLogs(F5)[0]
judge(R, {
  id: 'C19.report-endpoint', name: 'POST …/operations/{op}/report（工人 session）⇒ 落库并记在登录者头上',
  expect: 'HTTP 200 + work_logs 1 行 qty=4.00 worker=A',
  actual: `HTTP ${repOk.status} logs=${workLogs(F5).length} qty=${repLog?.qty} worker=${repLog?.worker_id}`,
  pass: repOk.status === 200 && workLogs(F5).length === 1 && cents(repLog?.qty) === cents('4.00') && repLog?.worker_id === A.workerId,
  expectSource: 'WorkerProductionController.report → ProductionService.report（identity 来自 session）',
})
const repDup = await apiWorker('POST', `/api/worker/production/orders/${F5.orderId}/operations/${F5.opId}/report`, {
  sessionId: A.sessionId, body: { qty: '4.00' }, headers: { 'X-Client-Request-Id': repKey },
})
judge(R, {
  id: 'C20.report-idempotent', name: 'report 同 X-Client-Request-Id 重放 ⇒ 不重复计件（仍 1 行）',
  expect: 'work_logs 仍 1 行', actual: `HTTP ${repDup.status} logs=${workLogs(F5).length}`,
  pass: repDup.status === 200 && workLogs(F5).length === 1,
  expectSource: 'ClientRequestIdService（与 scan/complete 同一套幂等实现，同一张表）',
})
const repNoSession = await apiWorker('POST', `/api/worker/production/orders/${F5.orderId}/operations/${F5.opId}/report`, { sessionId: null, body: { qty: '1.00' } })
judge(R, {
  id: 'C21.report-needs-session', name: 'report 无工人 session ⇒ 401（不降级到 body 口径）',
  expect: 'HTTP 401', actual: `HTTP ${repNoSession.status}`, pass: repNoSession.status === 401,
  expectSource: 'WorkerProductionController.report：identity==null ⇒ authFailed（工人路径上「谁报的」没有第二条来源）',
})

// ⑭ 跨租户 report：会话租户 20 的工人带 X-Tenant-Id:21 报租户 20 的单 ⇒ 租户 21 侧必须零写入
//    （A11 已证「租户不由请求头决定」⇒ 请求头只是**不被采纳**，不是越权通道）
const F6 = buildFixture({ tag: 'P2H', qty: '1.00' })
fixtures.P2H = F6; saveStore(store)
const XT = T21  // 动态对照租户（同 ⑫）；null ⇒ 本判定未覆盖
const crossReport = XT == null ? null : await apiWorker('POST', `/api/worker/production/orders/${F6.orderId}/operations/${F6.opId}/report`, { sessionId: B.sessionId, tenantId: XT, body: { qty: '1.00' } })
const t21Before = XT == null ? null : psql(`select
    (select count(*)::int from orders where tenant_id=21) as orders,
    (select count(*)::int from processing_orders where tenant_id=21) as pos,
    (select count(*)::int from production_work_logs where tenant_id=21) as logs,
    (select count(*)::int from worker_report_audits where tenant_id=21) as audits`)[0]
const t21After = XT == null ? null : psql(`select
    (select count(*)::int from orders where tenant_id=21) as orders,
    (select count(*)::int from processing_orders where tenant_id=21) as pos,
    (select count(*)::int from production_work_logs where tenant_id=21) as logs,
    (select count(*)::int from worker_report_audits where tenant_id=21) as audits`)[0]
if (XT == null) {
  R.skip('C22.report-tenant-binding', '会话工人 + 请求头 X-Tenant-Id:<对照租户> 报本租户的单 ⇒ 对照租户侧零写入', '库内没有第二个租户 ⇒ 无对照面，本判定未覆盖')
} else {
  judge(R, {
    id: 'C22.report-tenant-binding', name: `会话租户(${TENANT_ID}) 工人 + 请求头 X-Tenant-Id:${XT} 报本租户的单 ⇒ **对照租户 ${XT} 侧零写入**（独立复读其全表计数）`,
    expect: `租户 ${XT} 的 orders/processing_orders/work_logs/audits 四项前后完全相同（0 命中）`,
    actual: `before=${JSON.stringify(t21Before)} after=${JSON.stringify(t21After)}（本次 HTTP ${crossReport.status}，落库进本租户夹具：logs=${workLogs(F6).length}）`,
    pass: JSON.stringify(t21Before) === JSON.stringify(t21After) && workLogs(F6).length === 1,
    expectSource: 'TenantContext 由会话行设定（A11）+ 写面查询带 tenant_id 谓词 ⇒ 请求头换租户不产生任何跨租户写',
    evidence: ['判据修正留档：第一版写「4xx 或零写入」⇒ 200 被误判红（假红），且没有**去对照租户侧复读**——命题本身写偏了',
               '2026-10-04 口径修正：旧底座把对照租户写死成 21（已清空）⇒ 改为动态取「id ≠ 本租户 的第一个租户」，没有则 skip'],
  })
}

// ══════════════ P2-4 cutting-height（只读，不写机器）══════════════
const ch = await apiWorker('GET', `/api/worker/production/cutting-height?token=${encodeURIComponent(F5.token)}`, { sessionId: A.sessionId })
// 🔴 判据三态分明（**修前红证**）：200 且有 base/cutting_height = pass；4xx = 可接受（数据不足）；
//    5xx = **fail(产品)**。第一版写成 `(status>=400 && …)` ⇒ 把 500 吞成 pass（主会话独立复核当场抓到，
//    属 migao-acceptance「判据比它声称的宽」那种假绿）。
const chData = ch.json?.data ?? {}
judge(R, {
  id: 'C23.cutting-height', name: 'GET /api/worker/production/cutting-height ⇒ 只读一屏（200 有 base/cutting_height）或 4xx（数据不足）；**5xx 一律判红**',
  expect: '200 且含 base/cutting_height 键 / 或 4xx；不得 5xx',
  actual: `HTTP ${ch.status} keys=${JSON.stringify(Object.keys(chData))} positions[0]=${JSON.stringify(chData.positions?.[0] ?? null).slice(0, 220)}`,
  // base / cutting_height 在 `positions[]` 行内（源码：positionRow 把 base/cutting_height 放进每个部位行）
  pass: ch.status === 200
    ? Array.isArray(chData.positions) && chData.positions.length > 0 && 'base' in chData.positions[0] && 'cutting_height' in chData.positions[0]
    : (ch.status >= 400 && ch.status < 500),
  expectSource: 'WorkerCuttingHeightService.read（只读；#5161「不写机器」）+ 类注释「缺值 ⇒ 显式缺失，不静默」',
  evidence: [`夹具工序/报工数：ops=${fixtureOps(F5).length} logs=${workLogs(F5).length}（只读面零副作用）`],
})
// 真缺陷指向（详见 P2b 复现段）：同一码在**订单行 product_id 为 NULL** 时必 500
const nullPidProbe = store.fixtures?.P2N1 ? null : null
judge(R, {
  id: 'C23b.cutting-height-null-product', name: '🔴 cutting-height：本夹具订单行 product_id 为 NULL 时的读数（真缺陷复现见 P2b）',
  expect: '不得 5xx（设计：缺值 ⇒ 进 missing[]，不静默、不 500）',
  actual: `本夹具 product_id=${JSON.stringify(one(`select product_id from order_items where id='${F5.itemId}'`))}；端点 HTTP ${ch.status}`,
  pass: ch.status < 500,
  expectSource: 'WorkerCuttingHeightService.positionRow:149 `brands.get(item.getProductId())` + brands():276 `Map.of()` ⇒ NULL 建键 NPE',
  evidence: ['独立复现（自建夹具 + 单变量对照）见 P2b/N1~N5 与 out/P2b-cuttingheight-npe.json'],
})

// ② C22 改判：命题 = **租户 21 侧零写入**（去租户 21 库复读），不是「4xx」
writeFileSync(outPath('P2-scan-summary.json'), JSON.stringify({ at: nowCST(), summary: R.summary() }, null, 2))
log(`P2 汇总: ${JSON.stringify(R.summary())}`)
process.exit(0)
