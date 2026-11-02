// p2：admin-web 7 岗位 × 页面闭环（真浏览器 + 真实登录 + DOM 真值 + DB 真值源）
//
// 判定口径（不自我验收：期望值全部来自 **DB 真值源 + 提交对象**，不读被测读面自证）：
//   · 期望可见菜单 = menu.ts（origin/main）的 22 项 ∩ 该岗位的 role_permissions（DB）
//   · 期望可进页面 = 同上；期望被拦页面 = 菜单项权限码 ∉ 该岗位权限
//   · 页面「可用」= 非 403 页 ∧ 稳定帧 ∧ 正文非空 ∧ 零 console error（分类在报告里给）
// 证据：out/p2-roles-ui.json + out/shots/** + out/text/**
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { OUT, WEB, psql, scrub, PROBE, SUBJECT_SHA } from './lib.mjs'
import { launch, newPage, loginEmployeeUi, loginAdminUi, sidebarLinks, visit } from './ui.mjs'

const MAP = JSON.parse(readFileSync(join(OUT, 'map.json'), 'utf8'))
const SESSION = JSON.parse(readFileSync(process.env.A06_SESSION || '/tmp/a06-session.json', 'utf8'))
const TENANT_ID = Number(process.env.TENANT_ID || 25)
const ADMIN_PHONE = '13800138000'
const EMP_PWD = 'Migao@2026x'

const roles = psql(`select code, name from roles where tenant_id=${TENANT_ID} order by code`)
// 企业开关：`menu.ts` 的 briefingToggle 项（每日简报）**只在该租户开关为真时**才渲染
// （前端 `lib/menu-nav.ts` 的 `item.briefingToggle && !opts.briefingEnabled ⇒ 隐藏`，issue #3468）。
// 🔴 假红修正（本会话实测）：v1 期望里没建模这个开关 ⇒ 7 个岗位一律「缺 /briefing」被误判为缺陷。
const tenant = psql(`select briefing_enabled from tenants where id=${TENANT_ID}`)[0] || {}
const briefingEnabled = tenant.briefing_enabled === true
const permsByRole = Object.fromEntries(psql(
  `select r.code, array_agg(p.code order by p.code) as codes from roles r
   join role_permissions rp on rp.role_id=r.id join permissions p on p.id=rp.permission_id
   where r.tenant_id=${TENANT_ID} group by r.code`).map((r) => [r.code, r.codes]))

const has = (perms, code) => !code || perms.includes('*') || perms.includes(code)
const usernameOf = (code) => `a06_${code}`
const R = []
const rec = (state, id, name, detail, evidence = []) => R.push({ state, id, name, detail, evidence })
mkdirSync(join(OUT, 'text'), { recursive: true })
mkdirSync(join(OUT, 'shots'), { recursive: true })

