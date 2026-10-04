// P1 — 工人身份面：建号 / 登录 / 会话载体 / fail-closed / 越权 / 跨租户
import { writeFileSync, readFileSync, existsSync, outPath } from './lib.mjs'
import {
  Recorder, judge, api, apiWorker, log, nowCST, psql, one, loginApi, loginWorker, createProbeWorker,
  probeWorkerRow, guardedWrite, TENANT_ID, PROBE_PREFIX, ID_PREFIX, PROBE_PIN, WORKER_HEADER,
} from './lib.mjs'

const R = new Recorder('P1-auth.json')
const STORE = outPath('.store.json')
const store = existsSync(STORE) ? JSON.parse(readFileSync(STORE, 'utf8')) : {}
const save = () => writeFileSync(STORE, JSON.stringify(store, null, 2))

// ── 建两个探针工人（真实 API：POST /api/admin/workers）──────────────────
const admin = await loginApi()
for (const tag of ['A', 'B']) {
  const key = `worker${tag}`
  if (store[key]?.workerId) { continue }
  const w = await createProbeWorker(admin.token, { workerNo: `${ID_PREFIX.toUpperCase()}${tag}${String(Date.now()).slice(-5)}` })
  const row = w.workerId ? probeWorkerRow(w.workerId) : null
  store[key] = { workerNo: w.body.workerNo, workerId: w.workerId, name: w.body.name, pin: PROBE_PIN, createdStatus: w.status, row, response: w.raw.json }
  save()
  judge(R, {
    id: `A1.${tag}.create`, name: `建探针工人(${tag})：POST /api/admin/workers`,
    expect: 'HTTP 200 + users 行落库(role=worker,status=active)', actual: `HTTP ${w.status} id=${w.workerId} row=${JSON.stringify(row)}`,
    pass: w.status === 200 && !!w.workerId && row?.role === 'worker' && row?.status === 'active',
    expectSource: 'AdminWorkerController.createWorker + WorkerAdminService（API 建行的终态由 DB 独立复读）',
    evidence: [JSON.stringify(w.body), `DB row: ${JSON.stringify(row)}`],
  })
}

// ── 登录（真实工人登录链）───────────────────────────────────────────────
for (const tag of ['A', 'B']) {
  const w = store[`worker${tag}`]
  if (!w?.workerNo) continue
  const l = await loginWorker(w.workerNo, w.pin)
  const row = one(`select id, worker_id, worker_no, worker_name, ended_at, end_reason,
                          (idle_expires_at at time zone 'Asia/Shanghai')::text as idle_cst
                     from worker_sessions where id='${l.sessionId}'`)
  store[`worker${tag}`].sessionId = l.sessionId
  store[`worker${tag}`].workerName = l.workerName
  save()
  judge(R, {
    id: `A2.${tag}.login`, name: `工人登录(${tag})：POST /api/worker/login`,
    expect: 'HTTP 200 + session_id 32 位 + worker_sessions 行(ended_at IS NULL)',
    actual: `HTTP session=${l.sessionId?.slice(0, 8)}… worker=${l.workerName} idle=${l.idleMinutes}min row=${JSON.stringify(row)}`,
    pass: !!l.sessionId && row?.worker_id === w.workerId && row?.ended_at === null,
    expectSource: 'WorkerSessionService.login + createSession（session 行从 DB 独立复读，不看 API 回执）',
    evidence: [`loginData=${JSON.stringify(l.raw)}`, `DB worker_sessions: ${JSON.stringify(row)}`],
  })
}

const wa = store.workerA
const wb = store.workerB

// ── 身份载体：X-Worker-Session-Id 真的是身份来源吗 ──────────────────────
// 判据：同一次写请求里 body 塞别人的 worker_id/worker_name ⇒ 落库的仍是 session 解出的工人。
const me = await apiWorker('GET', '/api/worker/me', { sessionId: wa.sessionId })
judge(R, {
  id: 'A3.me', name: 'GET /api/worker/me（有效 session）',
  expect: 'HTTP 200 + worker_id == 探针工人 + pages 为数组',
  actual: `HTTP ${me.status} worker_id=${me.json?.data?.worker_id} pages=${JSON.stringify(me.json?.data?.pages)}`,
  pass: me.status === 200 && me.json?.data?.worker_id === wa.workerId && Array.isArray(me.json?.data?.pages),
  expectSource: 'WorkerProfileController.me（worker_id 必须等于 A1 建的工人 id）',
})

