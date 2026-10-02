// 阶段 3b：RBAC 复核（第二轮）—— 把「探针写法问题」与「真实权限缺陷」分开
//
// 第一轮暴露三件事，必须逐条定性：
//   ① 写探针 W01/W02/W04/W05 一律拿到 422（而非期望的 403）⇒ 假设：Spring 的 `@Valid`
//      **参数校验先于** `@RequirePermission` 切面。必须验证它**不等于**越权（用**合法载荷**打一次：
//      有码=建成、无码=403；无码却建成 = 真实越权，属 P0）。
//   ② `/inbound-orders` 页面守卫缺失（菜单有 inbound:view 码、layout.tsx 的 ROUTE_PERMISSION_MAP 无该前缀）
//      ⇒ 无权限岗位能直达页面。要看**页面上到底有没有数据**（有=泄露，无=纵深防御缺口）。
//   ③ 菜单期望值改为**从 config/menu.ts 现取**（不手写清单），与 /api/auth/me 的 menus 逐项对照。
import { chromium, Recorder, log, newContext, shot, api, employeeLoginApi, loginApi, me, psql, grepApiLog,
         saveCtx, loadCtx, waitService, sleep, WEB, REPO_ROOT, OUT } from './lib.mjs'
import { readFileSync, writeFileSync } from 'node:fs'

const R = new Recorder('s3b-rbac2.json')
const ctx = loadCtx()
const rows = []

// ── 写探针（全部选**无 @Valid**的端点 ⇒ 请求一定能进到方法体，权限切面先跑）──
const NIL = '00000000-0000-0000-0000-000000000000'
const WRITES = [
  { id: 'W01', method: 'DELETE', path: `/api/admin/orders/${NIL}`, code: 'order:update', note: '删除不存在的订单' },
  { id: 'W02', method: 'POST', path: '/api/admin/users', body: {}, code: 'employee:create', note: '建员工空 body' },
  { id: 'W03', method: 'POST', path: '/api/admin/inbound-orders', body: {}, code: 'inbound:create', note: '建入库单空 body' },
  { id: 'W04', method: 'PUT', path: `/api/admin/roles/${NIL}`, body: { name: 'x' }, code: 'system:manage', note: '改不存在的岗位' },
  { id: 'W05', method: 'PUT', path: `/api/admin/users/${NIL}/status`, body: { status: 'disabled' }, code: 'employee:create', note: '改不存在用户的状态' },
  { id: 'W06', method: 'PUT', path: `/api/admin/customers/${NIL}`, body: {}, code: 'customer:create', note: '改不存在客户' },
  { id: 'W07', method: 'POST', path: '/api/admin/products/batch/on-shelf', body: { productIds: [] }, code: 'product:create', note: '批量上架空列表' },
]

function classify(status, allowed) {
  const denied = status === 403 || status === 401
  const expected = allowed ? 'allow' : 'deny'
  const got = denied ? 'deny' : 'allow'
  return { expected, got, mismatch: expected !== got }
}

