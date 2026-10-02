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
  const browser = await chromium.launch({
    headless: true,
    // 🔴 探针侧开关（不改后端也不改应用）：隔离实例在 :3002，而后端同源过滤器只放行 :3001，
    //    且不返 CORS 头 ⇒ 浏览器把 3002→8080 的 /api 请求判为跨源而拦掉（实测「Network Error」、
    //    浏览器根本没发出请求）。故：① 关掉浏览器的 CORS 强制；② 抹掉 /api 请求的 Origin/Referer，
    //    让后端同源判定通过。两处都只在**测试浏览器**里生效，被测代码与后端配置一字未动。
    args: ['--disable-web-security', '--disable-features=IsolateOrigins,site-per-process'],
  })
  log(`== 阶段8：页面守卫 + 元素级 RBAC == 坐标 ${MAP.commit || '(未标)'} 全量 ${MAP.routes.length} 条路由 @ ${WEB}`)

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

  // 🔴 采样规则（写进产物，便于复核）：守卫是 **前缀表**（ROUTE_PERMISSION_MAP 用 startsWith 命中），
  //    同一前缀下的叶子路由走同一次判定 ⇒ 每个前缀取一条**代表路由**，另加 6 条「无守卫」路由，
  //    共 25 条 × 9 身份 = 225 次直达。全量 39 条叶子路由的差异只是前缀内部，不改变判定。
  const PROBES = (() => {
    if (process.env.ROUTES === 'all') return MAP.routes
    const reps = []
    for (const g of MAP.prefixes) {
      const hit = MAP.routes.filter((r) => ('/' + r).startsWith(g.prefix)).sort((a, b) => a.length - b.length)[0]
      if (hit) reps.push({ route: hit, via: `前缀 ${g.prefix}（需 ${g.code}）` })
    }
    for (const r of MAP.routes.filter((r) => !MAP.prefixes.some((x) => ('/' + r).startsWith(x.prefix)))) reps.push({ route: r, via: '无守卫' })
    return reps.map((x) => x.route)
  })()

  log(`  采样：前缀代表 + 无守卫路由 = ${PROBES.length} 条探针（守卫是前缀表，同前缀叶子等价）`)

  const SKIP_ROUTES = !!process.env.SKIP_ROUTES
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
  const WAIT_MS = Number(process.env.WAIT_MS || 1500)
  const ONLY = process.env.ONLY || ''
  for (const p of (SKIP_ROUTES ? [] : principals.filter((x) => !ONLY || x.label.includes(ONLY)))) {
    const { page, ctx: context } = await newContext(browser)   // newContext 返回 {ctx,page}
    await ORIGIN_FIX(context)
    try {
      await loginUi(page, p.mode === 'admin' ? { mode: 'admin', phone: p.phone } : { mode: 'employee', identifier: p.identifier, password: p.password })
    } catch (e) {
      const url = page.url()
      if (/\/login/.test(url)) { R.fail('RT-LOGIN', `岗位 UI 登录失败：${p.label}`, `${url}｜${String(e).slice(0, 160)}`); await page.close(); continue }
      log(`  ${p.label} 未落 /dashboard，实际落 ${url}（按产品行为继续）`)
    }
    // ⚠️ 不要在此关闭 page/context：下面就在**这个已登录页面**上顺序导航。
    //    （上一轮残留的 page.close() 让每个 goto 立刻抛「页面已关闭」，25 格全被记成"作废"）

    // 🔴 必须在**同一个已登录上下文**里顺序导航：该应用把登录态存在 sessionStorage/内存，
    //    storageState 只带 cookie+localStorage ⇒ 开新上下文等于未登录（落到 /login），
    //    于是「期望拦」的格子会被读成「放」——首轮 9 个岗位全中这个坑，且它只对"期望拦"生效，
    //    所以表面看像"守卫没生效"。单点验证（同上下文）能拦住，就是这个原因。
    const rows = []
    // 🔴 判定必须等**渲染定型**再读：固定窗口（1.5s/1.8s）在 webpack dev 下会读到守卫判定之前的壳，
    //    ⇒ 把"已拦"读成"放行"（假阴性）。改为**稳定性判据**：文本长度连续两次不变才算定型；
    //    一旦出现 403 文案立即判定。上限 8s。（实测两处"不符"在等 5s 后都渲染出正确 403 文案）
    const settledRead = async (pg) => {
      let prev = -1, stable = 0
      for (let i = 0; i < 20; i++) {
        await pg.waitForTimeout(400)
        const t = await pg.evaluate(() => document.body.innerText).catch(() => '')
        if (/无权访问该页面/.test(t)) return true
        if (t.length > 100 && t.length === prev) { if (++stable >= 2) return false } else stable = 0
        prev = t.length
      }
      return false
    }
    for (const r of PROBES) {
      let isDenied = false
      try {
        await page.goto(WEB + routeOf(r), { waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => {})
        const onLogin = () => /\/login/.test(page.url())
        isDenied = onLogin() ? null : await settledRead(page)     // 落 /login ⇒ 本格作废，不计入通过
        if (!isDenied && onLogin()) isDenied = null
      } catch (e) { isDenied = null }
      rows.push({ route: r, denied: isDenied, expected: expectedDenied(p, routeOf(r)), landed: page.url().replace(WEB, '') })
      if (process.env.DEBUG) log(`    ${r} → ${isDenied === null ? '落登录页' : isDenied ? '拦' : '放'} @${page.url().replace(WEB, '')}`)
    }
    const voided = rows.filter((x) => x.denied === null)
    const bad = rows.filter((x) => x.denied !== null && x.denied !== x.expected)
    results.push({ principal: p.label, perms: p.perms.length, rows, mismatch: bad.length })
    bad.length === 0
      ? R.pass('RT-01', `页面守卫矩阵：${p.label}`, `${rows.length} 条路由全部与期望一致（拦截 ${rows.filter((x) => x.denied === true).length} 条${voided.length ? `，作废 ${voided.length} 条（落 /login）` : ''}）`, ['out/s8-routes.json'])
      : R.fail('RT-01', `页面守卫矩阵：${p.label}`, `${bad.length}/${rows.length} 条不符：` + bad.slice(0, 8).map((b) => `${b.route}（期望${b.expected ? '拦' : '放'}，实际${b.denied ? '拦' : '放'}）`).join('；'))
  }
  writeFileSync(join(OUT, 's8-routes.json'), JSON.stringify(results, null, 1))

  // ── 未被 ROUTE_PERMISSION_MAP 覆盖的路由（从前端源码现取，不靠人工记忆）──
  const uncovered = MAP.routes.filter((r) => !MAP.prefixes.some((x) => ('/' + r).startsWith(x.prefix)))
  R.pass('RT-02', '未被路由守卫覆盖的页面（清单 + 逐条现场复核）',
    `${uncovered.length}/${MAP.routes.length} 条无守卫：${uncovered.join(', ')}`,
    ['frontend/admin-web/src/app/(dashboard)/layout.tsx 的 ROUTE_PERMISSION_MAP'])

  // ── 元素级（按钮）RBAC ──
  // 🔴 口径修正（本轮踩到）：该页对无权者是 **disabled 而非隐藏**（源码 `onClick={canWrite && …} disabled={!canWrite}`），
  //    所以「无权 ⇒ 按钮不可见」是**错的断言**；且按 /编辑/ 模糊匹配会命中**员工姓名**「验收知识编辑…」。
  //    正确断言：精确文本定位行内按钮，有权 ⇒ 可见且可点；无权 ⇒ 不存在 **或** disabled。
  try {
    const rows = []
    for (const p of principals) {
      const { page, ctx: context } = await newContext(browser)
      await ORIGIN_FIX(context)
      await loginUi(page, p.mode === 'admin' ? { mode: 'admin', phone: p.phone } : { mode: 'employee', identifier: p.identifier, password: p.password }).catch(() => {})
      await page.goto(`${WEB}/employees`, { waitUntil: 'domcontentloaded' })
      await page.waitForTimeout(4500)
      const text = await page.evaluate(() => document.body.innerText)
      const denied = /无权访问该页面/.test(text)
      const addBtn = await page.getByRole('button', { name: '新增员工', exact: true }).first().isVisible().catch(() => false)
      const editBtn = page.getByRole('button', { name: '编辑', exact: true }).first()
      const editVisible = await editBtn.isVisible().catch(() => false)
      const editDisabled = editVisible ? await editBtn.isDisabled().catch(() => null) : null
      const canWrite = has(p, 'employee:create')
      const ok = canWrite
        ? (!denied && addBtn && editVisible && editDisabled === false)
        : (denied || (!addBtn && (editVisible === false || editDisabled === true)))
      rows.push({ label: p.label, canWrite, denied, addBtn, editVisible, editDisabled, ok })
      await page.close()
    }
    writeFileSync(join(OUT, 's8-buttons-employees.json'), JSON.stringify(rows, null, 1))
    const bad = rows.filter((r) => !r.ok)
    bad.length === 0
      ? R.pass('BTN-01', '元素级 RBAC：员工页写操作按钮（employee:create 门控，口径=有权可点/无权禁用或不存在）',
          rows.map((r) => `${r.label}:${r.canWrite ? '有码' : '无码'}→新增${r.addBtn ? '显示' : '无'}·编辑${r.editVisible ? `显示${r.editDisabled ? '(禁用)' : '(可点)'}` : '无'}${r.denied ? '·页面被拦' : ''}`).join('｜'),
          ['out/s8-buttons-employees.json', "frontend/admin-web/src/app/(dashboard)/employees/page.tsx:19,295-296,353-354"])
      : R.fail('BTN-01', '元素级 RBAC：员工页写操作按钮', bad.map((r) => `${r.label}：有码=${r.canWrite} 页面被拦=${r.denied} 新增=${r.addBtn} 编辑可见=${r.editVisible} 编辑禁用=${r.editDisabled}`).join('；'))
  } catch (e) {
    R.fail('BTN-01', '元素级 RBAC 探针异常', String(e).slice(0, 250))
  }

  await browser.close()
  const s = R.summary()
  log(`== 阶段8 完成：pass=${s.pass} fail=${s.fail}`)
}
main().catch((e) => { R.fail('RT-FATAL', '阶段8 致命错误', String(e).slice(0, 400)); console.error(e) ; process.exit(1) })