const cw = await apiWorker('GET', '/api/worker/production/current-worker', { sessionId: wa.sessionId })
judge(R, {
  id: 'A4.current-worker', name: 'GET /api/worker/production/current-worker',
  expect: 'HTTP 200 + worker_id == 探针工人 + worker_name 与建号一致',
  actual: `HTTP ${cw.status} worker_id=${cw.json?.data?.worker_id} worker_name=${cw.json?.data?.worker_name}`,
  pass: cw.status === 200 && cw.json?.data?.worker_id === wa.workerId && cw.json?.data?.worker_name === wa.name,
  expectSource: 'WorkerSessionService.currentWorker（页头数据源 = 服务端 session）',
})

// ── fail-closed：无效/伪造 session ─────────────────────────────────────
const bogus = 'la' + '0'.repeat(30)
const badSession = await apiWorker('GET', '/api/worker/production/current-worker', { sessionId: bogus })
judge(R, {
  id: 'A5.bogus-session', name: '伪造 worker session（32 位不存在）⇒ 必须 401',
  expect: 'HTTP 401', actual: `HTTP ${badSession.status} ${JSON.stringify(badSession.json?.error)}`,
  pass: badSession.status === 401,
  expectSource: 'WorkerSessionFilter（resolveIdentityOrNull=null ⇒ 不设认证 ⇒ authenticated() 判 401）',
})

const noSession = await apiWorker('GET', '/api/worker/production/current-worker', { sessionId: null })
judge(R, {
  id: 'A6.no-session', name: '无 X-Worker-Session-Id ⇒ 必须 401',
  expect: 'HTTP 401', actual: `HTTP ${noSession.status}`, pass: noSession.status === 401,
  expectSource: 'SecurityConfig: `/api/worker/**` ⇒ authenticated()',
})

// ── 工人 session 不得进管理后台（红线：不给工人商家权限）────────────────
const adminAsWorker = await api('GET', '/api/admin/products?page=1&size=1', { headers: { [WORKER_HEADER]: wa.sessionId, 'X-Tenant-Id': String(TENANT_ID) } })
const adminAsWorkerPost = await api('POST', '/api/admin/workers', { headers: { [WORKER_HEADER]: wa.sessionId, 'X-Tenant-Id': String(TENANT_ID) }, body: { workerNo: 'LAHACK', name: '线A验收越权', pin: '246810' } })
judge(R, {
  id: 'A7.worker-cannot-admin', name: '工人 session 访问 /api/admin/** ⇒ 必须 403（拒绝集合 worker）',
  expect: 'GET 403 且 POST /api/admin/workers 403（两个端点都要拦）',
  actual: `GET=${adminAsWorker.status} POST=${adminAsWorkerPost.status}`,
  pass: adminAsWorker.status === 403 && adminAsWorkerPost.status === 403,
  expectSource: 'SecurityConfig.ADMIN_API_REJECTED_ROLES 含 worker（#4716 C11 红线）',
  evidence: [`GET body=${JSON.stringify(adminAsWorker.json?.error ?? {})}`, `POST body=${JSON.stringify(adminAsWorkerPost.json?.error ?? {})}`],
})