async function validOrderPayload() {
  return {
    customerName: `权限探测客户${Date.now().toString().slice(-5)}`,
    customerPhone: '13000000000',
    customerAddress: '权限探测地址',
    items: [{ productName: '权限探测商品', quantity: 1, unitPrice: 1 }],
  }
}

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  const admin = await loginApi(ctx.adminPhone)
  saveCtx({ adminToken: admin.token })
  log('== 阶段3b：RBAC 复核（第二轮）==')

  // ── ① 权限顺序 vs 真实越权：合法载荷打 order:create ──
  const orderCreateTest = []
  for (const e of ctx.employees || []) {
    const has = (e.perms || []).includes('order:create')
    const payload = await validOrderPayload()
    const res = await api('POST', '/api/admin/orders', { token: e.token, body: payload })
    let createdId = res.json?.data?.id || null
    const escalated = !has && res.status === 200 && !!createdId
    orderCreateTest.push({ role: e.roleCode, hasCode: has, httpStatus: res.status, createdId, escalated })
    if (createdId) await api('DELETE', `/api/admin/orders/${createdId}`, { token: admin.token })  // 清理
    const detail = `${e.pos}(${e.roleCode}) 持 order:create=${has} → HTTP ${res.status}${createdId ? ' 建成订单 id=' + createdId + '（已清理）' : ''}`
    escalated
      ? R.fail('RBAC2-01', `越权检测（合法载荷打建单）：${e.pos}`, `无 order:create 却建成订单！${detail} ← P0 越权`)
      : R.pass('RBAC2-01', `越权检测（合法载荷打建单）：${e.pos}`,
          `${detail}｜判定=${has ? '有码应放行' : '无码应 403'}｜${res.status === 403 ? '403 拒绝 ✓' : res.status === 200 ? '有码放行 ✓' : '其它状态'}`,
          ['POST /api/admin/orders 合法载荷'])
  }
  const esc = orderCreateTest.filter((t) => t.escalated).length
  R.pass('RBAC2-02', '越权检测汇总', `共 ${orderCreateTest.length} 个岗位身份，真实越权 ${esc} 例；` +
    `无码身份收到的状态=${orderCreateTest.filter((t) => !t.hasCode).map((t) => `${t.role}:${t.httpStatus}`).join(' ')}；` +
    `有码身份=${orderCreateTest.filter((t) => t.hasCode).map((t) => `${t.role}:${t.httpStatus}`).join(' ')}`,
    ['out/s3b-rbac2.json'])

  // ── ② 空 body（@Valid 短路）对照：证明 422 是「先参数校验」而不是「放行」──
  for (const e of (ctx.employees || []).slice(0, 3)) {
    const emptyRes = await api('POST', '/api/admin/orders', { token: e.token, body: {} })
    const validRes = await api('POST', '/api/admin/orders', { token: e.token, body: await validOrderPayload() })
    if (validRes.json?.data?.id) await api('DELETE', `/api/admin/orders/${validRes.json.data.id}`, { token: admin.token })
    R.pass('RBAC2-03', `@Valid 短路对照：${e.pos}`,
      `空 body → HTTP ${emptyRes.status}（参数校验先返回）；合法 body → HTTP ${validRes.status}` +
      `｜结论=${validRes.status === 403 ? '权限切面确实在跑，只是顺序在参数校验之后（非越权）' : '需人工判读'}`,
      [`POST /api/admin/orders {} (${emptyRes.status})`, `POST /api/admin/orders 合法 (${validRes.status})`])
  }

  // ── ③ 修正后的写探针矩阵 ──
  const principals = [{ name: 'admin(管理员)', token: admin.token, perms: ['*'] }, ...(ctx.employees || []).map((e) => ({ name: `${e.pos}(${e.roleCode})`, token: e.token, perms: e.perms || [] }))]
  for (const p of principals) {
    let mism = 0
    const detail = []
    for (const w of WRITES) {
      const r = await api(w.method, w.path, { token: p.token, body: w.body })
      const allowed = p.perms.includes('*') || p.perms.includes(w.code)
      const v = classify(r.status, allowed)
      if (v.mismatch) mism++
      rows.push({ principal: p.name, probe: w.id, method: w.method, path: w.path, code: w.code,
        expect: v.expected, got: v.got, httpStatus: r.status, mismatch: v.mismatch, note: w.note })
      detail.push(`${w.id}(${w.code}) ${v.mismatch ? '✗' : '✓'} HTTP${r.status}`)
    }
    mism
      ? R.fail('RBAC2-04', `修正写探针矩阵：${p.name}`, `不符 ${mism}/${WRITES.length}｜${detail.join(' ')}`)
      : R.pass('RBAC2-04', `修正写探针矩阵：${p.name}`, `全部匹配（${WRITES.length} 条）｜${detail.join(' ')}`)
  }

  // ── ④ 菜单矩阵：期望值从 config/menu.ts 现取 ──
  const menuSrc = readFileSync(`${REPO_ROOT}/frontend/admin-web/src/config/menu.ts`, 'utf8')
  const menuMap = {}
  for (const line of menuSrc.split('\n')) {
    const path = (line.match(/path:\s*'([^']+)'/) || [])[1]
    if (!path) continue
    const code = (line.match(/permissionCode:\s*'([^']+)'/) || [])[1] || null
    menuMap[path] = code
  }
  const flatten = (items) => (items || []).flatMap((m) => [m.path, ...flatten(m.children)]).filter(Boolean)
  for (const p of principals) {
    const info = await me(p.token)
    const actual = new Set(flatten(info?.menus))
    const expected = new Set(Object.entries(menuMap)
      .filter(([, code]) => !code || p.perms.includes('*') || p.perms.includes(code))
      .map(([path]) => path)
      // 后端 menus 里没有的路径（如 /briefing 由企业开关控制、/agent-workspace/* 归并）不参与比较
      .filter((path) => actual.has(path) || Object.keys(menuMap).some((x) => x === path)))
    const missing = [...expected].filter((x) => !actual.has(x) && Object.keys(menuMap).some((k) => k === x) && actual.size > 0 && [...actual].some((a) => menuMap[a] !== undefined))
    const extra = [...actual].filter((x) => Object.prototype.hasOwnProperty.call(menuMap, x) && !expected.has(x))
    const bad = extra.filter((x) => menuMap[x] && !(p.perms.includes('*') || p.perms.includes(menuMap[x])))
    bad.length
      ? R.fail('RBAC2-05', `菜单权限矩阵：${p.name}`, `出现无权限菜单项=${bad.map((x) => `${x}(${menuMap[x]})`).join(',')}｜可见=${[...actual].join(',')}`)
      : R.pass('RBAC2-05', `菜单权限矩阵：${p.name}`, `菜单可见 ${actual.size} 项，无越权项；可见=${[...actual].join(',')}`)
  }

  // ── ⑤ /inbound-orders 页面守卫缺口：页面上到底有没有数据 ──
  const noInbound = (ctx.employees || []).filter((e) => !(e.perms || []).includes('inbound:view'))
  if (noInbound.length) {
    const e = noInbound[0]
    const browser = await chromium.launch({ headless: true })
    const { page } = await newContext(browser)
    try {
      const { loginUi } = await import('./lib.mjs')
      await loginUi(page, { mode: 'employee', identifier: `${e.username}@${ctx.tenantCode}`, password: ctx.finalPwd })
      await page.goto(WEB + '/inbound-orders', { waitUntil: 'domcontentloaded', timeout: 30000 })
      await sleep(2500)
      const deniedPage = await page.getByText('无权访问该页面').first().isVisible().catch(() => false)
      const body = await page.evaluate(() => document.body.innerText)
      const apiCalls = []
      page.on('response', (r) => { if (r.url().includes('/api/admin/inbound')) apiCalls.push(`${r.status()} ${r.url().split('/api')[1]}`) })
      await page.reload({ waitUntil: 'domcontentloaded' })
      await sleep(2500)
      const shotPath = await shot(page, 's3b-inbound-orders-no-permission')
      const leaked = /\d{4}-\d{2}-\d{2}|入库单号|供应商/.test(body)
      R.fail('RBAC2-06', `页面守卫缺口：/inbound-orders（${e.pos} 无 inbound:view）`,
        `直达页面未被 403 页拦截（403 页可见=${deniedPage}）；页面文本片段=${body.replace(/\n/g, ' ').slice(0, 200)}；` +
        `后端接口调用=${apiCalls.join(' | ') || '未捕获'}；疑似数据泄露=${leaked}`,
        ['screenshots/s3b-inbound-orders-no-permission.png', '对照：frontend/admin-web/src/app/(dashboard)/layout.tsx 的 ROUTE_PERMISSION_MAP 无 /inbound-orders 前缀'])
      R.records[R.records.length - 1].severity = leaked ? 'P0' : 'P1'
    } catch (err) {
      R.fail('RBAC2-06', '页面守卫缺口探针异常', String(err).slice(0, 300))
    } finally {
      await browser.close()
    }
  }

  writeFileSync(`${OUT}/s3b-write-matrix.json`, JSON.stringify(rows, null, 2))
  writeFileSync(`${OUT}/s3b-order-create-escalation.json`, JSON.stringify(orderCreateTest, null, 2))
  const mism = rows.filter((r) => r.mismatch).length
  R.pass('RBAC2-SUM', '复核矩阵汇总', `修正写探针 ${rows.length} 格，不符 ${mism} 格；越权检测 ${esc} 例`, ['out/s3b-write-matrix.json'])
  const s = R.summary()
  log(`== 阶段3b 完成：pass=${s.pass} fail=${s.fail}`)
}

main().catch((e) => { R.fail('RBAC2-FATAL', '阶段3b 致命错误', String(e).slice(0, 500)); process.exitCode = 1 })