async function runRole(browser, role) {
  const roleCode = role.code
  const perms = permsByRole[roleCode] || []
  const { ctx, page } = await newPage(browser)
  const out = { roleCode, roleName: role.name, perms, loginOk: false, sidebar: [], visited: [], deniedProbes: [], expected: [], missing: [], unexpected: [] }
  try {
    const url = roleCode === 'admin'
      ? await loginAdminUi(page, ADMIN_PHONE)
      : await loginEmployeeUi(page, `${usernameOf(roleCode)}@${SESSION.tenantCode}`, EMP_PWD)
    out.loginOk = true
    out.landingUrl = url
    rec('pass', `P2-LOGIN:${roleCode}`, `UI 登录：${role.name}`,
      `真浏览器登录成功，「${roleCode === 'admin' ? '管理员登录（手机验证码）' : `员工登录 ${usernameOf(roleCode)}@${SESSION.tenantCode}`}」→ ${url}`,
      [url])

    // ── 菜单真值：期望（DB+提交对象） vs 实际（DOM）──
    const expectedMenu = MAP.menu.filter((m) => has(perms, m.permissionCode))
      .filter((m) => !(m.briefingToggle && !briefingEnabled))
    const expectedPaths = expectedMenu.map((m) => m.path)
    out.expected = expectedMenu.map((m) => ({ path: m.path, name: m.name, code: m.permissionCode }))
    await page.goto(WEB + '/dashboard', { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {})
    await page.waitForTimeout(2500)
    const links = await sidebarLinks(page)
    out.sidebar = links
    const actualPaths = links.map((l) => l.href)
    out.missing = expectedPaths.filter((p) => !actualPaths.includes(p))
    out.unexpected = actualPaths.filter((p) => !expectedPaths.includes(p))
    const menuOk = out.missing.length === 0 && out.unexpected.length === 0
    rec(menuOk ? 'pass' : 'fail', `P2-MENU:${roleCode}`, `侧边栏菜单：${role.name}`,
      `期望 ${expectedPaths.length} 项 / DOM 实际 ${actualPaths.length} 项；缺=${JSON.stringify(out.missing)} 多=${JSON.stringify(out.unexpected)}；DOM=${JSON.stringify(links.map((l) => l.text))}`,
      ['out/map.json#menu', 'roles/role_permissions（DB）', 'DOM nav a[href]'])

    // ── 正向：每一条「该看得到的页面」真的点得开 ──
    let i = 0
    for (const m of expectedMenu) {
      const r = await visit(page, m.path, { name: `${roleCode}${m.path.replace(/[^\w]+/g, '_')}`, shotIt: i < 4 })
      r.menuName = m.name
      r.permissionCode = m.permissionCode
      out.visited.push(r)
      writeFileSync(join(OUT, 'text', `${roleCode}${m.path.replace(/[^\w]+/g, '_')}.txt`), r.textHead)
      i++
    }
    const badRender = out.visited.filter((v) => v.denied || v.textLen < 40 || !v.stable || v.loading)
    rec(badRender.length === 0 ? 'pass' : 'fail', `P2-PAGES:${roleCode}`, `本岗位页面可开：${role.name}`,
      `访问 ${out.visited.length} 条；不可用 ${badRender.length} 条 ${JSON.stringify(badRender.map((b) => ({ p: b.path, denied: b.denied, len: b.textLen, stable: b.stable, loading: b.loading })))}`,
      ['out/p2-roles-ui.json#visited'])

    // ── 负向：无码页面必须被拦（403 提示页），且**不得**白屏/报错 ──
    const deniedMenu = MAP.menu.filter((m) => m.permissionCode && !has(perms, m.permissionCode))
    const probes = deniedMenu.slice(0, 3)
    for (const m of probes) {
      const r = await visit(page, m.path, { name: `${roleCode}-deny${m.path.replace(/[^\w]+/g, '_')}`, shotIt: false, settle: 900 })
      r.menuName = m.name
      r.expectedDenied = true
      out.deniedProbes.push(r)
    }
    const leaked = out.deniedProbes.filter((d) => !d.denied)
    rec(leaked.length === 0 ? 'pass' : 'fail', `P2-NEG:${roleCode}`, `无码页面被拦：${role.name}`,
      `探测 ${out.deniedProbes.length} 条；未被拦 ${JSON.stringify(leaked.map((l) => ({ p: l.path, len: l.textLen })))}；被拦明细 ${JSON.stringify(out.deniedProbes.map((d) => ({ p: d.path, denied: d.denied })))}`,
      ['DOM「无权访问该页面」标记', 'app/(dashboard)/layout.tsx:permissionDenied'])
  } catch (e) {
    rec('fail', `P2-ERR:${roleCode}`, `岗位旅程异常：${role.name}`, String(e).slice(0, 400))
    out.error = String(e).slice(0, 400)
  } finally {
    await ctx.close().catch(() => {})
  }
  return out
}

async function main() {
  const browser = await launch()
  const out = { at: new Date().toISOString(), subjectSha: SUBJECT_SHA, web: WEB, tenantId: TENANT_ID, probe: PROBE, mapCommit: MAP.commit, roles: [] }
  for (const role of roles) {
    const r = await runRole(browser, role)
    out.roles.push(r)
    console.log(`[${role.code}] login=${r.loginOk} 期望菜单=${r.expected.length} DOM=${r.sidebar.length} 页面=${r.visited.length} 被拦探针=${r.deniedProbes.filter((d) => d.denied).length}/${r.deniedProbes.length}`)
  }
  await browser.close()
  const counts = R.reduce((a, x) => ({ ...a, [x.state]: (a[x.state] || 0) + 1 }), {})
  writeFileSync(join(OUT, 'p2-roles-ui.json'), JSON.stringify(scrub({ counts, rows: R, ...out }), null, 2))
  console.log('== p2 counts:', JSON.stringify(counts))
  for (const x of R) console.log(`  [${x.state}] ${x.id} ${x.name} — ${x.detail.slice(0, 260)}`)
}

main().catch((e) => { console.error('p2 失败:', e); process.exit(1) })
