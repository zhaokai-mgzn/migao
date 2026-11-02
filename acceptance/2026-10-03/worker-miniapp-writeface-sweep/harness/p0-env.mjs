// P0 — 环境自证：构建点 + 时钟（对 DB now()）+ 端点存在性 + 工人身份面连通性
// 期望来源：被测构建点源码（git ls-tree/show）+ 端点契约原文；**不**取自被测读面。
import {
  buildPoint, writeFileSync, outPath, api, psql, one, log, nowCST,
  loginApi, createProbeWorker, loginWorker, probeResidue, LEDGER_TABLES, ledgerHash,
  PROBE_PREFIX, ID_PREFIX, TENANT_ID, WORKER_HEADER,
} from './lib.mjs'

const bp = buildPoint()
log(`构建点: worktree=${bp.worktree} sha=${bp.sha} full=${bp.shaFull}`)
log(`构建点: subject=${bp.subject}`)
log(`构建点: commitTime=${bp.commitTime} adminApiPid=${bp.pid} 进程启动=${bp.adminApiStart}`)
log(`构建点: originMain=${bp.originMain} 采集时刻=${bp.observedAt.cst} / ${bp.observedAt.utc}`)

// ── 时钟自检（铁律 7：一切 +08；对 DB now() at time zone 'Asia/Shanghai'）──
const dbNow = one(`select (now() at time zone 'Asia/Shanghai')::timestamp(0)::text as cst,
                          now()::text as utc_text`)
const nodeNow = nowCST()
const dbBasis = one(`select current_setting('TimeZone') as tz,
                            (now() at time zone 'Asia/Shanghai')::text as cst_full`)
log(`时钟: node=${nodeNow.cst} / db=${dbNow.cst} (+08) / dbTZ=${dbBasis.tz}`)

// 差值（秒）：node 与本机 wall clock 同源，DB 是远端；两者相差应远小于 120s
const deltaSec = Math.abs(new Date(`${dbNow.cst.replace(' ', 'T')}+08:00`).getTime() - Date.now()) / 1000

// ── 端点存在性（**无凭证 ⇒ 必须 401/403**，不得 200 也不得 404/500）──
const unauth = {}
const probe = async (m, p, body) => {
  const r = await api(m, p, { body })
  unauth[`${m} ${p}`] = { status: r.status, code: r.json?.error?.code ?? null }
  return r
}
await probe('GET', '/api/worker/me')
await probe('GET', '/api/worker/production/current-worker')
await probe('GET', '/api/worker/production/scan?token=la00000000000000000000000000000000')
await probe('POST', '/api/worker/production/scan/complete', { token: 'la00000000000000000000000000000000' })
await probe('GET', '/api/worker/production/cutting-height?token=la00000000000000000000000000000000')
await probe('POST', '/api/worker/shipment/recognize', { images: [] })
await probe('POST', '/api/worker/shipment/orders/la00000000000000000000000000000000/pack')
await probe('POST', '/api/worker/inbound/recognize', { images: ['http://x/1.jpg'] })
await probe('POST', '/api/worker/inbound/drafts', { productId: 'la', skuId: 1, quantity: 1 })
await probe('POST', '/api/worker/inbound/drafts/la00000000000000000000000000000000/post', { confirmed: true })
await probe('POST', '/api/worker/session/current')
await probe('GET', '/api/admin/products?page=1&size=1')
log(`无凭证探针: ${JSON.stringify(unauth)}`)

// ── 工人身份面连通性（建探针工人 → 登录 → 读 /api/worker/me）──
const admin = await loginApi()
log(`管理员登录 OK: tenantId=${admin.raw.tenantId ?? admin.raw.tenant_id} user=${admin.raw.username ?? admin.raw.name ?? '?'}`)

const cw = await createProbeWorker(admin.token)
log(`建探针工人: HTTP ${cw.status} id=${cw.workerId} workerNo=${cw.body.workerNo} name=${cw.body.name}`)
writeFileSync(outPath('P0-worker-created.json'), JSON.stringify({
  at: nowCST(), status: cw.status, workerId: cw.workerId, requestBody: cw.body,
  response: cw.raw.json, dbRow: cw.workerId ? psql(`select id, worker_no, nickname, role, status, tenant_id from users where id='${cw.workerId}'`) : null,
}, null, 2))

let loginOk = null
try {
  loginOk = await loginWorker(cw.body.workerNo)
  log(`工人登录 OK: sessionId=${loginOk.sessionId.slice(0, 8)}… worker=${loginOk.workerName} idle=${loginOk.idleMinutes}min`)
} catch (e) {
  log(`工人登录 FAIL: ${e.message}`)
}

let me = null
if (loginOk) {
  me = await api('GET', '/api/worker/me', { headers: { [WORKER_HEADER]: loginOk.sessionId, 'X-Tenant-Id': String(TENANT_ID) } })
  log(`GET /api/worker/me: HTTP ${me.status} body=${JSON.stringify(me.json?.data ?? me.json).slice(0, 300)}`)
}

// 工人 session 行（独立 DB 读数）
const sessRow = loginOk
  ? one(`select id, worker_id, worker_no, worker_name, (idle_expires_at at time zone 'Asia/Shanghai')::text as idle_expires_cst, ended_at, end_reason from worker_sessions where id='${loginOk.sessionId}'`)
  : null

writeFileSync(outPath('P0-env.json'), JSON.stringify({
  buildPoint: bp,
  clock: { node: nodeNow, dbCst: dbNow.cst, dbTz: dbBasis.tz, deltaSec },
  unauthProbes: unauth,
  worker: { created: cw.status, workerId: cw.workerId, workerNo: cw.body.workerNo, name: cw.body.name, loggedIn: !!loginOk, sessionIdPrefix: loginOk?.sessionId?.slice(0, 8) ?? null, me: { status: me?.status ?? null, pages: me?.json?.data?.pages ?? null }, sessionRow: sessRow },
  probePrefix: `${PROBE_PREFIX} / ${ID_PREFIX}`,
  residueAtStart: probeResidue(),
  ledgerHashAtStart: ledgerHash(),
  ledgerTables: LEDGER_TABLES,
}, null, 2))
log(`P0 完成：时钟差 ${deltaSec.toFixed(1)}s；残留(起始)=${JSON.stringify(probeResidue().counts)}`)
process.exit(0)
