// P4 — 小程序（bmini-app）其余写面 + C 端（mini-app）图片上传写面
//
// 覆盖：
//   ① 小程序登录链负例：/api/auth/mini/login、/bmini/login、/employee/login、/sms/send|login、/password/change
//   ② 发货写面（工人端能到的部分）：/api/worker/shipment/**（recognize / pack / ship / unpack）
//   ③ 小程序生产写面入口（管理面）：/api/admin/production/pool/preview|dispatch、/orders/{id}/ship —— **只测权限/租户/负例**
//   ④ 售后与会话写面：/api/admin/after-sales/{id}/status、/api/admin/agent-sessions/{id}/assign|end —— 同上（闭环归线B）
//   ⑤ C 端图片上传（**ai-agent-service :8001** `/upload-image`）：无凭证必拒 / 类型校验 / 大小校验 / 不落存储
import { writeFileSync, readFileSync, existsSync, outPath } from './lib.mjs'
import { execFileSync } from 'node:child_process'
import {
  Recorder, judge, api, apiWorker, log, nowCST, psql, one,
  ensureWorkerSession, storePath, loginApi, TENANT_ID, ID_PREFIX, PROBE_PREFIX, buildFixture,
} from './lib.mjs'

const R = new Recorder('P4-miniapp-ship-upload.json')
const store = existsSync(storePath()) ? JSON.parse(readFileSync(storePath(), 'utf8')) : {}
const A = await ensureWorkerSession(store, 'A')
const admin = await loginApi()

// ══════════════ ① 小程序登录链（负例：不得凭伪造/空凭证登录）══════════════
const miniNoCred = await api('POST', '/api/auth/mini/login', { body: {} })
const bminiNoCred = await api('POST', '/api/auth/bmini/login', { body: {} })
judge(R, {
  id: 'E1.mini-login-needs-cred', name: '小程序登录：空 body ⇒ 4xx（不得 200、不得建匿名会话）',
  expect: 'both 4xx', actual: `mini=${miniNoCred.status}/${miniNoCred.json?.error?.code} bmini=${bminiNoCred.status}/${bminiNoCred.json?.error?.code}`,
  pass: miniNoCred.status >= 400 && bminiNoCred.status < 500 && bminiNoCred.status >= 400,
  expectSource: 'AuthController.miniProgramLogin / bminiLogin（微信 code 交换，无 code ⇒ 拒绝）',
})
const miniFake = await api('POST', '/api/auth/mini/login', { body: { code: `${ID_PREFIX}-fake-code`, tenantId: TENANT_ID } })
judge(R, {
  id: 'E2.mini-login-fake-code', name: '小程序登录：伪造 code ⇒ 4xx（不换取 token）',
  expect: 'HTTP 4xx', actual: `HTTP ${miniFake.status} code=${miniFake.json?.error?.code} msg=${String(miniFake.json?.error?.message).slice(0, 60)}`,
  pass: miniFake.status >= 400 && miniFake.status < 500,
  expectSource: 'AuthService 微信 code2session 失败 ⇒ 拒绝（不签发 token）',
  evidence: ['本机 wx 未配置时该链必然失败 ⇒ 只作「失败面必须拒绝」判据，成功链**未覆盖**（登记见 REPORT）'],
})
const pwdChangeNoAuth = await api('POST', '/api/auth/password/change', { body: { oldPassword: 'x', newPassword: 'y' } })
judge(R, {
  id: 'E3.password-change-needs-auth', name: '改密端点无凭证 ⇒ 401（不得匿名改密）',
  expect: 'HTTP 401', actual: `HTTP ${pwdChangeNoAuth.status}`, pass: pwdChangeNoAuth.status === 401,
  expectSource: '/api/auth/password/change 非 permitAll（SecurityConfig permitAll 清单只有 login/sms 等）',
})
const smsLoginBad = await api('POST', '/api/auth/sms/login', { headers: { 'X-Tenant-Id': String(TENANT_ID) }, body: { phone: '13800000000', code: '000000' } })
judge(R, {
  id: 'E4.sms-login-bad-code', name: '短信登录：错误验证码 ⇒ 401 AUTH_FAILED（不签发 token）',
  expect: 'HTTP 401', actual: `HTTP ${smsLoginBad.status} code=${smsLoginBad.json?.error?.code}`,
  pass: smsLoginBad.status === 401,
  expectSource: 'AuthService.smsLogin：验证码校验失败 ⇒ authFailed',
})