// ── 快速切换工人：旧 session 必须立即失效 ──────────────────────────────
// 驱动事实（源码）：`/api/worker/**` 的准入是 SecurityConfig 的 authenticated()（WorkerSessionFilter 解 session 头）
// ⇒ 「切换」这一步**必须带当前 session 头**，否则请求在门禁处 401、根本到不了控制器
// （实测：不带 ⇒ 401 且旧 session 未被结束 —— 保存该负读数为判据素材，见 A8b）
const swNoHeader = await api('POST', '/api/worker/session/switch', {
  headers: { 'X-Tenant-Id': String(TENANT_ID) },
  body: { workerNo: wb.workerNo, pin: wb.pin, deviceLabel: '线A验收PAD-B', tenantId: TENANT_ID },
})
const sw = await api('POST', '/api/worker/session/switch', {
  headers: { 'X-Tenant-Id': String(TENANT_ID), [WORKER_HEADER]: wa.sessionId },
  body: { workerNo: wb.workerNo, pin: wb.pin, deviceLabel: '线A验收PAD-B', tenantId: TENANT_ID },
})
const swSession = sw.json?.data?.session_id ?? null
const oldAfterSwitch = await apiWorker('GET', '/api/worker/production/current-worker', { sessionId: wa.sessionId })
const swRow = swSession ? one(`select id, end_reason, (ended_at is not null) as ended from worker_sessions where id='${wa.sessionId}'`) : null
judge(R, {
  id: 'A8b.switch-needs-session-header', name: 'session/switch **不带**当前 session 头 ⇒ 门禁 401（认证先行，切换不是免登录入口）',
  expect: 'HTTP 401（不得 200 换号）', actual: `HTTP ${swNoHeader.status} body=${JSON.stringify(swNoHeader.json?.error ?? {})}`,
  pass: swNoHeader.status === 401,
  expectSource: 'SecurityConfig: `/api/worker/**` ⇒ authenticated()；WorkerSessionFilter 是唯一认证来源',
})
judge(R, {
  id: 'A8.switch-invalidates-old', name: 'POST /api/worker/session/switch ⇒ 旧 session 立即失效',
  expect: '切换 HTTP 200 + 旧 session 再用 ⇒ 401 + DB end_reason=switched',
  actual: `switch=${sw.status} newSession=${swSession?.slice(0, 8)}… 旧session再用=${oldAfterSwitch.status} DB=${JSON.stringify(swRow)}（switch body=${JSON.stringify(sw.json?.error ?? sw.json?.data ?? {}).slice(0, 160)}）`,
  pass: sw.status === 200 && oldAfterSwitch.status === 401 && swRow?.end_reason === 'switched',
  expectSource: 'WorkerSessionService.switchWorker（endSession(switched) + 新 session）—— 旧 id 报工必 401（设计 W2）',
  evidence: [`switch body=${JSON.stringify(sw.json?.error ?? sw.json?.data ?? {})}`],
})
if (swSession) { store.workerA.sessionId = swSession; store.workerA.switchedToB = true; save() }

// ── 登出幂等 + 登出后失效 ─────────────────────────────────────────────
const logout1 = await apiWorker('POST', '/api/worker/session/logout', { sessionId: store.workerA.sessionId })
const afterLogout = await apiWorker('GET', '/api/worker/production/current-worker', { sessionId: store.workerA.sessionId })
const logoutRow = one(`select id, end_reason, (ended_at is not null) as ended from worker_sessions where id='${store.workerA.sessionId}'`)
judge(R, {
  id: 'A9.logout', name: 'POST /api/worker/session/logout ⇒ 200 + DB end_reason=logout + 该 session 之后 401',
  expect: 'logout=200 + 之后 current-worker=401 + DB end_reason=logout',
  actual: `logout=${logout1.status} 登出后=${afterLogout.status} DB=${JSON.stringify(logoutRow)}`,
  pass: logout1.status === 200 && afterLogout.status === 401 && logoutRow?.end_reason === 'logout',
  expectSource: 'WorkerSessionService.logout 的 endSession(logout) 由 DB 复读；失效由 WorkerSessionFilter 复读',
})
// ⚠️ 假红（判据缺陷，**不是产品缺陷**，如实登记）：我第一版断言「同一 session 调两次 logout 都 200（幂等）」——
// 实测第二次 401。源码复核：`WorkerAuthController.logout` 本身**无** session 参数校验（body 为空、幂等），
// 但门禁 `/api/worker/**` ⇒ authenticated() 是**先于控制器**的层：session 已在第一次登出时结束
// ⇒ 第二次请求在过滤器处没有认证 ⇒ 401。故「幂等」的适用范围是**控制器/服务层**（重复登出不改首次
// end_reason），**不是**「会话失效后仍可用它调登出」。前端 `api.mjs::logout()` 也是「无论服务端结果如何
// 都清本地」⇒ 产品面无实际影响。判据缺陷已改（上面 A9），此处留档。
const logout2 = await apiWorker('POST', '/api/worker/session/logout', { sessionId: store.workerA.sessionId })
judge(R, {
  id: 'A9b.logout-after-ended', name: '（假红留档）已结束 session 再调 logout ⇒ 401：门禁先于控制器，幂等只到服务层',
  expect: 'HTTP 401（可解释：authenticated() 在控制器之前）', actual: `HTTP ${logout2.status}`,
  pass: logout2.status === 401,
  expectSource: 'SecurityConfig `/api/worker/**` authenticated() + WorkerAuthController.logout（服务层幂等，控制器无 session 校验）',
})

