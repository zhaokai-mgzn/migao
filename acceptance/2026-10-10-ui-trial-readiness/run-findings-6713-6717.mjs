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
for (const path of ['/chat', '/employees', '/notifications', '/products', '/shipments']) {
  await p1.route('**/api/admin/**', INJ)
  await p1.goto(BASE + path, { waitUntil: 'domcontentloaded' })
  await p1.waitForTimeout(6000)
  const m = await probe(p1)
  const hasSurface = m.anchors.length > 0 || m.failWords >= 2
  rep('读失败⇄空态', hasSurface && m.empty.length === 0, `${path} 空态=${JSON.stringify(m.empty)} 零值=${JSON.stringify(m.zero)} 失败词=${m.failWords} 锚点=${m.anchors.slice(0, 2).join(',') || '无'}`)
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

writeFileSync(OUT + 'S12-findings-6713-6717.json', JSON.stringify({ when: new Date().toISOString(), fails }, null, 2))
console.log(`\n${fails.length ? '🔴 红项 ' + fails.length + ' 条' : '✅ 全绿'}`)
await browser.close()
process.exit(fails.length ? 1 : 0)
