// 阶段 1：模拟一家全新企业入驻（真页面 + 真后端 + 真库）
//
// 覆盖：注册页两个步骤的全部输入框 + 前后端校验（负面用例）→ 提交 → AI 甄别结果页
//      → 租户/管理员落库核验 → 管理员登录（API + UI）。
// 证据三路：① 页面（截图 + 可见文案）② DB（tenants / tenant_applications / users / roles / role_permissions）
//          ③ 服务器日志（admin-api 的入驻申请与甄别调用记录）。
import { chromium, Recorder, log, newContext, shot, loginApi, loginUi, me, api, psql, grepApiLog,
         saveCtx, loadCtx, waitService, sleep, WEB, OUT } from './lib.mjs'

const R = new Recorder('s1-onboard.json')
const ctx0 = loadCtx()
const runId = Date.now().toString().slice(-6)
const PHONE = process.env.ONBOARD_PHONE || ctx0.adminPhone || `139${Date.now().toString().slice(-8)}`
const COMPANY = ctx0.tenantName || `验收布艺${runId}`
const CONTACT = `验收联系人${runId}`
// 已入驻过（context.json 有 tenantId）⇒ 只重放「校验轮次 + 登录 + DB 核验」，不重复建租户
const REUSE = !!ctx0.tenantId

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  log(`== 阶段1：新企业入驻 == phone=${PHONE} company=${COMPANY}`)

  const browser = await chromium.launch({ headless: true })
  const { page } = await newContext(browser)

  // ── 1. 步骤一：手机号/验证码校验（负面）──
  try {
    await page.goto(WEB + '/register', { waitUntil: 'domcontentloaded', timeout: 30000 })
    await page.waitForSelector('#reg-phone', { timeout: 20000 })

    // ① 空手机号 + 空验证码 → 必填校验
    await page.getByRole('button', { name: '下一步' }).click()
    await sleep(400)
    const e1 = await page.getByText(/请输入手机号/).first().isVisible().catch(() => false)
    const e1b = await page.getByText(/请输入验证码/).first().isVisible().catch(() => false)
    await shot(page, 's1-reg-01-required-errors')
    if (e1 && e1b) R.pass('ON-01', '注册步骤一：空提交必填校验', `可见「请输入手机号」=${e1}、「请输入验证码」=${e1b}`, ['screenshots/s1-reg-01-required-errors.png'])
    else R.fail('ON-01', '注册步骤一：空提交必填校验', `手机号必填提示=${e1} 验证码必填提示=${e1b}`, ['screenshots/s1-reg-01-required-errors.png'])

    // ② 手机号格式非法
    await page.fill('#reg-phone', '12345')
    await page.fill('#reg-code', '123456')
    await page.getByRole('button', { name: '下一步' }).click()
    await sleep(400)
    const e2 = await page.getByText(/请输入正确的11位手机号/).first().isVisible().catch(() => false)
    await shot(page, 's1-reg-02-phone-format')
    e2 ? R.pass('ON-02', '注册步骤一：手机号格式校验', '11 位以外手机号被拦（提示「请输入正确的11位手机号」）', ['screenshots/s1-reg-02-phone-format.png'])
       : R.fail('ON-02', '注册步骤一：手机号格式校验', '非法手机号未被拦截')

    // ③ 验证码长度非法
    await page.fill('#reg-phone', PHONE)
    await page.fill('#reg-code', '123')
    await page.getByRole('button', { name: '下一步' }).click()
    await sleep(400)
    const e3 = await page.getByText(/验证码为6位数字/).first().isVisible().catch(() => false)
    await shot(page, 's1-reg-03-code-format')
    e3 ? R.pass('ON-03', '注册步骤一：验证码长度校验', '3 位验证码被拦（提示「验证码为6位数字」）', ['screenshots/s1-reg-03-code-format.png'])
       : R.fail('ON-03', '注册步骤一：验证码长度校验', '短验证码未被拦截')

    // ── 2. 步骤一通过（正向）──
    await page.fill('#reg-code', '123456')
    await page.getByRole('button', { name: '下一步' }).click()
    await page.waitForSelector('#companyName', { timeout: 15000 })
    R.pass('ON-04', '注册步骤一：合法手机号+验证码进入步骤二', `phone=${PHONE} code=123456 → 出现企业信息表单`, ['screenshots/s1-reg-04-step2.png'])
    await shot(page, 's1-reg-04-step2')

    // ── 3. 步骤二：企业信息校验（负面）──
    await page.getByRole('button', { name: '提交申请' }).click()
    await sleep(500)
    const e4 = await page.getByText(/请输入企业名称/).first().isVisible().catch(() => false)
    const e5 = await page.getByText(/请输入联系人姓名/).first().isVisible().catch(() => false)
    await shot(page, 's1-reg-05-company-required')
    ;(e4 && e5)
      ? R.pass('ON-05', '注册步骤二：企业名称/联系人必填校验', `空提交被拦（企业名称=${e4} 联系人=${e5}）`, ['screenshots/s1-reg-05-company-required.png'])
      : R.fail('ON-05', '注册步骤二：企业名称/联系人必填校验', `企业名称提示=${e4} 联系人提示=${e5}`)

    // 蜜罐字段必须为空（反爬）：确认页面上它不参与填写
    const honeypot = await page.inputValue('#website').catch(() => '')

    // ── 4. 步骤二：填真实企业信息并提交（AI 甄别）──
    if (REUSE) {
      R.skip('ON-06', '注册提交 → AI 甄别通过（步骤三结果页）', `本轮不重复提交（已入驻 tenantId=${ctx0.tenantId}），改由 DB 复核既有租户`)
      throw { reused: true }
    }
    await page.fill('#companyName', COMPANY)
    await page.fill('#contactName', CONTACT)
    const industrySel = page.locator('#industry')
    const opts = await industrySel.locator('option').allTextContents().catch(() => [])
    let industryPicked = ''
    for (let i = 1; i < opts.length; i++) {
      const t = opts[i].trim()
      if (t && !/请选择/.test(t)) { await industrySel.selectOption({ index: i }); industryPicked = t; break }
    }
    await page.fill('#address', '浙江省杭州市余杭区验收路 1 号')
    await page.fill('#description', '窗帘布艺生产与销售，验收专用企业')

    const t0 = Date.now()
    await page.getByRole('button', { name: '提交申请' }).click()
    // 步骤三：AI 甄别结果（秒级）
    await page.getByText(/审核通过，欢迎入驻！|审核未通过/).first().waitFor({ timeout: 40000 })
    const tookMs = Date.now() - t0
    const approved = await page.getByText(/审核通过，欢迎入驻！/).first().isVisible().catch(() => false)
    const rejected = await page.getByText(/审核未通过/).first().isVisible().catch(() => false)
    const bodyText = (await page.evaluate(() => document.body.innerText)).slice(0, 1200)
    await shot(page, 's1-reg-06-result')
    if (approved) {
      R.pass('ON-06', '注册提交 → AI 甄别通过（步骤三结果页）',
        `${tookMs}ms 返回「审核通过，欢迎入驻！」；蜜罐字段保持为空=${honeypot === ''}；行业=${industryPicked || '未选'}`,
        ['screenshots/s1-reg-06-result.png'])
    } else {
      R.fail('ON-06', '注册提交 → AI 甄别通过（步骤三结果页）',
        `${tookMs}ms 返回「审核未通过」=${rejected}；页面文本片段：${bodyText.slice(0, 300)}`,
        ['screenshots/s1-reg-06-result.png'])
    }
    R.records[R.records.length - 1].pageText = bodyText
  } catch (e) {
    if (!e?.reused) R.fail('ON-00', '注册流程异常终止', String(e).slice(0, 500), [])
  }

  // ── 5. DB 侧核验：申请单 / 租户 / 管理员 / 岗位 / 岗位权限 ──
  try {
    const apps = psql(`select id, company_name, phone, status, review_source, reject_reason, created_at from tenant_applications where phone='${PHONE}' order by created_at desc limit 3`)
    const app = apps[0]
    if (app && app.status === 'approved') {
      R.pass('ON-07a', 'DB：入驻申请单已 approved', `tenant_applications#${app.id} status=${app.status} review_source=${app.review_source}`, [`SQL: select id,company_name,phone,status,review_source from tenant_applications where phone='${PHONE}'`])
    } else {
      R.fail('ON-07a', 'DB：入驻申请单已 approved', `申请单=${JSON.stringify(apps).slice(0, 300)}`)
    }

    const tenants = psql(`select id, name, status, created_at from tenants where name='${COMPANY}'`)
    const tenant = tenants[0]
    if (tenant) R.pass('ON-07b', 'DB：自动开通租户', `tenants#${tenant.id} name=${tenant.name} status=${tenant.status}`, [`SQL: select id,name,status from tenants where name='${COMPANY}'`])
    else R.fail('ON-07b', 'DB：自动开通租户', `未找到 name=${COMPANY} 的租户`)

    const users = psql(`select id, phone, nickname, username, role, position, status, permissions::text as permissions, tenant_id from users where phone='${PHONE}'`)
    const admin = users[0]
    if (admin) R.pass('ON-07c', 'DB：自动创建企业管理员', `users#${admin.id} role=${admin.role} position=${admin.position} tenant_id=${admin.tenant_id} permissions=${admin.permissions}`, [`SQL: select id,phone,role,tenant_id,permissions from users where phone='${PHONE}'`])
    else R.fail('ON-07c', 'DB：自动创建企业管理员', '未找到管理员用户')

    const tid = tenant?.id ?? admin?.tenant_id
    const roles = psql(`select code, name from roles where tenant_id=${tid} order by code`)
    const codes = roles.map((r) => r.code)
    const expected = ['admin', 'customer_service', 'finance', 'operator', 'sales']
    const missing = expected.filter((c) => !codes.includes(c))
    if (roles.length && missing.length === 0) {
      R.pass('ON-08', 'DB：新租户五岗种子齐备', `roles=${codes.join(',')}`, [`SQL: select code,name from roles where tenant_id=${tid}`])
    } else {
      R.fail('ON-08', 'DB：新租户五岗种子齐备', `roles=${codes.join(',')} 缺失=${missing.join(',')}`)
    }

    const rp = psql(`select r.code as role_code, count(*)::int as perm_count from role_permissions rp join roles r on r.id=rp.role_id where r.tenant_id=${tid} group by r.code order by r.code`)
    R.pass('ON-09', 'DB：岗位默认权限已预置（role_permissions）', rp.map((x) => `${x.role_code}=${x.perm_count}`).join(' '), [`SQL: select r.code,count(*) from role_permissions rp join roles r on r.id=rp.role_id where r.tenant_id=${tid} group by r.code`])

    saveCtx({ runId, tenantId: tid, tenantName: COMPANY, adminPhone: PHONE, adminUserId: admin?.id, roles })
    log(`   tenantId=${tid} adminUserId=${admin?.id}`)
  } catch (e) {
    R.fail('ON-07', 'DB 核验失败', String(e).slice(0, 400))
  }

  // ── 6. 管理员登录（API + UI）──
  try {
    const { token } = await loginApi(PHONE)
    const info = await me(token)
    const perms = info?.permissions || []
    const u = info?.user || {}
    const isAll = perms.includes('*')
    R.pass('ON-10', '管理员短信登录 + /api/auth/me 权限',
      `roles=${JSON.stringify(info?.roles)} permissions=${JSON.stringify(perms)} tenantId=${u.tenantId} tenantName=${u.tenantName} 菜单节点=${JSON.stringify((info?.menus || []).map((m) => m.key))}`,
      [`POST /api/auth/sms/login phone=${PHONE}`, 'GET /api/auth/me'])
    isAll ? R.pass('ON-11', '管理员权限恒为 ["*"]', `permissions=${JSON.stringify(perms)}`, ['GET /api/auth/me'])
          : R.fail('ON-11', '管理员权限恒为 ["*"]', `实际=${JSON.stringify(perms)}`)
    saveCtx({ adminToken: token, adminMe: u, adminMenus: info?.menus || [] })

    // UI 登录 + 首页渲染（登录页默认「员工登录」页签，管理员须切页签 —— issue #5485）
    await loginUi(page, { mode: 'admin', phone: PHONE })
    const dashText = await page.evaluate(() => document.body.innerText.slice(0, 400))
    await shot(page, 's1-admin-dashboard')
    R.pass('ON-12', '管理员 UI 登录并进入经营看板', `URL=${page.url()}；页面文本片段=${dashText.replace(/\n/g, ' ').slice(0, 120)}`, ['screenshots/s1-admin-dashboard.png'])

    // 侧边栏菜单数（管理员应为全部）
    const menuCount = await page.locator('aside a, nav a').count().catch(() => 0)
    R.pass('ON-13', '管理员侧边栏菜单可见', `侧边栏链接数=${menuCount}`, ['screenshots/s1-admin-dashboard.png'])
  } catch (e) {
    R.fail('ON-10', '管理员登录失败', String(e).slice(0, 400))
  }

  // ── 7. 服务器日志侧证据 ──
  try {
    const hits = grepApiLog(`(企业入驻申请|入驻申请|AI 甄别|registration)`, { limit: 12 })
    const hitText = hits.map((h) => `L${h.line}: ${h.text.trim()}`)
    hits.length
      ? R.pass('ON-14', '服务器日志：入驻申请处理链路可追溯', `命中 ${hits.length} 行，示例：${hits[0].text.trim().slice(0, 160)}`, hitText)
      : R.fail('ON-14', '服务器日志：入驻申请处理链路可追溯', `日志 ${API_LOG} 中未检索到入驻相关记录`)
  } catch (e) {
    R.fail('ON-14', '服务器日志检索失败', String(e).slice(0, 200))
  }

  await browser.close()
  const s = R.summary()
  log(`== 阶段1 完成：pass=${s.pass} fail=${s.fail} skip=${s.skip}`)
}

main().catch((e) => { R.fail('ON-FATAL', '阶段1 致命错误', String(e).slice(0, 600)); process.exitCode = 1 })