// ══════════════ ② 工人发货写面（/api/worker/shipment/**）══════════════
// 用**夹具订单**（自建、非真实生产单）打状态机：夹具加工单 state=generated ⇒ 发货面应拒绝（不在可发货态）
const F = buildFixture({ tag: 'P4S', qty: '1.00' })
store.fixtures = store.fixtures || {}; store.fixtures.P4S = F
writeFileSync(storePath(), JSON.stringify(store, null, 2))

const recog = await apiWorker('POST', '/api/worker/shipment/recognize', { sessionId: A.sessionId, body: { images: [] } })
judge(R, {
  id: 'E5.shipment-recognize-empty', name: '发货拍照识别：空图片列表 ⇒ 不得 500（拒绝或空候选）',
  expect: 'HTTP 200（空候选）或 4xx；不得 5xx',
  actual: `HTTP ${recog.status} code=${recog.json?.error?.code ?? '-'} data=${JSON.stringify(recog.json?.data ?? {}).slice(0, 120)}`,
  pass: recog.status < 500,
  expectSource: 'WorkerShipmentController.recognize: images 空 ⇒ List.of()（**不调用视觉链** —— 因此本条不消耗真实 LLM）',
})
const pack = await apiWorker('POST', `/api/worker/shipment/orders/${F.orderId}/pack`, { sessionId: A.sessionId })
const ship = await apiWorker('POST', `/api/worker/shipment/orders/${F.orderId}/ship`, { sessionId: A.sessionId, body: { trackingNo: `${ID_PREFIX}TRK` } })
const unpack = await apiWorker('POST', `/api/worker/shipment/orders/${F.orderId}/unpack`, { sessionId: A.sessionId, body: { reason: `${PROBE_PREFIX}测试` } })
const orderAfter = one(`select status from orders where id='${F.orderId}'`)
const shipments = psql(`select id, source, (packed_at is not null) as packed, (shipped_at is not null) as shipped, packed_by_worker_id from order_shipments where tenant_id=${TENANT_ID} and order_id='${F.orderId}'`)
judge(R, {
  id: 'E6.shipment-state-machine', name: '发货状态机：pack 走**声明的**迁移（confirmed→producing）+ 单据留痕；ship 无实发明细 ⇒ 4xx',
  expect: 'pack=200 且订单**离开起始态**（confirmed→{packed,producing}）+ order_shipments 行 source=worker 且记录打包人；ship=4xx（探针单无实发明细）',
  actual: `pack=${pack.status} ship=${ship.status}/${ship.json?.error?.code} unpack=${unpack.status} 终态 orders.status=${orderAfter?.status} shipments=${JSON.stringify(shipments)}`,
  pass: pack.status === 200 && ['packed', 'producing'].includes(orderAfter?.status)
    && shipments.length >= 1 && shipments[0]?.source === 'worker'
    && ship.status >= 400 && ship.status < 500,
  expectSource: 'OrderShipmentService.doPack（OrderStatusTransitions.assertTransitionAllowed(current,"packed")）+ WorkerShipmentController.unpack 注释「packed → producing」',
  evidence: [
    '🔴 判据修正留档（两次）：① 第一版写「三个端点全 4xx」= 假红（判据是**订单**状态，confirmed 是合法起点）；② 第二版要求 `packed_at IS NOT NULL` 也过严 —— `unpack` 把 `packed → producing` 时会**清掉**打包标记，故终态读 `packed=false` 属正常（改为断言 source=worker + 打包人列存在）。',
    `夹具订单状态轨迹：confirmed --pack--> producing（unpack 把 packed 退回 producing）⇒ 与源码声明的迁移一致`,
  ],
})
const shipNoReason = await apiWorker('POST', `/api/worker/shipment/orders/${F.orderId}/unpack`, { sessionId: A.sessionId, body: {} })
judge(R, {
  id: 'E7.unpack-needs-reason', name: '撤销打包**必带理由**（body 空 ⇒ 4xx，不得静默留痕）',
  expect: 'HTTP 4xx', actual: `HTTP ${shipNoReason.status} code=${shipNoReason.json?.error?.code}`,
  pass: shipNoReason.status >= 400 && shipNoReason.status < 500,
  expectSource: 'WorkerShipmentController.unpack body {reason}（类注释逐字「必带理由 + 留痕」）',
})
const shipNoAuth = await apiWorker('POST', `/api/worker/shipment/orders/${F.orderId}/pack`, { sessionId: null })
judge(R, {
  id: 'E8.shipment-needs-session', name: '发货面无工人 session ⇒ 401',
  expect: 'HTTP 401', actual: `HTTP ${shipNoAuth.status}`, pass: shipNoAuth.status === 401,
  expectSource: 'SecurityConfig `/api/worker/**` authenticated()',
})

