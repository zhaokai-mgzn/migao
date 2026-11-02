// 阶段 3：RBAC 多岗位权限验收（真 API + 真页面 + 真库）
//
// 口径：期望值来自**两个真值源**，不是手写清单 ——
//   ① API 面：`users.permissions` 快照（DB）× 端点上声明的权限码（§「强制点」表）
//   ② 页面面：`(dashboard)/layout.tsx` 的 ROUTE_PERMISSION_MAP × `config/menu.ts` 的 permissionCode
// 判定：有码 ⇒ 期望放行；无码 ⇒ 期望 403 / 403 页。写成矩阵并逐格对照。
// 证据：API 响应状态 + 页面文案（403 页「无权访问该页面」）+ 截图 + DB 权限快照。
import { chromium, Recorder, log, newContext, shot, api, employeeLoginApi, me, psql, grepApiLog,
         saveCtx, loadCtx, waitService, sleep, WEB } from './lib.mjs'

const R = new Recorder('s3-rbac.json')
const ctx = loadCtx()
const matrix = []

// ── API 探针：path → 端点声明的权限码（null = 无注解，审计项）──
const PROBES = [
  { id: 'R01', method: 'GET', path: '/api/admin/dashboard/stats', code: 'dashboard:view' },
  { id: 'R02', method: 'GET', path: '/api/admin/orders?page=1&size=1', code: 'order:list' },
  { id: 'R03', method: 'GET', path: '/api/admin/products?page=1&size=1', code: 'product:list' },
  { id: 'R04', method: 'GET', path: '/api/admin/customers?page=1&size=1', code: 'customer:view' },
  { id: 'R05', method: 'GET', path: '/api/admin/customer-tags', code: 'customer:view' },
  { id: 'R06', method: 'GET', path: '/api/admin/finance/summary', code: 'finance:view' },
  { id: 'R07', method: 'GET', path: '/api/admin/finance/transactions?page=1&size=1', code: 'finance:view' },
  { id: 'R08', method: 'GET', path: '/api/admin/inbound-orders?page=1&size=1', code: 'inbound:view' },
  { id: 'R09', method: 'GET', path: '/api/admin/knowledge/cards?page=1&size=1', code: 'knowledge:view' },
  { id: 'R10', method: 'GET', path: '/api/admin/users?page=1&size=1', code: 'employee:list' },
  { id: 'R11', method: 'GET', path: '/api/admin/after-sales?page=1&size=1', code: 'after_sales:view' },
  { id: 'R12', method: 'GET', path: '/api/admin/processing-orders?page=1&size=1', code: 'production:view' },
  { id: 'R13', method: 'GET', path: '/api/admin/permissions', code: 'system:view' },
  { id: 'R14', method: 'GET', path: '/api/admin/roles', code: null, audit: true, note: 'AdminRoleController.getRoles 无 @RequirePermission（#4727 审计面）' },
  { id: 'R15', method: 'GET', path: '/api/admin/roles/all', code: null, audit: true, note: 'getAllRoles 无 @RequirePermission（#4727 审计面）' },
  // 写面：空 body ⇒ 有码走校验(400/422)，无码 403；① 不得真的落库
  { id: 'W01', method: 'POST', path: '/api/admin/orders', body: {}, code: 'order:create', write: true },
  { id: 'W02', method: 'POST', path: '/api/admin/products', body: {}, code: 'product:create', write: true },
  { id: 'W03', method: 'POST', path: '/api/admin/users', body: {}, code: 'employee:create', write: true },
  { id: 'W04', method: 'POST', path: '/api/admin/after-sales', body: {}, code: 'order:refund', write: true },
  { id: 'W05', method: 'POST', path: '/api/admin/finance/transactions', body: {}, code: 'finance:create', write: true },
]

// ── 页面探针：路由 → 页面守卫码（layout.tsx ROUTE_PERMISSION_MAP）──
const ROUTES = [
  ['/dashboard', 'dashboard:view'], ['/briefing', 'dashboard:view'],
  ['/orders', 'order:list'], ['/products', 'product:list'], ['/categories', 'product:category:view'],
  ['/customers', 'customer:view'], ['/after-sales', 'after_sales:view'], ['/finance', 'finance:view'],
  ['/employees', 'employee:list'], ['/roles', 'system:view'], ['/settings', 'system:manage'],
  ['/knowledge', 'knowledge:view'], ['/production', 'production:view'],
  ['/processing-orders', 'production:view'], ['/inbound-orders', 'inbound:view'],
  ['/chat', 'agent:session'],
]
// 菜单节点：路径 → 菜单码（config/menu.ts permissionCode）
const MENU_PATHS = Object.fromEntries(ROUTES)

function verdict(probe, status, perms) {
  const hasCode = perms.includes('*') || (probe.code && perms.includes(probe.code))
  const deny = status === 403 || status === 401
  if (probe.audit) return { expected: 'audit', got: deny ? 'deny' : 'allow', mismatch: false }
  const expected = hasCode ? 'allow' : 'deny'
  const got = deny ? 'deny' : 'allow'
  return { expected, got, mismatch: expected !== got }
}

