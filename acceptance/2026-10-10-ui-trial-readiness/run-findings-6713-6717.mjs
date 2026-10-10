/**
 * P17–P20 重放仪器（先红后绿的"绿证"侧；修前用它应当**红**）
 *   V17 #6713  /chat 读失败 ⇒ **不得**渲染「暂无会话」；须有常驻失败面 + 重试
 *   V18 #6714  /employees /notifications /products 读失败 ⇒ 同；/shipments ⇒ 不得只剩空表无信号
 *   V19 #6715  /dashboard **冷启动**（登录前挂 500，全程无成功加载）⇒ 不得印「共 0 单」；
 *              且横幅文案不得与屏上事实矛盾（不得一边承诺"不是 0、也不是暂无数据"，一边屏上两者都在）
 *   V20 #6717  /orders(1440 与 1280) /inbound-orders(1280) /processing-orders(1280) /production(1280)
 *              ⇒ 「状态」列可见（/orders）；「操作」列每个行内按钮中心点自击命中
 *
 * 用法：node acceptance/2026-10-10-ui-trial-readiness/run-findings-6713-6717.mjs
 * 退出码：0 = 全绿；1 = 有红（打印逐条判定与屏上原文）
 */
import { createRequire } from 'node:module'
import { mkdirSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
const require = createRequire('/Users/guangzhen.zk/ai native/migao/tests/package.json')
const { chromium } = require('@playwright/test')
const OUT = fileURLToPath(new URL('./evidence/', import.meta.url))
mkdirSync(OUT, { recursive: true })
const BASE = 'http://localhost:3001'
const browser = await chromium.launch({ channel: 'chrome' })
const fails = []
const rep = (id, ok, detail) => { console.log(`${ok ? '✅' : '❌'} ${id} ${detail}`); if (!ok) fails.push(`${id} ${detail}`) }

const login = async (page) => {
  await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('input', { timeout: 90000 })
  await page.waitForTimeout(1500)
  try { await page.getByRole('tab', { name: /管理员登录/ }).first().click({ timeout: 8000 }) } catch { await page.getByText('管理员登录', { exact: false }).first().click({ timeout: 8000 }).catch(() => {}) }
  await page.getByLabel('手机号', { exact: false }).first().fill('13800138000')
  await page.getByLabel('验证码', { exact: false }).first().fill('123456')
  await page.getByRole('button', { name: /登\s*录/ }).first().click()
  await page.waitForURL((u) => !/^\/login\b/.test(u.pathname), { timeout: 40000 })
}
const INJ = (r) => r.fulfill({ status: 500, contentType: 'application/json', body: '{"success":false,"error":{"code":"INTERNAL_ERROR"}}' })
const probe = (page) => page.evaluate(() => {
  const t = document.body.innerText || ''
  const tid = Array.from(document.querySelectorAll('[data-testid]')).map((e) => e.getAttribute('data-testid') || '')
  return {
    empty: (t.match(/暂无[^\s，。|]*|还没有[^\s，。|]*/g) || []).slice(0, 3),
    zero: (t.match(/共\s?0\s?[条块件单]/g) || []).slice(0, 3),
    failWords: (t.match(/读不到|读取失败|加载失败|暂时|稍后重试/g) || []).length,
    anchors: tid.filter((x) => /load-error|load-failed|retry/i.test(x)),
    rows: document.querySelectorAll('tbody tr').length,
  }
})

// ── V17/V18 读失败 ⇄ 空态
const ctx1 = await browser.newContext({ viewport: { width: 1440, height: 980 } })
const p1 = await ctx1.newPage()
await login(p1)
// ⚠️ `/customers` 是 #6728 用**调用图普查**发现的同类第三例（同一形态同一根因：早有常驻失败面，
//    唯独共享 `ui/Table` 仍继承默认「暂无数据」）⇒ 一并纳入重放，否则本批的"类普查"成果就没人重放。
// ⚠️ `/orders` 是**运行期类普查**（35 路由失败注入）抓出来的同族第 4 处：它用的是**自定义表**，
//    不在「共享 ui/Table」的调用图射程内 ⇒ #6728 的调用图普查自然看不到（射程盲区，不是判据写错）。
//    并入重放：本页读失败时**不得**印「暂无数据」（同屏「共 — 条」已在说"不可知"）。
for (const path of ['/chat', '/employees', '/notifications', '/products', '/shipments', '/customers', '/orders']) {
  await p1.route('**/api/admin/**', INJ)
  await p1.goto(BASE + path, { waitUntil: 'domcontentloaded' })
  await p1.waitForTimeout(6000)
  const m = await probe(p1)
  const hasSurface = m.anchors.length > 0 || m.failWords >= 2
  rep('读失败⇄空态', hasSurface && m.empty.length === 0, `${path} 空态=${JSON.stringify(m.empty)} 零值=${JSON.stringify(m.zero)} 失败词=${m.failWords} 锚点=${m.anchors.slice(0, 2).join(',') || '无'}`)
  // 修复包点名的两项「判据判不了」的版面检查（§31 P1）
  if (path === '/chat') {
    const g = await p1.evaluate(() => {
      // ⚠️ 不要用 document.querySelector('aside')：那是**左侧主导航**（收起态仅 64px），
      //    而本判据要的是**会话列表侧栏**（`w-64` ≈ 256px）。改用失败块的**父容器**当参照，
      //    否则断言瞄错元素 ⇒ 修完也假红（实测踩过）。
      const fail = document.querySelector('[data-testid*="load-failed"],[data-testid*="load-error"]')
      const fr = fail ? fail.getBoundingClientRect() : null
      const host = fail && fail.parentElement ? fail.parentElement.getBoundingClientRect() : null
      const list = document.querySelector('[data-testid*="session-list"],[class*="overflow-y-auto"]')
      const lr = list ? list.getBoundingClientRect() : null
      return {
        hostW: host ? Math.round(host.width) : null,
        failW: fr ? Math.round(fr.width) : null, failH: fr ? Math.round(fr.height) : null,
        failClipped: fail ? fail.scrollHeight > fail.clientHeight + 2 : null,
        listH: lr ? Math.round(lr.height) : null,          // 列表区残余高度：失败块不许把它吃光
        failText: fail ? (fail.innerText || '').replace(/\n/g, ' ').slice(0, 70) : null,
      }
    })
    rep('chat 失败面在侧栏内够显眼', !!g.failW && g.failW <= (g.hostW || 0) + 4 && g.failH >= 24 && g.failClipped === false && (g.listH === null || g.listH >= 120), JSON.stringify(g))
    await p1.screenshot({ path: OUT + 'S13-chat-failure-sidebar.png' })
  }
  if (path === '/products') {
    const g = await p1.evaluate(() => {
      const fail = document.querySelector('[data-testid*="load-failed"],[data-testid*="load-error"]')
      const table = document.querySelector('table')
      const fy = fail ? Math.round(fail.getBoundingClientRect().top) : null
      const ty = table ? Math.round(table.getBoundingClientRect().top) : null
      return { failTop: fy, tableTop: ty, above: fy !== null && ty !== null ? fy < ty : null, rows: document.querySelectorAll('tbody tr').length }
    })
    rep('products 失败面在表之上（版式不抖）', g.above === true, JSON.stringify(g))
    await p1.screenshot({ path: OUT + 'S13-products-failure.png' })
  }
  await p1.unroute('**/api/admin/**')
}

// ── V19 工作台冷启动
const ctx2 = await browser.newContext({ viewport: { width: 1440, height: 980 } })
const p2 = await ctx2.newPage()
await p2.route('**/api/admin/dashboard/**', INJ)   // ★ 登录前就挂 ⇒ 全程无成功加载
await login(p2)
await p2.waitForTimeout(6000)
const d = await p2.evaluate(() => {
  const t = document.body.innerText || ''
  return { zero: (t.match(/共\s?0\s?单/g) || []).length, empty: (t.match(/暂无[^\s，。|]*/g) || []).length, yuan0: (t.match(/¥\s?0(\.00)?/g) || []).length, banner: /上次成功取到的值/.test(t), failBanner: !!document.querySelector('[data-testid="dashboard-load-failed"]') }
})
rep('冷启动不印共 0 单', d.zero === 0, `屏上「共 0 单」=${d.zero} 次`)
rep('冷启动横幅不与屏上事实矛盾', !(d.banner && (d.empty > 0 || d.zero > 0)), `横幅承诺"上次成功值"=${d.banner} 而屏上「暂无…」=${d.empty} 处、「共 0 单」=${d.zero} 处`)
rep('冷启动不印 ¥0', d.yuan0 === 0, `¥0=${d.yuan0} 次；失败面=${d.failBanner}`)

// ── V21 会话监控页读失败（#6721）
{
  const c = await browser.newContext({ viewport: { width: 1440, height: 980 } })
  const pg = await c.newPage()
  // ⚠️ 该读面**直连 ai-agent**（`lib/api.ts` 的 `NEXT_PUBLIC_AI_API_BASE_URL || http://localhost:8001`），
  //    不走同源 `/api/admin/**` ⇒ 注入必须打这个 URL；打错面 ⇒ 判据**永远绿**（空断言，本批已踩过同类）。
  await pg.route('**/api/chat/sessions*', INJ)
  await login(pg)
  await pg.goto(BASE + '/agent-workspace/sessions', { waitUntil: 'domcontentloaded' })
  await pg.waitForTimeout(6500)
  const s = await pg.evaluate(() => {
    const t = document.body.innerText || ''
    // ⚠️ 数字与标签之间**可能有空白/换行**（实测屏上是 `0\n活跃`）⇒ 正则必须容忍，否则"0 活跃"读成 0 处（假绿）
    return {
      zeroCells: (t.match(/0\s*活跃|0\s*已结束|0\s*共/g) || []).length,
      dashCells: (t.match(/—\s*活跃|—\s*已结束|—\s*共/g) || []).length,
      anchors: Array.from(document.querySelectorAll('[data-testid$="-load-failed"]')).map((e) => e.getAttribute('data-testid')),
      retries: document.querySelectorAll('[data-testid$="-load-failed-retry"]').length,
    }
  })
  rep('会话页读失败不印 0', s.zeroCells === 0 && s.dashCells >= 3, `零值格=${s.zeroCells} 破折号格=${s.dashCells}`)
  rep('会话页有常驻失败面与重试', s.anchors.length >= 1 && s.retries >= 1, `锚点=${s.anchors.join(',') || '无'} 重试=${s.retries}`)
  await c.close()
}

// ── V20 宽表可达性
for (const vp of [{ w: 1440, h: 980, pages: ['/orders'] }, { w: 1280, h: 800, pages: ['/orders', '/inbound-orders', '/processing-orders', '/production'] }]) {
  const c = await browser.newContext({ viewport: { width: vp.w, height: vp.h } })
  const pg = await c.newPage()
  await login(pg)
  for (const path of vp.pages) {
    await pg.goto(BASE + path, { waitUntil: 'domcontentloaded' })
    await pg.waitForTimeout(4000)
    const g = await pg.evaluate(() => {
      const ths = Array.from(document.querySelectorAll('th'))
      const status = ths.find((t) => (t.textContent || '').trim() === '状态')
      // 行内操作按钮：取表体末列里的 button/a
      const btns = Array.from(document.querySelectorAll('tbody tr')).slice(0, 3).map((tr) => Array.from(tr.querySelectorAll('button, a')).slice(-2)).flat().filter(Boolean).slice(0, 4)
      const hits = btns.map((b) => {
        const r = b.getBoundingClientRect()
        const cx = Math.round(r.left + r.width / 2), cy = Math.round(r.top + r.height / 2)
        if (cx < 0 || cx > window.innerWidth || cy < 0 || cy > window.innerHeight) return { txt: (b.textContent || '').trim().slice(0, 6), hitSelf: false, why: '在视口外' }
        // 临时移开常驻浮球，避免把"被浮球挡"误读成"列不可达"
        const fab = Array.from(document.querySelectorAll('button')).find((e) => getComputedStyle(e).position === 'fixed' && e.getBoundingClientRect().width > 40)
        const saved = fab ? fab.style.display : null
        if (fab) fab.style.display = 'none'
        const el = document.elementFromPoint(cx, cy)
        if (fab) fab.style.display = saved || ''
        const hitSelf = !!el && (el === b || b.contains(el))
        return { txt: (b.textContent || '').trim().slice(0, 6), hitSelf, why: el ? el.tagName + '.' + String(el.className).slice(0, 20) : 'null' }
      })
      return {
        statusVisible: status ? status.getBoundingClientRect().left < window.innerWidth && status.getBoundingClientRect().right > 0 : null,
        statusLeft: status ? Math.round(status.getBoundingClientRect().left) : null,
        hits,
      }
    })
    if (path === '/orders') rep('状态列可见', g.statusVisible === true, `${vp.w}px 下 状态列 left=${g.statusLeft}`)
    const ok = g.hits.length > 0 && g.hits.every((h) => h.hitSelf)
    rep('操作列按钮自击', ok, `${vp.w}px ${path} 命中=${JSON.stringify(g.hits)}`)
  }
  await c.close()
}

// ── V22 冻结列在**选中态**必须不透明（#6729）
//    ⚠️ 触发面 = **选中态**（#6717 给冻结格写的是 `bg-inherit`，继承 `<tr>` 的半透明选中底色
//    `bg-primary-50/40` ⇒ alpha 0.4 ⇒ 横滚时下层列穿透叠印）。**hover 不触发**（实测），
//    所以判据必须打在选中态上；打在 hover 或未选中态上是**永远绿的空断言**。
{
  const c = await browser.newContext({ viewport: { width: 1440, height: 980 } })
  const pg = await c.newPage()
  await login(pg)
  await pg.goto(BASE + '/orders', { waitUntil: 'domcontentloaded' })
  await pg.waitForTimeout(4500)
  const readAlpha = () => pg.evaluate(() => {
    const row = document.querySelector('tbody tr')
    if (!row) return { err: '无数据行' }
    const cells = Array.from(row.querySelectorAll('td'))
    const frozen = cells[cells.length - 1]
    const alphaOf = (el) => {
      const m = (getComputedStyle(el).backgroundColor || '').match(/rgba?\(([^)]+)\)/)
      if (!m) return null
      const parts = m[1].split(',').map((x) => parseFloat(x.trim()))
      return parts.length === 4 ? parts[3] : 1
    }
    return { checked: !!row.querySelector('input[type=checkbox]:checked'), frozenAlpha: alphaOf(frozen), frozenText: (frozen.innerText || '').replace(/\s+/g, ' ').slice(0, 20) }
  })
  const before = await readAlpha()
  const box = pg.locator('tbody tr').first().locator('input[type=checkbox]').first()
  if (await box.count()) { await box.check({ timeout: 6000 }).catch(() => {}); await pg.waitForTimeout(1500) }
  const after = await readAlpha()
  rep('冻结列选中态不透明', after.frozenAlpha === 1, `未选中 alpha=${before.frozenAlpha} ⇒ 勾选后 checked=${after.checked} alpha=${after.frozenAlpha}（须为 1；0.4 即半透明穿透）`)
  await pg.screenshot({ path: OUT + 'S30-frozen-col-selected.png' })
  await c.close()
}

// ⚠️ 文件名必须**按阶段区分**（PHASE 环境变量）：写死一个名字时，下一次运行会**静默覆盖**上一次的读数
//    ——本次实测把已提交的「修前红基线」覆盖掉了（还得从 git 历史 git show <commit>:<path> 捞回来）。
//    用法：PHASE=red-baseline node run-findings-6713-6717.mjs / PHASE=after-6715 ...
const PHASE = process.env.PHASE || 'latest'
const OUT_FILE = OUT + `S12-${PHASE}.json`
writeFileSync(OUT_FILE, JSON.stringify({ when: new Date().toISOString(), phase: PHASE, fails }, null, 2))
console.log(`\n${fails.length ? '🔴 红项 ' + fails.length + ' 条' : '✅ 全绿'}（读数落盘：evidence/S12-${PHASE}.json）`)
await browser.close()
process.exit(fails.length ? 1 : 0)