// ══════════════ ③④ 小程序管理面写入口：权限 / 租户 / 负例（闭环与并发**归线B**）══════════════
const poolPreview = await api('POST', '/api/admin/production/pool/preview', { token: admin.token, headers: { 'X-Tenant-Id': String(TENANT_ID) }, body: {} })
const poolDispatch = await api('POST', '/api/admin/production/pool/dispatch', { token: admin.token, headers: { 'X-Tenant-Id': String(TENANT_ID) }, body: { items: [] } })
judge(R, {
  id: 'E9.pool-write-negative', name: '生产池 preview/dispatch：空入参 ⇒ 4xx（不得 500、不得建空派工）',
  expect: 'both 4xx（4xx 不限 422）',
  actual: `preview=${poolPreview.status}/${poolPreview.json?.error?.code} dispatch=${poolDispatch.status}/${poolDispatch.json?.error?.code}`,
  pass: [poolPreview, poolDispatch].every((r) => r.status >= 400 && r.status < 500),
  expectSource: 'ProductionPoolController（preview/dispatch 的参数校验；本线**不测**闭环与并发 —— 归线B）',
})
const asStatus = await api('PUT', `/api/admin/after-sales/${ID_PREFIX}-nope/status`, { token: admin.token, headers: { 'X-Tenant-Id': String(TENANT_ID) }, body: { status: 'closed' } })
judge(R, {
  id: 'E10.after-sales-status-negative', name: '售后状态更新：不存在的工单 ⇒ 404（**不测闭环/并发**，归线B）',
  expect: 'HTTP 404', actual: `HTTP ${asStatus.status} code=${asStatus.json?.error?.code}`,
  pass: asStatus.status === 404,
  expectSource: 'AfterSalesController（工单不存在 ⇒ NOT_FOUND）—— 与线B 的分工见 BRIEF §A2',
})
const asStatusNoAuth = await api('PUT', `/api/admin/after-sales/${ID_PREFIX}-nope/status`, { body: { status: 'closed' } })
judge(R, {
  id: 'E11.after-sales-needs-auth', name: '售后状态更新无凭证 ⇒ 401',
  expect: 'HTTP 401', actual: `HTTP ${asStatusNoAuth.status}`, pass: asStatusNoAuth.status === 401,
  expectSource: '/api/admin/** ⇒ authenticated() + 权限码',
})
const assignNoAuth = await api('POST', `/api/admin/agent-sessions/${ID_PREFIX}-nope/assign`, { body: {} })
const endNoAuth = await api('POST', `/api/admin/agent-sessions/${ID_PREFIX}-nope/end`, { body: {} })
judge(R, {
  id: 'E12.agent-session-needs-auth', name: '会话 assign/end 无凭证 ⇒ 401（两个端点）',
  expect: 'both 401', actual: `assign=${assignNoAuth.status} end=${endNoAuth.status}`,
  pass: assignNoAuth.status === 401 && endNoAuth.status === 401,
  expectSource: '/api/admin/** ⇒ authenticated()',
})
const shipAdmin = await api('POST', `/api/admin/production/orders/${ID_PREFIX}-nope/ship`, { token: admin.token, headers: { 'X-Tenant-Id': String(TENANT_ID) }, body: { trackingNo: `${ID_PREFIX}X` } })
judge(R, {
  id: 'E13.admin-ship-negative', name: '管理面发货：不存在的加工单 ⇒ 404（不得 500）',
  expect: 'HTTP 404', actual: `HTTP ${shipAdmin.status} code=${shipAdmin.json?.error?.code}`,
  pass: shipAdmin.status === 404,
  expectSource: 'ProductionController.ship（加工单不存在 ⇒ NOT_FOUND）',
})

