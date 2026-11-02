// p1：岗位账号池（真后端 + 真库）—— 为 tenant 25 建齐 6 个非管理员岗位账号
//
// 为什么自建：tenant 25 现有 users = 1（管理员 13800138000）+ 5 个 disabled 的「造数探针工人」，
// 6 个岗位（客服/运营/销售/财务/商品管理员/知识编辑）**一个账号都没有** ⇒ 不建就无从「按岗位登页面」。
//
// 口径：期望权限的**真值源 = DB 的 role_permissions**（不读被测读面 /api/auth/me 来自证）。
// 纪律：token 只写 /tmp/a06-session.json（不进 acceptance/ 产物，issue #6303）。
import { api, loginApi, me, employeeLoginApi, psql, log, OUT, API, scrub } from './lib.mjs'
import { writeFileSync, readFileSync, existsSync } from 'node:fs'

const SESSION = process.env.A06_SESSION || '/tmp/a06-session.json'
const INIT_PWD = 'Init@123456'
const FINAL_PWD = 'Migao@2026x'
const POSITIONS = ['客服', '运营', '销售', '财务', '商品管理员', '知识编辑']
const TENANT_ID = Number(process.env.TENANT_ID || 25)
const ADMIN_PHONE = process.env.ADMIN_PHONE || '13800138000'

const R = []
const rec = (state, id, name, detail, evidence = []) => R.push({ state, id, name, detail, evidence })

function loadSession() { try { return JSON.parse(readFileSync(SESSION, 'utf8')) } catch { return {} } }
function saveSession(o) { writeFileSync(SESSION, JSON.stringify({ ...loadSession(), ...o }, null, 2)) }

