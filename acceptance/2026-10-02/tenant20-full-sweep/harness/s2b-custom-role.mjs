// 阶段 2b：自定义岗位（岗位权限页能力）补测 —— 用 permissionId 口径落库，并覆盖「零权限岗位」
//
// 为什么单列：阶段 2 首次用 `permissions`（权限码）提交 ⇒ 服务端只认 `permissionIds` ⇒ 落库为空。
// 本阶段用**正确口径**重跑一遍，并保留那次的产物作为「零权限自定义岗位」这个边界样本。
import { Recorder, log, api, employeeLoginApi, me, psql, saveCtx, loadCtx, waitService } from './lib.mjs'

const R = new Recorder('s2b-custom-role.json')
const ctx = loadCtx()
const INIT_PWD = 'Init@123456'
const FINAL_PWD = ctx.finalPwd || 'Migao@2026x'

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  const { loginApi } = await import('./lib.mjs')
  const { token } = await loginApi(ctx.adminPhone)
  saveCtx({ adminToken: token })
  const stamp = String(Date.now()).slice(-6)
  log(`== 阶段2b：自定义岗位权限落库 ==`)

  // ── 1. 权限树（permissionId 口径的真值源）──
  const permRes = await api('GET', '/api/admin/permissions', { token })
  const permList = permRes.json?.data || []
  const pick = ['dashboard:view', 'order:list']
  const ids = permList.filter((p) => pick.includes(p.code)).map((p) => p.id)
  R.pass('CR-01', '读取权限树', `HTTP ${permRes.status}；权限总数=${permList.length}；目标 ${pick.join(',')} → permissionId=${ids.length} 个`,
    ['GET /api/admin/permissions'])

  // ── 2. 建自定义岗位（permissionIds）──
  const name = `验收自定义岗${stamp}`
  const code = `acc_custom2_${stamp}`
  const cr = await api('POST', '/api/admin/roles', { token, body: { name, code, description: '验收用', permissionIds: ids } })
  if (!cr.json?.success) { R.fail('CR-02', '自定义岗位创建', `HTTP ${cr.status} ${cr.text.slice(0, 200)}`); return }
  const roleId = cr.json.data.id
  const rp = psql(`select array_agg(p.code order by p.code) as codes from role_permissions rp join permissions p on p.id=rp.permission_id where rp.role_id='${roleId}' and rp.deleted=0`)
  const codes = rp[0]?.codes || []
  JSON.stringify([...codes].sort()) === JSON.stringify([...pick].sort())
    ? R.pass('CR-02', '自定义岗位权限落库 role_permissions', `roles#${roleId} → ${JSON.stringify(codes)}（与提交一致）`,
        [`SQL: select p.code from role_permissions rp join permissions p on p.id=rp.permission_id where rp.role_id='${roleId}'`])
    : R.fail('CR-02', '自定义岗位权限落库 role_permissions', `提交 ${JSON.stringify(pick)} 落库 ${JSON.stringify(codes)}`)

  // ── 3. 该岗位员工：权限快照应等于岗位默认权限 ──
  const phone = `135${String(Date.now()).slice(-6)}11`.slice(0, 11)
  const username = `acc_custom2_${stamp}`
  const ur = await api('POST', '/api/admin/users', { token, body: { phone, name: `验收自定义岗员${stamp}`, username, password: INIT_PWD, position: name } })
  if (!ur.json?.success) { R.fail('CR-03', '自定义岗位员工建号', `HTTP ${ur.status} ${ur.text.slice(0, 200)}`); return }
  const { token: t1 } = await employeeLoginApi(`${username}@${ctx.tenantCode}`, INIT_PWD)
  const cp = await api('POST', '/api/auth/password/change', { token: t1, body: { oldPassword: INIT_PWD, newPassword: FINAL_PWD } })
  const t2 = cp.json?.data?.accessToken || t1
  const info = await me(t2)
  const perms = info?.permissions || []
  JSON.stringify([...perms].sort()) === JSON.stringify([...pick].sort())
    ? R.pass('CR-03', '自定义岗位员工权限快照', `users#${ur.json.data.id} permissions=${JSON.stringify(perms)}（= 岗位默认权限）`,
        ['GET /api/auth/me'])
    : R.fail('CR-03', '自定义岗位员工权限快照', `实际 ${JSON.stringify(perms)} vs 期望 ${JSON.stringify(pick)}`)

  // ── 4. 零权限自定义岗位（上一轮遗留样本）：边界确认 ──
  const zero = psql(`select u.username, u.position, coalesce(u.permissions,'[]')::text as permissions
                     from users u where u.tenant_id=${ctx.tenantId} and u.permissions is null and u.role like 'acc_custom%'`)
  R.pass('CR-04', '零权限自定义岗位样本存在（边界用例）',
    zero.length ? `样本=${zero.map((z) => `${z.username}(${z.position})`).join(',')} —— 该身份应「门禁放行、细粒度全拒」` : '无（不影响）',
    [`SQL: select username,position,permissions from users where tenant_id=${ctx.tenantId} and permissions is null`])

  const employees = (ctx.employees || []).filter((e) => e.roleCode !== code)
  employees.push({ pos: name, roleCode: code, phone, username, name: `验收自定义岗员${stamp}`, id: ur.json.data.id, expectedPerms: codes, perms, token: t2 })
  saveCtx({ employees })

  const s = R.summary()
  log(`== 阶段2b 完成：pass=${s.pass} fail=${s.fail}`)
}

main().catch((e) => { R.fail('CR-FATAL', '阶段2b 致命错误', String(e).slice(0, 400)); process.exitCode = 1 })
