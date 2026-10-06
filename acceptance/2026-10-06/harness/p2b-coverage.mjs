// p2b：岗位 × 路由 **覆盖率补齐**（正向 7 岗位 × 全部 40 条路由 + 负向 65 个「岗位 × 无码菜单页」组合）
//
// ── 为什么写这个 ────────────────────────────────────────────────────────────────
// 2026-10-06 首轮 p2-roles-ui.mjs 的正向只访问了**各岗位的菜单顶层页**（82 次访问 / 并集 21 条路径），
// 而 out/map.json#routes 共 **40 条**（19 条 0 次访问）；负向每岗位只抽 3 条无码页（共 17 条），
// 而「岗位 × 无码菜单页」组合共 **65 个**（48 个未探）。GLM 复核判「覆盖不足」。
// 本脚本**只做补齐**：不改产品代码、不改既有 harness 文件（lib.mjs / ui.mjs / q.mjs / p1 / p7 一律只 import）。
//
// ── 期望值从哪来（全部可从产物 + DB 复算，**不读被测读面自证**）─────────────────────
//   ① 路由清单  = out/map.json#routes   —— gen-map.py 用 `git ls-tree origin/main:frontend/admin-web/src/app/(dashboard)`
//                 收集 **/page.tsx 导出（40 条，含 7 条动态段 `[id]` → `:id`）。
//   ② 守卫映射  = out/map.json#prefixes —— 同上从 `(dashboard)/layout.tsx` 的 `ROUTE_PERMISSION_MAP` **按文件顺序**导出。
//                 判定语义**照抄产品代码**（`frontend/admin-web/src/app/(dashboard)/layout.tsx:92`）：
//                   `ROUTE_PERMISSION_MAP.find(r => pathname.startsWith(r.prefix))?.code`
//                 ⇒ 是**首次命中（数组序）**，不是最长前缀。本脚本按数组序取首个命中，
//                   并额外断言「数组序首个命中 == 最长前缀」（不等则计入 orderDivergence，见产物）。
//   ③ 岗位权限  = DB 真值源 `roles ⨝ role_permissions ⨝ permissions`（tenant_id=25），**每次运行现取**。
//   ⇒ 期望「可进」= 命中前缀的码 ∈ 该岗位权限；命中前缀但无该码 ⇒ 期望「被拦（403 提示页）」；
//      **无任何前缀命中 ⇒ no-guard**（无守卫，期望值不可判定 ⇒ 记 skip，**不是 pass**）。
//   ④ 动态段路由（含 `/:`）本轮**无夹具 id** ⇒ 一律 skip，理由逐字写「动态段无夹具」，
//      **不伪装成 pass/fail**（不给"没有 id 就当作能进"这种空断言）。
//
// ── 四态口径（migao-acceptance：skip 永不折算 pass）──────────────────────────────
//   pass        判据命中且与期望一致（expected-deny 且 DOM 含「无权访问该页面」/ expected-allow 且未被拦且可渲染）
//   fail(产品)  与期望相反（无码路由未拦 = 泄漏；有码路由被拦 = 误拦；有码路由停加载态/空白/404）
//   skip(未覆盖) 动态段无夹具 / no-guard（无前缀覆盖，期望不可判定）
//   假红(判据缺陷) 判据自身失效的已识别形态（如 alternate-block：页面被别的方式拦住，DOM 无 403 卡片）
//
// ── 证据 ──────────────────────────────────────────────────────────────────────
//   out/p2b-coverage.json（逐条读数 + 计数）· out/shots/p2b_*.png（每岗位 ≤6 张）· out/text-p2b/**（异常条目全文）
//   纪律：产物一律 scrub() 脱敏（不落活 token，issue #6303）；写操作只碰本轮探针对象（前缀 A06验收）。
//
// 用法：node p2b-coverage.mjs
//   P2B_SMOKE=1        只跑 1 个岗位 × 前 3 条静态路由（冒烟，产物写 out/p2b-coverage.smoke.json）
//   P2B_ROLES=a,b      只跑指定岗位   P2B_SHOTS=n  每岗位截图上限（默认 6）
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { OUT, WEB, psql, scrub, PROBE, SUBJECT_SHA, log } from './lib.mjs'
import { launch, newPage, loginEmployeeUi, loginAdminUi, visit, bodyText } from './ui.mjs'