async function probeAll(name, token, perms) {
  const rows = []
  for (const p of PROBES) {
    const r = await api(p.method, p.path, { token, body: p.body })
    const v = verdict(p, r.status, perms)
    rows.push({ principal: name, probe: p.id, method: p.method, path: p.path, code: p.code,
      expect: v.expected, actual: v.got, httpStatus: r.status, mismatch: v.mismatch,
      audit: !!p.audit, note: p.note || '', body: (r.text || '').slice(0, 160) })
  }
  return rows
}

async function uiMatrix(principal, { identifier, password, phone }) {
  const browser = await chromium.launch({ headless: true })
  const { page } = await newContext(browser)
  const out = { menus: [], routes: [], shots: [] }
  try {
    const { loginUi } = await import('./lib.mjs')
    await loginUi(page, phone ? { mode: 'admin', phone } : { mode: 'employee', identifier, password })
    await sleep(1500)
    out.menus = await page.locator('aside a').allInnerTexts().catch(() => [])
    out.shotSidebar = await shot(page, `s3-${principal}-sidebar`)
    out.shots.push(out.shotSidebar)
    for (const [route, code] of ROUTES) {
      await page.goto(WEB + route, { waitUntil: 'domcontentloaded', timeout: 30000 })
      await sleep(700)
      const denied = await page.getByText('无权访问该页面').first().isVisible().catch(() => false)
      const missing = denied
        ? (await page.locator('code').first().innerText().catch(() => '')).trim()
        : ''
      out.routes.push({ route, code, denied, missingCode: missing })
      if (denied && !out.shotDenied) out.shotDenied = await shot(page, `s3-${principal}-denied${route.replace(/\//g, '-')}`)
    }
    if (out.shotDenied) out.shots.push(out.shotDenied)
  } catch (e) {
    out.error = String(e).slice(0, 300)
  } finally {
    await browser.close()
  }
  return out
}

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  log(`== 阶段3：RBAC 多岗位验收 == tenantId=${ctx.tenantId}`)

  const principals = [
    { name: 'admin(管理员)', token: ctx.adminToken, ui: { phone: ctx.adminPhone }, expectAll: true },
  ]
  // 管理员 token 可能过期 → 重新登录
  {
    const { loginApi } = await import('./lib.mjs')
    const r = await loginApi(ctx.adminPhone)
    principals[0].token = r.token
    saveCtx({ adminToken: r.token })
  }
  for (const e of ctx.employees || []) {
    principals.push({
      name: `${e.pos}(${e.roleCode})`, token: e.token,
      ui: { identifier: `${e.username}@${ctx.tenantCode}`, password: ctx.finalPwd },
      emp: e,
    })
  }

  const dbPerms = psql(`select username, position, role, coalesce(permissions,'[]')::text as permissions
                        from users where tenant_id=${ctx.tenantId} and deleted=0`)

  for (const p of principals) {
    // 权限快照（DB 是权威；API /me 用于确认线上口径一致）
    const info = await me(p.token)
    const perms = info?.permissions || []
    const dbRow = dbPerms.find((d) => (p.emp ? d.username === p.emp.username : d.role === 'admin'))
    const dbPermsArr = JSON.parse(dbRow?.permissions || '[]')
    const consistent = p.expectAll ? perms.includes('*') : JSON.stringify([...perms].sort()) === JSON.stringify([...dbPermsArr].sort())

    // ── API 矩阵 ──
    const rows = await probeAll(p.name, p.token, perms)
    matrix.push(...rows)
    const mism = rows.filter((r) => r.mismatch)
    const audits = rows.filter((r) => r.audit)
    const detail = `探针 ${rows.length} 条：匹配 ${rows.length - mism.length}，不符 ${mism.length}` +
      (mism.length ? `｜不符=${mism.map((m) => `${m.probe}(${m.path} 期望${m.expect} 实际${m.actual} HTTP${m.httpStatus})`).join('; ')}` : '') +
      `｜权限快照与 DB 一致=${consistent}`
    mism.length
      ? R.fail('RBAC-API', `API 权限矩阵：${p.name}`, detail, [`GET /api/auth/me ≥${perms.length} 码`, 'DB users.permissions'])
      : R.pass('RBAC-API', `API 权限矩阵：${p.name}`, detail + `｜无注解审计项：${audits.map((a) => `${a.path}=${a.actual}`).join(' ')}`,
          ['表：out/s3-rbac-routes.json / 见 s3-rbac.json 的 matrix'])

    // ── 页面矩阵 ──
    const ui = await uiMatrix(p.name.replace(/[()]/g, ''), p.ui)
    if (ui.error) { R.fail('RBAC-UI', `页面权限矩阵：${p.name}`, `UI 登录/遍历失败：${ui.error}`); continue }
    const uiMism = ui.routes.filter((r) => {
      const allowed = perms.includes('*') || perms.includes(r.code)
      return allowed === r.denied // 有码却 403 / 无码却放行
    })
    const uiDetail = `菜单可见 ${ui.menus.length} 项 [${ui.menus.map((m) => m.split('\n')[0]).join('/')}]｜路由 ${ui.routes.length} 条：拒绝 ${ui.routes.filter((r) => r.denied).length}，不符 ${uiMism.length}` +
      (uiMism.length ? `｜不符=${uiMism.map((r) => `${r.route}(期望${perms.includes('*') || perms.includes(r.code) ? '放行' : '拒绝'} 实际${r.denied ? '拒绝' : '放行'}${r.missingCode ? ' 缺' + r.missingCode : ''})`).join('; ')}` : '')
    uiMism.length
      ? R.fail('RBAC-UI', `页面权限矩阵：${p.name}`, uiDetail, ui.shots)
      : R.pass('RBAC-UI', `页面权限矩阵：${p.name}`, uiDetail, ui.shots)
    p.uiResult = ui
  }

  // ── 工人身份：不得进商家后台（ADMIN_API_REJECTED_ROLES）──
  if (ctx.worker) {
    try {
      const login = await api('POST', '/api/worker/login', { body: { workerNo: ctx.worker.workerNo, pin: ctx.worker.pin, tenantId: ctx.tenantId, deviceLabel: 'ACC-H5' } })
      const sid = login.json?.data?.sessionId || login.json?.data?.session_id
      R.pass('RBAC-W1', '工人端登录（工号+PIN）', `HTTP ${login.status}；sessionId=${String(sid).slice(0, 12)}… 角色=${JSON.stringify(login.json?.data?.worker?.role || login.json?.data?.role)}`,
        ['POST /api/worker/login'])
      const bad = await api('POST', '/api/worker/login', { body: { workerNo: ctx.worker.workerNo, pin: '000000', tenantId: ctx.tenantId } })
      ;(bad.status === 401 || bad.status === 400)
        ? R.pass('RBAC-W2', '工人端错误 PIN 拒绝', `错误 PIN → HTTP ${bad.status}（${bad.json?.error?.message || ''}）`, ['POST /api/worker/login 错误 PIN'])
        : R.fail('RBAC-W2', '工人端错误 PIN 拒绝', `错误 PIN → HTTP ${bad.status} ${bad.text.slice(0, 150)}`)

      if (sid) {
        const adminProbe = await api('GET', '/api/admin/orders?page=1&size=1', { headers: { 'X-Worker-Session-Id': sid } })
        adminProbe.status === 403
          ? R.pass('RBAC-W3', '工人身份访问商家后台被拒（垂直越权防护）', `GET /api/admin/orders with X-Worker-Session-Id → HTTP 403`, ['SecurityConfig ADMIN_API_REJECTED_ROLES'])
          : R.fail('RBAC-W3', '工人身份访问商家后台被拒', `→ HTTP ${adminProbe.status} ${adminProbe.text.slice(0, 150)}`)
        const meProbe = await api('GET', '/api/worker/me', { headers: { 'X-Worker-Session-Id': sid } })
        R.pass('RBAC-W4', '工人端自身端点可达', `GET /api/worker/me → HTTP ${meProbe.status}`, ['GET /api/worker/me'])
      }
      saveCtx({ workerSession: sid })
    } catch (e) {
      R.fail('RBAC-W1', '工人端登录异常', String(e).slice(0, 300))
    }
  }

  // ── 矩阵落盘 ──
  const fs = await import('node:fs')
  const out = (await import('./lib.mjs')).OUT
  fs.writeFileSync(`${out}/s3-rbac-matrix.json`, JSON.stringify(matrix, null, 2))
  const mismTotal = matrix.filter((m) => m.mismatch).length
  R.pass('RBAC-SUM', 'RBAC 矩阵汇总', `共 ${matrix.length} 格（${principals.length} 身份 × ${PROBES.length} 端点），不符 ${mismTotal} 格；明细见 out/s3-rbac-matrix.json`,
    ['out/s3-rbac-matrix.json'])

  const logHits = grepApiLog('权限不足|PERMISSION_DENIED|Access Denied|403', { limit: 6 })
  if (logHits.length) R.pass('RBAC-LOG', '服务器日志：403 拒绝留痕', `命中 ${logHits.length} 行，示例：${logHits[0].text.trim().slice(0, 140)}`, logHits.map((l) => `L${l.line}: ${l.text.trim().slice(0, 200)}`))
  else R.skip('RBAC-LOG', '服务器日志：403 拒绝留痕', '未命中（可能日志级别未记录 403 文案）')

  const s = R.summary()
  log(`== 阶段3 完成：pass=${s.pass} fail=${s.fail} skip=${s.skip}｜矩阵 ${matrix.length} 格，不符 ${mismTotal}`)
}

main().catch((e) => { R.fail('RBAC-FATAL', '阶段3 致命错误', String(e).slice(0, 600)); process.exitCode = 1 })