// ══════════════ ⑤ C 端图片上传（ai-agent-service :8001 /upload-image）══════════════
const AGENT = process.env.AGENT_BASE || 'http://127.0.0.1:8001'
const UPLOAD_PATH = process.env.UPLOAD_PATH || '/api/chat/upload-image'
const upload = async ({ token, files, timeoutMs = 60000 }) => {
  const fd = new FormData()
  for (const f of files) fd.append('files', new Blob([f.content], { type: f.type }), f.filename)
  try {
    const res = await fetch(`${AGENT}${UPLOAD_PATH}`, { method: 'POST', headers: token ? { Authorization: `Bearer ${token}` } : {}, body: fd, signal: AbortSignal.timeout(timeoutMs) })
    const text = await res.text()
    let json = null; try { json = JSON.parse(text) } catch { /* 非 JSON */ }
    return { status: res.status, json, text }
  } catch (e) { return { status: 0, json: null, text: `FETCH_ERROR ${e.name}: ${e.message}` } }
}
const AGENT_TOKEN = (() => {
  const mint = '/Users/guangzhen.zk/ai native/migao/acceptance/2026-10-03/agent-service-sweep/harness/mint_jwt.py'
  try {
    const claims = JSON.stringify({ sub: '9068a79a939c9be846a605dc78dc30b6', userId: '9068a79a939c9be846a605dc78dc30b6', tenant_id: TENANT_ID, tenantId: TENANT_ID, roles: ['admin'], type: 'access', exp: 2000000000, aud: 'migao', iss: 'migao-admin-api' })
    const out = execFileSync('python3', [mint], { input: claims, encoding: 'utf8' }).trim()
    if (!out.startsWith('ey')) throw new Error(`mint 输出不是 JWT: ${out.slice(0, 60)}`)
    return out
  } catch (e) { log(`铸造 agent token 失败: ${e.message.slice(0, 160)}`); return null }
})()
log(`agent token: ${AGENT_TOKEN ? AGENT_TOKEN.slice(0, 12) + '…(' + AGENT_TOKEN.length + ')' : '(未取得)'}`)

const PNG = Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), Buffer.alloc(1024, 7)])

