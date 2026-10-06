// UI 原语：真浏览器 + 真实登录 + 稳定帧证据（adapts migao-acceptance v1.4「证据层」与 dev-flow §15.7）
import { join } from 'node:path'
import { mkdirSync } from 'node:fs'
import { chromium, OUT, WEB, SMS_CODE } from './lib.mjs'

const DENIED_MARK = '无权访问该页面'

export async function launch() {
  return chromium.launch({ headless: true })
}

export async function newPage(browser) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const page = await ctx.newPage()
  const errors = []
  page.on('console', (m) => { if (m.type() === 'error') errors.push({ kind: 'console', text: m.text().slice(0, 300) }) })
  page.on('pageerror', (e) => errors.push({ kind: 'pageerror', text: String(e).slice(0, 300) }))
  page._a06errors = errors
  return { ctx, page, errors }
}

export function drainErrors(page) {
  const e = page._a06errors || []
  page._a06errors = []
  return e
}

/** 员工登录（「员工登录」页签：用户名@企业编码 + 密码）。#6009：先等表单真渲染再操作。 */
export async function loginEmployeeUi(page, identifier, password) {
  await page.goto(WEB + '/login', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForSelector('#identifier', { timeout: 60000 })
  await page.fill('#identifier', identifier)
  await page.fill('#password', password)
  await page.getByRole('button', { name: /登\s*录/ }).last().click()
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60000 })
  return page.url()
}

/** 管理员登录（「管理员登录」页签：手机号 + 短信万能码）。 */
export async function loginAdminUi(page, phone, code = SMS_CODE) {
  await page.goto(WEB + '/login', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.getByRole('tab', { name: /管理员登录/ }).click()
  await page.waitForSelector('#phone', { timeout: 60000 })
  await page.fill('#phone', phone)
  await page.fill('#code', code)
  await page.getByRole('button', { name: /登\s*录/ }).last().click()
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60000 })
  return page.url()
}

/**
 * 侧边栏实际渲染项（DOM 真值，不是配置）。
 *
 * 🔴 假红修正（本会话实测，v1 → v2）：v1 直接查 `nav a[href]`，而侧边栏是**分组折叠**的
 * （`Sidebar.tsx` 的 `expandedGroups` 默认只展开当前路由所在组）⇒ v1 在 7 个岗位上一律只读到
 * 3~4 项、把 22 项菜单判成「缺 18 项」。那是**判据缺陷**，不是产品缺陷。
 * 修正 = 先按 `data-testid="sidebar-group-toggle-*"` 把**所有**组展开（幂等：已展开的不动）再采。
 * 红证 = `out/p2-roles-ui.v1-false-red.json`（同一份 DOM，v1 判 fail / v2 判 pass）。
 */
export async function expandAllGroups(page) {
  const toggles = await page.$$('[data-testid^="sidebar-group-toggle-"]')
  let clicked = 0
  for (const t of toggles) {
    const expanded = await t.getAttribute('aria-expanded')
    if (expanded === 'false') { await t.click().catch(() => {}); clicked++ }
  }
  if (clicked) await page.waitForTimeout(400)
  return { groups: toggles.length, clicked }
}

export async function sidebarLinks(page) {
  await expandAllGroups(page)
  return page.evaluate(() => {
    const container = document.querySelector('aside') || document.querySelector('nav') || document.body
    return Array.from(container.querySelectorAll('a[href]'))
      .map((a) => ({ href: a.getAttribute('href'), text: (a.textContent || '').trim() }))
      .filter((x) => x.href && x.href.startsWith('/') && !x.href.startsWith('//'))
  })
}

export async function bodyText(page) {
  return page.evaluate(() => document.body?.innerText || '')
}

/** 稳定帧：连续两次读到的文本一致才算稳定（migao-acceptance v1.4「过渡帧」）。 */
export async function stableText(page, { tries = 6, gap = 400 } = {}) {
  let prev = null
  for (let i = 0; i < tries; i++) {
    const t = await bodyText(page)
    if (prev !== null && t === prev) return { text: t, stable: true, tries: i + 1 }
    prev = t
    await page.waitForTimeout(gap)
  }
  return { text: prev || '', stable: false, tries }
}

export async function shot(page, name) {
  const dir = join(OUT, 'shots')
  mkdirSync(dir, { recursive: true })
  const p = join(dir, `${name}.png`)
  try { await page.screenshot({ path: p, fullPage: false }) } catch { /* 忽略 */ }
  return p
}

/** 打开一个页面并采证：403 标记 / 文本长度 / 稳定帧 / 截图 / 本轮 console 错误。 */
export async function visit(page, path, { name, shotIt = true, settle = 1200, maxWait = 20000 } = {}) {
  const before = Date.now()
  let httpError = null
  try {
    await page.goto(WEB + path, { waitUntil: 'domcontentloaded', timeout: 60000 })
  } catch (e) {
    httpError = String(e).slice(0, 200)
  }
  await page.waitForTimeout(settle)
  // 🔴 假绿修正（本会话实测，v1 → v2）：「稳定帧」会稳定在**加载态**上（spinner 文案是静态的）。
  // v1 因此把 `/orders` 的加载中页面记成 pass。修正 = 轮询到**非加载态**再采（超时则如实记为 loading）。
  let text = '', stable = false, tries = 0
  const t0 = Date.now()
  while (Date.now() - t0 < maxWait) {
    const s = await stableText(page)
    text = s.text; stable = s.stable; tries += s.tries
    if (stable && !/加载中|正在加载|Loading/i.test(text)) break
  }
  const loading = /加载中|正在加载|Loading/i.test(text)
  const denied = text.includes(DENIED_MARK)
  const errs = drainErrors(page)
  const rec = {
    path,
    url: page.url(),
    denied,
    loading,
    textLen: text.length,
    stable,
    tries,
    ms: Date.now() - before,
    errors: errs,
    textHead: text.slice(0, 400),
  }
  if (httpError) rec.httpError = httpError
  // 🔴 截图必须 await（v1 漏了 await ⇒ JSON 里 `shot:{}`，且截图落到**下一页**的加载态上）
  if (shotIt) rec.shot = await shot(page, name || path.replace(/[^\w]+/g, '_') || 'root')
  return rec
}

export const DENIED = DENIED_MARK

/** 打开页面并等到「非加载态」的稳定帧；返回文本。写面旅程的统一起手。 */
export async function gotoLoaded(page, path, { settle = 1500, maxWait = 25000 } = {}) {
  await page.goto(WEB + path, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(settle)
  let text = ''
  const t0 = Date.now()
  while (Date.now() - t0 < maxWait) {
    const s = await stableText(page)
    text = s.text
    if (s.stable && !/加载中|正在加载|Loading/i.test(text)) break
    await page.waitForTimeout(600)
  }
  return { text, loading: /加载中|正在加载|Loading/i.test(text) }
}