// ── 登录面负例：错误 PIN / 不存在工号 ⇒ 同一 401 同一文案（反枚举）────────
const badPin = await api('POST', '/api/worker/login', { headers: { 'X-Tenant-Id': String(TENANT_ID) }, body: { workerNo: wa.workerNo, pin: '999999', tenantId: TENANT_ID } })
const noSuchWorker = await api('POST', '/api/worker/login', { headers: { 'X-Tenant-Id': String(TENANT_ID) }, body: { workerNo: `${ID_PREFIX.toUpperCase()}NOPE`, pin: '246810', tenantId: TENANT_ID } })
judge(R, {
  id: 'A10.login-enumeration', name: '登录负例：错误 PIN 与不存在工号 ⇒ 同一 401 同一文案（不泄露工号存在性）',
  expect: 'both 401 + message 逐字相同',
  actual: `badPin=${badPin.status}/${badPin.json?.error?.message} noSuch=${noSuchWorker.status}/${noSuchWorker.json?.error?.message}`,
  pass: badPin.status === 401 && noSuchWorker.status === 401 && badPin.json?.error?.message === noSuchWorker.json?.error?.message,
  expectSource: 'WorkerSessionService.login 的四条失败形态统一（"工号或 PIN 不正确"）',
})

// ── 租户判定（🔴 判据修正留档 —— 第一版是**假红**）：──────────────
// 我第一版断言「X-Tenant-Id:21 + 租户20 的 session ⇒ 401」。实测 **200**，源码复核后判**判据缺陷**：
//   · `/api/worker/**` 的门禁是 `authenticated()`，**不**比对头的租户；
//   · 租户由 `WorkerSessionService.loadActiveSession` **只从会话行解出**，并 set 进 TenantContext；
//     `TenantDomainResolver` 只为 `/api/worker/login`（permitAll）解析租户。
// ⇒ 请求头写 21 既不改变租户上下文、也不越权（会话租户是权威）。**真正的判据是跨租户对象访问**，
//   见 P2/P3（用租户 20 的 session 去动租户 21 的对象 ⇒ 必须 4xx/0 命中，不得靠前端）。
const crossTenantSession = await apiWorker('GET', '/api/worker/production/current-worker', { sessionId: wb.sessionId, tenantId: 21 })
judge(R, {
  id: 'A11.header-tenant-not-authority', name: '（判据修正）X-Tenant-Id 与会话租户不一致 ⇒ 200 且 worker 仍来自会话（租户**不由请求头**决定）',
  expect: 'HTTP 200 + worker_id == 会话解出的工人（请求头换租户不是通道）',
  actual: `HTTP ${crossTenantSession.status} worker_id=${crossTenantSession.json?.data?.worker_id} (期望 ${wb.workerId})`,
  pass: crossTenantSession.status === 200 && crossTenantSession.json?.data?.worker_id === wb.workerId,
  expectSource: 'WorkerSessionService.loadActiveSession：租户只来自会话行；TenantDomainResolver 只服务 /api/worker/login',
  evidence: ['假红留档：第一版断言 401 ⇒ 实测 200（判据写错了「租户权威在哪一层」）'],
})

// ── 无租户标识 ⇒ 显式拒绝（不得静默落默认租户）────────────────────────
const noTenant = await api('POST', '/api/worker/login', { body: { workerNo: wb.workerNo, pin: wb.pin } })
judge(R, {
  id: 'A12.login-no-tenant', name: '登录未给租户（无 X-Tenant-Id / 域名 / body.tenantId）⇒ 显式拒绝',
  expect: '4xx（422 校验类），不得 200、不得落入默认租户',
  actual: `HTTP ${noTenant.status} ${JSON.stringify(noTenant.json?.error ?? noTenant.json?.data ?? {}).slice(0, 200)}`,
  pass: noTenant.status >= 400 && noTenant.status < 500,
  expectSource: 'WorkerAuthController.login（tenantId==null ⇒ validationError "无法识别租户"）',
})

// ── 收尾：恢复一个**有效** session（P1 会把两个 session 都结束掉，后续分段需要可用身份）──
try {
  const relog = await loginWorker(wb.workerNo, wb.pin, TENANT_ID, '线A验收PAD-B')
  store.workerB.sessionId = relog.sessionId
  store.workerB.workerName = relog.workerName
  save()
  log(`收尾重登 B: session=${relog.sessionId.slice(0, 8)}…`)
} catch (e) { log(`收尾重登失败（非致命）: ${e.message}`) }

writeFileSync(outPath('P1-auth-summary.json'), JSON.stringify({ at: nowCST(), summary: R.summary(), workers: { A: { id: wa?.workerId, no: wa?.workerNo }, B: { id: wb?.workerId, no: wb?.workerNo } } }, null, 2))
log(`P1 汇总: ${JSON.stringify(R.summary())}`)
process.exit(0)