const MAP = JSON.parse(readFileSync(join(OUT, 'map.json'), 'utf8'))
const SESSION = JSON.parse(readFileSync(process.env.A06_SESSION || '/tmp/a06-session.json', 'utf8'))
const TENANT_ID = Number(process.env.TENANT_ID || 25)
const ADMIN_PHONE = process.env.ADMIN_PHONE || '13800138000'
const EMP_PWD = process.env.EMP_PWD || 'Migao@2026x'
const SHOT_PER_ROLE = Number(process.env.P2B_SHOTS || 6)
const SMOKE = process.env.P2B_SMOKE === '1'
const ONLY_ROLES = (process.env.P2B_ROLES || '').split(',').map((s) => s.trim()).filter(Boolean)

const isDynamic = (p) => p.includes('/:')
const roleVals = {}

/** 产品语义（layout.tsx:92 `find` ⇒ **数组序首次命中**）。 */
function guardOf(pathname) {
  const byOrder = MAP.prefixes.find((p) => pathname.startsWith(p.prefix)) || null
  const byLen = MAP.prefixes
    .filter((p) => pathname === p.prefix || pathname.startsWith(p.prefix + '/'))
    .sort((a, b) => b.prefix.length - a.prefix.length)[0] || null
  return { byOrder, byLen, diverged: byOrder?.prefix !== byLen?.prefix }
}

const has = (perms, code) => !!code && (perms.includes('*') || perms.includes(code))

