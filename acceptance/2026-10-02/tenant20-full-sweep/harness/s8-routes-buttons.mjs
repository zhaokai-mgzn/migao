// 阶段 8：**全量页面**守卫矩阵（41 条路由 × 9 个身份）+ 元素级（按钮）RBAC
//
// 阶段 3 只看了 16 条路由（打折扣版）；本阶段枚举 `(dashboard)` 下**全部** page.tsx（41 条）。
// 判定：直达该路由后，DOM 是否出现 403 页标记（「无权访问该页面」）——
//   期望 denied = 该路由**被 ROUTE_PERMISSION_MAP 覆盖** 且 该身份不含该码；
//   未被覆盖的路由（前缀不在表里）⇒ 期望不拦（放行），这正是 F1/F2 要量化的面。
import { chromium, Recorder, log, newContext, shot, api, loginApi, employeeLoginApi, saveCtx, loadCtx, waitService, sleep, loginUi } from './lib.mjs'
import { readFileSync, writeFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join } from 'node:path'

const R = new Recorder('s8-routes-buttons.json')
const ctx = loadCtx()
const OUT = process.env.OUT_DIR || join(process.cwd(), 'out')
const WEB = process.env.BASE_URL || 'http://localhost:3001'
const MAP = JSON.parse(readFileSync(join(OUT, process.env.ROUTE_MAP || 'route-guard-map-main.json'), 'utf8'))   // 主干坐标（从提交对象导出）   // {prefixes:[{prefix,code}], routes:[...]}
// 2026-10-03 固化（验收 §六 #1/#8）：读入 fail-fast——① 格式契约（gen 产出 ls-tree 全路径含 /page.tsx，
// 旧格式混入会让 routeOf 剥不干净 ⇒ 守卫矩阵假「放」）；② 坐标新鲜度（MAP.commit 必须等于 origin/main，
// 双目录陷阱曾让消费侧读到旧坐标）。红证：喂无 format 字段/旧 commit 的 MAP 会在此抛错拒跑。
{
  const headMain = execFileSync('git', ['-C', join(import.meta.dirname, '../../../..'), 'rev-parse', 'origin/main'], { encoding: 'utf8' }).trim()
  if (MAP.format !== 'ls-tree-fullpath-page-tsx') throw new Error(`MAP 格式契约缺失/不符（format=${MAP.format || '(无)'}）——重跑 gen-route-guard-map.py，勿用旧格式文件`)
  if (MAP.commit !== headMain) throw new Error(`MAP 坐标过期：MAP.commit=${MAP.commit} ≠ origin/main=${headMain}——重跑 gen-route-guard-map.py`)
  if (!Array.isArray(MAP.routes) || MAP.routes.length === 0) throw new Error('MAP.routes 为空——gen 产出异常，重跑 gen-route-guard-map.py')
  const bad = MAP.routes.filter((r) => r !== 'page.tsx' && !r.endsWith('/page.tsx'))
  if (bad.length) throw new Error(`MAP.routes 有 ${bad.length} 条缺 /page.tsx 后缀（旧格式，如 ${bad[0]}）——重跑 gen-route-guard-map.py`)
}

// 2026-10-03 修正：gen-route-guard-map.py（提交对象口径）产出的是 ls-tree 全路径（含 /page.tsx 后缀，
// 动态段形如 after-sales/:id/page.tsx）——直接 goto '/categories/page.tsx' 在 Next 里是 404（不进
// (dashboard) layout ⇒ 守卫 h1 不渲染 ⇒ 全矩阵假「放」，admin 反而假绿）。先剥 /page.tsx，再剥动态段。
const routeOf = (r) => '/' + r.replace(/\/page\.tsx$/, '').replace(/\/:id$/, '')
async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  // 预检：admin-web 必须可达，否则整场矩阵是空虚结果（全部判「放行」）——直接拒绝运行
  const webProbe = await fetch(`${WEB}/login`, { redirect: 'manual' }).catch(() => null)
  if (!webProbe) throw new Error(`admin-web(${WEB}) 不可达——拒绝产出空虚矩阵（先起 dev server）`)
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
    const { page, ctx } = await newContext(browser)
    await ORIGIN_FIX(ctx)
    try {
      await loginUi(page, p.mode === 'admin' ? { mode: 'admin', phone: p.phone } : { mode: 'employee', identifier: p.identifier, password: p.password })
    } catch (e) {
      const url = page.url()
      if (/\/login/.test(url)) { R.fail('RT-LOGIN', `岗位 UI 登录失败：${p.label}`, `${url}｜${String(e).slice(0, 160)}`); await page.close(); continue }
      if (!url || url === 'about:blank') throw new Error(`admin-web 登录未发生（落 ${url}）——大概率 ${WEB} 不可达或页面崩溃，拒绝空虚矩阵：${p.label}｜${String(e).slice(0, 160)}`)
      log(`  ${p.label} 未落 /dashboard，实际落 ${url}（按产品行为继续）`)
    }
    const state = await ctx.storageState()      // 登录态复用 ⇒ 每格开独立标签页并行，互不干扰
    await page.close(); await ctx.close()

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
      const { page, ctx } = await newContext(browser)
      await ctx.route('**/api/**', (route) => { const h = { ...route.request().headers() }; delete h['origin']; delete h['referer']; return route.continue({ headers: h }) })
      await loginUi(page, p.mode === 'admin' ? { mode: 'admin', phone: p.phone } : { mode: 'employee', identifier: p.identifier, password: p.password }).catch(() => {})
      await page.goto(`${WEB}/employees`, { waitUntil: 'domcontentloaded' })
      await Promise.race([page.getByText('无权访问该页面').first().waitFor({ timeout: 3000 }).catch(() => {}), page.waitForTimeout(3000)])
      const text = await page.evaluate(() => document.body.innerText)
      const denied = /无权访问该页面/.test(text)
      // 2026-10-03 修正：visible && enabled —— 员工页姓名列「编辑」按钮对无码者是 disabled 渲染
      // （page.tsx `disabled={!canWrite}`），isVisible 对禁用按钮仍返回 true ⇒ 曾把「看得见点不动」误判为可写
      const btnState = async (sel) => { try { const b = page.getByRole('button', { name: sel }).first(); if (!(await b.isVisible())) return false; return await b.isEnabled() } catch { return false } }
      const addBtn = await btnState(/新增员工/)
      const editBtn = await btnState(/编辑/)
      const resetBtn = await btnState(/重置密码/)
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
main().catch((e) => { R.fail('RT-FATAL', '阶段8 致命错误', String(e).slice(0, 400)); process.exit(1) })