async function main() {
  log(`== p1：岗位账号池 tenant=${TENANT_ID} API=${API}`)

  // ── 1. 管理员登录（部署面）──
  const login = await loginApi(ADMIN_PHONE)
  const adminToken = login.token
  const tCode = psql(`select code from tenants where id=${TENANT_ID}`)[0]?.code
  if (!adminToken || !tCode) throw new Error(`管理员登录失败或未取到企业编码（token=${!!adminToken} code=${tCode}）`)
  rec('pass', 'P1-01', '管理员登录（部署面短信万能码）',
    `POST /api/auth/sms/login HTTP 200；tenant=${TENANT_ID} code=${tCode}`,
    ['POST /api/auth/sms/login'])
  saveSession({ adminToken, tenantCode: tCode, tenantId: TENANT_ID })

  // ── 2. 岗位清单 + 期望权限真值源（DB）──
  const rolesRes = await api('GET', '/api/admin/roles/all', { token: adminToken })
  const roles = rolesRes.json?.data || []
  const byName = Object.fromEntries(roles.map((r) => [r.name, r]))
  const defaults = psql(`select r.code, array_agg(p.code order by p.code) as codes
                         from roles r join role_permissions rp on rp.role_id=r.id join permissions p on p.id=rp.permission_id
                         where r.tenant_id=${TENANT_ID} group by r.code`)
  const expected = Object.fromEntries(defaults.map((d) => [d.code, d.codes]))
  rec('pass', 'P1-02', '岗位清单 + 期望权限（DB 真值源）',
    `岗位=${roles.map((r) => `${r.name}(${r.code})`).join(' / ')}；每岗位权限数为 DB 现取`,
    [`select r.code, array_agg(p.code) from roles r join role_permissions …`])

  // ── 3. 逐岗位建号（已存在则复用）──
  const employees = []
  let seq = 0
  for (const pos of POSITIONS) {
    const role = byName[pos]
    if (!role) { rec('fail', `P1-03:${pos}`, `建号：${pos}`, '岗位不存在于 /api/admin/roles/all'); continue }
    const username = `a06_${role.code}`
    let row = psql(`select id,phone,username,status,must_change_password from users where tenant_id=${TENANT_ID} and username='${username}'`)[0]
    let created = false
    if (!row) {
      const phone = `137${String(Date.now()).slice(-5)}${String(seq++).padStart(2, '0')}`.slice(0, 11)
      const res = await api('POST', '/api/admin/users', {
        token: adminToken,
        body: { phone, name: `A06验收${pos}`, username, password: INIT_PWD, position: pos },
      })
      if (res.status !== 200 || !res.json?.success) {
        rec('fail', `P1-03:${pos}`, `建号：${pos}`, `HTTP ${res.status} ${res.text.slice(0, 200)}`,
          ['POST /api/admin/users'])
        continue
      }
      created = true
      row = psql(`select id,phone,username,status,must_change_password from users where tenant_id=${TENANT_ID} and username='${username}'`)[0]
    }

    // ── 4. 员工自助登录（用户名@企业编码 + 密码）→ 首登强制改密 → 复登 ──
    const emp = { pos, roleCode: role.code, username, id: row?.id, created, expectedPerms: expected[role.code] || [] }
    try {
      let pwd = FINAL_PWD
      let t1
      try {
        ;({ token: t1 } = await employeeLoginApi(`${username}@${tCode}`, pwd))
      } catch {
        ;({ token: t1 } = await employeeLoginApi(`${username}@${tCode}`, INIT_PWD))
        pwd = INIT_PWD
      }
      const info0 = await me(t1)
      emp.mustChangePassword = info0?.user?.mustChangePassword === true
      let token = t1
      if (pwd === INIT_PWD) {
        const cp = await api('POST', '/api/auth/password/change', { token: t1, body: { oldPassword: INIT_PWD, newPassword: FINAL_PWD } })
        emp.passwordChanged = cp.status === 200 && cp.json?.success === true
        token = cp.json?.data?.accessToken || t1
      }
      const info = await me(token)
      emp.perms = info?.permissions || []
      emp.rolesClaim = info?.roles || []
      emp.menus = (info?.menus || []).map((m) => m.key || m)
      emp.loginOk = true
      const missing = (emp.expectedPerms || []).filter((c) => !emp.perms.includes(c) && !emp.perms.includes('*'))
      const extra = (emp.perms || []).filter((c) => c !== '*' && !(emp.expectedPerms || []).includes(c))
      emp.permDiff = { missing, extra }
      rec('pass', `P1-04:${pos}`, `登录+权限：${pos}`,
        `username=${username}@${tCode} 新建=${created} 首登改密=${!!emp.mustChangePassword} 改密成功=${!!emp.passwordChanged} perms=${emp.perms.length} missing=${JSON.stringify(missing)} extra=${JSON.stringify(extra)}`,
        ['POST /api/auth/employee/login', 'POST /api/auth/password/change', 'GET /api/auth/me'])
    } catch (e) {
      emp.loginOk = false
      emp.loginError = String(e).slice(0, 300)
      rec('fail', `P1-04:${pos}`, `登录+权限：${pos}`, emp.loginError, ['POST /api/auth/employee/login'])
    }
    employees.push(emp)
  }

  const counts = R.reduce((a, r) => ({ ...a, [r.state]: (a[r.state] || 0) + 1 }), {})
  writeFileSync(`${OUT}/p1-roles.json`, JSON.stringify(scrub({ at: new Date().toISOString(), subjectSha: '73327161f', counts, rows: R, employees }), null, 2))
  saveSession({ employees: employees.map((e) => ({ pos: e.pos, roleCode: e.roleCode, username: e.username, id: e.id, loginOk: e.loginOk, expectedPerms: e.expectedPerms })), tenantCode: tCode, tenantId: TENANT_ID })
  log(`== p1 完成：${JSON.stringify(counts)}`)
  for (const r of R) log(`  [${r.state}] ${r.id} ${r.name} — ${r.detail.slice(0, 220)}`)
}

main().catch((e) => { console.error('p1 失败:', e); process.exit(1) })