async function main() {
  const permsByRole = Object.fromEntries(psql(
    `select r.code, array_agg(p.code order by p.code) as codes from roles r
     join role_permissions rp on rp.role_id=r.id join permissions p on p.id=rp.permission_id
     where r.tenant_id=${TENANT_ID} group by r.code`).map((r) => [r.code, r.codes]))

  const allRoles = psql(`select code, name from roles where tenant_id=${TENANT_ID} order by code`)
  const ORDER = ['admin', 'customer_service', 'operator', 'sales', 'finance', 'product_manager', 'knowledge_editor']
  const roles = [
    ...ORDER.map((c) => allRoles.find((r) => r.code === c)).filter(Boolean),
    ...allRoles.filter((r) => !ORDER.includes(r.code)),
  ].filter((r) => !ONLY_ROLES.length || ONLY_ROLES.includes(r.code))
  if (SMOKE) roles.splice(1)

  // 路由清单（动态段单独列出，不参与"访问"）
  const routes = SMOKE ? MAP.routes.filter((r) => !isDynamic(r)).slice(0, 3) : MAP.routes
  const staticRoutes = routes.filter((r) => !isDynamic(r))
  const dynamicRoutes = routes.filter(isDynamic)

  log(`== p2b 覆盖补齐 tenant=${TENANT_ID} subjectSha=${SUBJECT_SHA} mapCommit=${MAP.commit.slice(0, 9)}`)
  log(`   routes=${MAP.routes.length}（动态段 ${MAP.routes.filter(isDynamic).length} ⇒ skip）prefixes=${MAP.prefixes.length} menu=${MAP.menu.length} roles=${roles.length}`)

  const browser = await launch()
  const R = []          // 逐条读数
  const negRows = []    // 负向逐条
  const orderDivergence = []

  for (const role of roles) {
    const perms = permsByRole[role.code] || []
    const rec = (state, id, name, detail, evidence = []) => R.push({ state, id, role: role.code, name, detail, evidence })
    const { ctx, page } = await newPage(browser)
    let shotBudget = SHOT_PER_ROLE
    try {
      const url = role.code === 'admin'
        ? await loginAdminUi(page, ADMIN_PHONE)
        : await loginEmployeeUi(page, `a06_${role.code}@${SESSION.tenantCode}`, EMP_PWD)
      rec('pass', `P2B-LOGIN:${role.code}`, `UI 登录：${role.name}`,
        `真浏览器登录成功 → ${url}；perms(DB)=${perms.length}`, ['roles/role_permissions（DB）'])
    } catch (e) {
      rec('fail', `P2B-LOGIN:${role.code}`, `UI 登录：${role.name}`,
        `登录失败：${String(e).slice(0, 200)}（后续 0 条路由可判 ⇒ 本岗位全部 skip）`, [])
      for (const rt of staticRoutes) R.push({ state: 'skip', id: `P2B-POS:${role.code}:${rt}`, role: role.code, name: rt, detail: '前置不成立：本岗位登录失败 ⇒ 未覆盖', evidence: [] })
      await ctx.close().catch(() => {})
      continue
    }

    // ── 正向全覆盖：逐条路由 ──────────────────────────────────────────────
    const roleVisits = {}
    for (const rt of routes) {
      const dyn = isDynamic(rt)
      const g = dyn ? { byOrder: null, byLen: null, diverged: false } : guardOf(rt)
      if (g.diverged) orderDivergence.push({ role: role.code, route: rt, byOrder: g.byOrder.prefix, byLen: g.byLen.prefix })
      const guardCode = g.byOrder?.code || null
      const expect = dyn ? 'skip' : (!g.byOrder ? 'no-guard' : (has(perms, guardCode) ? 'allow' : 'deny'))

      if (dyn) {
        R.push({
          state: 'skip', id: `P2B-POS:${role.code}:${rt}`, role: role.code, name: rt,
          detail: '动态段无夹具：路由含 `/:`，本轮无夹具 id（未取到 orders/products/after-sales 的实体 id）⇒ 未覆盖，不伪装 pass/fail',
          evidence: ['out/map.json#routes'], route: rt, kind: 'dynamic', expect, guardCode, guardPrefix: null,
          denied: null, loading: null, stable: null, textLen: null, consoleErrors: [],
        })
        continue
      }

      const name = `p2b_${role.code}${rt.replace(/[^\w]+/g, '_')}`
      const shotIt = shotBudget > 0
      if (shotIt) shotBudget--
      const v = await visit(page, rt, { name, shotIt, settle: 900, maxWait: 18000 })
      const full = await bodyText(page).catch(() => v.textHead)
      const notFound = /This page could not be found|页面不存在|404 Not Found|找不到该页面/i.test(full)
      let state, subtype, note
      if (expect === 'deny') {
        if (v.denied) { state = 'pass'; subtype = 'blocked'; note = '无码路由被拦：DOM 含「无权访问该页面」' }
        else { state = 'fail'; subtype = 'permission-leak'; note = '无码路由**未**被拦（DOM 无「无权访问该页面」）' }
      } else if (expect === 'no-guard') {
        state = 'skip'; subtype = 'no-guard'
        note = 'no-guard：map.json#prefixes 无前缀覆盖该路由 ⇒ 无守卫码，期望不可判定 ⇒ 不判 pass；' +
               (v.denied ? '实测被拦（另有来源）' : '实测可进（与 menu.ts 的 permissionCode=null 一致）')
      } else { // allow
        if (v.denied) { state = 'fail'; subtype = 'false-deny'; note = '有码路由被**误拦**（403 提示页）' }
        else if (notFound) { state = 'fail'; subtype = 'route-404'; note = '有码路由落到「页面未找到」' }
        else if (v.loading) { state = 'fail'; subtype = 'stuck-loading'; note = '有码路由 18s 内仍停在加载态（非稳定帧）' }
        else if (!v.stable) { state = 'fail'; subtype = 'unstable'; note = '有码路由取不到稳定帧' }
        else if (v.textLen < 40) { state = 'fail'; subtype = 'blank'; note = '有码路由正文 <40 字（疑似空白页）' }
        else { state = 'pass'; subtype = 'rendered'; note = '有码路由可进且渲染出正文' }
      }
      const row = {
        state, id: `P2B-POS:${role.code}:${rt}`, role: role.code, name: rt, detail: note,
        evidence: ['out/map.json#prefixes（layout.tsx:92 find 语义）', 'roles/role_permissions（DB）', `out/p2b-coverage.json#roles[${role.code}].routeVisits`],
        route: rt, kind: 'static', expect, guardCode, guardPrefix: g.byOrder?.prefix || null,
        denied: v.denied, loading: v.loading, stable: v.stable, textLen: v.textLen, tries: v.tries, ms: v.ms,
        notFound, consoleErrors: v.errors || [], textHead: v.textHead, url: v.url, shot: v.shot || null, subtype,
      }
      R.push(row)
      roleVisits[rt] = {
        state, expect, guardCode, guardPrefix: g.byOrder?.prefix || null, denied: v.denied,
        loading: v.loading, stable: v.stable, textLen: v.textLen, notFound, consoleErrors: (v.errors || []).length,
        url: v.url, shot: v.shot || null, textHead: v.textHead,
      }
      if (state === 'fail' || v.loading || !v.stable || v.textLen < 80) {
        mkdirSync(join(OUT, 'text-p2b'), { recursive: true })
        writeFileSync(join(OUT, 'text-p2b', `${role.code}${rt.replace(/[^\w]+/g, '_')}.txt`), full)
      }
    }

    // ── 负向全覆盖：该岗位**所有**无码菜单页组合（逐条真探，不复用正向读数）──
    const deniedMenu = MAP.menu.filter((m) => m.permissionCode && !has(perms, m.permissionCode))
    const neg = []
    for (const m of deniedMenu) {
      const v = await visit(page, m.path, { name: `p2b-neg_${role.code}${m.path.replace(/[^\w]+/g, '_')}`, shotIt: false, settle: 900, maxWait: 18000 })
      const row = {
        role: role.code, roleName: role.name, path: m.path, menuName: m.name, permissionCode: m.permissionCode,
        denied: v.denied, loading: v.loading, stable: v.stable, textLen: v.textLen, ms: v.ms,
        consoleErrors: v.errors || [], textHead: v.textHead, url: v.url,
        state: v.denied ? 'pass' : 'fail',
        detail: v.denied ? 'DOM 含「无权访问该页面」（断言命中）' : 'DOM **无**「无权访问该页面」（断言未命中）',
      }
      neg.push(row)
      negRows.push(row)
      R.push({
        state: row.state, id: `P2B-NEG:${role.code}:${m.path}`, role: role.code, name: `${role.name} 无码页 ${m.name}（${m.path}）`,
        detail: `${row.detail}；需码 ${m.permissionCode}（该岗位 DB 权限内无此码）；textLen=${v.textLen} loading=${v.loading} stable=${v.stable}`,
        evidence: ['DOM「无权访问该页面」标记（layout.tsx:145）', 'out/map.json#menu + roles/role_permissions（DB）', 'out/p2b-coverage.json#negative'],
      })
    }
    const leaked = neg.filter((n) => !n.denied)
    const exOf = (r) => { const g = guardOf(r); return g.byOrder ? (has(perms, g.byOrder.code) ? 'allow' : 'deny') : 'no-guard' }
    const exCount = (k) => staticRoutes.filter((r) => exOf(r) === k).length
    log(`[${role.code}] 正向 static ${staticRoutes.length}：allow=${exCount('allow')} deny=${exCount('deny')} no-guard=${exCount('no-guard')}；负向组合 ${neg.length} 条，未拦 ${leaked.length} 条`)

    // 本岗位负向汇总成一行判定（逐条明细在上面 negRows）
    rec(leaked.length === 0 ? 'pass' : 'fail', `P2B-NEG-ALL:${role.code}`,
      `负向全覆盖（${role.name}）：${neg.length} 个无码菜单页组合`,
      `逐条探测 ${neg.length} 条；**未被拦 ${leaked.length} 条** ${JSON.stringify(leaked.map((l) => ({ p: l.path, len: l.textLen, head: l.textHead.slice(0, 80) })))}`,
      ['out/p2b-coverage.json#negative'])

    roleVals[role.code] = { roleCode: role.code, roleName: role.name, perms, routeVisits: roleVisits, negative: neg }
    await ctx.close().catch(() => {})
  }

  await browser.close()

  const counts = R.reduce((a, r) => ({ ...a, [r.state]: (a[r.state] || 0) + 1 }), {})
  const leakedAll = negRows.filter((n) => !n.denied)
  const out = {
    at: new Date().toISOString(), subjectSha: SUBJECT_SHA, web: WEB, tenantId: TENANT_ID, probe: PROBE,
    mapCommit: MAP.commit, smoke: SMOKE,
    guardSource: 'frontend/admin-web/src/app/(dashboard)/layout.tsx:92（find ⇒ 数组序首次命中）',
    expectationSource: 'out/map.json#routes（origin/main 的 page.tsx 清单）+ out/map.json#prefixes + DB roles⨝role_permissions⨝permissions(tenant=25) 现取',
    coverage: {
      routesTotal: MAP.routes.length,
      routesStatic: MAP.routes.filter((r) => !isDynamic(r)).length,
      routesDynamicSkipped: MAP.routes.filter(isDynamic).length,
      routesNoGuard: MAP.routes.filter((r) => !isDynamic(r) && !guardOf(r).byOrder).length,
      routeVisits: staticRoutes.length * roles.length,
      negativeCombos: negRows.length,
      negativeLeaked: leakedAll.length,
      orderDivergence,
    },
    counts, rows: R, roles: roleVals, negative: negRows,
  }
  const file = SMOKE ? 'p2b-coverage.smoke.json' : 'p2b-coverage.json'
  writeFileSync(join(OUT, file), JSON.stringify(scrub(out), null, 2))
  log(`== p2b counts: ${JSON.stringify(counts)}（产物 ${file}；负向 ${negRows.length} 条未拦 ${leakedAll.length}）`)
  for (const r of R.filter((x) => x.state !== 'pass')) log(`  [${r.state}] ${r.id} — ${String(r.detail).slice(0, 200)}`)
}

main().catch((e) => { console.error('p2b 失败:', e); process.exit(1) })
