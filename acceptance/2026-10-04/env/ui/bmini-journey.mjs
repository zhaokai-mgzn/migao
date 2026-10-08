// bmini 真实 UI 旅程（UA 层）· 2026-10-04
// 走**真实表单**：管理员登录 tab → 手机号 + 获取验证码 → 提交 → 首屏 → 数据页 → 我的页。
// 不注入 token、不改 localStorage；只点用户能点的东西。
// 用法：OUT_DIR=acceptance/2026-10-04/env/ui ADMIN_PHONE=13800138000 SMS_CODE=123456 \
//       node acceptance/2026-10-04/env/ui/bmini-journey.mjs
import { chromium } from '/Users/guangzhen.zk/ai native/migao/tests/node_modules/playwright/index.mjs'
import { writeFileSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
const OUT = process.env.OUT_DIR || 'acceptance/2026-10-04/env/ui'
const SHOTS = join(OUT, 'shots'); mkdirSync(SHOTS, { recursive: true })
const PHONE = process.env.ADMIN_PHONE || '13800138000', CODE = process.env.SMS_CODE || '123456'
const rec = { at: new Date().toLocaleString('sv-SE', { timeZone: 'Asia/Shanghai' }) + ' +08', url: 'https://app.migaozn.com/b/', steps: [], consoleErrors: [], apiCalls: [] }
const step = (id, name, expect, actual, verdict, ev) => { rec.steps.push({ id, name, expect, actual, verdict, evidence: ev }); console.log(`${verdict === 'pass' ? '✅' : verdict === 'skip' ? '⏭️' : '❌'} ${id} ${name}\n    期望: ${expect}\n    实测: ${String(actual).slice(0, 220)}`) }
const snap = (pg) => pg.evaluate(() => ({ href: location.href, text: (document.body.innerText || '').replace(/\n{2,}/g, '\n').slice(0, 600) }))
const b = await chromium.launch(); const pg = await b.newPage({ viewport: { width: 412, height: 915 } })
pg.on('console', m => { if (m.type() === 'error') rec.consoleErrors.push(m.text().slice(0, 150)) })
pg.on('response', r => { if (/sms\/(send|login)/.test(r.url())) rec.apiCalls.push({ path: r.url().replace('https://app.migaozn.com', ''), method: r.request().method(), status: r.status() }) })
try {
  await pg.goto(rec.url, { waitUntil: 'networkidle', timeout: 60000 }); await pg.waitForTimeout(4500)
  const s1 = await snap(pg); await pg.screenshot({ path: join(SHOTS, 'bmini-U1-login.png') })
  step('U1', '工人端小程序登录页渲染', '路由含 auth/login，且管理员 tab 可切（表单变手机号/验证码）',
    `href=${s1.href}`, /auth\/login/.test(s1.href) ? 'pass' : 'fail', ['shots/bmini-U1-login.png'])

  await pg.getByText('管理员登录', { exact: true }).last().click({ timeout: 5000 }); await pg.waitForTimeout(1200)
  const ins = await pg.locator('input').all(); const phs = []
  for (const i of ins) phs.push(await i.getAttribute('placeholder'))
  step('U2', '切「管理员登录」tab', '表单形态变为「手机号 / 验证码」', `inputs=${JSON.stringify(phs)}`,
    phs.some(p => /手机号/.test(p || '')) && phs.some(p => /验证码/.test(p || '')) ? 'pass' : 'fail', [])

  await pg.locator('input').nth(0).fill(PHONE)
  // 真实用户行为：若被限流（上一轮/刚发过 ⇒ 4xx），等过窗口重试一次；UI 必须给出**可见**反馈（倒计时或限流文案）
  const sendOnce = async () => {
    rec.apiCalls.length = 0
    await pg.getByText('获取验证码', { exact: true }).last().click({ timeout: 5000 }); await pg.waitForTimeout(3000)
    const s = await snap(pg)
    return { status: rec.apiCalls.filter(c => /send/.test(c.path)).map(c => c.status).pop(), text: s.text }
  }
  let r3 = await sendOnce()
  if (!/后重发/.test(r3.text) && r3.status !== 200) { await pg.waitForTimeout(65000); r3 = await sendOnce() }  // 过限流窗口
  const countdown = /(\d+)\s*s\s*后重发|后重发/.test(r3.text)
  const limiterText = (r3.text.match(/[^\n]*(限流|频繁|稍后|已发送|只能)[^\n]*/) || [''])[0].trim()
  const visibleFeedback = countdown || !!limiterText
  step('U3', '点「获取验证码」并观察真实反馈（限流则等窗口重试一次）',
    'UI 给出可见反馈（倒计时「Ns 后重发」或明确限流文案）；`POST /api/auth/sms/send` 记原始状态码',
    `send 状态码=${r3.status}；倒计时=${countdown}；限流文案=${JSON.stringify(limiterText)}`,
    visibleFeedback ? 'pass' : 'fail', ['shots/bmini-U1-login.png', `consoleErrors=${JSON.stringify(rec.consoleErrors)}`])

  await pg.locator('input').nth(1).fill(CODE); await pg.waitForTimeout(400)
  await pg.getByText('登录', { exact: true }).last().click({ timeout: 5000 }); await pg.waitForTimeout(8000)
  const s4 = await snap(pg); await pg.screenshot({ path: join(SHOTS, 'bmini-U4-home.png') })
  const loginOk = /chat|dashboard|profile/.test(s4.href) && !/auth\/login/.test(s4.href) && rec.apiCalls.some(c => /login/.test(c.path) && c.status === 200)
  step('U4', '管理员登录成功并落到首屏（真实旅程的 UA 判据）', '离开登录页 + `POST /api/auth/sms/login` = 200 + 首屏显示租户身份',
    `href=${s4.href}；text=${JSON.stringify(s4.text.slice(0, 120))}`, loginOk ? 'pass' : 'fail', ['shots/bmini-U4-home.png'])

  if (loginOk) {
    await pg.getByText('数据', { exact: true }).last().click({ timeout: 5000 }); await pg.waitForTimeout(4500)
    const s5 = await snap(pg); await pg.screenshot({ path: join(SHOTS, 'bmini-U5-dashboard.png') })
    // ⚠️ 判据侧修正：首版断言写 `/data/`，而真实路由是 `#/pages/dashboard/index` ⇒ **假红**（判据错，不是产品错）
    const dashOk = /dashboard/.test(s5.href) && /概览|今日|待处理/.test(s5.text)
    step('U5', '进入「数据」页并渲染真实业务读数', '路由含 dashboard 且页面含「概览/今日/待处理」等真实内容（首版断言误写 /data/ ⇒ 假红，已改）',
      `href=${s5.href}；text=${JSON.stringify(s5.text.slice(0, 160))}`, dashOk ? 'pass' : 'fail', ['shots/bmini-U5-dashboard.png'])

    await pg.getByText('我的', { exact: true }).last().click({ timeout: 5000 }); await pg.waitForTimeout(4000)
    const s6 = await snap(pg); await pg.screenshot({ path: join(SHOTS, 'bmini-U6-profile.png') })
    const mineOk = /profile/.test(s6.href) && !/请先登录/.test(s6.text) && /企业管理员|米高测试/.test(s6.text)
    step('U6', '「我的」页显示已登录身份与功能入口', '不再显示「请先登录」，且出现账号身份与企业名',
      `href=${s6.href}；text=${JSON.stringify(s6.text.slice(0, 200))}`, mineOk ? 'pass' : 'fail', ['shots/bmini-U6-profile.png'])
  }
} catch (e) { step('U0', '旅程未抛异常', '无异常', String(e.message || e).slice(0, 200), 'fail', []) }
finally {
  rec.counts = rec.steps.reduce((a, s) => { a[s.verdict] = (a[s.verdict] || 0) + 1; return a }, {})
  rec.consoleErrorsTotal = rec.consoleErrors.length
  writeFileSync(join(OUT, 'bmini-journey.json'), JSON.stringify(rec, null, 2))
  console.log(`\n汇总: ${JSON.stringify(rec.counts)} · console 错误=${rec.consoleErrors.length} · API=${JSON.stringify(rec.apiCalls)}`)
  console.log(`→ ${OUT}/bmini-journey.json`)
  await b.close()
}