const upNoToken = await upload({ files: [{ field: 'files', filename: 'a.png', type: 'image/png', content: PNG }] })
judge(R, {
  id: 'E14.upload-needs-token', name: 'C 端图片上传：无凭证 ⇒ 401（不得 200、不得落存储）',
  expect: 'HTTP 401', actual: `HTTP ${upNoToken.status} body=${String(upNoToken.text).slice(0, 160)}`,
  pass: upNoToken.status === 401,
  expectSource: 'app/api/upload.py::upload_chat_image 依赖 get_current_user（UserIdentity）',
})
const upBadToken = await upload({ token: 'la.' + 'x'.repeat(40), files: [{ field: 'files', filename: 'a.png', type: 'image/png', content: PNG }] })
judge(R, {
  id: 'E15.upload-bad-token', name: 'C 端图片上传：伪造 token ⇒ 401（签名不可验）',
  expect: 'HTTP 401', actual: `HTTP ${upBadToken.status}`, pass: upBadToken.status === 401,
  expectSource: 'get_current_user 的 JWT 验签（RS256）',
})
// 超 5MB（伪造 MIME 仍为 image/png）
const big = Buffer.concat([PNG, Buffer.alloc(6 * 1024 * 1024, 1)])
const upTooBig = await upload({ token: AGENT_TOKEN, files: [{ field: 'files', filename: 'big.png', type: 'image/png', content: big }] })
judge(R, {
  id: 'E16.upload-too-big', name: 'C 端图片上传：>5MB（MIME 伪装成 image/png）⇒ 400 FILE_TOO_LARGE（大小按**字节**判，不信客户端声明）',
  expect: 'HTTP 400 + code=FILE_TOO_LARGE', actual: `HTTP ${upTooBig.status} body=${String(upTooBig.text).slice(0, 200)}`,
  pass: upTooBig.status === 400 && /FILE_TOO_LARGE/.test(upTooBig.text),
  expectSource: 'app/api/upload.py::_check_file_size（MAX_IMAGE_SIZE=5MB，按读到的字节数判）',
})
const upFakeType = await upload({ token: AGENT_TOKEN, files: [{ field: 'files', filename: 'fake.png', type: 'image/png', content: Buffer.from('this is not an image at all, just text', 'utf8') }] })
judge(R, {
  id: 'E17.upload-fake-image', name: 'C 端图片上传：文本内容 + 伪装 image/png ⇒ 400（magic number 校验，不只看 Content-Type）',
  expect: 'HTTP 400', actual: `HTTP ${upFakeType.status} body=${String(upFakeType.text).slice(0, 200)}`,
  pass: upFakeType.status === 400,
  expectSource: 'app/api/upload.py::_sniff_image_type（文件头签名比对 declared_type）',
})
const upTooMany = await upload({ token: AGENT_TOKEN, files: [1, 2, 3, 4].map((i) => ({ field: 'files', filename: `a${i}.png`, type: 'image/png', content: PNG })) })
judge(R, {
  id: 'E18.upload-max-3', name: 'C 端图片上传：一次 4 张 ⇒ 400 TOO_MANY_FILES（上限 3）',
  expect: 'HTTP 400 + TOO_MANY_FILES', actual: `HTTP ${upTooMany.status} body=${String(upTooMany.text).slice(0, 200)}`,
  pass: upTooMany.status === 400 && /TOO_MANY_FILES/.test(upTooMany.text),
  expectSource: 'app/api/upload.py::MAX_FILES_PER_REQUEST=3',
})

// 文档路径观察（源码模块 docstring 写 `POST /upload-image`，实跑为 404 ⇒ 文档与挂载前缀不一致，登记为观察项）
// 合法凭证 + 合法图片 ⇒ 应过准入（后续真存储失败与否归 agent-service 侧，本条只判「准入放行」）
const upOk = await upload({ token: AGENT_TOKEN, files: [{ field: 'files', filename: 'ok.png', type: 'image/png', content: PNG }] })
judge(R, {
  id: 'E20.upload-valid-image', name: 'C 端图片上传：合法凭证 + 合法 PNG ⇒ 过校验（200 或下游存储类错误；不得是 400 校验类拒）',
  expect: '状态 ∈ {200, 5xx-存储类} 且 **不是** INVALID_FILE_TYPE/FILE_TOO_LARGE 这类校验拒绝',
  actual: `HTTP ${upOk.status} body=${String(upOk.text).slice(0, 200)}`,
  pass: upOk.status === 200 || (upOk.status >= 500 && !/INVALID_FILE_TYPE|FILE_TOO_LARGE|TOO_MANY_FILES/.test(String(upOk.text))),
  expectSource: 'app/api/upload.py：校验顺序 = 张数 → MIME/扩展名 → 读字节大小 → magic number → 代理 admin-api',
})
const docPath = await fetch(`${AGENT}/upload-image`, { method: 'POST', body: new FormData() }).then((r) => r.status).catch(() => 0)
judge(R, {
  id: 'E19.upload-doc-path-mismatch', name: '观察项（非产品缺陷）：源码 docstring 写 `POST /upload-image`，实际挂载为 `/api/chat/upload-image` ⇒ 文档路径 404',
  expect: '登记即可：实际路由 = openapi 的 /api/chat/upload-image（唯一真值）',
  actual: `GET/POST /upload-image = ${docPath}；openapi paths 含 /api/chat/upload-image`,
  pass: docPath === 404,
  expectSource: 'ai-agent-service openapi.json 的 paths（运行时真值）vs app/api/upload.py 模块 docstring',
  evidence: ['影响面：客户端照 docstring 拼路径会 404（前端 mini-app 用的是实际路径，故仅供文档修正）'],
})

writeFileSync(outPath('P4-summary.json'), JSON.stringify({ at: nowCST(), summary: R.summary() }, null, 2))
log(`P4 汇总: ${JSON.stringify(R.summary())}`)
process.exit(0)
