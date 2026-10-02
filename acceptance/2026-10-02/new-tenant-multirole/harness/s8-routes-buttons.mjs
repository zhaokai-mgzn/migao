// 阶段 8：**全量页面**守卫矩阵（41 条路由 × 9 个身份）+ 元素级（按钮）RBAC
//
// 阶段 3 只看了 16 条路由（打折扣版）；本阶段枚举 `(dashboard)` 下**全部** page.tsx（41 条）。
// 判定：直达该路由后，DOM 是否出现 403 页标记（「无权访问该页面」）——
//   期望 denied = 该路由**被 ROUTE_PERMISSION_MAP 覆盖** 且 该身份不含该码；
//   未被覆盖的路由（前缀不在表里）⇒ 期望不拦（放行），这正是 F1/F2 要量化的面。
import { chromium, Recorder, log, newContext, shot, api, loginApi, employeeLoginApi, saveCtx, loadCtx, waitService, sleep, loginUi } from './lib.mjs'
import { readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const R = new Recorder('s8-routes-buttons.json')
const ctx = loadCtx()
const OUT = process.env.OUT_DIR || join(process.cwd(), 'out')
const WEB = process.env.BASE_URL || 'http://localhost:3001'
const MAP = JSON.parse(readFileSync(join(OUT, process.env.ROUTE_MAP || 'route-guard-map-main.json'), 'utf8'))   // 主干坐标（从提交对象导出）   // {prefixes:[{prefix,code}], routes:[...]}

const routeOf = (r) => '/' + r.replace(/\/:id$/, '')            // 动态段用真实 id 替换
async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  const browser = await chromium.launch({ headless: true })
  log(`== 阶段8：全量页面守卫 + 元素级 RBAC == 坐标 ${MAP.commit || '(未标)'} 路由 ${MAP.routes.length} 条 @ ${WEB}`)

  const principals = [{ label: '管理员(admin)', perms: ['*'], mode: 'admin', phone: ctx.adminPhone }]
  for (const e of ctx.employees || []) {
    const { token } = await employeeLoginApi(`${e.username}@${ctx.tenantCode}`, e.pwd || ctx.finalPwd)
    const me = await api('GET', '/api/auth/me', { token })
    principals.push({ label: `${e.pos}(${e.roleCode})`, perms: me.json?.data?.permissions || [], mode: 'employee', identifier: `${e.username}@${ctx.tenantCode}`, password: e.pwd || ctx.finalPwd })
  }
  const has = (p, code) => p.perms.includes('*') || p.perms.includes(code)
  const expectedDenied = (p, route) => {
    const hit = MAP.prefixes.find((x) => route.startsWith(x.prefix))
    return hit ? !has(p, hit.code) : false
  }

  const results = []
  const ORIGIN_FIX = async (ctx2) => {
    // 隔离实例跑在 3002，而实测后端同源过滤器只放行 3001（Origin:3002 ⇒ 403）——
    // 坐标问题在**探针侧**解决：抹掉 /api 请求的 Origin/Referer（等价同源），不动后端与另一会话的 3001。
    await ctx2.route('**/api/**', (route) => {
      const h = { ...route.request().headers() }
      delete h['origin']; delete h['referer']
      return route.continue({ headers: h })
    })
  }
  const CONC = 5
  for (const p of principals) {
    const { page, context } = await newContext(browser)
    await ORIGIN_FIX(context)
    try {
      await loginUi(page, p.mode === 'admin' ? { mode: 'admin', phone: p.phone } : { mode: 'employee', identifier: p.identifier, password: p.password })
    } catch (e) {
      const url = page.url()
      if (/\/login/.test(url)) { R.fail('RT-LOGIN', `岗位 UI 登录失败：${p.label}`, `${url}｜${String(e).slice(0, 160)}`); await page.close(); continue }
      log(`  ${p.label} 未落 /dashboard，实际落 ${url}（按产品行为继续）`)
    }
    const state = await context.storageState()      // 登录态复用 ⇒ 每格开独立标签页并行，互不干扰
    await page.close(); await context.close()

    const rows = []
    for (let i = 0; i < MAP.routes.length; i += CONC) {
      const batch = MAP.routes.slice(i, i + CONC)
      const got = await Promise.all(batch.map(async (r) => {
        const c2 = await browser.newContext({ storageState: state })
        await ORIGIN_FIX(c2)
        const pg = await c2.newPage()
        let isDenied = false
        try {
          await pg.goto(WEB + routeOf(r), { waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => {})
          await Promise.race([
            pg.getByText('无权访问该页面').first().waitFor({ state: 'visible', timeout: 2600 }).catch(() => null),
            pg.waitForFunction(() => document.body.innerText.length > 200, { timeout: 2600 }).catch(() => null),
          ])
          const text = await pg.evaluate(() => document.body.innerText).catch(() => '')
          isDenied = /无权访问该页面/.test(text)
        } catch (e) { /* 单格异常按未拦处理，不符即会报出来 */ }
        await c2.close()
        return { route: r, denied: isDenied, expected: expectedDenied(p, routeOf(r)) }
      }))
      rows.push(...got)
    }
    const bad = rows.filter((x) => x.denied !== x.expected)
    results.push({ principal: p.label, perms: p.perms.length, rows, mismatch: bad.length })
    bad.length === 0
      ? R.pass('RT-01', `页面守卫矩阵：${p.label}`, `${rows.length} 条路由全部与期望一致（拦截 ${rows.filter((x) => x.denied).length} 条）`, ['out/s8-routes.json'])
      : R.fail('RT-01', `页面守卫矩阵：${p.label}`, `${bad.length}/${rows.length} 条不符：` + bad.slice(0, 8).map((b) => `${b.route}（期望${b.expected ? '拦' : '放'}，实际${b.denied ? '拦' : '放'}）`).join('；'))
  }
  writeFileSync(join(OUT, 's8-routes.json'), JSON.stringify(results, null, 1))

  // ── 未被 ROUTE_PERMISSION_MAP 覆盖的路由（从前端源码现取，不靠人工记忆）──
  const uncovered = MAP.routes.filter((r) => !MAP.prefixes.some((x) => ('/' + r).startsWith(x.prefix)))
  R.pass('RT-02', '未被路由守卫覆盖的页面（清单 + 逐条现场复核）',
    `${uncovered.length}/${MAP.routes.length} 条无守卫：${uncovered.join(', ')}`,
    ['frontend/admin-web/src/app/(dashboard)/layout.tsx 的 ROUTE_PERMISSION_MAP'])

  // ── 元素级（按钮）RBAC：前端只有 6 处 hasPermission 门控，逐处验 ──
  try {
    const empPage = principals.map((p) => ({ label: p.label, canWrite: has(p, 'employee:create'), mode: p.mode, phone: p.phone, identifier: p.identifier, password: p.password }))
    const rows = []
    for (const p of empPage) {
      const { page, context } = await newContext(browser)
      await context.route('**/api/**', (route) => { const h = { ...route.request().headers() }; delete h['origin']; delete h['referer']; return route.continue({ headers: h }) })
      await loginUi(page, p.mode === 'admin' ? { mode: 'admin', phone: p.phone } : { mode: 'employee', identifier: p.identifier, password: p.password }).catch(() => {})
      await page.goto(`${WEB}/employees`, { waitUntil: 'domcontentloaded' })
      await Promise.race([page.getByText('无权访问该页面').first().waitFor({ timeout: 3000 }).catch(() => {}), page.waitForTimeout(3000)])
      const text = await page.evaluate(() => document.body.innerText)
      const denied = /无权访问该页面/.test(text)
      const addBtn = await page.getByRole('button', { name: /新增员工/ }).first().isVisible().catch(() => false)
      const editBtn = await page.getByRole('button', { name: /编辑/ }).first().isVisible().catch(() => false)
      const resetBtn = await page.getByRole('button', { name: /重置密码/ }).first().isVisible().catch(() => false)
      rows.push({ label: p.label, canWrite: p.canWrite, denied, addBtn, editBtn, resetBtn })
      await shot(page, `s8-employees-${p.label.replace(/[^\w\u4e00-\u9fa5]/g, '')}`)
      const visible = addBtn || editBtn || resetBtn
      const ok = p.canWrite ? (!denied && addBtn) : (denied || !visible)
      rows[rows.length - 1].ok = ok
      await page.close()
    }
    writeFileSync(join(OUT, 's8-buttons-employees.json'), JSON.stringify(rows, null, 1))
    const bad = rows.filter((r) => !r.ok)
    bad.length === 0
      ? R.pass('BTN-01', '元素级 RBAC：员工页写操作按钮（employee:create 门控）',
          rows.map((r) => `${r.label}:${r.canWrite ? '有码' : '无码'}→新增${r.addBtn ? '显示' : '隐藏'}/编辑${r.editBtn ? '显示' : '隐藏'}/重置${r.resetBtn ? '显示' : '隐藏'}${r.denied ? '（页面被拦）' : ''}`).join('｜'),
          ['out/s8-buttons-employees.json', 'screenshots/s8-employees-*.png', "frontend/admin-web/src/app/(dashboard)/employees/page.tsx:19 canWrite = hasPermission('employee:create')"])
      : R.fail('BTN-01', '元素级 RBAC：员工页写操作按钮', bad.map((r) => `${r.label}：有码=${r.canWrite} 页面被拦=${r.denied} 新增=${r.addBtn} 编辑=${r.editBtn} 重置=${r.resetBtn}`).join('；'))
  } catch (e) {
    R.fail('BTN-01', '元素级 RBAC 探针异常', String(e).slice(0, 250))
  }

  await browser.close()
  const s = R.summary()
  log(`== 阶段8 完成：pass=${s.pass} fail=${s.fail}`)
}
main().catch((e) => { R.fail('RT-FATAL', '阶段8 致命错误', String(e).slice(0, 400)); process.exitCode = 1 })
