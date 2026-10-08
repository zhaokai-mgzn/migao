// R2 阶段 1：绑定既有租户 20（米高POC演示布艺）+ 刚入驻现场盘点
//
// 与上轮 s1（注册新租户）不同：本轮 tenantId=20 是既有 POC 演示租户，模拟「刚入驻」从它出发。
// 覆盖：真页面登录（UI）→ 管理员 token → DB 全量盘点（租户/岗位/员工/商品/订单/工艺配置现状）
//      → 工艺参数配置初始化缺口确认（routings=0、craft_calc_configs=0）→ 写 context.json 供后续阶段用。
// 证据：页面（登录+dashboard 截图）+ DB（tenants/roles/users/products/orders/crafts/...）+ API（/auth/me）。
import { chromium, Recorder, log, newContext, shot, loginApi, loginUi, me, psql, saveCtx, loadCtx,
         waitService, WEB, API } from './lib.mjs'

const R = new Recorder('s20-inventory.json')
const ctx = loadCtx()
const PHONE = process.env.T20_ADMIN_PHONE || '13870217889'
const TID = Number(process.env.T20_TENANT_ID || 20)

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  log(`== R2 阶段1：绑定租户${TID} + 入驻现场盘点 == phone=${PHONE}`)

  // ── 1. API 登录（管理员）──
  const { token } = await loginApi(PHONE)
  if (!token) throw new Error('管理员登录失败')
  saveCtx({ adminToken: token, adminPhone: PHONE, tenantId: TID })
  const meRes = await me(token)
  const meJson = meRes.json?.data?.user || {}
  R.pass('T20-01', '管理员 API 登录（短信万能码）',
    `POST /api/auth/sms/login → 200；me: nickname=${meJson.nickname} tenantId=${meJson.tenantId} role=${meJson.role || meJson.position}`,
    ['POST /api/auth/sms/login', 'GET /api/auth/me'])

  // ── 2. UI 登录（真页面）──
  const browser = await chromium.launch({ headless: true })
  const { page } = await newContext(browser)
  try {
    await loginUi(page, { mode: 'admin', phone: PHONE })
    await page.waitForTimeout(1500)
    await shot(page, 's20-login-ui')
    R.pass('T20-02', 'UI 管理员登录（验证码页签）', `url=${page.url()}`, ['screenshots/s20-login-ui.png'])
  } catch (e) {
    R.fail('T20-02', '登录页可达性', String(e).slice(0, 300))
  }
  await browser.close().catch(() => {})

  // ── 3. DB 盘点：租户现场 ──
  const t = psql(`select id,name,code,status,created_at from tenants where id=${TID}`)[0]
  if (t) R.pass('T20-03', 'DB：租户 20 存在且 active', `tenants#${t.id} ${t.name} code=${t.code} status=${t.status}`, ['SQL: tenants'])
  else { R.fail('T20-03', 'DB：租户 20 存在', `查无 tenants#${TID}`); throw new Error('租户 20 不存在') }
  saveCtx({ tenantCode: t.code, tenantName: t.name })

  const q = (label, id, sql) => {
    const rows = psql(sql)
    const n = rows[0]?.n ?? 0
    R.pass(id, `盘点：${label}`, `count=${n}`, [`SQL: ${sql}`])
    return n
  }
  q('角色数', 'T20-04', `select count(*)::int n from roles where tenant_id=${TID} and deleted=0`)
  q('员工数', 'T20-05', `select count(*)::int n from users where tenant_id=${TID} and deleted=0`)
  q('权限数', 'T20-06', `select count(*)::int n from permissions`)
  q('商品数', 'T20-07', `select count(*)::int n from products where tenant_id=${TID} and deleted=0`)
  q('订单数', 'T20-08', `select count(*)::int n from orders where tenant_id=${TID} and deleted=0`)
  q('工艺(原)数', 'T20-09', `select count(*)::int n from production_crafts where tenant_id=${TID} and deleted=0`)
  q('工序库数', 'T20-10', `select count(*)::int n from production_operations where tenant_id=${TID} and deleted=0`)
  q('工艺路线数', 'T20-11', `select count(*)::int n from production_route_templates where tenant_id=${TID} and deleted=0`)
  q('选路规则数', 'T20-12', `select count(*)::int n from production_route_rules where tenant_id=${TID}`)
  const cfgRows = psql(`select count(*)::int n from craft_calc_configs where tenant_id=${TID} and deleted=0`)
  R.pass('T20-13', '盘点：算料配置行数（初始化缺口）', `craft_calc_configs=${cfgRows[0]?.n ?? 0}（0=用引擎默认值，待初始化）`, ['SQL: craft_calc_configs'])

  // 员工与岗位明细（供 RBAC 阶段取账号）
  const staff = psql(`select u.id, u.phone, u.username, u.nickname, u.role, u.position, u.status,
                      coalesce(array_agg(r.code) filter (where r.code is not null), '{}') as roles
                      from users u left join user_roles ur on ur.user_id=u.id left join roles r on r.id=ur.role_id
                      where u.tenant_id=${TID} and u.deleted=0 group by u.id order by u.id`)
  R.pass('T20-14', '盘点：员工明细', staff.map(s => `${s.nickname||s.username}(${s.phone}) role=${s.role} roles=[${s.roles}] status=${s.status}`).join('；'),
    ['SQL: users join user_roles'])
  saveCtx({ staff: staff.map(s => ({ id: s.id, phone: s.phone, username: s.username, nickname: s.nickname, role: s.role, roles: s.roles, status: s.status })) })

  const roleRows = psql(`select r.id, r.code, r.name, count(rp.permission_id)::int as perms
                         from roles r left join role_permissions rp on rp.role_id=r.id
                         where r.tenant_id=${TID} and r.deleted=0 group by r.id order by r.id`)
  R.pass('T20-15', '盘点：岗位与权限数', roleRows.map(r => `${r.code}=${r.perms}`).join('，'), ['SQL: roles left join role_permissions'])
  saveCtx({ roles: roleRows.map(r => ({ id: r.id, code: r.code, name: r.name, perms: r.perms })) })

  // ── 4. 工艺参数配置 API 现状（读面 production:view）──
  const api = async (path) => {
    const res = await fetch(API + path, { headers: { Cookie: `access_token=${token}`, Authorization: `Bearer ${token}` } })
    let j = null; try { j = await res.json() } catch {}
    return { status: res.status, json: j }
  }
  const cfg = await api('/api/admin/production/craft-calc-config')
  R.pass('T20-16', '算料配置读面（GET craft-calc-config）',
    `HTTP ${cfg.status} source=${cfg.json?.data?.source} keys=${Object.keys(cfg.json?.data?.config || {}).length}`,
    ['GET /api/admin/production/craft-calc-config'])
  saveCtx({ craftCalcSource: cfg.json?.data?.source, craftCalcConfig: cfg.json?.data?.config || {} })

  const routes = await api('/api/admin/production/routings')
  const routeList = routes.json?.data?.routings || []
  R.pass('T20-17', '工艺路线读面（GET routings）', `HTTP ${routes.status} count=${routes.json?.data?.total} ${routeList.map(r => `${r.name}${r.is_default ? '[默认]' : ''}`).join('，')}`, ['GET /api/admin/production/routings'])
  saveCtx({ routingCount: routeList.length, routings: routeList })

  const catalog = await api('/api/admin/production/operations-catalog')
  const cat = (catalog.json?.data?.groups || []).flatMap(g => g.operations || [])
  R.pass('T20-18', '工序库读面（GET operations-catalog）', `HTTP ${catalog.status} count=${catalog.json?.data?.total} groups=${(catalog.json?.data?.groups || []).length} 样例=${cat.slice(0, 5).map(c => c.name).join('/')}`,
    ['GET /api/admin/production/operations-catalog'])
  saveCtx({ operationsCatalog: cat })

  log('== R2 阶段1 完成 ==')
}

main().catch(e => { R.fail('T20-00', '阶段1异常终止', String(e && e.stack || e).slice(0, 800), []) }).finally(() => R.dump())
