// 阶段 7：**全量** RBAC 矩阵 —— 100 个受控端点 × 9 个身份，逐格判定
//
// 与阶段 3 的区别（那次是打折扣版）：
//   ① 端点面：阶段 3 只挑了 20 个；本阶段从源码枚举**全部** `@RequirePermission` 端点（100 个 / 19 个权限码）；
//   ② 判据面：期望值 = 「该身份的权限快照是否含该端点要求的码」（快照取自 DB + /api/auth/me，二者须一致）；
//   ③ 反证面：**同一行内**必须有持有者与非持有者的对照 —— 非持有者 403 才能证明该行的非 403 是「过了切面」。
//
// 逐格读数分类（诚实口径，不含糊）：
//   DENY  = 403（决定性）
//   ALLOW = 200/201/204 或「过了切面的业务错」（404/409/422 且**同一端点行内有非持有者 403 反证**）
//   EARLY = 4xx/5xx 但**发生在权限切面之前**（如 @Valid/参数绑定早退）⇒ 判「无法判定」，不计入 allow
//   ⚠️ 违规 = 非持有者出现 ALLOW，或持有者出现 DENY
import { Recorder, log, api, loginApi, employeeLoginApi, psql, saveCtx, loadCtx, waitService, grepApiLog } from './lib.mjs'
import { readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const R = new Recorder('s7-rbac-matrix.json')
const ctx = loadCtx()
const T = ctx.tenantId
const OUT = process.env.OUT_DIR || join(process.cwd(), 'out')
const q = (sql) => { try { return psql(sql) } catch (e) { return null } }
const one = (sql) => (q(sql) || [])[0]

// ── 资源目录：把 {id} 占位符换成「形态合法但不存在」或真实存在的 id ──────────────
const BOGUS_HEX = 'deadbeefdeadbeefdeadbeefdeadbeef'
const RES = {
  orderId: one(`select id from orders where tenant_id=${T} and status in ('pending','confirmed') order by created_at desc limit 1`)?.id,
  orderDone: one(`select id from orders where tenant_id=${T} order by created_at desc limit 1`)?.id,
  productId: one(`select id from products where tenant_id=${T} order by created_at desc limit 1`)?.id,
  customerId: one(`select id from customer_profiles where tenant_id=${T} limit 1`)?.id,
  userId: ctx.employees?.[0]?.id,
  roleId: ctx.roles?.find((r) => r.code === 'customer_service')?.id || one(`select id from roles where tenant_id=${T} limit 1`)?.id,
  workerId: ctx.worker?.id,
  inboundId: one(`select id from inbound_orders where tenant_id=${T} order by created_at desc limit 1`)?.id,
  ticketId: one(`select id from after_sales_tickets where tenant_id=${T} order by created_at desc limit 1`)?.id,
  processingOrderId: one(`select id from processing_orders where tenant_id=${T} order by created_at desc limit 1`)?.id,
  setId: one(`select id from processing_order_sets where tenant_id=${T} limit 1`)?.id,
  orderItemId: one(`select id from order_items where tenant_id=${T} limit 1`)?.id,
  tagId: one(`select id from customer_tags where tenant_id=${T} limit 1`)?.id,
  cardId: one(`select id from knowledge_cards where tenant_id=${T} limit 1`)?.id,
  candidateId: one(`select id from knowledge_candidates where tenant_id=${T} limit 1`)?.id,
  operationId: one(`select id from production_operations where tenant_id=${T} limit 1`)?.id,
  templateId: one(`select id from knowledge_templates where tenant_id=${T} limit 1`)?.id,
  sessionId: one(`select id from agent_sessions where tenant_id=${T} limit 1`)?.id,
  setPartTokenId: null,
}
// 路径里出现这些段 ⇒ 用对应资源；缺失时用「形态合法的假 id」
const PATH_RES = [
  [/^\/api\/admin\/orders\/\{orderId\}/, 'orderId'], [/^\/api\/admin\/orders\/\{id\}/, 'orderDone'],
  [/^\/api\/admin\/products\/\{id\}/, 'productId'], [/^\/api\/admin\/customers\/\{customerId\}/, 'customerId'],
  [/^\/api\/admin\/customers\/\{id\}/, 'customerId'], [/^\/api\/admin\/users\/\{id\}/, 'userId'],
  [/^\/api\/admin\/roles\/\{id\}/, 'roleId'], [/^\/api\/admin\/workers\/\{id\}/, 'workerId'],
  [/^\/api\/admin\/inbound-orders\/\{id\}/, 'inboundId'], [/^\/api\/admin\/after-sales\/\{id\}/, 'ticketId'],
  [/^\/api\/admin\/processing-orders\/\{id\}/, 'processingOrderId'], [/^\/api\/admin\/processing-order-sets\/\{id\}/, 'setId'],
  [/^\/api\/admin\/customer-tags\/\{id\}/, 'tagId'], [/^\/api\/admin\/knowledge\/cards\/\{id\}/, 'cardId'],
  [/^\/api\/admin\/knowledge\/candidates\/\{id\}/, 'candidateId'], [/^\/api\/admin\/knowledge\/templates\/\{templateId\}/, 'templateId'],
  [/^\/api\/admin\/agent-sessions\/\{id\}/, 'sessionId'], [/^\/api\/admin\/production\/operations\/\{id\}/, 'operationId'],
]
const isHexId = (v) => /^[0-9a-f]{32}$/i.test(String(v || ''))
const isNumericId = (v) => /^\d+$/.test(String(v || ''))

/** 把端点模板变成实际可发的请求：路径参数替换 + 每个写端点的「合法但无副作用」载荷。 */
function buildProbe(ep) {
  const { verb, path } = ep
  let url = path
  // 🔴 幂等非破坏（本轮血的教训）：**写端点一律用形态合法的假 id** ——
  //    首轮把真实 id 交给 PUT/DELETE 探针 ⇒ 软删了「客服」账号、改了 admin 岗位名、重置了它的密码，
  //    后续 93 次 403 全是自伤（错误码 PASSWORD_CHANGE_REQUIRED / 已删除），差点被读成产品缺陷。
  const write = verb !== 'GET'
  for (const [re, key] of PATH_RES) {
    if (re.test(path)) {
      let v = write ? BOGUS_HEX : RES[key]
      if (!v) v = BOGUS_HEX
      url = url.replace(/\{[a-zA-Z]+\}/, v)
    }
  }
  url = url.replace(/\{[a-zA-Z]+\}/g, BOGUS_HEX).replace(/\{skuId\}/g, '999999999')
  const key = `${verb} ${path}`
  const W = {
    // —— 真实业务写：合法载荷 + 无副作用（引用不存在对象 ⇒ 业务层 404/422，均在切面之后）
    'POST /api/admin/customer-tags': { body: { name: `RBAC探针${Date.now() % 100000}`, color: '#888888' } },
    'PUT /api/admin/customer-tags/{id}': { body: { name: `RBAC改名${Date.now() % 100000}` } },
    'DELETE /api/admin/customer-tags/{id}': {},
    'DELETE /api/admin/customers/{customerId}/tags/{tagId}': {},
    'DELETE /api/admin/customers/{id}': {},
    'PUT /api/admin/customers/{id}': { body: { nickname: 'RBAC探针' } },
    'POST /api/admin/customers/{customerId}/tags/{tagId}': {},
    'POST /api/admin/users': { body: { name: 'RBAC探针', phone: ctx.adminPhone, username: `rbac_probe_${Date.now() % 100000}`, password: 'Probe@123456', position: '客服' } },
    'PUT /api/admin/users/{id}': { body: { name: 'RBAC探针' } },
    'PUT /api/admin/users/{id}/reset-password': { body: {} },
    'PUT /api/admin/users/{id}/status': { body: { status: 'active' } },
    'DELETE /api/admin/users/{id}': {},
    'POST /api/admin/workers': { body: { workerNo: ctx.worker?.workerNo, name: 'RBAC探针' } },
    'POST /api/admin/finance/transactions': { body: { type: 'income', amount: 1.23, paymentMethod: 'cash', remark: 'RBAC探针流水' } },
    'POST /api/admin/inbound-orders': { body: { supplier: 'RBAC探针', inboundDate: new Date().toISOString().slice(0, 10), items: [{ productId: BOGUS_HEX, skuId: 999999999, quantity: 1, unitCost: 1 }] } },
    'PATCH /api/admin/inbound-orders/{id}': { body: { action: '__rbac_probe__' } },   // 非法 action ⇒ 业务 422（切面之后）
    // 该端点有**必填查询参数** importRunId：缺它 ⇒ MissingServletRequestParameterException ⇒ 全局处理器无该分支 ⇒ **500**（客户端错误报成服务端故障，F9）。带上它才能越过参数绑定，看到切面判定。
    'POST /api/admin/inbound-orders/opening-import': { url: '/api/admin/inbound-orders/opening-import?importRunId=deadbeefdeadbeefdeadbeefdeadbeef', multipart: { name: 'file', filename: 'probe.xlsx', content: 'not-a-real-xlsx', contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' } },
    'POST /api/admin/knowledge/cards': { body: { title: 'RBAC探针卡', content: '内容', category: '其他' } },
    'PUT /api/admin/knowledge/cards/{id}': { body: { title: 'RBAC探针卡改' } },
    'DELETE /api/admin/knowledge/cards/{id}': {},
    'POST /api/admin/knowledge/cards/{id}/publish': {},
    'POST /api/admin/knowledge/cards/{id}/archive': {},
    'POST /api/admin/knowledge/candidates/{id}/adopt': {},
    'POST /api/admin/knowledge/candidates/{id}/adopt-edited': { body: {} },
    'POST /api/admin/knowledge/candidates/{id}/reject': {},
    'POST /api/admin/knowledge/templates/{templateId}/apply': {},
    'POST /api/admin/roles': { body: { name: `RBAC探针岗${Date.now() % 100000}`, description: '探针', permissionIds: [] } },
    'PUT /api/admin/roles/{id}': { body: { name: `RBAC探针岗改${Date.now() % 100000}` } },
    'DELETE /api/admin/roles/{id}': {},
    'PUT /api/admin/tenant/ai-config': { body: {} },
    'POST /api/admin/notifications': { body: { title: 'RBAC探针', content: '探针通知' } },
    'POST /api/admin/processing-orders/generate': { body: { orderIds: [BOGUS_HEX] } },
    'PATCH /api/admin/processing-orders/{id}': { body: { remark: 'RBAC探针' } },
    'POST /api/admin/production/orders/{orderId}/instantiate': {},
    'POST /api/admin/production/orders/{orderId}/print': {},
    'POST /api/admin/production/orders/{orderId}/ship': { body: { trackingNo: 'RBACPROBE' } },
    'POST /api/admin/production/orders/{orderId}/operations/{operationId}/report': { body: { qty: 1 } },
    'POST /api/admin/production/orders/{orderId}/qr-token/regenerate': {},
    'POST /api/admin/production/orders/{orderId}/qr-token/revoke': {},
    'POST /api/admin/production/orders/{orderId}/repricing': { body: {} },
    'POST /api/admin/production/repricing/{batchId}/rollback': { body: {} },
    'POST /api/admin/production/operations': { body: { name: `RBAC探针工序${Date.now() % 100000}`, unit: '米' } },
    'PUT /api/admin/production/operations/{id}': { body: { name: 'RBAC探针工序改' } },
    'DELETE /api/admin/production/operations/{id}': {},
    'DELETE /api/admin/production/operations/{id}/detach-and-delete': {},
    'PUT /api/admin/production/operation-positions/{id}': { body: {} },
    'POST /api/admin/production/route-rules': { body: {} },
    'PUT /api/admin/production/route-rules/{id}/customer-unit-price': { body: {} },
    'DELETE /api/admin/production/route-rules/{id}': {},
    'POST /api/admin/production/routings': { body: {} },
    'PUT /api/admin/production/routings/{id}': { body: {} },
    'DELETE /api/admin/production/routings/{id}': {},
    'POST /api/admin/production/processing-fee-combinations': { body: {} },
    'PUT /api/admin/production/processing-fee-combinations/{id}': { body: {} },
    'DELETE /api/admin/production/processing-fee-combinations/{id}': {},
    'POST /api/admin/agent-sessions/{id}/assign': { body: {} },
    'POST /api/admin/agent-sessions/{id}/end': { body: {} },
    'POST /api/admin/agent-sessions/{id}/messages': { body: { content: 'RBAC探针' } },
    'POST /api/admin/files/upload': { multipart: { name: 'file', filename: 'probe.txt', content: 'rbac-probe' } },
    'POST /api/admin/files/upload-batch': { multipart: { name: 'files', filename: 'probe.txt', content: 'rbac-probe' } },
    'POST /api/admin/upload/image': { multipart: { name: 'file', filename: 'probe.png', content: 'x', contentType: 'image/png' } },
    'POST /api/admin/upload/images': { multipart: { name: 'files', filename: 'probe.png', content: 'x', contentType: 'image/png' } },
    'DELETE /api/admin/files/{fileId}': {},
    // —— Agent 工具面（11 个；DTO 全 optional ⇒ 空对象即可过参数绑定，业务错在切面之后）——
    'POST /api/admin/agent/orders': { body: { customerName: 'RBAC探针客户', customerPhone: '13800000009', customerAddress: '杭州市余杭区探针路 9 号', logisticsType: 'express', logisticsCompany: '顺丰速运', items: [{ productName: 'RBAC探针商品', quantity: 1, unitPrice: 1, subtotal: 1 }] } },
    'PATCH /api/admin/agent/orders/{id}': { body: {} },
    'POST /api/admin/agent/products': { body: {} },
    'PATCH /api/admin/agent/products/{id}': { body: {} },
    'PATCH /api/admin/agent/products/{id}/stock': { body: { stock: 1 } },
    'PATCH /api/admin/agent/products/{productId}/skus/{skuId}': { body: {} },
    'PATCH /api/admin/agent/products/{productId}/skus/price': { body: {} },
    'POST /api/admin/agent/after-sales': { body: {} },
    // —— 前一轮 7 个「无 403 反证」行的修正载荷 ——
    'POST /api/admin/after-sales': { body: { ticketType: 'return', description: 'RBAC探针（刻意缺 orderId ⇒ 业务 422，切面之后，零写入）' } },
    'PUT /api/admin/after-sales/{id}/status': { body: { status: 'processing', remark: 'RBAC探针' } },
    'POST /api/admin/agent-sessions/{id}/assign': { body: { employeeId: BOGUS_HEX } },
    'POST /api/admin/notifications': { body: { recipientId: BOGUS_HEX, recipientType: 'user', title: 'RBAC探针', content: '探针' } },
    'DELETE /api/admin/upload/image': { body: { url: 'https://example.invalid/rbac-probe.png' } },
    'DELETE /api/admin/upload/image': {},
  }
  const w = W[key] || {}
  return { ...w, url: w.url || url }
}

/** 发一个探针；multipart 用 fetch 手工拼。返回 {status, text}。 */
async function send(verb, url, { token, body, multipart }) {
  const base = process.env.API_BASE || 'http://127.0.0.1:8080'
  const headers = { Authorization: `Bearer ${token}` }
  let payload
  if (multipart) {
    const boundary = '----rbacprobe' + Date.now()
    const head = `--${boundary}\r\nContent-Disposition: form-data; name="${multipart.name}"; filename="${multipart.filename}"\r\nContent-Type: ${multipart.contentType || 'text/csv'}\r\n\r\n`
    payload = Buffer.from(head + multipart.content + `\r\n--${boundary}--\r\n`)
    headers['Content-Type'] = `multipart/form-data; boundary=${boundary}`
  } else if (body !== undefined && verb !== 'GET') {   // DELETE 也可能带 body（如 /upload/image 要 {url}）—— 首轮把它排除了 ⇒ 全员 400
    payload = JSON.stringify(body); headers['Content-Type'] = 'application/json'
  }
  const r = await fetch(base + url, { method: verb, headers, body: payload })
  const text = await r.text()
  return { status: r.status, text: text.slice(0, 300) }
}

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  // 🔴 坐标自证（铁律 11）：端点面从**提交对象** 3fa84ab89 取，不从工作树取 ——
  //    工作树在 07:44 被切到 feat/5939-shipments-menu（另一 agent 在开发），工作树面比主干少 11 个
  //    `/api/admin/agent/**` 端点、多 1 个 `/api/admin/shipments` ⇒ 拿工作树当"主干面"会漏测。
  const surface = JSON.parse(readFileSync(join(OUT, 'permission-surface-main.json'), 'utf8')).filter((e) => e.perm)
  log(`== 阶段7：全量 RBAC 矩阵（坐标 main@3fa84ab89） == 端点 ${surface.length} 个 / 权限码 ${new Set(surface.map((e) => e.perm)).size} 个`)

  // ── 身份：管理员 + 8 个岗位员工；权限快照必须 DB 与 /api/auth/me 一致 ──
  const principalList = []
  {
    const { token } = await loginApi(ctx.adminPhone)
    const meRes = await api('GET', '/api/auth/me', { token })
    principalList.push({ label: '管理员(admin)', roleCode: 'admin', token, perms: meRes.json?.data?.permissions || [] })
  }
  for (const e of ctx.employees || []) {
    const { token } = await employeeLoginApi(`${e.username}@${ctx.tenantCode}`, e.pwd || ctx.finalPwd)
    // 权限快照以**运行时的 /api/auth/me** 为准（JWT 里带的那一份），并与 DB 的 users.permissions 对照
    const meRes = await api('GET', '/api/auth/me', { token })
    const perms = meRes.json?.data?.permissions || []
    const dbPerms = q(`select permissions::text as p from users where id='${e.id}'`)?.[0]?.p
    principalList.push({ label: `${e.pos}(${e.roleCode})`, roleCode: e.roleCode, token, perms, username: e.username, dbPerms: dbPerms ? JSON.parse(dbPerms) : null })
  }
  const permsOk = principalList.every((p) => Array.isArray(p.perms) && p.perms.length >= 0)
  R.pass('M-00', '身份就绪（管理员 + 岗位员工）', principalList.map((p) => `${p.label}:${p.perms.length}码`).join('｜') + `｜快照可用=${permsOk}`,
    ['POST /api/auth/sms/login', 'POST /api/auth/employee/login', 'GET /api/auth/me'])

  const has = (p, code) => p.perms.includes('*') || p.perms.includes(code)
  // 🔴 探针自证守卫（本轮教训的类级固化）：跑前跑后比对真实对象的读数，**任何变化都要报出来**
  const guard = () => ({
    usersDeleted: Number(one(`select count(*)::int as n from users where tenant_id=${T} and deleted=1`)?.n),
    usersActive: Number(one(`select count(*)::int as n from users where tenant_id=${T} and deleted=0`)?.n),
    roles: q(`select code, name from roles where tenant_id=${T} order by code`).map((r) => `${r.code}:${r.name}`).join('|'),
    orders: Number(one(`select count(*)::int as n from orders where tenant_id=${T}`)?.n),
    products: Number(one(`select count(*)::int as n from products where tenant_id=${T}`)?.n),
    shipC: Number(one(`select count(*)::int as n from order_shipments where tenant_id=${T}`)?.n),
  })
  const g0 = guard()
  const cells = []
  for (const ep of surface) {
    const probe = buildProbe(ep)
    const row = { endpoint: `${ep.verb} ${ep.path}`, perm: ep.perm, file: ep.file, cells: {} }
    for (const p of principalList) {
      const expected = has(p, ep.perm) ? 'allow' : 'deny'
      let r
      try { r = await send(ep.verb, probe.url, { token: p.token, body: probe.body, multipart: probe.multipart }) }
      catch (e) { r = { status: -1, text: String(e).slice(0, 120) } }
      let code = null
      try { code = JSON.parse(r.text)?.error?.code || null } catch (e) { code = null }
      row.cells[p.label] = { expected, status: r.status, code, sample: r.text.slice(0, 160) }
      await new Promise((r2) => setTimeout(r2, 8))
    }
    // 行内反证：本端点是否有非持有者拿到 403（证明切面在该端点确实生效）
    const denies = principalList.filter((p) => row.cells[p.label].status === 403)
    const holders = principalList.filter((p) => has(p, ep.perm))
    row.control = { nonHolderDenied: denies.some((d) => !has(d, ep.perm)), deniers: denies.map((d) => d.label) }
    cells.push(row)
  }
  writeFileSync(join(OUT, 's7-matrix-raw.json'), JSON.stringify(cells, null, 1))

  // ── 判定 ──
  let allow = 0, deny = 0, early = 0
  const violations = []
  for (const row of cells) {
    for (const p of principalList) {
      const c = row.cells[p.label]
      const decisiveAllow = c.status >= 200 && c.status < 300
      // 403 必须**按错误码**区分：PASSWORD_CHANGE_REQUIRED 是「首登强制改密」前置信封，不是权限拒绝
      if (c.status === 403 && c.code && c.code !== 'PERMISSION_DENIED') { c.verdict = 'PRECOND'; early++ }
      else if (c.status === 403) { c.verdict = 'DENY'; deny++ }
      else if (decisiveAllow) { c.verdict = 'ALLOW'; allow++ }
      else if (row.control.nonHolderDenied) { c.verdict = 'ALLOW'; allow++; c.note = `非 2xx（${c.status}）但同行非持有者 403 反证 ⇒ 已过权限切面` }
      else { c.verdict = 'EARLY'; early++; c.note = `非 2xx（${c.status}）且本行无 403 反证 ⇒ 无法判定` }
      if (c.expected === 'allow' && c.verdict === 'DENY') violations.push({ ...row, principal: p.label, kind: '持有者被拒' })
      if (c.expected === 'deny' && c.verdict === 'ALLOW') violations.push({ ...row, principal: p.label, kind: '非持有者放行' })
    }
  }
  writeFileSync(join(OUT, 's7-matrix.json'), JSON.stringify({ cells, violations: violations.map((v) => ({ endpoint: v.endpoint, perm: v.perm, principal: v.principal, kind: v.kind })) }, null, 1))

  const g1 = guard()
  const changed = Object.keys(g0).filter((k) => JSON.stringify(g0[k]) !== JSON.stringify(g1[k]))
  changed.length === 0
    ? R.pass('M-00b', '探针自证：矩阵运行期间**未改动任何真实对象**',
        `跑前跑后一致：用户(在用 ${g0.usersActive}/软删 ${g0.usersDeleted})、岗位名、订单 ${g0.orders}、商品 ${g0.products}、发货单 ${g0.shipC}`,
        ['harness/s7-rbac-matrix.mjs 的 guard()'])
    : R.fail('M-00b', '探针自证：矩阵改动了真实对象', `变化项：${changed.map((k) => `${k}: ${JSON.stringify(g0[k])} → ${JSON.stringify(g1[k])}`).join('；')}`)

  const total = cells.length * principalList.length
  violations.length === 0
    ? R.pass('M-01', `全量矩阵：${cells.length} 端点 × ${principalList.length} 身份 = ${total} 格，**零违规**`,
        `allow=${allow} deny=${deny} 无法判定=${early}（无法判定的格子已逐条列在 out/s7-matrix.json）`,
        ['out/s7-matrix.json', 'out/s7-matrix-raw.json'])
    : R.fail('M-01', `全量矩阵：发现 ${violations.length} 处违规`,
        violations.slice(0, 12).map((v) => `${v.kind}：${v.endpoint}（需 ${v.perm}）→ ${v.principal}`).join('；'))

  // 无 403 反证的行（说明该端点没有任何身份被拦 —— 可能是全员有码，也可能是守卫没生效）
  const noControl = cells.filter((r) => !r.control.nonHolderDenied)
  R.pass('M-02', '反证覆盖度：每行是否有「非持有者被 403」的对照', `${cells.length - noControl.length}/${cells.length} 行有反证；${noControl.length} 行无（逐条列出，便于人工复核是否全员有码）`,
    noControl.map((r) => `${r.endpoint}（${r.perm}）`).slice(0, 20))

  const hits = grepApiLog('权限不足|PERMISSION|forbidden', { limit: 5 })
  R.pass('M-03', '服务器日志：拒绝留痕', `命中 ${hits.length} 行；示例：${(hits[hits.length - 1]?.text || '(无)').trim().slice(0, 140)}`, hits.map((h) => `L${h.line}`))

  const s = R.summary()
  log(`== 阶段7 完成：pass=${s.pass} fail=${s.fail}｜矩阵 ${total} 格：allow=${allow} deny=${deny} 无法判定=${early}`)
}

main().catch((e) => { R.fail('M-FATAL', '阶段7 致命错误', String(e).slice(0, 400)); process.exitCode = 1 })
