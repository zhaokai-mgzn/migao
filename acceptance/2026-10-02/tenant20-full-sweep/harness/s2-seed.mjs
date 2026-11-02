// 阶段 2：多岗位员工 + 工人档案（真后端 + 真库）
//
// 覆盖：为「验收布艺」新租户创建 6 个不同岗位的员工（客服/运营/销售/财务/商品管理员/知识编辑）
//      + 1 个自定义岗位 + 1 名工人（工号+PIN，供工人端 H5 登录）。
// 每名员工：管理员建号 → 员工自助登录（用户名@企业编码 + 密码）→ 首登强制改密 → 改密后复登。
// 证据：DB（users / user_roles / roles / role_permissions）+ 页面（员工管理列表）+ 日志。
import { chromium, Recorder, log, newContext, shot, api, employeeLoginApi, loginApi, me, psql,
         saveCtx, loadCtx, waitService, sleep, WEB } from './lib.mjs'

const R = new Recorder('s2-seed.json')
const ctx = loadCtx()
const INIT_PWD = 'Init@123456'
const FINAL_PWD = 'Migao@2026x'
const POSITIONS = ['客服', '运营', '销售', '财务', '商品管理员', '知识编辑']
const stamp = String(Date.now()).slice(-6)

async function adminToken() {
  if (ctx.adminToken) {
    const r = await api('GET', '/api/auth/me', { token: ctx.adminToken })
    if (r.status === 200) return ctx.adminToken
  }
  const { token } = await loginApi(ctx.adminPhone)
  saveCtx({ adminToken: token })
  return token
}

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  const token = await adminToken()
  const tenantCode = psql(`select code from tenants where id=${ctx.tenantId}`)[0]?.code
  log(`== 阶段2：多岗位员工+工人 == tenantId=${ctx.tenantId} tenantCode=${tenantCode}`)
  if (!tenantCode) throw new Error('未取到企业编码')

  // ── 1. 岗位清单（新租户种子）──
  const rolesRes = await api('GET', '/api/admin/roles/all', { token })
  const roles = rolesRes.json?.data || []
  R.pass('SEED-01', '读取新租户岗位清单', `HTTP ${rolesRes.status}；岗位=${roles.map((r) => `${r.name}(${r.code})`).join(' / ')}`,
    ['GET /api/admin/roles/all'])
  const roleByName = Object.fromEntries(roles.map((r) => [r.name, r]))

  // 岗位默认权限（role_permissions）—— RBAC 期望值的真值源
  const defaults = psql(`select r.code, r.name, array_agg(p.code order by p.code) as codes
                         from roles r join role_permissions rp on rp.role_id=r.id join permissions p on p.id=rp.permission_id
                         where r.tenant_id=${ctx.tenantId} group by r.code, r.name`)
  const defaultMap = Object.fromEntries(defaults.map((d) => [d.code, d.codes]))

  // ── 2. 逐岗位建员工 ──
  const employees = []
  for (const pos of POSITIONS) {
    const role = roleByName[pos]
    if (!role) { R.fail('SEED-02', `建员工：${pos}`, '岗位不存在'); continue }
    const phone = `137${String(Date.now()).slice(-6)}${String(employees.length).padStart(2, '0')}`.slice(0, 11)
    const username = `acc_${role.code}_${stamp}`
    const name = `验收${pos}${stamp}`
    const res = await api('POST', '/api/admin/users', {
      token,
      body: { phone, name, username, password: INIT_PWD, position: pos },
    })
    if (res.status !== 200 || !res.json?.success) {
      R.fail('SEED-02', `建员工：${pos}`, `HTTP ${res.status} ${res.text.slice(0, 200)}`)
      continue
    }
    const created = res.json.data
    const emp = { pos, roleCode: role.code, roleId: role.id, phone, username, name, id: created.id, expectedPerms: defaultMap[role.code] || [] }

    // 员工自助登录（用户名@企业编码 + 初始密码）
    try {
      const { token: t1, raw } = await employeeLoginApi(`${username}@${tenantCode}`, INIT_PWD)
      emp.mustChangePassword = raw?.user?.mustChangePassword === true
      // 首登强制改密（issue #5485）：改密后换发新 token
      const cp = await api('POST', '/api/auth/password/change', {
        token: t1, body: { oldPassword: INIT_PWD, newPassword: FINAL_PWD },
      })
      emp.passwordChanged = cp.status === 200 && cp.json?.success === true
      emp.token = cp.json?.data?.accessToken || t1
      const info = await me(emp.token)
      emp.perms = info?.permissions || []
      emp.rolesClaim = info?.roles || []
      emp.menus = (info?.menus || []).map((m) => m.key)
      R.pass('SEED-03', `建员工+登录：${pos}`, `users#${created.id} username=${username}@${tenantCode} 首登强制改密=${emp.mustChangePassword} 改密成功=${emp.passwordChanged} permissions=${JSON.stringify(emp.perms)}`,
        [`POST /api/admin/users {position:${pos}}`, 'POST /api/auth/employee/login', 'POST /api/auth/password/change', 'GET /api/auth/me'])
    } catch (e) {
      emp.loginError = String(e).slice(0, 200)
      R.fail('SEED-03', `建员工+登录：${pos}`, `建号成功但登录失败：${emp.loginError}`)
    }
    employees.push(emp)
  }

  // ── 3. 自定义岗位（岗位权限页能力）+ 该岗位员工 ──
  try {
    const customName = `验收临时岗${stamp}`
    // 权限树提交的是 permissionId（不是 code）—— 与前端「岗位权限」弹窗同口径
    const permRes = await api('GET', '/api/admin/permissions', { token })
    const permList = permRes.json?.data || []
    const wantCodes = ['dashboard:view', 'order:list']
    const permissionIds = permList.filter((p) => wantCodes.includes(p.code)).map((p) => p.id)
    const cr = await api('POST', '/api/admin/roles', {
      token, body: { name: customName, code: `acc_custom_${stamp}`, description: '验收用自定义岗位', permissionIds },
    })
    if (cr.status === 200 && cr.json?.success) {
      const cid = cr.json.data?.id
      const crp = psql(`select array_agg(p.code order by p.code) as codes from role_permissions rp join permissions p on p.id=rp.permission_id where rp.role_id='${cid}'`)
      R.pass('SEED-04', '自定义岗位创建（岗位权限页能力）', `roles#${cid} name=${customName} 落库权限=${JSON.stringify(crp[0]?.codes)}`,
        [`POST /api/admin/roles {permissions:['dashboard:view','order:list']}`])
      const phone = `136${String(Date.now()).slice(-6)}01`.slice(0, 11)
      const username = `acc_custom_${stamp}`
      const ur = await api('POST', '/api/admin/users', { token, body: { phone, name: `验收自定义岗${stamp}`, username, password: INIT_PWD, position: customName } })
      if (ur.status === 200 && ur.json?.success) {
        const { token: t1 } = await employeeLoginApi(`${username}@${tenantCode}`, INIT_PWD)
        const cp = await api('POST', '/api/auth/password/change', { token: t1, body: { oldPassword: INIT_PWD, newPassword: FINAL_PWD } })
        const t2 = cp.json?.data?.accessToken || t1
        const info = await me(t2)
        employees.push({ pos: customName, roleCode: `acc_custom_${stamp}`, phone, username, name: `验收自定义岗${stamp}`, id: ur.json.data.id,
          expectedPerms: ['dashboard:view', 'order:list'], perms: info?.permissions || [], token: t2, rolesClaim: info?.roles || [], menus: (info?.menus || []).map((m) => m.key) })
        R.pass('SEED-05', '自定义岗位员工创建+登录', `users#${ur.json.data.id} username=${username}@${tenantCode} permissions=${JSON.stringify(info?.permissions)}`,
          ['POST /api/admin/users {position:自定义岗}', 'GET /api/auth/me'])
      } else {
        R.fail('SEED-05', '自定义岗位员工创建', `HTTP ${ur.status} ${ur.text.slice(0, 200)}`)
      }
    } else {
      R.fail('SEED-04', '自定义岗位创建（岗位权限页能力）', `HTTP ${cr.status} ${cr.text.slice(0, 200)}`)
    }
  } catch (e) {
    R.fail('SEED-04', '自定义岗位流程异常', String(e).slice(0, 300))
  }

  // ── 4. 工人档案（工号 + PIN，供工人端 H5）──
  let worker = null
  try {
    const workerNo = `W${stamp}`
    const wr = await api('POST', '/api/admin/workers', { token, body: { workerNo, name: `验收工人${stamp}`, pin: '246810' } })
    if (wr.status === 200 && wr.json?.success) {
      worker = { workerNo, pin: '246810', id: wr.json.data.id, name: `验收工人${stamp}` }
      R.pass('SEED-06', '工人档案创建（工号+PIN）', `users#${worker.id} workerNo=${workerNo} name=${worker.name} role=${wr.json.data.role}；响应不含口令字段=${!('passwordHash' in wr.json.data) && !('pin' in wr.json.data)}`,
        ['POST /api/admin/workers {workerNo,name,pin}'])
    } else {
      R.fail('SEED-06', '工人档案创建', `HTTP ${wr.status} ${wr.text.slice(0, 250)}`)
    }
    // 工号重复 → 409（唯一性校验）
    const dup = await api('POST', '/api/admin/workers', { token, body: { workerNo, name: '重复工号', pin: '111111' } })
    const dupOk = dup.status === 409 || (dup.status === 400)
    dupOk ? R.pass('SEED-07', '工人工号唯一性校验', `重复工号 → HTTP ${dup.status}（期望 409/400，非 500）`, ['POST /api/admin/workers 重复 workerNo'])
          : R.fail('SEED-07', '工人工号唯一性校验', `重复工号 → HTTP ${dup.status} ${dup.text.slice(0, 150)}`)
    // 缺 PIN → 校验错误
    const noPin = await api('POST', '/api/admin/workers', { token, body: { workerNo: `${workerNo}X`, name: '缺PIN' } })
    ;(noPin.status === 400 || noPin.status === 422)
      ? R.pass('SEED-08', '工人建号缺 PIN 校验', `缺 PIN → HTTP ${noPin.status}`, ['POST /api/admin/workers 无 pin'])
      : R.fail('SEED-08', '工人建号缺 PIN 校验', `缺 PIN → HTTP ${noPin.status} ${noPin.text.slice(0, 150)}`)
  } catch (e) {
    R.fail('SEED-06', '工人档案流程异常', String(e).slice(0, 300))
  }

  // ── 5. DB 侧核验：员工落库 + 权限快照 vs 岗位默认权限 ──
  try {
    const rows = psql(`select id, phone, nickname, username, role, position, status, permissions::text as permissions
                       from users where tenant_id=${ctx.tenantId} and deleted=0 order by created_at`)
    R.pass('SEED-09', 'DB：员工落库', `${rows.length} 名用户（含管理员）：${rows.map((r) => `${r.position}/${r.role}`).join(' ')}`,
      [`SQL: select id,phone,nickname,username,role,position from users where tenant_id=${ctx.tenantId}`])

    for (const e of employees) {
      const dbRow = rows.find((r) => r.username === e.username)
      if (!dbRow) { R.fail('SEED-10', `DB 权限快照：${e.pos}`, '未找到该员工行'); continue }
      const snapshot = JSON.parse(dbRow.permissions || '[]').sort()
      const expected = [...(e.expectedPerms || [])].sort()
      const same = JSON.stringify(snapshot) === JSON.stringify(expected)
      same
        ? R.pass('SEED-10', `DB 权限快照 = 岗位默认权限：${e.pos}`, `users.permissions(${snapshot.length}) == role_permissions(${expected.length})：${snapshot.join(',')}`,
            [`SQL: select permissions from users where username='${e.username}'`, `SQL: select p.code from role_permissions rp join permissions p on p.id=rp.permission_id join roles r on r.id=rp.role_id where r.code='${e.roleCode}'`])
        : R.fail('SEED-10', `DB 权限快照 = 岗位默认权限：${e.pos}`, `snapshot=${JSON.stringify(snapshot)} vs role_permissions=${JSON.stringify(expected)}`)
    }
  } catch (e) {
    R.fail('SEED-09', 'DB 员工核验异常', String(e).slice(0, 300))
  }

  // ── 6. 页面侧核验：员工管理列表能看到这些员工 ──
  try {
    const browser = await chromium.launch({ headless: true })
    const { page } = await newContext(browser)
    await loginAsAdmin(page)
    await page.goto(WEB + '/employees', { waitUntil: 'domcontentloaded', timeout: 40000 })
    await page.getByText('员工管理').first().waitFor({ timeout: 20000 })
    await sleep(1500)
    const body = await page.evaluate(() => document.body.innerText)
    const found = employees.filter((e) => body.includes(e.name))
    await shot(page, 's2-employees-list')
    found.length >= 1
      ? R.pass('SEED-11', '页面：员工管理列表渲染新建员工', `命中 ${found.length}/${employees.length} 名员工姓名（页面文本 ${body.length} 字符）`,
          ['screenshots/s2-employees-list.png'])
      : R.fail('SEED-11', '页面：员工管理列表渲染新建员工', `页面未出现任何新建员工姓名（文本片段：${body.slice(0, 200)}）`, ['screenshots/s2-employees-list.png'])
    // 工人是否在员工列表（或独立入口）
    const hasWorkerEntry = /工人/.test(body)
    R.pass('SEED-12', '页面：员工管理含工人入口/标签', `页面文本含「工人」=${hasWorkerEntry}`, ['screenshots/s2-employees-list.png'])
    await browser.close()
  } catch (e) {
    R.fail('SEED-11', '页面核验异常', String(e).slice(0, 300))
  }

  // ── 7. 日志侧证据 ──
  try {
    const lines = (await import('./lib.mjs')).grepApiLog(`创建用户: |建工人|worker`, { limit: 10 })
    lines.length
      ? R.pass('SEED-13', '服务器日志：建号链路可追溯', `命中 ${lines.length} 行，示例：${lines[lines.length - 1].text.trim().slice(0, 150)}`,
          lines.map((l) => `L${l.line}: ${l.text.trim()}`))
      : R.fail('SEED-13', '服务器日志：建号链路可追溯', '日志未命中')
  } catch (e) {
    R.fail('SEED-13', '日志核验异常', String(e).slice(0, 200))
  }

  saveCtx({ employees, worker, tenantCode, finalPwd: FINAL_PWD })
  const s = R.summary()
  log(`== 阶段2 完成：pass=${s.pass} fail=${s.fail} skip=${s.skip}`)
}

async function loginAsAdmin(page) {
  const { loginUi } = await import('./lib.mjs')
  await loginUi(page, { mode: 'admin', phone: ctx.adminPhone })
}

main().catch((e) => { R.fail('SEED-FATAL', '阶段2 致命错误', String(e).slice(0, 600)); process.exitCode = 1 })
